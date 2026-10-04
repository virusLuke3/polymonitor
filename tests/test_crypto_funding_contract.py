from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.services import crypto_funding_service as service
from api.services.crypto_funding import contracts, providers, universe

NOW = '2026-10-04T10:00:00Z'
MS = int(datetime.fromisoformat(NOW.replace('Z', '+00:00')).timestamp() * 1000)
NEXT = MS + 3_600_000


def settings():
    return SimpleNamespace(crypto_funding_watch_api_url='https://binance.test/fapi/v1/premiumIndex',
        crypto_funding_watch_bybit_api_url='https://bybit.test/v5/market/tickers',
        crypto_funding_watch_symbols=('BTCUSDT', 'ETHUSDT', 'TONUSDT'), gamma_api_base='https://gamma.test',
        crypto_funding_watch_ttl_seconds=15)


def make_context(assets=('BTC', 'ETH', 'HYPE', 'TON'), *, failures=(), periods=None, now=NOW):
    memory, calls = {}, []
    periods = periods or {}
    def get(url, params=None, **kwargs):
        calls.append((url, params))
        venue = 'Binance' if 'binance.test' in url else 'Bybit' if 'bybit.test' in url else 'Gamma'
        if venue in failures:
            raise TimeoutError('fixture failure')
        clock = int(datetime.fromisoformat(ctx['utc_now_iso']().replace('Z', '+00:00')).timestamp() * 1000)
        if url.endswith('exchangeInfo'):
            return {'symbols': [{'symbol': a + 'USDT', 'baseAsset': a, 'quoteAsset': 'USDT', 'marginAsset': 'USDT',
                'status': 'SETTLING' if a == 'TON' else 'TRADING', 'contractType': 'PERPETUAL'} for a in assets]}
        if url.endswith('fundingInfo'):
            return [{'symbol': a + 'USDT', 'fundingIntervalHours': periods.get(a, 8)} for a in assets]
        if url.endswith('premiumIndex'):
            return [{'symbol': a + 'USDT', 'lastFundingRate': '-0.0004' if a == 'BTC' else '0.0001',
                     'time': clock, 'nextFundingTime': clock + 3_600_000} for a in assets]
        if url.endswith('instruments-info'):
            return {'retCode': 0, 'time': clock, 'result': {'list': [
                {'symbol': a + 'USDT', 'baseCoin': a, 'quoteCoin': 'USDT', 'settleCoin': 'USDT',
                 'status': 'Closed' if a == 'TON' else 'Trading', 'contractType': 'LinearPerpetual',
                 'fundingInterval': periods.get(a, 8) * 60 if periods.get(a, 8) else None} for a in assets]}}
        if url.endswith('tickers'):
            return {'retCode': 0, 'time': clock, 'result': {'list': [
                {'symbol': a + 'USDT', 'fundingRate': '-0.0002' if a == 'BTC' else '0.0001',
                 'nextFundingTime': clock + 3_600_000} for a in assets]}}
        if url.endswith('/tags/slug/crypto'):
            return {'id': '21', 'slug': 'crypto'}
        if url.endswith('/events'):
            return [{'id': 'event-hype', 'slug': 'what-price-will-hyperliquid-hit', 'title': 'What price will Hyperliquid hit?',
                'active': True, 'tags': [{'slug': 'crypto-prices'}], 'markets': [
                    {'id': 'm1', 'question': 'Will Hyperliquid hit $50?', 'active': True, 'endDate': '2027-01-01T00:00:00Z'}]}]
        raise AssertionError(url)
    ctx = {'SETTINGS': settings(), 'http_json_get': get, 'utc_now_iso': lambda: now,
           'get_cached_json': lambda ns, key: memory.get((ns, key)),
           'set_cached_json': lambda ns, key, value, ttl: memory.__setitem__((ns, key), value)}
    return ctx, memory, calls


def test_only_trading_perpetuals_are_counted_and_signed_extreme_survives():
    ctx, _, _ = make_context()
    result = service.fetch_live_crypto_funding_watch_payload(ctx)
    assert result['status'] == 'ok'
    assert [a['asset'] for a in result['assets']][0] == 'HYPE'  # a relevant price market is first
    assert 'TON' not in {a['asset'] for a in result['assets']}
    assert any(a['asset'] == 'TON' and a['reason'] == 'no-trading-usdt-perpetual' for a in result['coverage']['unavailableAssets'])
    btc = next(a for a in result['assets'] if a['asset'] == 'BTC')
    assert btc['strongestFundingPercent8h'] == pytest.approx(-0.04)
    assert btc['consensusFundingPercent8h'] == pytest.approx(-0.03)
    assert btc['bias'] == 'shorts-pay'
    assert btc['spreadPercent8h'] == pytest.approx(0.02)
    bybit = next(q for q in btc['quotes'] if q['exchange'] == 'Bybit')
    assert bybit['quoteObservedAt'] is None
    assert bybit['sourceResponseAt'] == NOW
    assert bybit['timeBasis'] == 'provider-response'


