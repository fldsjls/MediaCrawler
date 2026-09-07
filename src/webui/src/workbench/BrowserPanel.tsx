import { useEffect, useRef, useState } from 'react'
import { api, PreviewPreference, Session, Task, states, wsUrl } from './api'
import { useBrowserPresentation } from './useBrowserPresentation'

export interface NavigationRequest { sessionId: string; url: string; complete: (error?: string) => void }
interface Props { session?: Session; visible: boolean; target: string; onOpen: () => void; onSession: (session: Session) => void; onError: (message: string) => void; recentTasks?: Task[]; onOpenTask?: (task: Task) => void; navigationRequest?: NavigationRequest }
type ControlMessage = { action: string; [key: string]: unknown }
type WheelInput = { x: number; y: number; dx: number; dy: number }
export function BrowserPanel({ session, visible, target, onOpen, onSession, onError, recentTasks = [], onOpenTask, navigationRequest }: Props) {
  const [controlConnected, setControlConnected] = useState(false)
  const [address, setAddress] = useState('')
  const [retry, setRetry] = useState(0)
  const socket = useRef<WebSocket>()
  const input = useRef<HTMLTextAreaElement>(null)
  const picture = useRef<HTMLImageElement>(null)
  const manual = useRef(false)
  const wheelPending = useRef<WheelInput>()
  const wheelTimer = useRef<ReturnType<typeof setTimeout>>()
  const wheelInFlight = useRef(0)
  const awaiting = useRef<{ action: string; complete?: (error?: string) => void }[]>([])
  const navigation = useRef<{ request: NavigationRequest; started: boolean; settled: boolean; finish: (error?: string) => void }>()
  const sessionSnapshot = useRef('')
  sessionSnapshot.current = JSON.stringify(session)
  const callbacks = useRef({ onSession, onError })
  callbacks.current = { onSession, onError }
  const id = session?.id, token = session?.token
  const selectedUrl = session?.pages.find(p => p.selected)?.url || ''
  const selectedPage = session?.pages.find(p => p.selected)?.id
  const clearWheel = () => {
    clearTimeout(wheelTimer.current)
    wheelTimer.current = undefined
    wheelPending.current = undefined
  }
  const display = useBrowserPresentation(session, visible, () => { manual.current = false; clearWheel(); socket.current?.close() })
  const { frame, connected } = display
  manual.current = Boolean(session?.manual && connected && controlConnected && visible)
  const [changingMode, setChangingMode] = useState(false)
  const changeMode = async (preference: PreviewPreference) => {
    if (!id || !token) return
    clearWheel(); setChangingMode(true)
    try { const value = await api<Session>(`/browser-sessions/${id}/presentation`, { token, preference }, 'PATCH'); callbacks.current.onSession(value); if (display.failure && value.presentation?.mode === 'realtime') display.retry() }
    catch (error) { callbacks.current.onError(error instanceof Error ? error.message : String(error)) }
    finally { setChangingMode(false) }
  }
  const sendRaw = (message: ControlMessage, complete?: (error?: string) => void) => {
    const ws = socket.current
    if (ws?.readyState !== WebSocket.OPEN) return false
    if (['click', 'wheel', 'text', 'key'].includes(message.action)) {
      const current = sessionSnapshot.current ? JSON.parse(sessionSnapshot.current) as Session : undefined
      message = { ...message, page_epoch: current?.page_epoch }
    }
    awaiting.current.push({ action: message.action, complete })
    if (message.action === 'wheel') wheelInFlight.current += 1
    ws.send(JSON.stringify(message))
    return true
  }
  const flushWheel = (force = false) => {
    clearTimeout(wheelTimer.current)
    wheelTimer.current = undefined
    if (!manual.current || socket.current?.readyState !== WebSocket.OPEN) { clearWheel(); return }
    // A slow browser gets one merged pending scroll, rather than an event backlog.
    if (!force && wheelInFlight.current > 0) return
    const value = wheelPending.current
    wheelPending.current = undefined
    if (value && (value.dx || value.dy)) sendRaw({ action: 'wheel', ...value })
  }
  const scheduleWheel = () => {
    if (wheelPending.current && !wheelTimer.current && wheelInFlight.current === 0) wheelTimer.current = setTimeout(() => flushWheel(), 40)
  }
  const send = (message: ControlMessage) => {
    if (['select', 'navigate', 'reload', 'claim'].includes(message.action)) clearWheel()
    else flushWheel(true) // Keep scroll -> click/text/key order on the control connection.
    if (message.action === 'select') { manual.current = false; display.invalidate() }
    sendRaw(message)
  }
  useEffect(() => { clearWheel(); return clearWheel }, [id, selectedPage, selectedUrl, session?.manual, connected, controlConnected, visible])
  useEffect(() => setAddress(selectedUrl), [selectedUrl])
  useEffect(() => {
    if (!id || !token) return
    const ws = new WebSocket(wsUrl(`/browser-sessions/${id}/control?token=${encodeURIComponent(token)}`))
    socket.current = ws
    ws.onopen = () => setControlConnected(true)
    ws.onclose = () => { manual.current = false; clearWheel(); navigation.current?.finish('控制连接已断开，请重新连接后打开网站'); awaiting.current = []; wheelInFlight.current = 0; setControlConnected(false) }
    ws.onmessage = event => {
      const message = JSON.parse(event.data)
      let acknowledged: { action: string; complete?: (error?: string) => void } | undefined
      if (message.type === 'ack' || message.type === 'error') {
        acknowledged = awaiting.current.shift()
        if (acknowledged?.action === 'wheel') wheelInFlight.current = Math.max(0, wheelInFlight.current - 1)
      }
      if (message.type === 'error') { clearWheel(); if (acknowledged?.action === 'select') display.retry(); if (!acknowledged?.complete) callbacks.current.onError(message.message) }
      if (message.session) {
        const previous = sessionSnapshot.current ? JSON.parse(sessionSnapshot.current) as Session : undefined
        const beforePage = previous?.pages.find(p => p.selected)
        const afterPage = (message.session as Session).pages.find(p => p.selected)
        if (!message.session.manual) manual.current = false
        if (!message.session.manual || beforePage?.id !== afterPage?.id || beforePage?.url !== afterPage?.url) clearWheel()
        const next = JSON.stringify(message.session)
        if (next !== sessionSnapshot.current) { sessionSnapshot.current = next; callbacks.current.onSession(message.session) }
      }
      acknowledged?.complete?.(message.type === 'error' ? message.message : undefined)
      scheduleWheel()
    }
    return () => { manual.current = false; clearWheel(); if (navigation.current?.started) navigation.current.finish('控制会话已切换，请重新打开网站'); awaiting.current = []; wheelInFlight.current = 0; ws.onclose = null; ws.onmessage = null; ws.close(); socket.current = undefined; setControlConnected(false) }
  }, [id, token, retry])
  useEffect(() => {
    if (!navigationRequest) return
    const job = { request: navigationRequest, started: false, settled: false, finish: (error?: string) => {
      if (job.settled) return
      job.settled = true; clearTimeout(timer); navigationRequest.complete(error)
    } }
    const timer = setTimeout(() => job.finish('打开网站超时，请检查当前页面后重试'), 35000)
    navigation.current = job
    return () => { job.finish('打开网站已取消'); if (navigation.current === job) navigation.current = undefined }
  }, [navigationRequest])
  useEffect(() => {
    const job = navigation.current
    if (!job || job.settled || job.started || job.request.sessionId !== id || !controlConnected || socket.current?.readyState !== WebSocket.OPEN) return
    if (session?.task_id && !session.finished) { job.finish('浏览器正在执行任务，请先在任务中心接管'); return }
    job.started = true; clearWheel()
    const navigate = (error?: string) => {
      if (job.settled) return
      if (error) { job.finish(error); return }
      if (!sendRaw({ action: 'navigate', url: job.request.url }, job.finish)) job.finish('控制连接不可用，请重新连接')
    }
    // Reuse this panel's authenticated control socket and wait for claim/navigation acknowledgements.
    if (session?.manual) navigate()
    else if (!sendRaw({ action: 'claim' }, navigate)) job.finish('控制连接不可用，请重新连接')
  }, [navigationRequest, id, controlConnected, session?.manual, session?.task_id, session?.finished])
  const position = (clientX: number, clientY: number) => {
    const rect = (display.mode === 'realtime' ? display.video.current : picture.current)?.getBoundingClientRect()
    if (!rect) return null
    const scale = Math.min(rect.width / 1280, rect.height / 720)
    const x = (clientX - rect.left - (rect.width - 1280 * scale) / 2) / scale
    const y = (clientY - rect.top - (rect.height - 720 * scale) / 2) / scale
    return x >= 0 && y >= 0 && x <= 1280 && y <= 720 ? { x, y } : null
  }
  useEffect(() => {
    const element: HTMLElement | null = display.mode === 'realtime' ? display.video.current : picture.current
    if (!element) return
    const wheel = (event: WheelEvent) => {
      if (!manual.current) return
      const point = position(event.clientX, event.clientY)
      if (!point) return
      event.preventDefault()
      // DOM_DELTA_LINE is normalized to a conventional 16px line; page deltas
      // use the fixed remote viewport rather than the scaled preview panel.
      const dx = event.deltaX * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 1280 : 1)
      const dy = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 720 : 1)
      if (!Number.isFinite(dx) || !Number.isFinite(dy)) return
      const pending = wheelPending.current
      wheelPending.current = { ...point, dx: Math.max(-3000, Math.min(3000, (pending?.dx || 0) + dx)), dy: Math.max(-3000, Math.min(3000, (pending?.dy || 0) + dy)) }
      scheduleWheel()
    }
    element.addEventListener('wheel', wheel, { passive: false })
    return () => { element.removeEventListener('wheel', wheel); clearWheel() }
  }, [Boolean(frame), display.mode, connected])
  const insert = (element: HTMLTextAreaElement) => {
    if (element.value && manual.current) send({ action: 'text', text: element.value })
    element.value = ''
  }
  if (!session) return <div className="wb-empty"><span className="wb-eyebrow">当前目标</span><p>{target || '先选择平台并填写目标。'}</p><ol className="wb-preview-steps"><li>打开网站并登录</li><li>播放以发现资源</li><li>开始采集或手选下载</li></ol><button onClick={onOpen}>打开网站</button><small>打开网站和播放只发现资源，不会自动下载。</small><small>支持 Chromium / Edge · 预览不会录制保存</small>{recentTasks.length > 0 && onOpenTask && <div className="wb-recent"><strong>近期任务与结果</strong>{recentTasks.map(task => <button key={task.id} onClick={() => onOpenTask(task)} title={task.config.target}><span>{task.config.target}</span><small>{states[task.state]}</small></button>)}</div>}</div>
  return <div className="wb-browser">
    <div className="wb-browser-toolbar">
      <select aria-label="预览页面" value={session.pages.find(p => p.selected)?.id || ''} onChange={e => send({ action: 'select', page_id: e.target.value })}>{session.pages.map((p, i) => <option key={p.id} value={p.id}>{i + 1}. {p.url}</option>)}</select>
      <form onSubmit={e => { e.preventDefault(); send({ action: 'navigate', url: address }) }}><input aria-label="页面地址" value={address} onChange={e => setAddress(e.target.value)} disabled={!session.manual || !controlConnected} /><button disabled={!session.manual || !controlConnected} title="前往地址">前往</button></form>
      <button disabled={!session.manual || !controlConnected} onClick={() => send({ action: 'reload' })}>刷新</button>
      <select aria-label="预览显示模式" value={session.presentation?.preference || 'auto'} disabled={changingMode} onChange={e => void changeMode(e.target.value as PreviewPreference)}><option value="auto">自动</option><option value="realtime">实时交互</option><option value="snapshot">低刷新</option></select>
    </div>
    <div className="wb-preview-status"><span>{session.finished ? '任务已结束 · 保留浏览器供检查' : session.manual ? '人工操作已开放' : '只读观看 · 接口采集时页面可能保持不变'}</span><span>{display.mode === 'realtime' ? '实时画面' : '低刷新画面'} · {connected ? '已连接' : '连接中'}</span></div>
    {display.failure && <div className="wb-preview-fallback" role="status"><span>{display.failure}，已切换为低刷新画面。</span><button onClick={display.retry}>重试实时画面</button></div>}
    <div className="wb-viewport">
      <video ref={display.video} autoPlay muted playsInline aria-label="采集浏览器实时视频" hidden={display.mode !== 'realtime'} onClick={e => { if (!manual.current) return; const point = position(e.clientX, e.clientY); if (point) { send({ action: 'click', ...point }); input.current?.focus({ preventScroll: true }) } }} />
      {frame && <img ref={picture} src={frame} hidden={display.mode !== 'snapshot'} alt="采集浏览器实时画面" draggable={false} onClick={e => { if (!manual.current) return; const point = position(e.clientX, e.clientY); if (point) { send({ action: 'click', ...point }); input.current?.focus({ preventScroll: true }) } }} />}
      {!connected && <p>正在连接浏览器画面…</p>}
      <textarea ref={input} className="wb-remote-input" aria-label="浏览器键盘输入" autoComplete="off" onCompositionEnd={e => insert(e.currentTarget)} onInput={e => { if (!(e.nativeEvent as InputEvent).isComposing) insert(e.currentTarget) }} onPaste={e => { e.preventDefault(); if (manual.current) send({ action: 'text', text: e.clipboardData.getData('text') }) }} onKeyDown={e => {
        if (!manual.current) { e.preventDefault(); return }
        if (e.nativeEvent.isComposing) return
        let key = e.key
        if (e.ctrlKey && ['a', 'z'].includes(key.toLowerCase())) key = `Control+${key.toUpperCase()}`
        if (e.shiftKey && key === 'Tab') key = 'Shift+Tab'
        if (['Enter', 'Tab', 'Shift+Tab', 'Escape', 'Backspace', 'Delete', 'ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown', 'Control+A', 'Control+Z'].includes(key)) { e.preventDefault(); send({ action: 'key', key }) }
      }} />
      {!controlConnected && <div className="wb-disconnected">控制连接已断开；重新连接不会自动继续采集。<button onClick={() => { display.retry(); setRetry(v => v + 1) }}>重新连接</button></div>}
    </div>
    <div className="wb-preview-status"><span>点击画面后可输入中文或粘贴；支持滚轮与常用按键。</span><button onClick={() => send({ action: 'claim' })} disabled={!controlConnected}>接管浏览器</button></div>
  </div>
}
