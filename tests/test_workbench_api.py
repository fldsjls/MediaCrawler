"""Local API boundaries with the real repository and no browser/server processes."""
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from mediacrawler.api.main import local_access
from mediacrawler.api.routers import crawler as legacy_router
from mediacrawler.api.services.crawler_manager import CrawlerManager
from mediacrawler.workbench import router as workbench_router
from mediacrawler.workbench.compat import LegacyTaskFacade
from mediacrawler.workbench.service import Workbench


@pytest.fixture
def local_api(tmp_path, monkeypatch):
    """Own SQLite on the ASGI thread; deliberately do not start the scheduler."""
    state = SimpleNamespace()

    @asynccontextmanager
    async def lifespan(_app):
        state.service = Workbench(tmp_path / 'workbench')
        monkeypatch.setattr(workbench_router, 'service', state.service)
        yield
        await state.service.close()

    app = FastAPI(lifespan=lifespan)
    app.middleware('http')(local_access)
    app.include_router(workbench_router.router, prefix='/api')
    app.include_router(legacy_router.router, prefix='/api')
    monkeypatch.setattr(legacy_router, 'crawler_manager', LegacyTaskFacade())
    state.old_start = AsyncMock(side_effect=AssertionError('Legacy CrawlerManager must not run'))
    monkeypatch.setattr(CrawlerManager, 'start', state.old_start)
    with TestClient(app, base_url='http://127.0.0.1:8080') as client:
        state.client = client
        state.call = client.portal.call
        yield state


def create_task(api, target='BV-local-fixture'):
    response = api.client.post('/api/tasks', json={
        'platform': 'bili', 'mode': 'detail', 'target': target,
        'comments': False, 'media': False,
    })
    assert response.status_code == 201, response.text
    return response.json()['id']


@pytest.mark.parametrize(('host', 'origin'), [
    ('127.0.0.1:8080', 'http://127.0.0.1:8080'),
    ('localhost:8080', 'http://localhost:8080'),
    ('[::1]:8080', 'http://[::1]:8080'),
    ('127.0.0.1:8080', 'http://localhost:5173'),
    ('127.0.0.1:8080', None),
])
def test_local_host_and_origin_are_accepted(local_api, host, origin):
    headers = {'host': host}
    if origin is not None:
        headers['origin'] = origin
    response = local_api.client.get('/api/platforms', headers=headers)
    assert response.status_code == 200
    assert any(platform['id'] == 'bili' for platform in response.json())


@pytest.mark.parametrize(('host', 'origin'), [
    ('evil.example', 'http://127.0.0.1:8080'),
    ('127.0.0.1.evil.example', 'http://127.0.0.1:8080'),
    ('192.168.1.20:8080', None),
    ('127.0.0.1:8080', 'https://evil.example'),
    ('127.0.0.1:8080', 'null'),
])
def test_foreign_host_or_origin_cannot_create_tasks(local_api, host, origin):
    headers = {'host': host}
    if origin is not None:
        headers['origin'] = origin
    response = local_api.client.post('/api/tasks', headers=headers, json={
        'platform': 'bili', 'target': 'BV-blocked',
    })
    assert response.status_code == 403
    assert local_api.call(local_api.service.repo.tasks) == []


class SessionFixture:
    id = 'session-fixture'
    token = 'fixture-private-token'

    def __init__(self):
        self.manual = False
        self.controller = None
        self.received = []

    def snapshot(self):
        return {'id': self.id, 'manual': self.manual}

    async def input(self, message, owner):
        self.received.append((message, owner))

    async def close(self):
        pass


def register_session(api):
    session = SessionFixture()
    api.call(api.service.sessions.items.__setitem__, session.id, session)
    return session


