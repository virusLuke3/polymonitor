from __future__ import annotations

import threading
from datetime import datetime, timezone
from unittest.mock import patch

from api.clients import market_data_client
from api.services import commodities_service, runtime_service
from test_market_data_client import make_chart_payload, make_context
from test_market_group_seed_watcher import MarketGroupSeedWatcherTestCase as _WatcherFixture

NOW = "2026-10-03T03:20:00Z"
ENTRIES = [("gold", "GOLD", "GC=F"), ("oil", "OIL", "CL=F")]


def quote(symbol="GC=F", **extra):
    return {"symbol": symbol, "price": 2400., "fetchedAt": NOW, "quoteAt": "2026-10-02T20:00:00Z", **extra}


def test_daily_change_uses_daily_previous_close_not_chart_baseline():
    raw = make_chart_payload(symbol="^VIX", current=15.31, previous=16.07, closes=[16., 15.31])
    meta = raw["chart"]["result"][0]["meta"]
    meta.update(previousClose=16.39, regularMarketTime=1790972101, instrumentType="INDEX")
    result = market_data_client.get_yahoo_market_snapshot(make_context(raw), "^VIX")
    assert result["changePercent"] == -4.73  # compatibility for other consumers
    assert result["dailyChangePercent"] == -6.59
    assert result["changeBasis"] == "previous-close"
    assert result["quoteAt"] == "2026-10-02T20:15:01Z"
    assert result["fetchedAt"] != result["quoteAt"]


def test_missing_daily_reference_and_quote_clock_remain_unknown():
    raw = make_chart_payload(symbol="GC=F", current=2400, previous=2000, closes=[2100, 2400])
    result = market_data_client.get_yahoo_market_snapshot(make_context(raw), "GC=F")
    assert result["dailyChangePercent"] is None
    assert result["changeBasis"] == "unknown"
    assert result["quoteAt"] is None
    assert result["marketState"] == "unknown"


def test_incompatible_daily_scale_does_not_turn_chart_change_into_daily_change():
    raw = make_chart_payload(symbol="ZR=F", current=12.45, previous=1200, closes=[12.5, 12.45])
    raw["chart"]["result"][0]["meta"]["previousClose"] = 1250
    assert market_data_client.get_yahoo_market_snapshot(make_context(raw), "ZR=F")["dailyChangePercent"] is None


def test_source_trading_window_distinguishes_open_closed_and_obsolete_metadata():
    now = datetime.now(timezone.utc).timestamp()
    def metadata(start, end):
        return market_data_client._quote_metadata({"currentTradingPeriod": {"regular": {"start": start, "end": end}}}, 10., lambda v: v)
    assert metadata(now - 300, now + 300)["marketState"] == "open"
    assert metadata(now - 86400, now - 3600)["marketState"] == "closed"
    assert metadata(now - 10 * 86400, now - 9 * 86400)["marketState"] == "unknown"


def test_partial_scan_preserves_only_failed_symbol_and_original_quote_clock():
    old = {"items": [quote(), quote("CL=F", fetchedAt="2026-10-03T03:19:00Z")], "generatedAt": "2026-10-03T03:19:00Z"}
    result = commodities_service.merge_snapshot({"items": [quote(price=2410.)], "generatedAt": NOW}, old, ENTRIES, NOW)
    assert result["status"] == "degraded"
    assert result["coverage"] == {"expected": 2, "succeeded": 1, "retained": 1, "missing": 0,
                                  "failedSymbols": ["CL=F"], "retainedSymbols": ["CL=F"], "missingSymbols": []}
    assert result["items"][1]["fetchedAt"] == "2026-10-03T03:19:00Z"
    assert result["items"][1]["acquisitionState"] == "retained"


def test_full_failure_does_not_advance_snapshot_clock_or_keep_unbounded_quotes():
    old = {"items": [quote(fetchedAt="2026-10-03T03:00:00Z")], "generatedAt": "2026-10-03T03:00:00Z"}
    result = commodities_service.merge_snapshot({"items": [], "generatedAt": NOW}, old, ENTRIES, NOW)
    assert result["generatedAt"] == old["generatedAt"]
    assert result["items"] == []
    assert result["coverage"]["succeeded"] == 0
    assert result["coverage"]["missing"] == 2
    assert commodities_service.seeded_response(result, NOW)["status"] == "stale"


def test_invalid_price_is_not_a_successful_quote():
    result = commodities_service.merge_snapshot({"items": [quote(price=float("nan")), quote("CL=F", price=None)], "generatedAt": NOW}, {}, ENTRIES, NOW)
    assert result["coverage"]["succeeded"] == 0
    assert result["status"] == "degraded"


def test_read_through_recovery_is_nonblocking_and_deduplicated():
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def recover():
        entered.set()
        release.wait(3)
        finished.set()
    with patch.object(commodities_service, "_last_recovery_attempt", float("-inf")):
        try:
            assert commodities_service.recover_seed(recover)
            assert entered.wait(1)
            assert not commodities_service.recover_seed(recover)
        finally:
            release.set()
            assert finished.wait(1)
            # Wait for the worker's finally block to release ownership.
            with commodities_service._recovery_lock:
                pass
        assert not commodities_service.recover_seed(recover)  # 30s cooldown


def test_failed_watcher_does_not_claim_new_success_time():
    case = _WatcherFixture()
    try:
        watcher, redis = case.make_watcher()
        with patch.object(runtime_service, "fetch_live_market_group_payload", side_effect=RuntimeError("source failed")):
            result = watcher.run_component(panel_id="commodities-watch", kind="commodities", items=ENTRIES)
        import json
        meta = json.loads(redis.get("polydata:seed-meta:markets:commodities-watch"))
        assert result["status"] == "degraded"
        assert meta["lastSuccessAt"] is None
    finally:
        case.doCleanups()


def test_api_returns_overdue_seed_immediately_and_schedules_bounded_recovery():
    from types import SimpleNamespace
    old = {"kind": "commodities", "items": [quote()], "generatedAt": "2026-10-03T03:00:00Z", "status": "ok"}
    ctx = {"utc_now_iso": lambda: NOW, "get_cached_json": lambda *args: old,
           "SNAPSHOT_STORE": SimpleNamespace(set=lambda *args: None), "FINANCE_RUNTIME_TTL_SECONDS": 300}
    with patch.object(commodities_service, "recover_seed") as schedule, patch.object(runtime_service, "fetch_live_market_group_payload") as fetch:
        response = runtime_service.get_market_group_snapshot(ctx, ENTRIES, kind="commodities")
    schedule.assert_called_once()
    fetch.assert_not_called()
    assert response["status"] == "stale"
    assert response["generatedAt"] == old["generatedAt"]
    assert response["items"] == old["items"]
