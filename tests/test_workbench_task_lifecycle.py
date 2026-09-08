"""Task cancellation and stale-session recovery without external sites or browsers."""
import asyncio
from types import SimpleNamespace

import pytest

from mediacrawler.workbench.browser.capture import MediaCapture
from mediacrawler.workbench.workflows.legacy_models import SessionConfig, TaskConfig
from mediacrawler.workbench.workflows.service import Workbench


@pytest.mark.asyncio
@pytest.mark.parametrize('explicit', [False, True])
@pytest.mark.parametrize('browser_missing', [False, True])
async def test_disconnected_preview_is_closed_before_replacement(tmp_path, explicit, browser_missing):
    workbench = Workbench(tmp_path)
    calls = []

    def session(identity, connected):
        async def close(): calls.append(('close', identity))
        return SimpleNamespace(id=identity, config=SessionConfig(platform='generic'),
            browser=SimpleNamespace(is_connected=lambda: connected), task_id=None,
            control_lock=asyncio.Lock(), manual=True, controller=None, close=close)

    old = session('dead', False)
    if browser_missing:
        old.browser = None
    workbench.sessions.items[old.id] = old
    fresh = session('replacement', True)

    async def create(config):
        assert old.id not in workbench.sessions.items, 'A dead profile must not block replacement creation'
        assert calls == [('close', old.id)]
        assert config.platform == 'generic'
        workbench.sessions.items[fresh.id] = fresh
        return fresh

    workbench.sessions.create = create
    task = workbench.create(TaskConfig(platform='generic', target='http://localhost/fixture',
                                      session_id=old.id if explicit else None))
    try:
        run = workbench.pending[task['id']]
        await workbench.prepare_session(run)
        assert run.session is fresh
        assert workbench.repo.task(run.id)['session_id'] == fresh.id
        assert fresh.task_id == run.id and not fresh.manual
    finally:
        await workbench.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('action', ['cancel', 'pause'])
async def test_inflight_direct_http_cancel_releases_queue_but_pause_allows_completion(tmp_path, action):
    entered, disconnected, deliver = asyncio.Event(), asyncio.Event(), asyncio.Event()
    handlers = set()

    async def serve(reader, writer):
        handler = asyncio.current_task()
        handlers.add(handler)
        closed = None
        available = None
        try:
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: video/mp4\r\nContent-Length: 4\r\nConnection: close\r\n\r\n')
            await writer.drain()
            entered.set()
            closed = asyncio.create_task(reader.read())
            available = asyncio.create_task(deliver.wait())
            done, _ = await asyncio.wait([closed, available], return_when=asyncio.FIRST_COMPLETED)
            if available in done:
                writer.write(b'data')
                await writer.drain()
                await closed
            disconnected.set()
        finally:
            for child in (closed, available):
                if child and not child.done(): child.cancel()
            await asyncio.gather(*(child for child in (closed, available) if child), return_exceptions=True)
            writer.close()
            await writer.wait_closed()
            handlers.discard(handler)

    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    base = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}'
    workbench = Workbench(tmp_path)
    session = SimpleNamespace(id='fixture', media=MediaCapture('fixture', 'generic'), context=None,
                              control_lock=asyncio.Lock(), controller=None, manual=False, finished=False)
    following_started = asyncio.Event()

    async def prepare(run): run.session = session

    async def collect(run):
        following_started.set()
        workbench.repo.record(run.id, dict(id='next', kind='content', title='Next task'))
        run.worker_done = True

    workbench.prepare_session, workbench.collect = prepare, collect
    first = workbench.create(TaskConfig(platform='generic', target=base + '/first'))
    run = workbench.pending[first['id']]
    run.download_only, run.session = True, session
    resource = session.media.add(dict(url=base + '/silent.mp4', title='In-flight direct file', origin='browser'))
    workbench.enqueue_resource(run, session.media.get(resource['id']), manual=True)
    second = workbench.create(TaskConfig(platform='generic', target=base + '/next'))

    async def wait_file(state):
        while workbench.repo.results(run.id)['files'][0]['state'] != state:
            await asyncio.sleep(.01)

    try:
        await workbench.start()
        await asyncio.wait_for(entered.wait(), 3)
        await asyncio.wait_for(workbench.control(run.id, action), 3)
        if action == 'pause':
            assert not run.download_task.done() and not disconnected.is_set()
            deliver.set()
            await asyncio.wait_for(wait_file('succeeded'), 3)
            assert workbench.repo.task(run.id)['state'] == 'paused'
            assert not following_started.is_set(), 'Paused task must retain queue ownership'
            await workbench.control(run.id, 'resume')
        await asyncio.wait_for(disconnected.wait(), 3)
        await asyncio.wait_for(workbench.queue.join(), 3)
        expected = 'cancelled' if action == 'cancel' else 'succeeded'
        assert workbench.repo.task(run.id)['state'] == expected
        result = workbench.repo.results(run.id)
        assert result['files'][0]['state'] == expected
        assert result['resources'][0]['state'] == expected
        assert session.media.get(resource['id'])['state'] == expected
        assert following_started.is_set()
        assert workbench.repo.task(second['id'])['state'] == 'succeeded'
        if action == 'cancel':
            assert not deliver.is_set(), 'Cancellation must close a silent response without waiting for its body'
    finally:
        deliver.set()
        await workbench.close()
        await session.media.close()
        server.close()
        await server.wait_closed()
        for handler in tuple(handlers): handler.cancel()
        await asyncio.gather(*tuple(handlers), return_exceptions=True)


@pytest.mark.asyncio
async def test_cancel_request_disconnect_does_not_interrupt_download_finalizer(tmp_path):
    workbench = Workbench(tmp_path)
    task = workbench.create(TaskConfig(platform='generic', target='http://localhost/fixture'))
    run = workbench.pending[task['id']]
    started, finalizing, release, finished = (asyncio.Event() for _ in range(4))

    async def transfer():
        try:
            started.set()
            await asyncio.Event().wait()
        finally:
            finalizing.set()
            await release.wait()
            finished.set()

    run.download_task = asyncio.create_task(transfer())
    workbench.active = run
    await started.wait()
    request = asyncio.create_task(workbench.control(run.id, 'cancel'))
    try:
        await asyncio.wait_for(finalizing.wait(), 1)
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        assert not run.download_task.done(), 'HTTP disconnect must not propagate a second cancellation into cleanup'
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
        await asyncio.gather(run.download_task, return_exceptions=True)
    finally:
        release.set()
        await asyncio.gather(run.download_task, return_exceptions=True)
        workbench.active = None
        await workbench.close()
