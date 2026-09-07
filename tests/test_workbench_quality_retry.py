"""A failed logical video keeps its quota slot when a refreshed quality changes."""
import asyncio
from types import SimpleNamespace

import pytest

from mediacrawler.workbench.media.capture import MediaCapture
from mediacrawler.workbench.media.identity import logical_resource_identity, resource_identity
from mediacrawler.workbench.models import TaskConfig
from mediacrawler.workbench.service import TaskRun, Workbench


@pytest.mark.asyncio
@pytest.mark.parametrize('before,after', [(720,1080),(1080,720)])
@pytest.mark.parametrize('identity_source', ['key','url'])
async def test_expired_video_quality_change_reuses_one_file_slot(tmp_path, before, after, identity_source):
    workbench = Workbench(tmp_path)
    config = TaskConfig(platform='bili', target='BV-fixture', download_video=True, max_downloads=1)
    task_id = workbench.repo.create(config.model_dump())
    run = TaskRun(task_id, config)
    session = SimpleNamespace(manual=False, finished=False, endpoint='http://127.0.0.1:0', media=MediaCapture('fixture'))
    calls, transfers = [], []

    async def prepare(current): current.session = session

    async def collect(current):
        calls.append('collect')
        quality = before if len(calls) == 1 else after
        workbench.repo.record(current.id, dict(id='post', kind='content', title='Post', fields={'video_status':'available'}))
        resource = dict(parent_id='post', title='Video', quality=f'{quality}p', height=quality,
                        url=f'https://media.example/{quality if identity_source == "key" else "video"}.mp4?token={len(calls)}')
        if identity_source == 'key': resource['key'] = 'bili:post:video:one'
        workbench.worker_event(current, dict(type='resource', resource=resource))
        current.worker_done = True

    async def transfer(current, item):
        resource = workbench._private_resource(current, item)
        transfers.append(resource['height'])
        if len(transfers) == 1: raise RuntimeError('媒体请求返回 HTTP 403')
        path = workbench.repo.directory(current.id) / 'video.mp4'
        path.write_bytes(b'valid test content')
        return path

    workbench.prepare_session, workbench.collect, workbench.download = prepare, collect, transfer
    try:
        await workbench.execute(run)
        result = workbench.repo.results(run.id)
        assert transfers == [before,after] and len(calls) == 2
        assert workbench.repo.task(run.id)['state'] == 'succeeded'
        assert len(result['files']) == 1 and result['files'][0]['height'] == after
        assert result['files'][0]['state'] == 'succeeded'
        old = next(r for r in result['resources'] if r['height'] == before)
        assert old['id'] != result['files'][0]['id'], 'Concrete quality identities must remain distinct'
        assert old['state'] == 'unavailable' and old['superseded_by'] == result['files'][0]['id']
        assert workbench.repo.task(run.id)['counts']['files_failed'] == 0
    finally:
        await workbench.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('manual,other_video', [(True,False),(False,True)])
async def test_refresh_cannot_replace_manual_quality_or_unrelated_video(tmp_path, manual, other_video):
    workbench = Workbench(tmp_path)
    config = TaskConfig(platform='bili', target='BV-fixture', download_video=True, max_downloads=1)
    task_id = workbench.repo.create(config.model_dump())
    run = TaskRun(task_id, config)
    run.session = SimpleNamespace(media=MediaCapture('fixture'))
    workbench.repo.record(run.id, dict(id='post', kind='content', fields={'video_status':'available'}))
    old = dict(parent_id='post', key='video:one', title='Video', quality='720p', height=720,
               url='https://media.example/720.mp4')
    try:
        workbench.enqueue_resource(run, old, manual=manual)
        file = workbench.repo.results(run.id)['files'][0]
        workbench.repo.file(run.id, {**file, 'state':'failed', 'error':'HTTP 403'})
        run.retry = True
        workbench.enqueue_resource(run, {**old, 'key':'video:two' if other_video else old['key'],
                                        'quality':'1080p','height':1080,'url':'https://media.example/1080.mp4'})
        result = workbench.repo.results(run.id)
        assert len(result['files']) == 1
        assert result['files'][0]['id'] == file['id'] and result['files'][0]['state'] == 'failed'
        assert not any(r.get('superseded_by') for r in result['resources'])
    finally:
        await workbench.close()


