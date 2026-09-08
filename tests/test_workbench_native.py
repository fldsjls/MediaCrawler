"""Native sender isolation and cleanup; real video acceptance uses local Chromium."""
import asyncio
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from mediacrawler.workbench.browser.preview.internal import is_internal_preview_url, public_pages
from mediacrawler.workbench.browser.preview.native import NativeRTCStreams, SenderServer
from mediacrawler.workbench.browser.preview import native as native_module


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
async def test_offer_deadline_releases_pending_peer_and_preserves_failure_stage(monkeypatch):
    page = SimpleNamespace(url='http://127.0.0.1/', is_closed=lambda: False)
    session = SimpleNamespace(id='fixture', page=page, control_lock=asyncio.Lock(), frame_hub=SimpleNamespace(epoch=0))
    rtc = NativeRTCStreams(session)
    timeout = asyncio.timeout
    monkeypatch.setattr(native_module.asyncio, 'timeout', lambda _seconds: timeout(.03))

    async def capture(_page):
        rtc.phase = '匹配浏览器视口'
        await asyncio.Event().wait()

    rtc._capture = capture
    with pytest.raises(RuntimeError, match='匹配浏览器视口'):
        await rtc.offer('offer', 'offer')
    assert '匹配浏览器视口' in rtc.snapshot()['error']
    assert not rtc.peers and not rtc.offers and not rtc.closing
    assert not session.control_lock.locked()
    await rtc.close()


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


def test_native_sender_keeps_stream_for_reserved_replacement_peer():
    """Execute the actual sender JS with deterministic browser API doubles."""
    script = r'''
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
let stopped = 0;
const config = {handle:'owned',origin:'http://127.0.0.1:1',sourceFps:60};
const makeStream = () => {
  const track = {readyState:'live',enabled:true,
    getSettings:()=>({displaySurface:'browser',width:1280,height:720}),
    getCaptureHandle:()=>({handle:config.handle,origin:config.origin}),
    addEventListener(){},stop(){this.readyState='ended';stopped++}};
  return {getTracks:()=>[track],getVideoTracks:()=>[track]};
};
class Peer {
  constructor(){this.connectionState='connected';this.iceGatheringState='complete'}
  async setRemoteDescription(){}
  getTransceivers(){return [{receiver:{track:{kind:'video'}}}]}
  addTrack(){return {getParameters:()=>({encodings:[{}]}),setParameters:async()=>{}}}
  async createAnswer(){return {type:'answer',sdp:'answer'}}
  async setLocalDescription(value){this.localDescription=value}
  close(){this.connectionState='closed'}
}
const sandbox={navigator:{mediaDevices:{getDisplayMedia:async()=>makeStream()}},
  document:{querySelector:()=>({})},RTCPeerConnection:Peer,
  setTimeout:()=>1,clearTimeout(){}};
sandbox.window=sandbox;
vm.runInNewContext(fs.readFileSync(process.argv[1],'utf8'),sandbox);
(async()=>{
 const api=sandbox.NativePreview;
 await api.capture(config);
 api.reserve('old'); await api.answer({id:'old',sdp:'offer',sourceFps:60});
 // This is the production race: B has reused the stream, but has not yet
 // registered its RTCPeerConnection when DELETE for A arrives.
 api.reserve('replacement'); api.closePeer('old');
 assert.equal(stopped,0); assert.equal(api.state().capture,true);
 assert.equal(api.state().reserved[0],'replacement');
 await api.answer({id:'replacement',sdp:'offer',sourceFps:60});
 assert.equal(api.state().reserved.length,0);
 api.closePeer('replacement'); assert.equal(stopped,1);
 assert.equal(api.state().capture,false);
 await api.capture(config); api.reserve('cancelled'); api.closePeer('cancelled');
 assert.equal(stopped,2); assert.equal(api.state().reserved.length,0);
 await api.capture(config); api.reserve('reset'); api.reset();
 assert.equal(stopped,3); assert.equal(api.state().reserved.length,0);
 await assert.rejects(()=>api.answer({id:'reset'}),/已取消/);
})().catch(error=>{console.error(error);process.exitCode=1});
'''
    node = shutil.which('node')
    assert node, 'Node.js is required by the browser capture worker'
    result = subprocess.run([node, '-e', script, str(Path(native_module.__file__).with_name('native_sender.js'))],
                            capture_output=True, text=True, encoding='utf-8', timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_stream_reservation_is_locked_but_ice_negotiation_is_not():
    page = SimpleNamespace(url='http://127.0.0.1/', is_closed=lambda: False)
    session = SimpleNamespace(id='fixture', page=page, control_lock=asyncio.Lock(), frame_hub=SimpleNamespace(epoch=0))
    rtc = NativeRTCStreams(session)
    calls = []
    class Helper:
        def is_closed(self): return False
        async def evaluate(self, script, value=None):
            if 'reserve' in script:
                assert rtc.lock.locked() and session.control_lock.locked()
                calls.append('reserved')
            elif 'answer' in script:
                assert not rtc.lock.locked() and not session.control_lock.locked()
                assert calls == ['reserved']
                return {'id': value['id'], 'sdp':'answer', 'type':'answer'}
        async def close(self): pass
    rtc.helper = Helper()
    async def capture(_page): rtc.source_fps = 60
    rtc._capture = capture
    try:
        answer = await rtc.offer('offer', 'offer')
        assert rtc.peers[answer['id']] == 'active'
    finally:
        await rtc.close()


@pytest.mark.asyncio
async def test_capture_click_uses_static_dom_rect_and_real_mouse_without_locator(monkeypatch):
    calls = []
    page = SimpleNamespace(is_closed=lambda: True)
    session = SimpleNamespace(id='fixture', preview_settings={'realtime_fps':60})
    rtc = NativeRTCStreams(session)
    class Mouse:
        async def click(self, x, y): calls.append(('mouse', x, y))
    class Helper:
        mouse = Mouse()
        def locator(self, *_): raise AssertionError('Capture must not wait on locator polling')
        async def bring_to_front(self): calls.append('front')
        async def evaluate(self, script, *args):
            if script == 'NativePreview.state()': return {'capture':False,'needsIdentity':False}
            if 'getBoundingClientRect' in script:
                calls.append('rect')
                return {'x':120,'y':24}
            if 'includes(window.captureResult' in script: return True
            if script == 'window.captureResult': return {'phase':'captured'}
            if script == 'NativePreview.state().settings': return {'width':1280,'height':720}
    helper = Helper()
    async def get_helper(): return helper
    async def identity(*_): return {'origin':'http://127.0.0.1','title':'owned'}
    async def fit(*_): calls.append('fit')
    rtc._helper, rtc._identity = get_helper, identity
    monkeypatch.setattr(native_module, 'fit_native_viewport', fit)
    await rtc._capture(page)
    assert calls == ['front','rect',('mouse',120,24),'fit']
