from __future__ import annotations
from conftest import missing_route_dependency
from api.routes import runtime_panels as _route_runtime_panels

from api.routes.runtime_panels import RuntimePanelRouteDependencies

import json
import pytest
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import patch

from flask import Flask


from api.routes.runtime_panels import create_runtime_panels_blueprint
from api.services import polymarket_macro_map_service
from runtime import polymarket_macro_map_watcher
from runtime.snapshot_store import SnapshotStore


class FakeLogger:
    def exception(self, *args, **kwargs) -> None:
        return None

    def warning(self, *args, **kwargs) -> None:
        return None

    def info(self, *args, **kwargs) -> None:
        return None


class FakeApp:
    logger = FakeLogger()


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value
        if ex is not None:
            self.expiries[key] = ex

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.set(key, value, ex=ttl)


def catalog_market(market_id=1, event_id="evt-cpi", **overrides):
    return {
        "id": market_id, "gammaMarketId": str(market_id + 100), "eventId": event_id,
        "eventTitle": "May CPI inflation", "eventSlug": "may-cpi-inflation",
        "title": "Will May CPI inflation be 0.3% or higher?", "slug": "may-cpi-03",
        "endDate": "2026-05-13T12:30:00Z", "tags": ["inflation"],
        "latestYesPrice": "0.57", "latestNoPrice": "0.43", "volume24h": 9000,
        "conditionId": "cond-1", "priceProjectionValid": True, "supportsYesNoWording": True,
        "outcomeSemanticsStatus": "projected",
        "outcomePrices": [{"tokenId": f"{market_id}-yes", "sourceLabel": "Yes", "sourceIndex": 0, "price": overrides.get("latestYesPrice", ".57")},
                          {"tokenId": f"{market_id}-no", "sourceLabel": "No", "sourceIndex": 1, "price": overrides.get("latestNoPrice", ".43")}],
        "sourceObservedAt": "2026-05-10T23:55:00Z", "sourceUpdatedAt": "2026-05-10T23:54:00Z",
        **overrides,
    }


def make_settings(snapshot_path: str = "", *, search_terms=()) -> SimpleNamespace:
    return SimpleNamespace(redis_url="redis://test/0", redis_prefix="polydata:",
        snapshot_sqlite_path=snapshot_path, gamma_api_base="https://gamma.example",
        polymarket_macro_map_source_url="https://gamma.example",
        polymarket_macro_map_ttl_seconds=180, polymarket_macro_map_search_terms=search_terms)


def make_context(*, http_json_get=None, read_market_catalog=None, search_terms=(), snapshot_store=None, cached=None):
    cached = cached if cached is not None else {}
    return {"SETTINGS": make_settings(search_terms=search_terms), "app": FakeApp(),
        "utc_now_iso": lambda: "2026-05-11T00:00:00Z",
        "http_json_get": http_json_get or (lambda *args, **kwargs: pytest.fail("external HTTP is forbidden")),
        "read_market_catalog": read_market_catalog or (lambda **kw: {
            "items": [catalog_market()], "coverage": {"truncated": False, "candidateCount": 1}}),
        "SNAPSHOT_STORE": snapshot_store,
        "get_cached_json": lambda namespace, key: cached.get((namespace, key)),
        "set_cached_json": lambda *args: pytest.fail("GET must not write snapshots")}


