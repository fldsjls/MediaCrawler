import json
import shutil
import subprocess
import uuid
import stat
from pathlib import Path
from mediacrawler.workbench.workflows.legacy_models import PLATFORMS

def import_files(root, config, has_sessions=False, known_platforms=None):
    def linked(path):
        return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    selected = Path(config['source']).expanduser()
    if not selected.exists() or linked(selected):
        raise ValueError('请选择普通数据文件或目录，不接受符号链接或目录联接')
    source = selected.resolve()
    if source == source.parent:
        raise ValueError('请选择有效的数据文件或目录')
    if config['kind'] not in ('data', 'profile', 'storage-state'):
        raise ValueError('未知导入类型')
    if config['platform'] not in (known_platforms or {p['id'] for p in PLATFORMS}) or config['channel'] not in ('chromium', 'msedge'):
        raise ValueError('平台或浏览器类型无效')
    if config['kind'] == 'profile':
        processes = subprocess.run(['powershell', '-NoProfile', '-Command',
            "Get-Process chrome,msedge,chromium -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"],
            capture_output=True, text=True)
        if has_sessions or processes.stdout.strip():
            raise ValueError('复制 Profile 前请关闭所有 Chromium / Edge 浏览器与预览会话')
        destination = root / 'profiles' / f'{config["platform"]}-{config["channel"]}'
        if destination.exists():
            raise ValueError('目标 Profile 已存在，导入不会覆盖；请使用其他导入方式或人工备份处理')
    else:
        destination = root / 'imports' / uuid.uuid4().hex / source.name
    if destination.resolve().is_relative_to(source) or source.is_relative_to(root.resolve()):
        raise ValueError('不能导入工作台自己的运行目录')
    if source.is_dir():
        # Junctions and links can escape the selected directory or recursively copy storage.
        if any(linked(p) for p in source.rglob('*')):
            raise ValueError('导入目录含符号链接或目录联接，请先提供普通文件副本')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns('.git', 'node_modules', '.venv', 'Singleton*'))
    else:
        if config['kind'] == 'profile':
            raise ValueError('Profile 必须是目录')
        if config['kind'] == 'storage-state':
            payload = json.loads(source.read_text(encoding='utf-8-sig'))
            if not isinstance(payload, dict) or not isinstance(payload.get('cookies'), list):
                raise ValueError('不是 Playwright storage_state 文件')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    return destination