def test_platform_management_declares_categories_and_templates(local_api):
    client = local_api.client
    assert {'video', 'books', 'shopping'} <= {t['id'] for t in client.get('/api/platform-types').json()}
    assert {t['id'] for t in client.get('/api/platform-templates').json()} == {'video_capture', 'preview_only'}
    definition = dict(name='书籍测试站', url='http://127.0.0.1:8123', category='books', template='preview_only')
    response = client.post('/api/platforms', json=definition)
    assert response.status_code == 201
    platform = response.json()
    assert not platform['collect'] and platform['enabled']
    assert client.post('/api/tasks', json={'platform': platform['id'], 'target': definition['url']}).status_code == 409
    response = client.put('/api/platforms/' + platform['id'], json={**definition, 'name': '已改名'})
    assert response.json()['name'] == '已改名'
    assert client.delete('/api/platforms/' + platform['id']).status_code == 200
    assert platform['id'] not in {p['id'] for p in client.get('/api/platforms').json()}
    assert platform['id'] in {p['id'] for p in client.get('/api/platforms?include_disabled=true').json()}
    assert client.delete('/api/platforms/bili').status_code == 409
    assert client.post('/api/platforms', json={**definition, 'template_config': {'script': 'x'}}).status_code == 422


def test_passive_resource_channel_does_not_create_task_or_leak_credentials(local_api):
    from mediacrawler.workbench.media.capture import MediaCapture
    session = register_session(local_api)
    session.media = MediaCapture(session.id)
    resource = session.media.add({'url': 'http://127.0.0.1/video.mp4?token=PRIVATE',
        'headers': {'Cookie': 'PRIVATE'}, 'title': 'fixture', 'origin': 'browser'})
    response = local_api.client.get(f'/api/browser-sessions/{session.id}/resources')
    assert response.status_code == 200 and len(response.json()['resources']) == 1
    assert 'PRIVATE' not in response.text
    with local_api.client.websocket_connect(f'/api/browser-sessions/{session.id}/resources?token={session.token}') as socket:
        event = socket.receive_json()
        assert event['type'] == 'resource' and event['resource']['id'] == resource['id']
        assert 'PRIVATE' not in str(event)
    with pytest.raises(WebSocketDisconnect):
        with local_api.client.websocket_connect(f'/api/browser-sessions/{session.id}/resources?token=wrong'):
            pytest.fail('Resource websocket accepted wrong token')
    assert local_api.call(local_api.service.repo.tasks) == []


@pytest.mark.parametrize(('token', 'origin', 'host'), [
    ('wrong-token', 'http://127.0.0.1:8080', '127.0.0.1:8080'),
    ('', 'http://127.0.0.1:8080', '127.0.0.1:8080'),
    ('fixture-private-token', 'https://evil.example', '127.0.0.1:8080'),
    ('fixture-private-token', 'http://127.0.0.1:8080', 'evil.example'),
])
def test_browser_control_requires_session_token_and_local_origin(local_api, token, origin, host):
    session = register_session(local_api)
    with pytest.raises(WebSocketDisconnect) as rejected:
        with local_api.client.websocket_connect(
            f'/api/browser-sessions/{session.id}/control?token={token}',
            headers={'origin': origin, 'host': host},
        ):
            pytest.fail('Untrusted control connection was accepted')
    assert rejected.value.code == 1008
    assert session.received == []
    assert session.controller is None
    assert session.manual is False


def test_valid_control_claim_is_exclusive_and_disconnect_releases_it(local_api):
    session = register_session(local_api)
    url = f'/api/browser-sessions/{session.id}/control?token={session.token}'
    with local_api.client.websocket_connect(url, headers={'origin': 'http://127.0.0.1:8080'}) as socket:
        socket.send_json({'action': 'claim'})
        assert socket.receive_json()['session']['manual'] is True
        with local_api.client.websocket_connect(url) as second:
            second.send_json({'action': 'claim'})
            assert second.receive_json()['type'] == 'error'
        assert session.controller is not None
    # WebSocketTestSession exit waits for the endpoint's finally block.
    assert session.controller is None
    assert session.manual is False


