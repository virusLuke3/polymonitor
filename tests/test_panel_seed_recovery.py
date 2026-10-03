from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest
from flask import Flask, current_app
from api.services import seed_recovery as service
from runtime import finance_watch_panels_watcher, tech_panels_watcher


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
