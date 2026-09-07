import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { ArrowUpRight, X } from 'lucide-react'
import { api, ended, Event, Session, states, Task } from './api'
import { StatusBadge } from './components/StatusBadge'
import { TaskResults } from './TaskResults'

interface Props {
  task: Task
  platformName: string
  session?: Session
  busy: boolean
  onClose: () => void
  onOpen: (task: Task) => void
  onRefresh: () => void
  onControl: (action: string, id: string) => void
  onError: (message: string, opener?: HTMLElement) => void
}

// Only mounted for an explicitly inspected task. Its logs never change the
// workbench's active task, browser session, configuration or log filters.
export function TaskDetailsDrawer({ task, platformName, session, busy, onClose, onOpen, onRefresh, onControl, onError }: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const logEnd = useRef<HTMLDivElement>(null)
  const [events, setEvents] = useState<Event[]>([])
  const [clearAt, setClearAt] = useState(0)
  const [errorsOnly, setErrorsOnly] = useState(false)
  const [logError, setLogError] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [view, setView] = useState('results')

  useLayoutEffect(() => {
    const element = dialog.current!
    element.showModal()
    return () => element.close()
  }, [])

  useEffect(() => {
    let stopped = false
    let after = 0
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const rows = await api<Event[]>(`/tasks/${task.id}/events?after=${after}`)
        if (stopped) return
        if (rows.length) {
          after = rows[rows.length - 1].seq
          setEvents(previous => [...previous, ...rows])
        }
        setLoaded(true)
        setLogError(false)
      } catch { if (!stopped) setLogError(true) }
      if (!stopped) timer = setTimeout(poll, 2000)
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [task.id])

  const visibleEvents = events.filter(event => event.seq > clearAt && (!errorsOnly || event.payload.level === 'error' || event.type === 'failure'))
  return <dialog ref={dialog} className="wb-task-drawer" aria-labelledby="task-detail-title" onCancel={event => { event.preventDefault(); onClose() }} onKeyDown={event => {
    if (event.key !== 'Tab') return
    const buttons = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), summary, [tabindex="0"]')].filter(element => element.getClientRects().length > 0)
    const first = buttons[0], last = buttons[buttons.length - 1]
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
  }} onClick={event => {
    if (event.target !== event.currentTarget) return
    const rect = event.currentTarget.getBoundingClientRect()
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose()
  }}>
    <header className="wb-task-drawer-heading">
      <div><h2 id="task-detail-title">任务详情</h2><p>{platformName} · {task.config.target || '媒体下载任务'}</p></div>
      <button autoFocus aria-label="关闭任务详情" onClick={onClose}><X size={19} /></button>
    </header>
    <div className="wb-task-detail-toolbar"><StatusBadge state={task.state} /><span>文件完成 {task.counts.files_succeeded} · 失败 {task.counts.files_failed}</span>
      {task.state === 'running' && <button disabled={busy} onClick={() => onControl('pause', task.id)}>暂停</button>}
      {['paused', 'waiting_login'].includes(task.state) && <button disabled={busy} onClick={() => onControl('resume', task.id)}>继续</button>}
      {['failed', 'partial', 'interrupted'].includes(task.state) && <button disabled={busy} onClick={() => onControl('retry', task.id)}>重试失败项</button>}
      {!ended.has(task.state) && <button disabled={busy || task.state === 'cancelling'} onClick={() => onControl('cancel', task.id)}>取消任务</button>}
    </div>
    <div className="wb-tabs wb-task-detail-tabs" role="tablist" aria-label="任务详情分类">{[['results', '文件与结果'], ['info', '基本信息'], ['logs', '运行日志']].map(([id, title]) => <button key={id} id={`task-detail-tab-${id}`} role="tab" aria-selected={view === id} aria-controls={`task-detail-panel-${id}`} onClick={() => setView(id)}>{title}</button>)}</div>
    <div id="task-detail-panel-results" role="tabpanel" aria-labelledby="task-detail-tab-results" className="wb-task-results-panel" hidden={view !== 'results'}>
      <TaskResults task={task} session={session} busy={busy} onRefresh={onRefresh} onError={onError} />
    </div>
    <div id="task-detail-panel-info" role="tabpanel" aria-labelledby="task-detail-tab-info" className="wb-task-drawer-body" hidden={view !== 'info'}>
      <section aria-label="任务基本信息"><h3>基本信息</h3><dl className="wb-detail-grid">
        <dt>任务目标</dt><dd>{task.config.target || '媒体下载任务'}</dd>
        <dt>任务状态</dt><dd><StatusBadge state={task.state} /></dd>
        <dt>平台</dt><dd>{platformName}</dd><dt>导出格式</dt><dd>{task.config.output.toUpperCase()}</dd>
        <dt>内容 / 上限</dt><dd>{task.counts.content} / {task.config.max_items}</dd>
        <dt>文件 / 上限</dt><dd>{task.counts.files_succeeded} / {task.config.max_downloads}</dd>
        <dt>评论</dt><dd>{task.counts.comments}</dd>
        <dt>创建时间</dt><dd>{new Date(task.created * 1000).toLocaleString('zh-CN', { hour12: false })}</dd>
      </dl>{task.error && <p className="wb-detail-error">{task.error}</p>}</section>
    </div>
    <div id="task-detail-panel-logs" role="tabpanel" aria-labelledby="task-detail-tab-logs" className="wb-task-drawer-body" hidden={view !== 'logs'}>
      <section className="wb-task-drawer-logs" aria-label="所选任务日志">
        <h3>运行日志</h3>
        <div className="wb-logs">
          <div className="wb-panel-tools"><button onClick={() => setClearAt(events[events.length - 1]?.seq || 0)}>清除显示</button><button onClick={() => { setClearAt(0); setErrorsOnly(false) }}>恢复历史</button><button aria-pressed={errorsOnly} onClick={() => { setErrorsOnly(!errorsOnly); setClearAt(0) }}>仅看错误</button><button onClick={() => logEnd.current?.scrollIntoView({ block: 'nearest' })}>最新</button></div>
          {logError && <p className="wb-detail-error" role="status">日志暂时无法加载，正在重试。</p>}
          <div className="wb-log-scroll" role="log" aria-label="详情运行日志">
            {visibleEvents.map(event => <div key={event.seq} className={event.payload.level === 'error' || event.type === 'failure' ? 'error' : ''}><time>{new Date(event.created * 1000).toLocaleTimeString()}</time><span>{event.payload.message || event.payload.error || states[event.payload.state || ''] || event.payload.phase || event.payload.path || event.type}</span></div>)}
            {!visibleEvents.length && <p>{!loaded ? '正在加载日志…' : errorsOnly ? '没有匹配的错误日志。' : '暂无可显示日志；清除显示不会删除历史记录。'}</p>}
            <div ref={logEnd} />
          </div>
        </div>
      </section>
    </div>
    <footer className="wb-task-drawer-footer"><button onClick={() => onOpen(task)}><ArrowUpRight size={16} />前往工作台预览</button><button className="wb-primary" onClick={onClose}>完成</button></footer>
  </dialog>
}
