from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from runtime.seed_meta import collection_delay, retained_snapshot
from runtime.breaking_event_radar_watcher import BreakingEventRadarWatcher
from runtime.market_tv_wire_watcher import MarketTvWireWatcher
from runtime.tech_panels_watcher import TechPanelsWatcher
from api.services import live_video_source_service as video
from api.services import food_retail_basket_service as food
from api.services.natural_hazards.providers import gdacs
from test_food_retail_basket import make_ctx


def test_failure_preserves_source_clock_and_normal_cadence_recovers():
    old = {"generatedAt": "2026-11-03T01:00:00Z", "status": "ok", "items": [{"date": "2026-10-01"}]}
    retained = retained_snapshot(old)
    assert retained["generatedAt"] == old["generatedAt"]
    assert retained["items"] == old["items"]
    assert retained["status"] == "stale" and old["status"] == "ok"
    assert [collection_delay(21600, n, 20) for n in range(1, 6)] == [280, 580, 1180, 1780, 1780]
    assert collection_delay(21600, 0, 20) == 21580
    assert collection_delay(900, 0, 1200) == 30


def test_macro_recovery_fetches_only_failed_series_and_keeps_success_clock():
    ctx = make_ctx()
    previous = food.build_food_retail_basket_payload(ctx)
    assert previous["status"] == "degraded"
    ctx["get_cached_json"] = lambda *args: previous
    ctx["utc_now_iso"] = lambda: "2026-05-11T00:05:00Z"
    ctx["requested_urls"].clear()
    recovered = food.build_food_retail_basket_payload(ctx)
    assert len(ctx["requested_urls"]) == len(food.SERIES) - len(previous["items"])
    assert all(item["fetchedAt"] == "2026-05-11T00:00:00Z" for item in recovered["items"])
    ctx["utc_now_iso"] = lambda: "2026-05-11T06:01:00Z"
    ctx["requested_urls"].clear()
    food.build_food_retail_basket_payload(ctx)
    assert len(ctx["requested_urls"]) == len(food.SERIES)


def test_gdelt_backoff_survives_worker_and_honors_retry_after(monkeypatch):
    state = {}
    store = SimpleNamespace(get_stale=lambda *args: state.copy(), set=lambda n, k, p, ttl: state.update(p))
    response = requests.Response()
    response.status_code = 429
    response._content_consumed = True
    response.headers["Retry-After"] = "3600"
    session = Mock()
    session.get.return_value = response
    monkeypatch.setattr("runtime.breaking_event_radar_watcher.time.time", lambda: 1000)
    for _ in range(2):
        worker = BreakingEventRadarWatcher.__new__(BreakingEventRadarWatcher)
        worker.snapshot_store, worker.requests = store, session
        with pytest.raises(requests.HTTPError):
            worker.http_json_get("https://api.gdeltproject.org/api/v2/doc/doc")
    assert session.get.call_count == 1
    assert state["nextAttemptAt"] == 4600
    assert state["lastAttemptAt"] == 1000 and state["failures"] == 1


def test_gdelt_success_and_invalid_payload_are_both_paced_across_restarts(monkeypatch, tmp_path):
    from runtime.snapshot_store import SnapshotStore
    now = [1000]
    monkeypatch.setattr("runtime.breaking_event_radar_watcher.time.time", lambda: now[0])
    store = SnapshotStore(str(tmp_path / 'rate.sqlite'))
    session = Mock()
    session.get.return_value.json.return_value = {'articles': []}
    worker = BreakingEventRadarWatcher.__new__(BreakingEventRadarWatcher)
    worker.snapshot_store, worker.requests = store, session
    url = 'https://api.gdeltproject.org/api/v2/doc/doc'
    assert worker.http_json_get(url) == {'articles': []}
    assert store.get_stale('state:content', 'gdelt-backoff')['lastSuccessAt'] == 1000
    restarted = BreakingEventRadarWatcher.__new__(BreakingEventRadarWatcher)
    restarted.snapshot_store, restarted.requests = store, session
    now[0] = 4599
    with pytest.raises(requests.HTTPError):
        restarted.http_json_get(url)
    assert session.get.call_count == 1
    now[0] = 4600
    session.get.return_value.json.return_value = {'invalid': True}
    with pytest.raises(ValueError):
        restarted.http_json_get(url)
    state = store.get_stale('state:content', 'gdelt-backoff')
    assert state['lastSuccessAt'] == 1000 and state['nextAttemptAt'] == 8200
    assert state['lastStatus'] == 'error' and session.get.call_count == 2


