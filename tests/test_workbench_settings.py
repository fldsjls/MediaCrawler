"""Owner-controlled browser settings, narrow PATCH and migration boundaries."""
from contextlib import asynccontextmanager
import json
import sqlite3
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from mediacrawler.workbench.persistence.repository import Repository
from mediacrawler.workbench.settings import BrowserSettings, SettingsRegistry
from mediacrawler.workbench.settings.router import create_settings_router


@pytest.fixture
def settings_api(tmp_path):
    state = SimpleNamespace(repo=None)

    @asynccontextmanager
    async def lifespan(_app):
        state.repo = Repository(tmp_path)
        yield
        state.repo.db.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(create_settings_router(lambda: state.repo), prefix='/api')
    with TestClient(app) as client:
        yield client, state


def test_browser_defaults_do_not_create_persisted_configuration(tmp_path):
    repo = Repository(tmp_path)
    try:
        assert SettingsRegistry(repo).read_browser() == {
            'auto_switch': True, 'snapshot_fps': 1, 'realtime_fps': 60, 'default_channel': 'chromium', 'reuse_login': True, 'navigation_timeout': 30,
        }
        assert repo.db.execute('SELECT count(*) FROM settings').fetchone()[0] == 0
    finally:
        repo.db.close()


def test_partial_patch_preserves_other_fields_and_other_owners_after_restart(tmp_path):
    repo = Repository(tmp_path)
    settings = SettingsRegistry(repo)
    repo.db.execute("INSERT INTO settings VALUES('future-owner',?,0)", ('{"untouched": true}',))
    repo.db.commit()
    settings.patch_browser({'auto_switch': False, 'realtime_fps': 30})
    value = settings.patch_browser({'snapshot_fps': 5})
    assert value == {'auto_switch': False, 'snapshot_fps': 5, 'realtime_fps': 30, 'default_channel': 'chromium', 'reuse_login': True, 'navigation_timeout': 30}
    # Returned snapshots are detached from persisted state and class defaults.
    value['default_channel'] = 'msedge'
    assert settings.read_browser()['default_channel'] == 'chromium'
    before = repo.db.execute("SELECT updated FROM settings WHERE section='browser'").fetchone()[0]
    assert settings.patch_browser({})['snapshot_fps'] == 5
    assert repo.db.execute("SELECT updated FROM settings WHERE section='browser'").fetchone()[0] == before
    repo.db.close()
    reopened = Repository(tmp_path)
    try:
        assert SettingsRegistry(reopened).read_browser() == {'auto_switch': False, 'snapshot_fps': 5, 'realtime_fps': 30, 'default_channel': 'chromium', 'reuse_login': True, 'navigation_timeout': 30}
        assert json.loads(reopened.db.execute("SELECT payload FROM settings WHERE section='future-owner'").fetchone()[0]) == {'untouched': True}
        assert BrowserSettings().snapshot_fps == 1
    finally:
        reopened.db.close()


def test_api_sections_describe_owners_without_moving_their_storage(settings_api):
    client, state = settings_api
    response = client.get('/api/settings/sections')
    assert response.status_code == 200
    sections = {section['id']: section for section in response.json()}
    assert set(sections) == {'appearance', 'browser', 'platforms', 'data', 'tasks', 'downloads', 'exports'}
    assert all(set(section) == {'id', 'title', 'summary', 'persistence'} for section in sections.values())
    assert sections['appearance']['persistence'] == 'localStorage'
    assert sections['platforms']['persistence'] == 'project_sqlite'
    assert client.patch('/api/settings/appearance', json={'theme': 'dark'}).status_code == 404
    assert client.patch('/api/settings/browser', json={'default_channel': 'msedge'}).json()['default_channel'] == 'msedge'
    rows = client.portal.call(lambda: state.repo.db.execute('SELECT section FROM settings').fetchall())
    assert [row[0] for row in rows] == ['browser']


def test_browser_api_patch_merges_and_returns_complete_normalized_value(settings_api):
    client, _state = settings_api
    assert client.get('/api/settings/browser').json() == BrowserSettings().model_dump()
    first = client.patch('/api/settings/browser', json={'auto_switch': False, 'realtime_fps': 10})
    assert first.status_code == 200
    second = client.patch('/api/settings/browser', json={'snapshot_fps': 2})
    assert second.status_code == 200
    expected = {'auto_switch': False, 'snapshot_fps': 2, 'realtime_fps': 10, 'default_channel': 'chromium', 'reuse_login': True, 'navigation_timeout': 30}
    assert second.json() == expected
    assert client.get('/api/settings/browser').json() == expected
    assert client.patch('/api/settings/browser', json={}).json() == expected


