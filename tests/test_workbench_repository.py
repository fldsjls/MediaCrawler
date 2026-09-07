from mediacrawler.workbench.models import TaskConfig
from mediacrawler.workbench.repository import Repository


def test_restart_interrupts_running_and_queued_but_retains_results(tmp_path):
    repo = Repository(tmp_path)
    first = repo.create(TaskConfig(platform='bili', target='BV-fixture').model_dump())
    second = repo.create(TaskConfig(platform='bili', target='BV-fixture2').model_dump())
    complete = repo.create(TaskConfig(platform='bili', target='BV-fixture3').model_dump())
    repo.state(first, 'running')
    repo.record(first, {'id': 'content:1', 'title': '已保存'})
    repo.file(first, {'id': 'file1', 'state': 'succeeded', 'path': 'media/sample.mp4'})
    repo.state(complete, 'succeeded')
    repo.db.close()
    reopened = Repository(tmp_path)
    try:
        assert reopened.task(first)['state'] == 'interrupted'
        assert reopened.task(second)['state'] == 'interrupted'
        assert reopened.task(complete)['state'] == 'succeeded'
        assert reopened.task(first)['counts']['content'] == 1
        assert reopened.task(first)['counts']['files_succeeded'] == 1
        assert reopened.events(first)[-1]['payload']['state'] == 'interrupted'
    finally:
        reopened.db.close()


def test_credentials_not_persisted_and_record_write_is_idempotent(tmp_path):
    repo = Repository(tmp_path)
    try:
        task = repo.create(TaskConfig(platform='bili', target='BV-fixture', cookies='SECRET=fixture').model_dump())
        assert repo.task(task)['config']['cookies'] == ''
        repo.record(task, {'id': 'content:1', 'title': '原始'})
        repo.record(task, {'id': 'content:1', 'title': '更新'})
        assert repo.task(task)['counts']['content'] == 1
        assert repo.results(task)['records'][0]['title'] == '更新'
        first_page = repo.events(task)
        assert first_page
        assert not repo.events(task, after=first_page[-1]['seq'])
    finally:
        repo.db.close()