def test_build_groups_real_event_identity_and_keeps_quote_clocks():
    rows = [catalog_market(), catalog_market(2), catalog_market(3, "different-event-same-title")]
    ctx = make_context(read_market_catalog=lambda **kw: {"items": rows, "coverage": {"truncated": True}})
    payload = polymarket_macro_map_service.build_polymarket_macro_map_payload(ctx)
    assert payload["status"] == "degraded"
    assert payload["sources"] == {"marketCatalog": "ok"}
    assert payload["summary"]["activeCount"] == 2
    assert {row["eventId"] for row in payload["items"]} == {"evt-cpi", "different-event-same-title"}
    item = payload["items"][0]
    assert item["outcomeCount"] == 2
    assert item["volume24h"] is None and item["liquidity"] is None
    assert item["observedMarketVolume24h"] == 18000
    assert item["eventMembershipComplete"] is False
    assert item["endDateScope"] == "earliest-observed-market"
    assert item["topOutcomes"][0]["yesPrice"] == .57
    assert payload["sourceObservedAt"] == "2026-05-10T23:55:00Z"
    assert item["topOutcomes"][0]["sourceUpdatedAt"] == "2026-05-10T23:54:00Z"
    assert payload["generatedAt"] == "2026-05-11T00:00:00Z"


def test_unverified_prices_remain_unknown_and_zero_is_not_missing():
    rows = [catalog_market(latestYesPrice="0", latestNoPrice="1"),
            catalog_market(2, priceProjectionValid=False, latestYesPrice=".99")]
    ctx = make_context(read_market_catalog=lambda **kw: {"items": rows, "coverage": {}})
    payload = polymarket_macro_map_service.build_polymarket_macro_map_payload(ctx)
    assert payload["status"] == "degraded"
    assert [r["yesPrice"] for r in payload["items"][0]["topOutcomes"]] == [0, None]
    assert payload["coverage"]["unpricedMarketCount"] == 1


def test_short_macro_terms_do_not_match_inside_unrelated_words():
    row = catalog_market(eventTitle="Edmonton Oilers win?", eventSlug="oilers", title="Oilers win?", tags=[])
    ctx = make_context(read_market_catalog=lambda **kw: {"items": [row], "coverage": {}})
    assert polymarket_macro_map_service.build_polymarket_macro_map_payload(ctx)["items"] == []


def test_up_down_uses_actual_token_labels_and_prices_without_yes_mapping():
    row = catalog_market(supportsYesNoWording=False, latestYesPrice=None, latestNoPrice=None,
        semanticMode="up_down", outcomePrices=[
            {"tokenId": "down-token", "sourceLabel": "Down", "sourceIndex": 1, "price": "1"},
            {"tokenId": "up-token", "sourceLabel": "Up", "sourceIndex": 0, "price": "0"}])
    payload = polymarket_macro_map_service.build_polymarket_macro_map_payload(
        make_context(read_market_catalog=lambda **kw: {"items": [row], "coverage": {}}))
    outcome = payload["items"][0]["topOutcomes"][0]
    assert outcome["yesPrice"] is None and outcome["noPrice"] is None
    assert outcome["price"] == 0 and outcome["sourceLabel"] == "Up"
    assert outcome["tokenId"] == "up-token"
    assert outcome["sourceOutcomes"] == [
        {"tokenId": "up-token", "sourceLabel": "Up", "sourceIndex": 0, "price": 0.0},
        {"tokenId": "down-token", "sourceLabel": "Down", "sourceIndex": 1, "price": 1.0}]
    assert payload["coverage"]["unpricedMarketCount"] == 0


def test_missing_event_identity_is_not_fabricated():
    row = catalog_market(eventId=None)
    ctx = make_context(read_market_catalog=lambda **kw: {"items": [row], "coverage": {}})
    assert polymarket_macro_map_service.build_polymarket_macro_map_payload(ctx)["items"] == []


def test_public_get_without_seed_never_reads_catalog_or_http():
    ctx = make_context(read_market_catalog=lambda **kw: pytest.fail("GET collected data"))
    payload = polymarket_macro_map_service.get_polymarket_macro_map_snapshot(ctx)
    assert payload["status"] == "warming" and payload["items"] == []


def test_limit_is_clamped_to_default_item_limit():
    payload = sample_payload()
    payload["items"] = [{"eventId": str(n), "sourceObservedAt": "2026-05-10T23:55:00Z"} for n in range(20)]
    result = polymarket_macro_map_service.normalize_polymarket_macro_map_payload(payload, ctx=make_context(), limit=99)
    assert len(result["items"]) == polymarket_macro_map_service.DEFAULT_ITEM_LIMIT


