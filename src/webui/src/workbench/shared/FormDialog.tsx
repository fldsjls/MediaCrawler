import { ReactNode, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'

export function FormDialog({title, description, children, onClose, onSave, footerActions, compact=false, dirty=false, busy=false}: {title:string;description?:string;children:ReactNode;onClose:()=>void;onSave?:()=>void;footerActions?:ReactNode;compact?:boolean;dirty?:boolean;busy?:boolean}) {
  const ref=useRef<HTMLDialogElement>(null), [discard,setDiscard]=useState(false)
  useLayoutEffect(()=>{const previous=document.activeElement as HTMLElement|null;const d=ref.current!;d.showModal();return()=>{d.close();if(previous?.isConnected)previous.focus()}},[])
  const close=()=>{if(busy)return;if(dirty)setDiscard(true);else onClose()}
  return <dialog ref={ref} className={`wb-form-dialog ${onSave||compact?'wb-form-dialog-compact':''}`} aria-label={title} onKeyDown={e=>{if(e.key!=='Tab')return;const items=Array.from(e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]')).filter(el=>el.getClientRects().length);const first=items[0],last=items[items.length-1];if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus()}}} onCancel={e=>{e.preventDefault();e.stopPropagation();close()}} onClick={e=>{if(e.target!==e.currentTarget)return;const r=e.currentTarget.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)close()}}>
    <header><div className="wb-dialog-heading"><h2>{title}</h2>{description&&<p>{description}</p>}</div><button disabled={busy} aria-label="关闭弹窗" onClick={close}><X size={18}/></button></header>
    <div className="wb-form-body">{children}</div>
    {(onSave||discard)&&<footer className="wb-dialog-footer">{discard?<div className="wb-dialog-discard" role="alert"><span>尚有未保存的修改，是否放弃？</span><div><button disabled={busy} onClick={()=>setDiscard(false)}>继续编辑</button><button disabled={busy} className="wb-dialog-danger" onClick={onClose}>放弃修改</button></div></div>:<><div className="wb-dialog-secondary">{footerActions}</div><div className="wb-dialog-primary"><button disabled={busy} onClick={close}>取消</button><button className="wb-primary" disabled={busy} onClick={onSave}>{busy?'保存中…':'保存'}</button></div></>}</footer>}
  </dialog>
}

export function OverflowText({text}: {text:string}) {
  const ref=useRef<HTMLSpanElement>(null),tip=useRef<HTMLSpanElement>(null),timer=useRef<ReturnType<typeof setTimeout>>()
  const [position,setPosition]=useState<{left:number;top:number;root:Element}|null>(null)
  useLayoutEffect(()=>{
    if(!position||!tip.current||!ref.current)return
    const box=tip.current.getBoundingClientRect(),anchor=ref.current.getBoundingClientRect()
    const left=Math.max(8,Math.min(anchor.left,innerWidth-box.width-8))
    const top=anchor.bottom+6+box.height<=innerHeight-8?anchor.bottom+6:Math.max(8,anchor.top-box.height-6)
    if(left!==position.left||top!==position.top)setPosition({...position,left,top})
  },[position])
  const hide=()=>{clearTimeout(timer.current);setPosition(null)}
  useLayoutEffect(()=>()=>clearTimeout(timer.current),[])
  const show=()=>{timer.current=setTimeout(()=>{const el=ref.current!;if(el.scrollWidth<=el.clientWidth)return;const r=el.getBoundingClientRect();setPosition({left:Math.max(8,Math.min(r.left,innerWidth-358)),top:Math.max(8,Math.min(r.bottom+6,innerHeight-100)),root:el.closest('dialog')||document.body})},120)}
  return <><span ref={ref} className="wb-ellipsis" onMouseEnter={show} onMouseLeave={hide} onFocus={show} onBlur={hide} tabIndex={0} aria-label={text}>{text}</span>{position&&createPortal(<span ref={tip} className="wb-overflow-tip" role="tooltip" style={{left:position.left,top:position.top}}>{text}</span>,position.root)}</>
}
