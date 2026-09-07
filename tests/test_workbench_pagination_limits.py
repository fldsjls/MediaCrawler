"""Run the upstream pagination loops against perpetual local page fixtures."""
import importlib
import io
from types import SimpleNamespace

import pytest

from mediacrawler.workbench.platform_worker import install_pagination_limits
from mediacrawler.workbench.runtime import Runtime


def runtime():
    value = Runtime()
    value.output = io.StringIO()
    return value


@pytest.mark.asyncio
@pytest.mark.parametrize('platform,module_name,class_name,page_method,all_method', [
    ('xhs', 'xhs', 'XiaoHongShuClient', 'get_notes_by_creator', 'get_all_notes_by_creator'),
    ('dy', 'douyin', 'DouYinClient', 'get_user_aweme_posts', 'get_all_user_aweme_posts'),
    ('ks', 'kuaishou', 'KuaiShouClient', 'get_video_by_creater_v2', 'get_all_videos_by_creator'),
    ('wb', 'weibo', 'WeiboClient', 'get_notes_by_creator', 'get_all_notes_by_creator_id'),
    ('zhihu', 'zhihu', 'ZhiHuClient', 'get_creator_answers', 'get_all_anwser_by_creator'),
])
async def test_creator_perpetual_pages_stop_after_shared_budget_and_finish_callbacks(
    monkeypatch, platform, module_name, class_name, page_method, all_method,
):
    module = importlib.import_module(f'mediacrawler.platforms.{module_name}.client')
    parent = getattr(module, class_name)
    calls, completed = [], []
    content_ids = set()

    async def page(self, *args, **kwargs):
        calls.append(args)
        assert len(calls) <= 2, 'Unbounded creator pagination dispatched a third real request'
        rows = [{'id': f'{len(calls)}-{n}', 'card_type': 9} for n in range(2)]
        return {
            'notes': rows, 'has_more': True, 'cursor': str(len(calls)),
            'aweme_list': rows, 'max_cursor': len(calls),
            'result': 1, 'feeds': rows, 'pcursor': str(len(calls)),
            'cards': rows, 'cardlistInfo': {'total': 100000, 'since_id': str(len(calls))},
            'data': rows, 'paging': {'is_end': False},
        }

    cls = type('BoundedCreatorFixture', (parent,), {page_method: page})
    client = object.__new__(cls)
    client._extractor = SimpleNamespace(extract_content_list_from_creator=lambda rows: rows)
    if hasattr(module, 'random'):
        monkeypatch.setattr(module.random, 'uniform', lambda *_: 0)
    install_pagination_limits(cls, platform, {'max_items': 3, 'max_comments': 3}, runtime(), content_ids, {})

    async def callback(rows):
        for row in rows:
            content_ids.add(row['id'])
            completed.append(('content', row['id']))
            completed.append(('media_and_comments', row['id']))

    args = ['creator'] + (['container'] if platform == 'wb' else [])
    kwargs = {'callback': callback}
    if platform != 'dy':
        kwargs['crawl_interval'] = 0
    result = await getattr(client, all_method)(*args, **kwargs)
    assert len(result) == 3
    assert len(calls) == 2
    assert len(content_ids) == 3
    assert len(completed) == 6
    # A second creator consumes the same task budget and performs no requests.
    assert await getattr(client, all_method)(*(['creator2'] + args[1:]), **kwargs) == []
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('platform,module_name,class_name', [
    ('xhs', 'xhs', 'XiaoHongShuClient'),
    ('dy', 'douyin', 'DouYinClient'),
    ('ks', 'kuaishou', 'KuaiShouClient'),
    ('bili', 'bilibili', 'BilibiliClient'),
])
async def test_root_and_child_comments_share_request_budget(monkeypatch, platform, module_name, class_name):
    import mediacrawler.config as config
    monkeypatch.setattr(config, 'ENABLE_GET_SUB_COMMENTS', True)
    module = importlib.import_module(f'mediacrawler.platforms.{module_name}.client')
    if hasattr(module, 'random'):
        monkeypatch.setattr(module.random, 'uniform', lambda *_: 0)
    parent = getattr(module, class_name)
    calls = {'root': 0, 'child': 0}
    seen = {'note': set()}

    async def root(self, *args, **kwargs):
        calls['root'] += 1
        assert calls['root'] == 1
        row = {'id': 'r', 'cid': 'r', 'rpid': 'r', 'comment_id': 'r', 'note_id': 'note',
               'reply_comment_total': 9999, 'rcount': 9999, 'hasSubComments': True,
               'sub_comment_has_more': True, 'sub_comment_cursor': 'start'}
        return {'comments': [row], 'has_more': True, 'cursor': {'is_end': False, 'next': 1} if platform == 'bili' else 'next',
                'rootCommentsV2': [row], 'pcursorV2': 'next', 'replies': [row]}

    async def child(self, *args, **kwargs):
        calls['child'] += 1
        assert calls['child'] == 1
        rows = [{'id': str(n), 'cid': str(n), 'rpid': str(n), 'comment_id': str(n)} for n in range(10)]
        return {'comments': rows, 'has_more': True, 'cursor': 'again',
                'subCommentsV2': rows, 'pcursorV2': 'again', 'replies': rows, 'page': {'count': 100000}}

    root_name, child_name, all_name = {
        'xhs': ('get_note_comments', 'get_note_sub_comments', 'get_note_all_comments'),
        'dy': ('get_aweme_comments', 'get_sub_comments', 'get_aweme_all_comments'),
        'ks': ('get_video_comments', 'get_video_sub_comments', 'get_video_all_comments'),
        'bili': ('get_video_comments', 'get_video_level_two_comments', 'get_video_all_comments'),
    }[platform]
    # Preserve the real signatures so note IDs bind exactly as they do in production.
    import functools
    root = functools.wraps(getattr(parent, root_name))(root)
    child = functools.wraps(getattr(parent, child_name))(child)
    cls = type('BoundedCommentFixture', (parent,), {root_name: root, child_name: child})
    client = object.__new__(cls)
    install_pagination_limits(cls, platform, {'max_items': 3, 'max_comments': 3}, runtime(), {'note'}, seen)

    async def callback(note_id, rows):
        assert note_id == 'note'
        seen[note_id].update(row['id'] for row in rows)

    kwargs = {'callback': callback, 'crawl_interval': 0, 'max_count': 3}
    if platform in ('dy', 'bili'):
        kwargs['is_fetch_sub_comments'] = True
    args = ['note', 'token'] if platform == 'xhs' else ['note']
    await getattr(client, all_name)(*args, **kwargs)
    assert seen['note'] == {'r', '0', '1'}
    assert calls == {'root': 1, 'child': 1}


