import { Terminal } from '@/components/console/Terminal'
import { useLogWebSocket } from '@/hooks/useWebSocket'

export function MainContent() {
  // Connect to WebSocket for logs
  useLogWebSocket()

  return (
    <main className="flex min-h-[420px] min-w-0 h-[65vh] flex-col overflow-hidden relative z-10 lg:h-full lg:min-h-0">
      <Terminal />
    </main>
  )
}
