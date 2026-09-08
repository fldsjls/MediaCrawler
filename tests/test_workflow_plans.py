import asyncio
from pathlib import Path
from types import SimpleNamespace
import pytest
from mediacrawler.workbench.workflows.models import WorkflowPlan
from mediacrawler.workbench.workflows.rules import inspect_plan, validate
from mediacrawler.workbench.workflows.service import Workbench
from mediacrawler.workbench.workflows.engine import create_run, run_view
from mediacrawler.workbench.settings.defaults import Defaults, save_defaults
from mediacrawler.workbench.results.artifacts import artifact_rows, artifact_path, document_preview
from mediacrawler.workbench.downloads.engines import select_engine
from mediacrawler.workbench.downloads.downloader import download
from tests.test_workbench_media import media_files, serve_media, TOOLS


def plan(**kw):
    return WorkflowPlan.model_validate(dict(name='验收方案',platform='bili',target='https://www.bilibili.com/video/example',**kw))


def step(id,kind,input='source',**kw):return dict(id=id,kind=kind,input=input,**kw)


def test_next_cards_follow_capabilities_and_dependencies(tmp_path):
    service=Workbench(tmp_path);platform=service.platforms.get('bili')
    p=plan()
    assert [d['id'] for d in inspect_plan(p,platform)['available']]==['session']
    p=plan(steps=[step('login','session'),step('find','discover','login'),step('save','media','find')])
    assert validate(p,platform)['valid']
    p.steps[0].enabled=False
    assert not inspect_plan(p,platform)['valid']
    p.steps[0].enabled=True;p.steps.reverse()
    assert not inspect_plan(p,platform)['valid']
    service.repo.db.close()


def test_unknown_override_and_empty_source_rejected(tmp_path):
    service=Workbench(tmp_path)
    p=plan(steps=[step('login','session',overrides={'cookies':'not-allowed'})])
    assert not inspect_plan(p,service.platforms.get('bili'))['valid']
    p=plan();p.target=''
    with pytest.raises(ValueError):create_run(service,p)
    service.repo.db.close()


@pytest.mark.asyncio
async def test_direct_file_export_and_defaults_snapshot(tmp_path,media_files):
    with serve_media(media_files) as (origin,requests):
        service=Workbench(tmp_path/'workbench');await service.start()
        try:
            p=plan(source='direct',steps=[step('download','files',overrides={'engine':'http'}),step('export','export','download',overrides={'output':'csv'})])
            p.target=origin+'/av.mp4'
            task=create_run(service,p)
            save_defaults(service.repo,{'engine':'n_m3u8dl','output':'excel'})
            await asyncio.wait_for(service.queue.join(),20)
            task=service.repo.task(task['id'])
            assert task['state']=='succeeded', (task,service.repo.events(task['id']))
            assert task['config']['step_settings']['download']['engine']=='http'
            files=artifact_rows(service.repo,task['id']);assert len(files)==2
            video=next(f for f in files if f.get('engine')=='http')
            assert artifact_path(service.repo,task['id'],video['id']).read_bytes()==(media_files/'av.mp4').read_bytes()
            csv=next(f for f in files if f['kind']=='export')
            preview=document_preview(artifact_path(service.repo,task['id'],csv['id']))
            assert preview['type']=='table' and 'engine' in preview['rows'][0] and 'state' in preview['rows'][0]
            assert run_view(service.repo,task)['steps_completed']==2
        finally:await service.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('engine,file',[('http','av.mp4'),('ffmpeg','play.m3u8'),('n_m3u8dl','play.m3u8'),('n_m3u8dl','play.mpd')])
async def test_real_download_engines(tmp_path,media_files,engine,file):
    with serve_media(media_files) as (origin,requests):
        settings=Defaults(engine=engine).model_dump()
        run=SimpleNamespace(cancelled=False,download_process=None,session=None,download_settings=settings)
        result=await asyncio.wait_for(download(run,dict(id='test',url=origin+'/'+file,format='dash' if file.endswith('mpd') else 'hls' if file.endswith('m3u8') else 'direct',title='验收视频'),tmp_path/'output with spaces',TOOLS),40)
        assert result.stat().st_size>0
        assert run.actual_engine==engine
        assert run.download_process is None


def test_explicit_engine_does_not_silently_fallback():
    settings=Defaults(engine='n_m3u8dl',n_m3u8dl_path='missing.exe').model_dump()
    with pytest.raises(ValueError):select_engine(settings,{'format':'hls'})
    with pytest.raises(ValueError):select_engine({**settings,'engine':'http'},{'format':'hls'})


