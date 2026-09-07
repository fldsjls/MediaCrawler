import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { LayoutDashboard, ListTodo, Database, Settings, Info, PanelLeftClose, PanelLeftOpen, Menu, X } from 'lucide-react'
import { api, BrowserSettings, Config, ended, Event, Platform, Resource, Results, saved, Session, states, Task, wsUrl } from './api'
import { ConfigurationPanel } from './ConfigurationPanel'
import { PlatformType } from './PlatformManager'
import { AuthorFooter } from '@/components/layout/AuthorFooter'
import { BrowserPanel } from './BrowserPanel'
import { ResultsPanel } from './ResultsPanel'
import { Workspace } from './Workspace'
import { SettingsCenter } from './SettingsCenter'
import './workbench.css'

const initial: Config = { platform: 'bili', mode: 'detail', target: '', max_items: 5, max_downloads: 5, max_comments: 20, comments: true, subcomments: false, download_video: false, download_images: false, operation: 'collect', output: 'jsonl', login: 'qrcode', cookies: '', start: 1, wait_ms: 5000, selector: '' }
const empty: Results = { records: [], files: [], exports: [] }
const navigation = ['工作台', '任务中心', '采集结果', '设置', '关于']
const navIcons = [LayoutDashboard, ListTodo, Database, Settings, Info]

