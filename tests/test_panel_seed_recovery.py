from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest
from flask import Flask, current_app
from api.services import seed_recovery as service
from runtime import finance_watch_panels_watcher, tech_panels_watcher


REMAINING_SNAPSHOT_OWNERS = [
    ("weather_news", "WeatherNewsWatcher"),
    ("polymarket_macro_map", "PolymarketMacroMapWatcher"),
    ("nba", "NbaWatcher"),
    ("market_tv_wire", "MarketTvWireWatcher"),
    ("inflation_nowcast", "InflationNowcastWatcher"),
    ("jin10", "Jin10Watcher"),
    ("global_transport_shipping", "GlobalTransportShippingWatcher"),
    ("energy_gasoline_shock", "EnergyGasolineShockWatcher"),
    ("cpi_release_calendar", "CpiReleaseCalendarWatcher"),
    ("breaking_event_radar", "BreakingEventRadarWatcher"),
    ("worldcup_dashboard", "WorldCupDashboardWatcher"),
    ("world_cup_match_ops", "WorldCupMatchOpsWatcher"),
    ("signals", "SignalsWatcher"),
]


def _remaining_watcher(monkeypatch, tmp_path, module_name, class_name):
    import importlib
    import inspect
    from unittest.mock import Mock

    module = importlib.import_module(f"runtime.{module_name}_watcher")
    monkeypatch.setattr(module, "redis", None)
    if hasattr(module, "source_session"):
        monkeypatch.setattr(module, "source_session", lambda *a, **kw: Mock())
    watcher_class = getattr(module, class_name)
    settings = SimpleNamespace(sports_runtime_ttl_seconds=300, finance_runtime_ttl_seconds=300,
                               signal_runtime_ttl_seconds=900, signal_refresh_interval_seconds=120,
                               jin10_flash_channel="fixture", jin10_flash_api_url="https://example.invalid/feed")
    arguments = dict(redis_url="", redis_prefix="test:", snapshot_sqlite_path=str(tmp_path / "snapshots.sqlite"),
                     settings=settings, limit=12, interval_seconds=300, component="whales")
    return module, watcher_class(**{k: v for k, v in arguments.items() if k in inspect.signature(watcher_class).parameters})


@pytest.mark.parametrize("module_name,class_name", REMAINING_SNAPSHOT_OWNERS)
def test_remaining_owner_confirms_sqlite_before_optional_mirror(monkeypatch, tmp_path, module_name, class_name):
    from unittest.mock import Mock
    from runtime.seed_meta import SnapshotPublicationError

    _, watcher = _remaining_watcher(monkeypatch, tmp_path, module_name, class_name)
    args = ("snapshot:test", "test") if module_name == "nba" else ()
    read = getattr(watcher, "load_previous_payload", None) or watcher.previous
    old, newer = snapshot(), snapshot(items=[{"id": "new"}])
    try:
        assert watcher.redis_client is None
        watcher.store_payload(*args, old)
        assert read(*args)["generatedAt"] == old["generatedAt"]
        mirror = watcher.redis_client = Mock()
        mirror.get.return_value = '{"items":[{"id":"old mirror"}]}'
        mirror.set.side_effect = ConnectionError("mirror offline")
        watcher.store_payload(*args, newer)
        assert read(*args)["items"] == newer["items"]
        mirror.get.assert_not_called()
        mirror.reset_mock()
        real_set = watcher.snapshot_store.set
        monkeypatch.setattr(watcher.snapshot_store, "set", lambda *a, **kw: False)
        with pytest.raises(SnapshotPublicationError, match="not accepted"):
            watcher.store_payload(*args, snapshot(items=[{"id": "rejected"}]))
        mirror.set.assert_not_called()
        assert read(*args)["items"] == newer["items"]
        monkeypatch.setattr(watcher.snapshot_store, "set", real_set)
        watcher.store_payload(*args, old)
        assert read(*args)["items"] == old["items"]
    finally:
        if hasattr(watcher, "close"):
            watcher.close()
        elif hasattr(watcher, "requests"):
            watcher.requests.close()