def test_migration_keeps_old_files_and_plans(tmp_path):
    from mediacrawler.workbench.persistence.repository import Repository
    repo=Repository(tmp_path);task=repo.create({'target':'legacy','platform':'bili','cookies':''});repo.state(task,'succeeded')
    repo.db.execute('PRAGMA user_version=3');repo.db.commit();repo.db.close()
    repo=Repository(tmp_path)
    assert repo.task(task)['state']=='succeeded'
    assert len(list((tmp_path/'backups').glob('index-before-v4-*.sqlite3')))==1
    repo.save_plan(plan().model_dump());repo.db.close()
    repo=Repository(tmp_path);assert len(repo.plans())==1;repo.db.close()



def test_overrides_restore_and_platform_precedence(tmp_path):
    from mediacrawler.workbench.settings.defaults import resolve
    service=Workbench(tmp_path)
    save_defaults(service.repo, {'max_items': 8})
    platform={**service.platforms.get('bili'), 'template_config': {'max_items': 12}}
    assert resolve(service.repo,platform,{})['max_items']==12
    assert resolve(service.repo,platform,{'max_items':3})['max_items']==3
    overrides={'max_items':3};del overrides['max_items']
    assert resolve(service.repo,platform,overrides)['max_items']==12
    service.repo.db.close()


@pytest.mark.parametrize('steps',[
    [step('a','session'),step('a','session')],
    [step('a','session'),step('b','content','b')],
    [step('b','content','a'),step('a','session')],
    [step('a','session',enabled=False),step('b','content','a')],
    [step('b','export','missing')],
])
def test_invalid_graph_cannot_be_submitted(tmp_path,steps):
    service=Workbench(tmp_path)
    with pytest.raises(ValueError): create_run(service,plan(steps=steps))
    assert not service.repo.tasks()
    service.repo.db.close()


def test_repeated_independent_cards_are_valid(tmp_path):
    service=Workbench(tmp_path)
    p=plan(steps=[step('a','session'),step('b','content','a'),step('c','content','a')])
    assert validate(p,service.platforms.get('bili'))['valid']
    p.steps[1],p.steps[2]=p.steps[2],p.steps[1]
    assert validate(p,service.platforms.get('bili'))['valid']
    service.repo.db.close()


@pytest.mark.asyncio
async def test_retry_preserves_attempt_and_skips_successful_files(tmp_path,media_files):
    with serve_media(media_files) as (origin,_):
        service=Workbench(tmp_path/'workbench');await service.start()
        original=service.download;calls=[];fail=True
        async def controlled(run,item):
            calls.append(item['step_id'])
            if item['step_id']=='bad' and fail:raise ValueError('本地验收失败')
            return await original(run,item)
        service.download=controlled
        try:
            p=plan(source='direct',steps=[step('good','files'),step('bad','files'),step('dependent','export','bad')]);p.target=origin+'/av.mp4'
            first=create_run(service,p)['id'];await asyncio.wait_for(service.queue.join(),20)
            assert service.repo.task(first)['state']=='partial'
            assert next(s for s in service.repo.steps(first) if s['id']=='dependent')['state']=='blocked'
            fail=False
            second=(await service.control(first,'retry'))['id'];await asyncio.wait_for(service.queue.join(),20)
            assert second!=first
            assert service.repo.task(first)['state']=='partial'
            assert service.repo.task(second)['state']=='succeeded'
            assert calls.count('good')==1 and calls.count('bad')==2
            f=next(f for f in artifact_rows(service.repo,second) if f.get('step_id')=='good')
            assert artifact_path(service.repo,second,f['id']).exists()
        finally:await service.close()


@pytest.mark.asyncio
async def test_cancel_active_download_marks_unfinished_steps(tmp_path):
    service=Workbench(tmp_path);await service.start();started=asyncio.Event()
    async def slow(run,item):
        started.set()
        while not run.cancelled:await asyncio.sleep(.01)
        raise asyncio.CancelledError()
    service.download=slow
    try:
        p=plan(source='direct',steps=[step('download','files'),step('export','export','download')])
        task=create_run(service,p)['id'];await asyncio.wait_for(started.wait(),5)
        await service.control(task,'cancel');await asyncio.wait_for(service.queue.join(),5)
        assert service.repo.task(task)['state']=='cancelled'
        assert all(s['state'] not in ('running','queued','succeeded') for s in service.repo.steps(task))
    finally:await service.close()


