"""Checkout relocation must not redirect resource reads or mutable data into cwd."""
import json
import os
import subprocess
import sys
from pathlib import Path

from mediacrawler.paths import PROJECT_ROOT, RESOURCE_ROOT


def test_installed_package_paths_from_unrelated_directory(tmp_path):
    env = os.environ.copy()
    env.pop('PYTHONPATH', None)
    env['MC_LOCAL_DIR'] = str(tmp_path / 'local-data')
    code = """
import json
from pathlib import Path
from mediacrawler.paths import PROJECT_ROOT, LOCAL_ROOT, WORKER_ROOT, javascript
print(json.dumps([str(PROJECT_ROOT), str(LOCAL_ROOT), str(WORKER_ROOT), Path(javascript('stealth.min.js')).is_file()]))
"""
    result = subprocess.run([sys.executable, '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    project, local, worker, js_exists = json.loads(result.stdout)
    assert Path(project) == PROJECT_ROOT
    assert Path(local) == tmp_path / 'local-data'
    assert Path(worker) == PROJECT_ROOT / 'src/browser-worker'
    assert js_exists
    assert RESOURCE_ROOT.is_dir()