@pytest.mark.asyncio
async def test_zhihu_root_and_child_budget_uses_owning_content_context():
    from mediacrawler.platforms.zhihu.client import ZhiHuClient
    calls = []

    class Fixture(ZhiHuClient):
        async def get_root_comments(self, content_id, content_type, offset='', limit=10, order_by='score'):
            calls.append('root')
            return {'data': [{'id': 1}], 'paging': {'is_end': False}}
        async def get_child_comments(self, root_comment_id, offset='', limit=10, order_by='sort'):
            calls.append('child')
            return {'data': [{'id': 2}, {'id': 3}, {'id': 4}], 'paging': {'is_end': False}}
        async def get_note_all_comments(self, content, **kwargs):
            roots = await self.get_root_comments(content.content_id, 'answer')
            children = await self.get_child_comments('root-id')
            after = await self.get_root_comments(content.content_id, 'answer', 'second-page')
            return roots, children, after

    install_pagination_limits(Fixture, 'zhihu', {'max_items': 3, 'max_comments': 3}, runtime(), set(), {})
    first, second, last = await object.__new__(Fixture).get_note_all_comments(SimpleNamespace(content_id='answer-id'))
    assert len(first['data']) == 1 and len(second['data']) == 2
    assert not last['data'] and last['paging']['is_end']
    assert calls == ['root', 'child']