def test_gdelt_existing_long_cooldown_is_not_shortened(monkeypatch, tmp_path):
    from runtime.snapshot_store import SnapshotStore
    now = 1000
    monkeypatch.setattr('runtime.breaking_event_radar_watcher.time.time', lambda: now)
    store = SnapshotStore(str(tmp_path / 'rate.sqlite'))
    previous = {'nextAttemptAt': 22600, 'failures': 17}
    store.set('state:content', 'gdelt-backoff', previous, 86400)
    worker = BreakingEventRadarWatcher.__new__(BreakingEventRadarWatcher)
    worker.snapshot_store, worker.requests = store, Mock()
    with pytest.raises(requests.HTTPError):
        worker.http_json_get('https://api.gdeltproject.org/api/v2/doc/doc')
    assert store.get_stale('state:content', 'gdelt-backoff') == previous
    assert worker.gdelt_state()['status'] == 'rate-limited'
    worker.requests.get.assert_not_called()


def test_tv_limits_expensive_probes_before_full_catalog(monkeypatch):
    monkeypatch.setattr(video, "load_manifest_items", lambda: [])
    monkeypatch.setattr(video.trusted_hls_sources, "trusted_hls_items", lambda **kw: [])
    monkeypatch.setenv("POLYDATA_MARKET_TV_WIRE_SEED_LIMIT", "24")
    playlist = '#EXTM3U\n' + '\n'.join(f'#EXTINF:-1 tvg-id="{i}",Channel {i}\nhttps://example.com/{i}.m3u8' for i in range(1000))
    seen = []
    monkeypatch.setattr(video, "_enrich_hls_watchability", lambda dep, rows, **kw: seen.extend(rows) or {"status": "ok", "count": len(rows)})
    result = video.build_market_tv_wire_payload({"http_text_get": lambda *a, **kw: playlist, "market_tv_youtube_probe_enabled": False})
    assert len(seen) == len(result["items"]) == 24
    worker = MarketTvWireWatcher.__new__(MarketTvWireWatcher)
    worker.settings = None
    worker.snapshot_store = None
    assert callable(worker.context()["http_json_get"])


def test_gdacs_revision_time_is_not_future_event_end():
    feature = {"geometry": {"type": "Point", "coordinates": [120, 10]}, "properties": {
        "eventtype": "TC", "eventid": 17, "alertlevel": "Red",
        "fromdate": "2026-11-03T00:00:00", "todate": "2026-11-08T00:00:00",
        "datemodified": "2026-11-04T00:00:00"}}
    result = gdacs.fetch(lambda *a, **kw: {"features": [feature]})
    assert result["events"][0]["updatedAt"] == "2026-11-04T00:00:00Z"
    assert result["events"][0]["geometry"]["coordinates"] == [120, 10]


def test_tech_publishes_finished_panel_before_slow_sibling(monkeypatch):
    from api.services import tech_panels_service
    worker = TechPanelsWatcher.__new__(TechPanelsWatcher)
    worker.limit = 24
    worker.service_context = lambda: {}
    worker.load_previous_payload = lambda panel: {}
    worker.store_seed_meta = Mock()
    published = []
    worker.store_payload = lambda panel, payload: published.append(panel)
    monkeypatch.setattr(tech_panels_service, "TECH_PANEL_IDS", ["fast", "slow"])
    def build(ctx, panel_id, limit):
        if panel_id == "slow":
            assert published == ["fast"]
        return {"status": "ok", "items": [{"id": panel_id}], "sources": {"source": "ok"}}
    monkeypatch.setattr(tech_panels_service, "build_tech_panel_payload", build)
    worker.run_once()
    assert published == ["fast", "slow"]


