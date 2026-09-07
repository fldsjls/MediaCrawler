import { useEffect, useRef, useState } from 'react'
import { Session, wsUrl } from './api'

export function useBrowserPresentation(session: Session | undefined, visible: boolean, onDisconnected: () => void) {
  const [frame, setFrame] = useState(''), [connected, setConnected] = useState(false)
  const [failure, setFailure] = useState(''), [retry, setRetry] = useState(0)
  const video = useRef<HTMLVideoElement>(null)
  const suspended = useRef(false)
  const disconnected = useRef(onDisconnected)
  disconnected.current = onDisconnected
  const id = session?.id, token = session?.token
  const requested = session?.presentation?.mode || 'snapshot'
  const mode = failure ? 'snapshot' : requested
  const snapshotFps = session?.presentation?.snapshot_fps || 1
  const realtimeFps = session?.presentation?.realtime_fps || 60
  const selectedPage = session?.pages.find(page => page.selected)?.id
  const pageEpoch = session?.page_epoch
  useEffect(() => { setFailure(''); setFrame('') }, [id, requested])
  useEffect(() => {
    setConnected(false)
    setFrame('')
    suspended.current = false
    if (!id || !token || !visible) return
    let stopped = false
    if (mode === 'snapshot') {
      const ws = new WebSocket(wsUrl(`/browser-sessions/${id}/frames?token=${encodeURIComponent(token)}`))
      ws.onmessage = event => {
        const value = JSON.parse(event.data)
        if (value.type === 'frame' && !suspended.current && (pageEpoch === undefined || value.epoch === undefined || value.epoch === pageEpoch)) { setFrame(`data:image/jpeg;base64,${value.data}`); setConnected(true) }
      }
      ws.onclose = () => { if (!stopped) { setConnected(false); disconnected.current() } }
      return () => { stopped = true; ws.onclose = null; ws.close(); setConnected(false) }
    }

    let peer: RTCPeerConnection | undefined, peerId: string | undefined
    let received = false, failed = false
    let timer: ReturnType<typeof setTimeout>, gatherTimer: ReturnType<typeof setTimeout>
    let cancelGather: (() => void) | undefined
    const controller = new AbortController()
    const release = (value: string) => {
      void fetch(`/api/browser-sessions/${id}/rtc/${encodeURIComponent(value)}`, { method: 'DELETE', headers: { Authorization: `Bearer ${token}` } }).catch(() => {})
    }
    const fail = (message: string) => {
      if (stopped || failed) return
      failed = true
      if (received) disconnected.current()
      setConnected(false); setFailure(message)
    }
    const connect = async () => {
      try {
        if (!window.RTCPeerConnection) throw new Error('当前浏览器不支持 WebRTC')
        peer = new RTCPeerConnection({ iceServers: [] })
        // The browser owns native video encoding and codec negotiation.
        peer.addTransceiver('video', { direction: 'recvonly' })
        peer.onconnectionstatechange = () => {
          if (peer?.connectionState === 'failed' || peer?.connectionState === 'disconnected') fail('实时画面连接已断开')
        }
        peer.ontrack = event => {
          const element = video.current
          if (!element || stopped) return
          element.srcObject = event.streams[0] || new MediaStream([event.track])
          element.onloadeddata = () => { if (!stopped && !failed && !suspended.current) { received = true; clearTimeout(timer); setConnected(true) } }
          void element.play().catch(() => fail('浏览器未能播放实时画面'))
        }
        timer = setTimeout(() => { controller.abort(); fail('实时画面连接超时') }, 15000)
        await peer.setLocalDescription(await peer.createOffer())
        if (peer.iceGatheringState !== 'complete') await new Promise<void>((resolve, reject) => {
          const connection = peer!
          const clean = () => { clearTimeout(gatherTimer); connection.removeEventListener('icegatheringstatechange', finished); cancelGather = undefined }
          const finished = () => { if (connection.iceGatheringState === 'complete') { clean(); resolve() } }
          cancelGather = () => { clean(); reject(new Error('预览已隐藏或切换')) }
          connection.addEventListener('icegatheringstatechange', finished)
          gatherTimer = setTimeout(() => { clean(); reject(new Error('本机实时连接地址收集超时')) }, 5000)
        })
        if (stopped) return
        // Let a late answer provide the peer id for cleanup after hiding, but
        // never retain a pending fetch indefinitely if the service disappears.
        const requestTimer = setTimeout(() => controller.abort(), 15000)
        let response: Response, answer: { id?: string; sdp: string; detail?: unknown }
        try {
          response = await fetch(`/api/browser-sessions/${id}/rtc`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ token, sdp: peer.localDescription?.sdp, type: 'offer' }), signal: controller.signal })
          answer = await response.json()
        } finally { clearTimeout(requestTimer) }
        if (!response.ok) throw new Error(typeof answer.detail === 'string' ? answer.detail : '实时传输暂不可用')
        peerId = answer.id
        if (stopped) { if (peerId) release(peerId); return }
        await peer.setRemoteDescription({ sdp: answer.sdp, type: 'answer' })
      } catch (error) { fail(error instanceof Error ? error.message : '实时传输暂不可用') }
    }
    void connect()
    return () => {
      stopped = true; clearTimeout(timer); cancelGather?.(); clearTimeout(gatherTimer)
      if (peer) { peer.onconnectionstatechange = null; peer.ontrack = null; peer.close() }
      const element = video.current
      if (element) { element.onloadeddata = null; element.srcObject = null }
      if (peerId) release(peerId)
      setConnected(false)
    }
  }, [id, token, selectedPage, pageEpoch, visible, mode, snapshotFps, realtimeFps, retry])
  return { frame, connected, video, mode, failure, invalidate: () => { suspended.current = true; setConnected(false); setFrame('') }, retry: () => { setFailure(''); setRetry(value => value + 1) } }
}
