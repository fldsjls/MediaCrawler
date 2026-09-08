export interface Platform { category?: string; tags?: string[]; builtin?: boolean; enabled?: boolean; template?: string; template_config?: Record<string, unknown>; collect?: boolean; id: string; name: string; url: string; inputs: string[]; comments: boolean; media?: boolean; media_modes?: string[]; video?: boolean; images?: boolean; video_modes?: string[]; video_strategy?: string; verification?: string; outputs: string[] }
export interface Config { platform: string; mode: string; target: string; max_items: number; max_downloads: number; max_comments: number; comments: boolean; subcomments: boolean; media?: boolean; download_video: boolean; download_images: boolean; operation: 'collect' | 'download'; output: string; login: string; cookies: string; start: number; wait_ms: number; selector: string; session_id?: string }
export interface Task { name?: string; current_step?:string; steps_completed?:number; retry_of?:string; steps?:{id:string;kind:string;name:string;state:string;settings:Record<string,unknown>;error:string}[]; id: string; state: string; config: Config; created: number; session_id?: string; error: string; counts: Record<string, number> }
export type PreviewPreference = 'auto' | 'realtime' | 'snapshot'
export interface BrowserSettings { auto_switch: boolean; reuse_login:boolean; navigation_timeout:number; snapshot_fps: 1 | 2 | 5; realtime_fps: 10 | 20 | 30 | 60; default_channel: 'chromium' | 'msedge' }
export interface SettingsSection { id: string; title: string; summary: string; persistence: string }
export interface Session { navigation_timeout?:number; page_epoch?: number; id: string; token: string; platform: string; manual: boolean; finished: boolean; task_id?: string; external: boolean; navigation_error?: string; presentation?: { preference: PreviewPreference; mode: 'realtime' | 'snapshot'; snapshot_fps: number; realtime_fps: number }; pages: { id: string; url: string; selected: boolean }[] }
export interface Event { seq: number; type: string; created: number; payload: { message?: string; level?: string; state?: string; phase?: string; error?: string; path?: string } }
export interface RecordItem { id: string; kind: string; title: string; parent_id?: string; fields?: unknown; target?: string }
export interface ResultFile { id: string; title: string; state: string; path: string; error: string; size?: number; parent_id?: string }
export interface Resource { id: string; title: string; kind: 'video' | 'audio' | 'image' | 'file'; format?: string; quality?: string; width?: number; height?: number; size?: number; page_url?: string; parent_id?: string; source?: string; origin?: 'adapter' | 'browser'; state: string; error?: string }
export interface Results { records: RecordItem[]; files: ResultFile[]; exports: string[]; resources?: Resource[] }
export const ended = new Set(['cancelled', 'succeeded', 'partial', 'failed', 'interrupted'])
export const states: Record<string, string> = { queued: '排队中', preparing: '准备中', running: '采集中', waiting_login: '等待登录', pausing: '正在暂停', paused: '已暂停', cancelling: '正在取消', cancelled: '已取消', succeeded: '成功', partial: '部分成功', failed: '失败', interrupted: '已中断', pending: '等待下载' }
export async function api<T>(path: string, data?: unknown, method?: string, submissionKey?:string): Promise<T> {
  const response = await fetch(`/api${path}`, { method: method || (data === undefined ? 'GET' : 'POST'), headers: data === undefined ? undefined : { 'Content-Type': 'application/json', ...(submissionKey?{'Idempotency-Key':submissionKey}:{}) }, body: data === undefined ? undefined : JSON.stringify(data) })
  if (!response.ok) { const error = await response.json().catch(() => ({})); throw new Error(typeof error.detail === 'string' ? error.detail : JSON.stringify(error.detail || response.statusText)) }
  return response.json()
}
export function wsUrl(path: string) { return `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api${path}` }
export function fileUrl(task: string, path: string) { return `/api/tasks/${task}/file?path=${encodeURIComponent(path)}` }
export function saved<T>(key: string, fallback: T): T { try { return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback } catch { return fallback } }
