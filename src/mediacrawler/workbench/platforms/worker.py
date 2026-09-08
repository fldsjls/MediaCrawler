"""Run upstream adapters against the workbench-owned browser, in an isolated process.

Hooks are installed only in this worker. Original CLI behaviour and anonymisation stay intact.
"""
import asyncio
import contextvars
import hashlib
import importlib
import inspect
import json
import logging
import os
import sys
from pathlib import Path

from mediacrawler.workbench.workflows.runtime import Runtime
from mediacrawler.workbench.browser.preview.internal import public_pages

MODULES = {'bili': 'bilibili', 'xhs': 'xhs', 'dy': 'douyin', 'ks': 'kuaishou',
           'wb': 'weibo', 'tieba': 'tieba', 'zhihu': 'zhihu'}


def is_adapter_client(value):
    # Weibo's upstream client implements the same protocol without inheriting
    # AbstractApiClient. Ownership/coordination must follow capabilities as well.
    return callable(getattr(value, 'request', None)) and callable(getattr(value, 'update_cookies', None))


def install_request_barrier(module, runtime):
    for _, cls in inspect.getmembers(module, inspect.isclass):
        if cls.__module__ == module.__name__ and is_adapter_client(cls):
            cls.request = runtime.wrap(cls.request)


async def refresh_adapter_login(crawler):
    for client in vars(crawler).values():
        if not is_adapter_client(client):
            continue
        signature = inspect.signature(client.update_cookies)
        kwargs = {'browser_context': crawler.browser_context}
        if 'urls' in signature.parameters:
            kwargs['urls'] = getattr(crawler, 'cookie_urls', [])
        await client.update_cookies(**kwargs)
        pong = getattr(client, 'pong', None)
        if pong and not await pong():
            return False
    return True


