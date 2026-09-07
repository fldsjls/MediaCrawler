"""Private, direct CDP capture transport for an existing browser page.

JPEG events bypass Playwright's Node protocol pipe. The connection never creates
another browser or target, and its debug address stays on the backend.
"""
import asyncio
import inspect
import json
import re
from urllib.parse import urlparse

from websockets.asyncio.client import connect


class CaptureChannel:
    def __init__(self, websocket, request_timeout=10):
        self._websocket = websocket
        self._request_timeout = request_timeout
        self._next_id = 0
        self._pending = {}
        self._callbacks = {}
        self._callback_tasks = set()
        self._closed = False
        self._close_task = None
        self._closing_caller = None
        self._receiver = asyncio.create_task(self._receive(), name='capture-cdp-receiver')

    @property
    def closed(self):
        return self._closed

    def on(self, event, callback):
        self._callbacks.setdefault(event, []).append(callback)

    async def send(self, method, params=None):
        if self.closed:
            raise ConnectionError('浏览器画面 CDP 连接已关闭')
        self._next_id += 1
        request_id = self._next_id
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            async with asyncio.timeout(self._request_timeout):
                await self._websocket.send(json.dumps({
                    'id': request_id, 'method': method, 'params': params or {}}, separators=(',', ':')))
                return await future
        except TimeoutError:
            raise TimeoutError('浏览器画面 CDP 请求超时') from None
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                # If a socket send fails at the same time the receiver fails pending
                # requests, retrieve this exception even though it was not awaited.
                future.exception()

    def _fail_pending(self):
        for future in self._pending.values():
            if not future.done():
                future.set_exception(ConnectionError('浏览器画面 CDP 连接已断开'))
        self._pending.clear()

    def _callback_done(self, task):
        self._callback_tasks.discard(task)
        if not task.cancelled():
            task.exception()

    async def _receive(self):
        try:
            async for raw in self._websocket:
                message = json.loads(raw)
                if 'id' in message:
                    future = self._pending.get(message['id'])
                    if future is None or future.done():
                        continue
                    if 'error' in message:
                        error = message['error']
                        future.set_exception(ValueError(
                            f"CDP 请求失败 ({error.get('code', 'unknown')}): {error.get('message', '浏览器拒绝请求')}"))
                    else:
                        future.set_result(message.get('result', {}))
                elif 'method' in message:
                    for callback in tuple(self._callbacks.get(message['method'], ())):
                        try:
                            value = callback(message.get('params', {}))
                            if inspect.isawaitable(value):
                                task = asyncio.ensure_future(value)
                                self._callback_tasks.add(task)
                                task.add_done_callback(self._callback_done)
                        except Exception:
                            # A viewer callback cannot break unrelated CDP responses.
                            pass
        except asyncio.CancelledError:
            raise
        except Exception:
            # No raw response, debug endpoint or request parameters in diagnostics.
            pass
        finally:
            self._closed = True
            self._fail_pending()
            pending = [task for task in self._callback_tasks if task is not self._closing_caller]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await self._websocket.close()

    async def detach(self):
        self._closed = True
        self._fail_pending()
        if self._close_task is None:
            self._closing_caller = asyncio.current_task()
            self._close_task = asyncio.create_task(self._close(), name='capture-cdp-close')
        await asyncio.shield(self._close_task)

    async def _close(self):
        await self._websocket.close()
        await asyncio.gather(self._receiver, return_exceptions=True)
        self._callbacks.clear()


async def open_capture_channel(session, page):
    endpoint = urlparse(session.endpoint)
    if (endpoint.scheme != 'http' or endpoint.hostname not in ('127.0.0.1', 'localhost', '::1')
            or endpoint.username or endpoint.password or endpoint.query or endpoint.fragment
            or endpoint.path not in ('', '/')):
        raise ValueError('画面 CDP 连接仅支持本机浏览器端点')
    probe = await session.context.new_cdp_session(page)
    try:
        result = await probe.send('Target.getTargetInfo')
        target_id = result['targetInfo']['targetId']
    finally:
        await probe.detach()
    if not isinstance(target_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', target_id):
        raise ValueError('浏览器未返回有效的页面标识')
    try:
        websocket = await connect(
            f'ws://{endpoint.netloc}/devtools/page/{target_id}', proxy=None,
            max_size=8 * 1024 * 1024, max_queue=4, compression=None,
            open_timeout=10, close_timeout=3)
    except Exception:
        raise ConnectionError('无法连接本机浏览器画面 CDP 通道') from None
    return CaptureChannel(websocket)
