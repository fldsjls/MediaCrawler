"""Local response samples: no platform authentication or production network calls."""
import asyncio
import io
from types import SimpleNamespace

import pytest

from api.workbench.adapters.media import bilibili_playback, parse_media
from api.workbench.adapters.media_worker import MediaCoordinator
from api.workbench.runtime import Runtime


def test_bili_dash_selects_highest_video_and_audio_and_retains_segments():
    result = bilibili_playback({'dash': {'video': [
        {'baseUrl': 'https://media/low', 'height': 720, 'id': 64},
        {'baseUrl': 'https://media/high', 'height': 2160, 'id': 120}],
        'audio': [{'baseUrl': 'https://media/audio1', 'bandwidth': 100},
                  {'baseUrl': 'https://media/audio2', 'bandwidth': 200}]}})
    assert result['height'] == 2160
    assert result['streams'] == [{'url': 'https://media/high', 'role': 'video'},
                                 {'url': 'https://media/audio2', 'role': 'audio'}]
    segmented = bilibili_playback({'quality': 80, 'durl': [
        {'order': 2, 'url': 'https://media/2'}, {'order': 1, 'url': 'https://media/1'}]})
    assert segmented['format'] == 'segments'
    assert segmented['height'] == 0  # quality ID 80 is not an 80-pixel resolution
    assert [s['url'] for s in segmented['streams']] == ['https://media/1', 'https://media/2']
    assert bilibili_playback({'durl': [{'url': 'https://media/1'}, {'url': 'blob:missing'}]}) is None


@pytest.mark.parametrize('platform,raw,expected', [
    ('xhs', {'type': 'video', 'video': {'media': {'stream': {'h264': [
        {'master_url': 'https://media/720', 'height': 720},
        {'master_url': 'https://media/1080', 'height': 1080}]}}}}, 'https://media/1080'),
    ('dy', {'aweme_type': 0, 'video': {'bit_rate': [
        {'play_addr': {'url_list': ['https://media/720'], 'height': 720}},
        {'play_addr': {'url_list': ['https://media/1080'], 'height': 1080}}]}}, 'https://media/1080'),
    ('ks', {'photo': {'photoUrl': 'https://media/photo.mp4'}}, 'https://media/photo.mp4'),
    ('wb', {'mblog': {'page_info': {'type': 'video', 'media_info': {
        'mp4_720p_mp4': 'https://media/720', 'mp4_1080p_mp4': 'https://media/1080'}},
        'retweeted_status': {'page_info': {'media_info': {'mp4_2160p_mp4': 'https://ad/2160'}}}}}, 'https://media/1080'),
    ('tieba', {'thread': {'id': 1}, 'first_floor': {'content': [
        {'type': 5, 'src': 'https://media/post.mp4'}]},
        'post_list': [{'content': [{'type': 5, 'src': 'https://ad/reply.mp4'}]}]}, 'https://media/post.mp4'),
    ('zhihu', {'type': 'zvideo', 'video': {'playlist': {
        'ld': {'play_url': 'https://media/480', 'height': 480},
        'hd': {'play_url': 'https://media/1080', 'height': 1080}}}}, 'https://media/1080'),
    ('zhihu', {'type': 'answer', 'content': '<video><source src="https://media/body.mp4"></video>'}, 'https://media/body.mp4'),
])
def test_platform_content_samples_choose_only_owned_video(platform, raw, expected):
    result = parse_media(platform, raw)
    assert result.status == 'available'
    assert result.videos[0]['url'] == expected


def test_image_post_excludes_background_music_and_explicit_none_vs_unresolved():
    result = parse_media('dy', {'aweme_type': 68, 'images': [{'url_list': ['https://media/photo.jpg']}],
                                'video': {'play_addr': {'url_list': ['https://media/background.mp4']}}})
    assert result.status == 'none' and result.videos == []
    assert result.images == ['https://media/photo.jpg']
    assert parse_media('xhs', {'type': 'normal'}).status == 'none'
    assert parse_media('xhs', {'type': 'video', 'video': {}}).status == 'unresolved'
    assert parse_media('wb', {'mblog': {'text': 'text only'}}).status == 'none'
    assert parse_media('tieba', {'first_floor': {'content': [{'type': 0, 'text': 'text'}]}}).status == 'none'
    embedded = parse_media('zhihu', {'type': 'answer', 'content': '<a data-video-id="123">Video</a>'})
    assert embedded.confirmed and embedded.status == 'unresolved'


def record(platform='xhs'):
    return {'id': 'content:42', 'source_id': '42', 'title': 'Example',
            'fields': {'note_url': 'https://platform/note/42', 'video_id': '42'}}


@pytest.mark.asyncio
async def test_independent_selection_and_stable_resource_headers():
    runtime = Runtime()
    cfg = {'max_downloads': 4, 'max_items': 1, 'download_video': False, 'download_images': True}
    crawler = SimpleNamespace(client=SimpleNamespace(headers={'Cookie': 'secret', 'Authorization': 'secret', 'User-Agent': 'test'}))
    media = MediaCoordinator('xhs', cfg, runtime, crawler)
    media.raw_content.set({'type': 'video', 'video': {'media': {'stream': {'h264': [{'master_url': 'https://media/video.mp4'}]}}},
                           'image_list': [{'url_default': 'https://media/cover.jpg'}]})
    status, resources, errors = await media.resolve(record())
    assert status == 'available' and not errors
    assert len(resources) == 1 and resources[0]['kind'] == 'image'
    assert resources[0]['key'] == 'xhs:42:image:0'
    assert resources[0]['headers'] == {'User-Agent': 'test', 'Referer': 'https://platform/note/42'}
    media.download_images = False
    assert (await media.resolve(record()))[1:] == ([], [])
    media.download_video = True
    media.raw_content.set({'type': 'video'})
    assert len((await media.resolve(record()))[2]) == 1
    media.raw_content.set({'type': 'normal'})
    assert await media.resolve(record()) == ('none', [], [])


