import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ChevronRight, Monitor, PanelsTopLeft, Globe, FolderInput } from 'lucide-react'
import { toast } from 'sonner'
import { useThemeStore } from '@/store/themeStore'
import { api, BrowserSettings, saved, Session, SettingsSection } from './api'
import { PlatformManager } from './PlatformManager'

interface Props {
  sessions: Session[]; platform: string; channel: string; busy: boolean; navCollapsed: boolean
  onChannel: (value: string) => void; onNavCollapsed: (value: boolean) => void; onLayout: () => void
  onPlatforms: () => Promise<void>; onCloseSession: (id: string) => void; onExternal: () => void
  onError: (message: string) => void
}
const groups = [
  { id: 'appearance', title: '外观布局', summary: '主题、导航与工作区布局', icon: PanelsTopLeft, items: [{ id: 'display', title: '显示与布局', summary: '当前浏览器的主题、导航宽度和面板排列。' }] },
  { id: 'browser', title: '浏览器预览', summary: '画面模式、帧率与会话', icon: Monitor, items: [{ id: 'presentation', title: '预览与浏览器默认值', summary: '自动切换、画面帧率以及新会话使用的浏览器。' }, { id: 'sessions', title: '浏览器会话', summary: '检查现有会话，或使用外部浏览器窗口。' }] },
  { id: 'platforms', title: '平台模板', summary: '网站入口与采集能力', icon: Globe, items: [{ id: 'platforms', title: '平台管理', summary: '新增、编辑和停用平台，选择已实现的功能模板。' }] },
  { id: 'data', title: '数据迁移', summary: '资料与登录信息导入', icon: FolderInput, items: [{ id: 'imports', title: '导入旧项目资料', summary: '复制数据、下载文件、登录备份或浏览器 Profile。' }] },
]

export function SettingsCenter(props: Props) {
  const [groupId, setGroup] = useState('appearance'), [detail, setDetail] = useState<string>()
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
  return <div className="wb-settings-detail"><p className="wb-settings-scope">仅保存在当前浏览器；清理浏览器数据后恢复默认。</p><label>外观主题<select aria-label="外观主题" value={theme} onChange={e => setTheme(e.target.value as 'light' | 'dark' | 'system')}><option value="light">浅色</option><option value="dark">深色</option><option value="system">跟随系统</option></select></label><label className="wb-check"><input type="checkbox" checked={navCollapsed} onChange={e => onNavCollapsed(e.target.checked)} />使用紧凑导航</label><label>工作区布局<select aria-label="工作区布局" value={layout} onChange={e => changeLayout(e.target.value)}><option value="vertical">上下平铺</option><option value="horizontal">左右平铺</option><option value="tabs">标签模式</option></select></label><p className="wb-muted">窄屏自动使用标签模式。采集配置栏始终展开。</p><button onClick={() => { setTheme('system'); onNavCollapsed(false); changeLayout('vertical'); toast.success('外观与布局已恢复默认') }}>恢复默认外观布局</button></div>
}

function BrowserDefaults({ onSaved, onError }: { onSaved: (settings: BrowserSettings) => void; onError: (message: string) => void }) {
  const [value, setValue] = useState<BrowserSettings>(), [busy, setBusy] = useState(false)
  useEffect(() => { void api<BrowserSettings>('/settings/browser').then(setValue).catch(e => onError(e.message)) }, [])
  const save = async () => { if (!value) return; setBusy(true); try { const next = await api<BrowserSettings>('/settings/browser', value, 'PATCH'); setValue(next); onSaved(next); toast.success('浏览器设置已保存') } catch (e) { onError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) } }
  if (!value) return <p role="status">正在读取浏览器设置…</p>
  return <form className="wb-settings-detail" onSubmit={e => { e.preventDefault(); void save() }}><p className="wb-settings-scope">由本机项目保存，修改后对新建会话生效。已有会话保留创建时的预览参数。</p><label className="wb-check"><input type="checkbox" checked={value.auto_switch} onChange={e => setValue({ ...value, auto_switch: e.target.checked })} />自动切换预览模式</label><p className="wb-muted">开启后，空闲和人工操作使用实时画面，自动采集使用低刷新画面。</p><div className="wb-fields"><label>低刷新帧率<select aria-label="低刷新帧率" value={value.snapshot_fps} onChange={e => setValue({ ...value, snapshot_fps: Number(e.target.value) as BrowserSettings['snapshot_fps'] })}>{[1, 2, 5].map(fps => <option value={fps} key={fps}>{fps} 帧 / 秒</option>)}</select></label><label>实时画面帧率<select aria-label="实时画面帧率" value={value.realtime_fps} onChange={e => setValue({ ...value, realtime_fps: Number(e.target.value) as BrowserSettings['realtime_fps'] })}>{[10, 20, 30, 60].map(fps => <option value={fps} key={fps}>{fps} 帧 / 秒</option>)}</select></label></div><label>新会话浏览器<select aria-label="新会话浏览器" value={value.default_channel} onChange={e => setValue({ ...value, default_channel: e.target.value as BrowserSettings['default_channel'] })}><option value="chromium">Chromium（独立 Playwright）</option><option value="msedge">Microsoft Edge</option></select></label><p className="wb-muted">实时模式仅传输画面。切换显示模式不重建浏览器，也不改变登录状态。</p><button className="wb-primary" disabled={busy} type="submit">保存浏览器设置</button></form>
}

function SessionSettings({ sessions, busy, onCloseSession, onExternal }: Props) {
  return <div className="wb-settings-detail"><p>会话按平台独立保存。外部窗口会重新建立会话；请先结束任务并关闭当前预览会话。</p><button disabled={busy} onClick={onExternal}>用外部浏览器打开当前目标</button><h3>现有浏览器会话</h3>{sessions.length === 0 && <p className="wb-muted">目前没有浏览器会话。</p>}{sessions.map(value => <div className="wb-settings-session" key={value.id}><span>{value.platform}<small>{value.external ? '外部窗口' : '网页预览'} · {value.id.slice(0, 8)}</small></span><button disabled={busy} onClick={() => onCloseSession(value.id)}>关闭会话</button></div>)}</div>
}

function ImportSettings({ platform, channel, onError }: { platform: string; channel: string; onError: (message: string) => void }) {
  const [kind, setKind] = useState('data'), [path, setPath] = useState(''), [busy, setBusy] = useState(false)
  const submit = async () => { setBusy(true); try { const value = await api<{ destination: string }>('/imports', { source: path, kind, platform, channel }); toast.success(`已导入：${value.destination}`) } catch (e) { onError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) } }
  return <form className="wb-settings-detail" onSubmit={e => { e.preventDefault(); void submit() }}><p>不自动覆盖数据或登录信息。Profile 导入前须关闭所有相关浏览器；导入的数据保留在独立归档目录。</p><p className="wb-settings-scope">当前平台：{platform} · 浏览器：{channel}</p><label>导入类型<select aria-label="导入类型" value={kind} onChange={e => setKind(e.target.value)}><option value="data">数据 / 下载文件归档</option><option value="storage-state">登录 storage_state 备份</option><option value="profile">浏览器 Profile（当前平台）</option></select></label><label>源文件或目录的完整路径<input value={path} onChange={e => setPath(e.target.value)} placeholder="C:\…" required /></label><button type="submit" disabled={busy || !path}>导入副本</button></form>
}
