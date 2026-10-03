"""Crypto quote clocks, rolling-change semantics and per-symbol retention."""
from __future__ import annotations

import math
from api.services.seed_recovery import age_seconds

MAX_SEED_AGE_SECONDS = 180
RETAIN_SECONDS = 900


def usable_quote(row: dict, now: str) -> bool:
    try:
        return float(row.get("price") or 0) > 0 and math.isfinite(float(row["price"])) and age_seconds(row.get("quoteAt"), now) < RETAIN_SECONDS
    except (ValueError, TypeError, KeyError):
        return False


def merge_snapshot(payload: dict, previous: dict, entries: list[tuple[str, str, str]], now: str) -> dict:
    fresh = {row["symbol"]: row for row in payload.get("items", []) if usable_quote(row, now)}
    old = {row["symbol"]: row for row in previous.get("items", []) if usable_quote(row, now)}
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
    return {
        **payload, "kind": "crypto", "items": rows,
        "generatedAt": payload.get("generatedAt") if fresh else previous.get("generatedAt") or "",
        "lastAttemptAt": now, "status": "degraded" if failed else "ok", "refreshIntervalSeconds": 60,
        "coverage": {"expected": len(entries), "succeeded": len(entries) - len(failed), "retained": len(retained),
                     "missing": len(missing), "failedSymbols": failed},
    }
