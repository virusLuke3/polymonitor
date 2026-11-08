import json
from types import SimpleNamespace

import pytest

from runtime import food_retail_basket_watcher as food
from runtime import macro_cpi_panels_watcher as drivers
from runtime import macro_cpi_registry_watcher as registry
from runtime.seed_meta import SeedMetaStore, SnapshotPublicationError


CASES = [(drivers, drivers.MacroCpiPanelsWatcher, "fed-rates-polymarket-gap"),
         (registry, registry.MacroCpiRegistryWatcher, "cpi-release-command-center"),
         (food, food.FoodRetailBasketWatcher, "food-retail-basket-pressure")]


class Store:
    def __init__(self):
        self.data = {}
        self.accept = True
    def get(self, namespace, key):
        return self.data.get((namespace, key))
    get_stale = get
    def set(self, namespace, key, payload, ttl):
        if not self.accept:
            return False
        self.data[(namespace, key)] = json.loads(json.dumps(payload))
        return True


class BrokenRedis:
    def __init__(self):
        self.reads = self.writes = 0
    def get(self, key):
        self.reads += 1
        raise ConnectionError("redis unavailable")
    def set(self, *args, **kwargs):
        self.writes += 1
        raise ConnectionError("redis unavailable")


def make_watcher(cls):
    watcher = cls.__new__(cls)
    watcher.settings = SimpleNamespace()
    watcher.interval_seconds = 21600
    watcher.redis_prefix = "test:"
    watcher.snapshot_store = Store()
    watcher.redis_client = BrokenRedis()
    watcher.seed_meta_store = SeedMetaStore(redis_client=watcher.redis_client,
        redis_prefix=watcher.redis_prefix, snapshot_store=watcher.snapshot_store)
    return watcher


def invoke(watcher, method, panel, *args, **kwargs):
    return getattr(watcher, method)(*(() if isinstance(watcher, food.FoodRetailBasketWatcher) else (panel,)), *args, **kwargs)


@pytest.mark.parametrize("module,cls,panel", CASES)
def test_sqlite_publication_survives_redis_outage_and_is_read_first(module, cls, panel):
    watcher = make_watcher(cls)
    payload = {"status": "ok", "generatedAt": "2026-11-06T13:00:00Z", "items": [{"date": "2026-09-01"}]}
    invoke(watcher, "store_payload", panel, payload)
    assert watcher.redis_client.writes == 1
    assert invoke(watcher, "previous", panel) == payload
    namespace = invoke(watcher, "namespace", panel)
    assert watcher._get_cached_json(namespace, watcher.cache_key()) == payload
    assert watcher.redis_client.reads == 0
    assert watcher._get_cached_json("missing", "missing") is None


@pytest.mark.parametrize("module,cls,panel", CASES)
def test_sqlite_rejection_never_mirrors_or_records_success(module, cls, panel, monkeypatch):
    watcher = make_watcher(cls)
    watcher.snapshot_store.accept = False
    watcher.context = lambda: {}
    service = module.food_retail_basket_service if module is food else module.macro_cpi_panels_service if module is drivers else module.macro_cpi_registry_service
    name = "build_food_retail_basket_payload" if module is food else "build_macro_cpi_panel_payload" if module is drivers else "build_macro_cpi_registry_payload"
    monkeypatch.setattr(service, name, lambda *args, **kwargs: {"status": "ok", "items": [{"date": "2026-09-01"}]})
    with pytest.raises(SnapshotPublicationError):
        invoke(watcher, "run_once" if module is food else "run_panel", panel)
    assert watcher.redis_client.writes == 0
    assert not watcher.snapshot_store.data


@pytest.mark.parametrize("module,cls,panel", CASES)
def test_first_failure_has_no_success_clock_then_preserves_real_success(module, cls, panel):
    watcher = make_watcher(cls)
    invoke(watcher, "store_meta", panel, status="error", record_count=0, preserve=True)
    first = watcher.snapshot_store.get("seed-meta:macro", panel)
    assert first["lastAttemptAt"] and first["lastSuccessAt"] is None
    invoke(watcher, "store_meta", panel, status="ok", record_count=1)
    success = watcher.snapshot_store.get("seed-meta:macro", panel)["lastSuccessAt"]
    invoke(watcher, "store_meta", panel, status="degraded", record_count=1)
    assert watcher.snapshot_store.get("seed-meta:macro", panel)["lastSuccessAt"] == success


@pytest.mark.parametrize("module,cls,panel", CASES)
def test_failed_refresh_retains_source_clocks_but_publishes_stale(module, cls, panel, monkeypatch):
    watcher = make_watcher(cls)
    original = {"status": "ok", "generatedAt": "2026-11-05T12:00:00Z", "items": [{"date": "2026-09-01", "fetchedAt": "2026-11-05T11:59:00Z"}]}
    invoke(watcher, "store_payload", panel, original)
    watcher.context = lambda: {}
    def fail(*args, **kwargs):
        raise TimeoutError("source timed out")
    service = module.food_retail_basket_service if module is food else module.macro_cpi_panels_service if module is drivers else module.macro_cpi_registry_service
    name = "build_food_retail_basket_payload" if module is food else "build_macro_cpi_panel_payload" if module is drivers else "build_macro_cpi_registry_payload"
    monkeypatch.setattr(service, name, fail)
    result = invoke(watcher, "run_once" if module is food else "run_panel", panel)
    retained = invoke(watcher, "previous", panel)
    assert result["status"] == "preserved" and retained["status"] == "stale"
    assert retained["generatedAt"] == original["generatedAt"]
    assert retained["items"] == original["items"]
    assert watcher.snapshot_store.get("seed-meta:macro", panel)["lastSuccessAt"] is None
