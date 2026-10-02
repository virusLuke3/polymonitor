from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from .. import clickhouse_orderfilled_service, outcome_semantics_service

SCHEMA_VERSION = "trade-watch-v1"
WHALE_NAMESPACE = "snapshot:signals:whales"
CRITICAL_NOTIONAL = Decimal("2500")
ELEVATED_NOTIONAL = Decimal("1000")

def normalize_signal_payload(
    payload: Dict[str, Any], *, generated_at: str, source: str = "polyData signal seed"
) -> Dict[str, Any]:
    items = payload.get("items")
    normalized = dict(payload)
    normalized["items"] = items if isinstance(items, list) else []
    normalized.setdefault("generatedAt", generated_at)
    normalized.setdefault("source", source)
    normalized.setdefault("status", "ok" if normalized["items"] else "empty")
    normalized.setdefault("cacheMode", "live-build")
    return normalized

def _severity_for_notional(ctx: dict, notional: Any) -> str:
    value = ctx["_safe_decimal"](notional)
    if value is not None and value >= CRITICAL_NOTIONAL:
        return "critical"
    if value is not None and value >= ELEVATED_NOTIONAL:
        return "elevated"
    return "watch"

def _is_live_signal_source(source_mode: str) -> bool:
    return str(source_mode or "") in {"live-trades", "clickhouse-volume-whales", "clickhouse-volume-alpha"}

def _is_near_resolved_price(ctx: dict, price: Any) -> bool:
    parsed = ctx["_safe_decimal"](price)
    return parsed is not None and (parsed > Decimal("0.98") or parsed < Decimal("0.02"))

def _whale_route_key(row: Dict[str, Any]) -> Optional[tuple[str, str]]:
    market_id = str(row.get("market_id") or row.get("marketId") or "").strip()
    route = str(row.get("taker") or row.get("maker") or "").strip().lower()
    if not market_id or not route:
        return None
    return (market_id, route)

