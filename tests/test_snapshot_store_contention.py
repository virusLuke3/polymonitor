from __future__ import annotations

import sqlite3
import sys
import time
from pathlib import Path


SCRIPTS_ROOT = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from runtime.snapshot_store import SnapshotStore


def test_snapshot_store_uses_wal_and_round_trips_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "snapshots.sqlite3"
    store = SnapshotStore(str(db_path))

    assert store.set("map", "hazards", {"events": [1]}, 60) is True
    assert store.get("map", "hazards") == {"events": [1]}

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    finally:
        connection.close()


def test_snapshot_write_fails_open_with_bounded_wait_during_contention(tmp_path: Path) -> None:
    db_path = tmp_path / "snapshots.sqlite3"
    store = SnapshotStore(str(db_path), busy_timeout_ms=20)
    assert store.set("map", "hazards", {"version": 1}, 60) is True

    blocker = sqlite3.connect(db_path, timeout=0.1)
    blocker.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        assert store.set("map", "hazards", {"version": 2}, 60) is False
    finally:
        blocker.rollback()
        blocker.close()

    assert time.monotonic() - started < 0.25
    assert store.get("map", "hazards") == {"version": 1}
