import asyncio
import secrets
from typing import Literal
from urllib.parse import urlparse
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .models import Control, PLATFORMS, SessionConfig, TaskConfig, TERMINAL
from .service import Workbench
from .platforms.catalog import PLATFORM_TYPES, TEMPLATES
from .platforms.registry import PlatformDefinition
from .settings_router import create_settings_router

router = APIRouter()
service: Workbench | None = None
router.include_router(create_settings_router(lambda: service.repo))
ALLOWED_ORIGINS = {f'http://{host}:{port}' for host in ('localhost', '127.0.0.1', '[::1]') for port in (8080, 5173)}

def allowed(headers):
    host = urlparse('http://' + headers.get('host', '')).hostname
    return host in ('localhost', '127.0.0.1', '::1', 'testserver') and (
        not headers.get('origin') or headers['origin'] in ALLOWED_ORIGINS)

async def startup():
    global service
    import logging
    import re
    class SessionTokenFilter(logging.Filter):
        def filter(self, record):
            def redact(value):
                return re.sub(r'([?&]token=)[^\s\"\']+', r'\1[redacted]', value) if isinstance(value, str) else value
            record.msg = redact(record.msg)
            if isinstance(record.args, tuple):
                record.args = tuple(redact(value) for value in record.args)
            return True
    for name in ('uvicorn.error', 'uvicorn.access'):
        logging.getLogger(name).addFilter(SessionTokenFilter())
    service = Workbench()
    await service.start()

async def shutdown():
    if service:
        await service.close()

def task(task_id):
    try:
        return service.repo.task(task_id)
    except (KeyError, ValueError):
        raise HTTPException(404, '任务不存在')

def session(session_id):
    value = service.sessions.items.get(session_id)
    if value is None:
        raise HTTPException(404, '浏览器会话不存在')
    return value


def session_identity(session_id, token):
    value = session(session_id)
    if not token or not secrets.compare_digest(value.token, token):
        raise HTTPException(403, '浏览器会话身份无效')
    return value


class PresentationConfig(BaseModel):
    token: str
    preference: Literal['auto', 'realtime', 'snapshot']


@router.patch('/browser-sessions/{session_id}/presentation')
async def presentation(session_id: str, config: PresentationConfig):
    value = session_identity(session_id, config.token)
    value.presentation = config.preference
    return value.snapshot()


class RTCOffer(BaseModel):
    token: str
    type: Literal['offer']
    sdp: str = Field(min_length=1, max_length=100000)


@router.post('/browser-sessions/{session_id}/rtc')
async def rtc_offer(session_id: str, config: RTCOffer):
    value = session_identity(session_id, config.token)
    try:
        return await value.rtc.offer(config.sdp, config.type)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc).splitlines()[0])
    except Exception:
        raise HTTPException(409, '实时预览协商失败，请重试或使用低刷新截图')


@router.delete('/browser-sessions/{session_id}/rtc/{peer_id}')
async def rtc_close(session_id: str, peer_id: str, request: Request):
    token = request.headers.get('authorization', '').removeprefix('Bearer ')
    value = session_identity(session_id, token)
    await value.rtc.close_peer(peer_id)
    return {'closed': True}

@router.get('/platforms')
async def platforms(include_disabled: bool = False):
    return service.platforms.list(include_disabled)

@router.get('/platform-types')
async def platform_types():
    return PLATFORM_TYPES

@router.get('/platform-templates')
async def platform_templates():
    return TEMPLATES

@router.post('/platforms', status_code=201)
async def create_platform(definition: PlatformDefinition):
    return service.platforms.save(definition)

@router.put('/platforms/{platform_id}')
async def update_platform(platform_id: str, definition: PlatformDefinition):
    if service.repo.platform_in_use(platform_id):
        raise HTTPException(409, '平台正在被任务使用，请在任务结束后修改')
    try:
        return service.platforms.save(definition, platform_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

@router.delete('/platforms/{platform_id}')
async def archive_platform(platform_id: str):
    if service.repo.platform_in_use(platform_id):
        raise HTTPException(409, '平台正在被任务使用，请先结束任务')
    try:
        return service.platforms.archive(platform_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

@router.get('/tasks')
async def tasks():
    return service.repo.tasks()

@router.post('/tasks', status_code=201)
async def create_task(config: TaskConfig):
    try:
        return service.create(config)
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc))

@router.get('/tasks/{task_id}')
async def get_task(task_id: str):
    return task(task_id)

@router.post('/tasks/{task_id}/control')
async def control(task_id: str, command: Control):
    task(task_id)
    try:
        return await service.control(task_id, command.action)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

@router.get('/tasks/{task_id}/results')
async def results(task_id: str):
    task(task_id)
    result = service.repo.results(task_id)
    for item in result['files']:
        for private in ('headers', 'url', 'streams', 'segments'):
            item.pop(private, None)
    result['exports'] = [p.name for p in service.repo.directory(task_id).glob('results.*') if p.is_file()]
    return result

class DownloadSelection(BaseModel):
    session_id: str
    resource_ids: list[str] = Field(min_length=1, max_length=10000)

@router.post('/tasks/{task_id}/downloads')
async def add_downloads(task_id: str, selection: DownloadSelection):
    task(task_id)
    try:
        return await service.add_downloads(task_id, selection.session_id, selection.resource_ids)
    except ValueError as exc:
        raise HTTPException(409, str(exc))

