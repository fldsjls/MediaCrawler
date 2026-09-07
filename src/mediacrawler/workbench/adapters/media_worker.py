"""Connect content-scoped media parsing to the existing adapter/store lifecycle."""
import asyncio
import contextvars
import functools
import importlib
import inspect

from .media import MediaResult, bilibili_playback, candidate, http_url, parse_media, video_identity


STORE_METHODS = {
    'bili': 'update_bilibili_video', 'xhs': 'update_xhs_note', 'dy': 'update_douyin_aweme',
    'ks': 'update_kuaishou_video', 'wb': 'update_weibo_note',
    'tieba': 'update_tieba_note', 'zhihu': 'update_zhihu_content',
}


class MediaCoordinator:
    def __init__(self, platform, cfg, runtime, crawler):
        self.platform, self.cfg, self.runtime, self.crawler = platform, cfg, runtime, crawler
        self.download_video = bool(cfg.get('download_video', cfg.get('media', False))) and cfg['max_downloads'] > 0
        self.download_images = bool(cfg.get('download_images', cfg.get('media', False))) and cfg['max_downloads'] > 0
        self.raw_content = contextvars.ContextVar('workbench_raw_media_content', default=None)
        self.extracted = {}
        self.emitted = set()
        self.browser_lock = asyncio.Lock()

    def install(self, module_name):
        store = importlib.import_module(f'mediacrawler.storage.stores.{module_name}')
        original = getattr(store, STORE_METHODS[self.platform])
        @functools.wraps(original)
        async def content(*args, **kwargs):
            raw = args[0] if args else next(iter(kwargs.values()))
            if not isinstance(raw, dict):
                cached = self.extracted.pop(id(raw), None)
                raw = cached[1] if cached and cached[0] is raw else raw.model_dump()
            token = self.raw_content.set(raw)
            try:
                return await original(*args, **kwargs)
            finally:
                self.raw_content.reset(token)
        setattr(store, STORE_METHODS[self.platform], content)

        # These upstream extractors discard the source's video URLs while creating
        # privacy-safe models. Keep their single-content input only until store runs.
        if self.platform in ('tieba', 'zhihu'):
            helper = importlib.import_module(f'mediacrawler.platforms.{module_name}.help')
            cls = getattr(helper, 'TieBaExtractor' if self.platform == 'tieba' else 'ZhihuExtractor')
            names = ['extract_note_detail_from_api'] if self.platform == 'tieba' else ['_extract_answer_content', '_extract_article_content', '_extract_zvideo_content']
            for name in names:
                extract = getattr(cls, name)
                @functools.wraps(extract)
                def remember(instance, raw, _extract=extract):
                    result = _extract(instance, raw)
                    if result is not None:
                        # Retain the model identity until store consumes it; a bare
                        # id cache can alias a later object after garbage collection.
                        self.extracted[id(result)] = (result, raw)
                        while len(self.extracted) > max(100, self.cfg['max_items'] * 2):
                            self.extracted.pop(next(iter(self.extracted)))
                    return result
                setattr(cls, name, remember)

    def page_url(self, fields, raw):
        if self.platform == 'bili':
            return http_url(fields.get('video_url'))
        if self.platform == 'ks':
            return http_url(fields.get('video_url'))
        return http_url(fields.get('note_url') or fields.get('content_url') or fields.get('aweme_url') or raw.get('note_url'))

    async def resolve(self, record):
        fields = record['fields']
        raw = self.raw_content.get() or fields
        parsed = parse_media(self.platform, raw, fields)
        errors = []
        page_url = self.page_url(fields, raw)
        if self.platform == 'bili' and self.download_video:
            view = raw.get('View') or raw
            aid = view.get('aid') or fields.get('video_id')
            parts = view.get('pages') or ([{'cid': view.get('cid')}] if view.get('cid') else [])
            client = getattr(self.crawler, 'bili_client', None)
            for part in parts:
                cid = part.get('cid')
                if not cid or not client:
                    continue
                try:
                    await self.runtime.checkpoint()
                    if hasattr(client, 'get'):
                        response = await client.get('/x/player/wbi/playurl',
                            {'avid': aid, 'cid': cid, 'qn': 127, 'fourk': 1, 'fnval': 4048, 'platform': 'pc'},
                            enable_params_sign=True)
                    else:
                        response = await client.get_video_play_url(aid=int(aid), cid=int(cid))
                    video = bilibili_playback(response)
                    if video:
                        parsed.videos.append({**video, 'logical_id': str(cid), 'part_title': part.get('part', '')})
                    else:
                        errors.append(f'B站分P {cid} 未返回可下载视频流')
                except Exception as exc:
                    errors.append(f'B站分P {cid} 视频解析失败：{exc}')
        if self.download_video and not parsed.videos and self.platform in ('tieba', 'zhihu', 'wb') and (parsed.confirmed or not parsed.known_absent):
            try:
                fallback = await self.browser_fallback(record, page_url)
                parsed.videos.extend(fallback.videos)
                parsed.confirmed |= fallback.confirmed
                parsed.known_absent |= fallback.known_absent
                if fallback.videos:
                    parsed.unresolved_videos = fallback.unresolved_videos
            except Exception as exc:
                if parsed.confirmed:
                    errors.append(f'当前内容浏览器视频解析失败：{exc}')
        resources = []
        if self.download_video:
            for index, video in enumerate(parsed.videos):
                resources.append(self.resource(record, page_url, video, 'video', video.get('logical_id', str(index))))
            if parsed.confirmed and not parsed.videos and not errors:
                errors.append('内容明确包含视频，但未取得可确认归属的播放地址；可在浏览器捕获列表中检查')
            elif parsed.videos:
                # A resolved sibling is never evidence that every video was resolved.
                # These content-local identities cannot safely target a generic play button.
                errors.extend(f'视频 {identity} 未取得可确认归属的播放地址，请人工播放后在浏览器捕获列表中检查'
                              for identity in parsed.unresolved_videos)
        if self.download_images:
            for index, url in enumerate(parsed.images):
                resources.append(self.resource(record, page_url, candidate(url), 'image', str(index)))
        return parsed.status, resources, errors

    def resource(self, record, page_url, asset, kind, logical_id):
        client = next((value for value in vars(self.crawler).values() if hasattr(value, 'headers')), None)
        headers = {key: value for key, value in getattr(client, 'headers', {}).items()
                   if key.lower() in ('referer', 'user-agent') and isinstance(value, str) and '\n' not in value and '\r' not in value}
        if page_url:
            headers['Referer'] = page_url
        return {key: value for key, value in {
            **asset, 'kind': kind, 'parent_id': record['id'], 'title': record['title'] + (f' - {asset["part_title"]}' if asset.get('part_title') else ''),
            'page_url': page_url, 'source': self.platform, 'origin': 'adapter',
            'key': f'{self.platform}:{record.get("source_id", record["id"])}:{kind}:{logical_id}',
            'headers': headers,
        }.items() if key not in ('bandwidth', 'logical_id', 'part_title')}

    def publish(self, record, resources, errors):
        for resource in resources:
            if resource['key'] in self.emitted:
                continue
            self.emitted.add(resource['key'])
            self.runtime.emit('resource', resource=resource)
        for message in errors:
            self.runtime.emit('failure', message=message, parent_id=record['id'])

    async def browser_fallback(self, record, page_url):
        """Read only a video inside the current content's identified DOM container.

        Network requests alone are never proof of content ownership. A blob player
        whose manifest cannot be associated remains unresolved for manual capture.
        """
        result = MediaResult()
        if not page_url:
            return result
        page = getattr(self.crawler, 'context_page', None)
        if page is None or page.is_closed():
            return result
        async with self.browser_lock:
            async def operate():
                if page.url != page_url:
                    await page.goto(page_url, wait_until='domcontentloaded', timeout=15000)
                # Reject redirects to login/another content instead of attributing
                # whatever happens to be playing there to the original record.
                from urllib.parse import urlparse
                current, expected = urlparse(page.url), urlparse(page_url)
                if current.hostname != expected.hostname or current.path.rstrip('/') != expected.path.rstrip('/'):
                    return MediaResult()
                selector = await page.evaluate('''({platform,id,type}) => {
                    document.querySelectorAll('[data-mc-owned-media]').forEach(e=>e.removeAttribute('data-mc-owned-media'));
                    let root=null;
                    if(platform==='tieba') root=document.querySelector('#j_p_postlist .l_post .d_post_content');
                    if(platform==='zhihu') {
                        if(type==='article') root=document.querySelector('.Post-RichText');
                        else if(type==='zvideo'||type==='video') root=document.querySelector('.ZVideo-mainColumn,.ZVideo-video');
                        else root=[...document.querySelectorAll('.AnswerItem')].find(e=>{
                            try { return String(JSON.parse(e.dataset.zop||'{}').itemId)===String(id) || e.dataset.aid===String(id); }catch{return false;}
                        });
                    }
                    if(platform==='wb') root=[...document.querySelectorAll('[data-mid],.card[data-id]')].find(e=>e.dataset.mid===String(id)||e.dataset.id===String(id));
                    if(!root) return false;
                    root.setAttribute('data-mc-owned-media','current');
                    return true;
                }''', {'platform': self.platform, 'id': record['source_id'], 'type': record['fields'].get('content_type')})
                if not selector:
                    return MediaResult()
                root = page.locator('[data-mc-owned-media="current"]')
                videos = root.locator('video')
                if not await videos.count():
                    play = root.locator('.VideoCard-playButton,button[aria-label="播放"],.video-play')
                    if await play.count() and await play.first.is_visible():
                        await play.first.click(timeout=3000)
                        await page.wait_for_timeout(min(self.cfg.get('wait_ms', 1500), 3000))
                if not await videos.count():
                    return MediaResult(known_absent=not await root.locator('[data-video-id],.VideoCard,.video-player').count())
                first = videos.first
                if await first.is_visible():
                    await first.click(timeout=3000)
                    await page.wait_for_timeout(min(self.cfg.get('wait_ms', 1500), 3000))
                rows = await videos.evaluate_all('(els)=>els.map(v=>({url:v.src?.startsWith("blob:")?v.src:(v.currentSrc||v.src||v.querySelector("source")?.src),height:v.videoHeight,width:v.videoWidth,video_id:v.getAttribute("data-video-id")||v.id}))')
                output = MediaResult(confirmed=True)
                for index, row in enumerate(rows):
                    identity = video_identity(row, f'html:{index}')
                    if item := candidate(row):
                        output.videos.append({**item, 'logical_id': identity})
                    else:
                        output.unresolved_videos.append(identity)
                return output
            return await self.runtime.wrap(operate)()
