import { useEffect, useRef, useState } from 'react'
import { api, Resource, Results, Session, Task } from './api'
import { ResultsPanel } from './ResultsPanel'

interface Props {
  task: Task; session?: Session; busy: boolean
  onRefresh: () => void; onError: (message: string, opener?: HTMLElement) => void
}
const empty: Results = { records: [], files: [], exports: [] }

// This task owns its result state; inspecting it must not replace the workspace draft.
export function TaskResults({ task, session, busy, onRefresh, onError }: Props) {
  const [results, setResults] = useState<Results>(empty)
  const [resources, setResources] = useState<Resource[]>([])
  const [loaded, setLoaded] = useState(false)
  const [loadError, setLoadError] = useState(false)
  const [resourceError, setResourceError] = useState(false)
  const [working, setWorking] = useState(false)
  const [notice, setNotice] = useState('')
  const mounted = useRef(false)
  const actionPending = useRef(false)
  const revision = useRef(0)

  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    let stopped = false, timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      const version = revision.current
      try {
        const value = await api<Results>(`/tasks/${task.id}/results`)
        if (!stopped && version === revision.current) { setResults(value); setLoaded(true); setLoadError(false) }
      } catch { if (!stopped) setLoadError(true) }
      if (!stopped) timer = setTimeout(poll, 1800)
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [task.id])

  useEffect(() => {
    setResources([]); setResourceError(false)
    if (!session) return
    let stopped = false, timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const value = await api<{ resources: Resource[] }>(`/browser-sessions/${session.id}/resources`)
        if (!stopped) { setResources(value.resources); setResourceError(false) }
      } catch { if (!stopped) { setResources([]); setResourceError(true) } }
      if (!stopped) timer = setTimeout(poll, 1800)
    }
    void poll()
    return () => { stopped = true; clearTimeout(timer) }
  }, [session?.id])

  const perform = async (path: string, data: unknown, message: string) => {
    if (busy || actionPending.current) return
    const opener = document.activeElement as HTMLElement
    actionPending.current = true
    setWorking(true); setNotice('')
    revision.current++
    try {
      await api(path, data)
      if (!mounted.current) return
      revision.current++
      setNotice(message)
      onRefresh()
      try {
        const value = await api<Results>(`/tasks/${task.id}/results`)
        if (mounted.current) { setResults(value); setLoaded(true); setLoadError(false) }
      } catch { if (mounted.current) setLoadError(true) }
    } catch (error) { if (mounted.current) onError(error instanceof Error ? error.message : String(error), opener) }
    finally { actionPending.current = false; if (mounted.current) setWorking(false) }
  }
  const canDownload = session && !resourceError && !['preparing', 'cancelling', 'cancelled'].includes(task.state)
  const merged = [...new Map([...(results.resources || []), ...(session ? resources : [])].map(r => [r.id, r])).values()]
  return <section className="wb-task-results" aria-label="所选任务结果">
    {!loaded && !loadError && <p className="wb-task-result-notice" role="status">正在加载任务结果…</p>}
    {loadError && <p className="wb-task-result-notice wb-detail-error" role="status">结果暂时无法更新，正在重试。已加载的文件仍可查看。</p>}
    {notice && <p className="wb-task-result-notice" role="status">{notice}</p>}
    {!session && <p className="wb-task-result-notice">会话已关闭或被其他任务使用，已保存文件仍可下载；失败任务可使用“重试失败项”。</p>}
    {resourceError && <p className="wb-task-result-notice wb-detail-error" role="status">资源列表暂时无法更新，正在重试。</p>}
    <ResultsPanel initialView="files" results={results} taskId={task.id} resources={merged} sessionId={session?.id} busy={busy || working || !loaded}
      onExport={() => void perform(`/tasks/${task.id}/export`, {}, '采集数据已生成，可在“导出数据”中下载。')}
      onDownload={canDownload ? ids => void perform(`/tasks/${task.id}/downloads`, { session_id: session.id, resource_ids: ids }, '所选资源已加入此任务的下载队列。') : undefined} />
  </section>
}