def test_yahoo_failure_budget_bounds_repeated_failed_symbol(monkeypatch):
    from api.clients import market_data_client
    from test_market_data_client import make_context
    state = {}
    ctx = make_context({})
    ctx["get_cached_runtime_payload"] = lambda ns, key: state.get((ns, key))
    ctx["set_cached_runtime_payload"] = lambda ns, key, value, ttl_seconds: state.update({(ns, key): value})
    getter = Mock(side_effect=requests.Timeout("source timeout"))
    monkeypatch.setattr(market_data_client, "http_json_get", getter)
    monkeypatch.setattr(market_data_client.time, "time", lambda: 1000)
    for symbol in ["A", "A", "A", "A", "A"]:
        with pytest.raises((requests.Timeout, RuntimeError)):
            market_data_client.get_yahoo_market_snapshot(ctx, symbol)
    assert getter.call_count == 3
    monkeypatch.setattr(market_data_client.time, "time", lambda: 1061)
    with pytest.raises(requests.Timeout):
        market_data_client.get_yahoo_market_snapshot(ctx, "A")
    assert getter.call_count == 4


def test_finance_external_yahoo_budget_survives_new_context_and_restart(monkeypatch, tmp_path):
    from api.clients import market_data_client
    from runtime.finance_external_sources_watcher import FinanceExternalSourcesWatcher
    from runtime.snapshot_store import SnapshotStore
    getter = Mock(side_effect=requests.Timeout("source timeout"))
    monkeypatch.setattr(market_data_client, "http_json_get", getter)
    for symbol in ["A", "A", "A", "A", "A"]:
        worker = FinanceExternalSourcesWatcher.__new__(FinanceExternalSourcesWatcher)
        worker.requests = requests.Session()
        worker.settings = SimpleNamespace(yahoo_chart_base_url="https://yahoo.test/chart", finance_runtime_ttl_seconds=300)
        worker.snapshot_store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
        with pytest.raises((requests.Timeout, RuntimeError)):
            worker.get_yahoo_market_snapshot(symbol)
    assert getter.call_count == 3


def test_yahoo_retry_after_stops_before_failure_threshold(monkeypatch):
    from api.clients import market_data_client
    from test_market_data_client import make_context
    state = {}
    ctx = make_context({})
    ctx["get_cached_runtime_payload"] = lambda ns, key: state.get((ns, key))
    ctx["set_cached_runtime_payload"] = lambda ns, key, value, ttl_seconds: state.update({(ns, key): value})
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "Thu, 01 Jan 1970 01:00:00 GMT"
    getter = Mock(side_effect=requests.HTTPError(response=response))
    monkeypatch.setattr(market_data_client, "http_json_get", getter)
    monkeypatch.setattr(market_data_client.time, "time", lambda: 1000)
    with pytest.raises(requests.HTTPError):
        market_data_client.get_yahoo_market_snapshot(ctx, "A")
    with pytest.raises(RuntimeError):
        market_data_client.get_yahoo_market_snapshot(ctx, "B")
    assert getter.call_count == 1
    assert next(iter(state.values()))["retryAt"] == 3600


def test_finance_external_does_not_bypass_injected_client_failure(monkeypatch):
    from api.services import finance_external_sources_service as service
    from test_finance_external_sources import _ctx
    ctx = _ctx()
    ctx["http_json_get"] = Mock(side_effect=requests.Timeout("source unavailable"))
    ctx["http_json_post"] = Mock(side_effect=requests.Timeout("source unavailable"))
    ctx["get_yahoo_market_snapshot"] = Mock(side_effect=RuntimeError("Yahoo source is in bounded failure backoff"))
    session = Mock(side_effect=AssertionError("must not bypass injected transport"))
    monkeypatch.setattr(service, "requests", SimpleNamespace(Session=session))
    dependencies = service.FinanceExternalSourceDependencies.from_context(ctx)
    with pytest.raises(requests.Timeout):
        service._http_get(dependencies, "https://example.test")
    with pytest.raises(requests.Timeout):
        service._http_post(dependencies, "https://example.test", json_payload={})
    with pytest.raises(RuntimeError, match="bounded failure backoff"):
        service._fetch_yahoo_snapshot(dependencies, "A")
    assert not session.called
    assert ctx["http_json_get"].call_count == 1
