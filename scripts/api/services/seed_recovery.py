"""Bounded seed reads and keyed, unscheduled recovery using existing builders."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any, Callable

from flask import current_app, has_app_context

_state_lock = threading.Lock()
_running: set[str] = set()
_last_attempts: dict[str, float] = {}
_slots = threading.BoundedSemaphore(4)
_logger = logging.getLogger(__name__)


def limit_snapshot_items(payload: dict, limit: int) -> dict:
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    limit = max(0, int(limit or 10))
    return {
        **payload,
        "items": items[:limit],
        "summary": {
            **(payload.get("summary") if isinstance(payload.get("summary"), dict) else {}),
            "count": min(len(items), limit),
            "totalCount": len(items),
        },
    }


def age_seconds(timestamp: Any, now: str) -> float:
    try:
        value = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        age = (current - value).total_seconds()
        return age if age >= -60 else float("inf")
    except (TypeError, ValueError):
        return float("inf")


def read_public_seed(*, namespace: str, cache_key: str, snapshot_store: Any,
                     redis_get: Callable | None, max_age_seconds: int,
                     retain_seconds: int, now: str | None = None) -> dict | None:
    """Read an existing owner's publication; never acquire, write or renew it.

    The configured seed store is authoritative; legacy mirrors are offline-only,
    and all tiers are bounded by the original payload clock, not storage TTL.
    """
    current = now or datetime.now(timezone.utc).isoformat()

    def accepted(value: Any, mode: str) -> dict | None:
        if not isinstance(value, dict):
            return None
        if str(value.get("status") or "").lower() in {"error", "failed", "unavailable", "warming", "invalid"}:
            return None
        age = age_seconds(value.get("generatedAt"), current)
        if age >= retain_seconds:
            return None
        return {**value, "cacheMode": mode,
                **({"status": "stale"} if age >= max_age_seconds else {})}

    if snapshot_store is not None:
        for getter in (snapshot_store.get, snapshot_store.get_stale):
            value = accepted(getter(namespace, cache_key), getattr(snapshot_store, "backend", "sqlite") + "-seed")
            if value is not None:
                return value
    if redis_get is not None and getattr(snapshot_store, "backend", "sqlite") != "redis":
        try:
            return accepted(redis_get(namespace, cache_key), "redis-seed")
        except Exception:
            _logger.warning("Optional Redis seed read failed namespace=%s", namespace)
    return None


def retain_failed_rows(previous: dict, failed_ids: list[str], now: str) -> list[dict]:
    """Retain only failed identities for 30m, never renew their acquisition clock."""
    failed = set(failed_ids)
    rows = []
    for row in previous.get("items", []):
        if not isinstance(row, dict) or row.get("id") not in failed:
            continue
        fetched_at = row.get("fetchedAt") or previous.get("generatedAt")
        if age_seconds(fetched_at, now) >= 1800:
            continue
        rows.append({**row, "fetchedAt": fetched_at, "retained": True, "sourceStatus": "stale",
                     "tags": [tag for tag in row.get("tags", []) if tag != "STALE"][:2] + ["STALE"]})
    return rows


def bounded_rows(payload: dict, now: str, retain_seconds: int = 1800) -> dict:
    """Publication/cache copies never extend an individual row's source lifetime."""
    original = payload.get("items")
    if not isinstance(original, list):
        return payload
    rows = [row for row in original if isinstance(row, dict) and
            age_seconds(row.get("sourceFetchedAt") or row.get("fetchedAt") or payload.get("generatedAt"), now) < retain_seconds]
    if len(rows) == len(original):
        return payload
    return {**payload, "items": rows, "status": "partial" if rows else "unavailable",
            "summary": {**(payload.get("summary") or {}), "count": len(rows), "expiredCount": len(original) - len(rows)}}


def recover_seed(key: str, callback: Callable[[], None]) -> bool:
    """At most four running recoveries and one attempt/key/30s per process."""
    app = current_app._get_current_object() if has_app_context() else None
    now = time.monotonic()
    with _state_lock:
        if key in _running or now - _last_attempts.get(key, float("-inf")) < 30 or not _slots.acquire(blocking=False):
            return False
        _running.add(key)
        _last_attempts[key] = now
        for old in list(_last_attempts):
            if old not in _running and now - _last_attempts[old] >= 30:
                del _last_attempts[old]

    def run() -> None:
        try:
            with app.app_context() if app is not None else nullcontext():
                callback()
        except Exception:
            _logger.exception("Seed recovery failed namespace=%s", key)
        finally:
            with _state_lock:
                _running.discard(key)
            _slots.release()

    try:
        threading.Thread(target=run, name="panel-seed-recovery", daemon=True).start()
    except Exception:
        with _state_lock:
            _running.discard(key)
        _slots.release()
        raise
    return True


