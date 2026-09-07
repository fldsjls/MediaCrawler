"""Scoped HTTP transfer and finite media assembly with one final logical file.

FFmpeg only sees a short-lived loopback proxy. Signed upstream URLs and browser
credentials stay in memory, and each upstream request obtains URL-scoped cookies.
"""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from urllib.parse import urljoin, urlsplit
import xml.etree.ElementTree as ET

import httpx

from .capture import classify, manifest_status
from .identity import resource_identity


def web_url(value):
    parts = urlsplit(value)
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        raise ValueError('媒体仅支持无内嵌凭据的 HTTP / HTTPS 地址')
    return value


def origin(url):
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or (443 if parts.scheme == 'https' else 80)


def clean_error(error):
    # Never persist raw FFmpeg stderr, HTTP request URLs or credential values.
    text = str(error)
    text = re.sub(r'https?://[^\s\]\[<>"\']+', '[media-url]', text)
    text = re.sub(r'(?i)(authorization|cookie|token|signature|auth_key)\s*[:=][^\r\n]+', r'\1=[redacted]', text)
    return text[-700:]


def check_cancel(run):
    if run.cancelled:
        raise asyncio.CancelledError()


async def scoped_headers(run, resource, url, incoming=None):
    incoming = incoming or {}
    result = {}
    source_url = resource.get('_header_url') or resource.get('url') or url
    for key, value in resource.get('headers', {}).items():
        name = key.lower()
        if name in ('host', 'cookie', 'content-length', 'connection', 'accept-encoding', 'range'):
            continue
        if '\n' in str(value) or '\r' in str(value):
            raise ValueError('媒体请求头无效')
        try:
            str(value).encode('ascii')
        except UnicodeEncodeError:
            raise ValueError('媒体请求头必须使用有效 HTTP 编码') from None
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", key):
            raise ValueError('媒体请求头名称无效')
        if origin(source_url) == origin(url) or name in ('referer', 'user-agent'):
            result[name] = str(value)
    # Preserve FFmpeg's real user agent unless the resource explicitly provides one.
    for name in ('user-agent', 'range'):
        if name in incoming and name not in result:
            result[name] = incoming[name]
    context = getattr(getattr(run, 'session', None), 'context', None)
    if context:
        cookies = await context.cookies([url])
        if cookies:
            result['cookie'] = '; '.join(f'{cookie["name"]}={cookie["value"]}' for cookie in cookies)
            if any(ord(character) < 32 or ord(character) > 126 for character in result['cookie']):
                raise ValueError('浏览器 Cookie 编码无效')
    result['accept-encoding'] = 'identity'
    return result


@asynccontextmanager
async def scoped_request(client, run, resource, url, incoming=None):
    """Recompute cookies and authorization scope on every redirect."""
    for _ in range(6):
        check_cancel(run)
        web_url(url)
        headers = await scoped_headers(run, resource, url, incoming)
        request = client.build_request('GET', url, headers=headers)
        response = await client.send(request, stream=True, follow_redirects=False)
        if response.status_code in (301, 302, 303, 307, 308) and response.headers.get('location'):
            next_url = urljoin(url, response.headers['location'])
            await response.aclose()
            url = next_url
            continue
        try:
            if response.status_code >= 400:
                raise RuntimeError(f'媒体请求返回 HTTP {response.status_code}')
            yield response, url
        finally:
            await response.aclose()
        return
    raise RuntimeError('媒体请求重定向次数过多')


