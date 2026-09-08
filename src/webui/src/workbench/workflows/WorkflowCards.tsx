import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { GripVertical } from 'lucide-react'
import { OverflowText } from '../shared/FormDialog'
import { labels, Step, titles, Validation, values } from './types'

type Drag={id:string;to:number;keyboard:boolean;active:boolean;x:number;y:number;width:number;offset:number}
interface Props {steps:Step[];busy:boolean;onEdit:(s:Step)=>void;onToggle:(id:string,value:boolean)=>void;onMove:(id:string,to:number)=>Promise<boolean>;onPreview:(id:string,to:number)=>Promise<Validation>}
const summary=(s:Step)=>Object.entries(s.overrides).map(([k,v])=>`${labels[k]}：${values[String(v)]||String(v)}`).join(' · ')||'使用默认设置'
export function WorkflowCards({steps,busy,onEdit,onToggle,onMove,onPreview}:Props) {
  const list=useRef<HTMLDivElement>(null),current=useRef<Drag|null>(null),pointer=useRef({x:0,y:0}),origin=useRef({x:0,y:0}),frame=useRef(0)
  const [drag,setDrag]=useState<Drag|null>(null),[check,setCheck]=useState<{valid:boolean;reason:string}|null>(null),[status,setStatus]=useState('')
  const preview=useRef(onPreview);preview.current=onPreview
  const put=(value:Drag|null)=>{current.current=value;setDrag(value)}
  const finish=(commit:boolean)=>{
    const d=current.current;put(null);cancelAnimationFrame(frame.current);setCheck(null)
    if(!d?.active)return
    if(commit&&d.to!==steps.findIndex(s=>s.id===d.id)){setStatus('正在校验排序…');void onMove(d.id,d.to).then(ok=>setStatus(ok?'卡片顺序已更新':'排序不符合依赖条件，已保留原顺序'))}
    else setStatus(commit?'顺序未改变':'已取消排序')
  }
  useEffect(()=>()=>cancelAnimationFrame(frame.current),[])
  useEffect(()=>{
    if(!drag?.active)return
    let active=true;setCheck(null)
    const timer=setTimeout(()=>{void preview.current(drag.id,drag.to).then(v=>{if(active)setCheck({valid:v.valid,reason:v.errors.join('；')})}).catch(()=>{if(active)setCheck({valid:false,reason:'暂时无法校验，松开后重新检查'})})},100)
    return()=>{active=false;clearTimeout(timer)}
  },[drag?.id,drag?.to,drag?.active])
  const tick=()=>{
    const d=current.current;if(!d||d.keyboard)return
    const pos=pointer.current
    if(!d.active&&Math.hypot(pos.x-origin.current.x,pos.y-origin.current.y)<5){frame.current=requestAnimationFrame(tick);return}
    const scroller=list.current?.closest('.wb-config-scroll') as HTMLElement|null
    if(scroller){const r=scroller.getBoundingClientRect();const speed=pos.y<r.top+44?-Math.min(14,(r.top+44-pos.y)/3):pos.y>r.bottom-44?Math.min(14,(pos.y-r.bottom+44)/3):0;scroller.scrollTop+=speed}
    const others=Array.from(list.current?.querySelectorAll<HTMLElement>('[data-step]')||[]).filter(el=>el.dataset.step!==d.id)
    let to=others.findIndex(el=>{const r=el.getBoundingClientRect();return pos.y<r.top+r.height/2});if(to<0)to=others.length
    put({...d,active:true,to,x:pos.x,y:pos.y});frame.current=requestAnimationFrame(tick)
  }
  const dragged=steps.find(s=>s.id===drag?.id),remaining=steps.filter(s=>s.id!==drag?.id)
  const target=drag?.active?remaining[drag.to]?.id:undefined
  const indicator=drag?.active?<div className={`wb-drop-line ${check?.valid===false?'invalid':''}`} aria-hidden="true"/>:null
  return <><div className={`wb-workflow-cards ${drag?.active?'sorting':''}`} ref={list}>
    {steps.map((s,index)=><div className="wb-sort-slot" key={s.id}>
      {s.id===target&&indicator}
      <div data-step={s.id} className={`wb-workflow-card ${s.enabled?'':'disabled'} ${drag?.active&&drag.id===s.id?'is-dragging':''}`}>
        <div className="wb-card-controls"><button type="button" className="wb-drag-handle" aria-label={`拖动排序：${s.name||titles[s.kind]}`} aria-describedby="workflow-sort-help" aria-pressed={drag?.active&&drag.id===s.id} disabled={busy||steps.length<2}
          onPointerDown={e=>{if(e.button!==0||current.current)return;e.preventDefault();e.currentTarget.focus();e.currentTarget.setPointerCapture(e.pointerId);const r=e.currentTarget.closest('[data-step]')!.getBoundingClientRect();pointer.current=origin.current={x:e.clientX,y:e.clientY};put({id:s.id,to:index,keyboard:false,active:false,x:e.clientX,y:e.clientY,width:r.width,offset:e.clientY-r.top});frame.current=requestAnimationFrame(tick)}}
          onPointerMove={e=>{pointer.current={x:e.clientX,y:e.clientY}}}
          onPointerUp={e=>{if(current.current&&!current.current.keyboard){const r=list.current!.closest('.wb-config-scroll')!.getBoundingClientRect();finish(e.clientX>=r.left&&e.clientX<=r.right&&e.clientY>=r.top&&e.clientY<=r.bottom)}}}
          onPointerCancel={()=>finish(false)} onLostPointerCapture={()=>{if(current.current&&!current.current.keyboard)finish(false)}}
          onKeyDown={e=>{if(e.key==='Escape'&&current.current){e.preventDefault();finish(false);return}if((e.key===' '||e.key==='Enter')){e.preventDefault();if(current.current)finish(true);else{put({id:s.id,to:index,keyboard:true,active:true,x:0,y:0,width:0,offset:0});setStatus('已选中卡片，使用方向键移动，回车确认，Esc 取消')}return}if(current.current?.keyboard&&['ArrowUp','ArrowDown'].includes(e.key)){e.preventDefault();const to=Math.max(0,Math.min(steps.length-1,current.current.to+(e.key==='ArrowUp'?-1:1)));put({...current.current,to});setStatus(`目标位置：第 ${to+1} 项`)}}}><GripVertical size={18}/></button>
          <input disabled={busy||!!drag?.active} type="checkbox" aria-label={`启用 ${s.name||titles[s.kind]}`} checked={s.enabled} onChange={e=>onToggle(s.id,e.target.checked)}/></div>
        <button className="wb-card-copy" disabled={busy||!!drag?.active} onClick={()=>onEdit(s)}><strong><OverflowText text={s.name||titles[s.kind]}/></strong><OverflowText text={summary(s)}/></button>
      </div>
    </div>)}
    {drag?.active&&drag.to===remaining.length&&indicator}
  </div>
  <span id="workflow-sort-help" className="wb-sr-only">拖动手柄排序；也可按空格选中、上下方向键移动、回车确认、Esc 取消。</span>
  <span className="wb-sr-only" role="status">{status}</span>
  {drag?.active&&<p className={`wb-sort-feedback ${check?.valid===false?'invalid':''}`} role="status">{check?check.valid?`移动到第 ${drag.to+1} 项，${drag.keyboard?'回车':'松开'}确认`:check.reason:'正在检查此位置的依赖…'}</p>}
  {drag?.active&&!drag.keyboard&&dragged&&createPortal(<div className="wb-sort-ghost" style={{left:Math.max(8,drag.x-28),top:drag.y-drag.offset,width:drag.width}}><GripVertical size={18}/><div><strong>{dragged.name||titles[dragged.kind]}</strong><span>{summary(dragged)}</span></div></div>,document.body)}
  </>
}