@pytest.mark.parametrize("module_name,class_name", REMAINING_SNAPSHOT_OWNERS)
@pytest.mark.parametrize("previous_success", [None, "2026-01-01T00:00:00Z"])
def test_remaining_owner_failed_attempt_does_not_create_success(monkeypatch, tmp_path, module_name, class_name, previous_success):
    from unittest.mock import Mock

    _, watcher = _remaining_watcher(monkeypatch, tmp_path, module_name, class_name)
    watcher.seed_meta_store = Mock()
    watcher.seed_meta_store.load.return_value = {"lastSuccessAt": previous_success}
    method = getattr(watcher, "store_seed_meta", None) or watcher.store_meta
    try:
        method(status="error", record_count=0, source_states={"feed": "error"}, error_summary="failed")
        stored = watcher.seed_meta_store.store.call_args.args[2]
        assert stored["lastSuccessAt"] == previous_success
        assert stored["lastAttemptAt"]
    finally:
        if hasattr(watcher, "close"):
            watcher.close()
        elif hasattr(watcher, "requests"):
            watcher.requests.close()


def test_seed_metadata_rejected_write_never_reaches_mirror_or_replaces_success(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from runtime.snapshot_store import SnapshotStore
    from runtime.seed_meta import SeedMetaStore, SnapshotPublicationError, build_seed_meta_payload

    store, mirror = SnapshotStore(str(tmp_path / "metadata.sqlite")), Mock()
    meta = SeedMetaStore(redis_client=mirror, redis_prefix="test:", snapshot_store=store)
    prior = {"status": "ok", "lastSuccessAt": "2026-01-01T00:00:00Z"}
    assert store.set("seed-meta:test", "test", prior, 600)
    monkeypatch.setattr(store, "set", lambda *a: False)
    with pytest.raises(SnapshotPublicationError):
        meta.store("seed-meta:test", "test", {"status": "ok", "lastSuccessAt": "rejected"})
    mirror.set.assert_not_called()
    assert meta.load("seed-meta:test", "test") == prior
    for status in ("error", "preserved", "degraded", "warming", "empty", "ok"):
        payload = build_seed_meta_payload(panel_id="test", namespace="test", cache_key="test", service_name="test",
                                          expected_interval_seconds=300, status=status, last_attempt_at="attempt")
        assert payload["lastSuccessAt"] is None


def test_nba_publication_failure_keeps_siblings_running_and_skips_publisher(monkeypatch, tmp_path):
    from unittest.mock import Mock

    module, watcher = _remaining_watcher(monkeypatch, tmp_path, "nba", "NbaWatcher")
    namespace = module.runtime_service.NBA_SCOREBOARD_NAMESPACE
    key = module.runtime_service.build_nba_scoreboard_cache_key(limit=watcher.scoreboard_limit)
    old = snapshot()
    watcher.store_payload(namespace, key, old)
    watcher.store_seed_meta(status="ok", record_count=1, cache_key="nba-scoreboard")
    old_success = watcher.load_seed_meta("nba-scoreboard")["lastSuccessAt"]
    real_set = watcher.snapshot_store.set
    monkeypatch.setattr(watcher.snapshot_store, "set", lambda ns, *a: False if ns == namespace else real_set(ns, *a))
    for fetcher in ("fetch_live_nba_scoreboard_payload", "fetch_live_nba_intel_payload", "fetch_live_nba_matchup_predictor_payload"):
        monkeypatch.setattr(module.runtime_service, fetcher, lambda *a, **kw: snapshot())
    publisher = Mock(return_value=0)
    monkeypatch.setattr(module, "publish_cached_panel_snapshot", publisher)
    result = watcher.run_once()
    assert result["components"]["scoreboard"]["status"] == "error"
    assert result["components"]["intel"]["status"] == "ok"
    assert result["components"]["predictor"]["status"] == "ok"
    assert "nba-scoreboard" not in [call.args[0] for call in publisher.call_args_list]
    assert watcher.load_seed_meta("nba-scoreboard")["lastSuccessAt"] == old_success
    assert watcher.load_previous_payload(namespace, key) == old
    watcher.requests.close()


def test_new_market_recovery_retains_confirmed_snapshot_clock_and_never_publishes(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from runtime import new_market_signal_watcher as module
    from runtime.snapshot_store import SnapshotStore
    from runtime.seed_meta import SeedMetaStore, SnapshotPublicationError

    watcher = module.NewMarketSignalWatcher.__new__(module.NewMarketSignalWatcher)
    watcher.snapshot_store = SnapshotStore(str(tmp_path / "new-market.sqlite"))
    watcher.redis_prefix = "test:"
    watcher.redis_client = None
    watcher.seed_meta_store = SeedMetaStore(redis_client=None, redis_prefix="test:", snapshot_store=watcher.snapshot_store)
    old = snapshot()
    watcher.snapshot_store.set(module.SNAPSHOT_NAMESPACE, module.SNAPSHOT_CACHE_KEY, old, 600)
    watcher.store_seed_meta(status="scan", record_count=1)
    success = watcher.load_seed_meta()["lastSuccessAt"]
    publisher = Mock()
    monkeypatch.setattr(module, "publish_cached_panel_snapshot", publisher)
    assert watcher.preserve_current_snapshot(reason="database offline")["mode"] == "preserved"
    retained = watcher.snapshot_store.get_stale(module.SNAPSHOT_NAMESPACE, module.SNAPSHOT_CACHE_KEY)
    assert retained["generatedAt"] == old["generatedAt"] and retained["status"] == "stale"
    assert watcher.load_seed_meta()["lastSuccessAt"] == success
    publisher.assert_not_called()
    watcher.build_snapshot_payload = lambda **kw: snapshot()
    monkeypatch.setattr(watcher.snapshot_store, "set", lambda *a: False)
    with pytest.raises(SnapshotPublicationError):
        watcher.store_snapshot_payload()
    publisher.assert_not_called()


def test_worldcup_split_and_panel_publication_require_durable_storage(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from api.services.worldcup import cache, panels
    from runtime.snapshot_store import SnapshotStore
    from runtime.seed_meta import SnapshotPublicationError

    store = SnapshotStore(str(tmp_path / "worldcup.sqlite"))
    mirror = Mock(side_effect=ConnectionError("mirror offline"))
    ctx = {"SNAPSHOT_STORE": store, "set_cached_json": mirror}
    cache.store_payload(ctx, namespace="snapshot:worldcup", cache_key="core", payload=snapshot(), ttl_seconds=600)
    assert store.get_stale("snapshot:worldcup", "core")["items"]
    mirror.reset_mock()
    monkeypatch.setattr(store, "set", lambda *a: False)
    with pytest.raises(SnapshotPublicationError):
        cache.store_payload(ctx, namespace="snapshot:worldcup", cache_key="live", payload=snapshot(), ttl_seconds=600)
    with pytest.raises(SnapshotPublicationError):
        panels.store_worldcup_panel_payloads(ctx, {}, core_ttl=3600, live_ttl=300)
    mirror.assert_not_called()


def test_new_market_failed_first_publication_does_not_advance_cursor(monkeypatch):
    from unittest.mock import Mock
    from runtime import new_market_signal_watcher as module
    from runtime.seed_meta import SnapshotPublicationError

    watcher = module.NewMarketSignalWatcher.__new__(module.NewMarketSignalWatcher)
    watcher.redis_client = Mock()
    watcher.get_last_seen_market_id = lambda: None
    watcher.get_current_max_market_id = lambda: 42
    watcher.max_market_age_hours = 24
    watcher.set_last_seen_market_id = Mock()
    watcher.store_seed_meta = Mock()
    watcher.store_snapshot_payload = Mock(side_effect=SnapshotPublicationError("SQLite rejected"))
    with pytest.raises(SnapshotPublicationError):
        watcher.run_once()
    watcher.set_last_seen_market_id.assert_not_called()
    watcher.store_seed_meta.assert_not_called()


def test_market_tv_rss_failure_still_keeps_persisted_refresh_cadence(monkeypatch, tmp_path):
    from unittest.mock import Mock

    module, watcher = _remaining_watcher(monkeypatch, tmp_path, "market_tv_wire", "MarketTvWireWatcher")
    builder = Mock(side_effect=TimeoutError("RSS failed"))
    monkeypatch.setattr(module.live_video_source_service, "build_market_tv_wire_payload", builder)
    assert watcher._youtube_rss_refresh_due()
    assert watcher.run_once()["status"] == "error"
    assert not watcher._youtube_rss_refresh_due()
    assert watcher.seed_meta_store.load(module.SEED_META_NAMESPACE, module.SEED_META_CACHE_KEY)["lastSuccessAt"] is None
    # The same database protects cadence after a process restart, without Redis.
    _, restarted = _remaining_watcher(monkeypatch, tmp_path, "market_tv_wire", "MarketTvWireWatcher")
    assert not restarted._youtube_rss_refresh_due()
    watcher.requests.close()
    restarted.requests.close()


def test_worldcup_split_failed_first_attempt_has_no_success_clock():
    from unittest.mock import Mock
    from runtime.worldcup_seed_common import WorldCupSeedWatcher

    watcher = WorldCupSeedWatcher.__new__(WorldCupSeedWatcher)
    watcher.seed_meta_store = Mock()
    watcher.seed_meta_store.load.return_value = {}
    watcher.mode, watcher.seed_meta_key, watcher.service_name = "core", "worldcup-core", "fixture"
    watcher.interval_seconds = 86400
    watcher.store_seed_meta(status="error", record_count_value=0, source_states={"feed": "error"}, error_summary="failed")
    assert watcher.seed_meta_store.store.call_args.args[2]["lastSuccessAt"] is None


def test_nba_http_uses_shared_route_session(monkeypatch, tmp_path):
    from unittest.mock import Mock
    from runtime import nba_watcher

    factory = Mock(return_value=Mock())
    monkeypatch.setattr(nba_watcher, "source_session", factory)
    monkeypatch.setattr(nba_watcher, "redis", None)
    watcher = nba_watcher.NbaWatcher(redis_url="", redis_prefix="", snapshot_sqlite_path=str(tmp_path / "nba.sqlite"),
                                    settings=SimpleNamespace(sports_runtime_ttl_seconds=300))
    assert watcher.requests is factory.return_value
    factory.assert_called_once_with(nba_watcher.requests)


def snapshot(age=0, **extra):
    return {"panelId": "test", "generatedAt": (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat(),
            "status": "ok", "items": [{"id": "row"}], **extra}


def setup(monkeypatch, initial=None):
    state = {"value": initial, "callbacks": [], "writes": []}
    store = SimpleNamespace(get=lambda *a: state["value"], get_stale=lambda *a: state["value"],
                            fetch_lock=lambda *a, **k: nullcontext())
    def write(*args):
        state["value"] = args[2]
        state["writes"].append(args[2])
    store.set = write
    monkeypatch.setattr(service, "recover_seed", lambda key, callback: state["callbacks"].append(callback))
    def read(builder=lambda: snapshot()):
        return service.read_watch_seed(namespace="snapshot:test", cache_key="test", panel_id="test", snapshot_store=store,
                                       redis_get=None, redis_set=None, builder=builder, ttl_seconds=600)
    return state, read


def test_get_returns_immediately_and_recovery_publishes_for_next_read(monkeypatch):
    state, read = setup(monkeypatch)
    calls = []
    assert read(lambda: calls.append(1) or snapshot())["status"] == "warming"
    assert calls == []
    state["callbacks"][0]()
    assert read()["items"] == [{"id": "row"}]
    assert calls == [1]


def test_stale_retention_expires_without_renewing_original_time(monkeypatch):
    old = snapshot(1000)
    state, read = setup(monkeypatch, old)
    assert read()["status"] == "stale"
    assert read()["generatedAt"] == old["generatedAt"]
    state["value"] = snapshot(1900)
    assert read()["items"] == []
    assert len(state["callbacks"]) == 3


def test_newer_collector_publication_wins_over_recovery(monkeypatch):
    state, read = setup(monkeypatch, snapshot(1000))
    newer = snapshot(0)
    def build():
        state["value"] = newer
        return snapshot(10)
    read(build)
    state["callbacks"][0]()
    assert state["writes"] == []
    assert state["value"] == newer


def test_failed_empty_cannot_erase_old_data_but_healthy_empty_can(monkeypatch):
    old = snapshot(1000)
    state, read = setup(monkeypatch, old)
    read(lambda: snapshot(items=[], sources={"feed": "error"}))
    with pytest.raises(RuntimeError, match="usable"):
        state["callbacks"][0]()
    assert state["value"] == old
    read(lambda: snapshot(status="empty", items=[], sources={"feed": "ok"}))
    state["callbacks"][-1]()
    assert read()["items"] == []
    assert read()["status"] == "empty"


def test_recovery_carries_flask_context_and_deduplicates_active_key():
    app = Flask(__name__)
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    values = []
    def build():
        values.append(current_app.name)
        entered.set()
        release.wait(2)
        done.set()
    with app.app_context():
        assert service.recover_seed("context-test", build)
        assert entered.wait(2)
        assert not service.recover_seed("context-test", build)
        release.set()
        assert done.wait(2)
    assert values == [app.name]


def test_source_clock_missing_invalid_and_future_are_not_fresh():
    now = datetime.now(timezone.utc)
    for value in [None, "invalid", (now + timedelta(seconds=61)).isoformat()]:
        assert service.age_seconds(value, now.isoformat()) == float("inf")


@pytest.mark.parametrize("module,class_name", [(finance_watch_panels_watcher, "FinanceWatchPanelsWatcher"), (tech_panels_watcher, "TechPanelsWatcher")])
def test_family_acquisition_cache_obeys_ttl_and_fetches_again(monkeypatch, module, class_name):
    watcher = getattr(module, class_name).__new__(getattr(module, class_name))
    watcher._runtime_cache = {}
    monkeypatch.setattr(module.time, "monotonic", lambda: 100.)
    watcher.set_cached_runtime_payload("yahoo", "asset", {"price": 10}, ttl_seconds=300)
    monkeypatch.setattr(module.time, "monotonic", lambda: 399.)
    assert watcher.get_cached_runtime_payload("yahoo", "asset") == {"price": 10}
    monkeypatch.setattr(module.time, "monotonic", lambda: 400.)
    assert watcher.get_cached_runtime_payload("yahoo", "asset") is None
    assert watcher._runtime_cache == {}


def test_recovery_rejected_sqlite_write_keeps_last_good_even_with_redis(monkeypatch):
    old = snapshot(1000)
    callbacks, mirrored = [], []
    store = SimpleNamespace(get=lambda *a: old, get_stale=lambda *a: old,
                            set=lambda *a: False, fetch_lock=lambda *a, **k: nullcontext())
    monkeypatch.setattr(service, "recover_seed", lambda key, callback: callbacks.append(callback))
    result = service.read_watch_seed(namespace="snapshot:test", cache_key="test", panel_id="test",
                                    snapshot_store=store, redis_get=lambda *a: None,
                                    redis_set=lambda *a: mirrored.append(a[2]),
                                    builder=lambda: snapshot(), ttl_seconds=600)
    assert result["generatedAt"] == old["generatedAt"]
    with pytest.raises(RuntimeError, match="accepted"):
        callbacks[0]()
    assert store.get("snapshot:test", "test") == old
    assert mirrored == []


@pytest.mark.parametrize("module_name,class_name", [
    ("market_group", "MarketGroupWatcher"),
    ("crypto_funding", "CryptoFundingWatcher"),
    ("defi_token_watch", "DefiTokenWatchWatcher"),
    ("finance_external_sources", "FinanceExternalSourcesWatcher"),
    ("finance_watch_panels", "FinanceWatchPanelsWatcher"),
    ("tech_panels", "TechPanelsWatcher"),
])
def test_watchers_publish_without_redis_and_reject_failed_durable_writes(monkeypatch, tmp_path, module_name, class_name):
    import importlib
    from unittest.mock import Mock
    from runtime.seed_meta import SnapshotPublicationError

    module = importlib.import_module(f"runtime.{module_name}_watcher")
    monkeypatch.setattr(module, "redis", None)
    monkeypatch.setattr(module, "source_session", lambda: Mock())
    settings = SimpleNamespace(finance_runtime_ttl_seconds=300, crypto_funding_watch_symbols=("BTCUSDT",),
                               crypto_funding_watch_api_url="https://venue-a.example.invalid",
                               crypto_funding_watch_bybit_api_url="https://venue-b.example.invalid",
                               crypto_funding_watch_ttl_seconds=180)
    watcher = getattr(module, class_name)(redis_url="", redis_prefix="test:",
        snapshot_sqlite_path=str(tmp_path / "snapshots.sqlite3"), settings=settings)
    family = module_name in {"tech_panels", "finance_watch_panels"}
    args = ("test",) if family else ("snapshot:test", "test") if module_name == "market_group" else ()
    kwargs = {"kind": "commodities"} if module_name == "market_group" else {}
    old = snapshot()
    try:
        assert watcher.redis_client is None
        watcher.store_payload(*args, old, **kwargs)
        previous = watcher.load_previous_payload(*args)
        assert previous["generatedAt"] == old["generatedAt"]
        watcher.redis_client = Mock()
        watcher.redis_client.get.return_value = '{"generatedAt":"older mirror"}'
        watcher.redis_client.set.side_effect = ConnectionError("optional mirror unavailable")
        newer = snapshot(items=[{"id": "new"}])
        watcher.store_payload(*args, newer, **kwargs)
        assert watcher.load_previous_payload(*args)["items"] == [{"id": "new"}]
        watcher.redis_client.get.assert_not_called()
        real_set = watcher.snapshot_store.set
        monkeypatch.setattr(watcher.snapshot_store, "set", lambda namespace, *a, **k:
                            real_set(namespace, *a, **k) if namespace.startswith("seed-meta:") else False)
        with pytest.raises(SnapshotPublicationError, match="not accepted"):
            watcher.store_payload(*args, snapshot(items=[{"id": "rejected"}]), **kwargs)
        assert watcher.load_previous_payload(*args)["items"] == [{"id": "new"}]
        monkeypatch.setattr(watcher.snapshot_store, "set", real_set)
        watcher.store_payload(*args, snapshot(items=[{"id": "recovered"}]), **kwargs)
        assert watcher.load_previous_payload(*args)["items"] == [{"id": "recovered"}]
    finally:
        if hasattr(watcher, "close"):
            watcher.close()
        elif hasattr(watcher, "_source_executor"):
            watcher._source_executor.shutdown(wait=True)
            watcher._resources.close()
            watcher.requests.close()
        else:
            watcher.requests.close()


@pytest.mark.parametrize("module,class_name,panel_ids_name,builder_name", [
    (tech_panels_watcher, "TechPanelsWatcher", "TECH_PANEL_IDS", "build_tech_panel_payload"),
    (finance_watch_panels_watcher, "FinanceWatchPanelsWatcher", "FINANCE_WATCH_PANEL_IDS", "build_finance_watch_panel_payload"),
])
def test_family_failed_publication_preserves_success_clock_and_continues(monkeypatch, module, class_name, panel_ids_name, builder_name):
    from unittest.mock import Mock
    from runtime.seed_meta import SeedMetaStore

    values = {}
    old_success = "2026-01-01T00:00:00Z"
    metadata_namespace = module.SEED_META_NAMESPACE
    values[metadata_namespace, "test"] = {"lastSuccessAt": old_success}
    def write(namespace, key, payload, ttl):
        if not namespace.startswith("seed-meta:") and payload.get("panelId") == "test":
            return False
        values[namespace, key] = payload
        return True
    store = SimpleNamespace(set=write, get_stale=lambda ns, key: values.get((ns, key)))
    watcher = getattr(module, class_name).__new__(getattr(module, class_name))
    watcher.snapshot_store = store
    watcher.redis_client = Mock()
    watcher.redis_client.get.return_value = None
    watcher.redis_client.set.side_effect = ConnectionError("mirror unavailable")
    watcher.redis_prefix = ""
    watcher.interval_seconds = 600
    watcher.limit = 24
    watcher.seed_meta_store = SeedMetaStore(redis_client=watcher.redis_client, redis_prefix="", snapshot_store=store)
    watcher.service_context = lambda: {}
    domain = module.tech_panels_service if module is tech_panels_watcher else module.finance_watch_panels_service
    monkeypatch.setattr(domain, panel_ids_name, ("test", "sibling"))
    monkeypatch.setattr(domain, builder_name, lambda ctx, panel_id, **k: snapshot(panelId=panel_id))
    result = watcher.run_once()
    assert result["panels"] == {"test": "publication-failed", "sibling": "ok"}
    assert values[metadata_namespace, "test"]["lastSuccessAt"] == old_success
    assert values[metadata_namespace, "test"]["status"] == "error"


@pytest.mark.parametrize("module_name,class_name", [
    ("market_group", "MarketGroupWatcher"),
    ("crypto_funding", "CryptoFundingWatcher"),
    ("defi_token_watch", "DefiTokenWatchWatcher"),
    ("finance_external_sources", "FinanceExternalSourcesWatcher"),
    ("finance_watch_panels", "FinanceWatchPanelsWatcher"),
])
def test_optional_redis_outage_does_not_prevent_first_collection(monkeypatch, module_name, class_name):
    import importlib
    from unittest.mock import Mock

    module = importlib.import_module(f"runtime.{module_name}_watcher")
    watcher = Mock()
    watcher.redis_client.ping.side_effect = ConnectionError("optional mirror unavailable")
    watcher.run_once.return_value = {"status": "ok"}
    monkeypatch.setattr(module, class_name, lambda **kwargs: watcher)
    monkeypatch.setattr(module, "load_api_settings", lambda: SimpleNamespace(
        redis_url="", redis_prefix="", snapshot_sqlite_path="unused-test-store"))
    monkeypatch.setattr(module, "build_arg_parser", lambda: SimpleNamespace(
        parse_args=lambda: SimpleNamespace(watch=False, interval=600, limit=24)))
    assert module.main() == 0
    watcher.run_once.assert_called_once()
    watcher.redis_client.ping.assert_not_called()
