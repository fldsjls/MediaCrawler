"""Parse only media fields belonging to a single source content object.

Never recursively harvest arbitrary URLs: feeds may include avatars, adverts, related
posts and audio thumbnails. Responses stay in memory; only selected media metadata
is returned to the worker alongside the already anonymised content record.
"""
import html
import hashlib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlparse


def http_url(value):
    if not isinstance(value, str):
        return ''
    value = html.unescape(value).replace('\\/', '/').strip()
    if value.startswith('//'):
        value = 'https:' + value
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password else ''
    except ValueError:
        return ''


def number(value):
    try:
        return int(float(value or 0))
    except (ValueError, TypeError):
        match = re.search(r'(\d{3,4})[pP]', str(value or ''))
        return int(match[1]) if match else 0


def first_url(value):
    if isinstance(value, str):
        return http_url(value)
    if isinstance(value, list):
        return next((url for item in value if (url := first_url(item))), '')
    if isinstance(value, dict):
        for key in ('baseUrl', 'base_url', 'master_url', 'main_url', 'play_url', 'url', 'src', 'url_list', 'backupUrl', 'backup_url'):
            if key in value and (url := first_url(value[key])):
                return url
    return ''


def candidate(value, **metadata):
    data = value if isinstance(value, dict) else {}
    url = first_url(value)
    if not url:
        return None
    quality = metadata.get('quality') or data.get('quality') or data.get('quality_type') or data.get('definition') or ''
    resolution = re.search(r'(\d{3,4})[pP]', str(quality))
    return dict(url=url, height=number(metadata.get('height') or data.get('height') or (resolution[1] if resolution else 0)),
                width=number(metadata.get('width') or data.get('width')),
                bandwidth=number(data.get('bandwidth') or data.get('bitrate') or data.get('bit_rate')),
                quality=str(quality), format='hls' if '.m3u8' in urlparse(url).path.lower() else 'direct')


def best(values):
    candidates = [item for item in values if item]
    return max(candidates, key=lambda item: (item['height'], item['width'], item['bandwidth']), default=None)


@dataclass
class MediaResult:
    videos: list = field(default_factory=list)
    images: list = field(default_factory=list)
    confirmed: bool = False
    known_absent: bool = False
    unresolved_videos: list = field(default_factory=list)

    @property
    def status(self):
        return 'available' if self.videos else 'none' if self.known_absent and not self.confirmed else 'unresolved'


def bilibili_playback(data):
    """One selected logical video; retain all progressive segments or DASH tracks."""
    if not isinstance(data, dict):
        return None
    if isinstance(data.get('data'), dict):
        data = data['data']
    dash = data.get('dash') or {}
    videos = [candidate(item, quality=item.get('id')) for item in dash.get('video') or []]
    video = best(videos)
    if video:
        audio_rows = list(dash.get('audio') or [])
        audio_rows += (dash.get('dolby') or {}).get('audio') or []
        flac = (dash.get('flac') or {}).get('audio')
        if flac:
            audio_rows.append(flac)
        audio = max((item for row in audio_rows if (item := candidate(row))), key=lambda item: item['bandwidth'], default=None)
        streams = [{'url': video['url'], 'role': 'video'}]
        if audio:
            streams.append({'url': audio['url'], 'role': 'audio'})
        return {**video, 'format': 'dash', 'streams': streams}
    segments = sorted(data.get('durl') or [], key=lambda item: number(item.get('order')))
    urls = [first_url(segment) for segment in segments]
    if segments and all(urls):
        quality = str(data.get('quality') or '')
        return {**candidate(urls[0], quality=quality), 'format': 'segments' if len(urls) > 1 else 'direct',
                'streams': [{'url': url, 'role': 'segment'} for url in urls]}
    return None


def video_identity(values, fallback):
    """Content-local identity must survive URL signatures and quality changes."""
    value = next((values.get(key) for key in ('video_id', 'data-video-id', 'vid', 'id') if values.get(key)), None)
    return 'id:' + hashlib.sha256(str(value).encode()).hexdigest()[:20] if value is not None else fallback


