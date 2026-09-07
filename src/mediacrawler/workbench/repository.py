import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

from .models import TERMINAL

def now():
    return time.time()

class Repository:
    """One event-loop owner; every mutation commits before broadcasting."""
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / 'index.sqlite3')
        self.db.row_factory = sqlite3.Row
        version = self.db.execute('PRAGMA user_version').fetchone()[0]
        if version > 3:
            self.db.close()
            raise RuntimeError('任务索引版本高于当前程序支持版本，请使用对应的新版本程序')
        # Back up an existing index using SQLite's snapshot API, including WAL data.
        if version < 3 and self.db.execute("SELECT 1 FROM sqlite_master WHERE name='tasks'").fetchone():
            target_version = 2 if version < 2 else 3
            backup_path = root / 'backups' / f'index-before-v{target_version}-{time.time_ns()}.sqlite3'
            backup_path.parent.mkdir(exist_ok=True)
            with sqlite3.connect(backup_path) as backup:
                self.db.backup(backup)
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, state TEXT, config TEXT,
            created REAL, updated REAL, session_id TEXT, error TEXT DEFAULT '');
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT,
            type TEXT, payload TEXT, created REAL);
          CREATE INDEX IF NOT EXISTS events_task ON events(task_id,seq);
          CREATE TABLE IF NOT EXISTS records(task_id TEXT, id TEXT, kind TEXT, payload TEXT,
            PRIMARY KEY(task_id,id));
          CREATE TABLE IF NOT EXISTS files(task_id TEXT, id TEXT, state TEXT, payload TEXT,
            PRIMARY KEY(task_id,id));
          CREATE TABLE IF NOT EXISTS resources(task_id TEXT, id TEXT, payload TEXT,
            PRIMARY KEY(task_id,id));
          CREATE TABLE IF NOT EXISTS platforms(id TEXT PRIMARY KEY, payload TEXT);
          CREATE TABLE IF NOT EXISTS settings(section TEXT PRIMARY KEY, payload TEXT NOT NULL, updated REAL NOT NULL);
          PRAGMA user_version=3;
        ''')
        # Queued work is also interrupted: a restart must never silently start old work.
        for row in self.db.execute('SELECT id,state FROM tasks').fetchall():
            if row['state'] not in TERMINAL:
                self.state(row['id'], 'interrupted', '应用退出，需手动检查后重试失败项或新建任务')
        self.db.commit()

    def create(self, config: dict):
        task_id = uuid.uuid4().hex
        self.directory(task_id).mkdir(parents=True)
        public = {**config, 'cookies': ''}  # credentials never enter persisted task/event history
        self.db.execute('INSERT INTO tasks(id,state,config,created,updated,session_id) VALUES(?,?,?,?,?,?)',
                        (task_id, 'queued', json.dumps(public), now(), now(), config.get('session_id')))
        self.db.commit()
        self.event(task_id, 'state', {'state': 'queued'})
        return task_id

    def directory(self, task_id):
        if not task_id or any(c not in '0123456789abcdef' for c in task_id):
            raise ValueError('Invalid task id')
        return self.root / 'tasks' / task_id

    def task(self, task_id):
        row = self.db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
        if row is None:
            raise KeyError(task_id)
        result = dict(row)
        result['config'] = json.loads(result['config'])
        result['counts'] = {
            'content': self.db.execute("SELECT count(*) FROM records WHERE task_id=? AND kind='content'", (task_id,)).fetchone()[0],
            'comments': self.db.execute("SELECT count(*) FROM records WHERE task_id=? AND kind='comment'", (task_id,)).fetchone()[0],
            **{f'files_{s}': self.db.execute('SELECT count(*) FROM files WHERE task_id=? AND state=?', (task_id, s)).fetchone()[0]
               for s in ('pending', 'running', 'succeeded', 'failed', 'cancelled')},
        }
        return result

    def tasks(self):
        return [self.task(r[0]) for r in self.db.execute('SELECT id FROM tasks ORDER BY created DESC LIMIT 200').fetchall()]

    def session_owner(self, session_id, excluding=None):
        if not session_id:
            return None
        # Ownership is not limited by the recent-task page size.
        for row in self.db.execute('SELECT id,state FROM tasks WHERE session_id=?', (session_id,)):
            if row['id'] != excluding and row['state'] not in TERMINAL:
                return row['id']
        return None

    def platform_in_use(self, platform_id):
        return any(row['state'] not in TERMINAL and json.loads(row['config']).get('platform') == platform_id
                   for row in self.db.execute('SELECT state,config FROM tasks'))

    def state(self, task_id, state, error=''):
        self.db.execute('UPDATE tasks SET state=?,updated=?,error=? WHERE id=?', (state, now(), error, task_id))
        self.db.commit()
        self.event(task_id, 'state', {'state': state, 'error': error})

    def session(self, task_id, session_id):
        self.db.execute('UPDATE tasks SET session_id=? WHERE id=?', (session_id, task_id))
        self.db.commit()

    def event(self, task_id, kind, payload):
        self.db.execute('INSERT INTO events(task_id,type,payload,created) VALUES(?,?,?,?)',
                        (task_id, kind, json.dumps(payload, ensure_ascii=False), now()))
        self.db.commit()

    def events(self, task_id, after=0):
        return [{**dict(r), 'payload': json.loads(r['payload'])} for r in self.db.execute(
            'SELECT * FROM events WHERE task_id=? AND seq>? ORDER BY seq LIMIT 500', (task_id, after))]

    def record(self, task_id, item):
        item = dict(item)
        item.setdefault('id', hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:24])
        item.setdefault('kind', 'content')
        item.setdefault('collected_at', now())
        self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?,?,?)',
                        (task_id, item['id'], item['kind'], json.dumps(item, ensure_ascii=False)))
        self.db.commit()

    def file(self, task_id, item):
        self.db.execute('INSERT OR REPLACE INTO files VALUES(?,?,?,?)',
                        (task_id, item['id'], item['state'], json.dumps(item, ensure_ascii=False)))
        self.db.commit()

    def resource(self, task_id, item):
        self.db.execute('INSERT OR REPLACE INTO resources VALUES(?,?,?)',
            (task_id, item['id'], json.dumps(item, ensure_ascii=False)))
        self.db.commit()

    def results(self, task_id):
        return {k: [json.loads(r[0]) for r in self.db.execute(f'SELECT payload FROM {table} WHERE task_id=?', (task_id,))]
                for k, table in [('records', 'records'), ('files', 'files'), ('resources', 'resources')]}
