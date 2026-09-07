import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.parametrize('video,images,expected', [(False, False, []), (True, False, ['video']), (False, True, ['image']), (True, True, ['video', 'image'])])
def test_capture_resource_types_and_independent_choices(video, images, expected):
    worker = Path(__file__).resolve().parents[1] / 'src' / 'browser-worker'
    config = {'platform': 'generic', 'target': 'https://fixture.test', 'max_items': 5,
              'max_downloads': 5, 'media': True, 'download_video': video, 'download_images': images}
    script = '''import { captured } from './src/workbench/runtime.ts';
      captured({url:'https://media.test/a.m3u8?token=first'});
      captured({url:'https://media.test/a.m3u8?token=renewed'});
      captured({url:'https://media.test/photo.jpg',kind:'image'});'''
    result = subprocess.run(['node', '--import', 'tsx', '--input-type=module', '-e', script], cwd=worker,
                            env={**os.environ, 'MC_TASK_CONFIG': json.dumps(config)}, capture_output=True,
                            text=True, encoding='utf-8', timeout=20)
    assert result.returncode == 0, result.stderr
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert len([event for event in events if event['type'] == 'record']) == 2
    resources = [event['resource'] for event in events if event['type'] == 'resource']
    assert [resource['kind'] for resource in resources] == expected
    assert all(resource['origin'] == 'adapter' and resource['key'].startswith('generic:content:') for resource in resources)