class VideoGroups:
    def __init__(self):
        self.groups = {}

    def add(self, identity, variants):
        values = [item for item in variants if item]
        # Root metadata and its body representation can describe the same video.
        # Merge only an explicit identity or an identical source, never mere proximity.
        urls = {item['url'] for item in values}
        matching = [key for key, rows in self.groups.items()
                    if key == identity or urls.intersection(item['url'] for item in rows)]
        key = matching[0] if matching else identity
        combined = self.groups.setdefault(key, [])
        for other in matching[1:]:
            combined.extend(self.groups.pop(other))
        combined.extend(values)

    @property
    def videos(self):
        return [{**chosen, 'logical_id': key} for key, values in self.groups.items() if (chosen := best(values))]


def object_variants(video):
    values = [candidate(video.get('video_url') or video.get('video_src') or video,
                        height=video.get('height'), width=video.get('width'), quality=video.get('quality'))]
    playlist = video.get('playlist') or {}
    for row in playlist.values() if isinstance(playlist, dict) else playlist:
        if isinstance(row, dict):
            values.append(candidate(row.get('video_url') or row.get('video_src') or row,
                                    height=row.get('height'), width=row.get('width'), quality=row.get('quality')))
    return values


class ContentHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.groups, self.images = VideoGroups(), []
        self.has_video = False
        self.current = None
        self.video_count = 0

    @property
    def videos(self):
        return self.groups.videos

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'video':
            self.current = video_identity(values, f'html:{self.video_count}')
            self.video_count += 1
            self.has_video = True
        if tag == 'video' or tag == 'source' and self.current is not None:
            found = candidate(values.get('src') or values.get('data-src') or values.get('data-video-url'),
                              height=values.get('height'), width=values.get('width'),
                              quality=values.get('data-quality') or values.get('label'))
            self.groups.add(self.current, [found])
        if tag == 'img' and (url := http_url(values.get('data-original') or values.get('src'))):
            self.images.append(url)
    def handle_endtag(self, tag):
        if tag == 'video':
            self.current = None


