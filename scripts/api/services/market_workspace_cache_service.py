from __future__ import annotations

import copy
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from api import cache as api_cache
from api.services import lob_service, market_service


DETAIL_TTL_SECONDS = int(os.environ.get("POLYDATA_MARKET_WORKSPACE_DETAIL_TTL_SECONDS", "120"))
CHART_TTL_SECONDS = int(os.environ.get("POLYDATA_MARKET_WORKSPACE_CHART_TTL_SECONDS", "90"))
ORDERBOOK_TTL_SECONDS = int(os.environ.get("POLYDATA_MARKET_WORKSPACE_ORDERBOOK_TTL_SECONDS", "5"))
FLOW_TTL_SECONDS = int(os.environ.get("POLYDATA_MARKET_WORKSPACE_FLOW_TTL_SECONDS", "8"))

_REFRESH_LOCK = threading.Lock()
_REFRESHING: set[str] = set()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _cache_key(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def _namespace(layer: str) -> str:
    return f"snapshot:market-workspace:{layer}"


def _copy_payload(payload: Any) -> Any:
    try:
        return copy.deepcopy(payload)
    except Exception:
        return json.loads(json.dumps(payload, default=str))


def _layer_meta(layer: str, mode: str, cache_key: str) -> Dict[str, Any]:
    return {
        "layer": layer,
        "mode": mode,
        "cacheKey": cache_key,
        "generatedAt": _utc_now_iso(),
    }


def _with_cache_meta(payload: Any, layer: str, mode: str, cache_key: str) -> Any:
    copied = _copy_payload(payload)
    if isinstance(copied, dict):
        copied["cacheMode"] = mode
        copied["marketWorkspaceCache"] = _layer_meta(layer, mode, cache_key)
    return copied


def _book_side_has_levels(side: Any) -> bool:
    return isinstance(side, dict) and bool(side.get("bids") or side.get("asks"))


def _lob_has_levels(payload: Any) -> bool:
    return isinstance(payload, dict) and (_book_side_has_levels(payload.get("yes")) or _book_side_has_levels(payload.get("no")))


def _chart_has_points(payload: Any) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get("points"), list) and bool(payload.get("points"))


def _flow_has_rows(payload: Any) -> bool:
    if isinstance(payload, dict):
        rows = payload.get("items")
    else:
        rows = payload
    return isinstance(rows, list) and bool(rows)


def _detail_is_usable(payload: Any) -> bool:
    return isinstance(payload, dict) and not payload.get("_status") and isinstance(payload.get("market"), dict)


def _is_empty_replacement(layer: str, payload: Any) -> bool:
    if layer == "detail":
        return not _detail_is_usable(payload)
    if layer == "chart":
        return not _chart_has_points(payload)
    if layer == "orderbook":
        return not _lob_has_levels(payload)
    if layer == "flow":
        return not _flow_has_rows(payload)
    return payload in (None, {}, [])


def _read_redis(ctx: dict, namespace: str, cache_key: str) -> Optional[Any]:
    try:
        return api_cache.get_cached_payload(ctx, namespace, cache_key)
    except Exception:
        ctx["app"].logger.exception("market-workspace-cache redis-read failed namespace=%s key=%s", namespace, cache_key)
        return None


def _write_cache(ctx: dict, namespace: str, cache_key: str, payload: Any, ttl_seconds: int) -> None:
    try:
        api_cache.set_cached_runtime_payload(ctx, namespace, cache_key, payload, ttl_seconds)
    except Exception:
        ctx["app"].logger.exception("market-workspace-cache memory-write failed namespace=%s key=%s", namespace, cache_key)
    try:
        api_cache.set_cached_payload(ctx, namespace, cache_key, payload, ttl_seconds)
    except Exception:
        ctx["app"].logger.exception("market-workspace-cache redis-write failed namespace=%s key=%s", namespace, cache_key)
    try:
        ctx["SNAPSHOT_STORE"].set(namespace, cache_key, payload, ttl_seconds)
    except Exception:
        ctx["app"].logger.exception("market-workspace-cache sqlite-write failed namespace=%s key=%s", namespace, cache_key)


def _refresh_async(
    ctx: dict,
    *,
    layer: str,
    namespace: str,
    cache_key: str,
    builder: Callable[[], Any],
    ttl_seconds: int,
    stale_payload: Any,
) -> None:
    refresh_key = f"{namespace}:{cache_key}"
    with _REFRESH_LOCK:
        if refresh_key in _REFRESHING:
            return
        _REFRESHING.add(refresh_key)

    def refresh() -> None:
        try:
            payload = builder()
            if _is_empty_replacement(layer, payload) and not _is_empty_replacement(layer, stale_payload):
                ctx["app"].logger.warning(
                    "market-workspace-cache refresh skipped empty layer=%s key=%s",
                    layer,
                    cache_key,
                )
                return
            _write_cache(ctx, namespace, cache_key, _with_cache_meta(payload, layer, "refresh", cache_key), ttl_seconds)
        except Exception:
            ctx["app"].logger.exception("market-workspace-cache refresh failed layer=%s key=%s", layer, cache_key)
        finally:
            with _REFRESH_LOCK:
                _REFRESHING.discard(refresh_key)

    thread = threading.Thread(target=refresh, name=f"market-workspace-cache:{layer}", daemon=True)
    thread.start()


