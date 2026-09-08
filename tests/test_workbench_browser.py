"""Actual local Chromium acceptance; no platform requests or credentials."""
import asyncio
import base64
import io
import time
from types import SimpleNamespace

import pytest
from PIL import Image
from playwright.async_api import async_playwright

from mediacrawler.workbench.browser import BrowserSession
from mediacrawler.workbench.workflows.legacy_models import SessionConfig


@pytest.mark.asyncio
async def test_screenshot_fallback_does_not_wait_for_idle_watchdog(tmp_path):
    """A rejected CDP stream must still deliver successive interactive frames."""
    session = BrowserSession(SessionConfig(platform='generic'), tmp_path)
    session.preview_settings['snapshot_fps'] = 5
    delivered = asyncio.Queue()
    captured_at = []
    picture = io.BytesIO()
    Image.new('RGB', (1280, 720)).save(picture, format='JPEG')

    class Page:
        def is_closed(self):
            return False
        async def set_viewport_size(self, _size):
            pass
        async def screenshot(self, **_kwargs):
            captured_at.append(time.monotonic())
            return picture.getvalue()

    class UnsupportedCDP:
        def on(self, *_args):
            pass
        async def send(self, *_args):
            raise RuntimeError('unsupported')
        async def detach(self):
            pass

    async def new_cdp(_page):
        return UnsupportedCDP()

    class Viewer:
        async def send_json(self, message):
            await delivered.put((time.monotonic(), message))

    session.page = Page()
    session.browser = SimpleNamespace(is_connected=lambda: True)
    session.context = SimpleNamespace(new_cdp_session=new_cdp)
    sender = asyncio.create_task(session.frames(Viewer()))
    try:
        _, first = await asyncio.wait_for(delivered.get(), 2)
        assert first['mode'] == 'screenshot'
        previous = first['seq']
        for _ in range(3):
            _, message = await asyncio.wait_for(delivered.get(), .8)
            assert message['mode'] == 'screenshot'
            assert message['seq'] > previous
            previous = message['seq']
        # Measure producer cadence. A delayed subscriber can receive two queued
        # frames closer together even while capture itself respects the budget.
        assert captured_at[-1] - captured_at[0] >= (len(captured_at) - 1) * .18
    finally:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)


@pytest.mark.asyncio
async def test_real_browser_frames_chinese_input_coordinates_popup_and_reuse(tmp_path, monkeypatch):
    session = BrowserSession(SessionConfig(platform='generic'), tmp_path)
    frames = asyncio.Queue()

    class Viewer:
        async def send_json(self, message):
            await frames.put(message)

    sender = None
    try:
        await session.start()
        await session.page.goto('about:blank')
        await session.page.set_content('''<!doctype html><meta charset="utf-8">
            <style>body {margin:0;height:2500px} input {position:absolute;left:100px;top:80px;width:240px;height:40px}
            button {position:absolute;left:600px;top:300px;width:150px;height:70px}
            #tiny {left:1111px;top:611px;width:20px;height:20px;padding:0;border:0;background:#e00000}</style>
            <input id="entry"><button onclick="this.textContent='已点击';window.hit=(window.hit||0)+1">点击</button>
            <button id="tiny" onclick="window.tinyHit=(window.tinyHit||0)+1"></button>''')
        sender = asyncio.create_task(session.frames(Viewer()))
        message = await asyncio.wait_for(frames.get(), 15)
        assert message['type'] == 'frame'
        encoded = base64.b64decode(message['data'])
        assert encoded.startswith(b'\xff\xd8')
        assert Image.open(io.BytesIO(encoded)).size == (1280, 720)
        # Continuous CDP frames used to be clipped by Chromium's outer window even
        # though the first fallback screenshot was full size.
        for index in range(4):
            await session.page.evaluate("(n) => document.body.style.backgroundColor = n % 2 ? '#ddffff' : '#ffffff'", index)
            next_frame = await asyncio.wait_for(frames.get(), 10)
            picture = Image.open(io.BytesIO(base64.b64decode(next_frame['data'])))
            assert picture.size == (1280, 720)
        await session.input({'action': 'click', 'x': 1121, 'y': 621}, 'viewer1')
        assert await session.page.evaluate('window.tinyHit') == 1
        # These are viewport coordinates after the frontend has removed letterboxing.
        await session.input({'action': 'click', 'x': 180, 'y': 100}, 'viewer1')
        await session.input({'action': 'text', 'text': '中文输入与粘贴✓'}, 'viewer1')
        assert await session.page.locator('#entry').input_value() == '中文输入与粘贴✓'
        await session.input({'action': 'key', 'key': 'Control+A'}, 'viewer1')
        await session.input({'action': 'text', 'text': '替换'}, 'viewer1')
        assert await session.page.locator('#entry').input_value() == '替换'
        await session.input({'action': 'click', 'x': 675, 'y': 335}, 'viewer1')
        assert await session.page.evaluate('window.hit') == 1
        with pytest.raises(ValueError, match='坐标'):
            await session.input({'action': 'click', 'x': 1281, 'y': 10}, 'viewer1')
        with pytest.raises(ValueError, match='接管'):
            await session.input({'action': 'text', 'text': 'other owner'}, 'viewer2')
        session.manual = False
        with pytest.raises(ValueError, match='接管'):
            await session.input({'action': 'click', 'x': 675, 'y': 335}, 'viewer1')
        session.manual = True
        await session.input({'action': 'wheel', 'dy': 600, 'x': 900, 'y': 500}, 'viewer1')
        await session.page.wait_for_function('window.scrollY > 0')
        async with session.context.expect_page() as popup_info:
            await session.page.evaluate("window.open('about:blank')")
        popup = await popup_info.value
        popup_id = next(k for k, page in session.pages.items() if page is popup)
        await session.select(popup_id)
        assert any(p['id'] == popup_id and p['selected'] for p in session.snapshot()['pages'])
        assert 'endpoint' not in session.snapshot()
        # A worker disconnecting its CDP client must leave the owned browser available.
        async with async_playwright() as playwright:
            worker_browser = await playwright.chromium.connect_over_cdp(session.endpoint)
            assert len(worker_browser.contexts[0].pages) == 2
            await worker_browser.close()
        assert session.browser.is_connected()
        assert await popup.evaluate('1+1') == 2
        original_id = next(k for k, page in session.pages.items() if page is not popup)
        await session.select(original_id)
        await session.page.evaluate('window.scrollTo(0,0)')
        await session.input({'action': 'click', 'x': 675, 'y': 335}, 'viewer1')
        assert await session.page.evaluate('window.hit') == 2
        await session.input({'action': 'wheel', 'dy': 500, 'x': 900, 'y': 500}, 'viewer1')
        await session.page.wait_for_function('window.scrollY > 0')
        # Hiding the frame view does not end the browser/session.
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        sender = None
        assert session.process.poll() is None
        assert await popup.evaluate('2+2') == 4
        # A Chromium build that rejects screencasting still provides screenshot frames.
        class UnsupportedCDP:
            def on(self, *_args):
                pass
            async def send(self, *_args):
                raise RuntimeError('screencast unavailable')
            async def detach(self):
                pass
        async def unavailable(_page):
            return UnsupportedCDP()
        monkeypatch.setattr(session.context, 'new_cdp_session', unavailable)
        while not frames.empty():
            frames.get_nowait()
        sender = asyncio.create_task(session.frames(Viewer()))
        fallback = await asyncio.wait_for(frames.get(), 10)
        assert base64.b64decode(fallback['data']).startswith(b'\xff\xd8')
    finally:
        if sender:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        await session.close()
    assert session.process.poll() is not None
