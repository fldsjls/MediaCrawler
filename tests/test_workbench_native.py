"""Native sender isolation and cleanup; real video acceptance uses local Chromium."""
import asyncio
from types import SimpleNamespace

import pytest

from api.workbench.preview.internal import is_internal_preview_url, public_pages
from api.workbench.preview.native import NativeRTCStreams, SenderServer


def test_internal_pages_are_not_collection_targets():
    pages = [SimpleNamespace(url=url, is_closed=lambda: False) for url in (
        'https://example.org/', 'http://127.0.0.1:9876/__mediacrawler_preview__/sender')]
    assert public_pages(SimpleNamespace(pages=pages)) == pages[:1]
    assert not is_internal_preview_url('https://example.org/__mediacrawler_preview__/sender')


@pytest.mark.asyncio
async def test_sender_http_requires_private_header_and_exact_host():
    server = SenderServer()
    await server.start()
    async def request(key='', host=None):
        authority = server.origin.removeprefix('http://')
        reader, writer = await asyncio.open_connection('127.0.0.1', int(authority.split(':')[-1]))
        writer.write((f'GET /__mediacrawler_preview__/sender HTTP/1.1\r\nHost: {host or authority}\r\n'
                      f'X-MC-Preview-Key: {key}\r\n\r\n').encode())
        await writer.drain()
        result = await reader.read()
        writer.close()
        await writer.wait_closed()
        return result
    try:
        assert (await request()).startswith(b'HTTP/1.1 403')
        assert (await request(server.key, 'malicious.example')).startswith(b'HTTP/1.1 403')
        assert (await request(server.key)).startswith(b'HTTP/1.1 200')
    finally:
        await server.close()


@pytest.mark.asyncio
async def test_pending_capture_without_javascript_peer_is_reset_and_helper_closed():
    calls = []
    class Helper:
        def is_closed(self): return False
        async def evaluate(self, script, *args): calls.append(script)
        async def close(self): calls.append('close')
    rtc = NativeRTCStreams(SimpleNamespace(id='fixture'))
    rtc.helper = Helper()
    rtc.peers['pending'] = 'pending'
    await rtc.close_peer('pending')
    assert 'NativePreview.reset()' in calls and calls[-1] == 'close'
    assert rtc.helper is None and not rtc.peers


@pytest.mark.asyncio
async def test_cancelled_helper_creation_closes_exact_late_target_before_page_event():
    entered, release = asyncio.Event(), asyncio.Event()
    closed = []
    class CDP:
        async def send(self, method, args):
            if method == 'Target.createTarget':
                entered.set()
                await release.wait()
                return {'targetId': 'owned-late-target'}
            if method == 'Target.closeTarget':
                closed.append(args['targetId'])
        async def detach(self): pass
    class Browser:
        async def new_browser_cdp_session(self): return CDP()
    session = SimpleNamespace(id='fixture', browser=Browser(), context=SimpleNamespace(pages=[]), pages={})
    rtc = NativeRTCStreams(session)
    request = asyncio.create_task(rtc._helper())
    await entered.wait()
    request.cancel()
    release.set()
    result = await asyncio.gather(request, return_exceptions=True)
    assert isinstance(result[0], asyncio.CancelledError)
    assert closed == ['owned-late-target']
    assert rtc.helper is None


@pytest.mark.asyncio
async def test_pending_offers_count_toward_limit_and_cancel_cleanly():
    entered = asyncio.Event()
    page = SimpleNamespace(url='http://127.0.0.1/', is_closed=lambda: False)
    session = SimpleNamespace(id='fixture', page=page, control_lock=asyncio.Lock(), frame_hub=SimpleNamespace(epoch=0))
    rtc = NativeRTCStreams(session)
    async def capture(_page):
        entered.set()
        await asyncio.Event().wait()
    rtc._capture = capture
    requests = [asyncio.create_task(rtc.offer('offer', 'offer')) for _ in range(4)]
    await entered.wait()
    await asyncio.sleep(0)
    assert len(rtc.peers) == 4
    with pytest.raises(ValueError, match='上限'):
        await rtc.offer('offer', 'offer')
    await asyncio.wait_for(rtc.close(), 2)
    await asyncio.gather(*requests, return_exceptions=True)
    assert not rtc.peers and not rtc.offers and not rtc.closing


@pytest.mark.asyncio
@pytest.mark.parametrize('missing', [False, True])
async def test_watcher_releases_active_peers_when_helper_disappears(missing):
    rtc = NativeRTCStreams(SimpleNamespace(id='fixture'))
    rtc.helper = None if missing else SimpleNamespace(is_closed=lambda: True)
    rtc.peers.update({'viewer-one': 'active', 'viewer-two': 'active'})
    rtc.capture_page = object()
    await asyncio.wait_for(rtc._watch(), 1)
    assert not rtc.peers and not rtc.closing
    assert rtc.capture_page is None
    assert '发送页已关闭' in rtc.error
    assert rtc.snapshot()['active'] is False


@pytest.mark.asyncio
async def test_watcher_does_not_invalidate_a_pending_helper_creation():
    rtc = NativeRTCStreams(SimpleNamespace(id='fixture'))
    rtc.peers['negotiating'] = 'pending'
    watcher = asyncio.create_task(rtc._watch())
    try:
        await asyncio.sleep(.3)
        assert rtc.peers == {'negotiating': 'pending'} and not rtc.error
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        await rtc.close()
