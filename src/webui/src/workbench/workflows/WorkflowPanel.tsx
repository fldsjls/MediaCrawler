import { useEffect, useRef, useState } from 'react'
import { WorkflowCards } from './WorkflowCards'
import { api, Config, Platform, Session, Task, saved } from '../api'
import { FormDialog, OverflowText } from '../shared/FormDialog'
import { choices, Definition, labels, Plan, Step, titles, Validation, values } from './types'

interface Props {config:Config;platforms:Platform[];session?:Session;tasks:Task[];busy:boolean;onSource:(p:Plan)=>void;onRun:(task:Task)=>void;onOpen:()=>void;onSettings:(group:string)=>void;onError:(s:string)=>void}
const makePlan=(config:Config):Plan=>({name:'新任务方案',platform:config.platform,target:config.target,source:'website',mode:'detail',resource_ids:[],steps:[]})

export function WorkflowPanel(props:Props) {
  const [plan,setPlan]=useState<Plan>(()=>saved('mc.workflow.draft',makePlan(props.config))),[validation,setValidation]=useState<Validation>(),[plans,setPlans]=useState<(Plan&{id:string})[]>([]),[planId,setPlanId]=useState(()=>saved('mc.workflow.plan-id',''))
  const [edit,setEdit]=useState<Step>(),[source,setSource]=useState<Plan>(),[adding,setAdding]=useState(false),[working,setWorking]=useState(false),[message,setMessage]=useState('')
  useEffect(()=>localStorage.setItem('mc.workflow.plan-id',JSON.stringify(planId)),[planId])
  const revision=useRef(0),submitting=useRef(false),submission=useRef<{plan:string;key:string}>()
  useEffect(()=>{void api<(Plan&{id:string})[]>('/plans').then(setPlans).catch(e=>props.onError(e.message))},[])
  useEffect(()=>{localStorage.setItem('mc.workflow.draft',JSON.stringify(plan));props.onSource(plan);const id=++revision.current;void api<Validation>('/plans/validate',plan).then(v=>{if(revision.current===id)setValidation(v)}).catch(e=>{if(revision.current===id)props.onError(e.message)})},[plan])
  const change=async(next:Plan,allowIncomplete=false)=>{setWorking(true);try{const check=await api<Validation>('/plans/validate',next);if(!check.valid&&!allowIncomplete)throw Error(check.errors.join('；'));setPlan(next);setValidation(check);setMessage('');return true}catch(e){props.onError(String(e instanceof Error?e.message:e));return false}finally{setWorking(false)}}
  const reordered=(id:string,to:number)=>{const steps=[...plan.steps],from=steps.findIndex(s=>s.id===id);if(from>=0&&to>=0&&to<steps.length)steps.splice(to,0,steps.splice(from,1)[0]);return {...plan,steps}}
  const move=(id:string,to:number)=>change(reordered(id,to))
  const save=async(copy=false)=>{setWorking(true);try{const result=await api<Plan&{id:string}>(planId&&!copy?`/plans/${planId}`:'/plans',plan,planId&&!copy?'PUT':'POST');setPlanId(result.id);setPlans(await api('/plans'));setMessage(copy?'已保存方案副本':'方案已保存')}catch(e){props.onError(String(e instanceof Error?e.message:e))}finally{setWorking(false)}}
  const start=async()=>{if(submitting.current)return;submitting.current=true;setWorking(true);try{const serialized=JSON.stringify(plan);if(submission.current?.plan!==serialized)submission.current={plan:serialized,key:crypto.randomUUID()};const run=await api<Task>('/runs',plan,'POST',submission.current.key);submission.current=undefined;props.onRun(run);setMessage('运行已加入队列')}catch(e){props.onError(String(e instanceof Error?e.message:e))}finally{submitting.current=false;setWorking(false)}}
  return <aside className="wb-config wb-workflow" aria-label="任务方案"><div className="wb-config-heading"><h1>任务方案</h1></div><div className="wb-config-scroll">
    <div className="wb-plan-actions"><select aria-label="已保存方案" value={planId} onChange={e=>{setPlanId(e.target.value);const p=plans.find(p=>p.id===e.target.value);if(p){const{id,...value}=p;setPlan(value)}else setPlan(makePlan(props.config))}}><option value="">新建方案</option>{plans.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select><button disabled={working} onClick={()=>void save()}>保存</button>{planId&&<button onClick={()=>void save(true)}>另存</button>}</div>
    <button className="wb-source-card" onClick={()=>setSource(structuredClone(plan))}><strong><OverflowText text={plan.name}/></strong><OverflowText text={plan.target||'设置网址或资源来源'}/><small>{props.platforms.find(p=>p.id===plan.platform)?.name||plan.platform} · 编辑来源</small></button>
    <WorkflowCards steps={plan.steps} busy={working} onEdit={s=>setEdit(structuredClone(s))} onMove={move} onPreview={(id,to)=>api<Validation>('/plans/validate',reordered(id,to))} onToggle={(id,enabled)=>void change({...plan,steps:plan.steps.map(t=>t.id===id?{...t,enabled}:t)})}/>
    <button className="wb-add-step" disabled={working||!validation} onClick={()=>setAdding(true)}>＋ 添加下一步</button>
    {validation&&!validation.valid&&<p className="wb-muted" role="status">{validation.errors.join('；')}</p>}
    {validation?.valid&&!validation.available.length&&<p className="wb-muted">当前没有下一步，请调整资源来源。</p>}
    {message&&<p role="status">{message}</p>}
  </div><div className="wb-config-actions">{plan.source==='website'&&<button disabled={props.busy} onClick={props.onOpen}>打开网站</button>}<button className="wb-primary" disabled={working||props.busy||!validation?.valid||!plan.steps.some(s=>s.enabled)} onClick={()=>void start()}>开始任务</button></div>
  {source&&<SourceEditor busy={working} value={source} session={props.session} platforms={props.platforms} tasks={props.tasks} onClose={()=>setSource(undefined)} onSave={async p=>{if(await change(p,!p.steps.length))setSource(undefined)}}/>}
  {adding&&<FormDialog compact description="全部已实现卡片均在这里；灰色卡片需先补齐条件。" title="添加下一步" onClose={()=>setAdding(false)}><div className="wb-next-steps">{validation?.options?.map(d=><button key={d.id} aria-disabled={!d.enabled} className={d.enabled?'':'unavailable'} onClick={()=>{if(!d.enabled)return;setAdding(false);setEdit({id:crypto.randomUUID(),kind:d.id,name:d.title,enabled:true,input:d.sources[d.sources.length-1],overrides:{}})}}><div className="wb-next-heading"><strong><OverflowText text={d.title}/></strong><small>{d.enabled?'可添加':'暂不可用'}</small></div><OverflowText text={d.enabled?`可用来源：${d.sources.map(id=>plan.steps.find(s=>s.id===id)?.name||'方案来源').join('、')}`:d.reason}/></button>)}</div></FormDialog>}
  {edit&&validation&&<StepEditor initial={edit} definition={{...validation.definitions.find(d=>d.id===edit.kind)!, sources:validation.step_inputs[edit.id] || validation.available.find(d=>d.id===edit.kind)?.sources || []}} defaults={validation.defaults} plan={plan} busy={working} onSettings={props.onSettings} onClose={()=>setEdit(undefined)} onDelete={async()=>{if(await change({...plan,steps:plan.steps.filter(s=>s.id!==edit.id)}))setEdit(undefined)}} onSave={async s=>{const found=plan.steps.some(p=>p.id===s.id);if(await change({...plan,steps:found?plan.steps.map(p=>p.id===s.id?s:p):[...plan.steps,s]}))setEdit(undefined)}}/>}
  </aside>
}

function SourceEditor({value,session,platforms,tasks,busy,onClose,onSave}:{busy:boolean;value:Plan;session?:Session;platforms:Platform[];tasks:Task[];onClose:()=>void;onSave:(p:Plan)=>void}) {
  const [draft,setDraft]=useState(value)
  const set=(p:Partial<Plan>)=>setDraft(old=>({...old,...p}))
  return <FormDialog title="方案与来源" description="设置方案名称与资源入口，后续卡片将沿用此来源。" busy={busy} dirty={JSON.stringify(draft)!==JSON.stringify(value)} onClose={onClose} onSave={()=>onSave(draft)}><div className="wb-editor-fields wb-source-fields">
    <label>方案名称<input value={draft.name} onChange={e=>set({name:e.target.value})}/></label>
    <label>资源来源<select value={draft.source} onChange={e=>set({source:e.target.value as Plan['source'],session_id:undefined,resource_ids:[]})}><option value="website">网站页面</option><option value="direct">直接文件链接</option><option value="history">历史运行数据</option></select></label>
    {draft.source==='history'?<label>历史运行<select value={draft.history_id||''} onChange={e=>set({history_id:e.target.value})}><option value="">请选择</option>{tasks.map(t=><option key={t.id} value={t.id}>{t.config.target}</option>)}</select></label>:<label className="wb-field-wide">目标地址 / 关键词<input value={draft.target} onChange={e=>{const target=e.target.value;let detected;try{const host=new URL(target).hostname;detected=platforms.find(p=>{try{return p.enabled!==false&&new URL(p.url).hostname===host}catch{return false}})}catch{}set({target,...(draft.source==='website'?{platform:detected?.id||'generic'}:{})})}}/></label>}
    <label>平台适配<select value={draft.platform} onChange={e=>set({platform:e.target.value,mode:'detail'})}>{platforms.filter(p=>p.enabled!==false).map(p=><option value={p.id} key={p.id}>{p.name}</option>)}</select></label>
    {draft.source==='website'&&<label>使用的会话<select value={draft.session_id||''} onChange={e=>set({session_id:e.target.value||undefined})}><option value="">自动准备会话</option>{session&&session.platform===draft.platform&&<option value={session.id}>当前浏览器会话</option>}</select></label>}
    {draft.source==='website'&&(platforms.find(p=>p.id===draft.platform)?.inputs.length||0)>1&&<label>采集目标<select value={draft.mode} onChange={e=>set({mode:e.target.value as Plan['mode']})}>{platforms.find(p=>p.id===draft.platform)?.inputs.map(m=><option value={m} key={m}>{{detail:'指定页面',search:'关键词搜索',creator:'创作者作品'}[m]||m}</option>)}</select></label>}
  </div></FormDialog>
}

function StepEditor({initial,definition,defaults,plan,busy,onClose,onSave,onDelete,onSettings}:{initial:Step;definition:Definition;defaults:Validation['defaults'];plan:Plan;busy:boolean;onClose:()=>void;onSave:(s:Step)=>void;onDelete:()=>void;onSettings:(group:string)=>void}) {
  const [step,setStep]=useState(initial),[leave,setLeave]=useState(false)
  const dirty=JSON.stringify(step)!==JSON.stringify(initial)
  const goSettings=()=>{onClose();onSettings(['media','files'].includes(step.kind)?'downloads':step.kind==='export'?'exports':step.kind==='session'?'browser':'tasks')}
  const update=(key:string,value:string|number|boolean|undefined)=>setStep(old=>{const overrides={...old.overrides};if(value===undefined)delete overrides[key];else overrides[key]=value;return {...old,overrides}})
  const formatDefault=(key:string)=>{
    const value=defaults[key]
    if(value===''||value===undefined)return key==='filename'?'自动命名':key==='subdirectory'?'运行目录':'未设置'
    return typeof value==='boolean'?(value?'开启':'关闭'):values[String(value)]||String(value)
  }
  const descriptions:Record<Step['kind'],string>={session:'建立或复用浏览会话，供后续发现与采集使用。',discover:'在浏览会话中发现资源，供下载卡片使用。',content:'采集页面内容，供评论采集或导出使用。',comments:'采集评论及回复，供后续导出使用。',media:'下载输入来源中的视频、音频或图片。',files:'下载输入来源中的文件，保存为任务产物。',export:'将记录或文件清单导出为可下载的文件。'}
  return <FormDialog title={`编辑${titles[step.kind]}`} description={descriptions[step.kind]} dirty={dirty} busy={busy} onClose={onClose} onSave={()=>onSave(step)} footerActions={plan.steps.some(s=>s.id===step.id)&&<button disabled={busy} className="wb-dialog-danger" onClick={onDelete}>删除卡片</button>}>
    <div className="wb-step-editor">
      <section className="wb-editor-section" aria-label="基本信息">
        <h3>基本信息</h3>
        <div className="wb-editor-fields">
          <label>卡片名称<input maxLength={120} value={step.name} onChange={e=>setStep({...step,name:e.target.value})}/></label>
          <label>输入来源<select title={step.input==='source'?'方案来源':plan.steps.find(s=>s.id===step.input)?.name} value={step.input} onChange={e=>setStep({...step,input:e.target.value})}>{definition.sources.map(id=><option key={id} value={id}>{id==='source'?'方案来源':plan.steps.find(s=>s.id===id)?.name||id}</option>)}</select></label>
        </div>
      </section>
      <section className="wb-editor-section" aria-label="本卡片设置">
        <div className="wb-editor-section-heading"><div><h3>本卡片设置</h3><p>仅对本卡片生效；未修改的项目沿用默认设置。</p></div><button disabled={busy} className="wb-settings-link" onClick={()=>dirty?setLeave(true):goSettings()}>前往对应设置 ↗</button></div>
        <div className="wb-overrides-grid">{definition.fields.map(key=>{
          const value=step.overrides[key]??defaults[key]??'',overridden=key in step.overrides,id=`step-${step.id}-${key}`,hint=`${id}-hint`
          return <div className={`wb-override ${key==='subdirectory'?'wb-field-wide':''}`} key={key}>
            <div className="wb-override-heading"><label htmlFor={id}>{labels[key]}</label><span className={overridden?'wb-override-badge changed':'wb-override-badge'}>{overridden?'本卡片覆盖':'使用默认'}</span></div>
            {choices[key]?<select id={id} aria-describedby={hint} value={String(value)} onChange={e=>update(key,e.target.value)}>{choices[key].map(v=><option key={v} value={v}>{values[v]||v.toUpperCase()}</option>)}</select>:typeof defaults[key]==='boolean'?<label className="wb-boolean-control"><input id={id} aria-describedby={hint} type="checkbox" checked={Boolean(value)} onChange={e=>update(key,e.target.checked)}/><span>{key==='subcomments'?'同时采集评论的回复':'启用此选项'}</span></label>:<input id={id} aria-describedby={hint} type={typeof defaults[key]==='number'?'number':'text'} placeholder={key==='filename'?'留空自动命名':key==='subdirectory'?'留空使用运行目录':undefined} value={String(value)} onChange={e=>update(key,typeof defaults[key]==='number'?Number(e.target.value):e.target.value)}/>}
            <div className="wb-override-help"><small id={hint}>默认：{formatDefault(key)}</small>{overridden&&<button disabled={busy} aria-label={`恢复默认：${labels[key]}`} onClick={()=>update(key,undefined)}>恢复默认</button>}</div>
          </div>
        })}</div>
        {!definition.fields.length&&<p className="wb-editor-empty">本卡片无需单独设置，浏览器与登录态复用规则沿用默认值。</p>}
        {leave&&<div className="wb-editor-notice" role="alert"><span>前往设置将放弃本次未保存的修改。</span><div><button onClick={()=>setLeave(false)}>继续编辑</button><button onClick={goSettings}>放弃修改并前往设置</button></div></div>}
      </section>
    </div>
  </FormDialog>
}
