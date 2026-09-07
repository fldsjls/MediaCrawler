"""One capture producer per browser, bounded latest-frame subscriptions."""
import asyncio
import base64
import time
from dataclasses import dataclass
from io import BytesIO

from PIL import Image

from .cdp import open_capture_channel


@dataclass(frozen=True)
class Frame:
    jpeg: bytes
    seq: int
    captured_at: float
    mode: str
    epoch: int = 0


class Subscription:
    def __init__(self, hub, fps, kind):
        self.hub, self.fps, self.kind = hub, fps, kind
        self.queue = asyncio.Queue(maxsize=1)
        self.next_at = 0.0
        self.closed = False

    async def recv(self):
        value = await self.queue.get()
        if isinstance(value, Exception):
            raise value
        return value

    def put(self, value):
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(value)

    async def close(self):
        await self.hub.unsubscribe(self)


class FrameHub:
    def __init__(self, session):
        self.session = session
        self.subscribers = set()
        self.lock = asyncio.Lock()
        self.producer = None
        self.closed = False
        self.seq = 0
        self.capture_count = 0
        self.mode = 'idle'
        self.error = ''
        self.epoch = 0
        self._page = getattr(session, 'page', None)

    async def subscribe(self, fps, kind='snapshot'):
        async with self.lock:
            if self.closed:
                raise ValueError('浏览器画面服务已关闭')
            sub = Subscription(self, max(1, min(30, fps)), kind)
            self.subscribers.add(sub)
            if self.producer is None or self.producer.done():
                self.error = ''
                self.producer = asyncio.create_task(self._capture())
            return sub

    async def unsubscribe(self, sub):
        async with self.lock:
            if sub.closed:
                return
            sub.closed = True
            self.subscribers.discard(sub)
            sub.put(ValueError('画面订阅已结束'))
            if not self.subscribers and self.producer:
                self.producer.cancel()
                await asyncio.gather(self.producer, return_exceptions=True)
                self.producer = None
                self.mode = 'idle'

    def invalidate(self):
        # Page changes may never deliver an old page's queued picture.
        self.epoch += 1
        self._page = self.session.page
        self._clear()

    def _clear(self):
        for sub in self.subscribers:
            while not sub.queue.empty():
                sub.queue.get_nowait()
            sub.next_at = 0.0

    def snapshot(self):
        return dict(subscribers=len(self.subscribers), producer_active=bool(self.producer and not self.producer.done()),
                    mode=self.mode, frames=self.seq, captures=self.capture_count, error=self.error)

    async def close(self):
        self.closed = True
        for sub in list(self.subscribers):
            await sub.close()

    async def _capture(self):
        current = None
        current_epoch = -1
        cdp = None
        latest = None
        jpeg = None
        pending = set()
        stream_requested = False
        failed_page = None
        last_capture = last_output = 0.0
        stream_started = 0.0
        invalid_since = None

        async def detach():
            nonlocal cdp
            previous, cdp = cdp, None
            if previous:
                try:
                    await asyncio.wait_for(previous.send('Page.stopScreencast'), 2)
                except Exception:
                    pass
                finally:
                    try:
                        await previous.detach()
                    except Exception:
                        pass

        async def received(event, source, epoch):
            nonlocal latest
            try:
                await source.send('Page.screencastFrameAck', {'sessionId': event['sessionId']})
                if source is cdp and epoch == self.epoch:
                    latest = event['data']
            except Exception:
                pass

        def enqueue(event, source, epoch):
            task = asyncio.create_task(received(event, source, epoch))
            pending.add(task)
            task.add_done_callback(pending.discard)

        try:
            while self.subscribers and self.session.browser and self.session.browser.is_connected():
                page = self.session.page
                if page is None or page.is_closed():
                    pages = (self.session.public_pages() if hasattr(self.session, 'public_pages')
                             else [p for p in self.session.context.pages if not p.is_closed()])
                    if not pages:
                        self.error = '没有可预览页面，请重新打开网站'
                        break
                    self.session.page = pages[-1]
                    continue
                if self._page is not page:
                    if self._page is None:
                        self._page = page
                    else:
                        self.invalidate()
                epoch = self.epoch
                realtime = any(s.kind == 'realtime' for s in self.subscribers)
                if current is not page or current_epoch != epoch or stream_requested != realtime:
                    await detach()
                    if epoch != self.epoch or page is not self.session.page:
                        continue
                    if current is not page:
                        failed_page = None
                    self._clear()
                    current, stream_requested = page, realtime
                    current_epoch = epoch
                    latest = jpeg = None
                    invalid_since = None
                    last_capture = last_output = 0
                    await page.set_viewport_size({'width': 1280, 'height': 720})
                    if epoch != self.epoch or page is not self.session.page:
                        continue
                    if realtime and failed_page is not page:
                        try:
                            cdp = (await open_capture_channel(self.session, page)
                                   if getattr(self.session, 'endpoint', '')
                                   else await self.session.context.new_cdp_session(page))
                            cdp.on('Page.screencastFrame', lambda event, source=cdp, generation=epoch: enqueue(event, source, generation))
                            # CDP sessions have their own emulation metrics; the page's
                            # Playwright viewport alone does not size screencast frames.
                            await cdp.send('Emulation.setDeviceMetricsOverride', {
                                'width': 1280, 'height': 720, 'deviceScaleFactor': 1, 'mobile': False})
                            stream_started = time.monotonic()
                            await cdp.send('Page.startScreencast', {'format': 'jpeg', 'quality': 75,
                                'maxWidth': 1280, 'maxHeight': 720,
                                # Limit capture work at the compositor as well as
                                # sampling delivery; a typical 60 Hz page otherwise
                                # emits many JPEGs that we immediately discard.
                                'everyNthFrame': max(1, round(60 / max(s.fps for s in self.subscribers)))})
                        except Exception:
                            failed_page = page
                            await detach()
                fps = max(s.fps for s in self.subscribers)
                await asyncio.sleep(max(0, 1 / fps - (time.monotonic() - last_output)))
                if epoch != self.epoch or page is not self.session.page or page.is_closed():
                    continue
                if cdp and getattr(cdp, 'closed', False):
                    raise ValueError('浏览器画面通道已断开，请重新连接预览')
                mode = 'screencast' if cdp else 'screenshot'
                if cdp and latest:
                    data, latest = latest, None
                    candidate = base64.b64decode(data)
                    with Image.open(BytesIO(candidate)) as picture:
                        valid = picture.size == (1280, 720)
                    if valid:
                        jpeg = candidate
                        invalid_since = None
                        last_capture = time.monotonic()
                        self.capture_count += 1
                    else:
                        if invalid_since is None:
                            invalid_since = time.monotonic()
                if cdp and ((jpeg is None and time.monotonic() - stream_started >= 2) or
                            (invalid_since is not None and time.monotonic() - invalid_since >= 2)):
                    failed_page = page
                    await detach()
                    jpeg = None
                    mode = 'screenshot'
                if cdp and jpeg is None:
                    # Resizing can produce a transient invalid first frame. Taking a
                    # screenshot during this window can overwrite CDP metrics again.
                    last_output = time.monotonic()
                    continue
                if not cdp:
                    jpeg = await page.screenshot(type='jpeg', quality=75 if realtime else 55, timeout=5000)
                    last_capture = time.monotonic()
                    self.capture_count += 1
                if epoch != self.epoch or page is not self.session.page:
                    continue
                self.seq += 1
                self.mode = mode
                last_output = time.monotonic()
                frame = Frame(jpeg, self.seq, last_capture, mode, epoch)
                for sub in list(self.subscribers):
                    # The producer already limits the fastest cadence. Windows
                    # timers may wake slightly early; applying the same deadline
                    # again would drop alternate frames for the fastest viewer.
                    if sub.fps == fps or last_output >= sub.next_at:
                        sub.put(frame)
                        sub.next_at = last_output + 1 / sub.fps
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc).splitlines()[0]
            for sub in self.subscribers:
                sub.put(ValueError('画面采集失败，请重新连接预览'))
        finally:
            self.mode = 'idle'
            if self.subscribers:
                if not self.closed and not self.error:
                    self.error = '浏览器画面连接已断开'
                for sub in list(self.subscribers):
                    sub.put(ValueError(self.error or '画面订阅已结束'))
            await detach()
            for task in list(pending):
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
