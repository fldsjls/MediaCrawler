"""Session-local passive network discovery. Never starts a download."""
import asyncio
import copy
import re
from pathlib import PurePosixPath
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET

from .identity import canonical_url, resource_identity
from ..preview.internal import is_internal_preview_url


def classify(url, content_type=''):
    suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
    mime = content_type.split(';', 1)[0].strip().lower()
    if suffix == '.m3u8' or mime in ('application/vnd.apple.mpegurl', 'application/x-mpegurl', 'audio/mpegurl'):
        return 'video', 'hls'
    if suffix == '.mpd' or mime == 'application/dash+xml':
        return 'video', 'dash'
    if mime.startswith('video/') or suffix in ('.mp4', '.webm', '.flv', '.mkv', '.mov', '.m4v'):
        return 'video', suffix.lstrip('.') or mime.split('/')[-1]
    if mime.startswith('audio/') or suffix in ('.mp3', '.m4a', '.aac', '.ogg', '.wav'):
        return 'audio', suffix.lstrip('.') or mime.split('/')[-1]
    if mime.startswith('image/') or suffix in ('.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif'):
        return 'image', suffix.lstrip('.') or mime.split('/')[-1]
    return None


def manifest_status(text, format):
    if format == 'hls':
        if '#EXTM3U' not in text:
            return '无效的 HLS 清单'
        for key in re.findall(r'#EXT-X-(?:SESSION-)?KEY:([^\r\n]+)', text):
            method = re.search(r'METHOD=([^,]+)', key)
            keyformat = re.search(r'KEYFORMAT="([^"]+)"', key)
            if not method or method.group(1) not in ('NONE', 'AES-128') or (keyformat and keyformat.group(1) != 'identity'):
                return 'DRM 或不支持的加密格式，无法下载'
        if '#EXT-X-ENDLIST' not in text and '#EXT-X-STREAM-INF:' not in text:
            return '不支持无限直播 HLS 清单'
    elif format == 'dash':
        try:
            root = ET.fromstring(text)
        except ET.ParseError:
            return '无效的 DASH 清单'
        if any(node.tag.rsplit('}', 1)[-1] == 'ContentProtection' for node in root.iter()):
            return 'DRM 媒体不支持下载'
        if root.get('type', 'static') == 'dynamic':
            return '不支持无限直播 DASH 清单'
        if not root.get('mediaPresentationDuration') and not any(
            node.get('duration') or node.tag.rsplit('}', 1)[-1] == 'SegmentList' for node in root.iter()):
            return 'DASH 清单未提供有限时长或分片列表'
    return ''


