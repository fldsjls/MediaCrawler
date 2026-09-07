"""Real loopback WebSocket tests; no Chromium, Node worker, or application server."""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from mediacrawler.workbench.preview.cdp import CaptureChannel, open_capture_channel


@asynccontextmanager
async def channel_server(handler, timeout=1):
    async with serve(handler, '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with connect(f'ws://127.0.0.1:{port}', proxy=None, max_size=8 * 1024 * 1024) as websocket:
            channel = CaptureChannel(websocket, request_timeout=timeout)
            try:
                yield channel
            finally:
                await channel.detach()


@pytest.mark.asyncio
async def test_out_of_order_responses_and_event_are_independent():
    async def handler(websocket):
        first, second = json.loads(await websocket.recv()), json.loads(await websocket.recv())
        await websocket.send(json.dumps({'method': 'Page.screencastFrame', 'params': {'data': 'jpeg'}}))
        for request in (second, first):
            await websocket.send(json.dumps({'id': request['id'], 'result': {'method': request['method']}}))
        await websocket.wait_closed()
    async with channel_server(handler) as channel:
        events = []
        channel.on('Page.screencastFrame', events.append)
        results = await asyncio.gather(channel.send('Page.first'), channel.send('Page.second'))
        assert results == [{'method': 'Page.first'}, {'method': 'Page.second'}]
        assert events == [{'data': 'jpeg'}] and not channel._pending


@pytest.mark.asyncio
async def test_protocol_error_does_not_stop_receiver():
    async def handler(websocket):
        async for raw in websocket:
            request = json.loads(raw)
            response = {'error': {'code': -32601, 'message': 'Method not found'}} if request['method'] == 'unknown' else {'result': {'ok': True}}
            await websocket.send(json.dumps({'id': request['id'], **response}))
    async with channel_server(handler) as channel:
        with pytest.raises(ValueError, match='-32601.*Method not found'):
            await channel.send('unknown')
        assert await channel.send('Page.enable') == {'ok': True}
        assert not channel.closed


@pytest.mark.asyncio
async def test_remote_disconnect_fails_every_pending_request():
    async def handler(websocket):
        await websocket.recv()
        await websocket.recv()
        await websocket.close()
    async with channel_server(handler) as channel:
        results = await asyncio.gather(channel.send('one'), channel.send('two'), return_exceptions=True)
        assert all(isinstance(result, ConnectionError) for result in results)
        assert channel.closed and not channel._pending
        with pytest.raises(ConnectionError):
            await channel.send('three')


@pytest.mark.asyncio
async def test_timeout_and_cancel_only_remove_their_own_request():
    seen = asyncio.Queue()
    async def handler(websocket):
        async for raw in websocket:
            request = json.loads(raw)
            await seen.put(request)
            if request['method'] == 'ok':
                await websocket.send(json.dumps({'id': request['id'], 'result': {}}))
    async with channel_server(handler, timeout=.05) as channel:
        with pytest.raises(TimeoutError, match='超时'):
            await channel.send('timeout')
        await seen.get()
        pending = asyncio.create_task(channel.send('cancel'))
        await seen.get()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert not channel._pending and not channel._receiver.done()
        assert await channel.send('ok') == {}


@pytest.mark.asyncio
async def test_detach_fails_requests_and_leaves_no_receiver():
    seen = asyncio.Event()
    async def handler(websocket):
        await websocket.recv()
        seen.set()
        await websocket.wait_closed()
    async with channel_server(handler) as channel:
        pending = asyncio.create_task(channel.send('wait'))
        await seen.wait()
        await asyncio.gather(channel.detach(), channel.detach())
        with pytest.raises(ConnectionError):
            await pending
        assert channel.closed and channel._receiver.done() and not channel._pending


@pytest.mark.asyncio
async def test_async_callback_does_not_block_responses_and_is_cancelled():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    async def callback(_event):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    async def handler(websocket):
        request = json.loads(await websocket.recv())
        await websocket.send(json.dumps({'method': 'frame', 'params': {}}))
        await websocket.send(json.dumps({'id': request['id'], 'result': {}}))
        await websocket.wait_closed()
    async with channel_server(handler) as channel:
        channel.on('frame', callback)
        assert await channel.send('ok') == {}
        await entered.wait()
        await channel.detach()
        assert cancelled.is_set() and not channel._callback_tasks


@pytest.mark.asyncio
async def test_open_channel_uses_exact_target_and_accepts_large_jpeg_event():
    target_page = object()
    paths = []
    payload = 'j' * (2 * 1024 * 1024)
    class Probe:
        detached = False
        async def send(self, method):
            assert method == 'Target.getTargetInfo'
            return {'targetInfo': {'targetId': 'TARGET-123'}}
        async def detach(self):
            self.detached = True
    probe = Probe()
    async def new_cdp_session(page):
        assert page is target_page
        return probe
    async def handler(websocket):
        paths.append(websocket.request.path)
        request = json.loads(await websocket.recv())
        await websocket.send(json.dumps({'method': 'Page.screencastFrame', 'params': {'data': payload}}))
        await websocket.send(json.dumps({'id': request['id'], 'result': {}}))
        await websocket.wait_closed()
    async with serve(handler, '127.0.0.1', 0) as server:
        session = SimpleNamespace(endpoint=f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}',
                                  context=SimpleNamespace(new_cdp_session=new_cdp_session))
        channel = await open_capture_channel(session, target_page)
        events = []
        channel.on('Page.screencastFrame', events.append)
        try:
            await channel.send('Page.startScreencast')
            assert events == [{'data': payload}]
            assert probe.detached and paths == ['/devtools/page/TARGET-123']
        finally:
            await channel.detach()


@pytest.mark.asyncio
async def test_probe_is_detached_on_target_lookup_failure():
    class Probe:
        detached = False
        async def send(self, _method):
            raise ValueError('Target closed')
        async def detach(self):
            self.detached = True
    probe = Probe()
    async def new_cdp_session(_page):
        return probe
    session = SimpleNamespace(endpoint='http://127.0.0.1:12345', context=SimpleNamespace(new_cdp_session=new_cdp_session))
    with pytest.raises(ValueError, match='Target closed'):
        await open_capture_channel(session, object())
    assert probe.detached


@pytest.mark.asyncio
@pytest.mark.parametrize('endpoint', ['http://example.com:9222', 'https://127.0.0.1:9222',
                                     'http://secret@127.0.0.1:9222', 'http://127.0.0.1:9222/?token=secret'])
async def test_nonlocal_or_credential_endpoint_rejected_without_disclosure(endpoint):
    with pytest.raises(ValueError, match='本机浏览器端点') as failure:
        await open_capture_channel(SimpleNamespace(endpoint=endpoint), object())
    assert 'secret' not in str(failure.value) and endpoint not in str(failure.value)