class MediaProxy:
    """Private per-download relay with bounded manifests and HTTP-only child URLs."""
    def __init__(self, run, resource):
        self.run, self.resource = run, resource
        self.token = secrets.token_urlsafe(24)
        self.routes = {}
        self.handlers = set()
        self.errors = []
        self.requests = 0
        self.server = None
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(60), trust_env=False)
        self.server = await asyncio.start_server(self.handle, '127.0.0.1', 0, limit=65536)
        self.base = f'http://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/{self.token}/'
        return self

    async def __aexit__(self, *_args):
        self.server.close()
        await self.server.wait_closed()
        for task in tuple(self.handlers):
            task.cancel()
        await asyncio.gather(*tuple(self.handlers), return_exceptions=True)
        await self.client.aclose()

    def register(self, url, resource=None, directory=False):
        web_url(url)
        resource = resource or self.resource
        route = secrets.token_hex(8)
        self.routes[route] = (url, resource, directory)
        suffix = Path(urlsplit(url).path).suffix
        if not re.fullmatch(r'\.[A-Za-z0-9]{1,12}', suffix):
            suffix = {'hls': '.m3u8', 'dash': '.mpd'}.get(resource.get('format'), '')
        return self.base + route + ('/' if directory else '/media' + suffix)

    def template_url(self, url, resource):
        # Preserve DASH placeholders in the URL FFmpeg expands, not inside hidden maps.
        parts = urlsplit(web_url(url))
        base = f'{parts.scheme}://{parts.netloc}/'
        return self.register(base, resource, directory=True) + parts.path.lstrip('/') + ('?' + parts.query if parts.query else '')

    def rewrite_manifest(self, text, format, url, resource):
        error = manifest_status(text, format)
        if error:
            raise ValueError(error)
        if format == 'hls':
            def replace_uri(match):
                return 'URI="' + self.register(urljoin(url, match.group(1)), resource) + '"'
            original_lines = text.splitlines()
            if resource.get('height') and '#EXT-X-STREAM-INF:' in text:
                selected = []
                matched = False
                skip_uri = False
                for line in original_lines:
                    if line.startswith('#EXT-X-STREAM-INF:'):
                        resolution = re.search(r'RESOLUTION=(\d+)x(\d+)', line)
                        skip_uri = not resolution or int(resolution.group(2)) != int(resource['height'])
                        if not skip_uri:
                            matched = True
                            selected.append(line)
                    elif skip_uri and line.strip() and not line.startswith('#'):
                        skip_uri = False
                    else:
                        selected.append(line)
                if not matched:
                    raise ValueError('所选清晰度已不可用，请重新捕获资源')
                original_lines = selected
            lines = []
            for line in original_lines:
                if line.startswith('#'):
                    line = re.sub(r'URI="([^"]+)"', replace_uri, line)
                elif line.strip():
                    line = self.register(urljoin(url, line.strip()), resource)
                lines.append(line)
            return ('\n'.join(lines) + '\n').encode()
        root = ET.fromstring(text)
        namespace = root.tag.split('}')[0] + '}' if '}' in root.tag else ''
        if namespace:
            ET.register_namespace('', namespace[1:-1])
        if resource.get('height'):
            matched = False
            for adaptation in root.iter():
                children = [node for node in adaptation if node.tag.rsplit('}', 1)[-1] == 'Representation' and node.get('height')]
                matches = [node for node in children if node.get('height') == str(resource['height'])]
                if matches:
                    matched = True
                    for node in children:
                        if node not in matches:
                            adaptation.remove(node)
            if not matched:
                raise ValueError('所选清晰度已不可用，请重新捕获资源')
        def visit(node, base):
            bases = [child for child in node if child.tag.rsplit('}', 1)[-1] == 'BaseURL']
            if bases:
                original = urljoin(base, (bases[0].text or '').strip())
                for child in bases:
                    resolved = urljoin(base, (child.text or '').strip())
                    child.text = self.template_url(resolved, resource)
                base = original
            for key in ('media', 'initialization', 'sourceURL', 'index'):
                if node.get(key):
                    node.set(key, self.template_url(urljoin(base, node.get(key)), resource))
            for child in list(node):
                if child.tag.rsplit('}', 1)[-1] != 'BaseURL':
                    visit(child, base)
        visit(root, url)
        if not any(child.tag.rsplit('}', 1)[-1] == 'BaseURL' for child in root):
            base = ET.Element(namespace + 'BaseURL')
            base.text = self.template_url(urljoin(url, './'), resource)
            root.insert(0, base)
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)

    async def handle(self, reader, writer):
        task = asyncio.current_task()
        self.handlers.add(task)
        sent = False
        try:
            self.requests += 1
            if self.requests > 10000:
                raise ValueError('媒体分片超过本次有限下载范围')
            head = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 15)
            lines = head.decode('iso-8859-1').split('\r\n')
            method, path, _version = lines[0].split(' ', 2)
            if method not in ('GET', 'HEAD') or not path.startswith('/' + self.token + '/'):
                raise ValueError('无效的本机媒体请求')
            route_path = path[len(self.token) + 2:]
            route_id, _, tail = route_path.partition('/')
            route_id = route_id.split('?', 1)[0]
            url, resource, directory = self.routes[route_id]
            if directory:
                url = urljoin(url, tail)
            incoming = {line.split(':', 1)[0].lower(): line.split(':', 1)[1].strip() for line in lines[1:] if ':' in line}
            async with scoped_request(self.client, self.run, resource, url, incoming) as (response, actual_url):
                format = (classify(actual_url, response.headers.get('content-type', '')) or ('', ''))[1]
                if not format and url == resource.get('url'):
                    format = resource.get('format', '')
                if format in ('hls', 'dash'):
                    body = bytearray()
                    async for block in response.aiter_bytes():
                        check_cancel(self.run)
                        body.extend(block)
                        if len(body) > 2_000_000:
                            raise ValueError('媒体清单超过 2 MB 限制')
                    content = self.rewrite_manifest(body.decode('utf-8-sig'), format, actual_url, resource)
                    mime = 'application/vnd.apple.mpegurl' if format == 'hls' else 'application/dash+xml'
                    writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: {mime}\r\nContent-Length: {len(content)}\r\nConnection: close\r\n\r\n'.encode())
                    sent = True
                    if method != 'HEAD':
                        writer.write(content)
                    await writer.drain()
                else:
                    headers = [f'HTTP/1.1 {response.status_code} OK', 'Connection: close']
                    for name in ('content-type', 'content-length', 'content-range', 'accept-ranges'):
                        if name in response.headers:
                            headers.append(f'{name}: {response.headers[name]}')
                    writer.write(('\r\n'.join(headers) + '\r\n\r\n').encode())
                    sent = True
                    if method != 'HEAD':
                        async for block in response.aiter_bytes():
                            check_cancel(self.run)
                            writer.write(block)
                            await writer.drain()
        except (ConnectionError, asyncio.CancelledError):
            pass
        except Exception as exc:
            self.errors.append(clean_error(exc))
            if not sent:
                writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
                try:
                    await writer.drain()
                except ConnectionError:
                    pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            self.handlers.discard(task)


