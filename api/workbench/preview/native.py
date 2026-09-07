"""Browser-native tab capture and WebRTC; Python only brokers authenticated SDP.

The helper shares the task context to permit Capture Handle verification. It has
no task/session credentials and all collection consumers exclude its reserved URL.
"""
import asyncio
import secrets
import uuid
from pathlib import Path

from .internal import INTERNAL_PREVIEW_PATH, is_internal_preview_url
from .viewport import fit_native_viewport


class SenderServer:
    def __init__(self):
        self.server = None
        self.key = secrets.token_urlsafe(32)
        self.origin = ''
        self.script = Path(__file__).with_name('native_sender.js').read_bytes()

    async def start(self):
        self.server = await asyncio.start_server(self._request, '127.0.0.1', 0, limit=8192)
        self.origin = f'http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}'

    async def _request(self, reader, writer):
        try:
            data = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 3)
            lines = data.decode('latin1').split('\r\n')
            method, path, _ = lines[0].split(' ', 2)
            headers = dict(line.split(':', 1) for line in lines[1:] if ':' in line)
            headers = {key.lower(): value.strip() for key, value in headers.items()}
            authorized = secrets.compare_digest(headers.get('x-mc-preview-key', ''), self.key)
            valid_host = headers.get('host') == self.origin.removeprefix('http://')
            if method != 'GET' or not authorized or not valid_host:
                status, mime, body = '403 Forbidden', 'text/plain', b'Forbidden'
            elif path == INTERNAL_PREVIEW_PATH + 'sender':
                status, mime = '200 OK', 'text/html; charset=utf-8'
                body = (f'<!doctype html><meta charset="utf-8"><title>Internal preview transport</title>'
                        f'<button id="capture">Start owned tab capture</button>'
                        f'<script src="{INTERNAL_PREVIEW_PATH}sender.js"></script>').encode()
            elif path == INTERNAL_PREVIEW_PATH + 'sender.js':
                status, mime, body = '200 OK', 'text/javascript; charset=utf-8', self.script
            else:
                status, mime, body = '404 Not Found', 'text/plain', b'Not found'
            writer.write((f'HTTP/1.1 {status}\r\nContent-Type: {mime}\r\nContent-Length: {len(body)}\r\n'
                          "Cache-Control: no-store\r\nX-Frame-Options: DENY\r\n"
                          "Content-Security-Policy: default-src 'none'; script-src 'self'; frame-ancestors 'none'\r\n"
                          'Connection: close\r\n\r\n').encode() + body)
            await writer.drain()
        except (ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass

    async def close(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None


class NativeRTCStreams:
    def __init__(self, session):
        self.session = session
        self.title = 'MC_OWN_TAB_' + session.id
        self.http = SenderServer()
        self.helper = None
        self.creating_helper = False
        self.capture_page = None
        self.handle = None
        self.peers = {}
        self.offers = {}
        self.closing = {}
        self.closed = False
        self.error = ''
        self.phase = 'idle'
        self.lock = asyncio.Lock()
        self.watcher = None
        self._close_task = None

    async def prepare(self):
        await self.http.start()

    def snapshot(self):
        return dict(transport='native-tab', peers=len(self.peers),
                    pending=sum(state == 'pending' for state in self.peers.values()),
                    active=any(state == 'active' for state in self.peers.values()), error=self.error)

    def owns_page(self, page):
        return page is self.helper or is_internal_preview_url(getattr(page, 'url', ''))

    async def _helper(self):
        if self.helper and not self.helper.is_closed():
            return self.helper
        self.creating_helper = True
        url = self.http.origin + INTERNAL_PREVIEW_PATH + 'sender'
        try:
            # Initial URL is internal even before authentication. The first response
            # is inert 403; reload with the page-only nonce loads the trusted script.
            cdp = await self.session.browser.new_browser_cdp_session()
            try:
                creation = asyncio.create_task(cdp.send('Target.createTarget', {'url': url, 'background': True}))
                try:
                    await asyncio.shield(creation)
                except BaseException:
                    # Await the owned command rather than racing its delayed page
                    # event. Close by exact target id even when no Page exists yet.
                    async def cancel_target():
                        result = await asyncio.wait_for(asyncio.shield(creation), 3)
                        await cdp.send('Target.closeTarget', {'targetId': result['targetId']})
                    try:
                        await asyncio.shield(cancel_target())
                    except Exception:
                        pass
                    raise
            finally:
                await cdp.detach()
            for _ in range(100):
                self.helper = next((page for page in self.session.context.pages if page.url == url), None)
                if self.helper:
                    break
                await asyncio.sleep(.02)
            if not self.helper:
                raise RuntimeError('无法建立内部预览发送页')
            await self.helper.set_extra_http_headers({'X-MC-Preview-Key': self.http.key})
            await self.helper.set_viewport_size({'width': 1280, 'height': 720})
            async def only_internal(route):
                if route.request.url.startswith(self.http.origin + INTERNAL_PREVIEW_PATH):
                    await route.continue_()
                else:
                    await route.abort()
            await self.helper.route('**/*', only_internal)
            await self.helper.reload(wait_until='domcontentloaded')
            for _ in range(100):
                if await self.helper.evaluate('Boolean(window.NativePreview)'):
                    break
                await asyncio.sleep(.05)
            else:
                raise RuntimeError('内部预览发送页初始化超时')
            return self.helper
        except BaseException:
            async def discard():
                # Target.createTarget may complete just as its caller is cancelled.
                for page in list(self.session.context.pages):
                    if page.url == url:
                        await page.close()
                self.helper = None
            await asyncio.shield(discard())
            raise
        finally:
            self.creating_helper = False
            self.session.pages = {key: page for key, page in self.session.pages.items() if not self.owns_page(page)}

    async def _identity(self, page, set_title=False):
        cdp = await self.session.context.new_cdp_session(page)
        try:
            frame = (await cdp.send('Page.getFrameTree'))['frameTree']['frame']['id']
            world = await cdp.send('Page.createIsolatedWorld', {'frameId': frame, 'worldName': 'mc-preview-identity'})
            result = await cdp.send('Runtime.callFunctionOn', {
                'executionContextId': world['executionContextId'], 'returnByValue': True,
                'functionDeclaration': '''function(config) {
                    if (!isSecureContext || !navigator.mediaDevices?.setCaptureHandleConfig)
                        throw new Error('当前网页不支持安全标签页身份验证（需要 HTTPS 或本机网页），使用低刷新预览');
                    navigator.mediaDevices.setCaptureHandleConfig({handle:config.handle,
                        exposeOrigin:true,permittedOrigins:[config.senderOrigin]});
                    const title = document.title;
                    if (config.title) document.title = config.title;
                    return {origin:location.origin,title};
                }''',
                'arguments': [{'value': dict(handle=self.handle, senderOrigin=self.http.origin,
                                            title=self.title if set_title else '')}],
            })
            if result.get('exceptionDetails'):
                raise RuntimeError('当前网页不支持安全标签页身份验证（需要 HTTPS 或本机网页），使用低刷新预览')
            return result['result']['value']
        finally:
            await cdp.detach()

    async def _capture(self, page):
        self.phase = '建立发送页'
        helper = await self._helper()
        state = await helper.evaluate('NativePreview.state()')
        if self.capture_page is page and state['capture'] and not state['needsIdentity']:
            return
        if state['capture']:
            await helper.evaluate('NativePreview.reset()')
        self.handle = secrets.token_urlsafe(32)
        self.phase = '验证来源页面'
        identity = await self._identity(page, True)
        self.capture_page = page
        self.source_fps = self.session.preview_settings['realtime_fps']
        config = dict(handle=self.handle, origin=identity['origin'], sourceFps=self.source_fps)
        try:
            await helper.evaluate('value => NativePreview.prepare(value)', config)
            # This is our static helper button; rAF-based stability checks can
            # stall while Chromium considers this internal tab backgrounded.
            self.phase = '请求标签页捕获'
            await helper.locator('#capture').click(force=True, timeout=3000)
            for _ in range(160):
                if await helper.evaluate("['captured','error'].includes(window.captureResult?.phase)"):
                    break
                await asyncio.sleep(.05)
            result = await helper.evaluate('window.captureResult')
            if result['phase'] != 'captured':
                raise RuntimeError(result.get('message', '标签页捕获不可用'))
            self.phase = '匹配浏览器视口'
            await fit_native_viewport(self.session, page)
            for _ in range(40):
                size = await helper.evaluate('NativePreview.state().settings')
                if size and (size['width'], size['height']) == (1280, 720):
                    break
                await asyncio.sleep(.05)
            else:
                dimensions = f"{size.get('width')}×{size.get('height')}" if size else '未知'
                raise RuntimeError(f'标签页捕获尺寸不匹配（{dimensions}），使用低刷新预览')
            self.error = ''
        finally:
            if not page.is_closed():
                await page.evaluate('value => { if(document.title === value.temporary) document.title=value.title }',
                                    dict(temporary=self.title, title=identity['title']))

    async def offer(self, sdp, description_type):
        try:
            async with asyncio.timeout(13):
                return await self._offer(sdp, description_type)
        except TimeoutError:
            raise RuntimeError(f'原生实时预览连接超时（{self.phase}），请重试或使用低刷新预览') from None

    async def _offer(self, sdp, description_type):
        if self.closed:
            raise ValueError('浏览器会话已关闭')
        if description_type != 'offer':
            raise ValueError('实时预览需要 offer')
        if len(self.peers) >= 4:
            raise ValueError('实时预览连接已达上限，请关闭其他预览窗口')
        peer_id = uuid.uuid4().hex
        self.peers[peer_id] = 'pending'
        self.offers[peer_id] = asyncio.current_task()
        try:
            async with self.session.control_lock:
                async with self.lock:
                    if self.closed or peer_id not in self.peers:
                        raise ValueError('实时预览已取消')
                    page = self.session.page
                    if not page or page.is_closed() or self.owns_page(page):
                        raise ValueError('没有可预览的采集页面')
                    epoch = self.session.frame_hub.epoch
                    await self._capture(page)
                    helper = self.helper
            # ICE gathering must not hold the task input lock; cancellation and
            # page selection can close this pending peer while it negotiates.
            self.phase = '协商视频连接'
            result = await asyncio.wait_for(helper.evaluate('value => NativePreview.answer(value)',
                dict(id=peer_id, sdp=sdp, sourceFps=self.source_fps)), 12)
            async with self.session.control_lock:
                if self.closed or peer_id not in self.peers or self.session.page is not page or self.session.frame_hub.epoch != epoch:
                    raise ValueError('实时预览页面已变化')
                self.peers[peer_id] = 'active'
                self.phase = '已连接'
                if not self.watcher or self.watcher.done():
                    self.watcher = asyncio.create_task(self._watch())
                return result
        except BaseException as exc:
            if not isinstance(exc, asyncio.CancelledError):
                self.error = str(exc).splitlines()[0].replace(self.http.key, '[internal]')
            if peer_id in self.peers:
                await self.close_peer(peer_id)
            if isinstance(exc, (asyncio.CancelledError, ValueError)):
                raise
            raise RuntimeError(self.error or '原生实时预览不可用，请使用低刷新预览') from None
        finally:
            self.offers.pop(peer_id, None)

    async def _watch(self):
        while not self.closed and self.peers:
            await asyncio.sleep(.25)
            if not self.peers:
                break
            helper = self.helper
            if not helper or helper.is_closed():
                # Pending offers may still be creating their helper. An active
                # peer, however, cannot recover after its sending page vanished.
                if any(state == 'active' for state in self.peers.values()):
                    self.error = '内部实时预览发送页已关闭，请重试或使用低刷新预览'
                    await self.invalidate()
                    break
                continue
            size = None
            try:
                state = await helper.evaluate('NativePreview.state()')
                if helper is not self.helper:
                    continue
                size = state.get('settings')
                resized = size and (size['width'], size['height']) != (1280, 720)
                for peer_id in list(self.peers):
                    if self.peers[peer_id] == 'active' and peer_id not in state['ids']:
                        await self.close_peer(peer_id)
                if (state['needsIdentity'] or resized) and self.peers:
                    await helper.evaluate('NativePreview.pause()')
                    async with self.session.control_lock:
                        async with self.lock:
                            if helper is not self.helper or not self.peers:
                                continue
                            if not self.capture_page or self.capture_page is not self.session.page or self.capture_page.is_closed():
                                raise RuntimeError('采集标签页已变化')
                            identity = await self._identity(self.capture_page)
                            await fit_native_viewport(self.session, self.capture_page)
                            for _ in range(40):
                                size = await helper.evaluate('NativePreview.state().settings')
                                if size and (size['width'], size['height']) == (1280, 720):
                                    break
                                await asyncio.sleep(.05)
                            else:
                                dimensions = f"{size.get('width')}×{size.get('height')}" if size else '未知'
                                raise RuntimeError(f'标签页捕获尺寸无法恢复（{dimensions}），使用低刷新预览')
                            await helper.evaluate('value => NativePreview.revalidate(value)',
                                dict(handle=self.handle, origin=identity['origin']))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if helper is not self.helper:
                    continue
                self.error = str(exc).splitlines()[0].replace(self.http.key, '[internal]')
                if size:
                    self.error += f"（捕获 {size.get('width')}×{size.get('height')}）"
                await self.invalidate()
                break

    async def close_peer(self, peer_id):
        if self.peers.pop(peer_id, None) is None:
            pending_close = self.closing.get(peer_id)
            if pending_close and pending_close is not asyncio.current_task():
                await asyncio.shield(pending_close)
            return
        caller = asyncio.current_task()
        pending = self.offers.get(peer_id)
        if pending and pending is not caller:
            pending.cancel()
        async def cleanup():
            if pending and pending is not caller:
                await asyncio.gather(pending, return_exceptions=True)
            async with self.lock:
                if self.helper and not self.helper.is_closed():
                    try:
                        await self.helper.evaluate('id => NativePreview.closePeer(id)', peer_id)
                        if not self.peers:
                            await self.helper.evaluate('NativePreview.reset()')
                            await self.helper.close()
                            self.helper = None
                            self.capture_page = None
                    except Exception:
                        pass
        task = asyncio.create_task(cleanup())
        self.closing[peer_id] = task
        task.add_done_callback(lambda _: self.closing.pop(peer_id, None))
        await asyncio.shield(task)

    async def invalidate(self):
        for peer_id in list(self.peers):
            await self.close_peer(peer_id)
        async with self.lock:
            if self.helper and not self.helper.is_closed():
                try:
                    await self.helper.evaluate('NativePreview.reset()')
                except Exception:
                    pass
            self.capture_page = None

    async def close(self):
        self.closed = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        if self.watcher and self.watcher is not asyncio.current_task():
            self.watcher.cancel()
            await asyncio.gather(self.watcher, return_exceptions=True)
        await self.invalidate()
        if self.closing:
            await asyncio.gather(*(asyncio.shield(task) for task in list(self.closing.values())))
        if self.helper and not self.helper.is_closed():
            await self.helper.close()
        await self.http.close()
