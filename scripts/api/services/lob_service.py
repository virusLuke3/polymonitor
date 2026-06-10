from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

try:
    from requests import RequestException
except Exception:  # pragma: no cover - requests is an API dependency in normal runtime.
    RequestException = Exception

from quant.core.db import PostgresSettings, postgres_connection
from quant.core.schema import create_schema


_SNAPSHOT_SCHEMA_READY = False
_SNAPSHOT_SCHEMA_LOCK = threading.Lock()
BOOK_LEVEL_LIMIT = 12


def _empty_book_side() -> Dict[str, Any]:
    return {"bids": [], "asks": [], "bestBid": None, "bestAsk": None, "spread": None}


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return parsed if parsed.is_finite() else None


def _float_or_none(value: Any) -> float | None:
    parsed = _decimal_or_none(value)
    return float(parsed) if parsed is not None else None


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_levels(rows: Any, *, reverse: bool = False) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        price = _decimal_or_none(row.get("price"))
        size = _decimal_or_none(row.get("size"))
        if price is None or size is None or price <= 0 or size <= 0:
            continue
        parsed.append({"price": str(price), "size": str(size)})
    parsed.sort(key=lambda item: Decimal(str(item["price"])), reverse=reverse)
    return parsed[:BOOK_LEVEL_LIMIT]


def _sum_notional(levels: list[dict[str, Any]], limit: int = BOOK_LEVEL_LIMIT) -> Decimal:
    total = Decimal("0")
    for level in levels[:limit]:
        price = _decimal_or_none(level.get("price"))
        size = _decimal_or_none(level.get("size"))
        if price is None or size is None:
            continue
        total += price * size
    return total


def _book_side_summary(side: Dict[str, Any]) -> Dict[str, Any]:
    bids = _normalize_levels(side.get("bids"), reverse=True)
    asks = _normalize_levels(side.get("asks"), reverse=False)
    best_bid = _decimal_or_none(side.get("bestBid")) or (_decimal_or_none(bids[0].get("price")) if bids else None)
    best_ask = _decimal_or_none(side.get("bestAsk")) or (_decimal_or_none(asks[0].get("price")) if asks else None)
    spread = None
    mid = None
    if best_bid is not None and best_ask is not None:
        spread = best_ask - best_bid
        mid = (best_bid + best_ask) / Decimal("2")
    bid_depth = _sum_notional(bids)
    ask_depth = _sum_notional(asks)
    depth_total = bid_depth + ask_depth
    imbalance = (bid_depth / depth_total) if depth_total > 0 else None
    return {
        "bids": bids,
        "asks": asks,
        "bestBid": str(best_bid) if best_bid is not None else None,
        "bestAsk": str(best_ask) if best_ask is not None else None,
        "spread": str(spread) if spread is not None else None,
        "mid": str(mid) if mid is not None else None,
        "bidDepth": str(bid_depth),
        "askDepth": str(ask_depth),
        "depthTotal": str(depth_total),
        "imbalance": str(imbalance) if imbalance is not None else None,
        "levelCountBid": len(bids),
        "levelCountAsk": len(asks),
    }


def _book_side_has_levels(side: Dict[str, Any]) -> bool:
    if not isinstance(side, dict):
        return False
    return bool(side.get("bids") or side.get("asks"))


def _lob_payload_has_levels(payload: Dict[str, Any]) -> bool:
    if not isinstance(payload, dict):
        return False
    return _book_side_has_levels(payload.get("yes") or {}) or _book_side_has_levels(payload.get("no") or {})


def _book_side_from_clob(ctx: dict, token_id: str) -> Dict[str, Any]:
    if not token_id:
        return _empty_book_side()
    session = ctx["get_clob_session"]()
    response = session.get(
        f"{ctx['CLOB_API_BASE'].rstrip('/')}/book",
        params={"token_id": token_id},
        timeout=min(float(ctx.get("CLOB_TIMEOUT_SECONDS") or 3), 3.0),
    )
    if response.status_code == 404:
        return _empty_book_side()
    response.raise_for_status()
    data = response.json() or {}

    bids = _normalize_levels(data.get("bids"), reverse=True)
    asks = _normalize_levels(data.get("asks"), reverse=False)
    best_bid = bids[0].get("price") if bids else None
    best_ask = asks[0].get("price") if asks else None
    return _book_side_summary({"bids": bids, "asks": asks, "bestBid": best_bid, "bestAsk": best_ask})


def _ensure_snapshot_schema() -> None:
    global _SNAPSHOT_SCHEMA_READY
    if _SNAPSHOT_SCHEMA_READY:
        return
    with _SNAPSHOT_SCHEMA_LOCK:
        if _SNAPSHOT_SCHEMA_READY:
            return
        with postgres_connection(PostgresSettings()) as conn:
            create_schema(conn)
        _SNAPSHOT_SCHEMA_READY = True