class MediaCapture:
    def __init__(self, session_id, source=''):
        self.session_id, self.source = session_id, source
        self.seq = 0
        self._items = {}
        self._events = []
        self._pending = set()
        self._context = None
        self._closed = False
        self._gate = asyncio.Semaphore(8)

    @staticmethod
    def public(item):
        fields = ('id', 'seq', 'resource_id', 'title', 'kind', 'format', 'quality', 'width', 'height',
                  'size', 'page_url', 'parent_id', 'source', 'origin', 'state', 'error', 'drm', 'is_live')
        result = {key: item[key] for key in fields if key in item}
        if result.get('error'):
            result['error'] = re.sub(r'https?://[^\s\]\[<>"\']+', '[media-url]', str(result['error']))
            for value in item.get('headers', {}).values():
                if isinstance(value, str) and len(value) > 3:
                    result['error'] = result['error'].replace(value, '[redacted]')
        if result.get('page_url'):
            parts = urlsplit(result['page_url'])
            result['page_url'] = urlunsplit((parts.scheme, parts.netloc.split('@')[-1], parts.path, '', ''))
        return copy.deepcopy(result)

    def add(self, resource):
        if self._closed:
            raise RuntimeError('浏览器资源会话已关闭')
        value = copy.deepcopy(resource)
        value.setdefault('source', self.source)
        value.setdefault('origin', 'adapter')
        value.setdefault('state', 'discovered')
        value.setdefault('parent_id', None)
        value.setdefault('kind', 'video')
        value.setdefault('format', (classify(value.get('url', '')) or ('video', 'direct'))[1])
        value['format'] = {'m3u8': 'hls', 'mpd': 'dash'}.get(value['format'], value['format'])
        value.setdefault('title', unquote(PurePosixPath(urlsplit(value.get('url', '')).path).name) or '媒体资源')
        value.setdefault('error', '')
        if value.get('origin') == 'browser' and not value.get('quality') and value.get('url'):
            variants = [item for item in self._items.values() if item.get('origin') == 'browser'
                        and canonical_url(item.get('url', '')) == canonical_url(value['url'])]
            if len(variants) == 1:
                for field in ('quality', 'height', 'width', 'key'):
                    if variants[0].get(field):
                        value[field] = variants[0][field]
        if value.get('drm') or value.get('is_live'):
            value['state'] = 'unavailable'
            value['error'] = value['error'] or ('DRM 媒体不支持下载' if value.get('drm') else '不支持无限直播')
        identity = value.get('id') or resource_identity(value)
        previous = self._items.get(identity, {})
        value = {**previous, **value, 'id': identity, 'resource_id': identity}
        # Refresh signed URLs and credentials privately even if visible metadata is unchanged.
        public = self.public(value)
        public.pop('seq', None)
        old_public = self.public(previous)
        old_public.pop('seq', None)
        if public != old_public:
            self.seq += 1
            value['seq'] = self.seq
            self._events.append({'seq': self.seq, 'type': 'resource', 'resource': self.public(value)})
        self._items[identity] = value
        return self.public(value)

    def list(self, after=0):
        return [self.public(item) for item in self._items.values() if item.get('seq', 0) > after]

    def events(self, after=0):
        return copy.deepcopy([event for event in self._events if event['seq'] > after])

    def get(self, identity):
        return copy.deepcopy(self._items.get(identity))

    def attach(self, context):
        self._context = context
        context.on('request', self._request)
        context.on('response', self._response)

    def _schedule(self, coroutine):
        if self._closed or len(self._pending) >= 128:
            coroutine.close()
            return
        task = asyncio.create_task(coroutine)
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def _request(self, request):
        if classify(request.url):
            self._schedule(self._capture(request))

    def _response(self, response):
        if classify(response.url, response.headers.get('content-type', '')):
            self._schedule(self._capture(response.request, response))

    async def _capture(self, request, response=None):
        try:
            async with self._gate:
                url = request.url
                if is_internal_preview_url(url):
                    return
                try:
                    if is_internal_preview_url(request.frame.page.url):
                        return
                except Exception:
                    pass
                if urlsplit(url).scheme not in ('http', 'https'):
                    return
                kind, format = classify(url, response.headers.get('content-type', '') if response else '')
                try:
                    page_url = request.frame.page.url
                except Exception:
                    page_url = ''
                headers = await asyncio.wait_for(request.all_headers(), 3)
                item = dict(url=url, kind=kind, format=format, page_url=page_url, headers=headers,
                            origin='browser', parent_id=None, source=self.source, state='discovered')
                if response:
                    size = response.headers.get('content-length', '')
                    if size.isdigit():
                        item['size'] = int(size)
                    if response.status >= 400:
                        item.update(state='unavailable', error=f'资源请求返回 HTTP {response.status}')
                    elif format in ('hls', 'dash') and (not size.isdigit() or int(size) < 2_000_000):
                        body = await asyncio.wait_for(response.body(), 5)
                        if len(body) < 2_000_000:
                            text = body.decode('utf-8-sig', errors='replace')
                            error = manifest_status(text, format)
                            if error:
                                item.update(state='unavailable', error=error,
                                            drm='DRM' in error, is_live='直播' in error)
                            elif format == 'hls':
                                lines = text.splitlines()
                                for index, line in enumerate(lines):
                                    resolution = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                                    if line.startswith('#EXT-X-STREAM-INF:') and resolution and index + 1 < len(lines):
                                        width, height = map(int, resolution.groups())
                                        self.add({**item, 'url': urljoin(url, lines[index + 1].strip()),
                                                  'width': width, 'height': height, 'quality': f'{height}p'})
                            elif format == 'dash':
                                for node in ET.fromstring(text).iter():
                                    if node.tag.rsplit('}', 1)[-1] == 'Representation' and node.get('height', '').isdigit():
                                        height = int(node.get('height'))
                                        self.add({**item, 'key': canonical_url(url), 'height': height,
                                                  'width': int(node.get('width', '0')), 'quality': f'{height}p'})
                if not self._closed:
                    self.add(item)
        except (Exception, asyncio.CancelledError):
            # Discovery is best effort and must never fail a browser operation.
            return

    async def close(self):
        self._closed = True
        if self._context:
            self._context.remove_listener('request', self._request)
            self._context.remove_listener('response', self._response)
        for task in self._pending:
            task.cancel()
        await asyncio.gather(*self._pending, return_exceptions=True)
        self._pending.clear()
        self._items.clear()
        self._events.clear()
