"""Real local course -> Node adapter -> common queue -> FFmpeg acceptance.

All traffic uses a local HTTP fixture; this does not certify any real platform login.
"""
import asyncio
import contextlib
import http.server
import json
import subprocess
import threading
import time
from pathlib import Path

import pytest

from api.workbench.models import TaskConfig, TERMINAL
from api.workbench.service import Workbench, WORKER, resource_identity


@contextlib.contextmanager
def fixture_site(root):
    subprocess.run([str(WORKER / 'tools/ffmpeg/ffmpeg.exe'), '-v', 'error', '-y', '-f', 'lavfi',
        '-i', 'color=c=blue:s=160x90:d=0.5', '-c:v', 'libx264', '-f', 'hls', '-hls_time', '1',
        '-hls_segment_filename', str(root / 'segment%03d.ts'), str(root / 'play.m3u8')], check=True, capture_output=True)
    requests = []
    failures = set()
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, time.monotonic()))
            if '/course' in self.path:
                content = '''<!doctype html><meta charset="utf-8"><h1 class="course-title">本地验证课程</h1>
                <div class="fa_children">''' + ''.join(f'''<div class="fa_Item_lession"><button class="name" onclick="fetch('/chaosw.com/{i}/play.m3u8')">第{i}课 示例 00:01</button></div>''' for i in range(1, 4)) + '</div>'
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(content.encode())
            elif self.path.startswith('/template'):
                content = '<!doctype html><meta charset="utf-8"><title>自定义网站</title><video controls src="/play.m3u8"></video>'
                self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8'); self.end_headers(); self.wfile.write(content.encode())
            else:
                filename = self.path.split('?')[0].split('/')[-1]
                path = root / filename
                # Fail only FFmpeg media downloads, not the browser's discovery request.
                if any(s in self.path for s in failures) and 'Lavf' in self.headers.get('User-Agent', ''):
                    self.send_error(503); return
                if not path.is_file():
                    self.send_error(404); return
                self.send_response(200); self.end_headers(); self.wfile.write(path.read_bytes())
        def log_message(self, *_):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests, failures
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=3)


async def until(workbench, task_id, states=TERMINAL, timeout=75):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = workbench.repo.task(task_id)
        if task['state'] in states:
            return task
        await asyncio.sleep(.1)
    events = workbench.repo.events(task_id)
    pytest.fail(f'Task did not reach {states}: {task}\n{json.dumps(events[-20:], ensure_ascii=False)}')


@pytest.mark.asyncio
async def test_custom_video_template_uses_owned_preview_and_shared_queue(tmp_path):
    from api.workbench.platforms.registry import PlatformDefinition
    from api.workbench.models import SessionConfig
    media = tmp_path / 'media'
    media.mkdir()
    workbench = Workbench(tmp_path / 'workbench')
    await workbench.start()
    try:
        with fixture_site(media) as (url, requests, failures):
            definition = workbench.platforms.save(PlatformDefinition(name='自定义视频站', category='video',
                url=url + '/template', template='video_capture', template_config={'wait_ms': 100}))
            session = await workbench.sessions.create(SessionConfig(platform=definition['id'], url=url + '/template'))
            await asyncio.sleep(.3)
            assert workbench.repo.tasks() == []
            created = workbench.create(TaskConfig(platform=definition['id'], target=url + '/template',
                session_id=session.id, download_video=True, download_images=False, max_items=1,
                max_downloads=1, comments=False, wait_ms=100))
            task = await until(workbench, created['id'])
            assert task['state'] == 'succeeded', workbench.repo.events(task['id'])[-15:]
            assert task['session_id'] == session.id and len(session.context.pages) == 1
            assert task['counts']['files_succeeded'] == 1
            results = workbench.repo.results(task['id'])
            assert results['records'][0]['source'] == definition['id']
            assert results['resources'][0]['parent_id'] == results['records'][0]['id']
            assert (workbench.repo.directory(task['id']) / results['files'][0]['path']).stat().st_size > 0
    finally:
        await workbench.close()


