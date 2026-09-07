"""Shared capture, presentation policy and actual local WebRTC reception."""
import asyncio
from io import BytesIO
from types import SimpleNamespace

import pytest
from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
from PIL import Image

from api.workbench.browser import BrowserSession
from api.workbench.models import SessionConfig
from api.workbench.preview.frames import FrameHub
from tests.test_workbench_api import local_api


def test_presentation_policy_never_grants_control(tmp_path):
    session = BrowserSession(SessionConfig(platform='bili'), tmp_path)
    assert session.presentation_snapshot()['mode'] == 'realtime'
    session.task_id, session.manual = 'task', False
    assert session.presentation_snapshot()['mode'] == 'snapshot'
    session.presentation = 'realtime'
    assert session.presentation_snapshot()['mode'] == 'realtime' and not session.manual
    session.presentation = 'auto'
    session.manual = True
    assert session.presentation_snapshot()['mode'] == 'realtime'
    session.manual, session.finished = False, True
    assert session.presentation_snapshot()['mode'] == 'realtime'


@pytest.mark.asyncio
async def test_page_switch_rejects_queued_input_for_old_picture(tmp_path):
    class Page:
        def is_closed(self):
            return False
        async def set_viewport_size(self, _size):
            pass
        async def bring_to_front(self):
            pass
    session = BrowserSession(SessionConfig(platform='bili'), tmp_path)
    previous, following = Page(), Page()
    session.page = previous
    session.pages = {'previous': previous, 'following': following}
    before = session.frame_hub.epoch
    await session.select('following')
    assert session.frame_hub.epoch != before
    with pytest.raises(ValueError, match='页面已切换'):
        await session.input({'action': 'click', 'x': 20, 'y': 20, 'page_epoch': before}, 'viewer')
    assert session.controller is None


