import asyncio
import json
import os
import subprocess

import pytest

from api.workbench.browser import kill_tree
from api.workbench.service import WORKER


@pytest.mark.asyncio
async def test_new_takeover_supersedes_node_resume_validation():
    script = '''
      import { initialize, waitForLogin, emit } from './src/workbench/runtime.ts';
      initialize(async () => {
        emit('validation_started');
        await new Promise(resolve => setTimeout(resolve, 300));
        emit('validation_finished');
        return true;
      });
      await waitForLogin();
      emit('done');
      process.exit(0);
    '''
    process = subprocess.Popen(['node', '--import', 'tsx', '--input-type=module', '-e', script],
        cwd=WORKER, env={**os.environ, 'MC_TASK_CONFIG': '{}'}, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8')
    async def event():
        line = await asyncio.wait_for(asyncio.to_thread(process.stdout.readline), 10)
        assert line, process.stderr.read()
        return json.loads(line)
    def command(action):
        process.stdin.write(json.dumps({'action': action}) + '\n')
        process.stdin.flush()
    try:
        assert (await event())['state'] == 'waiting_login'
        command('resume')
        assert (await event())['type'] == 'validation_started'
        command('takeover')
        assert (await event())['type'] == 'validation_finished', 'Takeover must not be acknowledged during active validation'
        assert (await event())['state'] == 'paused'
        command('resume')
        assert (await event())['type'] == 'validation_started'
        assert (await event())['type'] == 'validation_finished'
        assert (await event())['state'] == 'running'
        assert (await event())['type'] == 'done'
    finally:
        await kill_tree(process)
