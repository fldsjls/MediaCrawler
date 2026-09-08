"""Declarative website templates run through the same browser and task protocol.

Only known DOM video sources are automatically associated. Network-only candidates
remain in the browser's passive resource list for explicit selection.
"""
import asyncio
import hashlib
import json
import os
import sys
from urllib.parse import urljoin, urlparse

from playwright.async_api import async_playwright
from playwright._impl._connection import Channel

from mediacrawler.workbench.workflows.runtime import Runtime
from mediacrawler.workbench.browser.preview.internal import public_pages


async def run():
    runtime = Runtime()
    sys.stdout = sys.stderr
    config = json.loads(os.environ['MC_TASK_CONFIG'])
    definition = json.loads(os.environ['MC_PLATFORM_DEFINITION'])
    if definition['template'] != 'video_capture':
        raise ValueError('此模板仅支持预览')
    Channel.send = runtime.wrap(Channel.send)
    runtime.listen()
    settings = definition.get('template_config', {})
    selector = config.get('selector') or settings.get('selector', '')
    wait_ms = config.get('wait_ms', settings.get('wait_ms', 5000))
    runtime.emit('state', state='running')
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(os.environ['MC_BROWSER_ENDPOINT'])
        try:
            context = browser.contexts[0]
            pages = public_pages(context)
            page = pages[0] if pages else await context.new_page()
            async def resume_check():
                if page.is_closed():
                    raise ValueError('采集页面已关闭')
                if await page.locator('input[type=password]:visible').count():
                    return False
                if page.url != config['target']:
                    await page.goto(config['target'], wait_until='domcontentloaded')
                return not await page.locator('input[type=password]:visible').count()
            runtime.resume_check = resume_check
            if page.url != config['target']:
                await page.goto(config['target'], wait_until='domcontentloaded')
            if await page.locator('input[type=password]:visible').count():
                await runtime.wait_login()
            runtime.emit('phase', phase='discovering', message='通用视频模板：读取明确的视频元素，其他网络资源保留供手选')
            seen = set()
            pages = max(1, min(await page.locator(selector).count(), config['max_items'])) if selector else 1
            count = 0
            for index in range(pages):
                await runtime.checkpoint()
                if selector:
                    targets = page.locator(selector)
                    if index >= await targets.count():
                        break
                    await targets.nth(index).click()
                await page.wait_for_timeout(wait_ms)
                for frame in page.frames:
                    videos = frame.locator('video')
                    for position in range(await videos.count()):
                        if count >= config['max_items']:
                            break
                        video = videos.nth(position)
                        await video.evaluate('(v) => v.play().catch(() => {})')
                        await page.wait_for_timeout(min(wait_ms, 2000))
                        details = await video.evaluate('''v => ({url:v.currentSrc || v.src || v.querySelector('source')?.src || '',
                            width:v.videoWidth, height:v.videoHeight, label:v.getAttribute('aria-label') || v.title})''')
                        resource_url = urljoin(frame.url, details['url']) if details['url'] else ''
                        stable = (page.url, index, position)
                        if stable in seen:
                            continue
                        seen.add(stable)
                        count += 1
                        title = details['label'] or await page.title() or definition['name']
                        content_id = 'content:' + hashlib.sha256(f'{config["platform"]}:{config["target"]}:{index}:{position}'.encode()).hexdigest()[:24]
                        resolved = urlparse(resource_url).scheme in ('http', 'https')
                        runtime.emit('record', record=dict(id=content_id, source=config['platform'], kind='content',
                            title=title, target=page.url, fields={'video_status': 'available' if resolved else 'unresolved'}))
                        if resolved and config.get('download_video'):
                            runtime.emit('resource', resource=dict(url=resource_url, kind='video', parent_id=content_id,
                                title=title, page_url=page.url, source=config['platform'], origin='adapter',
                                key=content_id + ':video', width=details['width'], height=details['height'],
                                headers={'Referer': page.url}))
                        elif not resolved and config.get('download_video'):
                            runtime.emit('failure', message=f'{title}：播放器使用间接资源，请在“发现的视频”中选择实际视频')
                if count >= config['max_items']:
                    break
            if not count:
                runtime.emit('record', record=dict(id='page:' + hashlib.sha256(config['target'].encode()).hexdigest()[:24],
                    source=config['platform'], kind='content', title=await page.title() or definition['name'],
                    target=page.url, fields={'video_status': 'none'}))
            runtime.emit('done')
        finally:
            await browser.close()


if __name__ == '__main__':
    try:
        asyncio.run(run())
    except Exception as exc:
        # JSON protocol remains distinct from third-party stdout.
        sys.__stdout__.write(json.dumps({'type': 'failure', 'message': str(exc)}, ensure_ascii=False) + '\n')
        sys.__stdout__.flush()
        sys.exit(1)
