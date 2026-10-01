"""Real process termination, without network or production database access."""
import multiprocessing
import time
from types import SimpleNamespace

from runtime import content_topic_refresh as worker
from api.services.free_content import collector, store


def blocked_cycle(events, options):
    time.sleep(10)


def successful_cycle(events, options):
    events.put({"result": {"source_id": "fixture", "status": "ok"}})


def prepare(monkeypatch, target):
    context = multiprocessing.get_context("fork")
    monkeypatch.setattr(worker.multiprocessing, "get_context", lambda _: context)
    monkeypatch.setattr(worker, "_cycle_process", target)
    monkeypatch.setattr(store, "source_states", lambda _: {"fixture": {"last_success_at": "2026-10-01T00:00:00Z"}})
    monkeypatch.setattr(collector, "due_sources", lambda *a, **k: [{"source_id": "fixture", "poll_interval_seconds": 180}])
    writes, seeds = [], []
    monkeypatch.setattr(store, "save_state", lambda storage, sid, state: writes.append(state))
    monkeypatch.setattr(worker, "publish_seed", lambda *a: seeds.append(a[-1] if len(a) == 4 else None))
    return writes, seeds


def test_cycle_wall_budget_terminates_actual_blocked_process(monkeypatch):
    writes, seeds = prepare(monkeypatch, blocked_cycle)
    started = time.monotonic()
    assert worker.run_bounded_cycle(SimpleNamespace(), SimpleNamespace(), budget=0.15) == "cycle-budget-exhausted"
    assert time.monotonic() - started < 2
    assert writes[0]["status"] == "error"
    assert writes[0]["last_success_at"] == "2026-10-01T00:00:00Z"
    assert len(seeds) >= 2
    assert not multiprocessing.active_children()


def test_completed_sources_are_not_marked_failed(monkeypatch):
    writes, seeds = prepare(monkeypatch, successful_cycle)
    assert worker.run_bounded_cycle(SimpleNamespace(), SimpleNamespace(), budget=2) is None
    assert not writes
    assert len(seeds) >= 2
    assert not multiprocessing.active_children()
