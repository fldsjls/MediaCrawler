import { useEffect } from 'react'
import { useThemeStore } from '@/store/themeStore'
export function Sidebar({ onShowDisclaimer, connection = 'connecting' }: { onShowDisclaimer?: () => void; connection?: 'connecting' | 'connected' | 'disconnected' }) {
 const { theme, setTheme } = useThemeStore()
 useEffect(() => { if (!localStorage.getItem('mediacrawler_theme')) setTheme('system') }, [setTheme])
 return <header className="wb-app-header"><div className="wb-brand"><span className="wb-brand-mark" aria-hidden="true">M</span><strong>MediaCrawler</strong><span>工作台</span></div><div className="wb-header-actions"><span className={`wb-api-status ${connection}`} role="status" aria-label={`服务${connection === 'connected' ? '已连接' : connection === 'disconnected' ? '未连接' : '连接中'}`}><i aria-hidden="true" />{connection === 'connected' ? '已连接' : connection === 'disconnected' ? '未连接' : '连接中'}</span><button onClick={onShowDisclaimer}>使用协议</button><label className="wb-theme-label"><span>外观</span><select aria-label="外观主题" value={theme} onChange={e => setTheme(e.target.value as 'light'|'dark'|'system')}><option value="light">浅色</option><option value="dark">深色</option><option value="system">跟随系统</option></select></label></div></header>
}
