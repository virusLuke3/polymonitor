"""Commodity snapshot quality and bounded seed recovery, independent of views."""
from __future__ import annotations

import math
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

MAX_SEED_AGE_SECONDS = 180
RETAIN_SECONDS = 900
_recovery_lock = threading.Lock()
_last_recovery_attempt = float("-inf")


def age_seconds(timestamp: Any, now: str) -> float:
    try:
        value = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        current = datetime.fromisoformat(now.replace("Z", "+00:00"))
        age = (current - value).total_seconds()
        return age if age >= -60 else float("inf")
    except (TypeError, ValueError):
        return float("inf")


def valid_price(row: dict) -> bool:
    try:
        return row.get("price") is not None and math.isfinite(float(row["price"]))
    except (ValueError, TypeError):
        return False


def merge_snapshot(payload: dict, previous: dict, entries: list[tuple[str, str, str]], now: str) -> dict:
    """Retain failed symbols individually without changing their observation clocks."""
    fresh = {row["symbol"]: row for row in payload.get("items", []) if valid_price(row)}
    old = {row["symbol"]: row for row in previous.get("items", []) if valid_price(row)}
    rows, failed, retained, missing = [], [], [], []
    for _, _, symbol in entries:
        if symbol in fresh:
            rows.append({**fresh[symbol], "acquisitionState": "ok"})
            continue
        failed.append(symbol)
        row = old.get(symbol)
        if row and age_seconds(row.get("fetchedAt") or previous.get("generatedAt"), now) < RETAIN_SECONDS:
            rows.append({**row, "acquisitionState": "retained"})
            retained.append(symbol)
        else:
            missing.append(symbol)
    generated_at = payload.get("generatedAt") if fresh else previous.get("generatedAt") or payload.get("generatedAt")
    return {
        **payload, "kind": "commodities", "items": rows,
        "generatedAt": generated_at, "lastAttemptAt": now,
        "status": "degraded" if failed else "ok",
        "coverage": {"expected": len(entries), "succeeded": len(entries) - len(failed),
                     "retained": len(retained), "missing": len(missing),
                     "failedSymbols": failed, "retainedSymbols": retained, "missingSymbols": missing},
        "source": "Yahoo Finance", "refreshIntervalSeconds": 60,
        "error": f"{len(failed)} quote acquisitions failed; {len(retained)} last good quotes retained" if failed else None,
    }


def seeded_response(payload: dict, now: str) -> dict:
    if age_seconds(payload.get("generatedAt"), now) > MAX_SEED_AGE_SECONDS:
        return {**payload, "status": "stale", "error": "Collector snapshot is overdue; checking the source in the background"}
    return payload


def recover_seed(fetch_and_store: Callable[[], None]) -> bool:
    """One read-through recovery per process, at most every 30s; never block UI reads.

    This reuses the existing fetcher and cache, with no additional collection loop.
    The normal watcher remains the source owner.
    """
    global _last_recovery_attempt
    if not _recovery_lock.acquire(blocking=False):
        return False
    now = time.monotonic()
    if now - _last_recovery_attempt < 30:
        _recovery_lock.release()
        return False
    _last_recovery_attempt = now

    def run() -> None:
        try:
            fetch_and_store()
        finally:
            _recovery_lock.release()

    try:
        threading.Thread(target=run, name="commodity-seed-recovery", daemon=True).start()
    except Exception:
        _recovery_lock.release()
        raise
    return True