@pytest.mark.asyncio
async def test_course_pipeline_limits_download_retry_and_browser_reuse(tmp_path):
    media = tmp_path / 'media'
    media.mkdir()
    workbench = Workbench(tmp_path / 'workbench')
    await workbench.start()
    try:
        with fixture_site(media) as (url, requests, failures):
            # This is deliberately a localhost URL with the upstream CDN path pattern.
            failures.add('/1/')
            created = workbench.create(TaskConfig(platform='meishiwang', target=url + '/course',
                max_items=2, max_downloads=1, media=True, comments=False, wait_ms=100))
            result = await until(workbench, created['id'])
            assert result['state'] == 'partial', workbench.repo.events(created['id'])[-15:]
            assert result['counts']['content'] == 2
            assert result['counts']['files_failed'] == 1
            assert result['counts']['files_succeeded'] == 0
            session = workbench.sessions.items[result['session_id']]
            assert session.browser.is_connected(), 'Worker shutdown must retain the preview browser'
            assert len(session.context.pages) == 1, 'Worker must reuse the preview tab'
            failures.clear()
            before = len([p for p, _ in requests if p.startswith('/course')])
            await workbench.control(created['id'], 'retry')
            retried = await until(workbench, created['id'])
            assert retried['state'] == 'succeeded', workbench.repo.results(created['id'])
            assert retried['counts']['content'] == 2
            assert retried['counts']['files_succeeded'] == 1
            assert len([p for p, _ in requests if p.startswith('/course')]) == before, 'File-only retry must not rerun discovery'
            records = workbench.repo.results(created['id'])
            assert len(records['files']) == 1
            path = workbench.repo.directory(created['id']) / records['files'][0]['path']
            assert path.stat().st_size > 100
    finally:
        await workbench.close()


def test_signed_resource_identity_preserves_media_id():
    assert resource_identity({'parent_id': 'p', 'url': 'https://cdn.example/a.mp4?id=1&token=old'}) == resource_identity({'parent_id': 'p', 'url': 'https://cdn.example/a.mp4?id=1&token=new'})
    assert resource_identity({'parent_id': 'p', 'url': 'https://cdn.example/a.mp4?id=1'}) != resource_identity({'parent_id': 'p', 'url': 'https://cdn.example/a.mp4?id=2'})


@pytest.mark.asyncio
async def test_takeover_stops_clicks_cancel_cleans_worker_and_queue_continues(tmp_path):
    media = tmp_path / 'media'
    media.mkdir()
    workbench = Workbench(tmp_path / 'workbench')
    await workbench.start()
    try:
        with fixture_site(media) as (url, requests, _failures):
            config = TaskConfig(platform='meishiwang', target=url + '/course', max_items=3, media=False, wait_ms=300)
            first = workbench.create(config)
            await until(workbench, first['id'], {'running'})
            run = workbench.active
            queued = workbench.create(config)
            assert workbench.repo.task(queued['id'])['state'] == 'queued'
            await workbench.control(first['id'], 'takeover')
            await until(workbench, first['id'], {'paused'})
            assert run.session.manual
            prior = len(requests)
            await asyncio.sleep(.6)
            assert len(requests) == prior, 'No automatic requests/clicks while user owns the browser'
            await run.session.input({'action': 'click', 'x': 10, 'y': 10}, 'test-controller')
            await workbench.control(queued['id'], 'cancel')
            await workbench.control(first['id'], 'cancel')
            await until(workbench, first['id'], {'cancelled'})
            assert run.process.poll() is not None
            assert workbench.repo.task(queued['id'])['state'] == 'cancelled'
            next_task = workbench.create(TaskConfig(platform='meishiwang', target=url + '/course', max_items=1, media=False, wait_ms=100))
            finished = await until(workbench, next_task['id'])
            assert finished['state'] == 'succeeded', workbench.repo.events(next_task['id'])[-15:]
            assert finished['counts']['content'] == 1
    finally:
        await workbench.close()


@pytest.mark.asyncio
async def test_failed_file_retry_does_not_redownload_success(tmp_path):
    media = tmp_path / 'media'
    media.mkdir()
    workbench = Workbench(tmp_path / 'workbench')
    await workbench.start()
    try:
        with fixture_site(media) as (url, requests, failures):
            failures.add('/2/')
            created = workbench.create(TaskConfig(platform='meishiwang', target=url + '/course',
                max_items=2, max_downloads=2, media=True, comments=False, wait_ms=100))
            result = await until(workbench, created['id'])
            assert result['state'] == 'partial'
            assert result['counts']['files_succeeded'] == result['counts']['files_failed'] == 1
            successful = next(f for f in workbench.repo.results(created['id'])['files'] if f['state'] == 'succeeded')
            path = workbench.repo.directory(created['id']) / successful['path']
            modified = path.stat().st_mtime_ns
            first_downloads = len([p for p, _ in requests if p.startswith('/chaosw.com/1/')])
            failures.clear()
            await workbench.control(created['id'], 'retry')
            retried = await until(workbench, created['id'])
            assert retried['state'] == 'succeeded'
            assert retried['counts']['files_succeeded'] == 2
            assert path.stat().st_mtime_ns == modified
            assert len([p for p, _ in requests if p.startswith('/chaosw.com/1/')]) == first_downloads
    finally:
        await workbench.close()