def read_watch_seed(*, namespace: str, cache_key: str, panel_id: str, snapshot_store: Any,
                    redis_get: Callable | None, redis_set: Callable | None, builder: Callable[[], dict],
                    ttl_seconds: int, max_age_seconds: int = 900, retain_seconds: int = 1800,
                    owner_meta_namespace: str | None = None) -> dict:
    """GETs never wait for acquisition. Original seed clocks bound all cache tiers."""
    def clock() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def read() -> tuple[dict | None, str]:
        if snapshot_store is not None:
            payload = snapshot_store.get(namespace, cache_key) or snapshot_store.get_stale(namespace, cache_key)
            if isinstance(payload, dict) and payload.get("panelId") == panel_id:
                return bounded_rows(payload, clock(), retain_seconds), getattr(snapshot_store, "backend", "sqlite") + "-seed"
        if redis_get is not None and getattr(snapshot_store, "backend", "sqlite") != "redis":
            try:
                payload = redis_get(namespace, cache_key)
                if isinstance(payload, dict) and payload.get("panelId") == panel_id:
                    return bounded_rows(payload, clock(), retain_seconds), "redis-seed"
            except Exception:
                _logger.warning("Optional Redis seed read failed namespace=%s", namespace)
        return None, "warming"

    def usable(payload: dict | None, age: int) -> bool:
        if payload is None or payload.get("status") in {"error", "failed", "unavailable", "warming"}:
            return False
        sources = payload.get("sources") or {}
        if not payload.get("items") and isinstance(sources, dict) and sources:
            values = {str(value).lower() for value in sources.values()}
            if values <= {"error", "failed", "unavailable", "timeout", "warming"}:
                return False
        return age_seconds(payload.get("generatedAt"), clock()) < age

    payload, mode = read()
    owner_active = False
    if owner_meta_namespace and snapshot_store is not None:
        meta = snapshot_store.get_stale(owner_meta_namespace, panel_id)
        if isinstance(meta, dict):
            interval = min(3600, max(60, int(meta.get("expectedIntervalSeconds") or 600)))
            owner_active = age_seconds(meta.get("lastAttemptAt"), clock()) < interval * 2
    if getattr(snapshot_store, "backend", "sqlite") == "redis":
        owner_active = True  # Scheduled collectors own public seed acquisition.
    if not usable(payload, max_age_seconds) and not owner_active:
        def recover() -> None:
            lock = snapshot_store.fetch_lock(namespace, cache_key, timeout=0) if snapshot_store is not None and hasattr(snapshot_store, "fetch_lock") else nullcontext()
            try:
                with lock:
                    current, _ = read()
                    if usable(current, max_age_seconds):
                        return
                    replacement = builder()
                    if not usable(replacement, max_age_seconds):
                        raise RuntimeError("Builder did not publish a usable snapshot")
                    latest, _ = read()
                    if latest is not None and age_seconds(latest.get("generatedAt"), clock()) < age_seconds(replacement.get("generatedAt"), clock()):
                        return  # A newer watcher publication wins.
                    stored = False
                    if snapshot_store is not None:
                        try:
                            stored = snapshot_store.set(namespace, cache_key, replacement, ttl_seconds) is not False
                        except Exception:
                            _logger.exception("SQLite recovery write failed namespace=%s", namespace)
                    if redis_set is not None and (snapshot_store is None or stored):
                        try:
                            redis_set(namespace, cache_key, replacement, ttl_seconds)
                            if snapshot_store is None and redis_get is not None:
                                stored = redis_get(namespace, cache_key) == replacement
                        except Exception:
                            _logger.exception("Redis recovery write failed namespace=%s", namespace)
                    if not stored:
                        raise RuntimeError("No seed cache accepted the recovery")
            except TimeoutError:
                return  # Another API process owns the existing fetch lock.
        recover_seed(namespace, recover)
    if usable(payload, retain_seconds):
        stale = not usable(payload, max_age_seconds)
        return {**payload, "cacheMode": "stale-seed" if stale else mode,
                **({"status": "stale", "error": "Collector snapshot is overdue; waiting for its scheduled collector" if owner_active else "Collector snapshot is overdue; recovering in the background"} if stale else {})}
    return {"panelId": panel_id, "status": "warming", "generatedAt": "", "items": [],
            "cacheMode": "warming", "sources": {"collector": "warming"}}
