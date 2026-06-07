from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict


_RELATED_CONTENT_CACHE_TTL_SECONDS = 120
_RELATED_CONTENT_SNAPSHOT_TTL_SECONDS = 300
_RELATED_CONTENT_CACHE: Dict[tuple[int, int], tuple[float, Dict[str, Any]]] = {}
_RELATED_CONTENT_CACHE_LOCK = threading.Lock()


def _related_content_version(ctx: dict, market_id: int) -> Dict[str, Any]:
    try:
        if not (ctx.get("table_exists") and ctx["table_exists"]("content_items") and ctx["table_exists"]("content_links")):
            return {"links": 0, "linkCreatedAt": "", "itemUpdatedAt": ""}
        row = ctx["query_one"](
            """
            SELECT
                COUNT(*) AS links,
                MAX(cl.created_at) AS link_created_at,
                MAX(ci.updated_at) AS item_updated_at
            FROM content_links cl
            JOIN content_items ci ON ci.id = cl.content_id
            WHERE cl.market_id = ?
            """,
            (market_id,),
        ) or {}
        return {
            "links": int(row.get("links") or 0),
            "linkCreatedAt": str(row.get("link_created_at") or ""),
            "itemUpdatedAt": str(row.get("item_updated_at") or ""),
        }
    except Exception:
        return {"links": 0, "linkCreatedAt": "", "itemUpdatedAt": ""}


def _get_related_content_payload_uncached(ctx: dict, market_id: int, limit: int = 8) -> Dict[str, Any]:
    return ctx["get_related_content_by_market_id"](market_id, limit=limit)


def _get_related_content_payload_local_cached(ctx: dict, market_id: int, limit: int = 8) -> Dict[str, Any]:
    cache_key = (int(market_id), int(limit))
    now = time.time()
    with _RELATED_CONTENT_CACHE_LOCK:
        cached = _RELATED_CONTENT_CACHE.get(cache_key)
        if cached and now - cached[0] < _RELATED_CONTENT_CACHE_TTL_SECONDS:
            payload = dict(cached[1])
            payload["sourceMode"] = f"{payload.get('sourceMode') or 'database'}:cache"
            return payload
    payload = ctx["get_related_content_by_market_id"](market_id, limit=limit)
    with _RELATED_CONTENT_CACHE_LOCK:
        _RELATED_CONTENT_CACHE[cache_key] = (now, payload)
        if len(_RELATED_CONTENT_CACHE) > 256:
            oldest_key = min(_RELATED_CONTENT_CACHE, key=lambda key: _RELATED_CONTENT_CACHE[key][0])
            _RELATED_CONTENT_CACHE.pop(oldest_key, None)
    return payload


def get_related_content_payload(ctx: dict, market_id: int, limit: int = 8) -> Dict[str, Any]:
    snapshot_getter = ctx.get("get_snapshot_payload")
    if callable(snapshot_getter):
        cache_key = json.dumps(
            {
                "marketId": int(market_id),
                "limit": int(limit),
                "version": _related_content_version(ctx, int(market_id)),
                "v": 1,
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        return snapshot_getter(
            "snapshot:content:related",
            cache_key,
            lambda: _get_related_content_payload_uncached(ctx, market_id, limit=limit),
            ttl_seconds=_RELATED_CONTENT_SNAPSHOT_TTL_SECONDS,
        )
    return _get_related_content_payload_local_cached(ctx, market_id, limit=limit)


def get_latest_content_payload(ctx: dict, limit: int = 8) -> Dict[str, Any]:
    return ctx["get_latest_content_snapshot"](limit=limit)
