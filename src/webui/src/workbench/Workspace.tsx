import { ReactNode, useEffect, useRef, useState } from 'react'
import { saved } from './api'

type View = 'browser' | 'logs' | 'results'
interface Layout { type: string; ratio: number; view: View; secondary: 'logs' | 'results' }
const defaults: Layout = { type: 'vertical', ratio: 70, view: 'browser', secondary: 'logs' }
export function Workspace({ browser, logs, results, onVisibility, onReset, refreshKey = 0 }: { browser: ReactNode; logs: ReactNode; results: ReactNode; onVisibility: (visible: boolean) => void; onReset?: () => void; refreshKey?: number }) {
  const [layout, setLayout] = useState(() => saved('mc.workspace.layout', defaults))
  const [maximized, setMaximized] = useState<View | null>(null)
  const [narrow, setNarrow] = useState(matchMedia('(max-width: 1000px)').matches)
  const container = useRef<HTMLDivElement>(null)
  const [bounds, setBounds] = useState({ min: 25, max: 80 })
  const type = narrow ? 'tabs' : layout.type
  const browserVisible = maximized ? maximized === 'browser' : type !== 'tabs' || layout.view === 'browser'
  useEffect(() => { if (refreshKey) { setLayout(saved('mc.workspace.layout', defaults)); setMaximized(null) } }, [refreshKey])
  useEffect(() => { onVisibility(browserVisible) }, [browserVisible, onVisibility])
  useEffect(() => { localStorage.setItem('mc.workspace.layout', JSON.stringify(layout)) }, [layout])
  useEffect(() => {
    const media = matchMedia('(max-width: 1000px)')
    const change = () => setNarrow(media.matches)
    media.addEventListener('change', change)
    return () => media.removeEventListener('change', change)
  }, [])
  useEffect(() => {
    const element = container.current
    if (!element) return
    const observer = new ResizeObserver(() => {
      const length = type === 'horizontal' ? element.clientWidth : element.clientHeight
      const minimum = type === 'horizontal' ? 270 : 130
      const min = Math.min(45, minimum / Math.max(1, length) * 100)
      setBounds({ min, max: 100 - min })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [type])
  const clamp = (ratio: number) => Math.max(bounds.min, Math.min(bounds.max, ratio))
  const ratio = clamp(Number.isFinite(layout.ratio) ? layout.ratio : 70)
  const visible = (view: View) => maximized ? maximized === view : type === 'tabs' ? layout.view === view : view === 'browser' || layout.secondary === view
  const content = { browser, logs, results }
  const titles = { browser: '网站预览', logs: '运行日志', results: '采集结果' }
  return <section className="wb-workspace" aria-label="浏览器工作区">
    <div className="wb-workspace-bar"><div className="wb-tabs" role="tablist" aria-label="工作区视图">{(['browser', 'logs', 'results'] as View[]).map(view => <button key={view} role="tab" aria-selected={visible(view)} onClick={() => { setMaximized(null); setLayout(old => ({ ...old, view, secondary: view === 'browser' ? old.secondary : view })) }}>{titles[view]}</button>)}</div>
      <div className="wb-layout-actions"><select aria-label="工作区布局" value={type} disabled={narrow} onChange={e => { setMaximized(null); setLayout(old => ({ ...old, type: e.target.value, ratio: e.target.value === 'horizontal' ? 60 : 70 })) }}><option value="tabs">标签模式</option><option value="vertical">上下平铺</option><option value="horizontal">左右平铺</option></select><button onClick={() => { setLayout(defaults); setMaximized(null); onReset?.() }}>恢复布局</button></div>
    </div>
    <div ref={container} className={`wb-panels ${maximized || type === 'tabs' ? 'single' : type}`} style={maximized || type === 'tabs' ? undefined : { gridTemplateColumns: type === 'horizontal' ? `${ratio}fr 8px ${100 - ratio}fr` : undefined, gridTemplateRows: type === 'vertical' ? `${ratio}fr 8px ${100 - ratio}fr` : undefined }}>
      {(['browser', 'logs', 'results'] as View[]).map(view => <div key={view} className={`wb-panel panel-${view}`} style={{ display: visible(view) ? 'flex' : 'none', gridColumn: type === 'horizontal' && !maximized ? view === 'browser' ? 1 : 3 : undefined, gridRow: type === 'vertical' && !maximized ? view === 'browser' ? 1 : 3 : undefined }}>
        <div className="wb-panel-title"><span>{titles[view]}</span>{view !== 'browser' && type !== 'tabs' && <button onClick={() => setLayout(old => ({ ...old, secondary: view === 'logs' ? 'results' : 'logs' }))}>切换{view === 'logs' ? '结果' : '日志'}</button>}<button aria-label={maximized === view ? '退出最大化' : `最大化${titles[view]}`} onClick={() => setMaximized(maximized === view ? null : view)}>{maximized === view ? '还原' : '最大化'}</button></div>{content[view]}</div>)}
      {type !== 'tabs' && !maximized && <div className="wb-splitter" role="separator" tabIndex={0} aria-label="调整工作区分隔比例" aria-orientation={type === 'vertical' ? 'horizontal' : 'vertical'} aria-valuemin={Math.round(bounds.min)} aria-valuemax={Math.round(bounds.max)} aria-valuenow={Math.round(ratio)} style={{ gridColumn: type === 'horizontal' ? 2 : 1, gridRow: type === 'vertical' ? 2 : 1 }} onPointerDown={e => { e.currentTarget.setPointerCapture(e.pointerId); e.preventDefault() }} onPointerMove={e => { if (!e.currentTarget.hasPointerCapture(e.pointerId)) return; const rect = container.current!.getBoundingClientRect(); const next = type === 'horizontal' ? (e.clientX - rect.left) / rect.width * 100 : (e.clientY - rect.top) / rect.height * 100; setLayout(old => ({ ...old, ratio: clamp(next) })) }} onPointerUp={e => e.currentTarget.releasePointerCapture(e.pointerId)} onKeyDown={e => { if (['ArrowUp', 'ArrowLeft', 'ArrowDown', 'ArrowRight', 'Home', 'End'].includes(e.key)) { e.preventDefault(); setLayout(old => ({ ...old, ratio: clamp(e.key === 'Home' ? bounds.min : e.key === 'End' ? bounds.max : ratio + (['ArrowUp', 'ArrowLeft'].includes(e.key) ? -2 : 2)) })) } }} />}
    </div>
  </section>
}