def test_catalog_transport_or_shape_failures_propagate_to_owner():
    def fail(**kw):
        raise TimeoutError("database read failed")
    with pytest.raises(TimeoutError):
        polymarket_macro_map_service.build_polymarket_macro_map_payload(make_context(read_market_catalog=fail))
    with pytest.raises(ValueError):
        polymarket_macro_map_service.build_polymarket_macro_map_payload(make_context(read_market_catalog=lambda **kw: []))


def test_stale_snapshot_can_be_returned_by_cache_layer():
    stale = {
        "generatedAt": "2026-05-10T00:00:00Z",
        "status": "ok",
        "sources": {"gammaEvents": "ok"},
        "summary": {"activeCount": 1, "topCategory": "CPI / Inflation", "signal": "STALE CPI CLUSTER"},
        "categories": [],
        "items": [{"eventId": "stale", "title": "Stale CPI market"}],
        "cacheMode": "stale-seed",
    }

    class StaleOnlyStore:
        def get(self, namespace, cache_key):
            return None

        def get_stale(self, namespace, cache_key):
            return stale

        def set(self, *args, **kwargs):
            return None

    store = StaleOnlyStore()
    ctx = make_context(snapshot_store=store)

    payload = polymarket_macro_map_service.get_polymarket_macro_map_snapshot(ctx, limit=8)

    assert payload["cacheMode"] == "stale-seed"
    assert payload["items"] == []
    assert payload["status"] == "expired"
    assert store.get_stale("unused", "unused")["items"][0]["eventId"] == "stale"


def test_api_reads_seeded_sqlite_snapshot_without_live_fetch(tmp_path):
    seeded = {
        "generatedAt": "2026-05-11T00:00:00Z",
        "status": "ok",
        "sources": {"gammaEvents": "ok"},
        "summary": {"activeCount": 1, "topCategory": "CPI / Inflation", "signal": "CPI CLUSTER ACTIVE"},
        "categories": [],
        "items": [{"eventId": "seeded", "title": "Seeded CPI market", "sourceObservedAt": "2026-05-10T23:55:00Z"}],
        "cacheMode": "seeded",
    }
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    store.set(
        polymarket_macro_map_service.MACRO_MAP_SNAPSHOT_NAMESPACE,
        polymarket_macro_map_service.MACRO_MAP_CACHE_KEY,
        seeded,
        300,
    )
    ctx = make_context(
        snapshot_store=store,
        http_json_get=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live fetch should not run")),
    )

    payload = polymarket_macro_map_service.get_polymarket_macro_map_snapshot(ctx, limit=8)

    assert payload["cacheMode"] == "sqlite-seed"
    assert payload["items"][0]["eventId"] == "seeded"


def make_watcher(tmp_path) -> tuple[polymarket_macro_map_watcher.PolymarketMacroMapWatcher, FakeRedis]:
    fake_redis = FakeRedis()
    settings = make_settings(str(tmp_path / "snapshots.sqlite3"))
    redis_module = SimpleNamespace(from_url=lambda *args, **kwargs: fake_redis)
    with (
        patch.object(polymarket_macro_map_watcher, "redis", redis_module),
    ):
        watcher = polymarket_macro_map_watcher.PolymarketMacroMapWatcher(
            redis_url=settings.redis_url,
            redis_prefix=settings.redis_prefix,
            snapshot_sqlite_path=settings.snapshot_sqlite_path,
            settings=settings,
            interval_seconds=180,
        )
    return watcher, fake_redis


