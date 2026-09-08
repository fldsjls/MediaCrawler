import { useEffect, useState } from 'react'
import { api, RecordItem } from '../api'
import { FormDialog, OverflowText } from '../shared/FormDialog'
import { StatusBadge } from '../components/StatusBadge'
import { bytes } from './ResourceTable'

interface FileItem {id:string;title:string;state:string;extension?:string;received?:number;total?:number;kind?:string;size?:number;step_id?:string;engine?:string;error?:string}
interface ArtifactData {steps?:Record<string,string>;files:FileItem[];records:(RecordItem&{step_id?:string})[]}
const url=(taskId:string,id:string)=>`/api/runs/${taskId}/artifacts/${encodeURIComponent(id)}/file`

export function Artifacts({taskId,view='files'}:{taskId:string;view?:'files'|'data'}) {
  const [data,setData]=useState<ArtifactData>({files:[],records:[]}),[error,setError]=useState(''),[loaded,setLoaded]=useState(false),[step,setStep]=useState(''),[preview,setPreview]=useState<FileItem>()
  useEffect(()=>{let stopped=false,timer:ReturnType<typeof setTimeout>;setData({files:[],records:[]});setStep('');setPreview(undefined);setLoaded(false);setError('');const poll=async()=>{try{const value=await api<ArtifactData>(`/runs/${taskId}/artifacts`);if(!stopped){setData(value);setError('');setLoaded(true)}}catch{if(!stopped)setError('结果暂时无法加载，正在重试。')}if(!stopped)timer=setTimeout(poll,2000)};void poll();return()=>{stopped=true;clearTimeout(timer)}},[taskId])
  const steps=[...new Set([...data.files,...data.records].map(v=>v.step_id).filter(Boolean))]
  return <div className="wb-run-content">{error&&<p role="status">{error}</p>}{steps.length>1&&<label>步骤筛选 <select aria-label="结果所属步骤" value={step} onChange={e=>setStep(e.target.value)}><option value="">全部步骤</option>{steps.map(s=><option key={s} value={s}>{data.steps?.[s!]||'旧版任务'}</option>)}</select></label>}
    {view==='files'?data.files.filter(f=>!step||f.step_id===step).map(f=><div className="wb-artifact-row" key={f.id}><strong><OverflowText text={f.title}/><small>{bytes(f.size)}{f.engine&&` · ${f.engine}`}</small></strong><StatusBadge state={f.state} resource/>{f.state==='running'&&!!f.received&&<small>{bytes(f.received)}{f.total?` / ${bytes(f.total)}`:''}</small>}{f.state==='succeeded'&&<><button onClick={()=>setPreview(f)}>预览</button><a download href={url(taskId,f.id)+'?download=true'}>下载</a></>}{f.error&&<p className="wb-detail-error">{f.error}</p>}</div>):data.records.filter(r=>!step||r.step_id===step).map(r=><div className="wb-record-comment" key={r.id}><strong>{r.title||r.id}</strong>{r.kind==='comment'&&<><small>{r.parent_id&&`回复对象：${r.parent_id}`}</small><p>{String((r.fields as Record<string,unknown>)?.content||(r.fields as Record<string,unknown>)?.text||'')}</p></>}<details><summary>查看原始记录</summary><pre>{JSON.stringify(r.fields||r,null,2)}</pre></details></div>)}
    {!loaded&&!error&&<p role="status">正在加载运行产物…</p>}{loaded&&!(view==='files'?data.files:data.records).length&&<p className="wb-muted">{view==='files'?'暂无下载文件':'暂无数据记录'}</p>}
    {preview&&<FilePreview taskId={taskId} file={preview} onClose={()=>setPreview(undefined)}/>}
  </div>
}

function FilePreview({taskId,file,onClose}:{taskId:string;file:FileItem;onClose:()=>void}) {
  const ext=file.extension||file.title.split('.').pop()?.toLowerCase()||'', src=url(taskId,file.id)
  const [doc,setDoc]=useState<{type:string;rows?:string[][];text?:string;more:boolean;next_offset?:number}>(),[offset,setOffset]=useState(0),[error,setError]=useState('')
  const media=['mp4','webm','mp3','m4a','wav','ogg','jpg','jpeg','png','webp','gif','avif','pdf'].includes(ext)
  useEffect(()=>{if(media)return;let stopped=false;void api<typeof doc>(`/runs/${taskId}/artifacts/${encodeURIComponent(file.id)}/preview?offset=${offset}`).then(v=>{if(!stopped)setDoc(v)}).catch(e=>{if(!stopped)setError(e.message)});return()=>{stopped=true}},[taskId,file.id,offset,media])
  return <FormDialog title={file.title} onClose={onClose}><div className="wb-document-preview">
    {['mp4','webm'].includes(ext)?<video controls src={src} onError={()=>setError('文件无法播放，请下载检查格式或权限。')}/>:['mp3','m4a','wav','ogg'].includes(ext)?<audio controls src={src} onError={()=>setError('文件无法播放，请下载检查格式或权限。')}/>:['jpg','jpeg','png','webp','gif','avif'].includes(ext)?<img src={src} alt={file.title} onError={()=>setError('图片无法加载，文件可能已移动或无权读取。')}/>:ext==='pdf'?<iframe title={file.title} src={src}/>:doc?.type==='table'?<div style={{overflow:'auto'}}><table><tbody>{doc.rows?.map((row,i)=><tr key={i}>{row.map((cell,j)=><td key={j}>{cell}</td>)}</tr>)}</tbody></table></div>:doc?.type==='text'?<pre>{doc.text}</pre>:doc?.type==='unsupported'?<p>此格式暂不支持内嵌预览，可下载后打开。</p>:<p>{error||'正在加载预览…'}</p>}
    {media&&error&&<p role="status">{error}</p>}{doc?.more&&<button onClick={()=>setOffset(doc.next_offset??offset+100)}>下一页</button>}{offset>0&&<button onClick={()=>setOffset(0)}>返回开头</button>}<a download href={src+'?download=true'}>下载原文件</a>
  </div></FormDialog>
}
