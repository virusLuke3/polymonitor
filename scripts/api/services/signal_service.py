from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import outcome_semantics_service
from .trade_watch.common import normalize_signal_payload
from .signal_reads import read_verified_seed


SIGNAL_SNAPSHOT_NAMESPACE_WHALES = "snapshot:signals:whales"
SIGNAL_SNAPSHOT_NAMESPACE_SUSPICIOUS = "snapshot:signals:suspicious"
DEFAULT_WHALE_TRADES_LIMIT = 14
DEFAULT_SUSPICIOUS_TRADES_LIMIT = 12


def build_whale_trades_cache_key(limit: int = 14) -> str:
    return json.dumps({"limit": limit, "v": 2}, sort_keys=True, ensure_ascii=True)


def build_suspicious_trades_cache_key(limit: int = 12) -> str:
    return json.dumps({"limit": limit}, sort_keys=True, ensure_ascii=True)


def _limit_signal_payload(ctx: dict, payload: Dict[str, Any], *, limit: int) -> Dict[str, Any]:
    normalized = normalize_signal_payload(payload, generated_at=ctx["utc_now_iso"]())
    normalized["items"] = [item for item in normalized.get("items", []) if isinstance(item, dict)][: max(0, int(limit))]
    return normalized


def get_signal_snapshot(ctx: dict, *, namespace: str, cache_key: str, limit: int) -> Dict[str, Any]:
    """Read the watcher-owned snapshot; requests never start signal builders."""
    payload = _read_cached_signal_snapshot(
        ctx, namespace=namespace, cache_key=cache_key, ttl_seconds=ctx["SIGNAL_RUNTIME_TTL_SECONDS"]
    )
    if payload is None:
        return {"items": [], "generatedAt": None, "status": "warming", "cacheMode": "seeded"}
    return _limit_signal_payload(ctx, payload, limit=limit)


def _sanitize_signal_payload(ctx: dict, payload: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(payload)
    items = [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]
    positions_by_mode: Dict[str, List[int]] = {"raw": [], "aggregate": [], "probe": []}
    aggregate_kinds = {"volume-flow", "market-flow", "momentum"}
    for index, item in enumerate(items):
        if (item.get("marketId") or item.get("market_id")) is None:
            continue
        if item.get("tokenId") or item.get("token_id"):
            mode = "raw"
        elif str(item.get("kind") or "").strip().lower() in aggregate_kinds and any(
            item.get(key) is not None for key in ("logicalOutcome", "logical_outcome", "outcome")
        ):
            mode = "aggregate"
        elif any(item.get(key) is not None for key in ("logicalOutcome", "logical_outcome", "outcome")):
            # Unknown/row-like cached items are raw by default.  Only named
            # market aggregates above may use a logical slot without a token.
            mode = "raw"
        else:
            mode = "probe"
        positions_by_mode[mode].append(index)
    for mode, positions in positions_by_mode.items():
        if not positions:
            continue
        annotated = outcome_semantics_service.annotate_trade_rows(
            ctx,
            [items[index] for index in positions],
            identity_mode=mode,
        )
        for index, row in zip(positions, annotated):
            items[index] = row
    sanitized["items"] = items
    if payload.get("schemaVersion") == "trade-watch-v1":
        sanitized["coverage"] = {**(payload.get("coverage") or {}),
                                 "labelVerifiedCount": sum(item.get("outcomeSemanticsValid") is True for item in items),
                                 "unverifiedLabelCount": sum(item.get("outcomeSemanticsValid") is not True for item in items)}
        if any(item.get("outcomeSemanticsStatus") == "semantics_query_failed" for item in items):
            sanitized["sourceStates"] = {**(payload.get("sourceStates") or {}), "labels": {"status": "error"}}
            sanitized["error"] = "Outcome labels could not be checked; neutral token observations remain visible."
            if sanitized.get("status") in {"ok", "empty"}:
                sanitized["status"] = "partial"
    if not items and sanitized.get("status") == "ok":
        sanitized["status"] = "empty"
    return sanitized


def _read_cached_signal_snapshot(
    ctx: dict, *, namespace: str, cache_key: str, ttl_seconds: int
) -> Optional[Dict[str, Any]]:
    payload = _load_signal_seed(ctx, namespace=namespace, cache_key=cache_key)
    if payload is None:
        return None
    verification_ctx = ctx.get("verification_context", ctx)
    payload = read_verified_seed(
        verification_ctx, namespace, payload,
        lambda value: _sanitize_signal_payload(verification_ctx, value),
    )
    return _signal_freshness(ctx, payload, ttl_seconds=ttl_seconds)


def _load_signal_seed(ctx: dict, *, namespace: str, cache_key: str) -> Optional[Dict[str, Any]]:
    reader = ctx.get("get_cached_json")
    payload = reader(namespace, cache_key) if callable(reader) else None
    if not isinstance(payload, dict):
        store = ctx.get("SNAPSHOT_STORE")
        payload = store.get_stale(namespace, cache_key) if store is not None else None
    if not isinstance(payload, dict):
        return None
    return payload


def _signal_freshness(ctx: dict, payload: Dict[str, Any], *, ttl_seconds: int) -> Dict[str, Any]:
    try:
        generated = datetime.fromisoformat(str(payload["generatedAt"]).replace("Z", "+00:00"))
        now = datetime.fromisoformat(ctx["utc_now_iso"]().replace("Z", "+00:00"))
        age = (now - generated.astimezone(timezone.utc)).total_seconds()
        fresh = 0 <= age <= ttl_seconds
    except (KeyError, TypeError, ValueError):
        fresh = False
    if not fresh:
        payload["status"] = "stale"
    return payload


def fetch_live_whale_trades_payload(ctx: dict, limit: int = 14) -> Dict[str, Any]:
    from .trade_watch import whales
    return whales.fetch_live_whale_trades_payload(ctx, limit=limit)


def get_whale_trades_snapshot(ctx: dict, limit: int = DEFAULT_WHALE_TRADES_LIMIT) -> Dict[str, Any]:
    return get_signal_snapshot(
        ctx, namespace=SIGNAL_SNAPSHOT_NAMESPACE_WHALES,
        cache_key=build_whale_trades_cache_key(), limit=limit,
    )


def get_suspicious_trades_snapshot(ctx: dict, limit: int = DEFAULT_SUSPICIOUS_TRADES_LIMIT) -> Dict[str, Any]:
    return get_signal_snapshot(
        ctx, namespace=SIGNAL_SNAPSHOT_NAMESPACE_SUSPICIOUS,
        cache_key=build_suspicious_trades_cache_key(), limit=limit,
    )


def fetch_live_suspicious_trades_payload(ctx: dict, limit: int = 12) -> Dict[str, Any]:
    from .trade_watch import flow
    return flow.fetch_live_suspicious_trades_payload(ctx, limit=limit)