@pytest.mark.asyncio
async def test_refresh_never_redownloads_a_successful_logical_video(tmp_path):
    workbench = Workbench(tmp_path)
    config = TaskConfig(platform='bili', target='BV-fixture', download_video=True, max_downloads=2)
    task_id = workbench.repo.create(config.model_dump())
    run = TaskRun(task_id, config)
    session = SimpleNamespace(manual=False, finished=False, endpoint='http://127.0.0.1:0', media=MediaCapture('fixture'))
    calls, transfers = [], []
    async def prepare(current): current.session = session
    async def collect(current):
        calls.append('collect')
        height = 720 if len(calls) == 1 else 1080
        workbench.repo.record(current.id, dict(id='post', kind='content', fields={'video_status':'available'}))
        for key in ('one','two'):
            workbench.worker_event(current, dict(type='resource', resource=dict(parent_id='post',
                key=key, title=key, height=height, quality=f'{height}p', url=f'https://media.example/{key}/{height}.mp4')))
        current.worker_done = True
    async def transfer(current, item):
        resource = workbench._private_resource(current, item)
        transfers.append((resource['key'],resource['height']))
        if resource['key'] == 'two' and resource['height'] == 720: raise RuntimeError('HTTP 403')
        path = workbench.repo.directory(current.id) / (resource['key'] + '.mp4')
        path.write_bytes(b'valid')
        return path
    workbench.prepare_session, workbench.collect, workbench.download = prepare, collect, transfer
    try:
        await workbench.execute(run)
        assert transfers == [('one',720),('two',720),('two',1080)]
        assert workbench.repo.task(run.id)['state'] == 'succeeded'
        assert len(workbench.repo.results(run.id)['files']) == 2
    finally:
        await workbench.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('old_succeeds', [False,True])
async def test_variant_discovered_during_inflight_retry_waits_for_owned_slot(tmp_path, old_succeeds):
    workbench = Workbench(tmp_path)
    config = TaskConfig(platform='bili', target='BV-fixture', download_video=True, max_downloads=1)
    task_id = workbench.repo.create(config.model_dump())
    run = TaskRun(task_id, config, retry=True)
    run.session = SimpleNamespace(media=MediaCapture('fixture'))
    entered, release = asyncio.Event(), asyncio.Event()
    attempts = []
    old = dict(parent_id='post', key='video:one', title='Video', quality='720p', height=720,
               url='https://media.example/720.mp4')
    async def transfer(current, item):
        attempts.append(item['height'])
        if item['height'] == 720:
            entered.set()
            await release.wait()
            if not old_succeeds: raise RuntimeError('HTTP 403')
        path = workbench.repo.directory(current.id) / 'video.mp4'
        path.write_bytes(b'valid')
        return path
    workbench.download = transfer
    workbench.enqueue_resource(run, old)
    task = asyncio.create_task(workbench.downloads(run))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        workbench.enqueue_resource(run, {**old,'height':1080,'quality':'1080p','url':'https://media.example/1080.mp4'})
        assert len(workbench.repo.results(run.id)['files']) == 1
        run.collecting = False
        release.set()
        await asyncio.wait_for(task, 2)
        assert attempts == ([720] if old_succeeds else [720,1080])
        assert len(workbench.repo.results(run.id)['files']) == 1
        assert not run.replacement_candidates
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await workbench.close()


def test_logical_identity_requires_location_not_parent_and_keeps_quality_ids():
    old = dict(source='bili', parent_id='post', key='video:one', quality='720p')
    new = {**old,'quality':'1080p'}
    assert logical_resource_identity(old) == logical_resource_identity(new)
    assert resource_identity(old) != resource_identity(new)
    assert logical_resource_identity(old) != logical_resource_identity({**old,'key':'video:two'})
    assert logical_resource_identity({'source':'bili','parent_id':'post'}) == ''