@pytest.mark.parametrize('invalid', [
    {'snapshot_fps': 0}, {'snapshot_fps': 3}, {'snapshot_fps': '1'}, {'snapshot_fps': 1.0}, {'snapshot_fps': True},
    {'realtime_fps': 1}, {'realtime_fps': 61}, {'realtime_fps': '20'}, {'realtime_fps': False},
    {'auto_switch': 1}, {'auto_switch': 'false'}, {'auto_switch': None},
    {'snapshot_fps': None}, {'realtime_fps': None}, {'default_channel': None},
    {'default_channel': 'chrome'}, {'default_channel': 'CHROMIUM'},
    {'cookies': 'not-a-setting'}, {'theme': 'dark'}, {'platforms': []},
])
def test_api_rejects_invalid_values_unknown_fields_and_secrets_without_partial_write(settings_api, invalid):
    client, _state = settings_api
    client.patch('/api/settings/browser', json={'snapshot_fps': 2})
    before = client.get('/api/settings/browser').json()
    response = client.patch('/api/settings/browser', json={'auto_switch': False, **invalid})
    assert response.status_code == 422
    assert client.get('/api/settings/browser').json() == before


def test_owner_validates_direct_calls_without_relying_on_http(tmp_path):
    repo = Repository(tmp_path)
    try:
        settings = SettingsRegistry(repo)
        with pytest.raises(ValidationError):
            settings.patch_browser({'snapshot_fps': True})
        with pytest.raises(ValidationError):
            settings.patch_browser({'cookies': 'secret'})
        assert settings.read_browser() == BrowserSettings().model_dump()
        first = settings.sections()
        first[0]['title'] = 'mutated'
        assert settings.sections()[0]['title'] != 'mutated'
    finally:
        repo.db.close()


def test_v2_migration_backs_up_wal_data_before_v4_and_preserves_platforms(tmp_path):
    path = tmp_path / 'index.sqlite3'
    with sqlite3.connect(path) as old:
        old.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE tasks(id TEXT PRIMARY KEY,state TEXT,config TEXT,created REAL,updated REAL,session_id TEXT,error TEXT);
            CREATE TABLE platforms(id TEXT PRIMARY KEY,payload TEXT);
            PRAGMA user_version=2;
        ''')
        old.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?)', ('a' * 32, 'succeeded', '{}', 0, 0, None, ''))
        old.execute('INSERT INTO platforms VALUES(?,?)', ('custom-fixture', '{"owner":"platform-registry"}'))
        old.commit()
        # Keep the old connection open, so backup must include committed WAL data.
        repo = Repository(tmp_path)
        try:
            assert repo.db.execute('PRAGMA user_version').fetchone()[0] == 4
            assert repo.task('a' * 32)['state'] == 'succeeded'
            assert json.loads(repo.db.execute('SELECT payload FROM platforms').fetchone()[0])['owner'] == 'platform-registry'
            SettingsRegistry(repo).patch_browser({'default_channel': 'msedge'})
        finally:
            repo.db.close()
    backups = list((tmp_path / 'backups').glob('index-before-v4-*.sqlite3'))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 2
        assert backup.execute('SELECT state FROM tasks').fetchone()[0] == 'succeeded'
        assert backup.execute('SELECT id FROM platforms').fetchone()[0] == 'custom-fixture'
        assert backup.execute("SELECT count(*) FROM sqlite_master WHERE name='settings'").fetchone()[0] == 0
    reopened = Repository(tmp_path)
    try:
        assert SettingsRegistry(reopened).read_browser()['default_channel'] == 'msedge'
        assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    finally:
        reopened.db.close()


def test_future_schema_is_not_silently_downgraded(tmp_path):
    path = tmp_path / 'index.sqlite3'
    with sqlite3.connect(path) as future:
        future.execute('PRAGMA user_version=5')
    with pytest.raises(RuntimeError, match='版本'):
        Repository(tmp_path)
    with sqlite3.connect(path) as untouched:
        assert untouched.execute('PRAGMA user_version').fetchone()[0] == 5
        assert untouched.execute("SELECT count(*) FROM sqlite_master WHERE name='settings'").fetchone()[0] == 0
