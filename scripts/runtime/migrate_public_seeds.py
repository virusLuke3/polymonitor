"""Explicit, resumable SQLite -> Redis seed import; source is always read-only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.config import load_api_settings
from runtime.redis_snapshot_store import create_snapshot_store, public_namespace, RETENTION_SECONDS


def migrate(store, path, *, apply=False):
    counts = {"eligible": 0, "imported": 0, "expired": 0, "private": 0, "newer": 0}
    with sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True) as db:
        for ns, key, raw, updated, expires in db.execute(
                "SELECT namespace,cache_key,payload_json,updated_at,expires_at FROM panel_snapshots"):
            if not public_namespace(ns):
                counts["private"] += 1
                continue
            if max(expires, updated + RETENTION_SECONDS) <= time.time():
                counts["expired"] += 1
                continue
            counts["eligible"] += 1
            if apply:
                accepted = store.import_snapshot(ns, key, json.loads(raw), updated, expires)
                counts["imported" if accepted else "newer"] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = load_api_settings()
    store = create_snapshot_store(settings.snapshot_sqlite_path)
    if getattr(store, "backend", "sqlite") != "redis":
        raise RuntimeError("Migration requires Redis mode")
    result = migrate(store, settings.snapshot_sqlite_path, apply=args.apply)
    # Crypto's history remains SQLite; only its public current result migrates.
    from api.services.crypto_strategy.store import database_path, NAMESPACE, CACHE_KEY
    crypto_path = Path(database_path(settings.snapshot_sqlite_path))
    if crypto_path.exists():
        with sqlite3.connect(crypto_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
            row = db.execute("SELECT payload FROM snapshot WHERE id=1").fetchone()
        if row:
            payload = json.loads(row[0])
            updated = float(payload["collectedAt"]) / 1000
            result["crypto"] = (store.import_snapshot(NAMESPACE, CACHE_KEY, payload, updated, updated + 120)
                                if args.apply else "eligible")
    print(json.dumps({"applied": args.apply, **result}))


if __name__ == "__main__":
    main()
