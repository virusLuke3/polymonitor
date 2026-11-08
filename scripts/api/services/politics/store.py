"""Versioned evidence plus last successful observations, independent of API workers."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

SOURCE_NS = "source:politics:v1"
BILL_CHECK_INTERVAL_SECONDS = 300
BILL_REQUESTS_PER_ROUND = 5
BILL_REFRESH_SECONDS = 1800


def bill_refresh_interval(target_count):
    """Expected rotation, not permission to fetch more often than source cadence."""
    rounds = (max(0, int(target_count or 0)) + BILL_REQUESTS_PER_ROUND - 1) // BILL_REQUESTS_PER_ROUND
    return max(BILL_REFRESH_SECONDS, rounds * BILL_CHECK_INTERVAL_SECONDS)


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def archive(store, key, body, data, now, *, budget=2 * 1024**3):
    path = Path(store.db_path).with_name("politics.sqlite3")
    if path.exists() and path.stat().st_size + len(body) > budget:
        raise ValueError("Politics archive capacity requires review")
    digest = hashlib.sha256(body).hexdigest()
    with sqlite3.connect(path, timeout=2) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS evidence(source TEXT, revision TEXT, first_received REAL, last_received REAL, body BLOB, normalized BLOB, PRIMARY KEY(source,revision))")
        db.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?) ON CONFLICT(source,revision) DO UPDATE SET last_received=excluded.last_received",
                   (key, digest, now, now, zlib.compress(body), zlib.compress(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())))
    return digest


def collect(store, key, acquire, cadence, *, now=None):
    """Caller holds the owner lock. A bad response can never erase last good data."""
    clock = time.time if now is None else lambda: now
    now = clock()
    previous = store.get_stale(SOURCE_NS, key) or {}
    if previous.get("nextAttemptAt", 0) > now:
        return previous
    state = {**previous, "lastAttemptAt": now, "cadence": cadence}
    try:
        body, data = acquire()
        if not isinstance(data, dict):
            raise ValueError("Invalid normalized source")
        received_at = clock()
        revision = archive(store, key, body, data, received_at)
        # Only publish a success after durable evidence has committed.
        state.update(data=data, revision=revision, lastSuccessAt=received_at,
                     nextAttemptAt=received_at + cadence, failures=0, error=None)
    except Exception as exc:
        response = getattr(exc, "response", None)
        code = response.status_code if response is not None else None
        failures = previous.get("failures", 0) + 1
        delay = min(1800, 300 * 2 ** min(failures - 1, 3))
        if code == 429:
            from api.clients.source_transport import _retry_seconds
            delay = max(delay, _retry_seconds(response.headers.get("Retry-After")))
        if code in (401, 403):
            delay = max(delay, cadence)  # Do not evade a denial through another route.
        if code == 404 and key.startswith("bill:"):
            # GovInfo's publication feed can precede its BILLSTATUS XML. Keep
            # the identity pending, but do not spend a scarce detail slot every round.
            delay = max(delay, min(6 * 3600, 3600 * 2 ** min(failures - 1, 3)))
        # No exception text/URLs: provider errors may contain credentials.
        state.update(error=f"HTTP {code}" if code else type(exc).__name__,
                     failures=failures, nextAttemptAt=clock() + delay)
    if not store.set(SOURCE_NS, key, state, ttl_seconds=366 * 86400):
        raise RuntimeError("Politics source state was not persisted")
    return state


def source(store, key, url, now=None):
    now = time.time() if now is None else now
    value = store.get_stale(SOURCE_NS, key) or {}
    success = value.get("lastSuccessAt")
    interval = value.get("cadence", 3600)
    if key.startswith("bill:"):
        index = store.get_stale(SOURCE_NS, "bill-index") or {}
        interval = max(interval, bill_refresh_interval(index.get("targetCount", len(index.get("ids", [])))))
    return value.get("data", {}), {
        "id": key, "url": url, "lastSuccessAt": iso(success),
        "lastAttemptAt": iso(value.get("lastAttemptAt")), "error": value.get("error"),
        "nextAttemptAt": iso(value.get("nextAttemptAt")), "failures": value.get("failures", 0),
        "usable": success is not None and isinstance(value.get("data"), dict),
        "revision": value.get("revision"),
        "expectedIntervalSeconds": interval, "staleAfterSeconds": 3 * interval,
        "stale": success is None or now - success > 3 * interval,
    }
