"""Workflow execution on Workbench's existing queue and worker lifecycle."""
import asyncio
import hashlib
import re
from pathlib import Path
from types import SimpleNamespace
from .models import WorkflowPlan
from .rules import validate, BY_KIND, inspect_source
from .legacy_models import TaskConfig, TERMINAL
from mediacrawler.workbench.settings.defaults import resolve
from mediacrawler.workbench.browser import kill_tree
from mediacrawler.workbench.browser.capture import MediaCapture, classify
from mediacrawler.workbench.downloads.downloader import clean_error


def create_run(service, plan, retry_of=None, snapshot=None, submission_key=None):
    from .service import TaskRun
    if submission_key:
        previous=service.repo.db.execute("SELECT id FROM tasks WHERE json_extract(config,'$.submission_key')=?", (submission_key,)).fetchone()
        if previous:
            task=service.repo.task(previous['id'])
            if task['config'].get('workflow')!=plan.model_dump(): raise ValueError('提交编号已用于另一份方案')
            return task
    platform = (snapshot or {}).get('platform_snapshot') or service.platforms.get(plan.platform)
    validate(plan, platform, inspect_source(service, plan))
    if not any(s.enabled for s in plan.steps): raise ValueError('请添加并启用至少一张卡片')
    if plan.session_id and service.repo.session_owner(plan.session_id): raise ValueError('该浏览器会话正在运行任务')
    selected = service.selected_resources(plan.session_id, plan.resource_ids) if plan.source == 'selection' else []
    if plan.source == 'history': service.repo.task(plan.history_id)
    settings = (snapshot or {}).get('step_settings') or {s.id: resolve(service.repo, platform, s.overrides) for s in plan.steps}
    config = TaskConfig(platform=plan.platform, target=plan.target or platform.get('url') or 'http://localhost/',
                        mode=plan.mode, comments=False, max_downloads=10000, session_id=plan.session_id)
    payload = {**config.model_dump(), 'workflow': plan.model_dump(), 'step_settings': settings,
               'submission_key': submission_key, 'platform_snapshot': platform, 'browser_snapshot': (snapshot or {}).get('browser_snapshot') or service.settings.read_browser(), 'retry_of': retry_of}
    task = service.repo.create(payload)
    run = TaskRun(task, config, retry=bool(retry_of))
    run.workflow, run.step_settings, run.platform, run.selected = plan, settings, platform, selected
    run.retry_of = retry_of
    run.download_settings = {}
    run.browser_settings = payload['browser_snapshot']
    for step in plan.steps:
        service.repo.step(task, dict(id=step.id, kind=step.kind, name=step.name or BY_KIND[step.kind].title,
                                    state='queued' if step.enabled else 'skipped', settings=settings[step.id], error=''))
    if retry_of:
        old = service.repo.results(retry_of)
        for record in old['records']:
            if record['kind'] != 'failure': service.repo.record(task, record)
        for file in old['files']:
            if file['state'] == 'succeeded': service.repo.file(task, {**file, 'source_task_id': file.get('source_task_id') or retry_of})
    service.pending[task] = run
    service.queue.put_nowait(run)
    return service.repo.task(task)


def run_view(repo, task):
    plan = task['config'].get('workflow')
    steps = repo.steps(task['id']) if plan else [dict(id='legacy', name='旧版任务', kind='legacy', state=task['state'], settings={}, error=task['error'])]
    return {**task, 'name': plan['name'] if plan else task['config']['target'], 'steps': steps,
            'retry_of': task['config'].get('retry_of'), 'current_step': next((s['name'] for s in steps if s['state'] in ('running','waiting_login','paused')), ''),
            'steps_completed': sum(s['state'] in ('succeeded','skipped') for s in steps)}


def update(service, run, step, state, error=''):
    value = next(s for s in service.repo.steps(run.id) if s['id'] == step.id)
    service.repo.step(run.id, {**value, 'state': state, 'error': error})
    service.repo.event(run.id, 'step', dict(step_id=step.id, state=state, message=f'{value["name"]}：{state}', error=error))


def file_state(files):
    if not files or not any(f['state'] == 'succeeded' for f in files): return 'failed'
    return 'succeeded' if all(f['state'] == 'succeeded' for f in files) else 'partial'


async def checkpoint(run):
    while run.paused and not run.cancelled: await asyncio.sleep(.1)
    if run.cancelled: raise asyncio.CancelledError()


