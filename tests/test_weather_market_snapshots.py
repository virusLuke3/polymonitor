import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests

from api.clients.source_transport import SourceSession
from api.services import weather_market_service as service
from runtime.snapshot_store import SnapshotStore
from runtime.weather_market_watcher import WeatherMarketWatcher

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc).timestamp()


def catalog(now=NOW, date='2026-11-07', tokens=('1', '2')):
    group = {'marketDate': date, 'eventStatus': 'live', 'eventSlug': 'weather',
             'bins': [{'yesTokenId': t, 'marketStatus': 'live'} for t in tokens]}
    return {'schemaVersion': 1, 'status': 'ok', 'generatedAt': service.iso(now), 'items': [
        {'cityId': 'new-york', 'timezone': 'America/New_York', 'markets': [group], **group}]}


def raw(token='1', **extra):
    return {'asset_id': token, 'timestamp': str(int((NOW - 30) * 1000)), 'hash': 'fixture',
            'bids': [{'price': '0', 'size': '10'}, {'price': '.3', 'size': '20'}],
            'asks': [{'price': '.9', 'size': '1'}, {'price': '.4', 'size': '5'}], **extra}


@pytest.fixture
def store(tmp_path):
    return SnapshotStore(str(tmp_path / 'snapshots.sqlite3'))


def test_book_validation_one_side_zero_unsorted_empty():
    value = service.validate_book(raw(), '1', NOW, 90)
    assert (value['bestBid'], value['bestAsk']) == (.3, .4)
    assert value['eventAt'] == service.iso(NOW - 30)
    zero = service.validate_book(raw(bids=[{'price': 0, 'size': 1}], asks=[]), '1', NOW, 90)
    assert zero['bestBid'] == 0 and zero['bestAsk'] is None
    empty = service.validate_book(raw(bids=[], asks=[]), '1', NOW, 90)
    assert service.quote_bin({'yesTokenId': '1'}, {'1': empty}, NOW)['bookStatus'] == 'no-book'


@pytest.mark.parametrize('patch', [dict(asset_id='wrong'), dict(timestamp='nan'),
    dict(timestamp=str(int((NOW + 60) * 1000))), dict(bids=[{'price': .8, 'size': 1}]),
    dict(asks=[{'price': float('nan'), 'size': 1}]), dict(asks=[{'price': .5, 'size': -1}])])
def test_invalid_books_never_publish(patch):
    with pytest.raises((ValueError, TypeError, KeyError)):
        service.validate_book(raw(**patch), '1', NOW, 90)


def test_expiry_uses_original_event_and_failed_reads_cannot_extend_it():
    book = service.validate_book(raw(), '1', NOW, 90)
    assert service.visible_book(book, '1', NOW + 89)['bookStatus'] == 'available'
    assert service.visible_book(book, '1', NOW + 90)['bookStatus'] == 'stale'
    expired = service.visible_book(book, '1', NOW + 7200)
    assert not expired['bids'] and 'bestBid' not in expired


def test_catalog_rollover_empty_replacement_outage_maximum(store):
    service.publish(store, service.CATALOG_KEY, catalog())
    assert service.catalog_tokens(service.read_catalog(store, NOW)) == {'1': 'new-york', '2': 'new-york'}
    # UTC date is already Nov 8, but New York is still Nov 7.
    midnight = datetime(2026, 11, 8, 4, 59, tzinfo=timezone.utc).timestamp()
    service.publish(store, service.CATALOG_KEY, catalog(midnight))
    assert service.catalog_tokens(service.read_catalog(store, midnight))
    assert not service.catalog_tokens(service.read_catalog(store, midnight + 60))
    service.publish(store, service.CATALOG_KEY, {**catalog(), 'status': 'error'})
    assert service.read_catalog(store, NOW + 60)['status'] == 'error'
    assert not service.catalog_tokens(service.read_catalog(store, NOW + 901))
    service.publish(store, service.CATALOG_KEY, {**catalog(), 'items': []})
    assert not service.read_catalog(store, NOW)['items']


def test_api_reads_shared_snapshot_and_bounded_demand_only(store, monkeypatch):
    service.publish(store, service.CATALOG_KEY, catalog())
    service.publish(store, service.BOOKS_KEY, {'books': {'1': service.validate_book(raw(), '1', NOW, 90)}})
    monkeypatch.setattr('requests.Session.request', lambda *a, **k: pytest.fail('API must not fetch'))
    first = service.read_books(store, ['1'], NOW)
    second = service.read_books(store, ['1', '2', '999'], NOW + 1)
    assert first['books']['1']['yes']['observedAt'] == second['books']['1']['yes']['observedAt']
    assert second['books']['999']['yes']['bookStatus'] == 'inactive'
    lease = store.get(service.STATE, 'demand:new-york')['tokens']
    assert set(lease) == {'1', '2'} and lease['1'] == NOW + 91
    service.publish(store, service.CATALOG_KEY, catalog(tokens=('2',)))
    assert service.read_books(store, ['1'], NOW + 2)['books']['1']['yes']['bookStatus'] == 'inactive'


def test_overlay_does_not_advance_forecast_clocks_and_removes_old_bins(store):
    service.publish(store, service.CATALOG_KEY, catalog())
    old = {'generatedAt': service.iso(NOW - 1000), 'items': [{'cityId': 'new-york', 'forecastFetchedAt': service.iso(NOW - 1000), 'bins': [{'yesTokenId': 'old'}]}]}
    result = service.overlay_weather(old, store, NOW)
    assert result['generatedAt'] == old['generatedAt']
    assert result['items'][0]['forecastFetchedAt'] == old['items'][0]['forecastFetchedAt']
    assert [r['yesTokenId'] for r in result['items'][0]['bins']] == ['1', '2']
    service.publish(store, service.CATALOG_KEY, {**catalog(), 'items': []})
    assert not service.overlay_weather(old, store, NOW)['items'][0]['bins']


