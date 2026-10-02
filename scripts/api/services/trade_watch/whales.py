from __future__ import annotations
from typing import Any, Dict, List
from .common import (SCHEMA_VERSION, _query_whale_rows, _is_near_resolved_price,
                     _whale_route_key, _is_live_signal_source, _clickhouse_source_states,
                     _format_trade_item, normalize_signal_payload)

def _build_whale_trades_payload(ctx: dict, limit: int = 14) -> Dict[str, Any]:
    rows = _query_whale_rows(ctx, limit=limit)
    items: List[Dict[str, Any]] = []
    seen_hashes: set[str] = set()
    seen_routes: set[tuple[str, str]] = set()
    source_modes: set[str] = set()
    for row in rows:
        tx_hash = str(row.get("tx_hash") or "")
        if tx_hash and tx_hash in seen_hashes:
            continue
        if tx_hash:
            seen_hashes.add(tx_hash)
        if _is_near_resolved_price(ctx, row.get("price")):
            continue
        route_key = _whale_route_key(row)
        if route_key is not None and str(row.get("source_mode") or "") == "clickhouse-volume-whales":
            if route_key in seen_routes:
                continue
            seen_routes.add(route_key)
        source_modes.add(str(row.get("source_mode") or "unknown"))
        items.append(_format_trade_item(ctx, row))
        if len(items) >= limit:
            break
    status = "empty"
    if items:
        status = "ok" if source_modes and all(_is_live_signal_source(mode) for mode in source_modes) else "degraded"
    source_mode = (
        next(iter(source_modes))
        if len(source_modes) == 1
        else "mixed-live"
        if source_modes and all(_is_live_signal_source(mode) for mode in source_modes)
        else "fallback"
        if source_modes
        else "none"
    )
    return normalize_signal_payload(
        {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "whale-trades",
            "items": items,
            "coverage": {"candidateCount": len(rows), "displayedCount": len(items),
                         "labelVerifiedCount": sum(item.get("outcomeSemanticsValid") is True for item in items),
                         "limit": limit, "limited": len(rows) >= limit},
            "generatedAt": ctx["utc_now_iso"](),
            "status": status,
            "sourceMode": source_mode,
            "sourceStates": _clickhouse_source_states(ctx, "ok" if status == "ok" else status, rows=rows),
        },
        generated_at=ctx["utc_now_iso"](),
    )

def fetch_live_whale_trades_payload(ctx: dict, limit: int = 14) -> Dict[str, Any]:
    return normalize_signal_payload(
        _build_whale_trades_payload(ctx, limit=limit),
        generated_at=ctx["utc_now_iso"](),
    )
