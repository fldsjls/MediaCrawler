import json
import uuid
from copy import deepcopy
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .catalog import PLATFORMS, PLATFORM_TYPES, TEMPLATES


class PlatformDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    category: str
    url: str = Field(max_length=2048)
    template: str = 'preview_only'
    template_config: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=8)
    enabled: bool = True

    @field_validator('name')
    @classmethod
    def strip_name(cls, value):
        if not value.strip():
            raise ValueError('请输入网站名称')
        return value.strip()

    @model_validator(mode='after')
    def validate_definition(self):
        parsed = urlparse(self.url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('网站入口必须是无内嵌凭据的 HTTP / HTTPS 地址')
        if self.category not in {t['id'] for t in PLATFORM_TYPES}:
            raise ValueError('未知平台类型')
        template = next((t for t in TEMPLATES if t['id'] == self.template), None)
        if not template:
            raise ValueError('未知采集模板')
        allowed = {f['key'] for f in template['fields']}
        if set(self.template_config) - allowed:
            raise ValueError('模板含不支持的参数；仅接受声明的字段，不执行脚本')
        selector = self.template_config.get('selector', '')
        wait = self.template_config.get('wait_ms', 5000)
        if not isinstance(selector, str) or len(selector) > 1000:
            raise ValueError('选择器过长或类型错误')
        if type(wait) is not int or not 100 <= wait <= 120000:
            raise ValueError('等待时间应为 100–120000 毫秒')
        self.tags = list(dict.fromkeys(t.strip() for t in self.tags if t.strip()))
        if any(len(t) > 30 for t in self.tags):
            raise ValueError('标签最多 30 个字符')
        return self


class PlatformRegistry:
    def __init__(self, repository):
        self.repo = repository

    def get(self, platform_id):
        builtin = next((p for p in PLATFORMS if p['id'] == platform_id), None)
        if builtin:
            return deepcopy(builtin)
        row = self.repo.db.execute('SELECT payload FROM platforms WHERE id=?', (platform_id,)).fetchone()
        if row is None:
            raise ValueError('平台不存在')
        return self.describe(platform_id, json.loads(row[0]))

    @staticmethod
    def describe(platform_id, definition):
        template = next(t for t in TEMPLATES if t['id'] == definition['template'])
        return dict(**definition, id=platform_id, builtin=False, legacy=False,
            inputs=['detail'], comments=False, images=template['images'], video=template['video'],
            media=template['video'], media_modes=['detail'] if template['video'] else [],
            video_modes=['detail'] if template['video'] else [], collect=template['collect'],
            outputs=['jsonl', 'json', 'csv', 'excel'], video_strategy='capture', verification='user_defined')

    def list(self, include_disabled=False):
        items = [deepcopy(p) for p in PLATFORMS if not p['legacy']]
        items.extend(self.describe(r['id'], json.loads(r['payload'])) for r in self.repo.db.execute('SELECT * FROM platforms ORDER BY rowid'))
        return [p for p in items if include_disabled or p['enabled']]

    def save(self, definition, platform_id=None):
        if platform_id:
            if self.get(platform_id)['builtin']:
                raise ValueError('内置平台由源码维护，不能从配置界面修改')
        else:
            platform_id = 'custom_' + uuid.uuid4().hex[:16]
        self.repo.db.execute('INSERT OR REPLACE INTO platforms(id,payload) VALUES(?,?)',
            (platform_id, definition.model_dump_json()))
        self.repo.db.commit()
        return self.get(platform_id)

    def archive(self, platform_id):
        value = self.get(platform_id)
        if value['builtin']:
            raise ValueError('不能删除内置平台')
        config = {k: value[k] for k in PlatformDefinition.model_fields}
        config['enabled'] = False
        return self.save(PlatformDefinition(**config), platform_id)