def test_events_remain_task_scoped_and_resume_from_sequence(local_api):
    first = create_task(local_api, 'BV-first')
    second = create_task(local_api, 'BV-second')
    repo = local_api.service.repo
    local_api.call(repo.event, first, 'log', {'message': 'first-secret'})
    local_api.call(repo.event, second, 'log', {'message': 'second-secret'})
    local_api.call(repo.event, first, 'phase', {'phase': 'collecting'})
    first_events = local_api.client.get(f'/api/tasks/{first}/events').json()
    assert first_events
    assert {event['task_id'] for event in first_events} == {first}
    assert all('second-secret' not in str(event) for event in first_events)
    after = first_events[-2]['seq']
    expected = [event for event in first_events if event['seq'] > after]
    assert local_api.client.get(f'/api/tasks/{first}/events', params={'after': after}).json() == expected

    class CapturedSocket:
        headers = {'host': '127.0.0.1:8080', 'origin': 'http://127.0.0.1:8080'}

        def __init__(self):
            self.accepted = False
            self.messages = []

        async def accept(self):
            self.accepted = True

        async def send_json(self, value):
            self.messages.append(value)
            # Bound the real endpoint after the expected batch; no polling sleep.
            if len(self.messages) == len(expected):
                raise WebSocketDisconnect(1000)

    socket = CapturedSocket()
    local_api.call(workbench_router.event_socket, socket, first, after)
    assert socket.accepted
    assert socket.messages == expected
    assert local_api.client.get('/api/tasks/aaaaaaaa/events').status_code == 404


def test_task_file_download_cannot_escape_its_directory(local_api, tmp_path):
    first = create_task(local_api)
    second = create_task(local_api, 'BV-other')
    root = local_api.service.repo.directory(first)
    root.joinpath('results.jsonl').write_text('{"title":"allowed"}\n', encoding='utf-8')
    outside = tmp_path / 'outside-secret.txt'
    outside.write_text('not-public', encoding='utf-8')
    local_api.service.repo.directory(second).joinpath('private.txt').write_text('other-task', encoding='utf-8')
    response = local_api.client.get(f'/api/tasks/{first}/file', params={'path': 'results.jsonl'})
    assert response.status_code == 200
    assert 'allowed' in response.text
    for path in ('../../index.sqlite3', f'../{second}/private.txt', str(outside), '..\\..\\index.sqlite3'):
        response = local_api.client.get(f'/api/tasks/{first}/file', params={'path': path})
        assert response.status_code == 404, path
        assert 'not-public' not in response.text
        assert 'other-task' not in response.text


def test_legacy_http_uses_the_same_workbench_queue_and_history(local_api):
    modern_id = create_task(local_api, 'BV-modern')
    response = local_api.client.post('/api/crawler/start', json={
        'platform': 'bili', 'crawler_type': 'detail', 'login_type': 'cookie',
        'specified_ids': 'BV-legacy', 'cookies': 'SESSDATA=private-fixture',
        'max_notes_count': 3, 'max_comments_count': 7, 'enable_comments': True,
        'save_option': 'jsonl',
    })
    assert response.status_code == 200, response.text
    tasks = local_api.client.get('/api/tasks').json()
    assert len(tasks) == 2
    legacy_task = next(task for task in tasks if task['id'] != modern_id)
    config = legacy_task['config']
    assert config['target'] == 'BV-legacy'
    assert config['mode'] == 'detail'
    assert (config['max_items'], config['max_comments']) == (3, 7)
    assert config['comments'] is True
    assert config['cookies'] == ''
    assert local_api.call(local_api.service.queue.qsize) == 2
    assert all(run.process is None for run in local_api.service.pending.values())
    local_api.call(local_api.service.repo.event, legacy_task['id'], 'log', {'level': 'info', 'message': 'same-history'})
    assert local_api.client.get('/api/crawler/logs').json()['logs'][0]['message'] == 'same-history'
    assert local_api.client.get('/api/crawler/status').json()['status'] == 'running'
    assert local_api.client.post('/api/crawler/stop').status_code == 200
    assert local_api.client.get(f'/api/tasks/{legacy_task["id"]}').json()['state'] == 'cancelled'
    assert local_api.client.get(f'/api/tasks/{modern_id}').json()['state'] == 'queued'
    local_api.old_start.assert_not_called()