def parse_media(platform, raw, normalized=None):
    raw = raw if isinstance(raw, dict) else {}
    normalized = normalized or {}
    result = MediaResult()
    variants = []
    if platform == 'bili':
        view = raw.get('View') or raw
        result.confirmed = bool(view.get('aid') or normalized.get('video_id'))
        if url := http_url(view.get('pic') or normalized.get('video_cover_url')):
            result.images.append(url)
    elif platform == 'xhs':
        video = raw.get('video') or {}
        result.confirmed = raw.get('type') == 'video'
        result.known_absent = raw.get('type') in ('normal', 'image')
        streams = (video.get('media') or {}).get('stream') or {}
        for codec in ('h264', 'h265', 'av1'):
            for row in streams.get(codec) or []:
                variants.append(candidate(row))
        consumer = video.get('consumer') or {}
        key = consumer.get('origin_video_key') or consumer.get('originVideoKey')
        if key:
            variants.append(candidate(http_url(key) or f'https://sns-video-bd.xhscdn.com/{key}', height=video.get('height'), width=video.get('width')))
        for image in raw.get('image_list') or []:
            if url := first_url(image.get('url_default') or image.get('url_pre') or image.get('url')):
                result.images.append(url)
    elif platform == 'dy':
        images = raw.get('images') or []
        result.known_absent = bool(images) or str(raw.get('aweme_type')) in ('68', '2')
        video = raw.get('video') or {}
        result.confirmed = bool(video) and not result.known_absent
        if result.confirmed:
            for row in video.get('bit_rate') or []:
                address = row.get('play_addr') or {}
                variants.append(candidate({**address, 'bit_rate': row.get('bit_rate')}, quality=row.get('gear_name')))
            variants.append(candidate(video.get('play_addr') or video.get('download_addr'), height=video.get('height'), width=video.get('width')))
        for image in images:
            if url := first_url(image.get('url_list')):
                result.images.append(url)
    elif platform == 'ks':
        photo = raw.get('photo') or raw
        variants.append(candidate(photo.get('photoUrl') or photo.get('playUrl') or normalized.get('video_play_url'),
                                  height=photo.get('height'), width=photo.get('width')))
        video_resource = photo.get('videoResource') or {}
        manifests = video_resource.get('h264') or []
        for manifest in manifests if isinstance(manifests, list) else [manifests]:
            adaptations = manifest.get('adaptationSet') or []
            for adaptation in adaptations if isinstance(adaptations, list) else [adaptations]:
                for row in adaptation.get('representation') or []:
                    variants.append(candidate(row))
        result.confirmed = any(variants) or str(raw.get('type')).lower() == 'video'
        result.known_absent = str(raw.get('type')).lower() in ('image', 'photo', 'text') and not result.confirmed
        if url := http_url(photo.get('coverUrl') or normalized.get('video_cover_url')):
            result.images.append(url)
    elif platform == 'wb':
        blog = raw.get('mblog') or raw
        page = blog.get('page_info') or {}
        info = page.get('media_info') or blog.get('media_info') or {}
        result.confirmed = page.get('type') == 'video' or page.get('object_type') == 'video' or bool(info)
        result.known_absent = not result.confirmed and 'mblog' in raw
        for source in (info, page.get('urls') or {}):
            for key in ('stream_url', 'stream_url_hd', 'mp4_sd_url', 'mp4_hd_url', 'mp4_720p_mp4', 'mp4_1080p_mp4', 'mp4_1440p_mp4', 'mp4_2160p_mp4'):
                height = number(re.search(r'(\d{3,4})p', key)[1]) if re.search(r'(\d{3,4})p', key) else 720 if 'hd' in key else 0
                variants.append(candidate(source.get(key), height=height, quality=key))
            for row in source.get('playback_list') or []:
                variants.append(candidate(row.get('play_info') or row))
        for row in blog.get('pics') or []:
            if url := first_url(row.get('large') or row.get('url')):
                result.images.append(url)
        for row in (blog.get('pic_infos') or {}).values():
            if url := first_url(row.get('largest') or row.get('large')):
                result.images.append(url)
    elif platform in ('tieba', 'zhihu'):
        groups = VideoGroups()
        if platform == 'tieba':
            thread = raw.get('thread') or raw
            first_floor = raw.get('first_floor') or {}
            videos = [thread.get('video_info'), thread.get('video'), first_floor.get('video_info')]
            for video in videos:
                if isinstance(video, dict) and video:
                    groups.add(video_identity(video, 'main'), object_variants(video))
            block_index = 0
            for block in first_floor.get('content') or []:
                if isinstance(block, dict) and str(block.get('type')) in ('5', 'video'):
                    videos.append(block)
                    groups.add(video_identity(block, f'block:{block_index}'), object_variants(block))
                    block_index += 1
                elif isinstance(block, dict) and str(block.get('type')) == '3':
                    if url := first_url(block.get('origin_src') or block.get('src')):
                        result.images.append(url)
            body = first_floor.get('content') if isinstance(first_floor.get('content'), str) else normalized.get('desc', '')
            result.confirmed = bool(thread.get('is_video') or thread.get('video_id'))
            # A complete root-post API payload explicitly lacking video blocks is
            # a text/image post; missing/incomplete payloads remain unresolved.
            result.known_absent = bool(first_floor) and not any(videos) and not result.confirmed
        else:
            video = raw.get('video') or {}
            video = {**video, 'playlist': video.get('playlist') or raw.get('playlist') or {}}
            videos = [video] if any(video.values()) else []
            if videos:
                groups.add(video_identity(video, 'main'), object_variants(video))
            body = raw.get('content') or normalized.get('content_text') or ''
            result.confirmed = (raw.get('type') in ('zvideo', 'video') or normalized.get('content_type') in ('zvideo', 'video')
                                or 'data-video' in str(body).lower() or 'videocard' in str(body).lower())
            result.known_absent = raw.get('type') in ('answer', 'article') and not any(video.values()) and '<video' not in str(body).lower() and 'data-video' not in str(body).lower()
        for video in videos:
            if not isinstance(video, dict) or not video:
                continue
            result.confirmed = True
        parser = ContentHTML()
        parser.feed(body if isinstance(body, str) else '')
        for identity, rows in parser.groups.groups.items():
            groups.add(identity, rows)
        result.videos.extend(groups.videos)
        result.unresolved_videos = [identity for identity, rows in groups.groups.items() if not best(rows)]
        result.images.extend(parser.images)
        result.confirmed |= parser.has_video
    chosen = best(variants)
    if chosen:
        result.videos.append(chosen)
        result.confirmed = True
    result.images = list(dict.fromkeys(result.images))
    return result