def test_restart_interrupts_workflow_steps_without_replaying(tmp_path):
    from mediacrawler.workbench.persistence.repository import Repository
    repo=Repository(tmp_path);task=repo.create({'target':'local','platform':'bili'})
    repo.step(task,{'id':'s','kind':'files','name':'下载','state':'running'})
    repo.db.close();repo=Repository(tmp_path)
    assert repo.task(task)['state']=='interrupted'
    assert repo.steps(task)[0]['state']=='interrupted'
    assert len(repo.tasks())==1
    repo.db.close()


def test_document_preview_bounds_and_unsupported_format(tmp_path):
    text=tmp_path/'large.jsonl';text.write_text('x'*200000,encoding='utf-8')
    page=document_preview(text)
    assert len(page['text'])==65536 and page['more']
    assert document_preview(text,page['next_offset'])['offset']==65536
    csv=tmp_path/'table.csv';csv.write_text('a,b\n'*250,encoding='utf-8')
    assert len(document_preview(csv)['rows'])==100
    assert document_preview(tmp_path/'file.exe')['type']=='unsupported'


@pytest.mark.asyncio
@pytest.mark.parametrize('second_download',[False,True])
async def test_real_workflow_discovery_download_and_export(tmp_path,second_download):
    from tests.test_workbench_pipeline import fixture_site, until
    from mediacrawler.workbench.platforms.registry import PlatformDefinition
    media=tmp_path/'media';media.mkdir()
    service=Workbench(tmp_path/'workbench');await service.start()
    try:
        with fixture_site(media) as (origin,requests,failures):
            platform=service.platforms.save(PlatformDefinition(name='本地编排验收',category='video',url=origin+'/template',template='video_capture',template_config={'wait_ms':100}))
            steps=[step('session','session'),step('find','discover','session'),step('download','media','find',overrides={'engine':'ffmpeg'})]
            if second_download:steps.append(step('download2','media','find',overrides={'engine':'ffmpeg'}))
            steps.append(step('export','export','download'))
            p=WorkflowPlan(platform=platform['id'],target=origin+'/template',steps=steps)
            task=create_run(service,p)['id'];result=await until(service,task,timeout=45)
            assert result['state']=='succeeded',(result,service.repo.steps(task),service.repo.events(task))
            assert result['counts']['files_succeeded']==(3 if second_download else 2)
            assert all(r['step_id']=='find' for r in service.repo.results(task)['resources'])
    finally:await service.close()


def test_duplicate_submission_returns_original_run(tmp_path):
    service=Workbench(tmp_path)
    p=plan(source='direct',steps=[step('download','files')])
    first=create_run(service,p,submission_key='same-click')['id']
    assert create_run(service,p,submission_key='same-click')['id']==first
    assert len(service.repo.tasks())==1 and service.queue.qsize()==1
    p.name='另一方案'
    with pytest.raises(ValueError):create_run(service,p,submission_key='same-click')
    service.repo.db.close()


from tests.test_workbench_api import local_api


def test_workflow_api_idempotency_and_indexed_preview(local_api):
    client=local_api.client
    p=plan(source='direct',steps=[step('download','files')]).model_dump()
    first=client.post('/api/runs',json=p,headers={'Idempotency-Key':'api-fixture'})
    assert first.status_code==201,first.text
    task=first.json()['id']
    assert client.post('/api/runs',json=p,headers={'Idempotency-Key':'api-fixture'}).json()['id']==task
    def fixture():
        repo=local_api.service.repo
        path=repo.directory(task)/'sample.csv';path.write_text('name,value\nexample,2\n',encoding='utf-8')
        repo.file(task,dict(id='sample',state='succeeded',title='sample.csv',path='sample.csv',step_id='download'))
    local_api.call(fixture)
    result=client.get(f'/api/runs/{task}/artifacts').json()
    assert result['steps']['download']=='下载文件'
    assert 'path' not in result['files'][0]
    assert client.get(f'/api/runs/{task}/artifacts/sample/preview').json()['rows'][1]==['example','2']
    response=client.get(f'/api/runs/{task}/artifacts/sample/file')
    assert response.status_code==200 and response.headers['x-content-type-options']=='nosniff'
    partial=client.get(f'/api/runs/{task}/artifacts/sample/file',headers={'Range':'bytes=0-3'})
    assert partial.status_code==206 and partial.content==b'name'
    assert partial.headers['content-range'].startswith('bytes 0-3/')
    assert client.get(f'/api/runs/{task}/artifacts/sample/file',headers={'Range':'bytes=9999-'}).status_code==416
    assert client.get(f'/api/runs/{task}/artifacts/missing/file').status_code==404
    assert client.get('/api/runs/missing/artifacts/sample/file').status_code==404
    response=client.post(f'/api/runs/{task}/control',json={'action':'cancel'})
    assert response.status_code==200
    assert response.json()['steps'][0]['state']=='cancelled'


