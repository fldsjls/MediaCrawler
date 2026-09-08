import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api } from '../api'
import { choices, labels, values } from '../workflows/types'
import { SettingsActions, SettingsBlock } from './SettingsLayout'
const sections:Record<string,{title:string;description:string;fields:string[]}[]>={
  tasks:[
    {title:'采集范围',description:'用于自动采集与课程发现，手动下载按实际勾选的资源执行。',fields:['max_items','start']},
    {title:'评论与回复',description:'为支持评论采集的平台设置默认数量。',fields:['max_comments','subcomments']},
    {title:'自动操作',description:'控制页面等待与资源发现规则。选择器留空时沿用平台规则。',fields:['wait_ms','selector']},
  ],
  downloads:[
    {title:'下载引擎',description:'自动模式按资源类型选择；指定引擎后不会静默切换。',fields:['engine']},
    {title:'媒体选择',description:'选择清单中的视频流和音轨；直接文件不会转码。',fields:['quality','audio']},
    {title:'本机工具',description:'填写可执行文件的完整路径。路径修改后需先保存，再检查版本与可用状态。',fields:['ffmpeg_path','n_m3u8dl_path']},
    {title:'传输与重试',description:'分片并发数用于 N_m3u8DL-RE，公共文件队列按顺序执行。',fields:['timeout','retries','concurrency']},
  ],
  exports:[
    {title:'保存位置',description:'目录留空使用受管运行目录；每次运行独立保存。',fields:['output_dir','subdirectory']},
    {title:'文件命名',description:'名称留空时自动命名，重名文件不会被覆盖。',fields:['filename','collision']},
    {title:'数据导出',description:'字段使用逗号分隔，留空保留全部公开字段。',fields:['output','export_fields']},
  ],
}
const limits:Record<string,[number,number?]>={max_items:[1,10000],start:[1],max_comments:[0,10000],wait_ms:[100,120000],timeout:[5,600],retries:[0,5],concurrency:[1,16]}
const wide=new Set(['ffmpeg_path','n_m3u8dl_path','output_dir','subdirectory','selector','export_fields'])
type Defaults=Record<string,string|number|boolean>
type Tool={engine:string;available:boolean;version:string}
export function TaskDefaults({group,onError}:{group:string;onError:(s:string)=>void}) {
  const [defaults,setDefaults]=useState<Defaults>(),[original,setOriginal]=useState<Defaults>(),[tools,setTools]=useState<Tool[]>([]),[busy,setBusy]=useState(false),[checking,setChecking]=useState(false)
  useEffect(()=>{let active=true;setDefaults(undefined);setTools([]);void api<Defaults>('/settings/defaults').then(v=>{if(active){setDefaults(v);setOriginal(v)}}).catch(e=>{if(active)onError(e.message)});return()=>{active=false}},[group])
  const fields=sections[group].flatMap(s=>s.fields)
  const dirty=!!defaults&&fields.some(k=>defaults[k]!==original?.[k])
  const pathsDirty=!!defaults&&['ffmpeg_path','n_m3u8dl_path'].some(k=>defaults[k]!==original?.[k])
  const inspect=async()=>{setChecking(true);try{setTools(await api<Tool[]>('/settings/tools'))}catch(e){onError(e instanceof Error?e.message:String(e))}finally{setChecking(false)}}
  const save=async()=>{if(!defaults)return;setBusy(true);try{const next=await api<Defaults>('/settings/defaults',Object.fromEntries(fields.map(k=>[k,defaults[k]])),'PATCH');setDefaults(next);setOriginal(next);if(pathsDirty)setTools([]);toast.success('默认设置已保存，对下次开始的运行生效')}catch(e){onError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
  if(!defaults)return <p role="status">正在读取默认设置…</p>
  return <form className="wb-settings-detail wb-settings-form" onSubmit={e=>{e.preventDefault();void save()}}>
    <p className="wb-settings-context"><strong>项目默认值</strong><span>卡片可单独覆盖；已提交的运行保留原参数。</span></p>
    <div className={`wb-settings-sections ${group==='downloads'?'wb-download-sections':''}`}>{sections[group].map(section=><SettingsBlock key={section.title} title={section.title} description={section.description} action={section.title==='本机工具'&&<button type="button" disabled={busy||checking||pathsDirty} onClick={()=>void inspect()}>{checking?'正在检查…':'检查工具状态'}</button>}>
      <div className="wb-settings-grid">{section.fields.map(key=><label className={`${wide.has(key)?'wb-settings-full ':''}${typeof defaults[key]==='boolean'?'wb-settings-toggle':''}`} key={key}>
        <span>{labels[key]}</span>
        {choices[key]?<select disabled={busy||checking} value={String(defaults[key])} onChange={e=>setDefaults({...defaults,[key]:e.target.value})}>{choices[key].map(v=><option key={v} value={v}>{values[v]||v.toUpperCase()}</option>)}</select>:typeof defaults[key]==='boolean'?<input disabled={busy||checking} type="checkbox" checked={Boolean(defaults[key])} onChange={e=>setDefaults({...defaults,[key]:e.target.checked})}/>:<input disabled={busy||checking} title={wide.has(key)?String(defaults[key]):undefined} type={typeof defaults[key]==='number'?'number':'text'} min={limits[key]?.[0]} max={limits[key]?.[1]} placeholder={key==='output_dir'?'留空使用受管运行目录':key==='filename'?'留空自动命名':undefined} value={String(defaults[key])} onChange={e=>setDefaults({...defaults,[key]:typeof defaults[key]==='number'?Number(e.target.value):e.target.value})}/>}
      </label>)}</div>
      {section.title==='下载引擎'&&<p className="wb-settings-note">自动选择：直接文件 → HTTP；完整 HLS / DASH → N_m3u8DL-RE 优先；分离流与分片合并 → FFmpeg。</p>}
      {section.title==='本机工具'&&<div className="wb-tool-status" aria-live="polite">{pathsDirty?<p>工具路径尚未保存，请先保存再检查。</p>:tools.length?tools.map(t=><div key={t.engine}><strong>{values[t.engine]||t.engine}</strong><span className={`wb-tool-badge ${t.available?'available':'unavailable'}`}>{t.available?'可用':'不可用'}</span><small>{t.version||'未读取到版本'}</small></div>):<p>尚未检查工具状态。</p>}</div>}
    </SettingsBlock>)}</div>
    <SettingsActions status={dirty?'有未保存的修改':'已与项目保存值一致'}><button type="button" disabled={busy||checking||!dirty} onClick={()=>setDefaults(original)}>撤销修改</button><button type="submit" className="wb-primary" disabled={busy||checking||!dirty}>{busy?'保存中…':'保存默认设置'}</button></SettingsActions>
  </form>
}