def test_overlay_source_health_uses_independent_catalog_and_books(store):
    service.publish(store, service.CATALOG_KEY, catalog())
    books = {'1': service.validate_book(raw(), '1', NOW, 90),
             '2': service.validate_book(raw('2', bids=[], asks=[]), '2', NOW, 90)}
    service.publish(store, service.BOOKS_KEY, {'books': books})
    old = {'status': 'ok', 'sources': {'clob': 'empty', 'marketDatabase': 'error', 'openMeteo': 'ok'},
           'items': [{'cityId': 'new-york'}]}
    result = service.overlay_weather(old, store, NOW)
    assert result['sources'] == {'clob': 'ok', 'marketDatabase': 'ok', 'openMeteo': 'ok'}
    assert result['items'][0]['bookCoverage']['quoted'] == 1
    assert service.overlay_weather(old, store, NOW + 91)['sources']['clob'] == 'unavailable'
    service.publish(store, service.CATALOG_KEY, {**catalog(), 'status': 'error'})
    failed = service.overlay_weather(old, store, NOW)
    assert failed['status'] == 'degraded' and failed['sources']['marketDatabase'] == 'error'
    service.publish(store, service.CATALOG_KEY, {**catalog(), 'items': []})
    empty = service.overlay_weather(old, store, NOW)
    assert empty['sources']['clob'] == 'empty' and not empty['items'][0]['bins']


class Reply:
    status_code = 200
    headers = {}
    def __init__(self, rows):
        self.rows = rows
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def raise_for_status(self):
        if self.status_code >= 400:
            response = requests.Response()
            response.status_code = self.status_code
            raise requests.HTTPError(response=response)
    def iter_content(self, chunk_size):
        yield json.dumps(self.rows).encode()


def test_worker_recovery_keeps_individual_good_times_and_clears_valid_empty(store, monkeypatch):
    monkeypatch.setattr(service.time, 'time', lambda: NOW)
    monkeypatch.setattr('runtime.weather_market_watcher.source_value', lambda k: 'https://example.test')
    service.publish(store, service.CATALOG_KEY, catalog())
    owner = WeatherMarketWatcher.__new__(WeatherMarketWatcher)
    owner.snapshot_store = store
    owner.round_seconds, owner.timeout, owner.book_interval, owner.catalog_interval = 90, 12, 30, 300
    owner.books_session = SimpleNamespace(read_weather_books=lambda *a, **k: [raw('1'), raw('2')])
    assert owner.collect_books(overview=True)['received'] == 2
    success = store.get_stale(service.NAMESPACE, service.BOOKS_KEY)['books']['2']['observedAt']
    owner.books_session.read_weather_books = lambda *a, **k: [raw('1', bids=[], asks=[])]
    assert owner.collect_books(overview=True)['failed'] == 1
    books = store.get_stale(service.NAMESPACE, service.BOOKS_KEY)['books']
    assert books['2']['observedAt'] == success and books['2']['bookStatus'] == 'stale'
    assert not books['1']['bids'] and not books['1']['asks']
    owner.books_session.read_weather_books = lambda *a, **k: [raw('1'), raw('2')]
    assert owner.collect_books(overview=True)['received'] == 2
    assert not owner.collect_books(overview=False)['requested']  # no active viewers


def test_publication_rejection_is_not_success():
    with pytest.raises(RuntimeError):
        service.publish(SimpleNamespace(set=lambda *a: False), 'catalog', {})


def test_source_routing_opt_in_cannot_enable_trading(monkeypatch):
    monkeypatch.setattr('api.clients.source_transport.source_value', lambda k: 'https://example.test' if k == 'POLYDATA_CLOB_API_BASE' else '')
    session = SourceSession()
    with pytest.raises(ValueError):
        session.read_weather_books('https://example.test/order', ['1'])
    with pytest.raises(ValueError):
        session.read_weather_books('https://example.test/books', [{'token_id': '1', 'side': 'BUY'}])


def test_weather_transport_retries_complete_body_and_honors_429_403(monkeypatch):
    from api.clients import source_transport as transport
    monkeypatch.setattr(transport, 'source_value', lambda k: 'https://example.test' if k == 'POLYDATA_CLOB_API_BASE' else '')
    monkeypatch.setattr(transport, '_COOLDOWNS', {})
    monkeypatch.setattr(transport, '_FAILURES', {})
    session = SourceSession()
    session.trust_env = False
    session.routes = {'example.test': ['http://primary.test', 'http://backup.test']}
    calls = []
    def request(_self, method, url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise requests.ConnectionError('fixture disconnect')
        return Reply([raw()])
    monkeypatch.setattr(requests.Session, 'request', request)
    assert session.read_weather_books('https://example.test/books', ['1'])[0]['asset_id'] == '1'
    assert len(calls) == 2
    assert all(c['timeout'].total > 11 for c in calls)  # no six-second split
    assert calls[0]['proxies'] != calls[1]['proxies']
    for code in (403, 429):
        calls.clear()
        reply = Reply([])
        reply.status_code, reply.headers = code, {'Retry-After': '120'}
        def denied(*a, **k):
            calls.append(k)
            return reply
        monkeypatch.setattr(requests.Session, 'request', denied)
        with pytest.raises(requests.HTTPError):
            session.read_weather_books('https://example.test/books', ['1'])
        assert len(calls) == 1
    with pytest.raises(requests.exceptions.RetryError):
        session.read_weather_books('https://example.test/books', ['1'])
    assert len(calls) == 1