def _clickhouse_source_states(ctx: dict, status: str, *, rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    states: Dict[str, Any] = {
        "clickhouse": "ok" if status == "ok" else status,
        "clickhouseMode": clickhouse_orderfilled_service.clickhouse_read_mode(ctx),
    }
    latest_block = None
    for row in rows or []:
        raw = row.get("latest_block") or row.get("block_number")
        try:
            block = int(raw)
        except (TypeError, ValueError):
            continue
        latest_block = block if latest_block is None else max(latest_block, block)
    if latest_block is not None:
        states["clickhouseLatestBlock"] = latest_block
    return states

def _format_trade_item(ctx: dict, row: Dict[str, Any]) -> Dict[str, Any]:
    row = canonical_row(row)
    item = {
        "marketId": row.get("market_id"),
        "localMarketId": row.get("market_id"),
        "marketTitle": row.get("market_title"),
        "timestamp": row.get("timestamp"),
        "txHash": row.get("tx_hash"),
        "blockNumber": row.get("block_number"),
        "logIndex": row.get("log_index"),
        "tokenId": row.get("token_id"),
        "outcome": row.get("outcome"),
        "logicalOutcome": row.get("logicalOutcome") or row.get("logical_outcome"),
        "sourceOutcomeLabel": row.get("sourceOutcomeLabel") or row.get("source_outcome_label"),
        "semanticMode": row.get("semanticMode") or row.get("semantic_mode"),
        "outcomeSemanticsStatus": row.get("outcomeSemanticsStatus") or row.get("outcome_semantics_status"),
        "outcomeSemanticsValid": bool(row.get("outcomeSemanticsValid", row.get("outcome_semantics_valid"))),
        "outcomeSemanticsCapabilities": row.get("outcomeSemanticsCapabilities")
        or {
            "supportsYesNoWording": bool(row.get("supports_yes_no_wording")),
            "supportsDirectionalSemantics": bool(row.get("supports_directional_semantics")),
        },
        "side": row.get("side"),
        "price": ctx["format_trade_decimal"](row.get("price")),
        "size": ctx["format_trade_decimal"](row.get("size")),
        "notional": ctx["format_trade_decimal"](row.get("notional")),
        "maker": ctx["format_trade_address"](row.get("maker")),
        "taker": ctx["format_trade_address"](row.get("taker")),
        "severity": row.get("severity") or _severity_for_notional(ctx, row.get("notional")),
    }
    metric_fields = [
        ("source_mode", "sourceMode"),
        ("signal_type", "signalType"),
        ("threshold_notional", "thresholdNotional"),
        ("elevated_threshold_notional", "elevatedThresholdNotional"),
        ("critical_threshold_notional", "criticalThresholdNotional"),
        ("market_window_notional", "marketWindowNotional"),
        ("market_share", "marketShare"),
    ]
    if outcome_semantics_service.directional_semantics_allowed(row):
        metric_fields.extend(
            [
                ("entry_yes_price", "entryYesPrice"),
                ("price_after_1m", "priceAfter1m"),
                ("price_after_5m", "priceAfter5m"),
                ("price_after_15m", "priceAfter15m"),
                ("edge_after_fees", "edgeAfterFees"),
                ("edge_fee_probability", "edgeFeeProbability"),
            ]
        )
    for source_key, target_key in metric_fields:
        if row.get(source_key) is not None:
            item[target_key] = (
                ctx["format_trade_decimal"](row.get(source_key))
                if source_key != "source_mode" and source_key != "signal_type"
                else row.get(source_key)
            )
    item["id"] = trade_identity(item)
    return item

def _query_whale_rows(ctx: dict, *, limit: int) -> List[Dict[str, Any]]:
    rows = clickhouse_orderfilled_service.get_volume_whale_rows(ctx, limit=max(limit * 2, limit))
    if rows is None:
        raise TimeoutError("Recent whale trade source unavailable")
    return rows

def canonical_row(row: Dict[str, Any]) -> Dict[str, Any]:
    aliases = {"market_id": "marketId", "market_title": "marketTitle", "tx_hash": "txHash",
               "token_id": "tokenId", "block_number": "blockNumber", "log_index": "logIndex",
               "source_outcome_label": "sourceOutcomeLabel", "logical_outcome": "logicalOutcome",
               "outcome_semantics_valid": "outcomeSemanticsValid", "outcome_semantics_status": "outcomeSemanticsStatus"}
    result = dict(row)
    for target, alias in aliases.items():
        if result.get(target) is None:
            result[target] = row.get(alias)
    return result


def trade_identity(item: Dict[str, Any]) -> str:
    # A transaction may contain multiple distinct fills and outcome tokens.
    return ":".join(str(item.get(key) if item.get(key) is not None else "")
                    for key in ("txHash", "logIndex", "tokenId", "side"))


def parse_time(value: Any) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def recent_large_trades(ctx: dict, limit: int) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    # An explicit producer snapshot dependency avoids a second quantile scan.
    key = json.dumps({"limit": 14, "v": 2}, sort_keys=True)
    reader = ctx.get("get_cached_json")
    cached = reader(WHALE_NAMESPACE, key) if callable(reader) else None
    if not isinstance(cached, dict) and ctx.get("SNAPSHOT_STORE") is not None:
        cached = ctx["SNAPSHOT_STORE"].get_stale(WHALE_NAMESPACE, key)
    now = parse_time(ctx["utc_now_iso"]())
    stamp = parse_time(cached.get("generatedAt")) if isinstance(cached, dict) else None
    if (isinstance(cached, dict) and cached.get("schemaVersion") == SCHEMA_VERSION
        and cached.get("status") in {"ok", "empty", "partial"} and now and stamp
        and 0 <= (now-stamp).total_seconds() <= ctx.get("SIGNAL_RUNTIME_TTL_SECONDS", 300)):
        return [{**item, "id": trade_identity(item)} for item in cached.get("items", [])][:limit], {
            "mode": "whale-seed", "status": "ok", "observedAt": cached["generatedAt"],
            "candidateCount": len(cached.get("items", [])), "limit": 14}
    rows = _query_whale_rows(ctx, limit=limit)
    return [_format_trade_item(ctx, row) for row in rows[:limit]], {
        "mode": "clickhouse-volume-whales", "status": "ok", "candidateCount": len(rows), "limit": limit*2}
