"""Compatibility facade: old HTTP calls enqueue the same workbench tasks."""
from datetime import datetime

from api.schemas import LogEntry
from .models import TaskConfig, TERMINAL

class LegacyTaskFacade:
    def __init__(self):
        self.task_id = None

    def service(self):
        from .router import service
        if service is None:
            raise RuntimeError('工作台尚未启动')
        return service

    @property
    def process(self):
        run = self.service().pending.get(self.task_id)
        return run.process if run else None

    async def start(self, request):
        service = self.service()
        if self.task_id and service.repo.task(self.task_id)['state'] not in TERMINAL:
            return False
        mode = request.crawler_type.value
        config = TaskConfig(platform=request.platform.value, mode=mode,
            target={'search': request.keywords, 'detail': request.specified_ids, 'creator': request.creator_ids}[mode],
            max_items=request.max_notes_count or 15, max_comments=request.max_comments_count or 20,
            comments=request.enable_comments, subcomments=request.enable_sub_comments,
            login=request.login_type.value, cookies=request.cookies, output=request.save_option.value,
            start=request.start_page)
        self.task_id = service.create(config)['id']
        return True

    async def stop(self):
        service = self.service()
        if not self.task_id or service.repo.task(self.task_id)['state'] in TERMINAL:
            return False
        await service.control(self.task_id, 'cancel')
        return True

    def get_status(self):
        if not self.task_id:
            return {'status': 'idle'}
        task = self.service().repo.task(self.task_id)
        state = task['state']
        return dict(status='stopping' if state == 'cancelling' else 'error' if state in ('failed', 'partial', 'interrupted') else 'idle' if state in TERMINAL else 'running',
                    platform=task['config']['platform'], crawler_type=task['config']['mode'],
                    started_at=datetime.fromtimestamp(task['created']).isoformat(), error_message=task['error'] or None)

    @property
    def logs(self):
        if not self.task_id:
            return []
        rows = self.service().repo.db.execute("SELECT seq,payload,created FROM events WHERE task_id=? AND type='log' ORDER BY seq DESC LIMIT 500", (self.task_id,)).fetchall()
        import json
        entries = []
        for row in reversed(rows):
            payload = json.loads(row['payload'])
            level = payload.get('level', 'info')
            entries.append(LogEntry(id=row['seq'], timestamp=datetime.fromtimestamp(row['created']).strftime('%H:%M:%S'),
                level=level if level in ('info', 'warning', 'error', 'success', 'debug') else 'info', message=payload.get('message', '')))
        return entries

crawler_manager = LegacyTaskFacade()
