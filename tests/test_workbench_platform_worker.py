"""Exercise the real subprocess protocol and Playwright hooks with a local adapter fixture."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from api.workbench.browser import BrowserSession, kill_tree
from api.workbench.models import SessionConfig, TaskConfig


FIXTURE = r'''
import asyncio, importlib, json, os, types, faulthandler
faulthandler.dump_traceback_later(20, repeat=True)
from base.base_crawler import AbstractCrawler, AbstractApiClient
from playwright.async_api import async_playwright

class FixtureClient(AbstractApiClient):
    __module__ = 'media_platform.bilibili.client'
    headers = {'Referer': 'http://127.0.0.1/', 'Cookie': 'do-not-export'}
    async def request(self, *args, **kwargs): return {}
    async def update_cookies(self, browser_context, urls=None): pass
    async def pong(self): return True
    async def get_video_media(self, url): raise AssertionError('Old download sink must not execute')
    discovery_calls = 0
    async def search_video_by_keyword(self, **kwargs):
        self.discovery_calls += 1
        return {'result': [{'aid': aid} for aid in range(5)]}
    async def get_creator_videos(self, *args, **kwargs):
        self.discovery_calls += 1
        return {'list': {'vlist': [{'bvid': str(aid)} for aid in range(5)]}, 'page': {'count': 1000}}

class FixtureLogin:
    __module__ = 'media_platform.bilibili.login'
    def __init__(self, page): self.page = page
    async def check_login_state(self, previous_session):
        assert previous_session == 'before-login'
        return await self.page.locator('#login').input_value() == 'fixture-login'

class FixtureCrawler(AbstractCrawler):
    def __init__(self): self.index_url = 'about:blank'; self.cookie_urls = []
    async def search(self): pass
    async def launch_browser(self, *args, **kwargs): raise AssertionError('Browser must be reused')
    async def start(self):
        from tools.async_file_writer import AsyncFileWriter
        from store.bilibili import update_bilibili_video
        import config
        assert len(config.BILI_SPECIFIED_ID_LIST) == 2, 'detail inputs must obey the content limit'
        async with async_playwright() as playwright:
            self.browser_context = await self.launch_browser(playwright.chromium)
            self.context_page = await self.browser_context.new_page()
            assert len(self.browser_context.pages) == 1, 'worker must reuse preview page'
            await self.context_page.goto('about:blank')
            await self.context_page.set_content('<input id="login" style="position:absolute;left:100px;top:100px;width:250px;height:40px">')
            self.bili_client = FixtureClient()
            await FixtureLogin(self.context_page).check_login_state('before-login')
            assert len((await self.bili_client.search_video_by_keyword())['result']) == 2
            creator_page = await self.bili_client.get_creator_videos(1, 1, 30)
            assert len(creator_page['list']['vlist']) == 2 and creator_page['page']['count'] == 0
            async def item(aid, delay):
                await update_bilibili_video({'View': {'aid': aid, 'title': f'fixture {aid}', 'owner': {'mid': 123456789, 'name': '真实昵称'}, 'stat': {}}})
                await asyncio.sleep(delay)
                await self.bili_client.get_video_media(f'http://127.0.0.1/media/{aid}.mp4')
            await asyncio.gather(item(101, .2), item(102, .01))
            assert not (await self.bili_client.search_video_by_keyword())['result']
            assert not (await self.bili_client.get_creator_videos(1, 2, 30))['list']['vlist']
            assert self.bili_client.discovery_calls == 2, 'No requests after reaching the content limit'
            writer = AsyncFileWriter('bili', 'detail')
            await writer.write_to_jsonl({'comment_id':'c1','video_id':'101','parent_comment_id':'root','content':'第一条'}, 'comments')
            await writer.write_to_jsonl({'comment_id':'c2','video_id':'101','content':'超出限制'}, 'comments')
            await writer.write_to_jsonl({'comment_id':'c3','video_id':'102','content':'另一内容评论'}, 'comments')
            await self.context_page.evaluate('window.automaticOperations = 0')
            fixture_runtime.emit('phase', phase='fixture_takeover')
            for _ in range(8):
                await asyncio.sleep(.05)
                await self.context_page.evaluate('window.automaticOperations += 1')

original_import = importlib.import_module
def imports(name, *args, **kwargs):
    fixtures = {
      'media_platform.bilibili.core': types.SimpleNamespace(FixtureCrawler=FixtureCrawler),
      'media_platform.bilibili.client': types.SimpleNamespace(FixtureClient=FixtureClient),
      'media_platform.bilibili.login': types.SimpleNamespace(FixtureLogin=FixtureLogin),
    }
    if name in fixtures:
        module = types.ModuleType(name)
        vars(module).update(vars(fixtures[name]))
        return module
    return original_import(name, *args, **kwargs)
importlib.import_module = imports
from api.workbench import platform_worker
class CapturedRuntime(platform_worker.Runtime):
    def __init__(self):
        super().__init__()
        global fixture_runtime
        fixture_runtime = self
platform_worker.Runtime = CapturedRuntime
asyncio.run(platform_worker.run())
'''


@pytest.mark.asyncio
async def test_worker_reuses_browser_waits_login_and_preserves_normalized_results(tmp_path):
    session = BrowserSession(SessionConfig(platform='generic'), tmp_path)
    process = None
    stderr_task = None
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / 'adapter_fixture.py'
    script.write_text(FIXTURE, encoding='utf-8')
    task_directory = tmp_path / 'task'
    task_directory.mkdir()
    received = []
    try:
        await session.start()
        config = TaskConfig(platform='bili', target='BV-fixture1,BV-fixture2,BV-ignored',
                            max_items=2, max_comments=1, media=True)
        env = {**os.environ, 'PYTHONPATH': str(root), 'PYTHONIOENCODING': 'utf-8',
               'MC_TASK_CONFIG': config.model_dump_json(), 'MC_TASK_DIR': str(task_directory),
               'MC_BROWSER_ENDPOINT': session.endpoint, 'MC_EXISTING_RECORDS': '["content:101"]'}
        process = subprocess.Popen([sys.executable, '-u', str(script)], cwd=root, env=env,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   encoding='utf-8', errors='replace', creationflags=subprocess.CREATE_NO_WINDOW)
        stderr_task = asyncio.create_task(asyncio.to_thread(process.stderr.read))

        async def read_protocol():
            while True:
                line = await asyncio.to_thread(process.stdout.readline)
                if not line:
                    return
                message = json.loads(line)  # stdout must contain structured events exclusively
                received.append(message)
                if message.get('phase') == 'preparing':
                    process.stdin.write('{"action":"pause"}\n')
                    process.stdin.flush()
                elif message.get('state') == 'waiting_login':
                    assert not any(e['type'] == 'record' for e in received)
                    await session.input({'action': 'click', 'x': 180, 'y': 120}, 'test-viewer')
                    await session.input({'action': 'text', 'text': 'fixture-login'}, 'test-viewer')
                    process.stdin.write('{"action":"resume"}\n')
                    process.stdin.flush()
                elif message.get('phase') == 'fixture_takeover':
                    process.stdin.write('{"action":"pause"}\n')
                    process.stdin.flush()
                elif message.get('state') == 'paused':
                    before = await session.page.evaluate('window.automaticOperations')
                    if before is not None:
                        await session.input({'action': 'key', 'key': 'Control+A'}, 'test-viewer')
                        await session.input({'action': 'text', 'text': 'manual-takeover'}, 'test-viewer')
                    await asyncio.sleep(.2)
                    assert await session.page.evaluate('window.automaticOperations') == before
                    process.stdin.write('{"action":"resume"}\n')
                    process.stdin.flush()
        try:
            await asyncio.wait_for(read_protocol(), 90)
        except asyncio.TimeoutError:
            await kill_tree(process)
            stderr = await stderr_task
            pytest.fail(f'Worker protocol timed out; events={received!r}; stderr={stderr}')
        returncode = await asyncio.to_thread(process.wait)
        stderr = await stderr_task
        assert returncode == 0, stderr
        assert any(e.get('state') == 'waiting_login' for e in received)
        assert sum(e.get('state') == 'paused' for e in received) == 2
        assert received[-1]['type'] == 'done'
        records = [e['record'] for e in received if e['type'] == 'record']
        contents = [r for r in records if r['kind'] == 'content']
        assert len(contents) == 2
        assert all(r['fields']['creator_hash'] for r in contents)
        assert all(r['fields']['nickname'] != '真实昵称' for r in contents)
        assert all('mid' not in r['fields'] for r in contents)
        comments = [r for r in records if r['kind'] == 'comment']
        assert {r['id'] for r in comments} == {'comment:c1', 'comment:c3'}
        assert next(r for r in comments if r['id'] == 'comment:c1')['parent_id'] == 'comment:root'
        media = [e['resource'] for e in received if e['type'] == 'resource']
        assert len(media) == 2
        assert all(r['url'].endswith(r['parent_id'].split(':')[-1] + '.mp4') for r in media)
        assert all('Cookie' not in r['headers'] for r in media)
        saved = [json.loads(line) for path in task_directory.rglob('*contents*.jsonl') for line in path.read_text(encoding='utf-8').splitlines()]
        assert [r['video_id'] for r in saved] == ['102'], 'Retry must not append the existing content again'
        assert session.browser.is_connected()
        assert len(session.context.pages) == 1
        assert await session.page.evaluate('window.automaticOperations') == 8
    finally:
        await kill_tree(process)
        if stderr_task and not stderr_task.done():
            await asyncio.wait_for(stderr_task, 10)
        await session.close()
