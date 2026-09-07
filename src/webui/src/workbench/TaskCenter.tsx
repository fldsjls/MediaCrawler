import { useEffect, useState } from 'react'
import { Eye, Pause, Play, Plus, RefreshCw, Search, X } from 'lucide-react'
import { ended, Platform, Session, Task } from './api'
import { StatusBadge } from './components/StatusBadge'
import { TaskDetailsDrawer } from './TaskDetailsDrawer'

interface Props {
  tasks: Task[]; platforms: Platform[]; sessions: Session[]; busy: boolean
  onOpen: (task: Task) => void; onNew: () => void
  onRefresh: () => void; onControl: (action: string, id: string) => void
  onError: (message: string, opener?: HTMLElement) => void
}
const filters = [
  { id: 'all', label: '全部任务', states: [] },
  { id: 'active', label: '运行中', states: ['preparing', 'running', 'waiting_login', 'pausing', 'cancelling'] },
  { id: 'queued', label: '等待中', states: ['queued'] },
  { id: 'paused', label: '已暂停', states: ['paused'] },
  { id: 'done', label: '已完成', states: ['succeeded'] },
  { id: 'failed', label: '需处理', states: ['failed', 'partial', 'interrupted'] },
  { id: 'cancelled', label: '已取消', states: ['cancelled'] },
]
const date = (time: number) => new Date(time * 1000).toLocaleString('zh-CN', { hour12: false })

export function TaskCenter({ tasks, platforms, sessions, busy, onOpen, onNew, onRefresh, onControl, onError }: Props) {
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [platform, setPlatform] = useState('all')
  const [detailId, setDetailId] = useState<string>()
  const group = filters.find(value => value.id === filter)!
  const name = (id: string) => platforms.find(p => p.id === id)?.name || id
  const visible = tasks.filter(task => (filter === 'all' || group.states.includes(task.state))
    && (platform === 'all' || platform === task.config.platform)
    && `${task.config.target} ${name(task.config.platform)} ${task.id}`.toLowerCase().includes(query.toLowerCase()))
  const selected = visible.find(task => task.id === detailId)
  useEffect(() => { if (detailId && !selected) setDetailId(undefined) }, [detailId, selected])
  const showDetails = (task: Task, opener: HTMLElement) => {
    opener.focus()
    setDetailId(task.id)
  }
  return <section className="wb-page wb-task-center" aria-labelledby="task-center-title">
    <div className="wb-page-heading">
      <div><h1 id="task-center-title">任务中心</h1><p>统一管理采集、下载与结果；点击任务查看文件、内容和日志</p></div>
      <div className="wb-heading-actions"><button disabled={busy} onClick={onRefresh}><RefreshCw size={16} />刷新</button><button className="wb-primary" onClick={onNew}><Plus size={16} />新建采集</button></div>
    </div>
    <div className="wb-task-toolbar">
      <div className="wb-filter-tabs" role="group" aria-label="任务状态筛选">{filters.map(item => <button key={item.id} aria-pressed={filter === item.id} onClick={() => setFilter(item.id)}>
        {item.label}<span>{tasks.filter(task => item.id === 'all' || item.states.includes(task.state)).length}</span>
      </button>)}</div>
      <div className="wb-search-tools"><label className="wb-search"><Search size={16} /><input aria-label="搜索任务" placeholder="搜索任务、平台或目标" value={query} onChange={e => setQuery(e.target.value)} /></label>
        <select aria-label="任务平台" value={platform} onChange={e => setPlatform(e.target.value)}><option value="all">全部平台</option>{platforms.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
    </div>
    <div className="wb-table-scroll wb-task-table-wrap">
      <table className="wb-table wb-task-table" aria-label="采集任务">
        <thead><tr><th>任务名称</th><th>平台</th><th>任务状态</th><th>内容 / 上限</th><th>文件 / 上限</th><th>创建时间</th><th>操作</th></tr></thead>
        <tbody>{visible.map(task => <tr key={task.id} data-selected={selected?.id === task.id} onClick={event => showDetails(task, event.currentTarget.querySelector<HTMLButtonElement>('.wb-title-button')!)}>
          <td><button className="wb-title-button" title={task.config.target} aria-haspopup="dialog" onClick={event => { event.stopPropagation(); showDetails(task, event.currentTarget) }}>{task.config.target || '媒体下载任务'}</button></td>
          <td>{name(task.config.platform)}</td>
          <td><div className="wb-task-status"><StatusBadge state={task.state} />{!ended.has(task.state) && task.config.operation !== 'download' && <meter aria-label="内容数量与采集上限" min={0} max={task.config.max_items} value={Math.min(task.counts.content, task.config.max_items)} />}</div></td>
          <td>{task.counts.content} / {task.config.max_items}</td><td>{task.counts.files_succeeded} / {task.config.max_downloads}{task.counts.files_failed > 0 && <small className="wb-detail-error"> · {task.counts.files_failed} 失败</small>}</td>
          <td className="wb-date">{date(task.created)}</td>
          <td><div className="wb-row-actions" onClick={e => e.stopPropagation()}>
            <button onClick={event => showDetails(task, event.currentTarget)} aria-haspopup="dialog" aria-label={`任务详情 ${task.config.target}`}><Eye size={15} />详情</button>
            {task.state === 'running' && <button disabled={busy} onClick={() => onControl('pause', task.id)}><Pause size={15} />暂停</button>}
            {['paused', 'waiting_login'].includes(task.state) && <button disabled={busy} onClick={() => onControl('resume', task.id)}><Play size={15} />继续</button>}
            {['failed', 'partial', 'interrupted'].includes(task.state) && <button disabled={busy} onClick={() => onControl('retry', task.id)}><RefreshCw size={15} />重试</button>}
            {!ended.has(task.state) && <button disabled={busy || task.state === 'cancelling'} onClick={() => onControl('cancel', task.id)}><X size={15} />取消</button>}
          </div></td>
        </tr>)}</tbody>
      </table>
      {!visible.length && <div className="wb-table-empty"><h3>{tasks.length ? '没有匹配的任务' : '还没有采集任务'}</h3><p>{tasks.length ? '尝试其他关键词、平台或任务状态。' : '创建采集后，可以在这里查看进度与结果。'}</p>{!tasks.length && <button onClick={onNew}>新建采集</button>}</div>}
    </div>
    <footer className="wb-page-footer">{visible.length} 个任务{visible.length !== tasks.length && ` / 已加载 ${tasks.length} 个`} · {tasks.filter(t => filters[1].states.includes(t.state)).length} 个运行中<span>单任务执行，其余排队；中断后不会自动重跑</span></footer>
    {selected && <TaskDetailsDrawer key={selected.id} task={selected} platformName={name(selected.config.platform)} session={sessions.find(s => s.id === selected.session_id && s.platform === selected.config.platform && s.task_id === selected.id && !tasks.some(t => t.id !== selected.id && t.session_id === s.id && !ended.has(t.state)))} busy={busy} onClose={() => setDetailId(undefined)} onOpen={onOpen} onRefresh={onRefresh} onControl={onControl} onError={onError} />}
  </section>
}
