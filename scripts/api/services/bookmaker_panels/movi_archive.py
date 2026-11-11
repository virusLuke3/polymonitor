"""MoviOdds durable evidence, normalized history and restartable acquisition queue.

Only the collector initializes/writes this archive. Public reads are bounded,
read-only queries; live public snapshots belong to Redis, not this database.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zlib

from data_sources import source_value
from .model import instant, number

FIELDS = ('group_id', 'market_id', 'sel_id', 'group_name', 'period', 'market_key',
          'label', 'side', 'line', 'handicap', 'n2', 'phase', 'fixture_id')


def configured_int(key, default, minimum, maximum):
    value = int(source_value(key) or default)
    if not minimum <= value <= maximum:
        raise ValueError(f'Invalid {key}')
    return value


def enabled():
    return source_value('POLYDATA_MOVIODDS_STREAM_ENABLED').lower() in ('1', 'true', 'yes')


def encode(data):
    return json.dumps(data, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(',', ':')).encode()


def unpack(data):
    return json.loads(zlib.decompress(data))


def selection_key(row):
    return '|'.join(str(row.get(k) or '') for k in ('group_id', 'market_id', 'sel_id', 'group_name', 'period', 'market_key'))


def point(row):
    if not isinstance(row, dict) or not row.get('group_id') or not row.get('sel_id'):
        raise ValueError('Missing price identity')
    ts = instant(row.get('ts'))
    suspended_without_price = row.get('suspended') is True and row.get('odds_dec') in (None, 0)
    price = None if suspended_without_price else number(row.get('odds_dec'))
    if not ts or (price is not None and not 1 <= price <= 1_000_000) or not 946684800 <= datetime.fromisoformat(ts).timestamp() <= time.time() + 60:
        raise ValueError('Invalid historical price or source time')
    if 'suspended' in row and not isinstance(row['suspended'], bool):
        raise ValueError('Invalid suspension')
    out = {k: str(row[k]) for k in FIELDS if row.get(k) is not None}
    if any(len(v) > 500 for v in out.values()):
        raise ValueError('Oversized price identity')
    return {**out, 'ts': ts, 'odds_dec': price, 'suspended': row.get('suspended', False)}


class Archive:
    def __init__(self, path=None):
        configured = str(path or source_value('POLYDATA_MOVIODDS_ARCHIVE_PATH'))
        if not configured:
            raise ValueError('POLYDATA_MOVIODDS_ARCHIVE_PATH is required')
        self.path = Path(configured).expanduser().resolve()
        self.max_bytes = configured_int('POLYDATA_MOVIODDS_ARCHIVE_MAX_MIB', 8192, 128, 65536) * 1024**2
        self.raw_days = configured_int('POLYDATA_MOVIODDS_RAW_RETENTION_DAYS', 7, 1, 90)
        self.history_days = configured_int('POLYDATA_MOVIODDS_HISTORY_RETENTION_DAYS', 30, 7, 365)

    @contextmanager
    def connection(self, write=False, maintenance=False):
        uri = str(self.path) if write else self.path.as_uri() + '?mode=ro'
        db = sqlite3.connect(uri, uri=not write, timeout=2)
        db.row_factory = sqlite3.Row
        deadline = time.monotonic() + (15 if write else 2)
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        try:
            if write and not maintenance:
                physical = sum(p.stat().st_size for p in (self.path, Path(str(self.path) + '-wal')) if p.exists())
                reusable = db.execute('PRAGMA freelist_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
                if physical - reusable >= self.max_bytes:
                    raise ValueError('MoviOdds archive capacity reached')
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection(True) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS raw (
                    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, identity TEXT NOT NULL,
                    received REAL NOT NULL, last_received REAL NOT NULL, sha TEXT NOT NULL,
                    body BLOB NOT NULL, UNIQUE(kind,identity,sha));
                CREATE INDEX IF NOT EXISTS raw_age ON raw(last_received);
                CREATE TABLE IF NOT EXISTS points (
                    id TEXT PRIMARY KEY, fixture TEXT NOT NULL, selection TEXT NOT NULL,
                    ts TEXT NOT NULL, received REAL NOT NULL, channel TEXT NOT NULL,
                    raw_id INTEGER NOT NULL, data BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS points_read ON points(fixture,selection,ts,id);
                CREATE INDEX IF NOT EXISTS points_all ON points(fixture,ts,id);
                CREATE INDEX IF NOT EXISTS points_age ON points(received);
                CREATE TABLE IF NOT EXISTS fixtures (
                    id TEXT PRIMARY KEY, sport TEXT NOT NULL, project TEXT NOT NULL,
                    kickoff TEXT, received REAL NOT NULL, data BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS fixture_projects ON fixtures(project,received DESC);
                CREATE TABLE IF NOT EXISTS documents (
                    kind TEXT NOT NULL, fixture TEXT NOT NULL, received REAL NOT NULL,
                    raw_id INTEGER NOT NULL, data BLOB NOT NULL, PRIMARY KEY(kind,fixture));
                CREATE TABLE IF NOT EXISTS tasks (
                    key TEXT PRIMARY KEY, kind TEXT NOT NULL, fixture TEXT NOT NULL, sport TEXT NOT NULL,
                    due REAL NOT NULL, checked REAL, failures INTEGER NOT NULL DEFAULT 0,
                    error TEXT, cursor TEXT NOT NULL DEFAULT '{}');
                CREATE INDEX IF NOT EXISTS tasks_due ON tasks(due);
                CREATE INDEX IF NOT EXISTS task_sport_checks ON tasks(kind,sport,checked);
            ''')
            if 'attempted' not in {row[1] for row in db.execute('PRAGMA table_info(tasks)')}:
                db.execute('ALTER TABLE tasks ADD COLUMN attempted REAL')

    def raw(self, db, kind, identity, body, now):
        if len(body) > 8 * 1024**2:
            raise ValueError('MoviOdds evidence response too large')
        sha = hashlib.sha256(body).hexdigest()
        db.execute('INSERT INTO raw(kind,identity,received,last_received,sha,body) VALUES(?,?,?,?,?,?) '
                   'ON CONFLICT(kind,identity,sha) DO UPDATE SET last_received=excluded.last_received',
                   (kind, identity, now, now, sha, zlib.compress(body)))
        return db.execute('SELECT id FROM raw WHERE kind=? AND identity=? AND sha=?', (kind, identity, sha)).fetchone()[0]

    def points(self, db, fixture, rows, raw_id, channel, now):
        for row in rows:
            value = point(row)
            identity = hashlib.sha256(encode([fixture, value])).hexdigest()
            db.execute('INSERT OR IGNORE INTO points VALUES(?,?,?,?,?,?,?,?)',
                       (identity, fixture, selection_key(value), value['ts'], now, channel, raw_id, zlib.compress(encode(value))))

    def frames(self, batch):
        with self.connection(True) as db:
            for raw, msg, received in batch:
                fi = str(msg.get('fixture') or '')
                raw_id = self.raw(db, 'ws:' + msg['type'], fi, raw, received)
                if msg['type'] in ('snapshot', 'delta'):
                    if not fi or not isinstance(msg.get('quotes'), list) or any(str(q.get('fixture_id', fi)) != fi for q in msg['quotes']):
                        raise ValueError('WS archive identity mismatch')
                    self.points(db, fi, msg['quotes'], raw_id, 'ws', received)

    def catalog(self, body, rows, now, lookback):
        from .moviodds import project
        with self.connection(True) as db:
            self.raw(db, 'catalog', 'all', body, now)
            for row in rows:
                domain = project(row['sport'], row.get('league', ''))
                if not domain:
                    continue
                db.execute('INSERT INTO fixtures VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                           'sport=excluded.sport,project=excluded.project,kickoff=excluded.kickoff,received=excluded.received,data=excluded.data',
                           (row['id'], row['sport'], domain, row.get('kickoff_utc'), now, zlib.compress(encode(row))))
                kickoff = instant(row.get('kickoff_utc'))
                if kickoff and now - lookback * 86400 <= datetime.fromisoformat(kickoff).timestamp() <= now + 48 * 3600:
                    for kind in ('history', 'closing'):
                        # Prefer near-start fixtures and esports without starving older due work.
                        priority = 600 if row['sport'] == 'esports' else 550 if row.get('league') == 'NBA' else 0
                        self.enqueue(db, kind, row['id'], row['sport'], now - priority)

    @staticmethod
    def enqueue(db, kind, fixture, sport, due):
        db.execute('INSERT OR IGNORE INTO tasks(key,kind,fixture,sport,due) VALUES(?,?,?,?,?)',
                   (kind + ':' + sport + ':' + fixture, kind, fixture, sport, due))

    def result_tasks(self, sports, days, now):
        order = sorted(sports, key=lambda sport: ({'esports': 0, 'basketball': 1, 'soccer': 2}.get(sport, 3), sport))
        with self.connection(True) as db:
            for ago in range(days):
                day = datetime.fromtimestamp(now - ago * 86400, timezone.utc).date().isoformat()
                for rank, sport in enumerate(order):
                    self.enqueue(db, 'results', day, sport, now - (1000 if ago < 2 else 500) + rank * 4 + ago)

    def due(self, now, kind):
        with self.connection() as db:
            priority = ("CASE WHEN json_extract(cursor,'$.scope')='primary-groups-v1' AND json_extract(cursor,'$.complete')=0 THEN 0 ELSE 1 END, "
                        if kind == 'history' else "EXISTS(SELECT 1 FROM documents WHERE fixture=tasks.fixture AND kind='result') DESC, " if kind == 'closing' else '')
            # Round-robin sport lanes by successful work; a large esports
            # backlog cannot consume every basketball/football history slot.
            fair = 'COALESCE((SELECT MAX(checked) FROM tasks t WHERE t.kind=tasks.kind AND t.sport=tasks.sport),0), '
            retry = 'CASE WHEN error IS NOT NULL AND failures<=2 THEN 0 ELSE 1 END, '
            row = db.execute('SELECT * FROM tasks WHERE due<=? AND kind=? ORDER BY ' + retry + fair + priority + 'due,key LIMIT 1', (now, kind)).fetchone()
            return dict(row) if row else None

    def attempt(self, task, now):
        with self.connection(True) as db:
            db.execute('UPDATE tasks SET attempted=? WHERE key=?', (now, task['key']))

    def fail(self, task, error, delay, now):
        with self.connection(True) as db:
            db.execute('UPDATE tasks SET due=?,failures=failures+1,error=? WHERE key=?', (now + delay, error, task['key']))

    def save(self, task, body, data, *, cursor, next_due, now):
        from .moviodds import project
        kind, fi = task['kind'], task['fixture']
        with self.connection(True) as db:
            raw_id = self.raw(db, kind, task['key'], body, now)
            if kind == 'history':
                self.points(db, fi, data['points'], raw_id, 'rest-history', now)
            elif kind == 'results':
                for row in data['results']:
                    domain = project(row['sport'], row.get('league', ''))
                    if not domain:
                        continue
                    identity = row['fixture_id']
                    old = db.execute('SELECT data FROM fixtures WHERE id=?', (identity,)).fetchone()
                    meta = {**(unpack(old[0]) if old else {}), 'id': identity, 'sport': row['sport'],
                            'home': row['home'], 'away': row['away'], 'league': row.get('league', '')}
                    db.execute('INSERT INTO fixtures VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET '
                               'received=excluded.received,data=excluded.data',
                               (identity, row['sport'], domain, meta.get('kickoff_utc'), now, zlib.compress(encode(meta))))
                    self.document(db, 'result', identity, {**row, 'archiveSource': data.get('source')}, raw_id, now)
                    for follow in ('history', 'closing'):
                        self.enqueue(db, follow, identity, row['sport'], now - (700 if row['sport'] == 'esports' else 650 if row.get('league') == 'NBA' else 0))
            else:
                self.document(db, kind, fi, data, raw_id, now)
            db.execute('UPDATE tasks SET due=?,checked=?,failures=0,error=NULL,cursor=? WHERE key=?',
                       (next_due, now, json.dumps(cursor), task['key']))

    @staticmethod
    def document(db, kind, fi, data, raw_id, now):
        db.execute('INSERT INTO documents VALUES(?,?,?,?,?) ON CONFLICT(kind,fixture) DO UPDATE SET '
                   'received=excluded.received,raw_id=excluded.raw_id,data=excluded.data',
                   (kind, fi, now, raw_id, zlib.compress(encode(data))))

    def prune(self, now):
        # Explicit retention, not emergency deletion to disguise capacity failure.
        with self.connection(True, maintenance=True) as db:
            db.execute('DELETE FROM raw WHERE last_received<?', (now - self.raw_days * 86400,))
            db.execute('DELETE FROM points WHERE received<?', (now - self.history_days * 86400,))
            db.execute('DELETE FROM documents WHERE received<?', (now - self.history_days * 86400,))
            db.execute('DELETE FROM fixtures WHERE received<?', (now - self.history_days * 86400,))
            db.execute('DELETE FROM tasks WHERE kind!=? AND fixture NOT IN (SELECT id FROM fixtures)', ('results',))
            db.execute('DELETE FROM tasks WHERE kind=? AND fixture<?', ('results', datetime.fromtimestamp(now - 30 * 86400, timezone.utc).date().isoformat()))
        with sqlite3.connect(self.path, timeout=2) as db:
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def status(self):
        with self.connection() as db:
            return {'points': db.execute('SELECT count(*) FROM points').fetchone()[0],
                    'tasks': db.execute('SELECT count(*) FROM tasks').fetchone()[0],
                    'failedTasks': db.execute('SELECT count(*) FROM tasks WHERE error IS NOT NULL').fetchone()[0],
                    'lastSuccessAt': db.execute('SELECT max(checked) FROM tasks').fetchone()[0]}
