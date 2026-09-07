import asyncio
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .browser import BrowserSessions, kill_tree
from .models import TERMINAL, SessionConfig, TaskConfig, web_url
from .repository import Repository
from .platforms import PlatformRegistry
from .settings import SettingsRegistry

PROJECT = Path(__file__).resolve().parents[2]
WORKER = PROJECT / 'workers' / 'browser-capture'

from .media.identity import resource_identity  # compatibility import for existing integrations

class TaskRun:
    def __init__(self, task_id, config, retry=False):
        self.id, self.config, self.retry = task_id, config, retry
        self.process = None
        self.download_process = None
        self.session = None
        self.collecting = True
        self.cancelled = False
        self.paused = False
        self.takeover = False
        self.worker_done = False
        self.download_task = None
        self.download_only = config.operation == 'download'
        self.platform = None

    def send(self, action):
        self.message({'action': action})

    def message(self, payload):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(json.dumps(payload) + '\n')
                self.process.stdin.flush()
            except (OSError, ValueError):
                pass

class Workbench:
    def __init__(self, root=None):
        self.repo = Repository(root or PROJECT / 'data' / 'workbench')
        self.platforms = PlatformRegistry(self.repo)
        self.settings = SettingsRegistry(self.repo)
        self.sessions = BrowserSessions(self.repo.root, platform_lookup=self.platforms.get,
                                        settings_lookup=self.settings.read_browser)
        self.queue = asyncio.Queue()
        self.active = None
        self.scheduler = None
        self.pending = {}

    async def start(self):
        self.scheduler = asyncio.create_task(self.schedule())

    async def close(self):
        if self.active:
            self.active.cancelled = True
            await kill_tree(self.active.process)
            await kill_tree(self.active.download_process)
        if self.scheduler:
            self.scheduler.cancel()
            await asyncio.gather(self.scheduler, return_exceptions=True)
        await self.sessions.close()
        self.repo.db.close()

    def create(self, config: TaskConfig):
        platform = self.platforms.get(config.platform)
        for key, value in platform.get('template_config', {}).items():
            if key in ('selector', 'wait_ms') and key not in config.model_fields_set:
                setattr(config, key, value)
        if not platform['enabled'] and not platform.get('legacy'):
            raise ValueError('此平台已停用')
        if config.mode not in platform['inputs']:
            raise ValueError('平台不支持此输入方式')
        if config.operation == 'collect' and not platform['collect']:
            raise ValueError('此模板仅支持预览，采集能力尚未接入')
        if config.download_video and not platform['video'] or config.download_images and not platform['images']:
            raise ValueError('此模板不支持所选下载内容')
        if not platform['comments']:
            config.comments = config.subcomments = False
        if config.session_id:
            session = self.sessions.items.get(config.session_id)
            if not session or session.config.platform != config.platform:
                raise ValueError('预览会话不存在或与平台不匹配')
            if self.repo.session_owner(session.id):
                raise ValueError('此会话已被任务占用')
        selected = self.selected_resources(config.session_id, config.resource_ids) if config.operation == 'download' else []
        if len(selected) > config.max_downloads:
            raise ValueError('所选视频超过下载数量上限')
        task_id = self.repo.create({**config.model_dump(), 'platform_snapshot': platform})
        run = TaskRun(task_id, config)
        run.platform = platform
        if selected:
            run.session = session
            self.repo.session(task_id, session.id)
            for resource in selected:
                self.enqueue_resource(run, resource, manual=True)
        self.pending[task_id] = run
        self.queue.put_nowait(run)
        return self.repo.task(task_id)

    def selected_resources(self, session_id, resource_ids):
        session = self.sessions.items.get(session_id)
        if not session:
            raise ValueError('浏览器会话已关闭，请重新预览并捕获资源')
        selected = []
        for resource_id in dict.fromkeys(resource_ids):
            try:
                item = session.media.get(resource_id)
            except KeyError:
                item = None
            if not item:
                raise ValueError('资源不属于此浏览器会话或已经失效')
            if item.get('state') == 'unavailable':
                raise ValueError(item.get('error') or '此资源暂不支持下载')
            selected.append(item)
        if not selected:
            raise ValueError('请选择待下载资源')
        return selected

    def enqueue_resource(self, run, resource, manual=False):
        resource = {**resource, 'source': resource.get('source') or run.config.platform}
        if manual:
            page_url = resource.get('page_url') or run.config.target
            record_id = resource.get('parent_id') or 'page:' + hashlib.sha256(page_url.encode()).hexdigest()[:24]
            if not any(r['id'] == record_id for r in self.repo.results(run.id)['records']):
                self.repo.record(run.id, dict(id=record_id, kind='content', source=run.config.platform,
                    title=resource.get('title', '手动选择的视频'), target=page_url,
                    fields={'selection': 'manual', 'video_status': 'available'}))
            # Keep the capture identity stable after the user supplies ownership.
            resource['parent_id'] = record_id
        media_kind = resource.get('kind', 'video')
        if not manual and (not resource.get('parent_id') or
                not (run.config.download_images if media_kind == 'image' else run.config.download_video)):
            return
        public = run.session.media.add(resource)
        self.repo.resource(run.id, public)
        files = self.repo.results(run.id)['files']
        existing = next((f for f in files if f['id'] == public['id']), None)
        if existing and existing['state'] in ('succeeded', 'running', 'pending'):
            return
        if not existing and len(files) >= run.config.max_downloads:
            return
        pending = {**public, 'resource_id': public['id'], 'state': 'pending', 'path': '', 'error': ''}
        self.repo.file(run.id, pending)
        self.resource_state(run, pending)

    def resource_state(self, run, item):
        try:
            private = run.session.media.get(item.get('resource_id', item['id']))
            if private:
                public = run.session.media.add({**private, **{k: item[k] for k in ('state', 'error', 'size') if k in item}})
                self.repo.resource(run.id, public)
        except (KeyError, AttributeError):
            pass

    async def add_downloads(self, task_id, session_id, resource_ids):
        task = self.repo.task(task_id)
        if task.get('session_id') != session_id:
            raise ValueError('请在该任务的浏览器会话中选择资源')
        if task['state'] in ('cancelling', 'cancelled', 'preparing'):
            raise ValueError('当前任务状态不能添加下载，请新建仅下载任务')
        if self.repo.session_owner(session_id, excluding=task_id):
            raise ValueError('此会话已被其他任务占用，请等待任务结束')
        selected = self.selected_resources(session_id, resource_ids)
        files = self.repo.results(task_id)['files']
        existing_ids = {f['id'] for f in files}
        if len(files) + sum(r['id'] not in existing_ids for r in selected) > task['config']['max_downloads']:
            raise ValueError('所选资源超过此任务剩余下载额度，请减少选择或新建任务')
        run = self.pending.get(task_id)
        requeue = task['state'] in TERMINAL
        if requeue:
            run = TaskRun(task_id, TaskConfig(**task['config']))
            run.download_only = True
            run.platform = self.platforms.get(run.config.platform)
            run.session = self.sessions.items[session_id]
            run.config.session_id = session_id
        elif run is None:
            raise ValueError('任务不可用')
        if run.session is None:
            run.session = self.sessions.items[session_id]
        for resource in selected:
            self.enqueue_resource(run, resource, manual=True)
        if requeue and any(f['state'] == 'pending' for f in self.repo.results(task_id)['files']):
            self.pending[task_id] = run
            self.repo.state(task_id, 'queued')
            self.queue.put_nowait(run)
        return self.repo.task(task_id)

    async def schedule(self):
        while True:
            run = await self.queue.get()
            try:
                if self.repo.task(run.id)['state'] == 'cancelled':
                    continue
                self.active = run
                await self.execute(run)
            finally:
                if self.pending.get(run.id) is run:
                    self.pending.pop(run.id, None)
                self.active = None
                self.queue.task_done()

    async def prepare_session(self, run):
        session = self.sessions.items.get(run.config.session_id)
        if session and (not session.browser or not session.browser.is_connected()):
            session = None
        for old in list(self.sessions.items.values()):
            reserved = self.repo.session_owner(old.id)
            if old is not session and old.task_id and not reserved:
                await old.close()
                self.sessions.items.pop(old.id, None)
        if session is None:
            # An unassigned preview for this platform is reusable even if the page reloaded.
            session = next((s for s in self.sessions.items.values() if s.config.platform == run.config.platform
                            and not s.task_id and not self.repo.session_owner(s.id, excluding=run.id)), None)
        if session is None:
            target = run.config.target.split(',')[0].strip()
            url = target if target.startswith(('https://', 'http://')) and run.config.mode != 'search' else ''
            session = await self.sessions.create(SessionConfig(platform=run.config.platform, url=url))
        run.session = session
        session.task_id = run.id
        session.finished = False
        async with session.control_lock:
            session.manual = False
            session.controller = None
        self.repo.session(run.id, session.id)

    async def execute(self, run):
        self.repo.state(run.id, 'preparing')
        try:
            await self.prepare_session(run)
            if run.cancelled:
                return
            run.download_task = asyncio.create_task(self.downloads(run))
            results = self.repo.results(run.id)
            file_only = run.retry and any(f['state'] == 'failed' for f in results['files']) and not any(
                r['kind'] == 'failure' for r in results['records'])
            if file_only:
                file_only = all(f.get('url') or self._private_resource(run, f) for f in results['files'] if f['state'] != 'succeeded')
            if run.retry:
                for item in results['files']:
                    if item['state'] in ('failed', 'cancelled', 'running'):
                        self.repo.file(run.id, {**item, 'state': 'pending', 'error': ''})
            if not file_only and not run.download_only:
                await self.collect(run)
            else:
                self.repo.state(run.id, 'running')
                run.worker_done = True
            run.collecting = False
            self.repo.event(run.id, 'phase', {'phase': 'downloading', 'message': '采集阶段结束，等待已登记文件下载完成'})
            if run.paused and not run.cancelled:
                self.repo.state(run.id, 'paused')
                run.session.manual = run.takeover
            if run.download_task:
                await run.download_task
            while run.paused and not run.cancelled:
                await asyncio.sleep(.1)
            expired = any(f['state'] == 'failed' and re.search(r'HTTP (401|403|410)\b', f.get('error', ''))
                          for f in self.repo.results(run.id)['files'])
            if expired and not run.cancelled and not run.download_only:
                # One bounded adapter pass refreshes short-lived URLs only after the
                # original collector has stopped. Successful identities remain skipped.
                self.repo.event(run.id, 'phase', {'phase': 'refreshing', 'message': '媒体地址失效，重新解析一次；已成功文件保持不变'})
                run.collecting, run.retry, run.worker_done = True, True, False
                run.download_task = asyncio.create_task(self.downloads(run))
                await self.collect(run)
                run.collecting = False
                await run.download_task
                while run.paused and not run.cancelled:
                    await asyncio.sleep(.1)
            if not run.cancelled:
                self.export(run.id)
                results = self.repo.results(run.id)
                content = [r for r in results['records'] if r['kind'] in ('content', 'creator')]
                errors = [r for r in results['records'] if r['kind'] == 'failure']
                failed = [f for f in results['files'] if f['state'] == 'failed']
                video_records = [r for r in content if (r.get('fields') or {}).get('video_status') != 'none']
                missing_media = run.config.download_video and run.config.max_downloads > 0 and bool(video_records) and not any(f.get('kind', 'video') == 'video' for f in results['files'])
                if not content:
                    state, error = 'failed', '没有采集到内容，请检查目标、登录和运行日志'
                elif missing_media:
                    state, error = 'partial', '内容已保存，但没有发现所选的可下载媒体，请检查目标与运行日志'
                elif errors or failed or not run.worker_done:
                    state, error = 'partial', '部分内容或文件失败，可在结果中检查并重试'
                else:
                    state, error = 'succeeded', ''
                self.repo.state(run.id, state, error)
        except asyncio.CancelledError:
            if not run.cancelled:
                raise
        except Exception as exc:
            self.repo.event(run.id, 'log', {'level': 'error', 'message': str(exc)})
            if not run.cancelled:
                self.repo.state(run.id, 'partial' if self.repo.task(run.id)['counts']['content'] else 'failed', str(exc))
        finally:
            run.collecting = False
            if run.download_task and not run.download_task.done():
                run.download_task.cancel()
                await asyncio.gather(run.download_task, return_exceptions=True)
            await kill_tree(run.process)
            await kill_tree(run.download_process)
            if run.cancelled:
                for item in self.repo.results(run.id)['files']:
                    if item['state'] in ('pending', 'running'):
                        self.repo.file(run.id, {**item, 'state': 'cancelled'})
                self.repo.state(run.id, 'cancelled')
            if run.session:
                run.session.finished = True
                run.session.manual = True
            run.config.cookies = ''

    async def collect(self, run):
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8', 'PYTHONUNBUFFERED': '1',
               'MC_TASK_CONFIG': run.config.model_dump_json(), 'MC_TASK_DIR': str(self.repo.directory(run.id)),
               'MC_BROWSER_ENDPOINT': run.session.endpoint}
        env['MC_EXISTING_RECORDS'] = json.dumps([r['id'] for r in self.repo.results(run.id)['records'] if r['kind'] != 'failure'])
        definition = run.platform or self.platforms.get(run.config.platform)
        env['MC_PLATFORM_DEFINITION'] = json.dumps(definition, ensure_ascii=False)
        node = definition['template'] in ('course', 'video_capture') and definition['builtin']
        command = ['node', '--import', 'tsx', 'src/workbench/worker.ts'] if node else [sys.executable, '-m',
            'api.workbench.template_worker' if not definition['builtin'] else 'api.workbench.platform_worker']
        run.process = subprocess.Popen(command, cwd=WORKER if node else PROJECT, env=env,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', errors='replace', bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        if run.retry:
            self.repo.db.execute("DELETE FROM records WHERE task_id=? AND kind='failure'", (run.id,))
            self.repo.db.commit()
        async def read(stream, structured):
            while True:
                line = await asyncio.to_thread(stream.readline)
                if not line:
                    break
                if structured:
                    try:
                        message = json.loads(line)
                        if isinstance(message, dict) and 'type' in message:
                            self.worker_event(run, message)
                            continue
                    except ValueError:
                        pass
                text = line.strip()
                text = text.replace(run.session.endpoint, '[browser session]')
                if run.config.cookies:
                    text = text.replace(run.config.cookies, '[cookies]')
                if text:
                    self.repo.event(run.id, 'log', {'level': 'info', 'message': text[:16000]})
        await asyncio.gather(read(run.process.stdout, True), read(run.process.stderr, False))
        returncode = await asyncio.to_thread(run.process.wait)
        if returncode and not run.cancelled:
            self.failure(run, f'采集执行模块退出，代码 {returncode}')

    def failure(self, run, message):
        self.repo.record(run.id, {'id': 'failure:' + hashlib.sha256(message.encode()).hexdigest()[:16],
            'kind': 'failure', 'title': message, 'target': run.config.target})

    def worker_event(self, run, message):
        if isinstance(message.get('message'), str):
            message['message'] = message['message'].replace(run.session.endpoint, '[browser session]')
        kind = message['type']
        if run.cancelled:
            return
        if kind == 'state':
            state = message.get('state')
            if state == 'running' and run.paused:
                run.send('pause')
                return
            if state in ('running', 'paused', 'waiting_login'):
                run.session.manual = state == 'waiting_login' or (state == 'paused' and run.takeover)
                self.repo.state(run.id, state)
        elif kind == 'record':
            self.repo.record(run.id, message['record'])
        elif kind == 'resource':
            resource = message['resource']
            web_url(resource['url'])
            self.enqueue_resource(run, {**resource, 'origin': 'adapter'})
        elif kind == 'failure':
            self.failure(run, message.get('message', '采集失败'))
        elif kind == 'done':
            run.worker_done = True
        elif kind == 'drain':
            async def drained():
                while not run.cancelled:
                    if not any(f['state'] in ('pending', 'running') for f in self.repo.results(run.id)['files']):
                        run.message({'action': 'drained', 'request_id': message['request_id']})
                        return
                    await asyncio.sleep(.1)
            asyncio.create_task(drained())
        if kind in ('log', 'phase', 'failure', 'done', 'record', 'resource'):
            # Do not duplicate signed resource URLs or large platform records into log history.
            payload = {k: v for k, v in message.items() if k != 'type'} if kind not in ('record', 'resource') else {'message': '已登记' + ('内容' if kind == 'record' else '资源')}
            self.repo.event(run.id, kind, payload)

    async def downloads(self, run):
        while not run.cancelled:
            pending = [f for f in self.repo.results(run.id)['files'] if f['state'] == 'pending']
            if run.paused and not run.takeover:
                await asyncio.sleep(.1)
                continue
            if not pending:
                if not run.collecting:
                    return
                await asyncio.sleep(.1)
                continue
            item = pending[0]
            self.repo.file(run.id, {**item, 'state': 'running'})
            self.resource_state(run, {**item, 'state': 'running'})
            try:
                path = await self.download(run, item)
                self.repo.file(run.id, {**item, 'state': 'succeeded', 'path': str(path.relative_to(self.repo.directory(run.id))), 'size': path.stat().st_size, 'error': ''})
                self.resource_state(run, {**item, 'state': 'succeeded', 'size': path.stat().st_size, 'error': ''})
            except asyncio.CancelledError:
                if run.cancelled:
                    return
                raise
            except Exception as exc:
                self.repo.file(run.id, {**item, 'state': 'failed', 'error': str(exc)})
                self.resource_state(run, {**item, 'state': 'failed', 'error': str(exc)})
                self.repo.event(run.id, 'log', {'level': 'error', 'message': f'文件下载失败：{item["title"]}；{exc}'})

    def _private_resource(self, run, item):
        try:
            return run.session.media.get(item.get('resource_id', item['id']))
        except (KeyError, AttributeError):
            return None

    async def download(self, run, item):
        from .media.downloader import download
        resource = self._private_resource(run, item)
        if resource is None:
            if not item.get('url'):
                raise ValueError('浏览器资源已失效，请重新打开来源页面捕获后下载')
            resource = item  # older indexes contain the download URL
        directory = self.repo.directory(run.id) / 'media'
        return await download(run, {**resource, 'id': item['id']}, directory, WORKER / 'tools')

    async def control(self, task_id, action):
        task = self.repo.task(task_id)
        run = self.pending.get(task_id)
        if action == 'retry':
            if task['state'] not in TERMINAL or task['state'] in ('cancelled', 'succeeded'):
                raise ValueError('仅失败、部分成功或中断任务可以重试')
            config = TaskConfig(**task['config'])
            config.session_id = task['session_id']
            if self.repo.session_owner(config.session_id, excluding=task_id):
                raise ValueError('此会话已被其他任务占用，请等待任务结束')
            run = TaskRun(task_id, config, retry=True)
            run.platform = task['config'].get('platform_snapshot') or self.platforms.get(config.platform)
            self.pending[task_id] = run
            self.repo.state(task_id, 'queued')
            self.queue.put_nowait(run)
            return self.repo.task(task_id)
        if task['state'] in TERMINAL or run is None:
            raise ValueError('任务已经结束')
        if action == 'cancel':
            run.cancelled = True
            if self.active is not run:
                for item in self.repo.results(task_id)['files']:
                    if item['state'] in ('pending', 'running'):
                        cancelled = {**item, 'state': 'cancelled'}
                        self.repo.file(task_id, cancelled)
                        self.resource_state(run, cancelled)
                self.repo.state(task_id, 'cancelled')
            else:
                self.repo.state(task_id, 'cancelling')
                await kill_tree(run.process)
                await kill_tree(run.download_process)
            return self.repo.task(task_id)
        if self.active is not run or run.session is None:
            raise ValueError('任务尚未建立会话')
        if action in ('pause', 'takeover'):
            run.paused, run.takeover = True, action == 'takeover'
            self.repo.state(task_id, 'pausing')
            run.send(action)
            if not run.collecting:
                self.repo.state(task_id, 'paused')
                run.session.manual = run.takeover
        elif action == 'resume':
            if task['state'] not in ('paused', 'waiting_login'):
                raise ValueError('请等待暂停确认后再继续')
            async with run.session.control_lock:
                run.session.manual = False
                run.session.controller = None
                run.paused = run.takeover = False
                if run.collecting:
                    run.send('resume')
                else:
                    self.repo.state(task_id, 'running')
        return self.repo.task(task_id)

    def export(self, task_id):
        result = self.repo.results(task_id)
        rows = result['records']
        output = self.repo.task(task_id)['config']['output']
        extension = 'xlsx' if output == 'excel' else output
        path = self.repo.directory(task_id) / f'results.{extension}'
        if output == 'json':
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        elif output == 'jsonl':
            path.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')
        else:
            fields = ['id', 'kind', 'source', 'title', 'parent_id', 'collected_at', 'fields']
            values = [[json.dumps(r.get(k, ''), ensure_ascii=False) if isinstance(r.get(k), (dict, list)) else r.get(k, '') for k in fields] for r in rows]
            if output == 'csv':
                with path.open('w', encoding='utf-8-sig', newline='') as stream:
                    writer = csv.writer(stream)
                    writer.writerow(fields)
                    writer.writerows(values)
            else:
                from openpyxl import Workbook
                workbook = Workbook()
                sheet = workbook.active
                sheet.append(fields)
                for row in values:
                    sheet.append(row)
                for row in sheet:
                    for cell in row:
                        if isinstance(cell.value, str):
                            cell.data_type = 's'
                workbook.save(path)
        self.repo.event(task_id, 'export', {'path': path.name})
        return path