def install_pagination_limits(client_class, platform, cfg, runtime, content_ids, comment_ids):
    """Bound existing iterators through their page responses, preserving callbacks.

    Returning an exhausted page lets upstream finish the selected batch's comments
    and media normally. Budgets include rows already dispatched to callbacks, so a
    child-comment loop cannot consume an unlimited number before roots are stored.
    """
    import functools
    parent_scope = contextvars.ContextVar('workbench_comment_parent', default='')
    reserved_content = 0
    reserved_comments = {}
    seen_pages = set()

    def field(value, path, default=None):
        for key in path:
            if not isinstance(value, dict):
                return default
            value = value.get(key, default)
        return value

    def replace(value, path, replacement):
        value = dict(value)
        if len(path) == 1:
            value[path[0]] = replacement
        else:
            value[path[0]] = replace(value.get(path[0]) or {}, path[1:], replacement)
        return value

    def wrap_page(name, rows_path, stop_values, *, comments=False, parent_parameter=None, empty_values=None):
        if not hasattr(client_class, name):
            return
        original = getattr(client_class, name)
        signature = inspect.signature(original)

        def finish(response, rows):
            result = replace(response, rows_path, rows)
            for path, value in stop_values:
                result = replace(result, path, value)
            return result

        @functools.wraps(original)
        async def page(client, *args, **kwargs):
            nonlocal reserved_content
            await runtime.checkpoint()
            arguments = signature.bind(client, *args, **kwargs).arguments
            parent = str(arguments.get(parent_parameter, '') or parent_scope.get()) if comments else ''
            remaining = max(0, cfg['max_comments'] - max(reserved_comments.get(parent, 0), len(comment_ids.get(parent, ())))) if comments else max(0, cfg['max_items'] - max(reserved_content, len(content_ids)))
            key = (name, json.dumps({k: v for k, v in arguments.items() if k != 'self'}, sort_keys=True, default=str))
            if not remaining or key in seen_pages:
                return finish(empty_values or {}, [])
            response = await original(client, *args, **kwargs)
            if not isinstance(response, dict):
                return response
            rows = field(response, rows_path)
            if not isinstance(rows, list):
                return response  # preserve the adapter's original API-error handling
            seen_pages.add(key)
            if platform == 'wb' and not comments:
                rows = [row for row in rows if row.get('card_type') == 9]
            selected = rows[:remaining]
            if comments:
                reserved_comments[parent] = reserved_comments.get(parent, 0) + len(selected)
            else:
                reserved_content += len(selected)
            if not selected or len(selected) >= remaining:
                return finish(response, selected)
            return replace(response, rows_path, selected)
        setattr(client_class, name, page)

    # Creator iterators with no intrinsic task-wide cap. XHS is also wrapped so a
    # second creator shares the first creator's budget rather than starting over.
    creators = {
        'xhs': [('get_notes_by_creator', ('notes',), [(('has_more',), False)], {})],
        'dy': [('get_user_aweme_posts', ('aweme_list',), [(('has_more',), 0)], {})],
        'ks': [('get_video_by_creater_v2', ('feeds',), [(('pcursor',), 'no_more')], {'result': 1})],
        'wb': [('get_notes_by_creator', ('cards',), [(('cardlistInfo', 'total'), 0)], {})],
        'zhihu': [(name, ('data',), [(('paging', 'is_end'), True)], {}) for name in
                  ('get_creator_answers', 'get_creator_articles', 'get_creator_videos')],
    }
    for name, rows, stops, empty in creators.get(platform, []):
        wrap_page(name, rows, stops, empty_values=empty)

    # Search adapters fetch whole pages and some count their limit per keyword.
    # Let the current page finish, then avoid all later page/keyword requests once
    # the common saved-content budget is exhausted. Success-shaped empty responses
    # preserve each adapter's existing handling instead of reporting a false error.
    searches = {
        'xhs': ('get_note_by_keyword', {'items': [], 'has_more': False}),
        'dy': ('search_info_by_keyword', {'data': [], 'has_more': 0}),
        'ks': ('search_info_by_keyword_v2', {'result': 1, 'feeds': [], 'pcursor': 'no_more'}),
        'wb': ('get_note_by_keyword', {'cards': []}),
        'tieba': ('get_notes_by_keyword', []),
        'zhihu': ('get_note_by_keyword', []),
    }
    search_name, exhausted = searches.get(platform, ('', None))
    if search_name and hasattr(client_class, search_name):
        original_search = getattr(client_class, search_name)
        @functools.wraps(original_search)
        async def search(client, *args, **kwargs):
            await runtime.checkpoint()
            if len(content_ids) >= cfg['max_items']:
                # Kuaishou/Weibo do not break on an empty successful page. Their
                # loop bound can now close after this iteration, including later
                # keywords; all selected content has already reached storage.
                import mediacrawler.config as config
                config.CRAWLER_MAX_NOTES_COUNT = 0
                return exhausted.copy()
            return await original_search(client, *args, **kwargs)
        setattr(client_class, search_name, search)

    # Zhihu's child endpoint has only a comment ID, so preserve the owning content
    # ID in task-local context while the upstream root/sub-comment iterator runs.
    if platform == 'zhihu' and hasattr(client_class, 'get_note_all_comments'):
        original_all = client_class.get_note_all_comments
        signature = inspect.signature(original_all)
        @functools.wraps(original_all)
        async def scoped(client, *args, **kwargs):
            content = signature.bind(client, *args, **kwargs).arguments['content']
            token = parent_scope.set(str(content.content_id))
            try:
                return await original_all(client, *args, **kwargs)
            finally:
                parent_scope.reset(token)
        client_class.get_note_all_comments = scoped

    comments = {
        'xhs': [(name, ('comments',), [(('has_more',), False)], 'note_id') for name in ('get_note_comments', 'get_note_sub_comments')],
        'dy': [(name, ('comments',), [(('has_more',), 0)], 'aweme_id') for name in ('get_aweme_comments', 'get_sub_comments')],
        'ks': [('get_video_comments', ('rootCommentsV2',), [(('pcursorV2',), 'no_more')], 'photo_id'),
               ('get_video_sub_comments', ('subCommentsV2',), [(('pcursorV2',), 'no_more')], 'photo_id')],
        'wb': [('get_note_comments', ('data',), [(('max_id',), 0)], 'mid_id')],
        'zhihu': [('get_root_comments', ('data',), [(('paging', 'is_end'), True)], 'content_id'),
                  ('get_child_comments', ('data',), [(('paging', 'is_end'), True)], None)],
        'bili': [('get_video_comments', ('replies',), [(('cursor', 'is_end'), True), (('cursor', 'next'), 0)], 'video_id'),
                 ('get_video_level_two_comments', ('replies',), [(('page', 'count'), 0)], 'video_id')],
    }
    for name, rows, stops, parent in comments.get(platform, []):
        wrap_page(name, rows, stops, comments=True, parent_parameter=parent)

    # Tieba's sub-comments are browser HTML, not a JSON cursor endpoint. Keep its
    # extractor/navigation code, but bound each root's advertised page count by
    # the remaining shared comment budget and stop before dispatching another root.
    if platform == 'tieba' and hasattr(client_class, 'get_comments_all_sub_comments'):
        original_sub = client_class.get_comments_all_sub_comments
        signature = inspect.signature(original_sub)
        @functools.wraps(original_sub)
        async def sub_comments(client, *args, **kwargs):
            bound = signature.bind(client, *args, **kwargs)
            result = []
            for comment in bound.arguments['comments']:
                remaining = cfg['max_comments'] - len(comment_ids.get(str(comment.note_id), ()))
                if remaining <= 0:
                    continue
                limited = comment.model_copy(update={'sub_comment_count': min(comment.sub_comment_count, max(1, remaining - 1))})
                bound.arguments['comments'] = [limited]
                result.extend(await original_sub(*bound.args, **bound.kwargs))
            return result
        client_class.get_comments_all_sub_comments = sub_comments


