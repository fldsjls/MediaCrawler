from types import SimpleNamespace

import pytest

from mediacrawler.workbench.models import TaskConfig
from mediacrawler.workbench.service import TaskRun, Workbench


@pytest.mark.asyncio
@pytest.mark.parametrize('media,expected', [(True, 'partial'), (False, 'succeeded')])
async def test_requested_media_without_resources_is_not_reported_as_complete(tmp_path, media, expected):
    workbench = Workbench(tmp_path)
    config = TaskConfig(platform='bili', target='BV-fixture', media=media, max_downloads=1)
    task_id = workbench.repo.create(config.model_dump())
    run = TaskRun(task_id, config)

    async def prepare(current):
        current.session = SimpleNamespace(manual=False, finished=False)

    async def collect(current):
        workbench.repo.record(current.id, {'id': 'content:fixture', 'kind': 'content', 'title': 'Fixture'})
        current.worker_done = True

    workbench.prepare_session = prepare
    workbench.collect = collect
    try:
        await workbench.execute(run)
        assert workbench.repo.task(task_id)['state'] == expected
        assert workbench.repo.task(task_id)['counts']['content'] == 1
    finally:
        await workbench.close()


@pytest.mark.asyncio
async def test_expiring_resource_gets_one_refresh_without_redownloading_success(tmp_path):
    from mediacrawler.workbench.media.capture import MediaCapture
    workbench = Workbench(tmp_path)
    config = TaskConfig(platform='bili', target='BV-fixture', download_video=True, max_downloads=2)
    task_id = workbench.repo.create(config.model_dump())
    run = TaskRun(task_id, config)
    calls, transfers = [], []
    session = SimpleNamespace(manual=False, finished=False, endpoint='http://127.0.0.1:0', media=MediaCapture('fixture'))

    async def prepare(current):
        current.session = session

    async def collect(current):
        calls.append('collect')
        for key in ('stable', 'expiring'):
            workbench.repo.record(current.id, dict(id=key, kind='content', title=key, fields={'video_status': 'available'}))
            workbench.worker_event(current, dict(type='resource', resource=dict(url=f'http://127.0.0.1/{key}.mp4?token={len(calls)}',
                key=key, parent_id=key, title=key)))
        current.worker_done = True

    async def transfer(current, item):
        private = workbench._private_resource(current, item)
        transfers.append((private['key'], private['url']))
        if private['key'] == 'expiring' and 'token=1' in private['url']:
            raise RuntimeError('媒体请求返回 HTTP 403')
        path = tmp_path / f'{private["key"]}.mp4'
        path.write_bytes(b'fixture')
        # Files are archived relative to the task directory by the service.
        destination = workbench.repo.directory(current.id) / path.name
        destination.write_bytes(path.read_bytes())
        return destination

    workbench.prepare_session, workbench.collect, workbench.download = prepare, collect, transfer
    try:
        await workbench.execute(run)
        assert workbench.repo.task(task_id)['state'] == 'succeeded'
        assert len(calls) == 2
        assert [key for key, _ in transfers].count('stable') == 1
        assert [key for key, _ in transfers].count('expiring') == 2
    finally:
        await workbench.close()
