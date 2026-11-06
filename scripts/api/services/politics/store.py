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
    now = time.time() if now is None else now
    previous = store.get_stale(SOURCE_NS, key) or {}
    if previous.get("nextAttemptAt", 0) > now:
        return previous
    state = {**previous, "lastAttemptAt": now, "cadence": cadence}
    try:
        body, data = acquire()
        if not isinstance(data, dict):
            raise ValueError("Invalid normalized source")
        revision = archive(store, key, body, data, now)
        # Only publish a success after durable evidence has committed.
        state.update(data=data, revision=revision, lastSuccessAt=now,
                     nextAttemptAt=now + cadence, failures=0, error=None)
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
        # No exception text/URLs: provider errors may contain credentials.
        state.update(error=f"HTTP {code}" if code else type(exc).__name__,
                     failures=failures, nextAttemptAt=now + delay)
    if not store.set(SOURCE_NS, key, state, ttl_seconds=366 * 86400):
        raise RuntimeError("Politics source state was not persisted")
    return state


def source(store, key, url, now=None):
    now = time.time() if now is None else now
    value = store.get_stale(SOURCE_NS, key) or {}
    success = value.get("lastSuccessAt")
    return value.get("data", {}), {
        "id": key, "url": url, "lastSuccessAt": iso(success),
        "lastAttemptAt": iso(value.get("lastAttemptAt")), "error": value.get("error"),
        "revision": value.get("revision"),
        "stale": success is None or now - success > 3 * value.get("cadence", 3600),
    }
