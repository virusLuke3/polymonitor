from datetime import datetime, timezone
import json
import sqlite3
import zlib
from api.services import official_disclosures_service as service
from runtime.snapshot_store import SnapshotStore


def test_report_duration_and_revisions():
    raw = {'cik': 320193, 'facts': {'us-gaap': {'EarningsPerShareDiluted': {'units': {'USD/shares': [
        {'start':'2026-01-01','end':'2026-09-30','filed':'2026-10-20','accn':'ytd','form':'10-Q','val':9},
        {'start':'2026-07-01','end':'2026-09-30','filed':'2026-10-20','accn':'quarter','form':'10-Q','val':2},
        {'start':'2026-07-01','end':'2026-09-30','filed':'2026-10-21','accn':'amended','form':'10-Q/A','val':2.1},
    ]}}}}}
    fact = service.facts(raw, '0000320193')['eps']
    assert fact['value'] == 2.1 and fact['start'] == '2026-07-01' and fact['accession'] == 'amended'


def test_failure_keeps_success_clock_and_restart_backoff(tmp_path):
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite'))
    good = service.collect_source(store, 'x', 'source', lambda x:x, lambda _: {'items':[1]}, 30, now=1000)
    def failure(_):
        raise TimeoutError('network')
    bad = service.collect_source(store, 'x', 'source', lambda x:x, failure, 30, now=1031)
    assert bad['data'] == good['data'] and bad['lastSuccessAt'] == 1000
    restarted = SnapshotStore(store.db_path)
    assert service.collect_source(restarted, 'x', 'source', lambda x:x, lambda _: 1/0, 30, now=1100) == bad
    empty = service.collect_source(restarted, 'x', 'source', lambda x:x, lambda _: {'items':[]}, 30, now=1400)
    assert empty['data'] == {'items':[]} and empty['lastSuccessAt'] == 1400 and not empty['error']
    with sqlite3.connect(tmp_path / 'official_disclosures.sqlite3') as db:
        rows = db.execute('SELECT payload FROM responses').fetchall()
    assert len(rows) == 2 and json.loads(zlib.decompress(rows[0][0])) == {'items':[1]}


def test_identity_and_empty_schema():
    import pytest
    with pytest.raises(ValueError):
        service.facts({'cik':1,'facts':{}}, '0000320193')
    with pytest.raises(ValueError):
        service.policies({'results':[]})
    assert service.policies({'results':[], 'count':0}) == {'items':[], 'availableCount':0}


def test_read_rechecks_age_without_fetch_or_write(tmp_path, monkeypatch):
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite'))
    now = datetime.now(timezone.utc).timestamp()
    store.set(service.SOURCES, 'federal-register', {'lastSuccessAt':now,'lastAttemptAt':now,'data':{'items':[{'id':'rule'}]}}, 1000)
    service.publish(store, now)
    original = store.get_stale(service.NAMESPACE, 'policy-progress')
    monkeypatch.setattr(service.time, 'time', lambda: now + 2*86400)
    read = service.get_snapshot(store, 'policy-progress')
    assert read['source']['stale'] and read['items'] == [{'id':'rule'}]
    assert store.get_stale(service.NAMESPACE, 'policy-progress') == original
    monkeypatch.setattr(service.time, 'time', lambda: now + 8*86400)
    assert service.get_snapshot(store, 'policy-progress')['items'] == []


def test_filing_amendment_and_evidence():
    raw = {'cik':320193, 'name':'Apple', 'filings':{'recent':{
        'accessionNumber':['0000320193-26-001','0000320193-26-002'],
        'form':['10-Q','10-Q/A'], 'filingDate':['2026-11-01','2026-11-02'],
        'primaryDocument':['a.htm','b.htm'], 'reportDate':['2026-09-30','2026-09-30']}}}
    rows = service.filings(raw, '0000320193', 'AAPL')
    assert len(rows) == 2 and rows[0]['amendment']
    assert rows[0]['period'] == '2026-09-30'
    assert rows[0]['url'].endswith('/000032019326002/b.htm')
