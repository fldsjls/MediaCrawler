"""Typed project defaults; plans store overrides and runs store resolved snapshots."""
import json
import time
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from mediacrawler.paths import TOOLS_ROOT


class Defaults(BaseModel):
    model_config = ConfigDict(extra='forbid')
    max_items: int = Field(5, ge=1, le=10000)
    start: int = Field(1, ge=1)
    max_comments: int = Field(20, ge=0, le=10000)
    subcomments: bool = False
    wait_ms: int = Field(5000, ge=100, le=120000)
    selector: str = Field('', max_length=1000)
    engine: Literal['auto', 'http', 'ffmpeg', 'n_m3u8dl'] = 'auto'
    timeout: int = Field(60, ge=5, le=600)
    retries: int = Field(2, ge=0, le=5)
    concurrency: int = Field(4, ge=1, le=16)
    quality: Literal['best', '720', '1080', '2160'] = 'best'
    audio: Literal['default', 'all'] = 'default'
    ffmpeg_path: str = str(TOOLS_ROOT / 'ffmpeg/ffmpeg.exe')
    n_m3u8dl_path: str = str(TOOLS_ROOT / 'n-m3u8dl-re/N_m3u8DL-RE.exe')
    output: Literal['jsonl', 'json', 'csv', 'excel'] = 'jsonl'
    output_dir: str = ''
    export_fields: str = Field('', max_length=1000)
    collision: Literal['rename', 'error'] = 'rename'
    subdirectory: str = ''
    filename: str = ''


def read_defaults(repo):
    row = repo.db.execute("SELECT payload FROM settings WHERE section='task_defaults'").fetchone()
    return Defaults.model_validate(json.loads(row[0]) if row else {}).model_dump()


def save_defaults(repo, patch):
    value = Defaults.model_validate({**read_defaults(repo), **patch}).model_dump()
    for field in ('subdirectory', 'filename'):
        part = Path(value[field])
        if part.is_absolute() or '..' in part.parts or ':' in value[field]:
            raise ValueError('名称和子目录必须位于输出目录内')
    with repo.db:
        repo.db.execute("INSERT INTO settings VALUES('task_defaults',?,?) ON CONFLICT(section) DO UPDATE SET payload=excluded.payload,updated=excluded.updated",
                        (json.dumps(value, ensure_ascii=False), time.time()))
    return value


def resolve(repo, platform, overrides):
    fields = Defaults.model_fields
    merged = {**read_defaults(repo), **{k: v for k, v in platform.get('template_config', {}).items() if k in fields}, **overrides}
    return Defaults.model_validate(merged).model_dump()
