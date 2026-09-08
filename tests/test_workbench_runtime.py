"""Operation-boundary tests: manual control may start only after in-flight work settles."""
import asyncio
import io
import json

import pytest

from mediacrawler.workbench.workflows.runtime import Runtime


def events(runtime):
    return [json.loads(line) for line in runtime.output.getvalue().splitlines()]


@pytest.mark.asyncio
async def test_pause_waits_for_active_operation_and_blocks_next():
    runtime = Runtime()
    runtime.output = io.StringIO()
    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    @runtime.wrap
    async def operation(name):
        calls.append(name)
        entered.set()
        if name == 'first':
            await release.wait()

    first = asyncio.create_task(operation('first'))
    await entered.wait()
    runtime.pause()
    assert events(runtime) == []
    second = asyncio.create_task(operation('second'))
    await asyncio.sleep(0)
    assert calls == ['first']
    release.set()
    await first
    assert events(runtime) == [{'type': 'state', 'state': 'paused'}]
    assert not second.done()
    await runtime.resume()
    await second
    assert calls == ['first', 'second']
    assert runtime.active == 0


@pytest.mark.asyncio
async def test_pause_after_wakeup_does_not_dispatch_waiting_operation():
    runtime = Runtime()
    runtime.output = io.StringIO()
    runtime.pause()
    calls = []

    @runtime.wrap
    async def operation():
        calls.append('clicked')

    waiting = asyncio.create_task(operation())
    await asyncio.sleep(0)
    await runtime.resume()
    runtime.pause()  # cleared after Event wakes waiter, before waiter actually runs
    await asyncio.sleep(0)
    assert not calls, 'An Event wakeup must not allow automation after a newer pause'
    await runtime.resume()
    await waiting
    assert calls == ['clicked']


@pytest.mark.asyncio
async def test_nested_operation_can_finish_and_error_releases_barrier():
    runtime = Runtime()
    runtime.output = io.StringIO()
    entered, release = asyncio.Event(), asyncio.Event()

    @runtime.wrap
    async def inner():
        raise ValueError('fixture failure')

    @runtime.wrap
    async def outer():
        entered.set()
        await release.wait()
        await inner()

    current = asyncio.create_task(outer())
    await entered.wait()
    runtime.pause()
    release.set()
    with pytest.raises(ValueError):
        await current
    assert runtime.active == 0
    assert events(runtime)[-1]['state'] == 'paused'


@pytest.mark.asyncio
async def test_resume_validates_login_without_unblocking_collecting():
    runtime = Runtime()
    runtime.output = io.StringIO()
    runtime.pause()

    @runtime.wrap
    async def check_login():
        return False

    runtime.resume_check = check_login
    await asyncio.wait_for(runtime.resume(), 2)
    assert not runtime.ready.is_set()
    assert events(runtime)[-1]['state'] == 'waiting_login'


@pytest.mark.asyncio
async def test_new_takeover_waits_for_resume_validation_and_supersedes_it():
    runtime = Runtime()
    runtime.output = io.StringIO()
    entered, release = asyncio.Event(), asyncio.Event()
    runtime.pause()

    async def validate():
        entered.set()
        await release.wait()
        return True

    runtime.resume_check = validate
    resume = asyncio.create_task(runtime.resume())
    await entered.wait()
    runtime.output = io.StringIO()
    runtime.pause()
    assert events(runtime) == [], 'Manual control must wait for the browser validation operation'
    release.set()
    await resume
    assert not runtime.ready.is_set()
    assert events(runtime) == [{'type': 'state', 'state': 'paused'}]
