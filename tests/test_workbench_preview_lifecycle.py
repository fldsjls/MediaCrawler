"""Isolated transport lifecycle tests: no browser process or listening server."""
import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from mediacrawler.workbench.browser.preview.frames import Frame, FrameHub, Subscription
from mediacrawler.workbench.browser.preview.rtc import BrowserVideoTrack, RTCStreams
from mediacrawler.workbench.browser.preview import rtc


def jpeg(color):
    output = BytesIO()
    Image.new('RGB', (1280, 720), color).save(output, format='JPEG')
    return output.getvalue()


class Peer:
    instances = []

    def __init__(self, *_args):
        self.connectionState = 'new'
        self.localDescription = SimpleNamespace(sdp='answer', type='answer')
        self.closed = False
        self.instances.append(self)

    def on(self, _name):
        return lambda function: function

    async def setRemoteDescription(self, _value):
        pass

    def getTransceivers(self):
        return [SimpleNamespace(kind='video')]

    def addTrack(self, _track):
        pass

    async def createAnswer(self):
        return None

    async def setLocalDescription(self, _value):
        pass

    async def close(self):
        self.closed = True


class DelayedHub:
    epoch = 0

    def __init__(self):
        self.gate = asyncio.Event()
        self.subscriptions = []

    async def subscribe(self, *_args):
        await self.gate.wait()
        sub = SimpleNamespace(closed=False, hub=self)

        async def close():
            sub.closed = True
        sub.close = close
        self.subscriptions.append(sub)
        return sub


@pytest.fixture
def fake_peers(monkeypatch):
    Peer.instances = []
    monkeypatch.setattr(rtc, 'RTCPeerConnection', Peer)
    return Peer.instances


@pytest.mark.asyncio
async def test_pending_offers_count_towards_limit(fake_peers):
    hub = DelayedHub()
    streams = RTCStreams(SimpleNamespace(frame_hub=hub, preview_settings={'realtime_fps': 20}))
    pending = [asyncio.create_task(streams.offer('v=0', 'offer')) for _ in range(4)]
    await asyncio.sleep(0)
    try:
        with pytest.raises(ValueError, match='上限'):
            await streams.offer('v=0', 'offer')
        assert len(streams.peers) == len(fake_peers) == 4
        hub.gate.set()
        await asyncio.gather(*pending)
    finally:
        await streams.close()
    assert all(peer.closed for peer in fake_peers)
    assert all(sub.closed for sub in hub.subscriptions)


@pytest.mark.asyncio
async def test_close_cancels_pending_subscription_without_late_peer(fake_peers):
    hub = DelayedHub()
    streams = RTCStreams(SimpleNamespace(frame_hub=hub, preview_settings={'realtime_fps': 20}))
    pending = asyncio.create_task(streams.offer('v=0', 'offer'))
    await asyncio.sleep(0)
    await asyncio.wait_for(streams.close(), 1)
    hub.gate.set()
    assert isinstance((await asyncio.gather(pending, return_exceptions=True))[0], asyncio.CancelledError)
    assert not streams.peers and not streams.offers and not streams.closing
    assert fake_peers[0].closed
    with pytest.raises(ValueError, match='关闭'):
        await streams.offer('v=0', 'offer')


@pytest.mark.asyncio
async def test_subscription_failure_closes_reserved_peer(fake_peers):
    class BrokenHub:
        async def subscribe(self, *_args):
            raise ValueError('subscription closed')
    streams = RTCStreams(SimpleNamespace(frame_hub=BrokenHub(), preview_settings={'realtime_fps': 20}))
    with pytest.raises(ValueError, match='subscription closed'):
        await streams.offer('v=0', 'offer')
    assert fake_peers[0].closed and not streams.peers and not streams.offers


