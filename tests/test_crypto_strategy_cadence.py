from collections import Counter

import pytest

from api.services.crypto_strategy import providers
from api.services.crypto_strategy.cadence import SourceCadence


def test_slow_provider_attempts_are_shared_without_advancing_observation_clocks(monkeypatch):
    calls = Counter()
    def venue(get, base, asset, now, cadence):
        calls['venue'] += 1
        return {'asset': asset, 'observedAt': now}
    def options(get, asset, now):
        calls['options'] += 1
        return {'asset': asset, 'observedAt': now, 'expiries': []}
    def stable(get, now):
        calls['stable'] += 1
        return [{'receivedAt': now, 'price': 1}]
    monkeypatch.setattr(providers, 'venue_asset', venue)
    monkeypatch.setattr(providers, 'options', options)
    monkeypatch.setattr(providers, 'stablecoins', stable)
    cadence = SourceCadence()
    def collect(now):
        return providers.collect(None, bybit_base='fixture', reference_url='', now=now, cadence=cadence)
    first = collect(1_000_000)
    first['stablecoins'][0]['receivedAt'] = -1  # Consumer mutation cannot rewrite the retained observation.
    second = collect(1_030_000)
    assert calls == {'venue': 8, 'options': 2, 'stable': 1}
    assert second['stablecoins'][0]['receivedAt'] == 1_000_000
    assert second['options']['BTC']['observedAt'] == 1_000_000
    assert second['assets']['BTC']['observedAt'] == 1_030_000
    collect(1_060_000)
    assert calls['stable'] == 2 and calls['options'] == 2
    third = collect(1_300_000)
    assert calls['options'] == 4
    assert third['options']['BTC']['observedAt'] == 1_300_000


def test_failed_provider_waits_its_budget_and_can_recover():
    cadence = SourceCadence()
    calls = []
    def fail():
        calls.append('failed')
        raise OSError('source unavailable')
    with pytest.raises(OSError, match='unavailable'):
        cadence.read('options', 1000, 300_000, fail)
    with pytest.raises(OSError, match='SOURCE_RETRY_WAIT'):
        cadence.read('options', 31_000, 300_000, fail)
    assert calls == ['failed']
    assert cadence.read('options', 301_000, 300_000, lambda: {'observedAt': 301_000}) == {'observedAt': 301_000}


def test_history_cadence_keeps_fast_reads_and_never_promotes_cached_open_candles():
    cadence = SourceCadence()
    calls = Counter()
    def get(url, params):
        endpoint = url.split('/market/')[1]
        calls[endpoint] += 1
        rows = [['60000', '1', '1', '1', '99'], ['0', '1', '1', '1', '100']] if endpoint == 'kline' else []
        return {'retCode': 0, 'time': 110_000, 'result': {'list': rows}}
    first = providers.venue_asset(get, 'https://fixture', 'BTC', 110_000, cadence)
    second = providers.venue_asset(get, 'https://fixture', 'BTC', 140_000, cadence)
    assert first['spotHistory'] == second['spotHistory'] == [{'t': 60_000, 'v': 100.0}]
    assert calls['tickers'] == 4 and calls['recent-trade'] == 2 and calls['orderbook'] == 2
    assert calls['kline'] == 2 and calls['open-interest'] == 1 and calls['funding/history'] == 1
    providers.venue_asset(get, 'https://fixture', 'BTC', 410_000, cadence)
    assert calls['open-interest'] == 2 and calls['funding/history'] == 1


def test_overview_waits_for_scheduled_collector_without_early_read_through(monkeypatch):
    from types import SimpleNamespace
    from api.services import runtime_service, commodities_service, seed_recovery
    now = "2026-11-03T10:05:00Z"
    snapshot = {"kind": "crypto", "status": "ok", "generatedAt": "2026-11-03T10:00:00Z", "items": []}
    monkeypatch.setattr(runtime_service, "_dependencies", lambda ctx: SimpleNamespace(finance_runtime_ttl_seconds=300, utc_now_iso=lambda: now))
    monkeypatch.setattr(runtime_service, "_read_seeded_snapshot", lambda *a, **kw: snapshot)
    recoveries = []
    monkeypatch.setattr(commodities_service, "recover_seed", lambda *a: recoveries.append("commodity"))
    monkeypatch.setattr(seed_recovery, "recover_seed", lambda *a: recoveries.append("crypto"))
    for kind in ("crypto", "commodities"):
        result = runtime_service.get_market_group_snapshot({}, [], kind=kind)
        assert result["generatedAt"] == snapshot["generatedAt"]
        assert result.get("status") != "stale"
    assert recoveries == []
    now = "2026-11-03T10:16:00Z"
    assert runtime_service.get_market_group_snapshot({}, [], kind="crypto")["status"] == "warming"
    assert runtime_service.get_market_group_snapshot({}, [], kind="commodities")["status"] == "stale"
    assert recoveries == ["crypto", "commodity"]