async def execute(service, run):
    plan, repo = run.workflow, service.repo
    completed = {}
    prior = {s['id']: s for s in repo.steps(run.retry_of)} if run.retry_of else {}
    try:
        repo.state(run.id, 'preparing')
        if plan.source in ('website', 'selection'):
            await service.prepare_session(run)
        else:
            run.session = SimpleNamespace(media=MediaCapture(run.id, plan.platform), context=None, manual=False,
                                          finished=False, control_lock=asyncio.Lock(), controller=None)
        repo.state(run.id, 'running')
        for step in plan.steps:
            if not step.enabled: continue
            await checkpoint(run)
            if completed.get(step.id): continue
            if step.input != 'source' and completed.get(step.input) not in ('succeeded', 'partial'):
                update(service, run, step, 'blocked', '前置步骤没有可用输出'); completed[step.id] = 'blocked'; continue
            if prior.get(step.id, {}).get('state') == 'succeeded' and step.kind not in ('session','discover'):
                update(service, run, step, 'succeeded'); completed[step.id] = 'succeeded'; continue
            run.step_id = step.id
            repo.step_context[run.id] = step.id
            settings = run.step_settings[step.id]
            update(service, run, step, 'running')
            try:
                if step.kind == 'session':
                    page = run.session.page
                    if await page.locator('input[type=password]:visible').count():
                        run.paused, run.collecting = True, False
                        run.session.manual = True
                        repo.state(run.id, 'waiting_login')
                        update(service, run, step, 'waiting_login')
                        await checkpoint(run)
                elif step.kind in ('discover','content','comments'):
                    changes = {k: v for k,v in settings.items() if k in TaskConfig.model_fields}
                    changes.update(comments=step.kind == 'comments', download_video=step.kind == 'discover', download_images=step.kind == 'discover' and bool(run.platform.get('images')))
                    run.config = run.config.model_copy(update=changes)
                    if step.kind == 'comments' and step.input != 'source':
                        rows = [r for r in repo.results(run.id)['records'] if r.get('step_id') == step.input and r['kind'] == 'content']
                        targets = [r.get('target') or r.get('original_id') or r.get('id') for r in rows]
                        if targets: run.config = run.config.model_copy(update={'target': ','.join(targets), 'mode': 'detail'})
                    consumers = [s for s in plan.steps if s.enabled and s.input == step.id and s.kind in ('media','files')]
                    stream = consumers[0] if len(consumers) == 1 and step.kind == 'discover' else None
                    run.discover_only = step.kind == 'discover' and stream is None
                    run.download_step = stream.id if stream else step.id
                    run.download_settings = run.step_settings[stream.id] if stream else settings
                    run.worker_done, run.collecting = False, True
                    before = len([r for r in repo.results(run.id)['records'] if r['kind']=='failure'])
                    if stream:
                        update(service, run, stream, 'running')
                        run.download_task = asyncio.create_task(service.downloads(run))
                    await service.collect(run)
                    run.collecting = False
                    if run.download_task:
                        await run.download_task; run.download_task = None
                    await checkpoint(run)
                    if not run.worker_done: raise ValueError('采集执行器未确认完成')
                    if len([r for r in repo.results(run.id)['records'] if r['kind']=='failure']) > before: raise ValueError('部分目标采集失败')
                    if stream and any(f['state'] == 'failed' and re.search(r'HTTP (401|403|410)\b', f.get('error', '')) for f in repo.results(run.id)['files'] if f.get('step_id') == stream.id):
                        repo.event(run.id, 'phase', {'message': '媒体地址失效，重新解析一次；保留成功产物'})
                        run.collecting, run.retry, run.worker_done = True, True, False
                        run.download_task = asyncio.create_task(service.downloads(run))
                        await service.collect(run)
                        run.collecting = False
                        await run.download_task; run.download_task = None
                    if stream:
                        files = [f for f in repo.results(run.id)['files'] if f.get('step_id') == stream.id]
                        state = file_state(files)
                        update(service, run, stream, state, '' if files else '没有发现可下载资源'); completed[stream.id]=state
                elif step.kind in ('media','files'):
                    run.download_settings, run.download_step, run.discover_only = settings, step.id, False
                    if step.input == 'source' and plan.source == 'direct':
                        kind, format = classify(plan.target) or ('file', 'direct')
                        resources = [dict(url=plan.target, kind=kind, format=format, title=Path(plan.target.split('?')[0]).name or '下载文件')]
                    elif step.input == 'source': resources = run.selected
                    else:
                        rows = repo.results(run.id)['resources']
                        resources = [run.session.media.get(r['id']) for r in rows if r.get('step_id') == step.input or step.input in r.get('step_ids', [])]
                    resources = [r for r in resources if r]
                    if not resources: raise ValueError('没有可下载资源，请重新发现或选择')
                    run.config = run.config.model_copy(update={'max_downloads':10000})
                    for resource in resources: service.enqueue_resource(run, resource, manual=True)
                    run.collecting = False
                    run.download_task = asyncio.create_task(service.downloads(run))
                    await run.download_task; run.download_task = None
                elif step.kind == 'export':
                    from mediacrawler.workbench.results.artifacts import export_step
                    export_step(service, run, step)
                await checkpoint(run)
                files = [f for f in repo.results(run.id)['files'] if f.get('step_id') == step.id]
                state = file_state(files) if step.kind in ('media', 'files') else 'succeeded'
                if step.kind == 'content' and not any(r.get('step_id') == step.id and r['kind'] in ('content','creator') for r in repo.results(run.id)['records']):
                    raise ValueError('没有采集到内容，请检查目标、登录和运行日志')
                update(service, run, step, state); completed[step.id]=state
            except asyncio.CancelledError: raise
            except Exception as exc:
                update(service, run, step, 'failed', clean_error(exc)); completed[step.id]='failed'
        state = 'succeeded' if all(v=='succeeded' for v in completed.values()) else 'partial' if any(v in ('succeeded','partial') for v in completed.values()) else 'failed'
        repo.state(run.id, state)
    except asyncio.CancelledError:
        repo.state(run.id, 'cancelled' if run.cancelled and not getattr(run, 'shutting_down', False) else 'interrupted')
        if not run.cancelled or getattr(run, 'shutting_down', False): raise
    except Exception as exc: repo.state(run.id, 'failed', clean_error(exc))
    finally:
        run.collecting=False
        if run.download_task and not run.download_task.done():
            run.download_task.cancel(); await asyncio.gather(run.download_task, return_exceptions=True)
        await kill_tree(run.process); await kill_tree(run.download_process)
        for s in repo.steps(run.id):
            if s['state'] in ('queued','running','waiting_login','paused'):
                repo.step(run.id,{**s,'state':'cancelled' if run.cancelled and not getattr(run, 'shutting_down', False) else 'interrupted'})
        for f in repo.results(run.id)['files']:
            if f['state'] in ('pending','running'): repo.file(run.id,{**f,'state':'cancelled' if run.cancelled else 'failed'})
        if run.session: run.session.finished, run.session.manual = True, True
        repo.step_context.pop(run.id,None)