async def ffmpeg(run, executable, arguments):
    check_cancel(run)
    process = subprocess.Popen([str(executable), '-nostdin', '-v', 'error', '-y', *arguments],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    run.download_process = process
    communicate = asyncio.create_task(asyncio.to_thread(process.communicate))
    try:
        while not communicate.done():
            check_cancel(run)
            await asyncio.wait([communicate], timeout=.15)
        _, stderr = await communicate
        check_cancel(run)
        if process.returncode:
            raise RuntimeError('媒体合并失败：' + clean_error(stderr.decode('utf-8', errors='replace')))
    finally:
        if process.poll() is None:
            if sys.platform == 'win32':
                await asyncio.to_thread(subprocess.run, ['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True)
            else:
                process.kill()
        await communicate
        run.download_process = None


async def direct(run, resource, path):
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        async with scoped_request(client, run, resource, web_url(resource['url'])) as (response, _url):
            with path.open('wb') as output:
                async for block in response.aiter_bytes():
                    check_cancel(run)
                    output.write(block)


async def download(run, item, directory, toolspath):
    """Download direct media, finite HLS/DASH, video/audio streams or ordered segments."""
    check_cancel(run)
    item = dict(item)
    if item.get('streams'):
        normalized = [{**stream, 'kind': stream.get('kind') or stream.get('role')} for stream in item['streams']]
        if any(stream.get('kind') == 'segment' for stream in normalized):
            if not all(stream.get('kind') == 'segment' for stream in normalized):
                raise ValueError('有序分片不能与分离音视频流混用')
            item['segments'], item['streams'] = normalized, []
        else:
            item['streams'] = normalized
    item.setdefault('_header_url', item.get('url') or next(
        (stream.get('url') for stream in item.get('streams', item.get('segments', [])) if isinstance(stream, dict)), ''))
    if item.get('drm') or item.get('is_live') or item.get('state') == 'unavailable':
        raise ValueError(clean_error(item.get('error') or 'DRM 或无限直播媒体不支持下载'))
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    tools = Path(toolspath)
    executable = tools / 'ffmpeg.exe' if tools.name == 'ffmpeg' else tools / 'ffmpeg' / 'ffmpeg.exe'
    identity = str(item.get('id') or resource_identity(item))
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', identity):
        raise ValueError('媒体编号无效')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(item.get('title') or 'media'))[:70].strip('. ') or 'media'
    format = item.get('format') or (classify(item.get('url', '')) or ('', 'direct'))[1]
    format = {'m3u8': 'hls', 'mpd': 'dash'}.get(format, format)
    composite = bool(item.get('streams') or item.get('segments'))
    mux = format in ('hls', 'dash') or composite
    suffix = Path(urlsplit(item.get('url', '')).path).suffix.lower()
    extension = '.mp4' if mux else suffix if suffix in ('.mp4', '.webm', '.flv', '.mkv', '.mov', '.mp3', '.m4a', '.aac', '.jpg', '.jpeg', '.png', '.webp', '.gif', '.avif') else '.' + format if format in ('mp4', 'webm', 'mp3', 'jpeg', 'png', 'webp') else '.bin'
    destination = directory / f'{identity}-{name}{extension}'
    partial = destination.with_suffix('.part' + extension)
    try:
        if not mux:
            await direct(run, item, partial)
        else:
            if not executable.is_file():
                raise ValueError('未安装 FFmpeg，请运行统一安装脚本')
            segments = item.get('segments') or []
            if len(segments) > 5000:
                raise ValueError('单个媒体分片数超过 5000')
            async with MediaProxy(run, item) as proxy:
                if segments:
                    # Download and remux segments in supplied order; concat paths are local
                    # opaque filenames, never signed URLs or headers.
                    parts = []
                    concat = directory / f'{identity}.concat.txt'
                    try:
                        for index, segment in enumerate(segments):
                            check_cancel(run)
                            resource = {**item, **(segment if isinstance(segment, dict) else {'url': segment})}
                            if isinstance(segment, dict) and 'headers' in segment:
                                resource['_header_url'] = resource['url']
                            part = directory / f'{identity}.segment-{index:05d}.ts'
                            # Track the in-progress part too: ffmpeg can write before failing.
                            parts.append(part)
                            await ffmpeg(run, executable, ['-protocol_whitelist', 'http,tcp,crypto', '-rw_timeout', '60000000',
                                '-i', proxy.register(resource['url'], resource), '-map', '0:v:0?', '-map', '0:a:0?', '-c', 'copy', '-f', 'mpegts', str(part)])
                        concat.write_text(''.join(f"file '{part.name}'\n" for part in parts), encoding='utf-8')
                        await ffmpeg(run, executable, ['-f', 'concat', '-safe', '1', '-i', str(concat), '-c', 'copy', str(partial)])
                    except Exception:
                        if proxy.errors:
                            raise RuntimeError(proxy.errors[-1]) from None
                        raise
                    finally:
                        concat.unlink(missing_ok=True)
                        for part in parts:
                            part.unlink(missing_ok=True)
                else:
                    streams = item.get('streams') or [item]
                    if len(streams) > 2:
                        raise ValueError('首版仅支持一个视频流和一个音频流')
                    if len(streams) == 2 and {stream.get('kind') for stream in streams} != {'video', 'audio'}:
                        raise ValueError('分离流须由一个视频流和一个音频流组成')
                    args = []
                    for stream in streams:
                        if not isinstance(stream, dict):
                            raise ValueError('媒体流配置无效')
                        resource = {**item, **stream}
                        if 'headers' in stream:
                            resource['_header_url'] = resource['url']
                        args += ['-protocol_whitelist', 'http,tcp,crypto', '-rw_timeout', '60000000', '-i', proxy.register(resource['url'], resource)]
                    if len(streams) > 1:
                        for index, stream in enumerate(streams):
                            kind = stream.get('kind')
                            if kind not in ('video', 'audio'):
                                raise ValueError('分离流必须明确指定 video 或 audio')
                            args += ['-map', f'{index}:{"v" if kind == "video" else "a"}:0']
                    else:
                        args += ['-map', '0:v:0?', '-map', '0:a:0?']
                    try:
                        await ffmpeg(run, executable, [*args, '-c', 'copy', '-movflags', '+faststart', str(partial)])
                    except Exception:
                        if proxy.errors:
                            raise RuntimeError(proxy.errors[-1]) from None
                        raise
        check_cancel(run)
        if not partial.is_file() or not partial.stat().st_size:
            raise RuntimeError('下载器未生成有效文件')
        partial.replace(destination)
        return destination
    except asyncio.CancelledError:
        partial.unlink(missing_ok=True)
        raise
    except Exception as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(clean_error(exc)) from None