@pytest.mark.asyncio
async def test_tieba_html_sub_comments_stop_before_later_roots(monkeypatch):
    import mediacrawler.config as config
    from mediacrawler.platforms.tieba.client import BaiduTieBaClient
    from mediacrawler.platforms.models.m_baidu_tieba import TiebaComment
    monkeypatch.setattr(config, 'ENABLE_GET_SUB_COMMENTS', True)
    monkeypatch.setattr(config, 'CRAWLER_MAX_SLEEP_SEC', 0)
    calls = []
    seen = {'note': {'existing-root'}}

    class Page:
        async def goto(self, url, **kwargs):
            calls.append(url)
            assert len(calls) == 1, 'No second sub-comment page/root may be requested after the cap'
        async def content(self):
            return '<fixture>'

    class Fixture(BaiduTieBaClient):
        pass
    client = object.__new__(Fixture)
    client.playwright_page = Page()
    client._host = 'http://127.0.0.1'
    client._page_extractor = SimpleNamespace(extract_tieba_note_sub_comments=lambda *_args, **_kwargs: ['c1', 'c2'])
    root = TiebaComment(comment_id='root1', content='root', note_id='note', note_url='http://127.0.0.1/',
                        tieba_id='bar', tieba_name='fixture', tieba_link='http://127.0.0.1/', sub_comment_count=100000)
    install_pagination_limits(Fixture, 'tieba', {'max_items': 3, 'max_comments': 3}, runtime(), {'note'}, seen)
    async def callback(note_id, rows):
        seen[note_id].update(rows)
    result = await client.get_comments_all_sub_comments([root, root.model_copy(update={'comment_id': 'root2'})],
                                                         crawl_interval=0, callback=callback)
    assert result == ['c1', 'c2']
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('empty', [False, True])
async def test_creator_repeating_cursor_or_empty_more_page_stops(empty):
    from mediacrawler.platforms.douyin.client import DouYinClient
    calls = []
    class Fixture(DouYinClient):
        async def get_user_aweme_posts(self, sec_user_id, max_cursor=''):
            calls.append(max_cursor)
            assert len(calls) <= 2
            return {'aweme_list': [] if empty else [{'aweme_id': 'same'}], 'has_more': 1, 'max_cursor': 'unchanged'}
    install_pagination_limits(Fixture, 'dy', {'max_items': 100, 'max_comments': 3}, runtime(), set(), {})
    await object.__new__(Fixture).get_all_user_aweme_posts('creator')
    assert len(calls) == (1 if empty else 2)


@pytest.mark.asyncio
async def test_weibo_without_abstract_base_still_pauses_and_refreshes_cookies():
    import asyncio
    import types
    from mediacrawler.common.base.base_crawler import AbstractApiClient
    from mediacrawler.platforms.weibo.client import WeiboClient
    from mediacrawler.workbench.platform_worker import install_request_barrier, refresh_adapter_login
    calls = []
    class Fixture(WeiboClient):
        __module__ = 'fixture.weibo'
        async def request(self, *args, **kwargs):
            calls.append('request')
        async def update_cookies(self, browser_context, urls=None):
            calls.append(('cookies', browser_context, urls))
        async def pong(self):
            calls.append('pong')
            return True
    module = types.ModuleType('fixture.weibo')
    module.Fixture = Fixture
    client = object.__new__(Fixture)
    assert not isinstance(client, AbstractApiClient)
    barrier = runtime()
    install_request_barrier(module, barrier)
    barrier.pause()
    request = asyncio.create_task(client.request('GET', '/fixture'))
    await asyncio.sleep(0)
    assert calls == []
    crawler = SimpleNamespace(wb_client=client, browser_context='owned-context', cookie_urls=['https://weibo.com'])
    barrier.resume_check = lambda: refresh_adapter_login(crawler)
    await barrier.resume()
    await request
    assert calls == [('cookies', 'owned-context', ['https://weibo.com']), 'pong', 'request']


@pytest.mark.asyncio
@pytest.mark.parametrize('platform,module_name,class_name,method_name,empty_field', [
    ('xhs', 'xhs', 'XiaoHongShuClient', 'get_note_by_keyword', 'items'),
    ('ks', 'kuaishou', 'KuaiShouClient', 'search_info_by_keyword_v2', 'feeds'),
])
async def test_multiple_search_keywords_do_not_request_after_common_limit(
    monkeypatch, platform, module_name, class_name, method_name, empty_field,
):
    import mediacrawler.config as config
    monkeypatch.setattr(config, 'CRAWLER_MAX_NOTES_COUNT', 20)
    module = importlib.import_module(f'mediacrawler.platforms.{module_name}.client')
    seen, requests = set(), []
    async def original(self, keyword, **kwargs):
        requests.append(keyword)
        return {empty_field: [{'id': n} for n in range(20)], 'has_more': True, 'result': 1}
    cls = type('SearchFixture', (getattr(module, class_name),), {method_name: original})
    install_pagination_limits(cls, platform, {'max_items': 3, 'max_comments': 3}, runtime(), seen, {})
    client = object.__new__(cls)
    for keyword in ['first', 'second', 'third']:
        response = await getattr(client, method_name)(keyword=keyword)
        for row in response[empty_field]:
            if len(seen) < 3:
                seen.add(row['id'])
    assert requests == ['first']
    assert seen == {0, 1, 2}
    assert config.CRAWLER_MAX_NOTES_COUNT == 0
