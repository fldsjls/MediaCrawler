import { CircleAlert, CircleCheck, Clock3, LoaderCircle, PauseCircle, XCircle } from 'lucide-react'
import { states } from '../api'

export const resourceStates: Record<string, string> = {
  discovered: '可下载', pending: '等待下载', running: '下载中', succeeded: '已下载',
  failed: '下载失败', unavailable: '暂不可下载', cancelled: '已取消',
}

export function StatusBadge({ state, resource = false }: { state: string; resource?: boolean }) {
  const Icon = state === 'succeeded' || state === 'discovered' ? CircleCheck
    : ['failed', 'partial', 'interrupted', 'unavailable'].includes(state) ? CircleAlert
    : ['paused', 'pausing'].includes(state) ? PauseCircle
    : state === 'cancelled' ? XCircle
    : ['running', 'preparing'].includes(state) ? LoaderCircle : Clock3
  return <span className="wb-status" data-state={state}>
    <Icon size={16} strokeWidth={1.7} aria-hidden="true" />
    {(resource ? resourceStates : states)[state] || state}
  </span>
}
