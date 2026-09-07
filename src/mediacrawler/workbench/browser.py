import asyncio
import base64
import secrets
import socket
import subprocess
import uuid
from pathlib import Path
from playwright.async_api import async_playwright

from .models import PLATFORMS, SessionConfig, web_url
from .media.capture import MediaCapture
from .preview.frames import FrameHub
from .preview.native import NativeRTCStreams
from .preview.internal import public_pages, INTERNAL_PREVIEW_PATH
from .settings import BrowserSettings

async def kill_tree(process):
    if process and process.poll() is None:
        # Only the Popen instance owned by this service is eligible for termination.
        await asyncio.to_thread(subprocess.run, ['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                capture_output=True)
        await asyncio.to_thread(process.wait, timeout=15)

class BrowserSession:
    def __init__(self, config, root, preview_settings=None):
        self.id = uuid.uuid4().hex
        self.token = secrets.token_urlsafe(32)
        self.config = config
        self.root = root
        self.process = None
        self.browser = None
        self.context = None
        self.playwright = None
        self.endpoint = ''
        self.manual = True
        self.task_id = None
        self.finished = False
        self.page = None
        self.controller = None
        self.pages = {}
        self.control_lock = asyncio.Lock()
        self.media = MediaCapture(self.id, self.config.platform)
        self.preview_settings = preview_settings or BrowserSettings().model_dump()
        self.presentation = 'auto' if self.preview_settings['auto_switch'] else 'realtime'
        self.frame_hub = FrameHub(self)
        self.rtc = NativeRTCStreams(self)
        self._close_task = None

    async def start(self):
        await self.rtc.prepare()
        self.playwright = await async_playwright().start()
        executable = self.playwright.chromium.executable_path
        if self.config.channel == 'msedge':
            import os
            candidates = [Path(os.environ.get(x, '')) / 'Microsoft/Edge/Application/msedge.exe'
                          for x in ('PROGRAMFILES(X86)', 'PROGRAMFILES')]
            executable = str(next((p for p in candidates if p.is_file()), ''))
            if not executable:
                raise RuntimeError('未找到 Edge，请选择 Chromium')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        profile = self.root / 'profiles' / f'{self.config.platform}-{self.config.channel}'
        profile.mkdir(parents=True, exist_ok=True)
        args = [executable, f'--remote-debugging-port={port}', '--remote-debugging-address=127.0.0.1',
                f'--user-data-dir={profile}', '--no-first-run', '--no-default-browser-check',
                '--window-size=1400,900', '--enable-automation', '--enable-usermedia-screen-capturing',
                f'--auto-select-tab-capture-source-by-title={self.rtc.title}',
                '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
                '--disable-backgrounding-occluded-windows']
        if not self.config.external:
            args.append('--headless=new')
        args.append('about:blank')
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.endpoint = f'http://127.0.0.1:{port}'
        for _ in range(60):
            try:
                self.browser = await self.playwright.chromium.connect_over_cdp(self.endpoint, timeout=1000)
                break
            except Exception:
                if self.process.poll() is not None:
                    raise RuntimeError('浏览器未能启动；请确认该 Profile 没有被其他浏览器占用')
                await asyncio.sleep(.2)
        if not self.browser:
            raise RuntimeError('连接采集浏览器超时')
        self.context = self.browser.contexts[0]
        # Automatic capture approval belongs only to our isolated, authenticated
        # helper document. Third-party task pages must not invoke that permission.
        import json
        trusted = self.rtc.http.origin + INTERNAL_PREVIEW_PATH
        await self.context.add_init_script('''(() => {
            if (location.href.startsWith(TRUSTED)) return;
            if (typeof MediaDevices !== 'undefined') Object.defineProperty(MediaDevices.prototype,
                'getDisplayMedia', {configurable:false,writable:false,value:async () => {
                    throw new DOMException('Display capture is reserved for the preview transport','NotAllowedError');
                }});
        })();'''.replace('TRUSTED', json.dumps(trusted)))
        self.media.attach(self.context)
        self.context.on('page', self.register_page)
        for page in self.context.pages:
            self.register_page(page)
        # Chromium can publish its startup target shortly after CDP connects. Creating
        # a page immediately in that gap produces a duplicate startup tab.
        if not self.context.pages:
            await self.context.wait_for_event('page', timeout=10000)
        self.page = self.context.pages[0]
        await self.page.set_viewport_size({'width': 1280, 'height': 720})
        if self.config.url:
            try:
                await self.page.goto(web_url(self.config.url), wait_until='domcontentloaded', timeout=30000)
            except Exception as exc:
                # Session remains usable to inspect a navigation failure or sign in manually.
                self.navigation_error = str(exc).splitlines()[0]
        return self

    def register_page(self, page):
        if self.rtc.owns_page(page) or page in self.pages.values():
            return
        self.pages[uuid.uuid4().hex[:12]] = page

    def public_pages(self):
        return [page for page in public_pages(self.context) if not self.rtc.owns_page(page)] if self.context else []

    def snapshot(self):
        return dict(id=self.id, platform=self.config.platform, token=self.token, manual=self.manual,
                    task_id=self.task_id, finished=self.finished, external=self.config.external,
                    width=1280, height=720, page_epoch=self.frame_hub.epoch, presentation=self.presentation_snapshot(),
                    preview={**self.frame_hub.snapshot(), 'native': self.rtc.snapshot()}, navigation_error=getattr(self, 'navigation_error', ''),
                    pages=[dict(id=k, url=p.url, selected=p == self.page) for k, p in self.pages.items() if not p.is_closed() and not self.rtc.owns_page(p)])

    async def select(self, page_id):
        async with self.control_lock:
            page = self.pages.get(page_id)
            if page is None or page.is_closed() or self.rtc.owns_page(page):
                raise ValueError('页面已关闭')
            if self.page is not page:
                await self.rtc.invalidate()
                self.page = page
                self.frame_hub.invalidate()
            await page.set_viewport_size({'width': 1280, 'height': 720})
            await page.bring_to_front()

    async def input(self, message, owner):
        async with self.control_lock:
            if not self.manual or self.controller not in (None, owner):
                raise ValueError('请先接管并等待采集暂停')
            if message.get('page_epoch', self.frame_hub.epoch) != self.frame_hub.epoch:
                raise ValueError('页面已切换，请等待新画面后重试')
            self.controller = owner
            page = self.page
            if page is None or page.is_closed():
                raise ValueError('没有可操作页面')
            action = message.get('action')
            if action == 'navigate':
                await page.goto(web_url(message['url']), wait_until='domcontentloaded', timeout=30000)
            elif action == 'reload':
                await page.reload(wait_until='domcontentloaded', timeout=30000)
            elif action == 'click':
                x, y = float(message['x']), float(message['y'])
                if not (0 <= x <= 1280 and 0 <= y <= 720):
                    raise ValueError('坐标超出视口')
                await page.mouse.click(x, y, button=message.get('button', 'left'))
            elif action == 'wheel':
                await page.mouse.move(max(0, min(1280, float(message.get('x', 640)))), max(0, min(720, float(message.get('y', 360)))))
                await page.mouse.wheel(max(-3000, min(3000, float(message.get('dx', 0)))), max(-3000, min(3000, float(message.get('dy', 0)))))
            elif action == 'text':
                await page.keyboard.insert_text(str(message.get('text', ''))[:20000])
            elif action == 'key':
                key = message.get('key', '')
                allowed = {'Enter', 'Tab', 'Shift+Tab', 'Escape', 'Backspace', 'Delete', 'ArrowLeft', 'ArrowRight',
                           'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown', 'Control+A', 'Control+Z'}
                if key not in allowed:
                    raise ValueError('不支持此按键')
                await page.keyboard.press(key)
            else:
                raise ValueError('不支持此操作')

    def presentation_snapshot(self):
        mode = self.presentation
        if mode == 'auto':
            mode = 'realtime' if self.manual or self.finished or not self.task_id else 'snapshot'
        return dict(preference=self.presentation, mode=mode,
                    snapshot_fps=self.preview_settings['snapshot_fps'],
                    realtime_fps=self.preview_settings['realtime_fps'])

    async def frames(self, websocket):
        sub = await self.frame_hub.subscribe(self.preview_settings['snapshot_fps'], 'snapshot')
        try:
            while True:
                frame = await sub.recv()
                await asyncio.wait_for(websocket.send_json(dict(type='frame',
                    data=base64.b64encode(frame.jpeg).decode(), mode=frame.mode, seq=frame.seq, epoch=frame.epoch)), 3)
        finally:
            await sub.close()

    async def close(self):
        # A tab/request disappearing must not cancel the cleanup it initiated.
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close())
        await asyncio.shield(self._close_task)

    async def _close(self):
        try:
            await self.rtc.close()
        finally:
            try:
                await self.frame_hub.close()
                await self.media.close()
                if self.browser:
                    await asyncio.wait_for(self.browser.close(), 10)
            finally:
                self.browser = None
                await kill_tree(self.process)
                if self.playwright:
                    await self.playwright.stop()

class BrowserSessions:
    def __init__(self, root, platform_lookup=None, settings_lookup=None):
        self.root = root
        self.platform_lookup = platform_lookup
        self.settings_lookup = settings_lookup
        self.items = {}
        self.lock = asyncio.Lock()

    async def create(self, config):
        platform = self.platform_lookup(config.platform) if self.platform_lookup else next(
            (p for p in PLATFORMS if p['id'] == config.platform), None)
        if not platform:
            raise ValueError('未知平台')
        if not platform.get('enabled', True) and not platform.get('legacy', False):
            raise ValueError('此平台已停用，不能建立新会话')
        if not config.url:
            config.url = platform['url']
        if config.url:
            web_url(config.url)
        async with self.lock:
            for session in self.items.values():
                if session.config.platform == config.platform and session.browser:
                    raise ValueError('此平台已有会话，请复用或先关闭它')
            settings = self.settings_lookup() if self.settings_lookup else BrowserSettings().model_dump()
            if 'channel' not in config.model_fields_set:
                config.channel = settings['default_channel']
            session = BrowserSession(config, self.root, settings)
            try:
                await session.start()
            except BaseException:
                await session.close()
                raise
            self.items[session.id] = session
            return session

    async def close(self):
        for session in list(self.items.values()):
            try:
                await session.close()
            except Exception:
                await kill_tree(session.process)
        self.items.clear()
