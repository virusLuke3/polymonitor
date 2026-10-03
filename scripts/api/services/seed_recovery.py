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


def age_seconds(timestamp: Any, now: str) -> float:
    try:
        value = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        age = (current - value).total_seconds()
        return age if age >= -60 else float("inf")
    except (TypeError, ValueError):
        return float("inf")


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
                    ttl_seconds: int, max_age_seconds: int = 900, retain_seconds: int = 1800) -> dict:
    """GETs never wait for acquisition. Original seed clocks bound all cache tiers."""
    def clock() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def read() -> tuple[dict | None, str]:
        if snapshot_store is not None:
            payload = snapshot_store.get(namespace, cache_key) or snapshot_store.get_stale(namespace, cache_key)
            if isinstance(payload, dict) and payload.get("panelId") == panel_id:
                return payload, "sqlite-seed"
        if redis_get is not None:
            try:
                payload = redis_get(namespace, cache_key)
                if isinstance(payload, dict) and payload.get("panelId") == panel_id:
                    return payload, "redis-seed"
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
    if not usable(payload, max_age_seconds):
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
                            snapshot_store.set(namespace, cache_key, replacement, ttl_seconds)
                            stored = True
                        except Exception:
                            _logger.exception("SQLite recovery write failed namespace=%s", namespace)
                    if redis_set is not None:
                        try:
                            redis_set(namespace, cache_key, replacement, ttl_seconds)
                            stored = True
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
                **({"status": "stale", "error": "Collector snapshot is overdue; recovering in the background"} if stale else {})}
    return {"panelId": panel_id, "status": "warming", "generatedAt": "", "items": [],
            "cacheMode": "warming", "sources": {"collector": "warming"}}
