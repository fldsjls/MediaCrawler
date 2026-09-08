import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ChevronRight, Monitor, PanelsTopLeft, Globe, FolderInput, Settings } from 'lucide-react'
import { toast } from 'sonner'
import { useThemeStore } from '@/store/themeStore'
import { api, BrowserSettings, saved, Session, SettingsSection } from '../api'
import { TaskDefaults } from './TaskDefaults'
import { SettingsBlock, SettingsActions } from './SettingsLayout'
import { PlatformManager } from './PlatformManager'

interface Props {
  initialGroup?:string
  sessions: Session[]; platform: string; channel: string; busy: boolean; navCollapsed: boolean
  onChannel: (value: string) => void; onNavCollapsed: (value: boolean) => void; onLayout: () => void
  onPlatforms: () => Promise<void>; onCloseSession: (id: string) => void; onExternal: () => void
  onError: (message: string) => void
}
const groups = [
  { id: 'appearance', title: '外观布局', summary: '主题、导航与工作区布局', icon: PanelsTopLeft, items: [{ id: 'display', title: '显示与布局', summary: '当前浏览器的主题、导航宽度和面板排列。' }] },
  { id: 'browser', title: '浏览器预览', summary: '画面模式、帧率与会话', icon: Monitor, items: [{ id: 'presentation', title: '预览与浏览器默认值', summary: '自动切换、画面帧率以及新会话使用的浏览器。' }, { id: 'sessions', title: '浏览器会话', summary: '检查现有会话，或使用外部浏览器窗口。' }] },
  { id: 'platforms', title: '平台模板', summary: '网站入口与采集能力', icon: Globe, items: [{ id: 'platforms', title: '平台管理', summary: '新增、编辑和停用平台，选择已实现的功能模板。' }] },
  { id:'tasks', title:'任务默认值', summary:'采集范围、评论与自动操作', icon:Settings, items:[{id:'tasks',title:'采集与自动操作默认值',summary:'卡片未覆盖时使用的参数。'}] },
  { id:'downloads', title:'下载与工具', summary:'引擎、工具路径与传输', icon:Settings, items:[{id:'downloads',title:'下载器设置',summary:'HTTP、FFmpeg 与 N_m3u8DL-RE。'}] },
  { id:'exports', title:'导出与文件', summary:'输出目录、命名与格式', icon:FolderInput, items:[{id:'exports',title:'文件与导出默认值',summary:'每次运行独立保存。'}] },
  { id: 'data', title: '数据迁移', summary: '资料与登录信息导入', icon: FolderInput, items: [{ id: 'imports', title: '导入旧项目资料', summary: '复制数据、下载文件、登录备份或浏览器 Profile。' }] },
]

export function SettingsCenter(props: Props) {
  const [groupId, setGroup] = useState(props.initialGroup||'appearance'), [detail, setDetail] = useState<string|undefined>(['tasks','downloads','exports'].includes(props.initialGroup||'')?props.initialGroup:undefined)
  const [sections, setSections] = useState<SettingsSection[]>([])
  const heading = useRef<HTMLHeadingElement>(null)
  const group = groups.find(item => item.id === groupId)!
  const item = group.items.find(value => value.id === detail)
  const storage = sections.find(value => value.id === groupId)?.persistence
  const storageLabel: Record<string, string> = { localStorage: '当前浏览器', project_sqlite: '当前项目数据库', project_files: '当前项目文件目录' }
  useEffect(() => { void api<SettingsSection[]>('/settings/sections').then(setSections).catch(e => props.onError(e.message)) }, [])
  useEffect(() => { heading.current?.focus() }, [groupId, detail])
  return <section className="wb-settings-center">
    <aside className="wb-settings-categories" aria-label="设置分类"><h1>设置</h1>{groups.map(value => { const Icon = value.icon; return <button key={value.id} aria-current={value.id === groupId ? 'page' : undefined} onClick={() => { setGroup(value.id); setDetail(undefined) }}><Icon size={18} /><span>{value.title}<small>{value.summary}</small></span></button> })}</aside>
    <div className={`wb-settings-content ${detail === 'platforms' ? 'wide' : ''}`}>
      <div className="wb-settings-breadcrumb"><span>设置</span><ChevronRight size={14} /><button onClick={() => setDetail(undefined)}>{group.title}</button>{item && <><ChevronRight size={14} /><span>{item.title}</span></>}</div>
      {item && <button className="wb-settings-back" onClick={() => setDetail(undefined)}><ArrowLeft size={15} />返回{group.title}</button>}
      <h2 ref={heading} tabIndex={-1}>{item?.title || group.title}</h2>
      <p className="wb-settings-description">{item?.summary || group.summary}</p>
      {!detail && <div className="wb-settings-entries">{group.items.map(value => <button key={value.id} onClick={() => setDetail(value.id)}><span><strong>{value.title}</strong><small>{value.summary}</small></span><ChevronRight size={18} /></button>)}</div>}
      {detail && ['tasks','downloads','exports'].includes(detail) && <TaskDefaults group={detail} onError={props.onError} />}
      {detail === 'display' && <AppearanceSettings {...props} />}
      {detail === 'presentation' && <BrowserDefaults onSaved={value => props.onChannel(value.default_channel)} onError={props.onError} />}
      {detail === 'sessions' && <SessionSettings {...props} />}
      {detail === 'platforms' && <PlatformManager onChanged={props.onPlatforms} onError={props.onError} />}
      {detail === 'imports' && <ImportSettings platform={props.platform} channel={props.channel} onError={props.onError} />}
      {!detail && storage && <p className="wb-settings-scope">保存范围：{storageLabel[storage] || storage}</p>}
    </div>
  </section>
}

