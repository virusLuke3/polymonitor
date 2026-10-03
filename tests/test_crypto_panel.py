from datetime import datetime, timezone
from api.clients import market_data_client
from api.services import crypto_service, runtime_service
from test_market_data_client import make_chart_payload, make_context
from runtime import market_group_watcher

NOW = "2026-10-03T06:00:00Z"
ENTRIES = [("btc", "BTC", "BTC-USD"), ("eth", "ETH", "ETH-USD")]


def quote(symbol="BTC-USD", **extra):
    return {"id": symbol, "label": symbol, "symbol": symbol, "price": 110., "quoteAt": NOW, "fetchedAt": NOW, **extra}


def test_rolling_change_uses_full_history_and_provider_clock():
    raw = make_chart_payload(symbol="BTC-USD", current=110, previous=50, closes=[100] + [105] * 287 + [110])
    result = raw["chart"]["result"][0]
    stamp = int(datetime.fromisoformat(NOW.replace("Z", "+00:00")).timestamp())
    result["timestamp"] = [stamp - 86400 + i * 300 for i in range(289)]
    result["meta"]["regularMarketTime"] = stamp
    data = market_data_client.get_yahoo_market_snapshot(make_context(raw), "BTC-USD", interval="5m")
    assert data["rollingChangePercent24h"] == 10
    assert data["reference24hAt"] == "2026-10-02T06:00:00Z"
    assert len(data["points"]) == 48
    assert data["changePercent"] != data["rollingChangePercent24h"]


def test_missing_reference_never_uses_chart_baseline_as_24h_change():
    raw = make_chart_payload(symbol="BTC-USD", current=110, previous=50, closes=[100, 110])
    raw["chart"]["result"][0]["meta"]["regularMarketTime"] = int(datetime.fromisoformat(NOW.replace("Z", "+00:00")).timestamp())
    data = market_data_client.get_yahoo_market_snapshot(make_context(raw), "BTC-USD", interval="5m")
    assert data["rollingChangePercent24h"] is None
    assert data["reference24hAt"] is None


def test_partial_acquisition_keeps_original_clock_per_failed_symbol():
    old = {"generatedAt": "2026-10-03T05:59:00Z", "items": [quote("ETH-USD", fetchedAt="2026-10-03T05:59:00Z")]}
    data = crypto_service.merge_snapshot({"generatedAt": NOW, "items": [quote()]}, old, ENTRIES, NOW)
    assert data["status"] == "degraded"
    assert data["coverage"]["succeeded"] == 1
    assert data["coverage"]["retained"] == 1
    assert data["items"][1]["fetchedAt"] == old["generatedAt"]
    assert data["items"][1]["acquisitionState"] == "retained"


def test_full_failure_does_not_advance_seed_clock_or_retain_expired_prices():
    old = {"generatedAt": "2026-10-03T05:40:00Z", "items": [quote(fetchedAt="2026-10-03T05:40:00Z")]}
    data = crypto_service.merge_snapshot({"generatedAt": NOW, "items": []}, old, ENTRIES, NOW)
    assert data["generatedAt"] == old["generatedAt"]
    assert data["items"] == []
    assert data["coverage"]["missing"] == 2


def test_missing_ancient_or_invalid_quote_cannot_be_rejuvenated():
    for extra in [{"quoteAt": None}, {"quoteAt": "2026-10-02T06:00:00Z"}, {"price": float("nan")}]:
        data = crypto_service.merge_snapshot({"generatedAt": NOW, "items": [quote(**extra)]}, {}, ENTRIES, NOW)
        assert data["coverage"]["succeeded"] == 0
        assert data["items"] == []


def test_crypto_is_not_marked_closed_on_weekends():
    assert crypto_service.usable_quote(quote(), NOW)  # Saturday, 24/7 market


def test_live_crypto_preserves_quote_metadata_and_does_not_fabricate_daily_change():
    ctx = {"get_yahoo_market_snapshot": lambda *a, **k: {"price": 110., "quoteAt": NOW, "fetchedAt": NOW, "changePercent": 120., "points": []},
           "utc_now_iso": lambda: NOW}
    data = runtime_service.fetch_live_market_group_payload(ctx, ENTRIES[:1], kind="crypto")
    assert data["items"][0]["changePercent"] is None
    assert data["items"][0]["quoteAt"] == NOW
    assert data["items"][0]["changeBasis"] == "unknown"


def test_watcher_does_not_restore_expired_crypto_after_domain_retention(monkeypatch):
    watcher = market_group_watcher.MarketGroupWatcher.__new__(market_group_watcher.MarketGroupWatcher)
    old = {"kind": "crypto", "generatedAt": "2026-10-03T05:40:00Z", "items": [quote(fetchedAt="2026-10-03T05:40:00Z")]}
    saved = []
    watcher.load_previous_payload = lambda *args, **kwargs: old
    watcher.service_context = lambda: {}
    watcher.store_payload = lambda namespace, key, payload, **kw: saved.append(payload)
    watcher.store_seed_meta = lambda **kwargs: None
    watcher.interval_seconds = 60
    monkeypatch.setattr(market_group_watcher, "utc_now_iso", lambda: NOW)
    monkeypatch.setattr(runtime_service, "fetch_live_market_group_payload", lambda *a, **k: {"items": [], "generatedAt": NOW})
    watcher.run_component(panel_id="crypto-watch", kind="crypto", items=ENTRIES)
    assert saved[-1]["items"] == []
    assert saved[-1]["generatedAt"] == old["generatedAt"]