@pytest.mark.asyncio
async def test_close_during_negotiation_closes_subscription(fake_peers, monkeypatch):
    entered = asyncio.Event()
    async def wait_for_remote(_self, _value):
        entered.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(Peer, 'setRemoteDescription', wait_for_remote)
    hub = DelayedHub()
    hub.gate.set()
    streams = RTCStreams(SimpleNamespace(frame_hub=hub, preview_settings={'realtime_fps': 20}))
    pending = asyncio.create_task(streams.offer('v=0', 'offer'))
    await entered.wait()
    await asyncio.wait_for(streams.close(), 1)
    await asyncio.gather(pending, return_exceptions=True)
    assert fake_peers[0].closed and hub.subscriptions[0].closed
    assert not streams.peers and not streams.offers


class Page:
    def is_closed(self):
        return False

    async def set_viewport_size(self, _size):
        pass

    async def screenshot(self, **_kwargs):
        return jpeg('red')


@pytest.mark.asyncio
async def test_browser_disconnect_wakes_existing_subscriber():
    connected = True
    session = SimpleNamespace(page=Page(), browser=SimpleNamespace(is_connected=lambda: connected))
    hub = FrameHub(session)
    sub = await hub.subscribe(30)
    try:
        await asyncio.wait_for(sub.recv(), 1)
        connected = False
        with pytest.raises(ValueError, match='断开'):
            # A capture already underway may publish once before the loop observes disconnect.
            while True:
                await asyncio.wait_for(sub.recv(), 1)
        assert hub.error and hub.mode == 'idle'
    finally:
        await hub.close()
    assert not hub.subscribers and hub.producer is None


@pytest.mark.asyncio
async def test_closing_last_page_ends_frame_subscription():
    session = SimpleNamespace(page=None, context=SimpleNamespace(pages=[]),
                              browser=SimpleNamespace(is_connected=lambda: True))
    hub = FrameHub(session)
    sub = await hub.subscribe(1)
    try:
        with pytest.raises(ValueError, match='没有可预览页面'):
            await asyncio.wait_for(sub.recv(), 1)
    finally:
        await hub.close()


