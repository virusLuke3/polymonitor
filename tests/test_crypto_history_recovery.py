"""Recovery checks for the real collector policy, independent of external sources."""
import json
from unittest.mock import Mock

import pytest
import requests

from api.clients import source_transport as transport
from api.services.crypto_strategy.cadence import SourceCadence, SourceReadError
from api.services.crypto_strategy.store import Store, read_snapshot
from api.services.crypto_strategy import providers


def response(status=200):
    result = requests.Response()
    result.status_code = status
    result._content = b'{"ok":true}'
    result._content_consumed = True
    return result


@pytest.fixture
def routed(monkeypatch):
    monkeypatch.delenv('POLYDATA_SNAPSHOT_SQLITE_PATH', raising=False)
    monkeypatch.setattr(transport, '_routes', lambda: {'source.example': ['socks5h://first:1', 'socks5h://second:2']})
    monkeypatch.setattr(transport.time, 'sleep', lambda _: None)
    transport._COOLDOWNS.clear()
    transport._FAILURES.clear()


def test_slow_read_keeps_45_seconds_and_switches_only_after_two_failures(monkeypatch, routed):
    calls = []
    def request(self, method, url, **kwargs):
        calls.append(kwargs)
        if len(calls) < 4:
            raise requests.exceptions.ReadTimeout()
        return response()
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session:
        assert transport.read_with_retry(session, 'https://source.example', lambda r: r.json(), timeout=45) == {'ok': True}
    assert [c['timeout'] for c in calls] == [45] * 4
    assert [c['proxies']['https'] for c in calls] == ['socks5h://first:1'] * 2 + ['socks5h://second:2'] * 2


def test_body_timeout_is_retried_and_responses_are_closed(monkeypatch, routed):
    replies = [response(), response()]
    for r in replies:
        r.close = Mock()
    monkeypatch.setattr(requests.Session, 'request', lambda *a, **kw: replies.pop(0))
    reads = []
    saved = replies[:]
    def read(r):
        reads.append(r)
        if len(reads) == 1:
            raise requests.exceptions.ChunkedEncodingError('truncated stream')
        return r.json()
    with transport.SourceSession() as session:
        assert transport.read_with_retry(session, 'https://source.example', read, timeout=45) == {'ok': True}
    assert len(reads) == 2
    assert all(r.close.call_count for r in saved)


def test_exhausted_cycle_does_not_start_another_attempt(monkeypatch, routed):
    clock = [0.0]
    calls = []
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock[0])
    def request(*a, **kw):
        calls.append(kw)
        clock[0] = 90
        raise requests.exceptions.ReadTimeout()
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session, pytest.raises(requests.exceptions.Timeout, match='budget'):
        transport.read_with_retry(session, 'https://source.example', lambda r: r.json(), timeout=45, deadline=90)
    assert len(calls) == 1


@pytest.mark.parametrize('status', [403, 404, 429])
def test_denial_and_rate_limit_do_not_retry_or_change_exit(monkeypatch, routed, status):
    calls = []
    def request(*a, **kw):
        calls.append(kw)
        r = response(status)
        r.headers['Retry-After'] = '600'
        return r
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session:
        with pytest.raises(requests.exceptions.HTTPError):
            transport.read_with_retry(session, 'https://source.example', lambda r: r.raise_for_status(), timeout=45)
        if status == 429:
            with pytest.raises(requests.exceptions.RetryError):
                transport.read_with_retry(session, 'https://source.example', lambda r: r.json(), timeout=45)
    assert len(calls) == 1


def fail():
    raise requests.exceptions.ReadTimeout('offline')


def test_last_good_survives_failure_restart_and_expires_without_clock_renewal(tmp_path):
    path = str(tmp_path / 'crypto.sqlite3')
    store = Store(path)
    cadence = SourceCadence()
    key = ('https://bybit.example', 'BTC', 'spotBars')
    original = {'time': 1000, 'result': {'list': [['0', '1', '1', '1', '100']]}}
    assert cadence.read(key, 1000, 60_000, lambda: original) == original
    assert cadence.read(key, 61_000, 60_000, fail) == original
    assert cadence.state(key)['status'] == 'stale'
    store.publish({'status': 'stale', 'collectedAt': 61_000}, 61_000, cadence.entries)
    store.conn.close()
    store = Store(path)
    recovered = SourceCadence(store.source_entries())
    assert recovered.read(key, 90_000, 60_000, lambda: pytest.fail('retry ran early')) == original
    assert recovered.state(key)['lastSuccessAt'] == 1000
    assert read_snapshot(path)['status'] == 'stale'
    with pytest.raises(SourceReadError, match='ReadTimeout'):
        recovered.read(key, 1_801_001, 60_000, fail)
    assert recovered.state(key)['status'] == 'unavailable'
    store.conn.close()


def test_recovery_and_successful_empty_replace_old_data():
    cadence = SourceCadence()
    cadence.read('options:BTC', 1000, 300_000, lambda: {'observedAt': 'original'})
    assert cadence.read('options:BTC', 301_000, 300_000, fail)['observedAt'] == 'original'
    assert cadence.state('options:BTC')['retryAt'] == 361_000
    assert cadence.read('options:BTC', 361_000, 300_000, lambda: {'expiries': []}) == {'expiries': []}
    assert cadence.state('options:BTC')['error'] is None
    assert cadence.state('options:BTC')['lastSuccessAt'] == 361_000


def test_retained_option_expiry_is_filtered_and_shared_snapshot_marks_stale(monkeypatch):
    from api.services.crypto_strategy.contracts import iso
    now = 1_790_000_000_000
    monkeypatch.setattr(providers, 'venue_asset', lambda *a: {'errors': {}})
    monkeypatch.setattr(providers, 'stablecoins', lambda *a: [])
    monkeypatch.setattr(providers, 'options', lambda get, asset, at: {
        'observedAt': iso(at), 'expiries': [{'expiry': iso(at + 300_000), 'bands': []},
                                         {'expiry': iso(at + 600_000), 'bands': []}]})
    cadence = SourceCadence()
    first = providers.collect(None, bybit_base='fixture', reference_url='', now=now, cadence=cadence)
    monkeypatch.setattr(providers, 'options', lambda *a: fail())
    second = providers.collect(None, bybit_base='fixture', reference_url='', now=now + 300_001, cadence=cadence)
    assert second['status'] == 'stale'
    assert len(second['options']['BTC']['expiries']) == 1
    assert second['options']['BTC']['observedAt'] == first['options']['BTC']['observedAt']
    assert second['options']['BTC']['error'] == 'ReadTimeout'


def test_persisted_keys_separate_source_and_asset(tmp_path):
    cadence = SourceCadence()
    cadence.read(('first', 'BTC', 'oiHistory'), 1000, 300_000, lambda: [1])
    assert cadence.read(('second', 'BTC', 'oiHistory'), 1000, 300_000, lambda: [2]) == [2]
    assert cadence.read(('first', 'ETH', 'oiHistory'), 1000, 300_000, lambda: [3]) == [3]
    assert len(json.loads(json.dumps(cadence.entries))) == 3