def _cached_layer(
    ctx: dict,
    *,
    layer: str,
    cache_key: str,
    ttl_seconds: int,
    builder: Callable[[], Any],
    allow_stale_refresh: bool = True,
) -> Dict[str, Any]:
    namespace = _namespace(layer)

    runtime_payload = api_cache.get_cached_runtime_payload(ctx, namespace, cache_key)
    if runtime_payload is not None:
        return {"payload": _with_cache_meta(runtime_payload, layer, "memory-hit", cache_key), "mode": "memory-hit"}

    redis_payload = _read_redis(ctx, namespace, cache_key)
    if redis_payload is not None:
        api_cache.set_cached_runtime_payload(ctx, namespace, cache_key, redis_payload, min(ttl_seconds, 30))
        return {"payload": _with_cache_meta(redis_payload, layer, "redis-hit", cache_key), "mode": "redis-hit"}

    sqlite_payload = ctx["SNAPSHOT_STORE"].get(namespace, cache_key)
    if sqlite_payload is not None:
        _write_cache(ctx, namespace, cache_key, sqlite_payload, ttl_seconds)
        return {"payload": _with_cache_meta(sqlite_payload, layer, "sqlite-hit", cache_key), "mode": "sqlite-hit"}

    stale_payload = ctx["SNAPSHOT_STORE"].get_stale(namespace, cache_key)
    if stale_payload is not None:
        ctx["app"].logger.info("market-workspace-cache stale-hit layer=%s key=%s", layer, cache_key)
        api_cache.set_cached_payload(ctx, namespace, cache_key, stale_payload, min(15, ttl_seconds))
        if allow_stale_refresh:
            _refresh_async(
                ctx,
                layer=layer,
                namespace=namespace,
                cache_key=cache_key,
                builder=builder,
                ttl_seconds=ttl_seconds,
                stale_payload=stale_payload,
            )
        return {"payload": _with_cache_meta(stale_payload, layer, "stale-hit", cache_key), "mode": "stale-hit"}

    try:
        payload = builder()
    except Exception:
        ctx["app"].logger.exception("market-workspace-cache live-build failed layer=%s key=%s", layer, cache_key)
        payload = _fallback_payload(layer, cache_key)
        return {"payload": _with_cache_meta(payload, layer, "live-error", cache_key), "mode": "live-error"}

    mode = "live-build"
    wrapped = _with_cache_meta(payload, layer, mode, cache_key)
    ttl = ttl_seconds if not _is_empty_replacement(layer, payload) else min(ttl_seconds, 10)
    _write_cache(ctx, namespace, cache_key, wrapped, ttl)
    return {"payload": _copy_payload(wrapped), "mode": mode}


def _fallback_payload(layer: str, cache_key: str) -> Any:
    if layer == "flow":
        return {"items": [], "status": "warming"}
    if layer == "chart":
        return {"points": [], "historyStatus": "warming"}
    if layer == "orderbook":
        return {
            "bookStatus": "warming",
            "source": "market-workspace-cache",
            "yes": {"bids": [], "asks": [], "bestBid": None, "bestAsk": None, "spread": None},
            "no": {"bids": [], "asks": [], "bestBid": None, "bestAsk": None, "spread": None},
        }
    return {"status": "warming", "cacheKey": cache_key}


def _build_detail(ctx: dict, market_id: int) -> Dict[str, Any]:
    payload = market_service.get_market_workspace_payload(ctx, market_id)
    if not isinstance(payload, dict):
        return {"error": "Invalid market workspace payload", "marketId": market_id, "_status": 502}
    detail = dict(payload)
    detail.pop("chart", None)
    detail.pop("trades", None)
    detail.pop("lob", None)
    detail["generatedAt"] = ctx["utc_now_iso"]()
    return detail


def get_market_detail_payload(ctx: dict, market_id: int) -> Dict[str, Any]:
    key = _cache_key({"marketId": int(market_id), "layer": "detail", "v": 1})
    result = _cached_layer(
        ctx,
        layer="detail",
        cache_key=key,
        ttl_seconds=DETAIL_TTL_SECONDS,
        builder=lambda: _build_detail(ctx, market_id),
    )
    payload = result["payload"]
    return payload if isinstance(payload, dict) else {"error": "Invalid detail cache payload", "marketId": market_id, "_status": 502}


