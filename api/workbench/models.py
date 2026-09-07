from typing import Literal
from urllib.parse import urlparse
from pydantic import BaseModel, Field, model_validator
from .platforms.catalog import PLATFORMS, LEGACY_MEDIA_MODES
TERMINAL = {'cancelled', 'succeeded', 'partial', 'failed', 'interrupted'}

def web_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('仅支持无内嵌凭据的 HTTP / HTTPS 地址')
    return value

class TaskConfig(BaseModel):
    platform: str
    mode: Literal['detail', 'search', 'creator'] = 'detail'
    target: str = Field(min_length=1, max_length=10000)
    max_items: int = Field(default=5, ge=1, le=10000)
    max_downloads: int = Field(default=5, ge=0, le=10000)
    max_comments: int = Field(default=20, ge=0, le=10000)
    comments: bool = True
    subcomments: bool = False
    media: bool = False
    download_video: bool | None = None
    download_images: bool | None = None
    operation: Literal['collect', 'download'] = 'collect'
    resource_ids: list[str] = Field(default_factory=list, max_length=10000)
    output: Literal['jsonl', 'json', 'csv', 'excel'] = 'jsonl'
    login: Literal['qrcode', 'cookie'] = 'qrcode'
    cookies: str = Field(default='', max_length=20000, repr=False)
    start: int = Field(default=1, ge=1)
    wait_ms: int = Field(default=5000, ge=100, le=120000)
    selector: str = Field(default='', max_length=1000)
    session_id: str | None = None

    @model_validator(mode='after')
    def capabilities(self):
        self.target = self.target.strip()
        if not self.target:
            raise ValueError('请输入采集目标')
        p = next((p for p in PLATFORMS if p['id'] == self.platform), None)
        custom = self.platform.startswith('custom_') and len(self.platform) == 23 and all(c in '0123456789abcdef' for c in self.platform[7:])
        if not p and not custom or p and self.mode not in p['inputs']:
            raise ValueError('平台不支持此输入方式')
        legacy = self.download_video is None and self.download_images is None
        if legacy and self.media and p and self.mode not in LEGACY_MEDIA_MODES.get(self.platform, []):
            raise ValueError('此平台未提供媒体下载')
        if self.download_video is None:
            self.download_video = self.media
        if self.download_images is None:
            self.download_images = self.media and bool(p and p['images'])
        if p and self.download_images and not p['images']:
            raise ValueError('此平台未提供图片下载')
        self.media = bool(self.download_video or self.download_images)
        if p and not p['comments']:
            self.comments = self.subcomments = False
        if not self.comments or not self.max_comments:
            self.comments = self.subcomments = False
        if self.platform in ('meishiwang', 'generic') or custom:
            web_url(self.target)
        if self.operation == 'download' and (not self.session_id or not self.resource_ids):
            raise ValueError('请选择浏览器会话及待下载资源')
        return self

class SessionConfig(BaseModel):
    platform: str
    url: str = ''
    channel: Literal['chromium', 'msedge'] = 'chromium'
    external: bool = False

class Control(BaseModel):
    action: Literal['pause', 'takeover', 'resume', 'cancel', 'retry']
