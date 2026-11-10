"""A partial collection must retry before the normal one/six-hour interval."""
from types import SimpleNamespace

import pytest

from runtime import cpi_release_calendar_watcher as calendar
from runtime import energy_gasoline_shock_watcher as energy
from runtime import environment


@pytest.mark.parametrize("module,owner,interval", [
    (calendar, "CpiReleaseCalendarWatcher", 3600),
    (energy, "EnergyGasolineShockWatcher", 21600),
])
def test_partial_then_failed_collection_retries_and_success_restores_cadence(monkeypatch, module, owner, interval):
    results = iter([
        {"status": "stored", "payload": {"status": "degraded"}},
        OSError("source unavailable"),
        {"status": "stored", "payload": {"status": "ok"}},
        KeyboardInterrupt(),
    ])
    failures, delays = [], []

    class Watcher:
        def __init__(self, **kwargs):
            self.interval_seconds = kwargs["interval_seconds"]

        def redis_key(self):
            return "test-source"

        def run_once(self):
            result = next(results)
            if isinstance(result, BaseException):
                raise result
            return result

        def store_meta_fail_soft(self, **kwargs):
            failures.append(kwargs)

        store_seed_meta_fail_soft = store_meta_fail_soft

    clock = iter([0, 10, 300, 310, 900, 910, 1800])
    monkeypatch.setattr(environment, "load_environment", lambda: None)
    monkeypatch.setattr(module, owner, Watcher)
    monkeypatch.setattr(module, "load_api_settings", lambda: SimpleNamespace(
        redis_url="", redis_prefix="", snapshot_sqlite_path="unused"))
    monkeypatch.setattr(module.sys, "argv", ["watcher", "--watch", "--interval", str(interval)])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    monkeypatch.setattr(module.time, "sleep", delays.append)

    assert module.main() == 0
    assert delays == [290, 590, interval - 10]
    assert len(failures) == 1 and failures[0]["status"] == "error"
