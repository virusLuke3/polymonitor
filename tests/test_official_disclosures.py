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


def test_failure_status_and_observation_clock_do_not_affect_sec(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc).timestamp()
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite'))
    for cik in service.WATCHLIST.values():
        for kind in ('submissions', 'facts'):
            store.set(service.SOURCES, f'sec:{cik}:{kind}', {
                'lastSuccessAt': now, 'lastAttemptAt': now, 'data': [] if kind == 'submissions' else {}}, 1000)
    state = {'lastSuccessAt': now - 60, 'lastAttemptAt': now, 'error': 'ReadTimeout',
             'nextAttemptAt': now + 300, 'data': {'items': [{'id': 'rule'}]}}
    store.set(service.SOURCES, 'federal-register', state, 1000)
    service.publish(store, now)
    failed = service.get_snapshot(store, 'policy-progress')
    assert failed['status'] == 'degraded' and failed['items'] == [{'id': 'rule'}]
    assert failed['generatedAt'] == service.iso(now - 60)
    assert failed['source']['lastSuccessAt'] == service.iso(now - 60)
    assert service.get_snapshot(store, 'company-events')['status'] == 'ok'
    monkeypatch.setattr(service.time, 'time', lambda: now + 2 * 86400)
    old = service.get_snapshot(store, 'company-events')
    assert old['status'] == 'degraded' and old['sources']['AAPL']['facts']['stale']
    assert not service.source_meta({}, 1000)['usable']


def test_rate_limit_is_persisted_without_secrets_or_success(tmp_path):
    import requests
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite'))
    response = requests.Response()
    response.status_code = 429
    response.headers['Retry-After'] = '7200'
    def limited(_):
        raise requests.HTTPError('secret query token', response=response)
    state = service.collect_source(store, 'x', 'source', lambda x: x, limited, 1800, now=1000)
    assert state['error'] == 'HTTP 429' and state['nextAttemptAt'] == 8200
    assert state.get('lastSuccessAt') is None


def test_disclosure_transport_retries_full_body_budget_and_stops_on_429(monkeypatch):
    import requests
    from api.clients import source_transport
    from runtime.official_disclosures_watcher import Transport
    calls = []
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def close(self): pass
        def iter_content(self, chunk_size):
            if len(calls) == 1:
                raise requests.exceptions.ChunkedEncodingError('body stalled')
            yield b'{"results": [], "count": 0}'
    class Session:
        def request(self, method, url, **kwargs):
            calls.append(kwargs)
            return Response()
    monkeypatch.setattr(source_transport.time, 'sleep', lambda _: None)
    import time
    transport = Transport(Session(), deadline=time.monotonic() + 1100, user_agent='contact')
    assert transport.fetch('https://www.federalregister.gov/api') == {'results': [], 'count': 0}
    assert len(calls) == 2 and all(call['timeout'] == 45 and call['stream'] for call in calls)
    class LimitedSession:
        def request(self, method, url, **kwargs):
            calls.append(kwargs)
            response = requests.Response()
            response.status_code = 429
            response._content = b''
            response._content_consumed = True
            return response
    import pytest
    calls.clear()
    with pytest.raises(requests.HTTPError):
        Transport(LimitedSession(), deadline=time.monotonic() + 1100, user_agent='').fetch('https://www.federalregister.gov/api')
    assert len(calls) == 1


def test_retry_after_starts_when_response_arrives_not_when_request_started(tmp_path, monkeypatch):
    import requests
    clock = [1000]
    monkeypatch.setattr(service.time, 'time', lambda: clock[0])
    store = SnapshotStore(str(tmp_path / 'snapshots.sqlite'))
    def fetch(_):
        clock[0] = 1090
        response = requests.Response()
        response.status_code = 429
        response.headers['Retry-After'] = '600'
        raise requests.HTTPError(response=response)
    state = service.collect_source(store, 'slow', 'url', lambda x: x, fetch, 1800)
    assert state['lastAttemptAt'] == 1000 and state['nextAttemptAt'] == 1690