@router.post('/tasks/{task_id}/export')
async def export(task_id: str):
    task(task_id)
    path = service.export(task_id)
    return {'path': path.name}

@router.get('/tasks/{task_id}/file')
async def file(task_id: str, path: str):
    task(task_id)
    root = service.repo.directory(task_id).resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise HTTPException(404, '文件不存在')
    return FileResponse(candidate, filename=candidate.name)

@router.get('/tasks/{task_id}/events')
async def events(task_id: str, after: int = 0):
    task(task_id)
    return service.repo.events(task_id, max(0, after))

@router.websocket('/tasks/{task_id}/events')
async def event_socket(websocket: WebSocket, task_id: str, after: int = 0):
    if not allowed(websocket.headers):
        await websocket.close(code=1008)
        return
    try:
        service.repo.task(task_id)
    except KeyError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    try:
        while True:
            for event in service.repo.events(task_id, after):
                await asyncio.wait_for(websocket.send_json(event), 5)
                after = event['seq']
            await asyncio.sleep(.25)
    except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
        pass

@router.get('/browser-sessions')
async def sessions():
    return [s.snapshot() for s in service.sessions.items.values()]

@router.post('/browser-sessions', status_code=201)
async def create_session(config: SessionConfig):
    try:
        return (await service.sessions.create(config)).snapshot()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc))

@router.get('/browser-sessions/{session_id}')
async def get_session(session_id: str):
    return session(session_id).snapshot()

@router.get('/browser-sessions/{session_id}/resources')
async def session_resources(session_id: str, after: int = 0):
    value = session(session_id)
    return {'resources': value.media.list(max(after, 0)), 'seq': value.media.seq}

@router.delete('/browser-sessions/{session_id}')
async def close_session(session_id: str):
    value = session(session_id)
    if service.repo.session_owner(session_id):
        raise HTTPException(409, '会话正在被任务使用，请先取消任务')
    cleanup = asyncio.create_task(value.close())
    cleanup.add_done_callback(lambda _: service.sessions.items.pop(session_id, None))
    await asyncio.shield(cleanup)
    return {'closed': True}

async def authenticate(websocket, session_id):
    value = service.sessions.items.get(session_id)
    token = websocket.query_params.get('token', '')
    if not value or not allowed(websocket.headers) or not secrets.compare_digest(value.token, token):
        await websocket.close(code=1008)
        return None
    await websocket.accept()
    return value

@router.websocket('/browser-sessions/{session_id}/resources')
async def resource_socket(websocket: WebSocket, session_id: str, after: int = 0):
    value = await authenticate(websocket, session_id)
    if not value:
        return
    async def send():
        cursor = max(after, 0)
        while session_id in service.sessions.items:
            for event in value.media.events(cursor):
                await asyncio.wait_for(websocket.send_json(event), 5)
                cursor = event['seq']
            await asyncio.sleep(.25)
    async def receive():
        while True:
            await websocket.receive_text()
    sender, receiver = asyncio.create_task(send()), asyncio.create_task(receive())
    try:
        await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
    finally:
        sender.cancel()
        receiver.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)

@router.websocket('/browser-sessions/{session_id}/frames')
async def frames(websocket: WebSocket, session_id: str):
    value = await authenticate(websocket, session_id)
    if not value:
        return
    sender = asyncio.create_task(value.frames(websocket))
    async def receive():
        while True:
            await websocket.receive_text()
    receiver = asyncio.create_task(receive())
    try:
        await asyncio.wait([sender, receiver], return_when=asyncio.FIRST_COMPLETED)
    finally:
        sender.cancel()
        receiver.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)

@router.websocket('/browser-sessions/{session_id}/control')
async def browser_control(websocket: WebSocket, session_id: str):
    value = await authenticate(websocket, session_id)
    if not value:
        return
    owner = secrets.token_hex(12)
    try:
        while True:
            message = await websocket.receive_json()
            try:
                if message.get('action') == 'select':
                    await value.select(message['page_id'])
                elif message.get('action') == 'claim':
                    if value.controller not in (None, owner):
                        raise ValueError('此会话正由另一个窗口接管')
                    value.controller = owner
                    active = service.repo.session_owner(session_id)
                    if active:
                        await service.control(active, 'takeover')
                    else:
                        value.manual = True
                else:
                    await value.input(message, owner)
                await websocket.send_json({'type': 'ack', 'session': value.snapshot()})
            except Exception as exc:
                await websocket.send_json({'type': 'error', 'message': str(exc)})
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if value.controller == owner:
            value.controller = None
            value.manual = False
            # It is already paused or waiting for login; reconnect never resumes automation.

class ImportConfig(BaseModel):
    source: str
    kind: str = 'data'
    platform: str = 'meishiwang'
    channel: str = 'chromium'

@router.post('/imports')
async def import_data(config: ImportConfig):
    from .migration import import_files
    try:
        service.platforms.get(config.platform)
        known = {p['id'] for p in service.platforms.list(True)} | {'generic'}
        path = await asyncio.to_thread(import_files, service.repo.root, config.model_dump(), bool(service.sessions.items), known)
        return {'destination': str(path)}
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc))