function AppearanceSettings({ navCollapsed, onNavCollapsed, onLayout }: Props) {
  const { theme, setTheme } = useThemeStore()
  const [layout, setLayout] = useState(() => saved('mc.workspace.layout', { type: 'vertical', ratio: 70, view: 'browser', secondary: 'logs' }).type)
  const changeLayout = (type: string) => {
    localStorage.setItem('mc.workspace.layout', JSON.stringify({ ...saved('mc.workspace.layout', { view: 'browser', secondary: 'logs' }), type, ratio: type === 'horizontal' ? 60 : 70 }))
    setLayout(type); onLayout()
  }
  return <div className="wb-settings-detail wb-settings-form">
    <p className="wb-settings-context"><strong>即时生效</strong><span>仅保存在当前浏览器，清理浏览器数据后恢复默认。</span></p>
    <SettingsBlock title="主题与导航" description="调整工作台的显示风格和导航宽度。"><div className="wb-settings-grid"><label>外观主题<select aria-label="外观主题" value={theme} onChange={e=>setTheme(e.target.value as 'light'|'dark'|'system')}><option value="light">浅色</option><option value="dark">深色</option><option value="system">跟随系统</option></select></label><label className="wb-settings-toggle"><span>使用紧凑导航</span><input type="checkbox" checked={navCollapsed} onChange={e=>onNavCollapsed(e.target.checked)}/></label></div></SettingsBlock>
    <SettingsBlock title="工作区布局" description="窄屏自动使用标签模式，卡片编辑始终使用独立弹窗。"><div className="wb-settings-grid"><label>面板排列<select aria-label="工作区布局" value={layout} onChange={e=>changeLayout(e.target.value)}><option value="vertical">上下平铺</option><option value="horizontal">左右平铺</option><option value="tabs">标签模式</option></select></label></div></SettingsBlock>
    <SettingsActions status="修改后自动保存"><button onClick={()=>{setTheme('system');onNavCollapsed(false);changeLayout('vertical');toast.success('外观与布局已恢复默认')}}>恢复默认外观布局</button></SettingsActions>
  </div>
}

function BrowserDefaults({onSaved,onError}:{onSaved:(settings:BrowserSettings)=>void;onError:(message:string)=>void}) {
  const [value,setValue]=useState<BrowserSettings>(),[original,setOriginal]=useState<BrowserSettings>(),[busy,setBusy]=useState(false)
  useEffect(()=>{let active=true;void api<BrowserSettings>('/settings/browser').then(v=>{if(active){setValue(v);setOriginal(v)}}).catch(e=>{if(active)onError(e.message)});return()=>{active=false}},[])
  const dirty=JSON.stringify(value)!==JSON.stringify(original)
  const save=async()=>{if(!value)return;setBusy(true);try{const next=await api<BrowserSettings>('/settings/browser',value,'PATCH');setValue(next);setOriginal(next);onSaved(next);toast.success('浏览器设置已保存')}catch(e){onError(e instanceof Error?e.message:String(e))}finally{setBusy(false)}}
  if(!value)return <p role="status">正在读取浏览器设置…</p>
  return <form className="wb-settings-detail wb-settings-form" onSubmit={e=>{e.preventDefault();void save()}}>
    <p className="wb-settings-context"><strong>新会话生效</strong><span>由当前项目保存，已有会话保持创建时的配置。</span></p>
    <SettingsBlock title="预览画面" description="实时模式仅传输画面，切换模式不会重建浏览器或改变登录状态。">
      <label className="wb-settings-toggle"><span>自动切换预览模式<small>空闲与人工操作使用实时画面，自动采集使用低刷新画面。</small></span><input disabled={busy} type="checkbox" checked={value.auto_switch} onChange={e=>setValue({...value,auto_switch:e.target.checked})}/></label>
      <div className="wb-settings-grid"><label>低刷新帧率<select disabled={busy} value={value.snapshot_fps} onChange={e=>setValue({...value,snapshot_fps:Number(e.target.value) as BrowserSettings['snapshot_fps']})}>{[1,2,5].map(fps=><option value={fps} key={fps}>{fps} 帧 / 秒</option>)}</select></label><label>实时画面帧率<select disabled={busy} value={value.realtime_fps} onChange={e=>setValue({...value,realtime_fps:Number(e.target.value) as BrowserSettings['realtime_fps']})}>{[10,20,30,60].map(fps=><option value={fps} key={fps}>{fps} 帧 / 秒</option>)}</select></label></div>
    </SettingsBlock>
    <SettingsBlock title="浏览器与会话" description="关闭登录复用后，新会话使用独立资料目录。">
      <div className="wb-settings-grid"><label>新会话浏览器<select disabled={busy} value={value.default_channel} onChange={e=>setValue({...value,default_channel:e.target.value as BrowserSettings['default_channel']})}><option value="chromium">Chromium（独立 Playwright）</option><option value="msedge">Microsoft Edge</option></select></label><label>页面导航超时（秒）<input disabled={busy} type="number" min={5} max={600} value={value.navigation_timeout} onChange={e=>setValue({...value,navigation_timeout:Number(e.target.value)})}/></label></div>
      <label className="wb-settings-toggle"><span>新会话复用登录状态</span><input disabled={busy} type="checkbox" checked={value.reuse_login} onChange={e=>setValue({...value,reuse_login:e.target.checked})}/></label>
    </SettingsBlock>
    <SettingsActions status={dirty?'有未保存的修改':'已与项目保存值一致'}><button type="button" disabled={busy||!dirty} onClick={()=>setValue(original)}>撤销修改</button><button className="wb-primary" disabled={busy||!dirty} type="submit">{busy?'保存中…':'保存浏览器设置'}</button></SettingsActions>
  </form>
}

