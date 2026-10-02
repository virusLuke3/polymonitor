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


def test_spawned_cycle_declares_the_watch_parent_schema_ready(monkeypatch):
    from api.services.query_service import ContentStorageDependencies
    runtime = SimpleNamespace(query_context={}, SNAPSHOT_STORE=object())
    class Context:
        def __enter__(self): return runtime
        def __exit__(self, *args): pass
    monkeypatch.setattr(worker, 'content_runtime', Context)
    monkeypatch.setattr(ContentStorageDependencies, 'from_context', lambda _: object())
    calls = []
    monkeypatch.setattr(collector, 'cycle', lambda *a, **kw: calls.append(kw))
    events = SimpleNamespace(put=lambda event: calls.append(event))
    worker._cycle_process(events, {'probe': False})
    assert len(calls) == 1 and calls[0]['schema_ready'] is True


def test_worker_connection_setup_can_exceed_http_budget_but_remains_bounded(monkeypatch):
    from api import config, db_pool, runtime as api_runtime
    import pytest
    clock = [0.0]
    monkeypatch.setattr(db_pool, 'time', SimpleNamespace(monotonic=lambda: clock[0]))
    class Connection:
        closed = False
        def commit(self): pass
        def rollback(self): pass
        def close(self): self.closed = True
    delay = [6.0]
    connection = Connection()
    def connect(*args, **kwargs):
        clock[0] += delay[0]  # includes session initialization after TCP connects
        return connection
    settings = SimpleNamespace(database=SimpleNamespace(backend='postgres', connect=connect))
    monkeypatch.setattr(config, 'load_api_settings', lambda: settings)
    monkeypatch.setattr(api_runtime, 'ServiceRuntime', lambda **kwargs: SimpleNamespace(**kwargs))
    runtime = worker.content_runtime()
    lease = runtime.connection_factory()
    lease.close()
    runtime.connection_factory.close()
    assert connection.closed
    delay[0] = 21.0
    runtime = worker.content_runtime()
    with pytest.raises(TimeoutError, match='connection deadline exceeded'):
        runtime.connection_factory()
    runtime.connection_factory.close()
