from __future__ import annotations

from api.context import runtime_resources

import json
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional

from . import clickhouse_orderfilled_service, outcome_semantics_service


CRITICAL_NOTIONAL = Decimal("2500")
ELEVATED_NOTIONAL = Decimal("1000")
SIGNAL_SNAPSHOT_NAMESPACE_ALPHA = "snapshot:signals:alpha"
SIGNAL_SNAPSHOT_NAMESPACE_WHALES = "snapshot:signals:whales"
SIGNAL_SNAPSHOT_NAMESPACE_SUSPICIOUS = "snapshot:signals:suspicious"
DEFAULT_ALPHA_SIGNAL_LIMIT = 8
DEFAULT_WHALE_TRADES_LIMIT = 14
DEFAULT_SUSPICIOUS_TRADES_LIMIT = 12


def build_whale_trades_cache_key(limit: int = 14) -> str:
    return json.dumps({"limit": limit, "v": 2}, sort_keys=True, ensure_ascii=True)


def build_suspicious_trades_cache_key(limit: int = 12) -> str:
    return json.dumps({"limit": limit}, sort_keys=True, ensure_ascii=True)


def build_alpha_signal_cache_key(limit: int = 8) -> str:
    return json.dumps({"limit": limit}, sort_keys=True, ensure_ascii=True)


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


def _limit_signal_payload(ctx: dict, payload: Dict[str, Any], *, limit: int) -> Dict[str, Any]:
    normalized = normalize_signal_payload(payload, generated_at=ctx["utc_now_iso"]())
    normalized["items"] = [item for item in normalized.get("items", []) if isinstance(item, dict)][: max(0, int(limit))]
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


def _clickhouse_signal_queries_available(ctx: dict) -> bool:
    return ctx.get("app") is not None and callable(ctx.get("query_all"))


def _format_percent(ctx: dict, value: Any) -> str:
    parsed = ctx["_safe_decimal"](value)
    if parsed is None:
        return "--"
    return f"{(parsed * Decimal('100')).quantize(Decimal('0.1'))}%"


def _money_text(ctx: dict, value: Any) -> str:
    parsed = ctx["_safe_decimal"](value)
    if parsed is None:
        return "$--"
    if parsed >= Decimal("1000000"):
        return f"${(parsed / Decimal('1000000')).quantize(Decimal('0.1'))}M"
    if parsed >= Decimal("1000"):
        return f"${(parsed / Decimal('1000')).quantize(Decimal('0.1'))}k"
    return f"${parsed.quantize(Decimal('1'))}"


def _is_near_resolved_price(ctx: dict, price: Any) -> bool:
    parsed = ctx["_safe_decimal"](price)
    return parsed is not None and (parsed > Decimal("0.98") or parsed < Decimal("0.02"))


def _whale_route_key(row: Dict[str, Any]) -> Optional[tuple[str, str]]:
    market_id = str(row.get("market_id") or row.get("marketId") or "").strip()
    route = str(row.get("taker") or row.get("maker") or "").strip().lower()
    if not market_id or not route:
        return None
    return (market_id, route)


