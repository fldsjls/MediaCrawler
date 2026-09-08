"""Settings owners and persistence, independent of the settings navigation UI.

Browser defaults are project-wide SQLite settings, snapshotted by a new session.
Appearance remains owned by browser localStorage; platform definitions remain
owned by PlatformRegistry. Runtime state and credentials do not belong here.
"""
from copy import deepcopy
import json
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, Field, field_validator


def validate_value(name, value):
    if name in ('auto_switch','reuse_login') and type(value) is not bool:
        raise ValueError('auto_switch 必须为布尔值')
    if name in ('snapshot_fps', 'realtime_fps') and type(value) is not int:
        raise ValueError(f'{name} 必须为整数枚举值')
    if name == 'navigation_timeout' and type(value) is not int:
        raise ValueError('navigation_timeout 必须为整数秒数')
    if name == 'default_channel' and type(value) is not str:
        raise ValueError('default_channel 必须为浏览器名称')
    return value


class BrowserSettings(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    auto_switch: StrictBool = True
    reuse_login: StrictBool = True
    navigation_timeout: int = Field(30,ge=5,le=600)
    snapshot_fps: Literal[1, 2, 5] = 1
    realtime_fps: Literal[10, 20, 30, 60] = 60
    default_channel: Literal['chromium', 'msedge'] = 'chromium'

    @field_validator('*', mode='before')
    @classmethod
    def exact_types(cls, value, info):
        return validate_value(info.field_name, value)


class BrowserSettingsPatch(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    # None is only the omitted-field default. An explicitly supplied null is invalid.
    auto_switch: StrictBool | None = None
    reuse_login: StrictBool | None = None
    navigation_timeout: int | None = Field(None,ge=5,le=600)
    snapshot_fps: Literal[1, 2, 5] | None = None
    realtime_fps: Literal[10, 20, 30, 60] | None = None
    default_channel: Literal['chromium', 'msedge'] | None = None

    @field_validator('*', mode='before')
    @classmethod
    def exact_types(cls, value, info):
        return validate_value(info.field_name, value)


SECTIONS = [
    dict(id='tasks', title='任务默认值', summary='采集与自动操作默认参数。', persistence='project_sqlite'),
    dict(id='downloads', title='下载与工具', summary='下载引擎与工具配置。', persistence='project_sqlite'),
    dict(id='exports', title='导出与文件', summary='文件保存与导出默认值。', persistence='project_sqlite'),
    dict(id='appearance', title='外观与布局', summary='仅影响当前浏览器的主题、布局与面板偏好。', persistence='localStorage'),
    dict(id='browser', title='浏览器预览', summary='项目级预览默认值，保存后对新建会话生效。', persistence='project_sqlite'),
    dict(id='platforms', title='平台与网站', summary='平台定义由平台注册表维护，此处只提供统一入口。', persistence='project_sqlite'),
    dict(id='data', title='数据与迁移', summary='查看本机归档位置并显式导入资料，保留现有数据。', persistence='project_files'),
]


class SettingsRegistry:
    def __init__(self, repository):
        self.repo = repository

    @staticmethod
    def sections():
        return deepcopy(SECTIONS)

    def read_browser(self):
        row = self.repo.db.execute("SELECT payload FROM settings WHERE section='browser'").fetchone()
        if row is None:
            return BrowserSettings().model_dump()
        # Missing fields inherit their owner-defined defaults. Malformed stored
        # configuration is reported instead of silently overwriting other values.
        return BrowserSettings.model_validate(json.loads(row['payload'])).model_dump()

    def patch_browser(self, patch):
        patch = BrowserSettingsPatch.model_validate(patch)
        changes = patch.model_dump(exclude_unset=True)
        # All read/merge/write operations are synchronous on Repository's owner
        # event loop, so two partial API patches cannot interleave here.
        with self.repo.db:
            current = self.read_browser()
            if not changes:
                return current
            updated = BrowserSettings.model_validate({**current, **changes}).model_dump()
            self.repo.db.execute('''INSERT INTO settings(section,payload,updated) VALUES('browser',?,?)
                ON CONFLICT(section) DO UPDATE SET payload=excluded.payload, updated=excluded.updated''',
                (json.dumps(updated, ensure_ascii=False), time.time()))
        return updated
