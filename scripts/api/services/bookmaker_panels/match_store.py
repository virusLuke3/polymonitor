"""Private, bounded decision evidence. Redis remains the only public projection."""
from contextlib import contextmanager
import json
import hashlib
from pathlib import Path
import sqlite3
import time
import uuid
import zlib

from data_sources import source_value
from .movi_archive import configured_int


class MatchStore:
    def __init__(self, path=None):
        value = path or source_value('POLYDATA_ODDS_MATCH_DB_PATH')
        if not value:
            raise ValueError('POLYDATA_ODDS_MATCH_DB_PATH is required')
        self.path = Path(value).expanduser().resolve()
        self.max_bytes = configured_int('POLYDATA_ODDS_MATCH_MAX_MIB', 256, 16, 4096) * 1024**2
        self.days = configured_int('POLYDATA_ODDS_MATCH_RETENTION_DAYS', 30, 7, 365)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        deadline = time.monotonic() + 10
        db.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
        try:
            db.execute('PRAGMA synchronous=FULL')
            with db:
                yield db
        finally:
            db.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS events (pm_event TEXT PRIMARY KEY, event_id TEXT NOT NULL UNIQUE);
                CREATE TABLE IF NOT EXISTS decisions (
                    identity TEXT PRIMARY KEY, checked REAL NOT NULL, due REAL NOT NULL,
                    failures INTEGER NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evidence (
                    id INTEGER PRIMARY KEY, identity TEXT NOT NULL, created REAL NOT NULL, body BLOB NOT NULL);
                CREATE INDEX IF NOT EXISTS evidence_created ON evidence(created);
                CREATE TABLE IF NOT EXISTS evidence_versions (identity TEXT NOT NULL, hash TEXT NOT NULL,
                    created REAL NOT NULL, PRIMARY KEY(identity,hash));
                CREATE TABLE IF NOT EXISTS source_links (
                    source_id TEXT PRIMARY KEY, identity TEXT NOT NULL, event_id TEXT, checked REAL NOT NULL);
            ''')

    def decisions(self):
        with self.connect() as db:
            return {r['identity']: {**json.loads(r['body']), '_due': r['due'], '_failures': r['failures']}
                    for r in db.execute('SELECT * FROM decisions')}

    def save(self, identity, f, decision, evidence, now, delay):
        body = dict(decision)
        with self.connect() as db:
            physical = sum(p.stat().st_size for p in (self.path, Path(str(self.path) + '-wal')) if p.exists())
            reusable = db.execute('PRAGMA freelist_count').fetchone()[0] * db.execute('PRAGMA page_size').fetchone()[0]
            if physical - reusable >= self.max_bytes:
                raise ValueError('Matching archive capacity reached')
            if body.get('pmEventId'):
                db.execute('INSERT OR IGNORE INTO events VALUES (?,?)', (body['pmEventId'], str(uuid.uuid4())))
                body['eventId'] = db.execute('SELECT event_id FROM events WHERE pm_event=?', (body['pmEventId'],)).fetchone()[0]
            previous = db.execute('SELECT body, failures FROM decisions WHERE identity=?', (identity,)).fetchone()
            failures = (previous['failures'] + 1 if previous else 1) if body['state'] == 'unavailable' else 0
            body['checkedAt'] = now
            old = json.loads(previous['body']) if previous else {}
            body['firstLinkedAt'] = old.get('firstLinkedAt') if old.get('pmEventId') == body.get('pmEventId') else None
            if body['state'] == 'linked' and not body['firstLinkedAt']:
                body['firstLinkedAt'] = now
            encoded = json.dumps(body, default=str, ensure_ascii=False)
            db.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?)', (identity, now, now + delay, failures, encoded))
            # Quote ticks and check clocks already have owners. Audit a new
            # identity/rules decision once, not every unchanged five-minute poll.
            def facts(value):
                clocks = {'checkedAt', 'firstLinkedAt', 'fetchedAt', 'sourceStale', 'sourceError',
                          'score', 'scoreUpdatedAt', 'inPlay', 'catalogPrice',
                          'observedAt', 'sourceUpdatedAt', 'quote_prices', 'quote_observed_at', 'quote_updated_at',
                          'gamma_updated_at', 'gamma_metadata_updated_at', 'market_refresh_attempted_at',
                          'market_state_observed_at', 'volume_24h', 'oracle_updated_at'}
                if isinstance(value, dict): return {k: facts(v) for k,v in value.items() if k not in clocks}
                if isinstance(value, list): return [facts(v) for v in value]
                return value
            raw = json.dumps(facts({'fixture': {k: v for k, v in f.items() if k != 'quotes'},
                                   'decision': body, 'evidence': evidence}), default=str, sort_keys=True).encode()
            version = hashlib.sha256(raw).hexdigest()
            fresh = db.execute('INSERT OR IGNORE INTO evidence_versions VALUES (?,?,?)', (identity, version, now)).rowcount
            if fresh:
                db.execute('INSERT INTO evidence(identity,created,body) VALUES (?,?,?)', (identity, now, zlib.compress(raw)))
            for sid in f.get('providerFixtureIds', [f['id']]):
                db.execute('INSERT OR REPLACE INTO source_links VALUES (?,?,?,?)', (sid, identity, body.get('eventId'), now))
        return body

    def prune(self, now):
        with self.connect() as db:
            for table, col in (('evidence', 'created'), ('evidence_versions', 'created'), ('decisions', 'checked'), ('source_links', 'checked')):
                db.execute(f'DELETE FROM {table} WHERE {col} < ?', (now - self.days * 86400,))
            # Stable event IDs survive temporary unavailability and retirement
            # of a provider fixture. This small identity table shares the cap.
