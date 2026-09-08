"""Logical videos and segment failure regressions; no platform requests."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from mediacrawler.workbench.platforms.adapters.media import parse_media
from mediacrawler.workbench.platforms.adapters.media_worker import MediaCoordinator
from mediacrawler.workbench.downloads import downloader
from mediacrawler.workbench.workflows.runtime import Runtime


@pytest.mark.parametrize('platform', ['zhihu', 'tieba'])
@pytest.mark.asyncio
async def test_body_videos_choose_quality_per_element_with_stable_keys(platform):
    media = MediaCoordinator(platform, {'download_video': True, 'max_downloads': 4, 'max_items': 1}, Runtime(), SimpleNamespace())
    record = dict(id='content:one', source_id='one', title='Two videos', fields={})
    previous = None
    for quality, token in [(720, 'old'), (1080, 'new')]:
        body = (f'<video data-video-id="first"><source src="https://media/a-low.mp4" height="360">'
                f'<source src="https://media/a-{quality}.mp4?token={token}" height="{quality}"></video>'
                f'<video><source src="https://media/b-low.mp4" height="360">'
                f'<source src="https://media/b-{quality}.mp4?token={token}" height="{quality}"></video>')
        raw = dict(type='answer', content=body) if platform == 'zhihu' else dict(first_floor={'content': body})
        parsed = parse_media(platform, raw)
        assert len(parsed.videos) == 2
        assert all(v['height'] == quality for v in parsed.videos)
        assert [v['url'].split('/')[-1][0] for v in parsed.videos] == ['a', 'b']
        media.raw_content.set(raw)
        status, resources, errors = await media.resolve(record)
        keys = [r['key'] for r in resources]
        assert status == 'available' and not errors and len(set(keys)) == 2
        assert keys[0].startswith(f'{platform}:one:video:id:')
        assert keys[1] == f'{platform}:one:video:html:1'
        if previous is not None:
            assert keys == previous  # quality and token changes never change logical identity
        previous = keys


def test_tieba_independent_blocks_and_root_alias_are_not_globally_ranked():
    first = dict(type=5, video_id='a', src='https://media/a.mp4', height=720,
                 playlist={'hd': dict(play_url='https://media/a-hd.mp4', height=1080)})
    second = dict(type=5, video_id='b', src='https://media/b.mp4', height=480)
    parsed = parse_media('tieba', dict(thread={'video_info': first}, first_floor={'content': [first, second]}))
    assert [v['url'] for v in parsed.videos] == ['https://media/a-hd.mp4', 'https://media/b.mp4']
    assert len({v['logical_id'] for v in parsed.videos}) == 2
    reordered = parse_media('tieba', dict(first_floor={'content': [second, first]}))
    assert {v['logical_id'] for v in reordered.videos} == {v['logical_id'] for v in parsed.videos}


def test_unresolved_first_video_keeps_later_video_identity_and_plain_text_is_absent():
    unresolved = parse_media('zhihu', dict(type='answer', content='<video src="blob:unresolved"></video><video src="https://media/b.mp4"></video>'))
    resolved = parse_media('zhihu', dict(type='answer', content='<video src="https://media/a.mp4"></video><video src="https://media/b.mp4"></video>'))
    assert unresolved.videos[0]['logical_id'] == resolved.videos[1]['logical_id'] == 'html:1'
    assert parse_media('zhihu', dict(type='answer', content='<p>Only text</p>')).status == 'none'


@pytest.mark.parametrize('failure', ['expired', 'concat', 'cancelled'])
@pytest.mark.asyncio
async def test_segment_failure_preserves_origin_status_and_cleans_every_owned_partial(tmp_path, monkeypatch, failure):
    toolspath = tmp_path / 'ffmpeg'
    toolspath.mkdir()
    (toolspath / 'ffmpeg.exe').write_bytes(b'not executed')
    destination = tmp_path / 'output'
    destination.mkdir()
    untouched = destination / 'unrelated.segment-00000.ts'
    untouched.write_bytes(b'other task')
    calls = []
    class Proxy:
        def __init__(self, *args): self.errors = []
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        def register(self, url, resource): return 'http://127.0.0.1/opaque'
    proxy = Proxy()
    async def fake_ffmpeg(run, executable, args):
        output = Path(args[-1])
        output.write_bytes(b'part written before failure')
        calls.append(output.name)
        if failure == 'expired' and len(calls) == 2:
            proxy.errors.append('媒体请求返回 HTTP 403')
            raise RuntimeError('媒体合并失败：HTTP 502 Bad Gateway')
        if failure == 'cancelled' and len(calls) == 2:
            raise asyncio.CancelledError()
        if failure == 'concat' and len(calls) == 3:
            raise RuntimeError('concat failed')
    monkeypatch.setattr(downloader, 'MediaProxy', lambda *args: proxy)
    monkeypatch.setattr(downloader, 'ffmpeg', fake_ffmpeg)
    expected = asyncio.CancelledError if failure == 'cancelled' else RuntimeError
    match = None if failure == 'cancelled' else 'HTTP 403' if failure == 'expired' else 'concat failed'
    with pytest.raises(expected, match=match):
        await downloader.download(SimpleNamespace(cancelled=False), dict(id='owned', title='clip',
            streams=[dict(role='segment', url=f'https://media/{n}.mp4') for n in (1, 2)]), destination, toolspath)
    assert list(destination.iterdir()) == [untouched]

@pytest.mark.asyncio
async def test_mixed_video_resolution_keeps_good_resource_and_emits_owned_failure():
    runtime = Runtime()
    events = []
    runtime.emit = lambda event, **data: events.append((event, data))
    media = MediaCoordinator('zhihu', {'download_video': True, 'max_downloads': 4, 'max_items': 1}, runtime, SimpleNamespace())
    media.raw_content.set(dict(type='answer', content='<video src="https://media/a.mp4"></video><video src="blob:unresolved"></video>'))
    record = dict(id='content:mixed', source_id='mixed', title='Mixed', fields={})
    status, resources, errors = await media.resolve(record)
    assert status == 'available' and len(resources) == 1 and resources[0]['key'].endswith(':html:0')
    assert len(errors) == 1 and 'html:1' in errors[0] and '人工播放' in errors[0]
    media.publish(record, resources, errors)
    assert [event for event, _ in events] == ['resource', 'failure']
    assert events[1][1]['parent_id'] == 'content:mixed'
    media.download_video = False
    assert (await media.resolve(record))[1:] == ([], [])
