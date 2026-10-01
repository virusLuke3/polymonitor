"""One shared, bounded candidate seed; market/window/policy are projected at read time.

The existing content worker owns refreshes. API reads never acquire external feeds.
Redis is optional, SQLite survives process restarts, and cold reads use the existing
indexed local query. Cached raw records never bypass current public-display policy.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
import logging
from .public import payload, read_records

NAMESPACE = "snapshot:content:free-public"
CACHE_KEY = "candidates-v3"
TTL_SECONDS = 90
MAX_STALE_SECONDS = 300
logger = logging.getLogger(__name__)


def _age(snapshot, now):
    if not isinstance(snapshot, dict) or snapshot.get("schemaVersion") != 1 or not isinstance(snapshot.get("records"), list):
        return float("inf")
    if not all(isinstance(row, dict) and row.get("record_kind") in {"source", "item", "coverage"}
               and isinstance(row.get("payload"), str) for row in snapshot["records"]):
        return float("inf")
    try:
        age = (now - datetime.fromisoformat(snapshot["generatedAt"].replace("Z", "+00:00"))).total_seconds()
        return max(0, age) if age >= -60 else float("inf")
    except (KeyError, TypeError, ValueError):
        return float("inf")


def _cached(cache, now):
    store = cache.get("store")
    get_json = cache.get("get_json")
    # The durable local seed is the latency bound. Optional Redis must not sit
    # in front of a fresh local hit on every HTTP request.
    if store:
        try:
            local = store.get_stale(NAMESPACE, CACHE_KEY)
            if _age(local, now) < TTL_SECONDS:
                return local, "sqlite"
        except Exception:
            pass
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


def refresh_candidates(storage, cache, *, now=None, require_cache=False):
    """Write only after a successful query; a failed refresh retains the previous seed."""
    now = now or datetime.now(timezone.utc)
    snapshot = {"schemaVersion": 1, "generatedAt": now.isoformat().replace("+00:00", "Z"),
                "records": read_records(storage, days=30, now=now)}
    store = cache.get("store")
    persisted = False
    if store:
        try:
            persisted = bool(store.set(NAMESPACE, CACHE_KEY, snapshot, TTL_SECONDS))
        except Exception as exc:
            logger.warning("Content SQLite cache write failed: %s", type(exc).__name__)
    set_json = cache.get("set_json")
    if set_json:
        try:
            written = set_json(NAMESPACE, CACHE_KEY, snapshot, TTL_SECONDS)
            persisted = bool(written) or persisted
            # The existing Redis setter returns None and tolerates write failures.
            if not persisted and cache.get("get_json"):
                verified = cache["get_json"](NAMESPACE, CACHE_KEY)
                persisted = _age(verified, now) < TTL_SECONDS and verified.get("generatedAt") == snapshot["generatedAt"]
        except Exception as exc:
            logger.warning("Content Redis cache write failed: %s", type(exc).__name__)
    if require_cache and not persisted:
        raise RuntimeError("Content candidate seed could not be persisted")
    return snapshot


def read_payload(storage, cache=None, *, market=None, market_id=None, limit=20, days=7, now=None):
    now = now or datetime.now(timezone.utc)
    cache = cache or {}
    snapshot, mode = _cached(cache, now)
    if snapshot is None:
        store = cache.get("store")
        # Recheck under the existing cross-process lock to prevent cold-query bursts.
        with ExitStack() as stack:
            if store:
                try:
                    stack.enter_context(store.fetch_lock(NAMESPACE, CACHE_KEY, timeout=1))
                except TimeoutError:
                    raise  # Bound cold requests instead of starting duplicate database queries.
                except OSError as exc:
                    logger.warning("Content cache lock unavailable: %s", type(exc).__name__)
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