@pytest.mark.asyncio
async def test_epoch_change_during_screenshot_discards_old_frame():
    entered, release = asyncio.Event(), asyncio.Event()
    class SlowPage(Page):
        calls = 0
        async def screenshot(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                entered.set()
                await release.wait()
                return jpeg('red')
            return jpeg('blue')
    page = SlowPage()
    hub = FrameHub(SimpleNamespace(page=page, browser=SimpleNamespace(is_connected=lambda: True)))
    sub = await hub.subscribe(30)
    try:
        await entered.wait()
        # Even A -> B -> A during the await must invalidate the old capture.
        hub.invalidate()
        release.set()
        packet = await asyncio.wait_for(sub.recv(), 1)
        assert packet.epoch == hub.epoch == 1
        assert Image.open(BytesIO(packet.jpeg)).getpixel((0, 0))[2] > 250
    finally:
        await hub.close()


@pytest.mark.asyncio
async def test_restart_and_transport_switch_do_not_increment_epoch():
    class Context:
        async def new_cdp_session(self, _page):
            raise RuntimeError('Use screenshot fallback')
    hub = FrameHub(SimpleNamespace(page=Page(), context=Context(), browser=SimpleNamespace(is_connected=lambda: True)))
    first = await hub.subscribe(30)
    await asyncio.wait_for(first.recv(), 1)
    assert hub.epoch == 0
    await first.close()
    realtime = await hub.subscribe(30, 'realtime')
    try:
        assert (await asyncio.wait_for(realtime.recv(), 1)).epoch == 0
        snapshot = await hub.subscribe(30)
        await realtime.close()
        assert (await asyncio.wait_for(snapshot.recv(), 1)).epoch == 0
        assert hub.epoch == 0
    finally:
        await hub.close()


@pytest.mark.asyncio
async def test_rtc_discards_frame_invalidated_during_decode(monkeypatch):
    hub = FrameHub(SimpleNamespace(page=None, browser=None))
    sub = Subscription(hub, 20, 'realtime')
    hub.subscribers.add(sub)
    sub.put(Frame(jpeg('red'), 1, 0, 'screenshot', 0))
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0
    async def delayed_decode(function):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return function()
    monkeypatch.setattr(rtc.asyncio, 'to_thread', delayed_decode)
    track = BrowserVideoTrack(sub)
    pending = asyncio.create_task(track.recv())
    await entered.wait()
    hub.invalidate()
    sub.put(Frame(jpeg('blue'), 2, 0, 'screenshot', hub.epoch))
    release.set()
    try:
        frame = await asyncio.wait_for(pending, 1)
        assert calls == 2 and frame.to_image().getpixel((0, 0))[2] > 250
    finally:
        track.stop()
        await hub.close()


@pytest.mark.asyncio
async def test_sender_track_end_closes_peer_and_subscription(fake_peers):
    hub = DelayedHub()
    hub.gate.set()
    streams = RTCStreams(SimpleNamespace(frame_hub=hub, preview_settings={'realtime_fps': 20}))
    answer = await streams.offer('v=0', 'offer')
    track = streams.peers[answer['id']][1]
    track.stop()  # RTCRtpSender does this when FrameHub's terminal notification raises.
    async def wait_closed():
        while not fake_peers[0].closed:
            await asyncio.sleep(0)
    await asyncio.wait_for(wait_closed(), 1)
    assert not streams.peers and hub.subscriptions[0].closed
    await streams.close()


@pytest.mark.asyncio
async def test_cdp_transient_size_and_static_frames_never_trigger_screenshot():
    class CDP:
        def __init__(self):
            self.commands = []
        def on(self, _event, callback):
            self.callback = callback
        async def send(self, method, _params=None):
            self.commands.append(method)
        async def detach(self):
            pass
        def frame(self, data):
            import base64
            self.callback({'sessionId': 1, 'data': base64.b64encode(data).decode()})
    class NoScreenshotPage(Page):
        async def screenshot(self, **_kwargs):
            raise AssertionError('Screenshot must not reset screencast metrics')
    cdp = CDP()
    class Context:
        async def new_cdp_session(self, _page):
            return cdp
    hub = FrameHub(SimpleNamespace(page=NoScreenshotPage(), context=Context(), browser=SimpleNamespace(is_connected=lambda: True)))
    sub = await hub.subscribe(30, 'realtime')
    try:
        while 'Page.startScreencast' not in cdp.commands:
            await asyncio.sleep(0)
        assert cdp.commands.index('Emulation.setDeviceMetricsOverride') < cdp.commands.index('Page.startScreencast')
        output = BytesIO()
        Image.new('RGB', (1238, 720)).save(output, format='JPEG')
        cdp.frame(output.getvalue())
        await asyncio.sleep(.08)
        assert not sub.queue.qsize() and 'Page.stopScreencast' not in cdp.commands
        cdp.frame(jpeg('blue'))
        packet = await asyncio.wait_for(sub.recv(), 1)
        assert packet.mode == 'screencast'
        await asyncio.sleep(1.1)
        packet = await asyncio.wait_for(sub.recv(), 1)
        assert packet.mode == 'screencast' and hub.capture_count == 1
        assert not hub.error and hub.epoch == 0
    finally:
        await hub.close()


@pytest.mark.asyncio
async def test_cancelled_session_close_does_not_poison_inflight_peer_close(fake_peers, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()
    completion = asyncio.get_running_loop().create_future()
    calls = 0
    async def slow_close(peer):
        nonlocal calls
        calls += 1
        if calls > 1:
            await completion
            return
        entered.set()
        await release.wait()
        peer.closed = True
        completion.set_result(True)
    monkeypatch.setattr(Peer, 'close', slow_close)
    hub = DelayedHub()
    hub.gate.set()
    streams = RTCStreams(SimpleNamespace(frame_hub=hub, preview_settings={'realtime_fps': 20}))
    answer = await streams.offer('v=0', 'offer')
    first = asyncio.create_task(streams.close_peer(answer['id']))
    await entered.wait()
    closing_request = asyncio.create_task(streams.close())
    await asyncio.sleep(0)
    closing_request.cancel()
    await asyncio.gather(closing_request, return_exceptions=True)
    release.set()
    await asyncio.wait_for(asyncio.gather(first, streams.close()), 1)
    assert fake_peers[0].closed and completion.done() and not completion.cancelled()
    assert calls == 1 and not streams.closing
