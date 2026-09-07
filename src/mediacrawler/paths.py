"""Canonical application paths, independent of the shell working directory.

MC_LOCAL_DIR can relocate mutable data without moving source code. Resource and
build paths always belong to this checkout; user output overrides remain explicit.
"""
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / 'src'
PACKAGE_ROOT = Path(__file__).resolve().parent
LOCAL_ROOT = Path(os.environ.get('MC_LOCAL_DIR', PROJECT_ROOT / '.local')).expanduser().resolve()
DATA_ROOT = LOCAL_ROOT / 'data'
WORKBENCH_ROOT = DATA_ROOT / 'workbench'
BROWSER_ROOT = LOCAL_ROOT / 'browser-data'
TEMP_ROOT = LOCAL_ROOT / 'temp'
LOG_ROOT = LOCAL_ROOT / 'logs'
TOOLS_ROOT = LOCAL_ROOT / 'tools'
BUILD_ROOT = PROJECT_ROOT / '.build'
WEBUI_ROOT = BUILD_ROOT / 'webui'
WORKER_ROOT = SOURCE_ROOT / 'browser-worker'
RESOURCE_ROOT = PACKAGE_ROOT / 'resources'


def javascript(name: str) -> str:
    """Return an absolute packaged JavaScript filename for browser/ExecJS APIs."""
    return str(RESOURCE_ROOT / 'js' / name)
