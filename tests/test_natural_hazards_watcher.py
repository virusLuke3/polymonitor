from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from runtime import natural_hazards_watcher


def test_watcher_runs_live_refresh_outside_api_request(monkeypatch, tmp_path: Path) -> None:
    captured = {}

    def fake_snapshot(context, *, limit, allow_provider_fetch):
        captured.update({
            "context": context,
            "limit": limit,
            "allow_provider_fetch": allow_provider_fetch,
        })
        return {
            "isPartial": False,
            "counts": {"events": 7},
            "sources": [{"key": "usgs", "status": "ok"}],
        }

    monkeypatch.setattr(
        natural_hazards_watcher.natural_hazards,
        "get_natural_hazards_snapshot",
        fake_snapshot,
    )
    watcher = natural_hazards_watcher.NaturalHazardsWatcher(
        settings=SimpleNamespace(),
        snapshot_sqlite_path=str(tmp_path / "snapshots.sqlite3"),
        interval_seconds=90,
    )

    result = watcher.run_once()

    assert captured["allow_provider_fetch"] is True
    assert captured["context"]["SNAPSHOT_STORE"] is watcher.snapshot_store
    assert watcher.session.trust_env is False
    assert result == {"status": "ok", "eventCount": 7, "sources": {"usgs": "ok"}}