def test_larger_qualified_universe_is_not_limited_to_eighteen():
    names = tuple(a for a in universe.CORE_ORDER[:35] if a != 'TON')
    ctx, _, _ = make_context(names)
    result = service.fetch_live_crypto_funding_watch_payload(ctx, limit=18)
    assert len(result['assets']) == len(names) > 18  # canonical acquisition is independent of the view limit
    assert result['coverage']['expectedQuotes'] == len(names) * 2
    assert result['coverage']['succeeded'] == len(names) * 2


def test_actual_period_controls_normalization_and_simple_annualization():
    ctx, _, _ = make_context(periods={'BTC': 4})
    result = service.fetch_live_crypto_funding_watch_payload(ctx)
    btc = next(a for a in result['assets'] if a['asset'] == 'BTC')
    quote = next(q for q in btc['quotes'] if q['exchange'] == 'Binance')
    assert quote['fundingRatePercent'] == pytest.approx(-0.04)
    assert quote['fundingRatePercent8h'] == pytest.approx(-0.08)
    assert quote['annualizedPercent'] == pytest.approx(-0.04 * 6 * 365)


def test_unknown_period_is_not_assumed_eight_hours():
    ctx, _, _ = make_context(periods={'BTC': None})
    result = service.fetch_live_crypto_funding_watch_payload(ctx)
    assert result['status'] == 'degraded'
    btc = next(a for a in result['assets'] if a['asset'] == 'BTC')
    assert all(q['annualizedPercent'] is None for q in btc['quotes'])
    assert btc['consensusFundingPercent8h'] is None


def test_one_source_failure_preserves_its_quotes_without_using_them_in_current_mean():
    ctx, _, _ = make_context()
    first = service.fetch_live_crypto_funding_watch_payload(ctx)
    getter = ctx['http_json_get']
    def failed(url, **kwargs):
        if url.endswith('/tickers'):
            raise TimeoutError('bybit unavailable')
        return getter(url, **kwargs)
    ctx['http_json_get'] = failed
    ctx['utc_now_iso'] = lambda: '2026-10-04T10:00:30Z'
    second = service.fetch_live_crypto_funding_watch_payload(ctx, previous=first)
    assert second['status'] == 'degraded'
    assert second['coverage']['retained'] == 3
    btc = next(a for a in second['assets'] if a['asset'] == 'BTC')
    assert btc['consensusFundingPercent8h'] == pytest.approx(-0.04)
    saved = next(q for q in btc['quotes'] if q['exchange'] == 'Bybit')
    assert saved['acquisitionState'] == 'retained'
    assert saved['updatedAt'] == NOW
    assert second['sourceDetails']['bybit']['lastSuccessAt'] == first['sourceDetails']['bybit']['lastSuccessAt']
    ctx['http_json_get'] = getter
    third = service.fetch_live_crypto_funding_watch_payload(ctx, previous=second)
    assert third['status'] == 'ok'
    assert third['coverage']['retained'] == 0


def test_all_sources_failure_does_not_advance_generated_or_success_time():
    ctx, _, _ = make_context()
    first = service.fetch_live_crypto_funding_watch_payload(ctx)
    ctx['http_json_get'] = lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError())
    ctx['utc_now_iso'] = lambda: '2026-10-04T10:00:30Z'
    result = service.fetch_live_crypto_funding_watch_payload(ctx, previous=first)
    assert result['status'] == 'stale'
    assert result['generatedAt'] == first['generatedAt']
    assert result['lastSuccessAt'] == first['lastSuccessAt']
    assert result['coverage']['succeeded'] == 0
    assert len(result['assets']) == len(first['assets'])
    ctx['utc_now_iso'] = lambda: '2026-10-04T10:16:00Z'
    assert not service.fetch_live_crypto_funding_watch_payload(ctx, previous=result)['assets']