def _clickhouse_source_states(status: str, *, rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    states: Dict[str, Any] = {
        "clickhouse": "ok" if status == "ok" else status,
        "clickhouseMode": clickhouse_orderfilled_service.clickhouse_read_mode(),
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
    item = {
        "marketId": row.get("market_id"),
        "localMarketId": row.get("market_id"),
        "marketTitle": row.get("market_title"),
        "timestamp": row.get("timestamp"),
        "txHash": row.get("tx_hash"),
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
    return item


def _format_alpha_volume_signal(ctx: dict, row: Dict[str, Any]) -> Dict[str, Any]:
    if not outcome_semantics_service.directional_semantics_allowed(row):
        raise ValueError("directional outcome semantics required for alpha volume signal")
    flow = ctx["format_trade_decimal"](row.get("flow_notional"))
    net_flow = ctx["format_trade_decimal"](row.get("net_flow_notional"))
    max_trade = ctx["format_trade_decimal"](row.get("max_trade_notional"))
    market_share = _format_percent(ctx, row.get("market_share"))
    net_strength = _format_percent(ctx, row.get("net_direction_strength"))
    side = str(row.get("side") or "FLOW").upper()
    outcome = str(row.get("outcome") or "--").strip()
    logical_outcome = str(row.get("logicalOutcome") or row.get("logical_outcome") or "").upper()
    direction = str(row.get("direction") or ("bearish" if logical_outcome == "NO" else "bullish")).lower()
    market_title = row.get("market_title") or "Market flow"
    window_minutes = row.get("window_minutes") or 15
    score = ctx["format_trade_decimal"](row.get("score"))
    max_trade_text = _money_text(ctx, row.get("max_trade_notional"))
    edge = ctx["format_trade_decimal"](row.get("edge_after_fees"))
    post_5m = ctx["format_trade_decimal"](row.get("price_after_5m"))
    post_summary = f"; 5m edge {edge}" if edge is not None else ""
    return {
        "kind": "volume-flow",
        "severity": row.get("severity") or _severity_for_notional(ctx, row.get("flow_notional")),
        "bias": "bearish" if direction == "bearish" else "bullish",
        "sourceLabel": "FLOW+$",
        "sourceTag": "FLOW",
        "headline": f"{window_minutes}m net directional flow",
        "action": {
            "label": "Sell" if side == "SELL" else "Buy",
            "outcome": outcome,
        },
        "title": f"{side} {outcome} flow {_money_text(ctx, row.get('flow_notional'))}: {market_title}",
        "summary": f"net {net_strength}; {row.get('trade_count') or 0} fills; max fill {max_trade_text}; {market_share} of market baseline{post_summary}",
        "timestamp": row.get("timestamp"),
        "marketId": row.get("market_id"),
        "localMarketId": row.get("market_id"),
        "marketTitle": market_title,
        "txHash": row.get("tx_hash"),
        "side": side,
        "outcome": outcome,
        "logicalOutcome": row.get("logicalOutcome") or row.get("logical_outcome"),
        "sourceOutcomeLabel": row.get("sourceOutcomeLabel") or row.get("source_outcome_label"),
        "semanticMode": row.get("semanticMode") or row.get("semantic_mode"),
        "outcomeSemanticsStatus": row.get("outcomeSemanticsStatus") or row.get("outcome_semantics_status"),
        "outcomeSemanticsValid": True,
        "outcomeSemanticsCapabilities": {
            "supportsYesNoWording": bool(row.get("supports_yes_no_wording")),
            "supportsDirectionalSemantics": True,
        },
        "price": ctx["format_trade_decimal"](row.get("avg_price")),
        "notional": flow,
        "contributors": ["clickhouse", "volume", "flow"],
        "relatedContent": [],
        "sourceMode": row.get("source_mode") or "clickhouse-volume-alpha",
        "metrics": {
            "flowNotional": flow,
            "netFlowNotional": net_flow,
            "bullishNotional": ctx["format_trade_decimal"](row.get("bullish_notional")),
            "bearishNotional": ctx["format_trade_decimal"](row.get("bearish_notional")),
            "oppositeFlowNotional": ctx["format_trade_decimal"](row.get("opposite_flow_notional")),
            "netDirectionStrength": ctx["format_trade_decimal"](row.get("net_direction_strength")),
            "churnRatio": ctx["format_trade_decimal"](row.get("churn_ratio")),
            "maxTradeNotional": max_trade,
            "marketBaselineNotional": ctx["format_trade_decimal"](row.get("market_baseline_notional")),
            "marketShare": ctx["format_trade_decimal"](row.get("market_share")),
            "uniqueTraderCount": row.get("unique_trader_count"),
            "priceHealth": ctx["format_trade_decimal"](row.get("price_health")),
            "entryYesPrice": ctx["format_trade_decimal"](row.get("entry_yes_price")),
            "priceAfter1m": ctx["format_trade_decimal"](row.get("price_after_1m")),
            "priceAfter5m": post_5m,
            "priceAfter15m": ctx["format_trade_decimal"](row.get("price_after_15m")),
            "edgeAfterFees": edge,
            "edgeFeeProbability": ctx["format_trade_decimal"](row.get("edge_fee_probability")),
            "tradeCount": row.get("trade_count"),
            "score": score,
            "volumeScore": ctx["format_trade_decimal"](row.get("volume_score")),
            "thresholdFlowNotional": ctx["format_trade_decimal"](row.get("threshold_flow_notional")),
        },
    }


def _query_whale_rows(ctx: dict, *, limit: int) -> List[Dict[str, Any]]:
    rows = clickhouse_orderfilled_service.get_volume_whale_rows(ctx, limit=max(limit * 2, limit))
    if rows is None:
        raise TimeoutError("Recent whale trade source unavailable")
    return rows


def _store_runtime_snapshot(
    ctx: dict, namespace: str, cache_key: str, payload: Dict[str, Any], ttl_seconds: int
) -> Dict[str, Any]:
    ctx["SNAPSHOT_STORE"].set(namespace, cache_key, payload, ttl_seconds)
    return ctx["set_cached_runtime_payload"](namespace, cache_key, payload, ttl_seconds)


def _refresh_runtime_snapshot(
    ctx: dict,
    *,
    namespace: str,
    cache_key: str,
    ttl_seconds: int,
    builder: Callable[[], Dict[str, Any]],
    refresh_state_key: str,
    label: str,
    reason: str,
) -> Optional[Dict[str, Any]]:
    resources = runtime_resources(ctx)
    started_at = time.perf_counter()
    ctx["app"].logger.info("%s refresh-start reason=%s", label, reason)
    try:
        payload = _sanitize_signal_payload(ctx, namespace, builder())
        stored = _store_runtime_snapshot(ctx, namespace, cache_key, payload, ttl_seconds)
        ctx["app"].logger.info(
            "%s refresh-done reason=%s duration_ms=%.2f", label, reason, (time.perf_counter() - started_at) * 1000
        )
        return stored
    except Exception:
        ctx["app"].logger.exception("%s refresh-failed reason=%s", label, reason)
        return None
    finally:
        with resources.signal_lock:
            resources.signal_refreshing[refresh_state_key] = False


def _schedule_runtime_snapshot_refresh(
    ctx: dict,
    *,
    namespace: str,
    cache_key: str,
    ttl_seconds: int,
    builder: Callable[[], Dict[str, Any]],
    refresh_state_key: str,
    label: str,
    reason: str,
) -> None:
    resources = runtime_resources(ctx)
    with resources.signal_lock:
        if resources.signal_refreshing.get(refresh_state_key):
            return
        resources.signal_refreshing[refresh_state_key] = True
    started = resources.start_thread(
        target=lambda: _refresh_runtime_snapshot(
            ctx,
            namespace=namespace,
            cache_key=cache_key,
            ttl_seconds=ttl_seconds,
            builder=builder,
            refresh_state_key=refresh_state_key,
            label=label,
            reason=reason,
        ),
        name=f"{label}-refresh",
    )
    if not started:
        with resources.signal_lock:
            resources.signal_refreshing[refresh_state_key] = False


def _get_stale_first_runtime_snapshot(
    ctx: dict,
    *,
    namespace: str,
    cache_key: str,
    ttl_seconds: int,
    builder: Callable[[], Dict[str, Any]],
    refresh_state_key: str,
    label: str,
) -> Dict[str, Any]:
    resources = runtime_resources(ctx)
    cached = _read_cached_signal_snapshot(
        ctx, namespace=namespace, cache_key=cache_key, ttl_seconds=ttl_seconds,
    )
    if cached is not None:
        if cached.get("status") == "stale":
            _schedule_runtime_snapshot_refresh(
                ctx, namespace=namespace, cache_key=cache_key, ttl_seconds=ttl_seconds,
                builder=builder, refresh_state_key=refresh_state_key, label=label, reason="stale-hit",
            )
        return cached

    with resources.signal_lock:
        if resources.signal_refreshing.get(refresh_state_key):
            payload = {"items": [], "generatedAt": ctx["utc_now_iso"](), "status": "warming"}
            return ctx["set_cached_runtime_payload"](namespace, cache_key, payload, min(5, ttl_seconds))
        resources.signal_refreshing[refresh_state_key] = True
    payload = _refresh_runtime_snapshot(
        ctx,
        namespace=namespace,
        cache_key=cache_key,
        ttl_seconds=ttl_seconds,
        builder=builder,
        refresh_state_key=refresh_state_key,
        label=label,
        reason="cold-miss",
    )
    if payload is not None:
        return _sanitize_signal_payload(ctx, namespace, payload)
    raise RuntimeError(f"{label} snapshot refresh failed")


def _sanitize_signal_payload(ctx: dict, namespace: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(payload)
    items = [dict(item) for item in payload.get("items") or [] if isinstance(item, dict)]
    positions_by_mode: Dict[str, List[int]] = {"raw": [], "aggregate": [], "probe": []}
    currently_verified_positions: set[int] = set()
    aggregate_kinds = {"volume-flow", "market-flow", "momentum", "polybeats"}
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
            currently_verified_positions.add(index)
    if namespace == SIGNAL_SNAPSHOT_NAMESPACE_ALPHA:
        items = [
            item
            for index, item in enumerate(items)
            if index in currently_verified_positions
            and outcome_semantics_service.directional_semantics_allowed(item)
            and item.get("outcomeSemanticsIdentityMode") in {"raw", "aggregate"}
        ]
    sanitized["items"] = items
    if not items and sanitized.get("status") == "ok":
        sanitized["status"] = "empty"
    return sanitized


def _read_cached_signal_snapshot(
    ctx: dict, *, namespace: str, cache_key: str, ttl_seconds: int
) -> Optional[Dict[str, Any]]:
    payload = None
    for name in ("get_cached_runtime_payload", "get_cached_json"):
        reader = ctx.get(name)
        payload = reader(namespace, cache_key) if callable(reader) else None
        if isinstance(payload, dict):
            break
    if not isinstance(payload, dict):
        store = ctx.get("SNAPSHOT_STORE")
        payload = store.get_stale(namespace, cache_key) if store is not None else None
    if not isinstance(payload, dict):
        return None
    payload = _sanitize_signal_payload(ctx, namespace, payload)
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


def _build_whale_trades_payload(ctx: dict, limit: int = 14) -> Dict[str, Any]:
    rows = _query_whale_rows(ctx, limit=max(limit * 2, limit))
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
            "items": items,
            "generatedAt": ctx["utc_now_iso"](),
            "status": status,
            "sourceMode": source_mode,
            "sourceStates": _clickhouse_source_states("ok" if status == "ok" else status, rows=rows),
        },
        generated_at=ctx["utc_now_iso"](),
    )


def fetch_live_whale_trades_payload(ctx: dict, limit: int = 14) -> Dict[str, Any]:
    return normalize_signal_payload(
        _build_whale_trades_payload(ctx, limit=limit),
        generated_at=ctx["utc_now_iso"](),
    )


def get_whale_trades_snapshot(
    ctx: dict, limit: int = DEFAULT_WHALE_TRADES_LIMIT
) -> Dict[str, Any]:
    fetch_limit = max(DEFAULT_WHALE_TRADES_LIMIT, int(limit))
    cache_key = build_whale_trades_cache_key(limit=fetch_limit)
    payload = _get_stale_first_runtime_snapshot(
        ctx, namespace=SIGNAL_SNAPSHOT_NAMESPACE_WHALES, cache_key=cache_key,
        ttl_seconds=ctx["SIGNAL_RUNTIME_TTL_SECONDS"],
        builder=lambda: fetch_live_whale_trades_payload(ctx, limit=fetch_limit),
        refresh_state_key=f"whales:{cache_key}", label="whales-snapshot",
    )
    return _limit_signal_payload(ctx, payload, limit=limit)


def _recent_oracle_candidates(ctx: dict, limit: int) -> List[Dict[str, Any]]:
    try:
        events = ctx["get_recent_oracle_events"](limit=max(limit * 2, 16))
    except Exception:
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.exception("suspicious oracle source failed")
        return []
    filtered = []
    seen: set[tuple[Any, Any]] = set()
    for event in events:
        market_id = event.get("marketId") or event.get("market_id")
        event_time = event.get("eventTime") or event.get("event_time")
        if market_id is None or not event_time:
            continue
        key = (market_id, event_time)
        if key in seen:
            continue
        seen.add(key)
        filtered.append(event)
    return filtered[: max(limit, 8)]


def get_suspicious_trades_snapshot(ctx: dict, limit: int = DEFAULT_SUSPICIOUS_TRADES_LIMIT) -> Dict[str, Any]:
    fetch_limit = max(DEFAULT_SUSPICIOUS_TRADES_LIMIT, int(limit))
    cache_key = build_suspicious_trades_cache_key(limit=fetch_limit)
    payload = _get_stale_first_runtime_snapshot(
        ctx, namespace=SIGNAL_SNAPSHOT_NAMESPACE_SUSPICIOUS, cache_key=cache_key,
        ttl_seconds=ctx["SIGNAL_RUNTIME_TTL_SECONDS"],
        builder=lambda: fetch_live_suspicious_trades_payload(ctx, limit=fetch_limit),
        refresh_state_key=f"suspicious:{cache_key}", label="suspicious-snapshot",
    )
    return _limit_signal_payload(ctx, payload, limit=limit)


def fetch_live_suspicious_trades_payload(ctx: dict, limit: int = 12) -> Dict[str, Any]:
    return normalize_signal_payload(
        {"items": _build_suspicious_trade_items(ctx, limit), "generatedAt": ctx["utc_now_iso"]()},
        generated_at=ctx["utc_now_iso"](),
    )


def _build_suspicious_trade_items(ctx: dict, limit: int = 12) -> List[Dict[str, Any]]:
    oracle_events = _recent_oracle_candidates(ctx, limit)
    recent_trades = ctx["get_recent_trades"](limit=max(200, limit * 30))
    recent_trades = outcome_semantics_service.annotate_raw_trade_rows(ctx, recent_trades)
    items: List[Dict[str, Any]] = []
    seen_hashes: set[str] = set()
    oracle_by_market: Dict[Any, List[Dict[str, Any]]] = {}
    for event in oracle_events:
        market_id = event.get("marketId") or event.get("market_id")
        if market_id is None:
            continue
        oracle_by_market.setdefault(market_id, []).append(event)

    for trade in recent_trades:
        market_id = trade.get("marketId") or trade.get("market_id")
        if market_id is None or market_id not in oracle_by_market:
            continue
        trade_time = ctx["parse_iso_datetime"](trade.get("timestamp"))
        if trade_time is None:
            continue
        for event in oracle_by_market[market_id]:
            event_time = event.get("eventTime") or event.get("event_time")
            event_dt = ctx["parse_iso_datetime"](event_time)
            if event_dt is None:
                continue
            if not (event_dt - timedelta(hours=6) <= trade_time <= event_dt):
                continue
            tx_hash = str(trade.get("txHash") or trade.get("tx_hash") or "")
            if tx_hash and tx_hash in seen_hashes:
                continue
            if tx_hash:
                seen_hashes.add(tx_hash)
            price = ctx["_safe_decimal"](trade.get("price"))
            size = ctx["_safe_decimal"](trade.get("size"))
            notional = ctx["_safe_decimal"](trade.get("notional"))
            if notional is None and price is not None and size is not None:
                notional = price * size
            item = _format_trade_item(
                ctx,
                {
                    "market_id": market_id,
                    "market_title": trade.get("marketTitle")
                    or trade.get("market_title")
                    or event.get("marketTitle")
                    or event.get("market_title"),
                    "timestamp": trade.get("timestamp"),
                    "tx_hash": tx_hash,
                    "outcome": trade.get("outcome"),
                    "logical_outcome": trade.get("logicalOutcome") or trade.get("logical_outcome"),
                    "source_outcome_label": trade.get("sourceOutcomeLabel") or trade.get("source_outcome_label"),
                    "semantic_mode": trade.get("semanticMode") or trade.get("semantic_mode"),
                    "outcome_semantics_status": trade.get("outcomeSemanticsStatus")
                    or trade.get("outcome_semantics_status"),
                    "outcome_semantics_valid": trade.get("outcomeSemanticsValid", trade.get("outcome_semantics_valid")),
                    "supports_directional_semantics": trade.get(
                        "supportsDirectionalSemantics",
                        trade.get("supports_directional_semantics"),
                    ),
                    "side": trade.get("side"),
                    "price": price,
                    "size": size,
                    "notional": notional,
                    "maker": trade.get("maker"),
                    "taker": trade.get("taker"),
                },
            )
            item.update(
                {
                    "eventStatus": event.get("eventStatus") or event.get("event_status"),
                    "eventTime": event_time,
                    "summary": f"{event.get('eventStatus') or event.get('event_status') or 'oracle'} window trade near oracle event",
                }
            )
            items.append(item)
            break
        if len(items) >= limit:
            break

    if items:
        items.sort(key=lambda item: ctx["_safe_decimal"](item.get("notional")) or Decimal("0"), reverse=True)
        return items[:limit]

    fallback_items = []
    for row in _query_whale_rows(ctx, limit=limit)[:limit]:
        fallback_items.append(
            {
                **_format_trade_item(ctx, row),
                "eventStatus": "heuristic",
                "summary": "Large live trade surfaced by fallback heuristic",
            }
        )
    return fallback_items


def _append_signal(
    signals: List[Dict[str, Any]],
    *,
    kind: str,
    severity: str,
    title: Any,
    summary: str,
    timestamp: Any,
    contributors: Iterable[str] | None = None,
) -> None:
    signals.append(
        {
            "kind": kind,
            "severity": severity,
            "title": title,
            "summary": summary,
            "timestamp": timestamp,
            "contributors": list(contributors or []),
        }
    )


def _build_alpha_signal_payload(ctx: dict, limit: int = 8) -> Dict[str, Any]:
    trade_source_status = "ok"
    signals: List[Dict[str, Any]] = []
    volume_rows = None
    if _clickhouse_signal_queries_available(ctx):
        try:
            volume_rows = clickhouse_orderfilled_service.get_alpha_volume_signal_rows(ctx, limit=limit)
        except Exception:
            logger = getattr(ctx.get("app"), "logger", None)
            if logger is not None:
                logger.exception("alpha volume source failed")
            trade_source_status = "degraded"
    if volume_rows is not None:
        signals.extend(
            _format_alpha_volume_signal(ctx, row)
            for row in volume_rows[:limit]
            if outcome_semantics_service.directional_semantics_allowed(row)
        )
    else:
        trade_source_status = "degraded"

    try:
        whale_rows = _query_whale_rows(ctx, limit=6)[:6] if len(signals) < limit else []
    except TimeoutError:
        whale_rows = []
        trade_source_status = "degraded"
    if any(not _is_live_signal_source(str(row.get("source_mode") or "")) for row in whale_rows):
        trade_source_status = "degraded"
    whales = [
        _format_trade_item(ctx, row)
        for row in whale_rows
        if outcome_semantics_service.directional_semantics_allowed(row)
    ]
    for trade in whales[:3]:
        if len(signals) >= limit:
            break
        _append_signal(
            signals,
            kind="whale",
            severity=trade.get("severity") or "elevated",
            title=trade.get("marketTitle") or "Whale flow",
            summary=f"{str(trade.get('side') or 'trade').upper()} {trade.get('outcome') or '--'} at {trade.get('price') or '--'} on-chain, notional {trade.get('notional') or '--'}",
            timestamp=trade.get("timestamp"),
            contributors=["whale", "onchain"],
        )

    deduped: List[Dict[str, Any]] = []
    seen = set()
    for signal in signals:
        key = (signal.get("kind"), signal.get("title"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(signal)
        if len(deduped) >= limit:
            break
    status = "degraded" if trade_source_status != "ok" else "ok" if deduped else "empty"
    source_rows = volume_rows or whale_rows
    source_state_status = "ok" if trade_source_status == "ok" else trade_source_status
    return normalize_signal_payload(
        {
            "items": deduped,
            "generatedAt": ctx["utc_now_iso"](),
            "status": status,
            "sourceMode": trade_source_status,
            "sourceStates": _clickhouse_source_states(source_state_status, rows=source_rows),
        },
        generated_at=ctx["utc_now_iso"](),
    )


def fetch_live_alpha_signal_payload(ctx: dict, limit: int = 8) -> Dict[str, Any]:
    return _sanitize_signal_payload(
        ctx,
        SIGNAL_SNAPSHOT_NAMESPACE_ALPHA,
        normalize_signal_payload(
            _build_alpha_signal_payload(ctx, limit=limit),
            generated_at=ctx["utc_now_iso"](),
        ),
    )


def get_alpha_signal_snapshot(ctx: dict, limit: int = DEFAULT_ALPHA_SIGNAL_LIMIT) -> Dict[str, Any]:
    cache_key = build_alpha_signal_cache_key(limit=limit)
    if int(limit or 0) != DEFAULT_ALPHA_SIGNAL_LIMIT:
        default_payload = _read_cached_signal_snapshot(
            ctx,
            namespace=SIGNAL_SNAPSHOT_NAMESPACE_ALPHA,
            cache_key=build_alpha_signal_cache_key(limit=DEFAULT_ALPHA_SIGNAL_LIMIT),
            ttl_seconds=ctx["SIGNAL_RUNTIME_TTL_SECONDS"],
        )
        if default_payload is not None:
            return _limit_signal_payload(ctx, default_payload, limit=limit)
    return _get_stale_first_runtime_snapshot(
        ctx,
        namespace=SIGNAL_SNAPSHOT_NAMESPACE_ALPHA,
        cache_key=cache_key,
        ttl_seconds=ctx["SIGNAL_RUNTIME_TTL_SECONDS"],
        builder=lambda: fetch_live_alpha_signal_payload(ctx, limit=limit),
        refresh_state_key=f"alpha:{cache_key}",
        label="alpha-snapshot",
    )
