"""Local WebRTC video transport. Input remains on the authenticated control channel."""
import asyncio
import time
import uuid
from fractions import Fraction
from io import BytesIO

from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, VideoStreamTrack
from av import VideoFrame
from PIL import Image


class BrowserVideoTrack(VideoStreamTrack):
    def __init__(self, subscription):
        super().__init__()
        self.subscription = subscription
        self.started = time.monotonic()
        self.last_pts = -1

    async def recv(self):
        while True:
            packet = await self.subscription.recv()
            if packet.epoch != self.subscription.hub.epoch:
                continue
            # Decode away from the browser/control event loop.
            def decode():
                with Image.open(BytesIO(packet.jpeg)) as picture:
                    return VideoFrame.from_image(picture.convert('RGB'))
            frame = await asyncio.to_thread(decode)
            if packet.epoch != self.subscription.hub.epoch:
                continue
            self.last_pts = max(self.last_pts + 1, int((time.monotonic() - self.started) * 90000))
            frame.pts, frame.time_base = self.last_pts, Fraction(1, 90000)
            return frame


class RTCStreams:
    def __init__(self, session):
        self.session = session
        self.peers = {}
        self.closed = False
        self.offers = {}
        self.closing = {}
        self._close_task = None

    async def offer(self, sdp, description_type):
        if self.closed:
            raise ValueError('浏览器会话已关闭')
        if len(self.peers) >= 4:
            raise ValueError('实时预览连接已达上限，请关闭其他预览窗口')
        # Local-only application: no external STUN/TURN service or media relay.
        peer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        peer_id = uuid.uuid4().hex
        # Reserve before the first await; pending negotiations count towards the limit.
        self.peers[peer_id] = (peer, None, None, None)
        self.offers[peer_id] = asyncio.current_task()

        @peer.on('connectionstatechange')
        async def state_changed():
            if peer.connectionState in ('failed', 'closed'):
                asyncio.create_task(self.close_peer(peer_id))

        async def expire_unconnected():
            await asyncio.sleep(20)
            if peer.connectionState != 'connected':
                await self.close_peer(peer_id)

        try:
            sub = await self.session.frame_hub.subscribe(self.session.preview_settings['realtime_fps'], 'realtime')
            track = BrowserVideoTrack(sub)
            @track.on('ended')
            def track_ended():
                # aiortc stops the sender track when recv fails. Closing the peer
                # propagates producer loss to viewers instead of freezing the video.
                asyncio.create_task(self.close_peer(peer_id))
            timer = asyncio.create_task(expire_unconnected())
            self.peers[peer_id] = (peer, track, sub, timer)
            await peer.setRemoteDescription(RTCSessionDescription(sdp=sdp, type=description_type))
            if not any(t.kind == 'video' for t in peer.getTransceivers()):
                raise ValueError('实时预览需要视频接收通道')
            peer.addTrack(track)
            await asyncio.wait_for(peer.setLocalDescription(await peer.createAnswer()), timeout=12)
            return dict(id=peer_id, sdp=peer.localDescription.sdp, type=peer.localDescription.type)
        except BaseException:
            await self.close_peer(peer_id)
            raise
        finally:
            self.offers.pop(peer_id, None)

    async def close_peer(self, peer_id):
        value = self.peers.pop(peer_id, None)
        if value:
            peer, track, sub, timer = value
            caller = asyncio.current_task()
            pending = self.offers.pop(peer_id, None)
            # Cancel negotiation before cleanup, so it cannot register after closure.
            if pending and pending is not caller:
                pending.cancel()
            async def cleanup():
                if pending and pending is not caller:
                    await asyncio.gather(pending, return_exceptions=True)
                if timer and timer is not caller:
                    timer.cancel()
                if track:
                    track.stop()
                try:
                    if sub:
                        await sub.close()
                finally:
                    await peer.close()
            cleanup_task = asyncio.create_task(cleanup())
            self.closing[peer_id] = cleanup_task
            cleanup_task.add_done_callback(lambda _: self.closing.pop(peer_id, None))
            await asyncio.shield(cleanup_task)

    async def close(self):
        self.closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close_all())
        # A disconnected HTTP caller must not cancel aiortc.close halfway through:
        # its internal completion Future would then never resolve on another close.
        await asyncio.shield(self._close_task)

    async def _close_all(self):
        for peer_id in list(self.peers):
            await self.close_peer(peer_id)
        if self.closing:
            await asyncio.gather(*(asyncio.shield(task) for task in list(self.closing.values())))
