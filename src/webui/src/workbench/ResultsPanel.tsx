import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { Download, FileText, Search, Upload, Video } from 'lucide-react'
import { Resource, Results, fileUrl } from './api'
import { StatusBadge } from './components/StatusBadge'
import { ResourceTable, bytes, downloadable } from './results/ResourceTable'
import { ExportData } from './results/ExportData'

interface Props { results: Results; taskId?: string; onExport: () => void; resources?: Resource[]; sessionId?: string; busy?: boolean; onDownload?: (ids: string[]) => void; resourceStatus?: string; initialView?: 'videos' | 'files' }
const noResources: Resource[] = []
const videoLabels: Record<string, string> = { none: '无视频', available: '有可用视频', unresolved: '视频待解析' }
const recordVideoStatus = (fields: unknown) => {
  if (!fields || typeof fields !== 'object' || !('video_status' in fields)) return ''
  const status = String(fields.video_status)
  return ` · ${videoLabels[status] || status}`
}
export function ResultsPanel({ results, taskId, onExport, resources = noResources, sessionId, busy = false, onDownload, resourceStatus, initialView = 'videos' }: Props) {
  const [view, setView] = useState<string>(initialView), [query, setQuery] = useState(''), [filter, setFilter] = useState('all'), [selected, setSelected] = useState<string[]>([])
  const [exportOpen, setExportOpen] = useState(false)
  const exportId = useId(), exportButton = useRef<HTMLButtonElement>(null)
  const closeExport = () => { setExportOpen(false); exportButton.current?.focus() }
  useEffect(() => { setExportOpen(false) }, [taskId])
  const failed = results.records.filter(r => r.kind === 'failure')
  const videos = useMemo(() => resources.filter(r => r.kind === 'video'), [resources])
  const filtered = videos.filter(r => (!query || `${r.title} ${r.format || ''} ${r.quality || ''} ${r.page_url || ''}`.toLowerCase().includes(query.toLowerCase())) && (filter === 'all' || filter === 'available' && downloadable(r) || filter === r.state))
  const eligible = filtered.filter(downloadable), selection = selected.filter(id => videos.some(r => r.id === id && downloadable(r)))
  useEffect(() => { setSelected([]) }, [taskId, sessionId])
  const toggle = (id: string) => setSelected(old => old.includes(id) ? old.filter(value => value !== id) : [...old, id])
  const requestDownload = (ids: string[]) => { if (ids.length && onDownload) onDownload(ids) }
  const tabs = [['videos', '视频', videos.length], ['content', '内容', results.records.filter(r => r.kind === 'content').length], ['comments', '评论', results.records.filter(r => r.kind === 'comment').length], ['files', '文件', results.files.length], ['failures', '失败项', failed.length + results.files.filter(f => f.state === 'failed').length]] as const
  const records = results.records.filter(r => view === 'content' ? ['content', 'creator'].includes(r.kind) : r.kind === 'comment')
  const files = results.files.filter(f => view === 'files' || f.state === 'failed')
  return <div className="wb-results" onKeyDown={event => { if (event.key === 'Escape' && exportOpen) { event.preventDefault(); event.stopPropagation(); closeExport() } }}>
    <div className="wb-results-toolbar"><div className="wb-tabs" role="tablist" aria-label="结果分类">{tabs.map(([id, title, count]) => <button key={id} role="tab" aria-selected={view === id} onClick={() => setView(id)}>{title}<span>{count}</span></button>)}</div>
      <div className="wb-heading-actions"><button ref={exportButton} className="wb-outline-accent" disabled={!taskId} aria-expanded={exportOpen} aria-controls={exportId} onClick={() => setExportOpen(value => !value)}><Upload size={16} />导出数据</button>{view === 'videos' && <button className="wb-primary" disabled={busy || !selection.length || !onDownload} onClick={() => requestDownload(selection)}><Download size={16} />下载所选{selection.length ? ` (${selection.length})` : ''}</button>}</div>
    </div>
    {exportOpen && taskId && <ExportData id={exportId} taskId={taskId} files={results.exports} busy={busy} onGenerate={onExport} onClose={closeExport} />}
    {view === 'videos' && <div className="wb-results-filters"><label className="wb-search"><Search size={16} /><input aria-label="筛选视频" value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索标题、格式或清晰度" /></label>
      <select aria-label="视频状态" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部状态</option><option value="available">可下载 / 可重试</option><option value="pending">等待下载</option><option value="running">下载中</option><option value="succeeded">已下载</option><option value="unavailable">暂不可下载</option></select>
      <label className="wb-check"><input type="checkbox" aria-label="选择当前可下载视频" checked={eligible.length > 0 && eligible.every(r => selection.includes(r.id))} disabled={!eligible.length || busy} onChange={e => setSelected(old => e.target.checked ? [...new Set([...old, ...eligible.map(r => r.id)])] : old.filter(id => !eligible.some(r => r.id === id)))} />全选可下载</label><span className="wb-selection-count">{selection.length ? `已选 ${selection.length} 项` : `${filtered.length} 个视频`}</span>
    </div>}
    {view === 'videos' ? filtered.length ? <ResourceTable key={`${taskId || ''}:${sessionId || ''}`} resources={filtered} selected={selection} busy={busy} canDownload={Boolean(onDownload)} onToggle={toggle} onDownload={requestDownload} /> : <div className="wb-table-empty"><Video size={32} strokeWidth={1.5} /><h3>{videos.length ? '没有匹配的视频' : '尚未发现视频'}</h3><p>{videos.length ? '尝试其他关键词或状态。' : '打开网站并播放视频，或开始采集后，发现的视频会列在这里。'}</p>{resourceStatus && <small>{resourceStatus}</small>}</div> : <div className="wb-result-scroll">
      {(view === 'content' || view === 'comments') && <>{!records.length && <div className="wb-table-empty"><FileText size={30} /><h3>暂无{view === 'content' ? '内容' : '评论'}记录</h3><p>采集后的记录会逐条保存在这里。</p></div>}{records.map(r => <details key={r.id} className="wb-record"><summary>{r.title || r.id}<small>{r.id}{recordVideoStatus(r.fields)}</small></summary><pre>{JSON.stringify(r.fields || r, null, 2)}</pre></details>)}</>}
      {(view === 'files' || view === 'failures') && <>{!files.length && (view !== 'failures' || !failed.length) && <div className="wb-table-empty"><FileText size={30} /><h3>{view === 'files' ? '暂无下载文件' : '没有失败项'}</h3></div>}{files.map(f => <div className="wb-record wb-file-row" key={f.id}><FileText size={22} /><strong>{f.title}</strong><StatusBadge state={f.state} resource /><small>{bytes(f.size)}</small>{f.state === 'succeeded' && f.path && taskId && <a download href={fileUrl(taskId, f.path)}>下载文件</a>}{f.error && <p className="wb-detail-error">{f.error}</p>}</div>)}</>}
      {view === 'failures' && failed.map(r => <div className="wb-record" key={r.id}><StatusBadge state="failed" />{r.title}<small>{r.target}</small></div>)}
    </div>}
    <div className="wb-results-footer">发现的视频需手动选择下载；采集配置勾选后随任务下载。</div>
  </div>
}