async def run():
    runtime = Runtime()
    sys.stdout = sys.stderr  # third-party print output is logging, never the event protocol
    runtime.emit('phase', phase='preparing', message='正在加载平台适配器与存储依赖')
    cfg = json.loads(os.environ['MC_TASK_CONFIG'])
    if cfg['mode'] == 'detail':
        cfg['target'] = ','.join([value.strip() for value in cfg['target'].split(',') if value.strip()][:cfg['max_items']])
    import mediacrawler.config as config
    from mediacrawler.cli.arguments.arg import parse_cmd
    args = ['--platform', cfg['platform'], '--type', cfg['mode'], '--lt', cfg['login'],
            '--save_data_option', 'jsonl', '--save_data_path', os.environ['MC_TASK_DIR'],
            '--crawler_max_notes_count', str(cfg['max_items']), '--max_concurrency_num', '1',
            '--max_comments_count_singlenotes', str(cfg['max_comments']),
            '--get_comment', str(cfg['comments']).lower(), '--get_sub_comment', str(cfg['subcomments']).lower()]
    args += [{'search': '--keywords', 'detail': '--specified_id', 'creator': '--creator_id'}[cfg['mode']], cfg['target']]
    await parse_cmd(args)
    config.ENABLE_CDP_MODE = False
    # Workbench resolves typed resources from each original content object. Disable
    # the old byte-download sinks so video/image choices cannot cross-trigger them.
    config.ENABLE_GET_MEIDAS = False
    config.COOKIES = cfg.get('cookies', '')
    config.START_PAGE = cfg['start']
    if cfg['platform'] == 'zhihu' and cfg['mode'] == 'creator':
        config.ZHIHU_CREATOR_URL_LIST = [s.strip() for s in cfg['target'].split(',') if s.strip()]
    config.ENABLE_GET_WORDCLOUD = False
    module_name = MODULES[cfg['platform']]
    core = importlib.import_module(f'mediacrawler.platforms.{module_name}.core')
    from mediacrawler.common.base.base_crawler import AbstractCrawler, AbstractApiClient
    crawler_class = next(c for _, c in inspect.getmembers(core, inspect.isclass)
                         if issubclass(c, AbstractCrawler) and c is not AbstractCrawler)
    crawler = crawler_class()
    from mediacrawler.infrastructure.helpers import utils

    class Handler(logging.Handler):
        def emit(self, record):
            text = record.getMessage()
            if cfg.get('cookies'):
                text = text.replace(cfg['cookies'], '[cookies]')
            runtime.emit('log', level=record.levelname.lower(), message=text)
            # A structured failure comes from the error-level logging call, not text parsing.
            if record.levelno >= logging.ERROR:
                runtime.emit('failure', message=text)
    utils.logger.handlers = [Handler()]
    utils.logger.propagate = False
    utils.show_qrcode = lambda *_args, **_kwargs: None

    from playwright.async_api import BrowserContext
    from playwright._impl._connection import Channel
    Channel.send = runtime.wrap(Channel.send)
    original_new_page = BrowserContext.new_page
    reused = False
    async def first_page(context):
        nonlocal reused
        pages = public_pages(context)
        if not reused and pages:
            reused = True
            return pages[0]
        return await original_new_page(context)
    BrowserContext.new_page = first_page

    async def launch(chromium, *_args, **_kwargs):
        browser = await chromium.connect_over_cdp(os.environ['MC_BROWSER_ENDPOINT'])
        return browser.contexts[0]
    crawler.launch_browser = launch

    client_module = importlib.import_module(f'mediacrawler.platforms.{module_name}.client')
    install_request_barrier(client_module, runtime)
    from mediacrawler.workbench.platforms.adapters.media import candidate, parse_media
    from mediacrawler.workbench.platforms.adapters.media_worker import MediaCoordinator
    media_coordinator = MediaCoordinator(cfg['platform'], cfg, runtime, crawler)
    media_coordinator.install(module_name)

    login_module = importlib.import_module(f'mediacrawler.platforms.{module_name}.login')
    for _, cls in inspect.getmembers(login_module, inspect.isclass):
        if cls.__module__ != login_module.__name__ or not hasattr(cls, 'check_login_state'):
            continue
        original = inspect.unwrap(cls.check_login_state)
        async def login_check(self, *args, _original=original, **kwargs):
            # QR display/cookie injection has already happened when upstream calls this check.
            async def validate():
                return await _original(self, *args, **kwargs)
            previous_check = runtime.resume_check
            runtime.resume_check = validate
            try:
                while not await validate():
                    await runtime.wait_login()
                return True
            finally:
                runtime.resume_check = previous_check
        cls.check_login_state = login_check

    from mediacrawler.infrastructure.helpers.async_file_writer import AsyncFileWriter
    original_write = AsyncFileWriter.write_to_jsonl
    content_ids = set()
    comment_ids = {}
    last_record = contextvars.ContextVar('workbench_last_content', default=None)
    persisted_ids = set(json.loads(os.environ.get('MC_EXISTING_RECORDS', '[]')))

    def identity(item, kind):
        keys = (['comment_id', 'cid', 'id'] if kind == 'comment' else
                ['note_id', 'video_id', 'aweme_id', 'mblogid', 'content_id', 'tid', 'id'])
        return str(next((item[k] for k in keys if item.get(k)),
                        hashlib.sha256(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:24]))

    async def write(writer, item, item_type):
        await runtime.checkpoint()
        kind = 'comment' if item_type == 'comments' else ('content' if item_type in ('contents', 'content', 'dynamics') else 'creator')
        local_id = identity(item, kind)
        parent = str(next((item[k] for k in ['note_id', 'video_id', 'aweme_id', 'content_id', 'tieba_id', 'tid'] if item.get(k)), '')) if kind == 'comment' else ''
        if kind == 'content':
            if local_id not in content_ids and len(content_ids) >= cfg['max_items']:
                last_record.set(None)
                return
            content_ids.add(local_id)
        if kind == 'comment':
            if parent and parent not in content_ids:
                return
            seen = comment_ids.setdefault(parent, set())
            if local_id not in seen and len(seen) >= cfg['max_comments']:
                return
            seen.add(local_id)
        record_id = f'{kind}:{local_id}'
        parent_comment = str(item.get('parent_comment_id') or '') if kind == 'comment' else ''
        record = dict(id=f'{kind}:{local_id}', source=cfg['platform'], source_id=local_id, kind=kind,
                      title=str(item.get('title') or item.get('desc') or item.get('content') or local_id)[:500],
                      parent_id=(f'comment:{parent_comment}' if parent_comment not in ('', '0') else
                                 f'content:{parent}' if parent else None), fields=item)
        resources, media_errors = [], []
        if kind == 'content':
            try:
                status, resources, media_errors = await media_coordinator.resolve(record)
            except Exception as exc:
                status = 'unresolved'
                if media_coordinator.download_video:
                    media_errors = [f'内容媒体解析失败：{exc}']
            record['fields'] = {**item, 'video_status': status}
            last_record.set(record)
        if record_id not in persisted_ids:
            await original_write(writer, record['fields'], item_type)
            persisted_ids.add(record_id)
        runtime.emit('record', record=record)
        media_coordinator.publish(record, resources, media_errors)
    AsyncFileWriter.write_to_jsonl = write

    for _, cls in inspect.getmembers(client_module, inspect.isclass):
        if cls.__module__ == client_module.__name__:
            install_pagination_limits(cls, cfg['platform'], cfg, runtime, content_ids, comment_ids)

    if cfg['platform'] == 'bili':
        # Upstream search rounds small limits up to a full page, and creator mode
        # walks every page. Trim discovery before it schedules detail requests;
        # finish this batch's comments/media before returning an exhausted page.
        for _, cls in inspect.getmembers(client_module, inspect.isclass):
            if cls.__module__ != client_module.__name__:
                continue
            for method_name in ('search_video_by_keyword', 'get_creator_videos'):
                if not hasattr(cls, method_name):
                    continue
                original_discovery = getattr(cls, method_name)
                async def limited_discovery(client, *args, _original=original_discovery,
                                            _name=method_name, **kwargs):
                    await runtime.checkpoint()
                    remaining = max(0, cfg['max_items'] - len(content_ids))
                    if not remaining:
                        return {'result': []} if _name == 'search_video_by_keyword' else {'list': {'vlist': []}, 'page': {'count': 0}}
                    result = await _original(client, *args, **kwargs)
                    if not isinstance(result, dict):
                        return result
                    if _name == 'search_video_by_keyword':
                        return {**result, 'result': (result.get('result') or [])[:remaining]}
                    listing = result.get('list') or {}
                    videos = listing.get('vlist') or []
                    page = result.get('page') or {}
                    if len(videos) >= remaining:
                        page = {**page, 'count': 0}
                    return {**result, 'list': {**listing, 'vlist': videos[:remaining]}, 'page': page}
                setattr(cls, method_name, limited_discovery)

    # Compatibility for adapter-specific code that directly calls an old media
    # client method. Normal collection uses the content-scoped resolver above.
    async def media(client, *args, **kwargs):
        await runtime.checkpoint()
        url = args[0] if args else next(iter(kwargs.values()))
        record = last_record.get()
        if record:
            raw = media_coordinator.raw_content.get() or record['fields']
            images = parse_media(cfg['platform'], raw, record['fields']).images
            kind = 'image' if url in images or str(url).split('?')[0].lower().endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')) else 'video'
            enabled = media_coordinator.download_images if kind == 'image' else media_coordinator.download_video
            asset = candidate(url)
            if enabled and asset:
                resource = media_coordinator.resource(record, media_coordinator.page_url(record['fields'], raw), asset, kind, '0')
                media_coordinator.publish(record, [resource], [])
        return None
    for _, cls in inspect.getmembers(client_module, inspect.isclass):
        if cls.__module__ != client_module.__name__:
            continue
        for name in ('get_video_media', 'get_aweme_media', 'get_note_media', 'get_note_image'):
            if hasattr(cls, name):
                setattr(cls, name, media)

    async def resume_validation():
        # Upstream clients own login detection; refresh cookies after manual interaction.
        page = getattr(crawler, 'context_page', None)
        if page is None:
            # A pause can arrive during adapter setup, before its first CDP call.
            # Startup itself will attach the existing browser and validate login.
            return True
        if page.is_closed():
            raise RuntimeError('采集页面已关闭，请取消并新建任务')
        if not await refresh_adapter_login(crawler):
            return False
        # API adapters continue from their saved identifiers. Restore their entry page if
        # the user navigated elsewhere, leaving target identifiers in the adapter unchanged.
        from urllib.parse import urlparse
        if urlparse(page.url).hostname != urlparse(crawler.index_url).hostname:
            await page.goto(crawler.index_url, wait_until='domcontentloaded')
        return True
    runtime.resume_check = resume_validation
    # Load NumPy/OpenCV and the other native adapter dependencies before starting
    # the blocking stdin reader; Windows DLL initialization can otherwise deadlock.
    runtime.listen()
    runtime.emit('state', state='running')
    runtime.emit('phase', phase='collecting', message='平台适配器运行中；接口采集不一定伴随页面跳转')
    await crawler.start()
    runtime.emit('done')

if __name__ == '__main__':
    try:
        asyncio.run(run())
    except BaseException as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
        sys.exit(1)
