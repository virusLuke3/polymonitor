"""Failure isolation at real transport, collector, storage and serving boundaries."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import threading

import pytest
import requests

from api.clients import source_transport as transport
from api.services import defi_token_watch_service as defi, seed_recovery
from api.services import finance_external_sources_service as finance
from api.services.crypto_strategy import providers
from api.services.crypto_strategy.cadence import SourceCadence
from api.services.finance_watch import sentiment
from runtime.crypto_strategy_watcher import SlowSources


def reply():
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"ok":true}'
    response._content_consumed = True
    return response


@pytest.fixture
def routed(monkeypatch):
    monkeypatch.setattr(transport, '_routes', lambda: {'example.test': ['socks5h://one:1', 'socks5h://two:2']})
    monkeypatch.delenv('POLYDATA_SNAPSHOT_SQLITE_PATH', raising=False)
    transport._COOLDOWNS.clear()
    transport._FAILURES.clear()
    monkeypatch.setattr(transport.time, 'sleep', lambda _: None)


@pytest.mark.parametrize('timeout', [5, 12])
def test_each_exit_gets_intact_attempt_and_read_timeout_does_not_poison_other_collectors(monkeypatch, routed, timeout):
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        if kwargs['proxies']['https'].endswith('one:1'):
            raise requests.exceptions.ReadTimeout()
        return reply()
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session:
        for _ in range(3):
            session.get('https://example.test', timeout=timeout)
        assert session._due('example.test:0')
    assert len(calls) == 6
    assert all(call['timeout'].total == pytest.approx(timeout, abs=.01) for call in calls)


def test_expired_owner_deadline_never_launches_point_one_second_fallback(monkeypatch, routed):
    clock = [0]
    calls = []
    monkeypatch.setattr(transport.time, 'monotonic', lambda: clock[0])
    def request(*a, **kw):
        calls.append(kw)
        clock[0] = 13
        raise requests.exceptions.ReadTimeout()
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session, pytest.raises(requests.exceptions.Timeout):
        session.get('https://example.test', timeout=12, source_deadline=12)
    assert len(calls) == 1


def test_stream_body_failure_switches_exit_before_recording_success(monkeypatch, routed):
    calls, successes = [], []
    def request(*a, **kw):
        calls.append(kw)
        response = reply()
        response.close = Mock()
        if len(calls) == 1:
            response.iter_content = Mock(side_effect=requests.exceptions.ChunkedEncodingError('truncated'))
        else:
            response.iter_content = lambda **kwargs: iter([b'video'])
        return response
    monkeypatch.setattr(requests.Session, 'request', request)
    with transport.SourceSession() as session:
        monkeypatch.setattr(session, '_route_succeeded', successes.append)
        data = transport.read_with_retry(session, 'https://example.test',
            lambda r: transport.read_response_bytes(r, 100), attempts=2, timeout=12, stream=True)
    assert data == b'video'
    assert [x['proxies']['https'] for x in calls] == ['socks5h://one:1', 'socks5h://two:2']
    assert successes == ['example.test:1']


def test_history_delay_cannot_separate_spot_and_perp_observation():
    now = 1_793_790_000_000
    clock = [now]
    calls = []
    def get(url, params=None):
        endpoint = url.rsplit('/', 1)[-1]
        calls.append(endpoint)
        if endpoint == 'kline':
            clock[0] += 7000
        rows = [{'symbol': 'BTCUSDT', 'lastPrice': '100', 'markPrice': '101', 'indexPrice': '100'}] if endpoint == 'tickers' else []
        return {'retCode': 0, 'time': clock[0], 'result': {'list': rows}}
    result = providers.venue_asset(get, 'https://example.test', 'BTC', now)
    assert calls[:2] == ['tickers', 'tickers']
    assert calls.index('orderbook') < calls.index('kline')
    assert result['basisClockSkewMs'] == 0
    assert result['basisBps'] == pytest.approx(100)


def test_stablecoin_failures_preserve_each_valid_price_without_renewing_success():
    cadence = SourceCadence()
    def good(url, **kwargs):
        return {'data': {'amount': '1'}} if 'coinbase' in url else {'result': {'pair': {'c': ['1']}}}
    first = providers.stablecoins(good, 1000, cadence)
    def failed(*a, **kw):
        raise requests.exceptions.ReadTimeout()
    retained = providers.stablecoins(failed, 61000, cadence)
    assert [x['price'] for x in retained] == [1] * 4
    assert [x['receivedAt'] for x in retained] == [x['receivedAt'] for x in first]
    assert all(x['status'] == 'stale' and x['sourceState']['lastSuccessAt'] == 1000 for x in retained)
    expired = providers.stablecoins(failed, 301001, cadence)
    assert all(x['price'] is None and x['status'] == 'unavailable' for x in expired)


def test_slow_jobs_are_bounded_and_never_resubmitted_while_running(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def blocked(name, base, entries):
        calls.append(name)
        entered.set()
        release.wait(2)
        return entries
    monkeypatch.setattr(SlowSources, '_refresh', staticmethod(blocked))
    sources = SlowSources()
    try:
        cadence = SourceCadence()
        sources.schedule(cadence, 'fixture', 1000)
        assert entered.wait(1)
        sources.schedule(cadence, 'fixture', 31000)
        assert len(sources.jobs) == 6
        assert len(calls) <= 3
    finally:
        release.set()
        sources.close()


def test_fast_collection_does_not_call_history_or_options(monkeypatch):
    calls = []
    def get(url, params=None):
        calls.append(url)
        if 'bybit.test' in url:
            return {'retCode': 0, 'result': {'list': []}}
        return {'data': {'amount': '1'}} if 'coinbase' in url else {'result': {'pair': {'c': ['1']}}}
    result = providers.collect(get, bybit_base='https://bybit.test', reference_url='', now=1_793_790_000_000,
                               cadence=SourceCadence(), fast_only=True)
    assert len(result['assets']) == 4
    assert len(result['stablecoins']) == 4
    assert not any(any(path in url for path in ('kline', 'open-interest', 'funding/history', 'deribit')) for url in calls)
    assert result['options']['BTC']['status'] == 'unavailable'


def test_individual_row_age_cannot_be_extended_by_new_envelope():
    now = datetime.now(timezone.utc)
    old = (now - timedelta(minutes=35)).isoformat()
    fresh = now.isoformat()
    result = seed_recovery.bounded_rows({'generatedAt': fresh, 'items': [
        {'id': 'old', 'fetchedAt': old}, {'id': 'new', 'fetchedAt': fresh}]}, fresh)
    assert [x['id'] for x in result['items']] == ['new']
    assert result['status'] == 'partial'


def test_defi_expired_seed_cannot_be_resurrected_or_trigger_live_api_acquisition():
    old = {'generatedAt': '2000-01-01T00:00:00Z', 'status': 'ok', 'items': [{'id': 'aave', 'price': 1}]}
    get = Mock(side_effect=AssertionError('GET acquired provider data'))
    ctx = {'SETTINGS': SimpleNamespace(coingecko_base_url='https://example.test'), 'http_json_get': get,
           'SNAPSHOT_STORE': SimpleNamespace(get=lambda *a: None, get_stale=lambda *a: old)}
    result = defi.get_defi_token_watch_snapshot(ctx)
    assert result['status'] == 'warming' and result['items'] == [] and result['generatedAt'] == ''
    get.assert_not_called()


def test_defi_partial_coverage_keeps_missing_identity_explicit():
    ctx = {'SETTINGS': SimpleNamespace(coingecko_base_url='https://example.test', defi_token_watch_ids=('aave', 'havven')),
           'http_json_get': lambda *a, **kw: [{'id': 'aave', 'symbol': 'aave', 'current_price': 10}]}
    result = defi.fetch_live_defi_token_watch_payload(ctx)
    assert result['status'] == 'partial'
    assert result['summary']['missingIds'] == ['havven']
    assert result['summary']['expectedCount'] == 2


def test_finance_failed_branch_retains_only_its_last_good_and_expires(monkeypatch):
    now = datetime.now(timezone.utc)
    old_at = (now - timedelta(minutes=20)).isoformat()
    old = {'generatedAt': old_at, 'sourcePayloads': {'referenceTradfiPerps': {
        'fetchedAt': old_at, 'status': 'ok', 'items': [{'symbol': 'ES=F', 'source': 'yahoo-reference', 'markPx': 10}]}}}
    ctx = {'SETTINGS': SimpleNamespace(), 'get_cached_json': lambda *a: old}
    for name in ('hyperliquid_perp', 'okx_tradfi_perp', 'etf_flow', 'cot', 'stablecoin'):
        monkeypatch.setattr(finance, '_fetch_' + name + '_source', lambda *a: {'status': 'ok', 'items': [{'symbol': 'good'}]})
    monkeypatch.setattr(finance, '_fetch_reference_tradfi_perp_source', Mock(side_effect=requests.exceptions.ReadTimeout()))
    result = finance.build_finance_external_sources_payload(ctx)
    retained = result['sourcePayloads']['referenceTradfiPerps']['items'][0]
    assert retained['markPx'] == 10 and retained['fetchedAt'] == old_at and retained['retained']
    assert result['sourcePayloads']['cot']['items'][0]['fetchedAt'] != old_at
    monkeypatch.setattr(finance, 'utc_now_iso', lambda: (now + timedelta(minutes=11)).isoformat())
    assert finance.build_finance_external_sources_payload(ctx)['sourcePayloads']['referenceTradfiPerps']['items'] == []


def test_fear_greed_yahoo_failure_does_not_abort_fred_or_other_symbols(monkeypatch):
    yahoo, fred = [], []
    monkeypatch.setattr(sentiment, '_http_json_get', lambda *a, **k: {'data': [{'value': '50'}]})
    monkeypatch.setattr(sentiment, '_fetch_cnn_fng', lambda *a: None)
    monkeypatch.setattr(sentiment, '_fetch_aaii_sentiment', lambda *a: None)
    monkeypatch.setattr(sentiment, '_fetch_barchart_last_price', lambda *a: None)
    def quotes(ctx, symbol, **kwargs):
        yahoo.append(symbol)
        if symbol == '^GSPC':
            raise requests.exceptions.ReadTimeout()
        return {'price': 10, 'closes': [10] * 200}
    monkeypatch.setattr(sentiment, '_fetch_yahoo_closes', quotes)
    monkeypatch.setattr(sentiment, '_fetch_yahoo_snapshot', lambda *a, **k: {})
    monkeypatch.setattr(sentiment, '_fetch_fred_observations', lambda ctx, series: fred.append(series) or [])
    ctx = {'SETTINGS': SimpleNamespace(), 'http_json_get': lambda *a: {}}
    result = sentiment.build_fear_greed_payload(ctx, 24)
    assert len(yahoo) == 10 and len(fred) >= 9
    assert result['status'] == 'partial' and result['errors']['yahoo:^GSPC'] == 'ReadTimeout'


def test_yahoo_symbol_failure_does_not_stop_other_symbols(monkeypatch):
    from api.clients import market_data_client
    from test_market_data_client import make_context
    state = {}
    ctx = make_context({})
    ctx['get_cached_runtime_payload'] = lambda ns, key: state.get((ns, key))
    ctx['set_cached_runtime_payload'] = lambda ns, key, value, ttl_seconds: state.update({(ns, key): value})
    getter = Mock(side_effect=[requests.ReadTimeout(), requests.ReadTimeout(), requests.ReadTimeout(), {}])
    monkeypatch.setattr(market_data_client, 'http_json_get', getter)
    for _ in range(3):
        with pytest.raises(requests.ReadTimeout):
            market_data_client.get_yahoo_market_snapshot(ctx, 'A')
    assert market_data_client.get_yahoo_market_snapshot(ctx, 'B') is None
    with pytest.raises(RuntimeError):
        market_data_client.get_yahoo_market_snapshot(ctx, 'A')
    assert getter.call_count == 4


def test_empty_kraken_ticker_preserves_previous_quote():
    cadence = SourceCadence()
    def good(url, params=None):
        return {'result': {'PAIR': {'c': ['1']}}} if 'kraken' in url else {'data': {'amount': '1'}}
    providers.stablecoins(good, 1000, cadence)
    def missing(url, params=None):
        return {'result': {}} if 'kraken' in url else {'data': {'amount': '1'}}
    rows = providers.stablecoins(missing, 62000, cadence)
    assert all(row['price'] == 1 for row in rows)
    assert all(row['sourceState']['retained'] for row in rows if row['source'] == 'Kraken')


def test_sqlite_publication_survives_redis_mirror_failure():
    from runtime.finance_external_sources_watcher import FinanceExternalSourcesWatcher
    watcher = FinanceExternalSourcesWatcher.__new__(FinanceExternalSourcesWatcher)
    watcher.interval_seconds = 900
    watcher.redis_prefix = 'test:'
    watcher.snapshot_store = Mock()
    watcher.redis_client = Mock()
    watcher.redis_client.set.side_effect = TimeoutError()
    payload = {'status': 'ok', 'items': [{'price': 1}]}
    watcher.store_payload(payload)
    assert watcher.snapshot_store.set.call_args.args[2] is payload


def test_finance_external_builder_uses_its_durable_owner():
    from runtime.finance_external_sources_watcher import FinanceExternalSourcesWatcher
    watcher = FinanceExternalSourcesWatcher.__new__(FinanceExternalSourcesWatcher)
    watcher.snapshot_store = Mock()
    watcher.settings = SimpleNamespace(finance_runtime_ttl_seconds=300)
    watcher.requests = Mock()
    assert watcher.service_context()['SNAPSHOT_STORE'] is watcher.snapshot_store


def test_empty_options_response_cannot_replace_successful_source_cache():
    with pytest.raises(ValueError, match='DERIBIT_NO_VALID_OPTION_BANDS'):
        providers.options(lambda *a, **k: {'result': []}, 'BTC', 1000)


def test_ofac_parsed_publication_is_reused_with_original_clock(tmp_path):
    from api.services import geo_sanctions_shock_service as geo
    from runtime.snapshot_store import SnapshotStore
    from test_geo_sanctions_shock import GeoSanctionsShockSeedBuilderTestCase, FakeRequests
    store = SnapshotStore(str(tmp_path / 'geo.sqlite'))
    ctx = GeoSanctionsShockSeedBuilderTestCase().make_context(requests_lib=FakeRequests())
    ctx['SNAPSHOT_STORE'] = store
    first = geo._fetch_ofac_snapshot(ctx)
    assert first['states']['ofacSdn'] == 'ok'
    ctx['requests'] = SimpleNamespace(get=Mock(side_effect=AssertionError('no duplicate download')))
    ctx['utc_now_iso'] = lambda: '2026-04-28T00:05:00Z'
    second = geo._fetch_ofac_snapshot(ctx)
    assert second == first
    assert second['focusEntries'][0]['collectedAt'] == '2026-04-28T00:00:00Z'


def test_finance_source_rows_cannot_live_forever_under_new_envelope(monkeypatch):
    now = datetime.now(timezone.utc)
    old = (now-timedelta(minutes=31)).isoformat()
    data = {'generatedAt': now.isoformat(), 'tradfiPerps': {'items': [{'symbol':'A','fetchedAt':old}], 'status':'ok'}}
    value = finance._bounded_snapshot(data)
    assert value['tradfiPerps']['items'] == []
    assert value['tradfiPerps']['status'] == 'unavailable'



def test_finance_external_sources_receive_independent_budgets(monkeypatch):
    from test_finance_external_sources import _ctx
    starts = []
    ctx = _ctx()
    ctx["begin_source"] = starts.append
    finance.build_finance_external_sources_payload(ctx)
    assert len(starts) == 6
    assert {"etfFlow", "cot", "stablecoin"}.issubset(starts)



def test_daily_yahoo_history_keeps_enough_observations_for_200_day_indicators():
    from api.clients import market_data_client
    from test_market_data_client import make_context, make_chart_payload
    raw = make_chart_payload(symbol="SPY", current=300, previous=1, closes=list(range(1, 301)))
    value = market_data_client.get_yahoo_market_snapshot(make_context(raw), "SPY", interval="1d", range_name="1y")
    assert len(value["points"]) == 260
    assert sentiment._sma([p["value"] for p in value["points"]], 200) == 200.5



def test_wrapped_body_failures_do_not_cool_shared_exit():
    assert not transport._connection_route_failure(requests.ConnectionError("Read timed out"))
    assert not transport._connection_route_failure(requests.ConnectionError("RemoteDisconnected('Remote end closed connection')"))
    assert transport._connection_route_failure(requests.ConnectTimeout())
    assert transport._connection_route_failure(requests.ConnectionError("Failed to establish a new connection"))



def test_only_hyperliquid_public_info_post_can_use_read_failover(monkeypatch):
    monkeypatch.setattr(transport, '_routes', lambda: {'api.hyperliquid.xyz': ['', 'socks5h://one:1']})
    monkeypatch.delenv('POLYDATA_SNAPSHOT_SQLITE_PATH', raising=False)
    transport._COOLDOWNS.clear()
    transport._FAILURES.clear()
    send = Mock(side_effect=[requests.ReadTimeout(), reply()])
    monkeypatch.setattr(requests.Session, 'request', send)
    with transport.SourceSession() as session:
        assert session.post('https://api.hyperliquid.xyz/info', json={'type':'metaAndAssetCtxs'}, timeout=12).status_code == 200
        assert send.call_count == 2
        send.reset_mock(side_effect=True)
        send.side_effect = requests.ReadTimeout()
        with pytest.raises(requests.ReadTimeout):
            session.post('https://api.hyperliquid.xyz/exchange', json={'type':'order'}, timeout=12)
        assert send.call_count == 1


@pytest.mark.parametrize('module_name,class_name', [
    ('runtime.tech_panels_watcher', 'TechPanelsWatcher'),
    ('runtime.finance_watch_panels_watcher', 'FinanceWatchPanelsWatcher'),
])
def test_yahoo_pool_bounds_concurrency_and_reuses_thread_local_sessions(monkeypatch, module_name, class_name):
    import importlib
    from concurrent.futures import ThreadPoolExecutor
    from api.context import RuntimeResources
    from api.clients.http_client import _thread_session
    module = importlib.import_module(module_name)
    watcher = getattr(module, class_name).__new__(getattr(module, class_name))
    watcher._source_executor = ThreadPoolExecutor(max_workers=3)
    watcher._yahoo_resources = RuntimeResources()
    watcher._yahoo_context = {'_resources': watcher._yahoo_resources}
    watcher.requests = Mock()
    barrier = threading.Barrier(3, timeout=3)
    seen = {}
    def fetch(value):
        ctx = watcher.yahoo_context()
        session = _thread_session(ctx, requests)
        ident = threading.get_ident()
        previous = seen.setdefault(ident, session)
        assert session is previous
        barrier.wait()
        return value
    try:
        assert watcher.map_yahoo(fetch, range(6)) == list(range(6))
        assert len(seen) == 3
        assert len({id(s) for s in seen.values()}) == 3
    finally:
        watcher.close()
    assert watcher._yahoo_resources.stopped.is_set()


def test_recent_collector_failure_does_not_start_competing_api_acquisition(monkeypatch):
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    store = Mock()
    store.get.return_value = None
    store.get_stale.side_effect = lambda ns, key: {'lastAttemptAt':now,'expectedIntervalSeconds':600} if ns == 'seed-meta:tech' else None
    recover = Mock()
    monkeypatch.setattr(seed_recovery, 'recover_seed', recover)
    builder = Mock()
    seed_recovery.read_watch_seed(namespace='runtime:tech:big-tech-market-cap', cache_key='v1',
        panel_id='big-tech-market-cap', snapshot_store=store, redis_get=None, redis_set=None,
        builder=builder, ttl_seconds=600, owner_meta_namespace='seed-meta:tech')
    recover.assert_not_called()
    builder.assert_not_called()


def test_transport_preserves_explicit_urllib3_budget_and_connect_limit(monkeypatch, routed):
    send = Mock(return_value=reply())
    monkeypatch.setattr(requests.Session, 'request', send)
    with transport.SourceSession() as session:
        session.get('https://example.test', timeout=transport.Timeout(total=20, connect=6, read=18))
    timeout = send.call_args.kwargs['timeout']
    assert timeout.total == pytest.approx(20, abs=.01)
    assert timeout.connect_timeout == 6


def test_nws_collector_budget_is_separate_from_browser_wait():
    from api.context import RuntimeResources
    from api.services.natural_hazards import service, providers
    resources = RuntimeResources()
    try:
        deps = service.NaturalHazardDependencies.from_context({'_resources':resources,
            'http_json_get':Mock(), 'NWS_COLLECTOR_FETCH_BUDGET_SECONDS':20})
        assert deps.nws_fetch_budget_seconds == 20
        assert service.SOURCE_PROVIDER_DEADLINE_SECONDS == 6.5
        assert providers.nws.PROVIDER_FETCH_BUDGET_SECONDS == 5.5
    finally:
        resources.close()
