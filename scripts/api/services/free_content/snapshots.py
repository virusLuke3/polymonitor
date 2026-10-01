"""One shared, bounded candidate seed; market/window/policy are projected at read time.

The existing content worker owns refreshes. API reads never acquire external feeds.
Redis is optional, SQLite survives process restarts, and cold reads use the existing
indexed local query. Cached raw records never bypass current public-display policy.
"""
from __future__ import annotations

from contextlib import nullcontext
from datetime import datetime, timezone
from .public import payload, read_records

NAMESPACE = "snapshot:content:free-public"
CACHE_KEY = "candidates-v1"
TTL_SECONDS = 90
MAX_STALE_SECONDS = 300


def _age(snapshot, now):
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != 1 or not isinstance(snapshot.get("records"), list):
        return float("inf")
    if not all(isinstance(row, dict) and row.get("record_kind") in {"source", "item"}
               and isinstance(row.get("payload"), str) for row in snapshot["records"]):
        return float("inf")
    try:
        return max(0, (now - datetime.fromisoformat(snapshot["generatedAt"].replace("Z", "+00:00"))).total_seconds())
    except (KeyError, TypeError, ValueError):
        return float("inf")


def _cached(cache, now):
    store = cache.get("store")
    get_json = cache.get("get_json")
    try:
        value = get_json(NAMESPACE, CACHE_KEY) if get_json else None
        if _age(value, now) < TTL_SECONDS:
            return value, "redis"
    except Exception:
        pass  # Optional cache failure cannot make verified content unavailable.
    if store:
        try:
            value = store.get_stale(NAMESPACE, CACHE_KEY)
            age = _age(value, now)
            if age <= MAX_STALE_SECONDS:
                return value, "sqlite" if age < TTL_SECONDS else "sqlite-stale"
        except Exception:
            pass
    return None, None


def refresh_candidates(storage, cache, *, now=None):
    """Write only after a successful query; a failed refresh retains the previous seed."""
    now = now or datetime.now(timezone.utc)
    snapshot = {"schemaVersion": 1, "generatedAt": now.isoformat().replace("+00:00", "Z"),
                "records": read_records(storage, days=30, now=now)}
    store = cache.get("store")
    if store:
        store.set(NAMESPACE, CACHE_KEY, snapshot, TTL_SECONDS)
    set_json = cache.get("set_json")
    if set_json:
        try:
            set_json(NAMESPACE, CACHE_KEY, snapshot, TTL_SECONDS)
        except Exception:
            pass
    return snapshot


def read_payload(storage, cache=None, *, market=None, market_id=None, limit=20, days=7, now=None):
    now = now or datetime.now(timezone.utc)
    cache = cache or {}
    snapshot, mode = _cached(cache, now)
    if snapshot is None:
        store = cache.get("store")
        # Recheck under the existing cross-process lock to prevent cold-query bursts.
        with store.fetch_lock(NAMESPACE, CACHE_KEY) if store else nullcontext():
            snapshot, mode = _cached(cache, now)
            if snapshot is None:
                snapshot = refresh_candidates(storage, cache, now=now)
                mode = "database"
    result = payload(storage, market=market, market_id=market_id, limit=limit, days=days,
                     now=now, records=snapshot["records"])
    stale = _age(snapshot, now) >= TTL_SECONDS
    result.update(generatedAt=snapshot["generatedAt"], cacheMode=mode, stale=stale)
    if stale and result["status"] == "ready":
        result["status"] = "partial"
    return result