@pytest.mark.asyncio
async def test_cancelled_close_request_still_finishes_owned_browser_cleanup(tmp_path):
    session = BrowserSession(SessionConfig(platform='bili'), tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()
    finished = []
    async def rtc_close():
        entered.set()
        await release.wait()
    async def hub_close():
        finished.append('hub')
    async def media_close():
        finished.append('media')
    session.rtc.close = rtc_close
    session.frame_hub.close = hub_close
    session.media.close = media_close
    request = asyncio.create_task(session.close())
    await entered.wait()
    request.cancel()
    await asyncio.gather(request, return_exceptions=True)
    release.set()
    await asyncio.wait_for(session.close(), 1)
    assert finished == ['hub', 'media']


@pytest.mark.asyncio
async def test_multiple_viewers_share_one_capture_and_latest_frame(tmp_path):
    encoded = BytesIO()
    Image.new('RGB', (1280, 720)).save(encoded, format='JPEG')
    calls = 0
    class Page:
        def is_closed(self):
            return False
        async def set_viewport_size(self, _size):
            pass
        async def screenshot(self, **_kwargs):
            nonlocal calls
            calls += 1
            return encoded.getvalue()
    page = Page()
    session = SimpleNamespace(page=page, browser=SimpleNamespace(is_connected=lambda: True))
    hub = FrameHub(session)
    fast, slow = await hub.subscribe(5), await hub.subscribe(1)
    producer = hub.producer
    try:
        first = await asyncio.wait_for(fast.recv(), 1)
        assert (await slow.recv()).seq == first.seq
        for _ in range(3):
            latest = await asyncio.wait_for(fast.recv(), 1)
        assert hub.producer is producer and calls == hub.capture_count
        assert latest.seq > first.seq
        assert fast.queue.qsize() <= 1 and slow.queue.qsize() <= 1
        await fast.close()
        assert hub.producer is producer and not producer.done()
        await slow.close()
        count = calls
        await asyncio.sleep(.25)
        assert hub.producer is None and calls == count
    finally:
        await hub.close()


def test_preview_signalling_requires_matching_session_identity(local_api, tmp_path):
    api = local_api
    session = BrowserSession(SessionConfig(platform='bili'), tmp_path)
    api.call(lambda: api.service.sessions.items.update({session.id: session}))
    base = f'/api/browser-sessions/{session.id}'
    assert api.client.patch(base + '/presentation', json={'token': 'wrong', 'preference': 'realtime'}).status_code == 403
    assert api.client.post(base + '/rtc', json={'token': 'wrong', 'sdp': 'v=0', 'type': 'offer'}).status_code == 403
    assert api.client.delete(base + '/rtc/missing').status_code == 403
    result = api.client.patch(base + '/presentation', json={'token': session.token, 'preference': 'snapshot'})
    assert result.status_code == 200
    assert result.json()['presentation']['mode'] == 'snapshot'
    assert result.json()['manual'] is True
    malformed = api.client.post(base + '/rtc', json={'token': session.token, 'sdp': 'invalid', 'type': 'offer'})
    assert malformed.status_code == 409
    assert not session.rtc.peers and not session.frame_hub.subscribers


@pytest.mark.asyncio
async def test_fastest_subscriber_does_not_drop_frames_when_timer_wakes_early(monkeypatch):
    from api.workbench.preview import frames as frame_module

    clock = [100.0]
    monkeypatch.setattr(frame_module, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    class Page:
        def is_closed(self):
            return False
        async def set_viewport_size(self, _size):
            pass
        async def screenshot(self, **_kwargs):
            # Simulate the monotonic clock advancing just less than a 20 fps
            # deadline. asyncio timers may wake early by clock resolution.
            clock[0] += .049
            return b'jpeg'
    hub = FrameHub(SimpleNamespace(page=Page(), browser=SimpleNamespace(is_connected=lambda: True)))
    fast, slow = await hub.subscribe(20), await hub.subscribe(5)
    try:
        sequences = [(await asyncio.wait_for(fast.recv(), 1)).seq for _ in range(8)]
        assert sequences == list(range(sequences[0], sequences[0] + 8))
        # Slower subscriptions still sample; they do not inherit the fast rate.
        assert (await slow.recv()).seq < sequences[-1]
    finally:
        await hub.close()


@pytest.mark.asyncio
async def test_real_chromium_streams_webrtc_and_switches_without_new_browser(tmp_path):
    session = BrowserSession(SessionConfig(platform='generic'), tmp_path)
    viewer = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    frames = asyncio.Queue()
    reader = None
    @viewer.on('track')
    def track_received(track):
        nonlocal reader
        async def read():
            while True:
                await frames.put(await track.recv())
        reader = asyncio.create_task(read())
    try:
        await session.start()
        pid = session.process.pid
        fixture = tmp_path / 'long-preview.html'
        fixture.write_text('<body style="margin:0;height:2600px;background:#238466"><input id="entry"><script>setInterval(()=>document.body.style.background=`hsl(${Date.now()%360},60%,60%)`,100)</script>', encoding='utf-8')
        await session.page.goto(fixture.as_uri())
        viewer.addTransceiver('video', direction='recvonly')
        await viewer.setLocalDescription(await viewer.createOffer())
        answer = await session.rtc.offer(viewer.localDescription.sdp, 'offer')
        await viewer.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'], type=answer['type']))
        for _ in range(3):
            frame = await asyncio.wait_for(frames.get(), 20)
            assert (frame.width, frame.height) == (1280, 720), str(await session.rtc.helper.evaluate('NativePreview.state().settings'))
        assert session.rtc.snapshot()['transport'] == 'native-tab'
        assert not session.frame_hub.subscribers, 'Native realtime must bypass JPEG/Python capture'
        assert len(session.public_pages()) == 1 and len(session.context.pages) == 2
        await session.input({'action': 'click', 'x': 60, 'y': 10}, 'local-viewer')
        await session.input({'action': 'text', 'text': '实时预览输入'}, 'local-viewer')
        assert await session.page.locator('#entry').input_value() == '实时预览输入'
        helper = session.rtc.helper
        await session.input({'action': 'reload'}, 'local-viewer')
        for _ in range(50):
            state = await helper.evaluate('NativePreview.state()')
            if state['capture'] and not state['needsIdentity']:
                break
            await asyncio.sleep(.1)
        assert state['capture'] and not state['needsIdentity'], 'Same-tab reload must revalidate without replacing the peer'
        assert session.rtc.helper is helper and answer['id'] in session.rtc.peers
        await session.input({'action': 'click', 'x': 60, 'y': 10}, 'local-viewer')
        await session.input({'action': 'text', 'text': '实时预览输入'}, 'local-viewer')
        await session.rtc.close_peer(answer['id'])
        assert not session.rtc.peers
        assert session.rtc.helper is None and len(session.context.pages) == 1
        sub = await session.frame_hub.subscribe(1)
        try:
            packet = await asyncio.wait_for(sub.recv(), 10)
            assert packet.jpeg.startswith(b'\xff\xd8')
            assert session.process.pid == pid
            assert await session.page.locator('#entry').input_value() == '实时预览输入'
        finally:
            await sub.close()
        assert session.frame_hub.producer is None
    finally:
        if reader:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        await viewer.close()
        await session.close()