export function Workbench({ onConnectionChange }: { onConnectionChange?: (state: 'connecting' | 'connected' | 'disconnected') => void }) {
  const [section, setSection] = useState('工作台')
  const [drawer, setDrawer] = useState(false)
  const [navCollapsed, setNavCollapsed] = useState(() => saved('mc.workspace.navCollapsed', false))
  const [platformTypes, setPlatformTypes] = useState<PlatformType[]>([])
  const [category, setCategory] = useState('all')
  const [resources, setResources] = useState<Resource[]>([])
  const [resourceStatus, setResourceStatus] = useState('')
  const [platforms, setPlatforms] = useState<Platform[]>([])
  const [config, setConfig] = useState<Config>(() => ({ ...initial, ...saved('mc.workspace.config', initial), cookies: '', session_id: undefined }))
  const [tasks, setTasks] = useState<Task[]>([])
  const [sessions, setSessions] = useState<Session[]>([])
  const [taskId, setTaskId] = useState<string | undefined>(() => saved('mc.workspace.task', undefined))
  const [previewId, setPreviewId] = useState<string>()
  const [events, setEvents] = useState<Event[]>([])
  const [clearAt, setClearAt] = useState(0)
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [results, setResults] = useState<Results>(empty)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [offline, setOffline] = useState(false)
  const [browserVisible, setBrowserVisible] = useState(true)
  const [channel, setChannel] = useState(() => saved('mc.workspace.channel', 'chromium'))
  const [layoutRevision, setLayoutRevision] = useState(0)
  const dialog = useRef<HTMLDialogElement>(null)
  const errorReturnFocus = useRef<HTMLElement | null>(null)
  const logEnd = useRef<HTMLDivElement>(null)
  const nav = useRef<HTMLElement>(null)
  const menuButton = useRef<HTMLButtonElement>(null)
  const platform = platforms.find(p => p.id === config.platform)
  const task = tasks.find(t => t.id === taskId)
  const currentSession = sessions.find(s => s.id === (previewId || task?.session_id) && s.platform === config.platform)
  const loadPlatforms = useCallback(async () => {
    const values = (await api<Platform[]>('/platforms?include_disabled=true')).filter(p => p.id !== 'generic').map(p => ({ ...p, name: p.id === 'meishiwang' ? '美石建工' : p.name }))
    setPlatforms(values)
    setConfig(old => old.platform === 'generic' ? { ...initial } : old)
  }, [])
  useEffect(() => { localStorage.setItem('mc.workspace.navCollapsed', JSON.stringify(navCollapsed)) }, [navCollapsed])
  useEffect(() => { localStorage.removeItem('mc.workspace.configCollapsed') }, [])
  useEffect(() => {
    if (!drawer) return
    nav.current?.querySelector<HTMLButtonElement>('button[aria-current]')?.focus()
    const keydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); setDrawer(false) }
      if (event.key === 'Tab') { const buttons = [...(nav.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || [])].filter(b => b.getClientRects().length); const first = buttons[0], last = buttons[buttons.length - 1]; if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() } else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() } }
    }
    document.addEventListener('keydown', keydown)
    return () => { document.removeEventListener('keydown', keydown); menuButton.current?.focus() }
  }, [drawer])
  useEffect(() => {
    setResources([])
    const id = currentSession?.id, token = currentSession?.token
    if (!id || !token) { setResourceStatus('尚未建立网站会话'); return }
    let stopped = false, socket: WebSocket | undefined, timer: ReturnType<typeof setTimeout>
    let after = 0
    const connect = async () => {
      try {
        const data = await api<{ resources: Resource[]; seq: number }>(`/browser-sessions/${id}/resources`)
        if (stopped) return
        setResources(data.resources); after = data.seq
        socket = new WebSocket(wsUrl(`/browser-sessions/${id}/resources?token=${encodeURIComponent(token)}&after=${after}`))
        socket.onopen = () => setResourceStatus('正在监听网站中的资源')
        socket.onmessage = event => { const data = JSON.parse(event.data); if (data.type === 'resource' && data.resource && data.seq >= after) { after = data.seq; setResources(old => [...old.filter(r => r.id !== data.resource.id), data.resource]) } }
        socket.onclose = () => { if (!stopped) { setResourceStatus('资源列表连接已断开，正在重连'); timer = setTimeout(connect, 2000) } }
      } catch { if (!stopped) { setResourceStatus('资源列表暂不可用，正在重试'); timer = setTimeout(connect, 2500) } }
    }
    void connect()
    return () => { stopped = true; clearTimeout(timer); socket?.close() }
  }, [currentSession?.id, currentSession?.token])
  const refresh = useCallback(async () => {
    const [nextTasks, nextSessions] = await Promise.all([api<Task[]>('/tasks'), api<Session[]>('/browser-sessions')])
    setTasks(nextTasks); setSessions(nextSessions); setOffline(false); onConnectionChange?.('connected')
  }, [onConnectionChange])
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout>
    loadPlatforms().catch(e => setError(e.message))
    api<PlatformType[]>('/platform-types').then(setPlatformTypes).catch(() => {})
    api<BrowserSettings>('/settings/browser').then(value => setChannel(value.default_channel)).catch(() => {})
    const poll = async () => { try { await refresh() } catch { setOffline(true); onConnectionChange?.('disconnected') } if (!stopped) timer = setTimeout(poll, 1200) }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [refresh, loadPlatforms, onConnectionChange])
  useEffect(() => { localStorage.setItem('mc.workspace.config', JSON.stringify({ ...config, cookies: '', session_id: undefined })) }, [config])
  useEffect(() => {
    localStorage.setItem('mc.workspace.task', JSON.stringify(taskId || null))
    setEvents([]); setClearAt(0); setResults(empty)
    if (!taskId) return
    let stopped = false, after = 0
    let socket: WebSocket, timer: ReturnType<typeof setTimeout>
    const connect = () => {
      socket = new WebSocket(wsUrl(`/tasks/${taskId}/events?after=${after}`))
      socket.onmessage = event => { const item: Event = JSON.parse(event.data); after = item.seq; setEvents(old => [...old, item]) }
      socket.onclose = () => { if (!stopped) timer = setTimeout(connect, 1500) }
    }
    connect()
    return () => { stopped = true; clearTimeout(timer); socket?.close() }
  }, [taskId])
  useEffect(() => {
    if (!taskId) return
    let stopped = false, timer: ReturnType<typeof setTimeout>
    const poll = async () => { try { const value = await api<Results>(`/tasks/${taskId}/results`); if (!stopped) setResults(value) } catch { /* Connection state is reported by the shared task poll. */ } if (!stopped) timer = setTimeout(poll, 1800) }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [taskId])
  useEffect(() => {
    if (error) dialog.current?.showModal()
    else { dialog.current?.close(); errorReturnFocus.current?.focus({ preventScroll: true }) }
  }, [error])
  const perform = async (operation: () => Promise<unknown>) => { if (busy) return; errorReturnFocus.current = document.activeElement as HTMLElement; setBusy(true); try { await operation(); await refresh() } catch (e) { setError(String(e instanceof Error ? e.message : e)) } finally { setBusy(false) } }
  const openWebsite = (external = false) => void perform(async () => {
    if (!platform) return
    const existing = sessions.find(s => s.platform === config.platform && !s.task_id)
    if (existing && !external) { setPreviewId(existing.id); return }
    if (existing && external) await api(`/browser-sessions/${existing.id}`, undefined, 'DELETE')
    const url = config.mode !== 'search' && /^https?:\/\//.test(config.target) ? config.target.split(',')[0].trim() : platform.url
    if (!url) throw new Error('请先填写网页地址')
    const session = await api<Session>('/browser-sessions', { platform: config.platform, url, channel, external })
    setPreviewId(session.id); setSessions(old => [...old.filter(s => s.id !== existing?.id), session])
  })
  const start = () => void perform(async () => {
    const session = currentSession?.platform === config.platform && (!currentSession.task_id || currentSession.finished) ? currentSession : undefined
    const created = await api<Task>('/tasks', { ...config, media: undefined, operation: 'collect', session_id: session?.id })
    setTaskId(created.id); setPreviewId(session?.id)
    toast.success('任务已加入队列')
  })
  const control = (action: string, id = taskId) => void perform(async () => { if (id) await api(`/tasks/${id}/control`, { action }) })
  const updateSession = (value: Session) => setSessions(old => [...old.filter(s => s.id !== value.id), value])
  const openTask = (value: Task) => { setTaskId(value.id); setPreviewId(value.session_id); setConfig({ ...initial, ...value.config, cookies: '', session_id: undefined }); setSection('工作台') }
  const exportResults = () => void perform(async () => { if (taskId) { await api(`/tasks/${taskId}/export`, {}); setResults(await api(`/tasks/${taskId}/results`)); toast.success('结果已导出') } })
  const downloadResources = (ids: string[]) => void perform(async () => {
    if (!currentSession) throw new Error('请先打开资源所属的网站会话')
    if (task && task.session_id === currentSession.id) await api(`/tasks/${task.id}/downloads`, { session_id: currentSession.id, resource_ids: ids })
    else {
      const created = await api<Task>('/tasks', { ...config, media: undefined, operation: 'download', session_id: currentSession.id, resource_ids: ids, target: currentSession.pages.find(p => p.selected)?.url || config.target || platform?.url })
      setTaskId(created.id)
    }
    toast.success('已提交所选资源，已完成的文件会自动跳过')
  })
  const visibleEvents = events.filter(e => e.seq > clearAt && (!errorsOnly || e.payload.level === 'error' || e.type === 'failure'))
  const logs = <div className="wb-logs"><div className="wb-panel-tools"><span>{task ? `${states[task.state]} · ${task.id.slice(0, 8)}` : '尚未运行'}</span><button onClick={() => setClearAt(events[events.length - 1]?.seq || 0)}>清除显示</button><button onClick={() => { setClearAt(0); setErrorsOnly(false) }}>恢复历史</button><button aria-pressed={errorsOnly} onClick={() => { setErrorsOnly(!errorsOnly); setClearAt(0) }}>定位错误</button><button onClick={() => logEnd.current?.scrollIntoView({ block: 'nearest' })}>最新</button></div><div className="wb-log-scroll" role="log" aria-label="任务运行日志">{visibleEvents.length ? visibleEvents.map(event => <div key={event.seq} className={event.payload.level === 'error' || event.type === 'failure' ? 'error' : ''}><time>{new Date(event.created * 1000).toLocaleTimeString()}</time><span>{event.payload.message || event.payload.error || states[event.payload.state || ''] || event.payload.phase || event.payload.path || event.type}</span></div>) : <p>等待任务事件。日志清除只影响显示，历史记录仍然保留。</p>}<div ref={logEnd} /></div></div>
  const resultResources = [...new Map([...(task?.config.platform === config.platform ? results.resources || [] : []), ...resources].map(r => [r.id, r])).values()]
  const resultPanel = <ResultsPanel results={results} resources={resultResources} sessionId={currentSession?.id} resourceStatus={resourceStatus} busy={busy} onDownload={currentSession ? downloadResources : undefined} taskId={taskId} onExport={exportResults} />
  return <div className={`wb-shell ${navCollapsed ? 'nav-collapsed' : ''}`}>
    <button ref={menuButton} className="wb-menu" aria-expanded={drawer} aria-controls="workspace-navigation" onClick={() => setDrawer(!drawer)}><Menu size={18} />{section}</button>
    {drawer && <button className="wb-drawer-backdrop" aria-label="关闭导航" onClick={() => setDrawer(false)} />}
    <nav ref={nav} id="workspace-navigation" className={`wb-nav ${drawer ? 'open' : ''}`} aria-label="主导航"><div className="wb-nav-heading"><span>工作空间</span><button className="wb-nav-collapse" aria-label={navCollapsed ? '展开导航' : '折叠导航'} aria-expanded={!navCollapsed} onClick={() => setNavCollapsed(!navCollapsed)}>{navCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}</button><button className="wb-nav-close" aria-label="关闭导航" onClick={() => setDrawer(false)}><X size={18} /></button></div>{navigation.map((title, i) => { const Icon = navIcons[i];return <button key={title} title={title} aria-label={title} aria-current={section === title ? 'page' : undefined} onClick={() => { setSection(title); setDrawer(false) }}><Icon size={18} strokeWidth={1.7} /><span>{title}</span></button> })}<small>本机工作区</small></nav>
    <main className="wb-main">
      {offline && <div className="wb-offline" role="status">与服务的连接已中断，正在重连。任务状态以重新连接后的记录为准。</div>}
      <div className="wb-workbench" style={{ display: section === '工作台' ? 'grid' : 'none' }}>
        <ConfigurationPanel config={config} setConfig={setConfig} platforms={platforms.filter(p => (p.enabled !== false || p.id === config.platform) && (category === 'all' || p.category === category || p.id === config.platform))} platform={platform} task={task} busy={busy} onPlatform={() => setPreviewId(undefined)} onOpen={() => openWebsite()} onStart={start} onControl={control} onError={setError} category={category} types={platformTypes} onCategory={setCategory} />
        <Workspace refreshKey={layoutRevision} onReset={() => { setNavCollapsed(false) }} onVisibility={setBrowserVisible} browser={<BrowserPanel recentTasks={tasks.slice(0, 3)} onOpenTask={openTask} session={currentSession} visible={browserVisible && section === '工作台'} target={config.target || platform?.url || ''} onOpen={() => openWebsite()} onSession={updateSession} onError={setError} />} logs={logs} results={resultPanel} />
      </div>
      {section === '任务中心' && <section className="wb-page"><span className="wb-eyebrow">任务中心</span><h1>每一次采集，都有记录</h1><p>单任务执行，其余排队；应用中断后不会自动重跑。</p><div className="wb-task-list">{tasks.length === 0 && <p>还没有任务。前往工作台创建第一个任务。</p>}{tasks.map(t => <article key={t.id}><div><span className={`wb-state ${t.state}`}>{states[t.state]}</span><strong>{platforms.find(p => p.id === t.config.platform)?.name || t.config.platform}</strong><small>{new Date(t.created * 1000).toLocaleString()}</small></div><p>{t.config.target}</p><small>内容 {t.counts.content} · 文件成功 {t.counts.files_succeeded} / 失败 {t.counts.files_failed}</small><div className="wb-task-actions"><button onClick={() => openTask(t)}>打开任务</button>{['failed', 'partial', 'interrupted'].includes(t.state) && <button disabled={busy} onClick={() => control('retry', t.id)}>重试失败项</button>}{!ended.has(t.state) && <button disabled={busy} onClick={() => control('cancel', t.id)}>取消任务</button>}</div></article>)}</div></section>}
      {section === '采集结果' && <section className="wb-page wb-all-results"><h1>采集结果</h1><label>选择任务<select value={taskId || ''} onChange={e => setTaskId(e.target.value)}><option value="">请选择</option>{tasks.map(t => <option key={t.id} value={t.id}>{t.config.platform} · {t.config.target} · {states[t.state]}</option>)}</select></label>{resultPanel}</section>}
      {section === '设置' && <SettingsCenter sessions={sessions} platform={config.platform} channel={channel} busy={busy} navCollapsed={navCollapsed} onChannel={setChannel} onNavCollapsed={setNavCollapsed} onLayout={() => setLayoutRevision(value => value + 1)} onPlatforms={loadPlatforms} onError={setError} onExternal={() => openWebsite(true)} onCloseSession={id => void perform(async () => { await api(`/browser-sessions/${id}`, undefined, 'DELETE'); if (previewId === id) setPreviewId(undefined) })} />}
      {section === '关于' && <section className="wb-page wb-about"><span className="wb-eyebrow">MediaCrawler</span><h1>统一工作台</h1><p>通用网站工作台。通过网站适配器与功能模板扩展采集能力，公共服务统一管理浏览器、任务、下载和结果。</p><h2>预览与人工操作</h2><p>预览来自任务使用的 Chromium，接管确认后才允许输入。隐藏预览只停止画面传输。打开网站只发现资源；开始任务或手动选择资源后才下载。书籍正文与购物价格采集尚未接入。</p><h2>许可与来源</h2><p>保留 MediaCrawler 的非商业学习许可证。课程模块来自本地 playwright_crawler；来源版本与下载工具说明见项目中的 workers/browser-capture/PROVENANCE.md。</p><a href="https://github.com/NanmiCoder/MediaCrawler" target="_blank" rel="noreferrer">MediaCrawler 上游项目</a><AuthorFooter /></section>}
    </main>
    <dialog ref={dialog} className="wb-error-dialog" onCancel={() => setError('')} onClose={() => setError('')}><h2>需要处理的问题</h2><p>{error}</p><button autoFocus onClick={() => setError('')}>关闭</button></dialog>
  </div>
}