def sample_payload(item_id: str = "macro-1") -> Dict[str, Any]:
    return {
        "generatedAt": "2026-05-11T00:00:00Z",
        "source": "Polymarket Gamma API",
        "sourceUrl": "https://gamma.example",
        "status": "ok",
        "sources": {"gammaEvents": "ok"},
        "summary": {"activeCount": 1, "topCategory": "CPI / Inflation", "signal": "CPI CLUSTER ACTIVE"},
        "categories": [],
        "items": [{"eventId": item_id, "title": "May CPI market"}],
    }


def test_watcher_stores_payload_snapshot_and_seed_meta(tmp_path):
    watcher, fake_redis = make_watcher(tmp_path)

    with patch.object(
        polymarket_macro_map_service, "build_polymarket_macro_map_payload", return_value=sample_payload()
    ):
        result = watcher.run_once()

    assert result["status"] == "stored"
    stored = json.loads(fake_redis.get(watcher.redis_key()) or "{}")
    assert stored["cacheMode"] == "seeded"
    assert stored["items"][0]["eventId"] == "macro-1"
    snapshot = watcher.snapshot_store.get_stale(watcher.namespace(), watcher.cache_key())
    assert snapshot["items"][0]["eventId"] == "macro-1"
    meta = json.loads(fake_redis.get("polydata:seed-meta:macro:polymarket-macro-map") or "{}")
    assert meta["status"] == "ok"
    assert meta["recordCount"] == 1
    assert meta["serviceName"] == "polydata-polymarket-macro-map-seed.service"


def test_watcher_preserves_previous_snapshot_when_new_payload_is_empty(tmp_path):
    watcher, fake_redis = make_watcher(tmp_path)
    previous = {**sample_payload("old-macro"), "cacheMode": "seeded"}
    watcher.store_payload(previous)

    empty_payload = {**sample_payload("empty"), "status": "empty", "items": [], "summary": {"activeCount": 0}}
    with patch.object(polymarket_macro_map_service, "build_polymarket_macro_map_payload", return_value=empty_payload):
        result = watcher.run_once()

    assert result["status"] == "preserved"
    stored = json.loads(fake_redis.get(watcher.redis_key()) or "{}")
    assert stored["items"][0]["eventId"] == "old-macro"
    meta = json.loads(fake_redis.get("polydata:seed-meta:macro:polymarket-macro-map") or "{}")
    assert meta["status"] == "preserved"
    assert "Preserved previous snapshot" in meta["errorSummary"]


def test_watcher_failed_read_keeps_original_clock_and_safe_error(tmp_path):
    watcher, _ = make_watcher(tmp_path)
    with patch.object(polymarket_macro_map_service, "build_polymarket_macro_map_payload", side_effect=TimeoutError("private detail")):
        assert watcher.run_once()["error"] == "TimeoutError"
        first = watcher.seed_meta_store.load("seed-meta:macro", "polymarket-macro-map")
        assert first["lastSuccessAt"] is None
        watcher.store_payload(sample_payload())
        result = watcher.run_once()
    assert result["status"] == "preserved"
    stored = watcher.snapshot_store.get_stale(watcher.namespace(), watcher.cache_key())
    assert stored["generatedAt"] == sample_payload()["generatedAt"]
    assert stored["status"] == "stale"
    meta = watcher.seed_meta_store.load("seed-meta:macro", "polymarket-macro-map")
    assert meta["errorSummary"] == "TimeoutError"


def test_watcher_releases_connection_pool_even_when_catalog_fails(tmp_path, monkeypatch):
    watcher, _ = make_watcher(tmp_path)
    watcher.settings.database = SimpleNamespace(connect=lambda *a, **k: None, backend="postgresql", sqlite_path="unused")
    closed = []
    connector = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(polymarket_macro_map_watcher, "build_api_connection_factory", lambda *a: connector)
    def fail(*a, **k):
        raise TimeoutError("read failed")
    monkeypatch.setattr(polymarket_macro_map_service, "read_macro_market_catalog", fail)
    with pytest.raises(TimeoutError):
        watcher.read_market_catalog(terms=("fed",))
    assert closed == [True]


