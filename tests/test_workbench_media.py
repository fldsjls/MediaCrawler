"""Passive browser discovery and real local finite-media download acceptance."""
import asyncio
import base64
from contextlib import contextmanager
import http.server
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from mediacrawler.workbench.browser import BrowserSession, BrowserSessions
from mediacrawler.workbench.media.capture import MediaCapture, classify, manifest_status
from mediacrawler.workbench.media.downloader import MediaProxy, download
from mediacrawler.workbench.media.identity import resource_identity
from mediacrawler.workbench.models import SessionConfig

TOOLS = Path(__file__).resolve().parents[1] / '.local/tools'


@pytest.fixture(scope='module')
def media_files(tmp_path_factory):
    root = tmp_path_factory.mktemp('finite-media')
    executable = TOOLS / 'ffmpeg/ffmpeg.exe'
    def generate(*args):
        subprocess.run([str(executable), '-v', 'error', '-y', *args], check=True, capture_output=True, cwd=root)
    generate('-f', 'lavfi', '-i', 'color=c=red:s=160x90:r=10:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(root / 'video.mp4'))
    generate('-f', 'lavfi', '-i', 'sine=frequency=440:duration=1', '-c:a', 'aac', str(root / 'audio.m4a'))
    generate('-i', str(root / 'video.mp4'), '-i', str(root / 'audio.m4a'), '-c', 'copy', str(root / 'av.mp4'))
    generate('-i', str(root / 'av.mp4'), '-c', 'copy', '-hls_time', '0.5', '-hls_segment_filename', str(root / 'segment%03d.ts'), str(root / 'play.m3u8'))
    generate('-i', str(root / 'av.mp4'), '-c', 'copy', '-seg_duration', '0.5', '-f', 'dash', str(root / 'play.mpd'))
    root.joinpath('key.bin').write_bytes(b'0123456789abcdef')
    root.joinpath('key.info').write_text('key.bin\n' + str(root / 'key.bin') + '\n', encoding='utf-8')
    generate('-i', str(root / 'av.mp4'), '-c', 'copy', '-hls_time', '0.5', '-hls_key_info_file', str(root / 'key.info'),
             '-hls_segment_filename', str(root / 'encrypted%03d.ts'), str(root / 'encrypted.m3u8'))
    root.joinpath('live.m3u8').write_text('#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nsegment000.ts\n')
    root.joinpath('drm.mpd').write_text('<MPD type="static" mediaPresentationDuration="PT1S"><Period><ContentProtection schemeIdUri="urn:uuid:test"/></Period></MPD>')
    return root


@contextmanager
def serve_media(root):
    requests = []
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append({'path': self.path, 'ua': self.headers.get('User-Agent', ''),
                             'cookie': self.headers.get('Cookie', ''), 'authorization': self.headers.get('Authorization', '')})
            path = self.path.split('?', 1)[0]
            if path in ('/page', '/popup', '/frame'):
                script = "Promise.all([fetch('/opaque?token=first'),fetch('/frame-audio')]).then(()=>window.ready=true)"
                if path == '/page':
                    script = "fetch('/opaque?token=first').then(()=>window.ready=true)"
                body = ('<!doctype html><meta charset="utf-8"><script>' + script + '</script>').encode()
                self.send_response(200); self.send_header('Content-Type', 'text/html'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            if path in ('/opaque', '/frame-audio'):
                file = root / ('video.mp4' if path == '/opaque' else 'audio.m4a')
                body = file.read_bytes()
                self.send_response(200); self.send_header('Content-Type', 'video/mp4' if path == '/opaque' else 'audio/mp4'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            if path == '/key.bin' and 'media-auth=ok' not in self.headers.get('Cookie', ''):
                self.send_error(403)
                return
            if path == '/redirect':
                self.send_response(302); self.send_header('Location', f'http://localhost:{self.server.server_port}/opaque'); self.end_headers()
                return
            if path == '/slow.m3u8':
                body = root.joinpath('play.m3u8').read_bytes().replace(b'segment000.ts', b'slow.ts')
                self.send_response(200); self.send_header('Content-Type', 'application/vnd.apple.mpegurl'); self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
                return
            if path == '/slow.ts':
                body = root.joinpath('segment000.ts').read_bytes()
                self.send_response(200); self.send_header('Content-Type', 'video/mp2t'); self.send_header('Content-Length', str(len(body))); self.end_headers()
                try:
                    for offset in range(0, len(body), 188):
                        self.wfile.write(body[offset:offset + 188]); self.wfile.flush(); time.sleep(.05)
                except (BrokenPipeError, ConnectionError):
                    pass
                return
            super().do_GET()
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', requests
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


class Cookies:
    def __init__(self):
        self.urls = []

    async def cookies(self, urls):
        self.urls.extend(urls)
        # Prove cookies are obtained per URL, not copied from a captured Cookie header.
        return [{'name': 'media-auth', 'value': 'ok'}] if any('/key.bin' in url for url in urls) else []


def make_run():
    return SimpleNamespace(cancelled=False, download_process=None, session=SimpleNamespace(context=Cookies()))


def inspect_file(path):
    result = subprocess.run([str(TOOLS / 'ffmpeg/ffprobe.exe'), '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                            capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_identity_is_signature_stable_but_keeps_quality():
    item = {'url': 'https://media.example/movie.mp4?token=old&quality=720', 'parent_id': 'lesson'}
    assert resource_identity(item) == resource_identity({**item, 'url': 'https://media.example/movie.mp4?quality=720&token=new'})
    assert resource_identity({**item, 'key': 'logical', 'quality': '720p'}) != resource_identity({**item, 'key': 'logical', 'quality': '1080p'})


def test_capture_keeps_credentials_private_and_refreshes_without_new_identity():
    capture = MediaCapture('session', 'bili')
    first = capture.add({'url': 'https://cdn.example/v.mp4?token=old', 'headers': {'Cookie': 'private', 'Authorization': 'private'},
                         'streams': [{'url': 'https://cdn.example/audio?secret=private'}], 'page_url': 'https://site.example/watch?session=private'})
    assert all(secret not in json.dumps(first) for secret in ('Cookie', 'Authorization', 'token=', 'secret=', 'session='))
    second = capture.add({'url': 'https://cdn.example/v.mp4?token=new', 'headers': {'Cookie': 'refreshed'},
                          'streams': [{'url': 'https://cdn.example/audio?secret=private'}], 'page_url': 'https://site.example/watch?session=private'})
    assert second['id'] == first['id']
    assert len(capture.list()) == 1
    assert capture.get(first['id'])['headers']['Cookie'] == 'refreshed'
    assert capture.get('missing') is None
    assert MediaCapture('different').list() == []
    assert classify('https://example/opaque', 'video/mp4; charset=binary') == ('video', 'mp4')
    assert classify('https://example/opaque', 'image/png') == ('image', 'png')


def test_manifest_quality_selection_keeps_requested_variant_and_refuses_missing_quality():
    proxy = MediaProxy(None, {})
    proxy.base = 'http://127.0.0.1:1234/private/'
    master = '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,RESOLUTION=640x360\nlow.m3u8\n#EXT-X-STREAM-INF:BANDWIDTH=2,RESOLUTION=1280x720\nhigh.m3u8\n'
    result = proxy.rewrite_manifest(master, 'hls', 'https://cdn.example/master.m3u8', {'height': 720})
    assert b'1280x720' in result and b'640x360' not in result
    assert [route[0] for route in proxy.routes.values()] == ['https://cdn.example/high.m3u8']
    with pytest.raises(ValueError, match='清晰度'):
        proxy.rewrite_manifest(master, 'hls', 'https://cdn.example/master.m3u8', {'height': 1080})
    dash = '<MPD type="static" mediaPresentationDuration="PT1S"><Period><AdaptationSet><Representation id="low" height="360"/><Representation id="high" height="720"/></AdaptationSet></Period></MPD>'
    result = proxy.rewrite_manifest(dash, 'dash', 'https://cdn.example/play.mpd', {'height': 720})
    assert b'id="high"' in result and b'id="low"' not in result
    assert manifest_status('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXT-X-ENDLIST', 'hls') == ''
    assert 'DRM' in manifest_status('#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="key"\n#EXT-X-ENDLIST', 'hls')


@pytest.mark.asyncio
async def test_passive_capture_before_navigation_popup_frames_and_hidden_preview(tmp_path, media_files):
    with serve_media(media_files) as (url, requests):
        session = BrowserSession(SessionConfig(platform='generic', url=url + '/page'), tmp_path)
        try:
            await session.start()
            await session.page.wait_for_function('window.ready === true')
            for _ in range(30):
                if session.media.list():
                    break
                await asyncio.sleep(.1)
            resources = session.media.list()
            assert len(resources) == 1
            assert resources[0]['format'] == 'mp4'
            assert resources[0]['origin'] == 'browser'
            assert resources[0]['parent_id'] is None
            assert [request['path'] for request in requests].count('/opaque?token=first') == 1
            # No frames() call was made: discovery is independent of preview visibility.
            async with session.context.expect_page() as created:
                await session.page.evaluate("url => window.open(url)", url + '/popup')
            popup = await created.value
            await popup.wait_for_function('window.ready === true')
            await session.page.evaluate("url => { const f=document.createElement('iframe'); f.src=url; document.body.appendChild(f) }", url + '/frame')
            for _ in range(30):
                if any(resource['kind'] == 'audio' for resource in session.media.list()):
                    break
                await asyncio.sleep(.1)
            assert any(resource['kind'] == 'audio' for resource in session.media.list())
            assert len([resource for resource in session.media.list() if resource['format'] == 'mp4' and resource['kind'] == 'video']) == 1
            assert not any('Lavf' in request['ua'] for request in requests)
            assert len(session.context.pages) == 2
        finally:
            await session.close()
        assert session.media.list() == []


@pytest.mark.asyncio
@pytest.mark.parametrize('manifest', ['play.m3u8', 'play.mpd', 'encrypted.m3u8'])
async def test_finite_hls_dash_and_aes128_output_audio_video(tmp_path, media_files, manifest):
    with serve_media(media_files) as (url, requests):
        run = make_run()
        try:
            path = await download(run, {'id': 'fixture', 'title': 'one video', 'url': url + '/' + manifest}, tmp_path, TOOLS)
        except Exception as exc:
            pytest.fail(f'{exc}; local fixture requests: {requests}')
        info = inspect_file(path)
        assert {stream['codec_type'] for stream in info['streams']} == {'video', 'audio'}
        assert float(info['format']['duration']) > .8
        assert len(list(tmp_path.glob('*.mp4'))) == 1
        assert run.download_process is None
        assert any('Lavf' in request['ua'] for request in requests)
        if manifest == 'encrypted.m3u8':
            assert any('/key.bin' in target for target in run.session.context.urls)
            assert all('media-auth=ok' in request['cookie'] for request in requests if request['path'] == '/key.bin')


@pytest.mark.asyncio
async def test_split_streams_and_ordered_segments_produce_one_logical_file(tmp_path, media_files):
    with serve_media(media_files) as (url, _requests):
        for name, streams in [
            ('split', [{'url': url + '/video.mp4', 'role': 'video'}, {'url': url + '/audio.m4a', 'role': 'audio'}]),
            ('silent', [{'url': url + '/video.mp4', 'role': 'video'}]),
            ('segments', [{'url': url + '/av.mp4?part=1', 'role': 'segment'}, {'url': url + '/av.mp4?part=2', 'role': 'segment'}]),
        ]:
            directory = tmp_path / name
            path = await download(make_run(), {'id': name, 'title': name, 'streams': streams}, directory, TOOLS)
            info = inspect_file(path)
            expected = {'video'} if name == 'silent' else {'video', 'audio'}
            assert {stream['codec_type'] for stream in info['streams']} == expected
            assert len(list(directory.iterdir())) == 1
            if name == 'segments':
                assert float(info['format']['duration']) > 1.7


@pytest.mark.asyncio
@pytest.mark.parametrize('manifest', ['live.m3u8', 'drm.mpd'])
async def test_live_and_drm_are_refused_without_leaking_source_urls(tmp_path, media_files, manifest):
    with serve_media(media_files) as (url, _requests):
        with pytest.raises(RuntimeError, match='直播|DRM') as rejected:
            await download(make_run(), {'id': 'unsupported', 'url': url + '/' + manifest + '?token=secret'}, tmp_path, TOOLS)
        assert 'secret' not in str(rejected.value)
        assert not list(tmp_path.glob('*.mp4'))


@pytest.mark.asyncio
async def test_direct_redirect_does_not_forward_authorization_to_other_origin(tmp_path, media_files):
    with serve_media(media_files) as (url, requests):
        path = await download(make_run(), {'id': 'redirect', 'url': url + '/redirect', 'headers': {
            'Authorization': 'Bearer private-fixture', 'Cookie': 'do-not-forward', 'User-Agent': 'explicit-resource-agent'}}, tmp_path, TOOLS)
        assert path.stat().st_size > 0
        assert requests[0]['authorization'] == 'Bearer private-fixture'
        assert requests[-1]['authorization'] == ''
        assert requests[-1]['cookie'] == ''
        assert requests[-1]['ua'] == 'explicit-resource-agent'


@pytest.mark.asyncio
async def test_archived_custom_platform_cannot_open_session(tmp_path):
    sessions = BrowserSessions(tmp_path, platform_lookup=lambda _id: {'url': 'https://example.test', 'enabled': False, 'legacy': False})
    with pytest.raises(ValueError, match='停用'):
        await sessions.create(SessionConfig(platform='custom_archived'))
    assert sessions.items == {}


@pytest.mark.asyncio
async def test_cancel_cleans_only_the_owned_ffmpeg_process(tmp_path, media_files):
    unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        with serve_media(media_files) as (url, requests):
            run = make_run()
            task = asyncio.create_task(download(run, {'id': 'cancel', 'url': url + '/slow.m3u8'}, tmp_path, TOOLS))
            for _ in range(50):
                if any(request['path'] == '/slow.ts' for request in requests):
                    break
                await asyncio.sleep(.05)
            process = run.download_process
            assert process is not None and process.poll() is None
            run.cancelled = True
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 5)
            assert process.poll() is not None
            assert run.download_process is None
            assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