def test_empty_history_has_no_available_next_step(local_api):
    def create():return local_api.service.repo.create({'platform':'bili','target':'empty'})
    history=local_api.call(create)
    p=plan(source='history',history_id=history).model_dump()
    result=local_api.client.post('/api/plans/validate',json=p).json()
    assert not result['valid'] and not result['available']


@pytest.mark.asyncio
async def test_graceful_shutdown_is_interruption(tmp_path):
    from mediacrawler.workbench.persistence.repository import Repository
    service=Workbench(tmp_path);await service.start();started=asyncio.Event()
    async def slow(run,item):
        started.set()
        while not run.cancelled:await asyncio.sleep(.01)
        raise asyncio.CancelledError()
    service.download=slow
    p=plan(source='direct',steps=[step('download','files')])
    task=create_run(service,p)['id'];await asyncio.wait_for(started.wait(),5)
    await asyncio.wait_for(service.close(),5)
    repo=Repository(tmp_path)
    assert repo.task(task)['state']=='interrupted'
    assert repo.steps(task)[0]['state']=='interrupted'
    repo.db.close()


def test_browser_settings_freeze_and_validate(tmp_path):
    service=Workbench(tmp_path)
    service.settings.patch_browser({'reuse_login':False,'navigation_timeout':12})
    p=plan(source='direct',steps=[step('download','files')])
    task=create_run(service,p)['id']
    service.settings.patch_browser({'reuse_login':True,'navigation_timeout':60})
    frozen=service.repo.task(task)['config']['browser_snapshot']
    assert frozen['reuse_login'] is False and frozen['navigation_timeout']==12
    for invalid in [{'navigation_timeout':0},{'navigation_timeout':None},{'reuse_login':'false'}]:
        with pytest.raises(ValueError):service.settings.patch_browser(invalid)
    service.repo.db.close()


@pytest.mark.parametrize('suffix',['.txt','.json','.jsonl'])
def test_text_previews_keep_literal_content(tmp_path,suffix):
    file=tmp_path/('file'+suffix);file.write_text('<script>literal</script>',encoding='utf-8')
    assert document_preview(file)['text']=='<script>literal</script>'


def test_excel_preview_pages_and_does_not_execute_formulas(tmp_path):
    from openpyxl import Workbook
    file=tmp_path/'table.xlsx';book=Workbook();sheet=book.active
    sheet.append(['标题','值'])
    for i in range(205):sheet.append([f'行{i}',i])
    sheet.append(['公式','=1+1']);book.save(file);book.close()
    assert document_preview(file)['more']
    assert document_preview(file,100)['rows'][0]==['行99','99']
    assert document_preview(file,206)['rows']==[['公式','']]


@pytest.mark.asyncio
async def test_fixed_streams_do_not_silently_ignore_quality(tmp_path):
    settings=Defaults(engine='ffmpeg',quality='720').model_dump()
    run=SimpleNamespace(cancelled=False,download_process=None,session=None,download_settings=settings)
    item=dict(id='fixed',kind='video',height=1080,streams=[{'url':'https://example.com/v','kind':'video'},{'url':'https://example.com/a','kind':'audio'}])
    with pytest.raises(ValueError,match='清晰度'):await download(run,item,tmp_path,TOOLS)


def test_card_catalog_includes_disabled_reasons(tmp_path):
    service=Workbench(tmp_path)
    p=plan()
    result=inspect_plan(p,service.platforms.get('bili'))
    assert len(result['options'])==7
    assert [d['id'] for d in result['options'] if d['enabled']]==['session']
    assert all(d['reason'] for d in result['options'] if not d['enabled'])
    p.target=''
    result=inspect_plan(p,service.platforms.get('bili'))
    assert len(result['options'])==7 and not any(d['enabled'] for d in result['options'])
    p=plan(steps=[step('login','session')])
    result=inspect_plan(p,{'enabled':True,'collect':False,'video':False,'comments':False})
    assert '当前平台不支持' in next(d for d in result['options'] if d['id']=='comments')['reason']
    service.repo.db.close()