def get_market_chart_payload(ctx: dict, market_id: int, *, range_name: str = "1d", interval: str = "5m") -> Dict[str, Any]:
    normalized_range = str(range_name or "1d").strip().lower()
    normalized_interval = str(interval or "5m").strip().lower()
    key = _cache_key(
        {
            "marketId": int(market_id),
            "layer": "chart",
            "range": normalized_range,
            "interval": normalized_interval,
            "v": 2,
        }
    )
    result = _cached_layer(
        ctx,
        layer="chart",
        cache_key=key,
        ttl_seconds=CHART_TTL_SECONDS,
        builder=lambda: market_service.get_market_chart_payload(
            ctx,
            market_id,
            range_name=normalized_range,
            interval=normalized_interval,
        ),
    )
    payload = result["payload"]
    if isinstance(payload, dict):
        payload.setdefault("marketId", market_id)
        payload.setdefault("localMarketId", market_id)
        payload.setdefault("range", normalized_range)
        payload.setdefault("interval", normalized_interval)
        return payload
    return {"marketId": market_id, "localMarketId": market_id, "range": normalized_range, "interval": normalized_interval, "points": []}


def get_market_flow_payload(ctx: dict, market_id: int, *, limit: int = 24, offset: int = 0) -> Dict[str, Any]:
    safe_limit = min(max(int(limit), 1), 500)
    safe_offset = max(int(offset), 0)
    key = _cache_key(
        {
            "marketId": int(market_id),
            "layer": "flow",
            "limit": safe_limit,
            "offset": safe_offset,
            "v": 1,
        }
    )

    def build() -> Dict[str, Any]:
        return {
            "marketId": market_id,
            "localMarketId": market_id,
            "items": market_service.get_trades_by_market_id(ctx, market_id, limit=safe_limit, offset=safe_offset),
            "generatedAt": ctx["utc_now_iso"](),
        }

    result = _cached_layer(ctx, layer="flow", cache_key=key, ttl_seconds=FLOW_TTL_SECONDS, builder=build)
    payload = result["payload"]
    if isinstance(payload, dict):
        payload.setdefault("marketId", market_id)
        payload.setdefault("localMarketId", market_id)
        payload.setdefault("items", [])
        return payload
    return {"marketId": market_id, "localMarketId": market_id, "items": []}


def get_market_flow_rows(ctx: dict, market_id: int, *, limit: int = 24, offset: int = 0) -> list[Dict[str, Any]]:
    payload = get_market_flow_payload(ctx, market_id, limit=limit, offset=offset)
    rows = payload.get("items") if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def get_market_orderbook_payload(ctx: dict, market_id: int) -> Dict[str, Any]:
    key = _cache_key({"marketId": int(market_id), "layer": "orderbook", "v": 1})
    result = _cached_layer(
        ctx,
        layer="orderbook",
        cache_key=key,
        ttl_seconds=ORDERBOOK_TTL_SECONDS,
        builder=lambda: lob_service.get_runtime_lob_payload(ctx, market_id),
    )
    payload = result["payload"]
    if isinstance(payload, dict):
        payload.setdefault("marketId", market_id)
        payload.setdefault("localMarketId", market_id)
        return payload
    fallback = _fallback_payload("orderbook", key)
    fallback["marketId"] = market_id
    fallback["localMarketId"] = market_id
    return fallback


def get_market_workspace_payload(ctx: dict, market_id: int) -> Dict[str, Any]:
    detail_result = get_market_detail_payload(ctx, market_id)
    if detail_result.get("_status") == 404:
        return detail_result

    with ThreadPoolExecutor(max_workers=3) as executor:
        chart_future = executor.submit(get_market_chart_payload, ctx, market_id, range_name="1d", interval="5m")
        flow_future = executor.submit(get_market_flow_payload, ctx, market_id, limit=24, offset=0)
        orderbook_future = executor.submit(get_market_orderbook_payload, ctx, market_id)
        chart = chart_future.result()
        flow = flow_future.result()
        orderbook = orderbook_future.result()

    payload = dict(detail_result)
    payload["chart"] = chart
    payload["trades"] = flow.get("items") if isinstance(flow, dict) else []
    payload["lob"] = orderbook
    payload["cacheLayers"] = {
        "detail": (detail_result.get("marketWorkspaceCache") or {}),
        "chart": (chart.get("marketWorkspaceCache") or {}),
        "flow": (flow.get("marketWorkspaceCache") or {}),
        "orderbook": (orderbook.get("marketWorkspaceCache") or {}),
    }
    payload["marketWorkspaceCache"] = {
        "mode": "layered",
        "layers": payload["cacheLayers"],
        "generatedAt": _utc_now_iso(),
    }
    payload["generatedAt"] = _utc_now_iso()
    return payload