def test_catalog_projection_uses_bounded_shared_reader_and_rejects_failed_proofs(monkeypatch):
    service = polymarket_macro_map_service
    calls = []
    def rows(query, where, params, **options):
        calls.append((where, params, options))
        return [{"id": n + 1, "event_id": "event", "event_title": "Fed decision"} for n in range(101)]
    monkeypatch.setattr(service.market_service, "market_rows", rows)
    monkeypatch.setattr(service.outcome_semantics_service, "sanitize_public_market_payload", lambda ctx, payload: payload)
    result = service.read_macro_market_catalog(lambda *a: [], terms=("fed", "interest rate"), backend="postgresql")
    assert len(result["items"]) == 100 and result["coverage"]["truncated"]
    assert result["coverage"]["completeness"] == "NOT_PROVEN"
    assert calls[0][2] == {"limit": 101, "sort": "volume", "search": True}
    assert "q.observed_at IS NOT NULL" in calls[0][0]
    assert calls[0][1] == ("(fed) | (interest & rate)",)
    monkeypatch.setattr(service.outcome_semantics_service, "sanitize_public_market_payload",
        lambda ctx, payload: {"items": [{"outcomeSemanticsStatus": "semantics_query_failed"}]})
    with pytest.raises(TimeoutError):
        service.read_macro_market_catalog(lambda *a: [], terms=("fed",), backend="postgresql")


def test_runtime_route_clamps_limit_to_max():
    app = Flask(__name__)
    helpers = {
        "COMMODITY_SYMBOLS": [],
        "CRYPTO_SYMBOLS": [],
        "get_market_group_snapshot": lambda symbols, kind: {"kind": kind, "items": symbols},
        "get_polymarket_macro_map_snapshot": lambda limit=12: {"limit": limit},
        "get_f1_panel_snapshot": lambda limit=10: {"limit": limit},
        "get_geo_sanctions_shock_snapshot": lambda limit=6: {"limit": limit},
        "get_jin10_panel_snapshot": lambda limit=24: {"limit": limit},
        "get_nba_scoreboard_snapshot": lambda limit=10: {"limit": limit},
        "get_nba_intel_snapshot": lambda limit=12: {"limit": limit},
        "get_nba_matchup_predictor_snapshot": lambda limit=8: {"limit": limit},
        "get_inflation_nowcast_snapshot": lambda: {"items": []},
        "get_alpha_signal_snapshot": lambda limit=8: {"limit": limit},
        "get_crypto_funding_watch_snapshot": lambda limit=16: {"limit": limit},
        "get_cpi_release_calendar_snapshot": lambda limit=8: {"limit": limit},
        "get_energy_gasoline_shock_snapshot": lambda limit=6: {"limit": limit},
        "get_food_retail_basket_snapshot": lambda limit=8: {"limit": limit},
        "get_new_market_signals_snapshot": lambda limit=12: {"limit": limit},
        "get_whale_trades_snapshot": lambda limit=14: {"limit": limit},
        "get_suspicious_trades_snapshot": lambda limit=12: {"limit": limit},
    }
    app.register_blueprint(
        create_runtime_panels_blueprint(
            RuntimePanelRouteDependencies(
                panel_context=_route_runtime_panels.RuntimePanelContext.from_context(helpers),
                utc_now_iso=helpers.get("utc_now_iso", missing_route_dependency),
                natural_hazard_map_snapshot=helpers.get("get_natural_hazard_map_snapshot", None),
                natural_hazard_event_detail=helpers.get("get_natural_hazard_event_detail", None),
                natural_hazard_related_markets=helpers.get("get_natural_hazard_related_markets", None),
                aviation_viewport_snapshot=helpers.get("get_aviation_viewport_snapshot", None),
            )
        )
    )

    response = app.test_client().get("/runtime/macro/polymarket-map?limit=99")

    assert response.status_code == 200
    assert response.get_json()["limit"] == 20