def test_eligibility_refresh_removes_formerly_trading_contract_even_if_rate_still_returns():
    ctx, memory, _ = make_context(assets=('BTC', 'ETH', 'HYPE'))
    first = service.fetch_live_crypto_funding_watch_payload(ctx)
    original = ctx['http_json_get']
    def delisted(url, **kwargs):
        payload = original(url, **kwargs)
        if url.endswith('exchangeInfo'):
            for item in payload['symbols']:
                if item['baseAsset'] == 'BTC': item['status'] = 'SETTLING'
        if url.endswith('instruments-info'):
            for item in payload['result']['list']:
                if item['baseCoin'] == 'BTC': item['status'] = 'Closed'
        return payload
    memory.clear(); ctx['http_json_get'] = delisted
    result = service.fetch_live_crypto_funding_watch_payload(ctx, previous=first)
    assert 'BTC' not in {asset['asset'] for asset in result['assets']}


@pytest.mark.parametrize('rate', [None, '', float('nan'), float('inf'), '-Infinity', True])
def test_invalid_rates_are_not_zero_funding(rate):
    instrument = {'symbol': 'BTCUSDT', 'asset': 'BTC', 'eligible': True, 'status': 'TRADING', 'intervalHours': 8, 'checkedAt': NOW}
    assert contracts.normalize_quote({'symbol': 'BTCUSDT', 'lastFundingRate': rate, 'time': MS}, instrument,
        exchange='Binance', response_at=None, fetched_at=NOW) is None


def test_zero_funding_is_valid_for_an_eligible_instrument():
    instrument = {'symbol': 'BTCUSDT', 'asset': 'BTC', 'eligible': True, 'status': 'TRADING', 'intervalHours': 8, 'checkedAt': NOW}
    assert contracts.normalize_quote({'symbol': 'BTCUSDT', 'lastFundingRate': 0, 'time': MS}, instrument,
        exchange='Binance', response_at=None, fetched_at=NOW)['fundingRatePercent'] == 0


def test_bybit_business_errors_and_bad_clocks_are_rejected():
    with pytest.raises(ValueError):
        providers.bybit_rows({'retCode': 10006, 'result': {'list': []}})
    instrument = {'symbol': 'BTCUSDT', 'asset': 'BTC', 'eligible': True, 'status': 'Trading', 'intervalHours': 8, 'checkedAt': NOW}
    for clock in (None, '2026-10-04T09:00:00Z', '2026-10-04T11:00:00Z'):
        assert contracts.normalize_quote({'symbol': 'BTCUSDT', 'fundingRate': '0.0001'}, instrument,
            exchange='Bybit', response_at=clock, fetched_at=NOW) is None


def test_bybit_instruments_follow_pagination_and_preserve_actual_minutes():
    calls = []
    def get(url, params=None):
        calls.append(params)
        if len(calls) == 1:
            return {'retCode': 0, 'result': {'list': [], 'nextPageCursor': 'second'}}
        return {'retCode': 0, 'result': {'list': [{'symbol': 'HYPEUSDT', 'baseCoin': 'HYPE', 'status': 'Trading',
            'contractType': 'LinearPerpetual', 'quoteCoin': 'USDT', 'settleCoin': 'USDT', 'fundingInterval': 240}]}}
    catalog = providers.fetch_catalog('Bybit', get, base='https://bybit.test', now=NOW)
    assert calls[1]['cursor'] == 'second'
    assert catalog['instruments']['HYPEUSDT']['intervalHours'] == 4


def test_api_cold_start_does_not_request_exchanges_and_hot_reads_do_not_write_sqlite():
    ctx, memory, _ = make_context()
    ctx['http_json_get'] = Mock(side_effect=AssertionError('API must not collect'))
    ctx['SNAPSHOT_STORE'] = Mock(get_stale=lambda *args: None)
    assert service.get_crypto_funding_watch_snapshot(ctx)['status'] == 'warming'
    ctx['SNAPSHOT_STORE'].set.assert_not_called()
    cold, _, _ = make_context()
    payload = service.fetch_live_crypto_funding_watch_payload(cold)
    memory[(service.CRYPTO_FUNDING_NAMESPACE, service.build_crypto_funding_cache_key(ctx['SETTINGS']))] = payload
    result = service.get_crypto_funding_watch_snapshot(ctx, limit=1)
    assert len(result['assets']) == 1
    assert all(item['asset'] == result['assets'][0]['asset'] for item in result['items'])
    ctx['http_json_get'].assert_not_called()
    ctx['SNAPSHOT_STORE'].set.assert_not_called()
    ctx['utc_now_iso'] = lambda: '2026-10-04T10:02:00Z'
    result = service.get_crypto_funding_watch_snapshot(ctx)
    assert result['cacheMode'] == 'stale-seed' and result['status'] == 'stale'
    assert result['generatedAt'] == NOW


