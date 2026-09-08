import asyncio
import csv
from fastapi import APIRouter, HTTPException, Query, Header
from .models import WorkflowPlan
from .legacy_models import Control
from .rules import DEFINITIONS, inspect_plan, validate, inspect_source
from .engine import create_run, run_view
from mediacrawler.workbench.results.artifacts import artifact_rows, artifact_path, document_preview, file_response
from mediacrawler.workbench.settings.defaults import resolve


def create_workflow_router(provider):
    router=APIRouter()

    def task(task_id):
        try:return provider().repo.task(task_id)
        except (KeyError,ValueError):raise HTTPException(404,'运行不存在')

    @router.get('/task-types')
    async def definitions(): return [d.model_dump() for d in DEFINITIONS]

    @router.post('/plans/validate')
    async def check(plan: WorkflowPlan):
        try:
            platform=provider().platforms.get(plan.platform)
            result=inspect_plan(plan,platform,inspect_source(provider(),plan))
            result['defaults']=resolve(provider().repo,platform,{})
            return result
        except ValueError as exc:raise HTTPException(422,str(exc))

    @router.get('/plans')
    async def plans():return provider().repo.plans()

    @router.post('/plans')
    async def save(plan: WorkflowPlan):
        try:
            validate(plan,provider().platforms.get(plan.platform),inspect_source(provider(),plan))
            return provider().repo.save_plan(plan.model_dump())
        except ValueError as exc:raise HTTPException(422,str(exc))

    @router.put('/plans/{plan_id}')
    async def update(plan_id: str, plan: WorkflowPlan):
        if not any(p['id']==plan_id for p in provider().repo.plans()):raise HTTPException(404,'方案不存在')
        try:
            validate(plan,provider().platforms.get(plan.platform),inspect_source(provider(),plan))
            return provider().repo.save_plan(plan.model_dump(),plan_id)
        except ValueError as exc:raise HTTPException(422,str(exc))

    @router.get('/runs')
    async def runs():return [run_view(provider().repo,t) for t in provider().repo.tasks()]

    @router.post('/runs',status_code=201)
    async def start(plan: WorkflowPlan, submission_key: str | None=Header(None,alias="Idempotency-Key",max_length=64)):
        try:return run_view(provider().repo,create_run(provider(),plan,submission_key=submission_key))
        except (KeyError,ValueError,OSError) as exc:raise HTTPException(409,str(exc))

    @router.get('/runs/{task_id}')
    async def run(task_id: str):return run_view(provider().repo,task(task_id))

    @router.post('/runs/{task_id}/control')
    async def control(task_id: str, value: Control):
        task(task_id)
        try: return run_view(provider().repo, await provider().control(task_id,value.action))
        except ValueError as exc: raise HTTPException(409,str(exc))

    @router.get('/runs/{task_id}/artifacts')
    async def artifacts(task_id: str):
        task(task_id)
        return {'files':artifact_rows(provider().repo,task_id),'records':provider().repo.results(task_id)['records'],'steps':{s['id']:s['name'] for s in run_view(provider().repo,task(task_id))['steps']}}

    @router.get('/runs/{task_id}/artifacts/{artifact_id}/file')
    async def file(task_id: str, artifact_id: str, download: bool=False, byte_range: str | None=Header(None,alias="Range")):
        task(task_id)
        try:path=artifact_path(provider().repo,task_id,artifact_id)
        except ValueError as exc:raise HTTPException(404,str(exc))
        return file_response(path,download,byte_range)

    @router.get('/runs/{task_id}/artifacts/{artifact_id}/preview')
    async def preview(task_id: str,artifact_id: str,offset: int=Query(0,ge=0,le=100000000),limit: int=Query(100,ge=1,le=200)):
        task(task_id)
        try:
            path=artifact_path(provider().repo,task_id,artifact_id)
            return await asyncio.to_thread(document_preview,path,offset,limit)
        except (ValueError,OSError,csv.Error) as exc:raise HTTPException(422,str(exc))

    return router
