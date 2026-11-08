from types import SimpleNamespace

import pytest
import requests

from api.clients import source_transport
from api.services import food_retail_basket_service as food_service
from api.services import macro_cpi_panels_service as drivers
from api.services import macro_cpi_registry_service as registry
from runtime import food_retail_basket_watcher as food
from runtime.macro_cpi_panels_watcher import MacroCpiPanelsWatcher
from runtime.seed_meta import SeedMetaStore
from runtime.snapshot_store import SnapshotStore


def test_whole_macro_round_budget_applies_across_panels(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(source_transport.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(source_transport.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    watcher = MacroCpiPanelsWatcher.__new__(MacroCpiPanelsWatcher)
    watcher.settings = SimpleNamespace(macro_cpi_round_budget_seconds=90)
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        clock[0] += 40
        raise requests.ReadTimeout()
    watcher.requests = SimpleNamespace(request=request)
    from api.clients.fred_csv import read_fred_text
    def panel(panel_id):
        with pytest.raises(requests.Timeout):
            read_fred_text(watcher.requests, "https://fred.example/series", deadline=watcher.collection_deadline)
        return {"status": "preserved", "panelId": panel_id}
    watcher.run_panel = panel
    result = watcher.run_once()
    assert result["status"] == "degraded"
    assert len(result["results"]) == 5
    assert len(calls) == 2 and all(call["timeout"] == 40 for call in calls)
    assert clock[0] == 81  # No fragment attempts for the other four panels.


def test_real_owner_sqlite_write_then_display_expiry_does_not_delete_snapshot(tmp_path, monkeypatch):
    settings = SimpleNamespace(food_basket_round_budget_seconds=720, food_basket_ttl_seconds=21600,
                               food_basket_max_display_age_seconds=64800, food_basket_source_url="")
    watcher = food.FoodRetailBasketWatcher(redis_url="", redis_prefix="", settings=settings,
        snapshot_sqlite_path=str(tmp_path / "macro.sqlite3"), interval_seconds=21600)
    item = {"key": "food", "seriesId": "CPIUFDSL", "value": 320,
            "date": "2026-09-01", "fetchedAt": "2026-11-06T00:00:00Z"}
    monkeypatch.setattr(food_service, "build_food_retail_basket_payload", lambda ctx: {
        "generatedAt": "2026-11-06T00:00:00Z", "status": "ok", "sources": {"food": "ok"}, "items": [item]})
    assert watcher.run_once()["status"] == "stored"
    ctx = {"SETTINGS": settings, "SNAPSHOT_STORE": watcher.snapshot_store,
        "get_cached_json": lambda *args: pytest.fail("SQLite authority bypassed"),
        "utc_now_iso": lambda: "2026-11-06T01:00:00Z"}
    current = food_service.get_food_retail_basket_snapshot(ctx)
    assert current["items"][0] == item  # A monthly observation is not a stale fetch.
    assert current["cacheMode"] == "sqlite-seed"
    ctx["utc_now_iso"] = lambda: "2026-11-07T00:00:00Z"
    expired = food_service.get_food_retail_basket_snapshot(ctx)
    assert expired["status"] == "expired" and expired["items"] == []
    stored = watcher.snapshot_store.get_stale(watcher.namespace(), watcher.cache_key())
    assert stored["items"] == [item]
    assert stored["generatedAt"] == "2026-11-06T00:00:00Z"
    assert stored["collectionBudget"]["budgetSeconds"] == 720


def test_republication_time_never_renews_macro_input_clock():
    ctx = {"utc_now_iso": lambda: "2026-11-07T00:00:00Z"}
    payload = {"generatedAt": "2026-11-07T00:00:00Z", "status": "ok", "items": [
        {"key": "old", "date": "2026-09-01", "fetchedAt": "2026-11-05T00:00:00Z"},
        {"key": "current", "date": "2026-09-01", "fetchedAt": "2026-11-06T23:00:00Z"}]}
    result = drivers.normalize_macro_cpi_panel_payload(payload, ctx=ctx, panel_id="labor-wage-services-pressure")
    assert [row["key"] for row in result["items"]] == ["current"]
    assert result["displayRetention"]["expiredItemCount"] == 1
    assert payload["items"][0]["key"] == "old"


def test_registry_food_preserves_parent_fetch_clock_and_actuals_expire():
    rows = registry._food_rows({"generatedAt": "2026-11-07T00:00:00Z", "items": [
        {"key": "food", "fetchedAt": "2026-11-06T20:00:00Z", "date": "2026-09-01", "value": 320}]})
    assert rows[0]["metadata"]["fetchedAt"] == "2026-11-06T20:00:00Z"
    result = registry._normalize_macro_cpi_registry_payload({
        "generatedAt": "2026-11-07T00:00:00Z", "items": rows, "status": "ok",
        "actualSeries": {"CPI": {"fetchedAt": "2026-11-06T20:00:00Z"}},
        "events": [{"seriesId": "CPI", "fetchedAt": "2026-11-06T20:00:00Z", "actual": 3, "previous": 2}]},
        dependencies=registry.MacroCpiRegistryDependencies.from_context({"utc_now_iso": lambda: "2026-11-07T00:00:00Z"}),
        panel_id="cpi-release-command-center", limit=12)
    assert result["actualSeries"] == {}
    assert result["events"][0]["actual"] is None
    assert result["summary"]["actualCount"] == 0


def test_legacy_event_can_use_only_matching_actual_series_clock():
    payload = {"generatedAt": "2026-11-07T08:00:00Z", "status": "ok", "items": [],
        "actualSeries": {"CPI": {"date": "2026-09-01", "fetchedAt": "2026-11-07T07:30:00Z"}},
        "events": [{"seriesId": "CPI", "asOf": "2026-09-01", "previous": 3},
                   {"seriesId": "CPI", "asOf": "2026-08-01", "previous": 2}]}
    result = registry._normalize_macro_cpi_registry_payload(payload,
        dependencies=registry.MacroCpiRegistryDependencies.from_context({"utc_now_iso": lambda: "2026-11-07T08:00:00Z"}),
        panel_id="cpi-release-command-center", limit=12)
    assert result["events"][0]["previous"] == 3
    assert result["events"][0]["fetchedAt"] == "2026-11-07T07:30:00Z"
    assert result["events"][1]["previous"] is None


def test_parent_expiry_survives_registry_source_composition_without_extra_source_count():
    states = {}
    registry._merge_sources(states, "supply", {"status": "degraded", "sources": {"fred": "ok"},
        "displayRetention": {"expiredItemCount": 1}})
    assert states == {"supply.fred": "ok", "supply": "expired"}
    assert registry._summarize("goods-tariff-supply-watch", [], states, {})["sourceCount"] == 1