def test_market_binding_rejects_expired_markets_and_ambiguous_substrings():
    assert universe.event_assets({'title': 'Bitcoin Cash above $500'}, {'BTC', 'BCH'}) == {'BCH'}
    assert universe.event_assets({'title': 'Will SOLAR power expand?'}, {'SOL'}) == set()
    events = [{'id': '1', 'slug': 'bitcoin-price', 'title': 'Bitcoin price', 'tags': [{'slug': 'crypto-prices'}],
        'markets': [{'id': 'ended', 'endDate': '2026-10-03T00:00:00Z'}, {'id': 'live', 'endDate': '2027-01-01T00:00:00Z'}]}]
    result = universe.market_relations(events, eligible_assets={'BTC'}, now=NOW)
    assert result['BTC']['priceMarketCount'] == 1
    assert result['BTC']['relatedMarkets'][0]['id'] == 'live'


def test_gamma_failures_do_not_block_quotes_and_have_retry_cooldown():
    ctx, _, calls = make_context(failures=('Gamma',))
    first = service.fetch_live_crypto_funding_watch_payload(ctx)
    assert first['status'] == 'ok'
    assert first['marketUniverse']['status'] == 'unavailable'
    before = sum('gamma.test' in url for url, _ in calls)
    service.fetch_live_crypto_funding_watch_payload(ctx)
    assert sum('gamma.test' in url for url, _ in calls) == before


@pytest.mark.parametrize('title', [
    'One day after token launch: what will the market cap be?',
    'Will the market cap be higher than one billion?',
    'What will TOKEN FDV be one day after launch?',
    'Will Robinhood be first to list tokenized stocks in the US?',
])
def test_ordinary_words_do_not_bind_venue_ticker_symbols(title):
    assert universe.event_assets({'title': title}, {'THE', 'ONE', 'TOKEN', 'CAP', 'HIGH', 'FDV', 'US'}) == set()


def test_explicit_symbols_and_long_asset_names_bind_without_alias_duplicates():
    assert universe.event_assets({'title': 'Will $ONE reach $1?'}, {'ONE'}) == {'ONE'}
    assert universe.event_assets({'title': 'Will Bitcoin Cash and HYPE outperform Bitcoin?'}, {'BTC', 'BCH', 'HYPE'}) == {'BCH', 'HYPE', 'BTC'}
    assert universe.event_assets({'title': 'What price will Pump.fun hit?'}, {'PUMP', 'PUMPFUN'}) == {'PUMP'}
    assert universe.event_assets({'title': 'Can a coin render a better story near the launch?'}, {'RENDER', 'IP', 'NEAR'}) == set()


def test_slow_gamma_job_is_independent_and_not_duplicated_between_quote_cycles():
    ctx, _, calls = make_context()
    original = ctx['http_json_get']
    entered, release = Event(), Event()
    def slow(url, **kwargs):
        if url.endswith('/tags/slug/crypto'):
            entered.set()
            assert release.wait(3)
        return original(url, **kwargs)
    with ThreadPoolExecutor(max_workers=1) as market_pool:
        ctx.update(http_json_get=slow, funding_market_executor=market_pool, funding_market_jobs={})
        try:
            first = service.fetch_live_crypto_funding_watch_payload(ctx)
            assert entered.wait(1)
            assert first['coverage']['succeeded'] == 6
            assert first['marketUniverse']['status'] == 'warming'
            pending = next(iter(ctx['funding_market_jobs'].values()))
            assert not pending.done()
            second = service.fetch_live_crypto_funding_watch_payload(ctx, previous=first)
            assert second['coverage']['succeeded'] == 6
            assert next(iter(ctx['funding_market_jobs'].values())) is pending
        finally:
            release.set()
        pending.result(timeout=2)
        third = service.fetch_live_crypto_funding_watch_payload(ctx, previous=second)
        assert third['marketUniverse']['status'] == 'ok'
        assert third['assets'][0]['asset'] == 'HYPE'
        assert sum(url.endswith('/tags/slug/crypto') for url, _ in calls) == 1


def test_multi_asset_event_does_not_bind_every_sibling_question_to_every_asset():
    event = {'id': 'multi', 'slug': 'btc-or-eth', 'title': 'Will Bitcoin or Ethereum hit the target first?',
        'tags': [{'slug': 'crypto-prices'}], 'markets': [
            {'id': 'btc', 'question': 'Will Bitcoin hit the target first?', 'endDate': '2027-01-01T00:00:00Z'},
            {'id': 'eth', 'question': 'Will Ethereum hit the target first?', 'endDate': '2027-01-01T00:00:00Z'}]}
    result = universe.market_relations([event], eligible_assets={'BTC', 'ETH'}, now=NOW)
    assert [m['id'] for m in result['BTC']['relatedMarkets']] == ['btc']
    assert [m['id'] for m in result['ETH']['relatedMarkets']] == ['eth']
