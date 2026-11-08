"""One writer; bounded observations and read-only API access."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path


def database_path(snapshot_path):
    return os.environ.get("POLYDATA_CRYPTO_STRATEGY_DB") or str(Path(snapshot_path).with_name("crypto_strategy.sqlite3"))


def read_snapshot(path):
    if not Path(path).is_file():
        return None
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=.75) as conn:
        row = conn.execute("SELECT payload FROM snapshot WHERE id=1").fetchone()
        return json.loads(row[0]) if row else None


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=2)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("CREATE TABLE IF NOT EXISTS snapshot (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS samples (series TEXT, t INTEGER, v REAL, PRIMARY KEY(series,t))")
        self.conn.execute("CREATE TABLE IF NOT EXISTS source_cache (key TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        self.conn.commit()

    def source_entries(self):
        return {key: json.loads(payload) for key, payload in
                self.conn.execute("SELECT key,payload FROM source_cache LIMIT 64")}

    def sample(self, series, at, value):
        if at is not None and value is not None:
            self.conn.execute("INSERT OR REPLACE INTO samples VALUES (?,?,?)", (series, int(at), value))

    def history(self, series, since):
        rows = self.conn.execute("SELECT t,v FROM samples WHERE series=? AND t>=? ORDER BY t DESC LIMIT 300", (series, since)).fetchall()
        return [{"t": t, "v": v} for t, v in reversed(rows)]

    def publish(self, value, now, source_entries=None):
        self.conn.execute("DELETE FROM samples WHERE t < ?", (now - 7 * 86400000,))
        self.conn.execute("INSERT OR REPLACE INTO snapshot VALUES(1,?)", (json.dumps(value, allow_nan=False),))
        if source_entries is not None:
            if len(source_entries) > 64:
                raise ValueError("CRYPTO_SOURCE_CACHE_LIMIT")
            self.conn.execute("DELETE FROM source_cache")
            self.conn.executemany("INSERT INTO source_cache VALUES(?,?)",
                                  [(key, json.dumps(entry, allow_nan=False)) for key, entry in source_entries.items()])
        self.conn.commit()


def get_snapshot(path, *, reference_only=False):
    import time
    from .contracts import iso
    from .native_reference import current_references
    references = current_references()
    if reference_only:
        now = time.time() * 1000
        return {"schemaVersion": 1, "kind": "crypto-strategy", "status": "partial", "generatedAt": iso(now),
                "collectedAt": now, "references": references, "assets": {}, "options": {}, "stablecoins": [],
                "inflows": {"mode": "unavailable", "rows": []}}
    try:
        data = read_snapshot(path)
    except (OSError, sqlite3.Error, ValueError):
        data = None
    if data is None:
        return {"schemaVersion": 1, "kind": "crypto-strategy", "status": "warming", "generatedAt": None,
                "assets": {}, "options": {}, "stablecoins": [], "inflows": {"mode": "unavailable", "rows": []}}
    age = time.time() * 1000 - data["collectedAt"]
    return {**data, "references": references, "status": "stale" if age > 120000 or age < -30000 else data["status"], "servedAt": iso(time.time() * 1000)}