@pytest.mark.asyncio
async def test_bili_coordinator_uses_highest_request_and_one_resource_per_part():
    calls = []
    class Client:
        headers = {}
        async def get(self, path, params, **kwargs):
            calls.append((path, params, kwargs))
            return {'durl': [{'url': f'https://media/{params["cid"]}/1', 'order': 1},
                             {'url': f'https://media/{params["cid"]}/2', 'order': 2}]}
    media = MediaCoordinator('bili', {'max_downloads': 3, 'max_items': 1, 'download_video': True}, Runtime(),
                             SimpleNamespace(bili_client=Client()))
    media.raw_content.set({'View': {'aid': 42, 'pages': [{'cid': 101, 'part': 'One'}, {'cid': 102, 'part': 'Two'}]}})
    item = record('bili')
    item['fields']['video_url'] = 'https://www.bilibili.com/video/av42'
    status, resources, errors = await media.resolve(item)
    assert status == 'available' and not errors and len(resources) == 2
    assert {r['key'] for r in resources} == {'bili:42:video:101', 'bili:42:video:102'}
    assert all(len(r['streams']) == 2 and r['format'] == 'segments' for r in resources)
    assert all(c[1]['qn'] == 127 and c[1]['fnval'] == 4048 for c in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize('platform', ['tieba', 'zhihu'])
async def test_real_extractor_store_preserves_scoped_media_without_raw_author(platform, monkeypatch):
    import importlib
    from var import source_keyword_var
    source_keyword_var.set('fixture')
    store = importlib.import_module(f'store.{platform}')
    helper = importlib.import_module(f'media_platform.{platform}.help')
    cls = helper.TieBaExtractor if platform == 'tieba' else helper.ZhihuExtractor
    names = ['extract_note_detail_from_api'] if platform == 'tieba' else ['_extract_answer_content', '_extract_article_content', '_extract_zvideo_content']
    store_method = 'update_tieba_note' if platform == 'tieba' else 'update_zhihu_content'
    # Register restoration before install mutates the per-process adapter methods.
    for name in names:
        monkeypatch.setattr(cls, name, getattr(cls, name))
    monkeypatch.setattr(store, store_method, getattr(store, store_method))
    media = MediaCoordinator(platform, {'max_downloads': 1, 'max_items': 1, 'download_video': True}, Runtime(), SimpleNamespace())
    media.install(platform)
    saved = []
    class Sink:
        async def store_content(self, fields):
            item = record(platform)
            item['fields'] = fields
            status, resources, errors = await media.resolve(item)
            saved.append((fields, status, resources, errors))
    factory = store.TieBaStoreFactory if platform == 'tieba' else store.ZhihuStoreFactory
    monkeypatch.setattr(factory, 'create_store', lambda: Sink())
    raw = ({'thread': {'id': '42'}, 'first_floor': {'content': [{'type': 5, 'src': 'https://media/owned.mp4'}]}}
           if platform == 'tieba' else {'id': '42', 'type': 'answer', 'question': {'id': 1},
               'content': '<video src="https://media/owned.mp4"></video>', 'author': {'id': 'private-id', 'name': 'PrivateName'}})
    obj = getattr(cls(), names[0])(raw)
    await getattr(store, store_method)(obj)
    fields, status, resources, errors = saved[0]
    assert status == 'available' and len(resources) == 1 and not errors
    assert resources[0]['url'] == 'https://media/owned.mp4'
    assert 'author' not in fields and 'private-id' not in str(fields)
    assert media.raw_content.get() is None and not media.extracted


@pytest.mark.asyncio
async def test_local_browser_fallback_scopes_content_and_obeys_pause(tmp_path):
    from api.workbench.browser import BrowserSession
    from api.workbench.models import SessionConfig
    session = BrowserSession(SessionConfig(platform='generic'), tmp_path)
    runtime = Runtime()
    runtime.output = io.StringIO()
    try:
        await session.start()
        page = session.page
        await page.route('https://fixture.test/**', lambda route: route.fulfill(body='<!doctype html><body></body>', content_type='text/html'))
        await page.goto('https://fixture.test/question/1/answer/42')
        await page.set_content('''<video src="https://ads.invalid/ad.mp4"></video>
            <div class="AnswerItem" data-aid="99"><video src="https://ads.invalid/other.mp4"></video></div>
            <div class="AnswerItem" data-aid="42"><video width="100" height="60" src="https://fixture.test/owned.mp4" onclick="window.hits=(window.hits||0)+1"></video></div>''')
        media = MediaCoordinator('zhihu', {'max_downloads': 2, 'max_items': 1, 'download_video': True, 'wait_ms': 0},
                                 runtime, SimpleNamespace(context_page=page))
        item = record('zhihu')
        item['fields'] = {'content_type': 'answer'}
        runtime.pause()
        pending = asyncio.create_task(media.browser_fallback(item, page.url))
        await asyncio.sleep(.05)
        assert not pending.done() and not await page.evaluate('window.hits')
        await runtime.resume()
        found = await pending
        assert [v['url'] for v in found.videos] == ['https://fixture.test/owned.mp4']
        assert await page.evaluate('window.hits') == 1
        await page.locator('[data-aid="42"] video').evaluate('(v)=>v.src="blob:unresolved"')
        found = await media.browser_fallback(item, page.url)
        assert found.status == 'unresolved' and not found.videos
    finally:
        await session.close()