function SessionSettings({ sessions, busy, onCloseSession, onExternal }: Props) {
  return <div className="wb-settings-detail wb-settings-form">
    <SettingsBlock title="现有浏览器会话" description="会话按平台独立保存，关闭会话不会删除已保存的任务产物。" action={<span className="wb-settings-count">{sessions.length} 个会话</span>}>
      {sessions.length===0?<div className="wb-settings-empty">目前没有浏览器会话。可在工作台打开目标网站。</div>:sessions.map(value=><div className="wb-settings-session" key={value.id}><span><strong>{value.platform}</strong><small>{value.external?'外部窗口':'网页预览'} · {value.id.slice(0,8)}</small></span><button disabled={busy} onClick={()=>onCloseSession(value.id)}>关闭会话</button></div>)}
    </SettingsBlock>
    <SettingsBlock title="外部浏览器" description="将重新建立会话。请先结束任务并关闭当前预览会话。"><button disabled={busy} onClick={onExternal}>用外部浏览器打开当前目标</button></SettingsBlock>
  </div>
}

function ImportSettings({ platform, channel, onError }: { platform: string; channel: string; onError: (message: string) => void }) {
  const [kind, setKind] = useState('data'), [path, setPath] = useState(''), [busy, setBusy] = useState(false)
  const submit = async () => { setBusy(true); try { const value = await api<{ destination: string }>('/imports', { source: path, kind, platform, channel }); toast.success(`已导入：${value.destination}`) } catch (e) { onError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) } }
  return <form className="wb-settings-detail wb-settings-form" onSubmit={e=>{e.preventDefault();void submit()}}>
    <p className="wb-settings-context"><strong>导入副本</strong><span>保留源资料，不覆盖已有数据或登录信息。</span></p>
    <SettingsBlock title="选择导入资料" description="导入数据会保存在独立归档目录。"><div className="wb-settings-grid">
      <label>导入类型<select disabled={busy} value={kind} onChange={e=>setKind(e.target.value)}><option value="data">数据 / 下载文件归档</option><option value="storage-state">登录 storage_state 备份</option><option value="profile">浏览器 Profile（当前平台）</option></select></label>
      <label className="wb-settings-full">源文件或目录的完整路径<input disabled={busy} value={path} onChange={e=>setPath(e.target.value)} placeholder="C:\…" required/></label>
    </div></SettingsBlock>
    <SettingsBlock title="导入目标" description={kind==='profile'?'Profile 导入前须关闭所有相关浏览器。':'登录资料按当前平台保存，归档数据保留在项目目录。'}><dl className="wb-settings-facts"><div><dt>当前平台</dt><dd>{platform}</dd></div><div><dt>浏览器</dt><dd>{channel}</dd></div></dl></SettingsBlock>
    <SettingsActions status={busy?'正在复制资料…':'确认来源后导入，不会移动原文件'}><button className="wb-primary" type="submit" disabled={busy||!path}>{busy?'正在导入…':'导入副本'}</button></SettingsActions>
  </form>
}
