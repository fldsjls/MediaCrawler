import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mediacrawler.workbench.browser import BrowserSession
from mediacrawler.workbench.workflows.legacy_models import SessionConfig, TaskConfig
from mediacrawler.workbench.platforms.registry import PlatformDefinition, PlatformRegistry
from mediacrawler.workbench.persistence.repository import Repository
from mediacrawler.workbench.workflows.service import Workbench


def test_platform_categories_are_not_executable_capabilities(tmp_path):
    repo = Repository(tmp_path)
    try:
        registry = PlatformRegistry(repo)
        books = registry.save(PlatformDefinition(name='本地书籍站', category='books', url='http://127.0.0.1:8091', template='preview_only'))
        assert books['category'] == 'books' and not books['collect']
        assert 'generic' in {p['id'] for p in registry.list()}
        assert registry.get('meishiwang')['name'] == '美石建工'
        assert all(p['video'] for p in registry.list() if p['builtin'])
        updated = registry.save(PlatformDefinition(name='本地演示视频', category='video', url=books['url'],
            template='video_capture', template_config={'selector': 'video', 'wait_ms': 300}), books['id'])
        assert updated['collect'] and updated['video']
        registry.archive(books['id'])
        assert books['id'] not in {p['id'] for p in registry.list()}
        assert registry.get(books['id'])['enabled'] is False
        with pytest.raises(ValueError, match='内置'):
            registry.archive('bili')
    finally:
        repo.db.close()


@pytest.mark.parametrize('changes', [dict(template='execute'), dict(template_config={'script': 'alert(1)'}),
    dict(url='javascript:alert(1)'), dict(url='https://name:secret@example.com'), dict(category='unknown'),
    dict(template_config={'wait_ms': -1}), dict(name=' ')])
def test_custom_definition_rejects_unknown_or_executable_configuration(changes):
    with pytest.raises(ValidationError):
        PlatformDefinition(**{'name': 'Fixture', 'url': 'http://127.0.0.1:8081', 'category': 'video',
            'template': 'video_capture', **changes})


def test_registry_and_v2_backup_survive_restart(tmp_path):
    import sqlite3
    path = tmp_path / 'index.sqlite3'
    with sqlite3.connect(path) as old:
        old.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY, state TEXT, config TEXT, created REAL, updated REAL, session_id TEXT, error TEXT)')
        old.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)', ('a' * 32, 'succeeded', '{}', 0, 0, None, ''))
    repo = Repository(tmp_path)
    definition = PlatformRegistry(repo).save(PlatformDefinition(name='商城预览', category='shopping', url='https://example.com'))
    repo.db.close()
    assert len(list((tmp_path / 'backups').glob('index-before-v4-*.sqlite3'))) == 1
    reopened = Repository(tmp_path)
    try:
        assert PlatformRegistry(reopened).get(definition['id'])['name'] == '商城预览'
        assert reopened.task('a' * 32)['state'] == 'succeeded'
        assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    finally:
        reopened.db.close()


@pytest.mark.asyncio
async def test_discovery_is_passive_and_manual_download_needs_owned_resource(tmp_path):
    workbench = Workbench(tmp_path)
    session = BrowserSession(SessionConfig(platform='bili'), tmp_path)
    workbench.sessions.items[session.id] = session
    try:
        resource = session.media.add(dict(url='http://127.0.0.1/clip.mp4?token=secret', headers={'Authorization': 'SECRET'},
            title='演示视频', page_url='http://127.0.0.1/watch', origin='browser'))
        assert workbench.repo.tasks() == []  # previews and sniffed network traffic never create jobs
        assert 'url' not in resource and 'headers' not in resource
        with pytest.raises(ValueError, match='不属于'):
            workbench.create(TaskConfig(platform='bili', target='BV-fixture', operation='download',
                resource_ids=['unknown'], session_id=session.id))
        created = workbench.create(TaskConfig(platform='bili', target='http://127.0.0.1/watch', operation='download',
            resource_ids=[resource['id']], session_id=session.id, max_downloads=1))
        results = workbench.repo.results(created['id'])
        assert len(results['files']) == 1 and results['files'][0]['state'] == 'pending'
        assert 'secret' not in json.dumps(results).lower()
        assert results['records'][0]['fields']['selection'] == 'manual'
    finally:
        await workbench.close()


@pytest.mark.asyncio
async def test_preview_template_does_not_pretend_to_collect_books(tmp_path):
    workbench = Workbench(tmp_path)
    try:
        platform = workbench.platforms.save(PlatformDefinition(name='书籍', url='http://127.0.0.1', category='books'))
        with pytest.raises(ValueError, match='仅支持预览'):
            workbench.create(TaskConfig(platform=platform['id'], target=platform['url']))
        assert not workbench.repo.tasks()
    finally:
        await workbench.close()


@pytest.mark.asyncio
async def test_download_only_adapter_resource_has_content_and_queued_cancel_closes_files(tmp_path):
    workbench = Workbench(tmp_path)
    session = BrowserSession(SessionConfig(platform='bili'), tmp_path)
    workbench.sessions.items[session.id] = session
    try:
        resource = session.media.add(dict(url='http://127.0.0.1/clip.mp4', parent_id='content:original',
            title='原视频', page_url='http://127.0.0.1/watch', origin='adapter'))
        created = workbench.create(TaskConfig(platform='bili', target='http://127.0.0.1/watch', operation='download',
            resource_ids=[resource['id']], session_id=session.id, max_downloads=1))
        results = workbench.repo.results(created['id'])
        assert results['records'][0]['id'] == 'content:original'
        assert results['files'][0]['parent_id'] == 'content:original'
        await workbench.control(created['id'], 'cancel')
        task = workbench.repo.task(created['id'])
        assert task['state'] == 'cancelled' and task['counts']['files_pending'] == 0
        assert task['counts']['files_cancelled'] == 1
        assert session.media.get(resource['id'])['state'] == 'cancelled'
    finally:
        await workbench.close()


@pytest.mark.asyncio
async def test_terminal_download_append_and_retry_cannot_steal_reserved_session(tmp_path):
    workbench = Workbench(tmp_path)
    session = BrowserSession(SessionConfig(platform='bili'), tmp_path)
    workbench.sessions.items[session.id] = session
    try:
        resource = session.media.add(dict(url='http://127.0.0.1/clip.mp4', title='视频'))
        original = workbench.create(TaskConfig(platform='bili', target='BV-fixture', session_id=session.id))
        workbench.repo.state(original['id'], 'partial')
        owner = workbench.create(TaskConfig(platform='bili', target='BV-next', session_id=session.id))
        # The task-list display limit must not weaken session exclusivity.
        for _ in range(201):
            task_id = workbench.repo.create(TaskConfig(platform='bili', target='BV-old').model_dump())
            workbench.repo.state(task_id, 'succeeded')
        assert owner['id'] not in {t['id'] for t in workbench.repo.tasks()}
        assert workbench.repo.platform_in_use('bili')
        with pytest.raises(ValueError, match='占用'):
            await workbench.add_downloads(original['id'], session.id, [resource['id']])
        with pytest.raises(ValueError, match='占用'):
            await workbench.control(original['id'], 'retry')
        with pytest.raises(ValueError, match='占用'):
            workbench.create(TaskConfig(platform='bili', target='BV-another', session_id=session.id))
        assert workbench.repo.task(original['id'])['state'] == 'partial'
        assert workbench.repo.results(original['id'])['files'] == []
    finally:
        await workbench.close()
