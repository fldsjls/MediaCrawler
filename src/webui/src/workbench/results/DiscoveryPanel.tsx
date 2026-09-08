import { useEffect, useState } from 'react'
import { Download, Search } from 'lucide-react'
import { Resource } from '../api'
import { ResourceTable, downloadable } from './ResourceTable'
import { FormDialog } from '../shared/FormDialog'

export function DiscoveryPanel({resources,sessionId,onDownload,busy,status}:{resources:Resource[];sessionId?:string;onDownload?:(ids:string[])=>void;busy:boolean;status:string}) {
  const [selected,setSelected]=useState<string[]>([]),[kind,setKind]=useState('all'),[query,setQuery]=useState(''),[preview,setPreview]=useState<Resource>(),[previewError,setPreviewError]=useState('')
  useEffect(()=>{setSelected([]);setPreview(undefined)},[sessionId])
  const rows=resources.filter(r=>(kind==='all'||r.kind===kind)&&`${r.title} ${r.format||''}`.toLowerCase().includes(query.toLowerCase()))
  const eligible=rows.filter(downloadable),selection=selected.filter(id=>resources.some(r=>r.id===id&&downloadable(r)))
  return <div className="wb-results wb-discovery">
    <div className="wb-discovery-toolbar" role="group" aria-label="资源筛选与下载">
      <select aria-label="资源类型" value={kind} onChange={e=>setKind(e.target.value)}><option value="all">全部资源</option><option value="video">视频</option><option value="audio">音频</option><option value="image">图片</option><option value="file">文件</option></select>
      <label className="wb-search"><Search size={16} aria-hidden="true"/><input type="search" aria-label="搜索发现资源" placeholder="搜索名称或格式" value={query} onChange={e=>setQuery(e.target.value)}/></label>
      <button className="wb-primary" disabled={busy||!selection.length||!onDownload} onClick={()=>onDownload?.(selection)}><Download size={16} aria-hidden="true"/>下载所选{selection.length ? ` (${selection.length})` : ''}</button>
    </div>
    <div className="wb-discovery-selection">
      <label className="wb-check"><input type="checkbox" aria-label="全选可下载资源" disabled={busy||!eligible.length} checked={eligible.length>0&&eligible.every(r=>selection.includes(r.id))} onChange={e=>setSelected(e.target.checked?[...new Set([...selection,...eligible.map(r=>r.id)])]:selection.filter(id=>!eligible.some(r=>r.id===id)))}/><span>全选当前可下载</span></label>
      <span className="wb-discovery-status" role="status">{selection.length ? `已选 ${selection.length} 项 · ` : ''}{status}</span>
    </div>
    {rows.length?<ResourceTable resources={rows} selected={selection} busy={busy} canDownload={!!onDownload} onToggle={id=>setSelected(old=>old.includes(id)?old.filter(s=>s!==id):[...old,id])} onDownload={onDownload||(()=>{})} onPreview={r=>{setPreviewError('');setPreview(r)}}/>:<div className="wb-table-empty"><h3>{resources.length ? '没有匹配的资源' : '尚未发现资源'}</h3><p>{resources.length ? '尝试其他资源类型或搜索词。' : '打开网站并浏览、播放，或运行发现资源卡片。'}</p></div>}
    <div className="wb-results-footer">勾选只影响本次下载，预览不会自动创建下载任务。</div>
    {preview&&<FormDialog title={preview.title} onClose={()=>setPreview(undefined)}><div className="wb-document-preview">{!sessionId?<p>资源会话已关闭，请重新打开来源页面。</p>:['hls','dash','m4s','segments'].includes(preview.format||'')?<p>此资源需要解析或合并。请下载后在任务产物中预览完整文件。</p>:preview.kind==='video'?<video controls onError={()=>setPreviewError('在线资源无法播放，可能已过期或无权限；请重新发现或下载后预览。')} src={`/api/browser-sessions/${sessionId}/resources/${preview.id}/preview`}/>:preview.kind==='audio'?<audio controls onError={()=>setPreviewError('在线音频无法播放，请重新发现资源。')} src={`/api/browser-sessions/${sessionId}/resources/${preview.id}/preview`}/>:preview.kind==='image'?<img onError={()=>setPreviewError('图片无法加载，请重新发现资源。')} alt={preview.title} src={`/api/browser-sessions/${sessionId}/resources/${preview.id}/preview`}/>:<p>请下载后预览文件内容。</p>}{previewError&&<p role="status">{previewError}</p>}</div></FormDialog>}
  </div>
}
