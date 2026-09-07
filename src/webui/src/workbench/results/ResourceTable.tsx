import { useEffect, useRef, useState } from 'react'
import { Download, ExternalLink, FileVideo, X } from 'lucide-react'
import { Resource } from '../api'
import { StatusBadge } from '../components/StatusBadge'

export const downloadable = (r: Resource) => ['discovered', 'failed'].includes(r.state)
export const bytes = (size?: number) => size === undefined ? '大小未知' : size >= 1048576 ? `${(size / 1048576).toFixed(1)} MB` : `${Math.round(size / 1024)} KB`
const quality = (r: Resource) => r.quality || (r.width && r.height ? `${r.width} × ${r.height}` : '—')
const source = (r: Resource) => r.origin === 'adapter' ? '平台解析' : '浏览器发现'
interface Props { resources: Resource[]; selected: string[]; busy?: boolean; canDownload: boolean; onToggle: (id: string) => void; onDownload: (ids: string[]) => void }

export function ResourceTable({ resources, selected, busy, canDownload, onToggle, onDownload }: Props) {
  const [inspectedId, setInspectedId] = useState<string>()
  const inspected = resources.find(r => r.id === inspectedId)
  const returnFocus = useRef<HTMLButtonElement | null>(null)
  const close = () => { setInspectedId(undefined); returnFocus.current?.focus() }
  useEffect(() => {
    if (!inspectedId) return
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') { setInspectedId(undefined); returnFocus.current?.focus() } }
    document.addEventListener('keydown', key)
    return () => document.removeEventListener('keydown', key)
  }, [inspectedId])
  return <div className="wb-resource-layout">
    <div className="wb-table-scroll"><table className="wb-table wb-video-table" aria-label="发现的视频">
      <thead><tr><th className="wb-checkbox-cell"><span className="sr-only">选择</span></th><th>视频标题</th><th>格式与清晰度</th><th>大小</th><th>来源</th><th>状态</th><th>操作</th></tr></thead>
      <tbody>{resources.map(r => <tr key={r.id} data-selected={selected.includes(r.id)}>
        <td className="wb-checkbox-cell"><input type="checkbox" aria-label={`选择视频 ${r.title || r.id}`} checked={selected.includes(r.id)} disabled={busy || !downloadable(r)} onChange={() => onToggle(r.id)} /></td>
        <td><button className="wb-title-button wb-video-title" title={r.title} onClick={event => { returnFocus.current = event.currentTarget; setInspectedId(r.id) }}><FileVideo size={21} strokeWidth={1.5} /><span>{r.title || '未命名视频'}</span></button></td>
        <td>{r.format?.toUpperCase() || '—'} <span className="wb-cell-muted">{quality(r)}</span></td><td>{bytes(r.size)}</td><td>{source(r)}</td><td><StatusBadge state={r.state} resource /></td>
        <td>{downloadable(r) ? <button className="wb-outline-accent" aria-label={`下载视频 ${r.title || r.id}`} disabled={busy || !canDownload} onClick={() => onDownload([r.id])}><Download size={14} />下载</button> : <span className="wb-cell-muted">—</span>}</td>
      </tr>)}</tbody>
    </table></div>
    {inspected && <aside className="wb-resource-detail" aria-label="资源信息">
      <div className="wb-inspector-heading"><h3>资源信息</h3><button aria-label="关闭资源信息" onClick={close}><X size={17} /></button></div>
      <div className="wb-file-preview" aria-hidden="true"><FileVideo size={56} strokeWidth={1} /><span>{inspected.format?.toUpperCase() || 'VIDEO'}</span></div>
      <h2>{inspected.title || '未命名视频'}</h2><dl><dt>格式</dt><dd>{inspected.format?.toUpperCase() || '—'}</dd><dt>清晰度</dt><dd>{quality(inspected)}</dd><dt>大小</dt><dd>{bytes(inspected.size)}</dd><dt>来源</dt><dd>{source(inspected)}</dd><dt>状态</dt><dd><StatusBadge state={inspected.state} resource /></dd></dl>
      {inspected.page_url && <div className="wb-resource-source"><span>来源页面</span><a href={inspected.page_url} target="_blank" rel="noreferrer">{inspected.page_url}<ExternalLink size={13} /></a></div>}
      {inspected.error && <p className="wb-detail-error">{inspected.error}</p>}
    </aside>}
  </div>
}