def _persist_book_side_snapshot(
    ctx: dict,
    *,
    token_id: str,
    side_name: str,
    paired_token_id: str,
    market_title: str,
    source: str,
    book_status: str,
    fetched_at: str,
    side_payload: Dict[str, Any],
) -> None:
    if not token_id:
        return
    summary = _book_side_summary(side_payload)
    payload = {
        **summary,
        "tokenId": token_id,
        "pairedTokenId": paired_token_id,
        "side": side_name,
        "marketTitle": market_title,
        "source": source,
        "bookStatus": book_status,
        "fetchedAt": fetched_at,
    }
    _ensure_snapshot_schema()
    with postgres_connection(PostgresSettings()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO quant.clob_orderbook_snapshots (
                    token_id, side, paired_token_id, market_title, source, book_status,
                    best_bid, best_ask, spread, mid,
                    bid_depth, ask_depth, depth_total, imbalance,
                    level_count_bid, level_count_ask, payload, fetched_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s::jsonb, %s
                )
                """,
                (
                    token_id,
                    side_name,
                    paired_token_id or None,
                    market_title or None,
                    source or "clob-book",
                    book_status or "unknown",
                    summary["bestBid"],
                    summary["bestAsk"],
                    summary["spread"],
                    summary["mid"],
                    summary["bidDepth"],
                    summary["askDepth"],
                    summary["depthTotal"],
                    summary["imbalance"],
                    summary["levelCountBid"],
                    summary["levelCountAsk"],
                    json.dumps(payload),
                    fetched_at,
                ),
            )


def _persist_orderbook_snapshots(ctx: dict, payload: Dict[str, Any], yes_token_id: str, no_token_id: str) -> None:
    try:
        fetched_at = str(payload.get("fetchedAt") or _iso_utc_now())
        source = str(payload.get("source") or "clob-book")
        book_status = str(payload.get("bookStatus") or ("ok" if _lob_payload_has_levels(payload) else "no-book"))
        market_title = str(payload.get("marketTitle") or "")
        _persist_book_side_snapshot(
            ctx,
            token_id=yes_token_id,
            side_name="YES",
            paired_token_id=no_token_id,
            market_title=market_title,
            source=source,
            book_status=book_status,
            fetched_at=fetched_at,
            side_payload=payload.get("yes") or _empty_book_side(),
        )
        if no_token_id:
            _persist_book_side_snapshot(
                ctx,
                token_id=no_token_id,
                side_name="NO",
                paired_token_id=yes_token_id,
                market_title=market_title,
                source=source,
                book_status=book_status,
                fetched_at=fetched_at,
                side_payload=payload.get("no") or _empty_book_side(),
            )
    except Exception as exc:
        logger = ctx.get("app").logger if ctx.get("app") else None
        if logger:
            logger.warning("clob snapshot persistence failed token_id=%s: %s", yes_token_id, exc)


def get_lob_snapshots_by_token_payload(ctx: dict, token_id: str, *, side: str = "", limit: int = 48) -> Dict[str, Any]:
    token_id = str(token_id or "").strip()
    side = str(side or "").strip().upper()
    if not token_id:
        return {"error": "Missing token id", "items": [], "count": 0, "_status": 400}
    limit = max(1, min(int(limit or 48), 200))
    try:
        _ensure_snapshot_schema()
        params: list[Any] = [token_id]
        where = "token_id = %s"
        if side in {"YES", "NO"}:
            where += " AND side = %s"
            params.append(side)
        params.append(limit)
        with postgres_connection(PostgresSettings(), readonly=True) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        snapshot_id, token_id, side, paired_token_id, market_title, source, book_status,
                        best_bid, best_ask, spread, mid, bid_depth, ask_depth, depth_total, imbalance,
                        level_count_bid, level_count_ask, payload, fetched_at, created_at
                    FROM quant.clob_orderbook_snapshots
                    WHERE {where}
                    ORDER BY fetched_at DESC, snapshot_id DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                rows = cur.fetchall()
        items = []
        for row in rows:
            items.append({
                "snapshotId": row["snapshot_id"],
                "tokenId": row["token_id"],
                "side": row["side"],
                "pairedTokenId": row["paired_token_id"],
                "marketTitle": row["market_title"],
                "source": row["source"],
                "bookStatus": row["book_status"],
                "bestBid": _float_or_none(row["best_bid"]),
                "bestAsk": _float_or_none(row["best_ask"]),
                "spread": _float_or_none(row["spread"]),
                "mid": _float_or_none(row["mid"]),
                "bidDepth": _float_or_none(row["bid_depth"]),
                "askDepth": _float_or_none(row["ask_depth"]),
                "depthTotal": _float_or_none(row["depth_total"]),
                "imbalance": _float_or_none(row["imbalance"]),
                "levelCountBid": int(row["level_count_bid"] or 0),
                "levelCountAsk": int(row["level_count_ask"] or 0),
                "payload": row["payload"] if isinstance(row["payload"], dict) else {},
                "fetchedAt": row["fetched_at"].isoformat().replace("+00:00", "Z") if row["fetched_at"] else None,
                "createdAt": row["created_at"].isoformat().replace("+00:00", "Z") if row["created_at"] else None,
            })
        return {"tokenId": token_id, "side": side or None, "items": items, "count": len(items)}
    except Exception as exc:
        ctx["app"].logger.exception("lob snapshot history failed token_id=%s", token_id)
        return {"error": "LOB snapshot history unavailable", "detail": str(exc), "items": [], "count": 0, "_status": 502}


def _clob_book_fallback(ctx: dict, market: Dict[str, Any], yes_token_id: str, no_token_id: str) -> Dict[str, Any]:
    payload = {
        "marketId": market.get("id"),
        "localMarketId": market.get("id"),
        "marketTitle": str(market.get("title") or ""),
        "fetchedAt": _iso_utc_now(),
        "source": "clob-book",
        "yes": _book_side_from_clob(ctx, yes_token_id),
        "no": _book_side_from_clob(ctx, no_token_id),
    }
    payload["bookStatus"] = "ok" if _lob_payload_has_levels(payload) else "no-book"
    _persist_orderbook_snapshots(ctx, payload, yes_token_id, no_token_id)
    return payload


def _unavailable_lob_payload(market: Dict[str, Any], detail: str = "") -> Dict[str, Any]:
    return {
        "marketId": market.get("id"),
        "localMarketId": market.get("id"),
        "marketTitle": str(market.get("title") or ""),
        "fetchedAt": _iso_utc_now(),
        "source": "clob-book",
        "bookStatus": "unavailable",
        "detail": detail[:220],
        "yes": _empty_book_side(),
        "no": _empty_book_side(),
    }


def get_runtime_lob_by_token_payload(
    ctx: dict,
    token_id: str,
    *,
    no_token_id: str = "",
    market_title: str = "",
) -> Dict[str, Any]:
    yes_token_id = str(token_id or "").strip()
    no_token_id = str(no_token_id or "").strip()
    if not yes_token_id:
        return {"error": "Missing token id", "marketId": 0, "localMarketId": None, "_status": 400}
    try:
        payload = {
            "marketId": 0,
            "localMarketId": None,
            "marketTitle": str(market_title or ""),
            "fetchedAt": _iso_utc_now(),
            "tokenMode": True,
            "source": "clob-book",
            "yes": _book_side_from_clob(ctx, yes_token_id),
            "no": _book_side_from_clob(ctx, no_token_id) if no_token_id else _empty_book_side(),
        }
        payload["bookStatus"] = "ok" if _lob_payload_has_levels(payload) else "no-book"
        _persist_orderbook_snapshots(ctx, payload, yes_token_id, no_token_id)
        return payload
    except Exception as exc:
        ctx["app"].logger.exception("lob-runtime token fallback failed token_id=%s", yes_token_id)
        return {
            "error": "LOB token snapshot unavailable",
            "marketId": 0,
            "localMarketId": None,
            "detail": str(exc),
            "_status": 502,
        }


def get_runtime_lob_payload(ctx: dict, market_id: int) -> Dict[str, Any]:
    market = ctx["get_market_by_id"](market_id)
    if not market:
        return {"error": "Market not found", "marketId": market_id, "localMarketId": market_id, "_status": 404}
    yes_token_id = str(market.get("yes_token_id") or "").strip()
    no_token_id = str(market.get("no_token_id") or "").strip()
    if not yes_token_id or not no_token_id:
        return {"error": "Market is missing token ids", "marketId": market_id, "localMarketId": market_id, "_status": 409}
    try:
        runtime_payload = ctx["LOB_RUNTIME_MANAGER"].get_market_snapshot(
            market_id=market_id,
            yes_token_id=yes_token_id,
            no_token_id=no_token_id,
            market_title=str(market.get("title") or ""),
        )
        if isinstance(runtime_payload, dict):
            runtime_payload.setdefault("localMarketId", market_id)
            runtime_payload.setdefault("source", "runtime-lob")
            runtime_payload.setdefault("bookStatus", "ok" if _lob_payload_has_levels(runtime_payload) else "no-book")
        if _lob_payload_has_levels(runtime_payload):
            _persist_orderbook_snapshots(ctx, runtime_payload, yes_token_id, no_token_id)
            return runtime_payload
        fallback_payload = _clob_book_fallback(ctx, market, yes_token_id, no_token_id)
        if _lob_payload_has_levels(fallback_payload):
            fallback_payload["fallbackReason"] = "runtime-empty"
            return fallback_payload
        return runtime_payload if isinstance(runtime_payload, dict) else fallback_payload
    except Exception as exc:
        ctx["app"].logger.warning("lob-runtime failed market_id=%s; falling back to CLOB /book: %s", market_id, exc)
        if isinstance(exc, RequestException):
            return _unavailable_lob_payload(market, str(exc))
        try:
            return _clob_book_fallback(ctx, market, yes_token_id, no_token_id)
        except Exception as fallback_exc:
            ctx["app"].logger.exception("lob-runtime fallback failed market_id=%s", market_id)
            return {
                "error": "LOB runtime unavailable",
                "marketId": market_id,
                "localMarketId": market_id,
                "detail": str(fallback_exc),
                "_status": 502,
            }
