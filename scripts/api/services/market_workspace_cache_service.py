from __future__ import annotations

import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from api import cache as api_cache
from api.context import RuntimeResources
from api.services.market_service import assemble_market_workspace


@dataclass(frozen=True)
class MarketWorkspaceCacheDependencies:
    resources: RuntimeResources
    cache: api_cache.CacheState
    build_detail: Callable[..., Any]
    build_chart: Callable[..., Any]
    build_flow: Callable[..., Any]
    build_lob: Callable[..., Any]
    get_market_by_id: Callable[[int], dict | None]
    application: Any
    snapshot_store: Any
    utc_now_iso: Callable[..., str]
    detail_ttl: int = 120
    chart_ttl: int = 90
    orderbook_ttl: int = 60
    flow_ttl: int = 8



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
        previous = copied.get("marketWorkspaceCache") or {}
        copied["cacheMode"] = mode
        copied["marketWorkspaceCache"] = _layer_meta(layer, mode, cache_key)
        if mode not in {"live-build", "refresh", "closed"}:
            copied["marketWorkspaceCache"]["generatedAt"] = previous.get("generatedAt") or copied.get("generatedAt")
        if mode == "stale-hit" and layer == "flow":
            copied["status"] = "stale"
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


def _read_redis(
    context: MarketWorkspaceCacheDependencies,
    namespace: str,
    cache_key: str,
) -> Optional[Any]:
    dependencies = context
    try:
        return api_cache.get_cached_payload(
            dependencies.cache,
            namespace,
            cache_key,
        )
    except Exception:
        dependencies.application.logger.exception(
            "market-workspace-cache redis-read failed namespace=%s key=%s",
            namespace,
            cache_key,
        )
        return None


def _write_cache(
    context: MarketWorkspaceCacheDependencies,
    namespace: str,
    cache_key: str,
    payload: Any,
    ttl_seconds: int,
) -> None:
    dependencies = context
    try:
        api_cache.set_cached_runtime_payload(
            dependencies.cache,
            namespace,
            cache_key,
            payload,
            ttl_seconds,
        )
    except Exception:
        dependencies.application.logger.exception(
            "market-workspace-cache memory-write failed namespace=%s key=%s",
            namespace,
            cache_key,
        )
    try:
        api_cache.set_cached_payload(
            dependencies.cache,
            namespace,
            cache_key,
            payload,
            ttl_seconds,
        )
    except Exception:
        dependencies.application.logger.exception(
            "market-workspace-cache redis-write failed namespace=%s key=%s",
            namespace,
            cache_key,
        )
    try:
        dependencies.snapshot_store.set(
            namespace,
            cache_key,
            payload,
            ttl_seconds,
        )
    except Exception:
        dependencies.application.logger.exception(
            "market-workspace-cache sqlite-write failed namespace=%s key=%s",
            namespace,
            cache_key,
        )


def _claim_build(dependencies: MarketWorkspaceCacheDependencies, key: str):
    """Bound running builds; Redis excludes duplicate work across API workers."""
    resources = dependencies.resources
    with resources.workspace_lock:
        if resources.stopped.is_set() or key in resources.workspace_refreshing or not resources.workspace_slots.acquire(blocking=False):
            return False, None
        resources.workspace_refreshing.add(key)
    lease = None
    try:
        client = api_cache.get_redis_client(dependencies.cache)
        if client is not None:
            lease = client.lock(f"{dependencies.cache.redis_prefix}build:{key}", timeout=180, thread_local=False)
            if not lease.acquire(blocking=False):
                _release_build(dependencies, key, None)
                return False, None
        return True, lease
    except Exception:
        _release_build(dependencies, key, None)
        dependencies.application.logger.warning("market cache build lease unavailable", exc_info=True)
        return False, None


def _release_build(dependencies: MarketWorkspaceCacheDependencies, key: str, lease) -> None:
    try:
        if lease is not None:
            lease.release()
    except Exception:
        dependencies.application.logger.warning("market cache build lease expired", exc_info=True)
    finally:
        with dependencies.resources.workspace_lock:
            dependencies.resources.workspace_refreshing.discard(key)
        dependencies.resources.workspace_slots.release()


def _refresh_async(
    context: MarketWorkspaceCacheDependencies,
    *,
    layer: str,
    namespace: str,
    cache_key: str,
    builder: Callable[[], Any],
    ttl_seconds: int,
    stale_payload: Any,
) -> None:
    dependencies = context
    refresh_key = f"{namespace}:{cache_key}"
    claimed, lease = _claim_build(dependencies, refresh_key)
    if not claimed:
        return

    def refresh() -> None:
        try:
            payload = builder()
            if layer != "flow" and _is_empty_replacement(layer, payload) and not _is_empty_replacement(layer, stale_payload):
                dependencies.application.logger.warning(
                    "market-workspace-cache refresh skipped empty layer=%s key=%s",
                    layer,
                    cache_key,
                )
                return
            _write_cache(
                dependencies,
                namespace,
                cache_key,
                _with_cache_meta(payload, layer, "refresh", cache_key),
                ttl_seconds,
            )
        except Exception:
            dependencies.application.logger.exception(
                "market-workspace-cache refresh failed layer=%s key=%s",
                layer,
                cache_key,
            )
        finally:
            _release_build(dependencies, refresh_key, lease)

    try:
        started = dependencies.resources.start_thread(refresh, name="market-cache-refresh")
    except RuntimeError:
        started = False
    if not started:
        _release_build(dependencies, refresh_key, lease)


def _cached_layer(
    context: MarketWorkspaceCacheDependencies,
    *,
    layer: str,
    cache_key: str,
    ttl_seconds: int,
    builder: Callable[[], Any],
    background_only: bool = False,
) -> Dict[str, Any]:
    dependencies = context
    namespace = _namespace(layer)

    runtime_payload = api_cache.get_cached_runtime_payload(
        dependencies.cache,
        namespace,
        cache_key,
    )
    if runtime_payload is not None:
        return {"payload": _with_cache_meta(runtime_payload, layer, "memory-hit", cache_key), "mode": "memory-hit"}

    redis_payload = _read_redis(dependencies, namespace, cache_key)
    if redis_payload is not None:
        api_cache.set_cached_runtime_payload(
            dependencies.cache,
            namespace,
            cache_key,
            redis_payload,
            min(ttl_seconds, 30),
        )
        return {"payload": _with_cache_meta(redis_payload, layer, "redis-hit", cache_key), "mode": "redis-hit"}

    sqlite_payload = dependencies.snapshot_store.get(namespace, cache_key)
    if sqlite_payload is not None:
        return {"payload": _with_cache_meta(sqlite_payload, layer, "sqlite-hit", cache_key), "mode": "sqlite-hit"}

    stale_payload = dependencies.snapshot_store.get_stale(
        namespace,
        cache_key,
    )
    if stale_payload is not None:
        dependencies.application.logger.info(
            "market-workspace-cache stale-hit layer=%s key=%s",
            layer,
            cache_key,
        )
        api_cache.set_cached_payload(
            dependencies.cache,
            namespace,
            cache_key,
            stale_payload,
            min(15, ttl_seconds),
        )
        _refresh_async(
            dependencies, layer=layer, namespace=namespace, cache_key=cache_key,
            builder=builder, ttl_seconds=ttl_seconds, stale_payload=stale_payload,
        )
        return {"payload": _with_cache_meta(stale_payload, layer, "stale-hit", cache_key), "mode": "stale-hit"}

    refresh_key = f"{namespace}:{cache_key}"
    if background_only:
        _refresh_async(
            dependencies, layer=layer, namespace=namespace, cache_key=cache_key,
            builder=builder, ttl_seconds=ttl_seconds, stale_payload=_fallback_payload(layer, cache_key),
        )
        return {"payload": _fallback_payload(layer, cache_key), "mode": "warming"}
    claimed, lease = _claim_build(dependencies, refresh_key)
    if not claimed:
        payload = _fallback_payload(layer, cache_key)
        return {"payload": _with_cache_meta(payload, layer, "warming", cache_key), "mode": "warming"}

    try:
        payload = builder()
        mode = "live-build"
        wrapped = _with_cache_meta(payload, layer, mode, cache_key)
        ttl = ttl_seconds if not _is_empty_replacement(layer, payload) else min(ttl_seconds, 10)
        _write_cache(dependencies, namespace, cache_key, wrapped, ttl)
        return {"payload": _copy_payload(wrapped), "mode": mode}
    except Exception:
        dependencies.application.logger.exception(
            "market-workspace-cache live-build failed layer=%s key=%s", layer, cache_key,
        )
        payload = _fallback_payload(layer, cache_key)
        payload["status"] = "unavailable"
        return {"payload": _with_cache_meta(payload, layer, "live-error", cache_key), "mode": "live-error"}
    finally:
        _release_build(dependencies, refresh_key, lease)


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


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"", "0", "false", "none", "null"}


def _market_is_closed(
    context: MarketWorkspaceCacheDependencies,
    market_id: int,
) -> bool:
    dependencies = context
    resolver = dependencies.get_market_by_id
    if not callable(resolver):
        return False
    try:
        market = resolver(int(market_id))
    except Exception:
        dependencies.application.logger.exception(
            "market-workspace-cache market-status lookup failed market_id=%s",
            market_id,
        )
        return False
    if not isinstance(market, Mapping):
        return False
    if any(
        _truthy_flag(market.get(key))
        for key in ("is_trading_closed", "gamma_closed", "is_final")
    ):
        return True
    statuses = " ".join(
        str(market.get(key) or "").strip().lower().replace("_", "-")
        for key in ("status", "completion_status")
    )
    return any(
        token in statuses
        for token in ("closed", "settled", "resolved", "final", "cancelled", "expired", "awaiting-oracle", "awaiting oracle")
    )


def _closed_orderbook_result(
    context: MarketWorkspaceCacheDependencies,
    *,
    market_id: int,
    cache_key: str,
) -> Dict[str, Any]:
    dependencies = context
    namespace = _namespace("orderbook")
    payload = _fallback_payload("orderbook", cache_key)
    payload.update(
        {
            "marketId": int(market_id),
            "localMarketId": int(market_id),
            "bookStatus": "closed",
            "source": "market-lifecycle",
            "fallbackReason": "Trading is closed; live CLOB levels are not applicable.",
        }
    )
    wrapped = _with_cache_meta(payload, "orderbook", "closed", cache_key)
    _write_cache(
        dependencies,
        namespace,
        cache_key,
        wrapped,
        dependencies.orderbook_ttl,
    )
    return {"payload": _copy_payload(wrapped), "mode": "closed"}


def get_market_detail_payload(
    context: MarketWorkspaceCacheDependencies,
    market_id: int,
) -> Dict[str, Any]:
    dependencies = context
    key = _cache_key({"marketId": int(market_id), "layer": "detail", "v": 4})
    result = _cached_layer(
        dependencies,
        layer="detail",
        cache_key=key,
        ttl_seconds=dependencies.detail_ttl,
        builder=lambda: dependencies.build_detail(market_id),
    )
    payload = result["payload"]
    return payload if isinstance(payload, dict) else {"error": "Invalid detail cache payload", "marketId": market_id, "_status": 502}


def get_market_chart_payload(
    context: MarketWorkspaceCacheDependencies,
    market_id: int,
    *,
    range_name: str = "1d",
    interval: str = "5m",
) -> Dict[str, Any]:
    dependencies = context
    normalized_range = str(range_name or "1d").strip().lower()
    normalized_interval = str(interval or "5m").strip().lower()
    key = _cache_key(
        {
            "marketId": int(market_id),
            "layer": "chart",
            "range": normalized_range,
            "interval": normalized_interval,
            "v": 5,
        }
    )
    result = _cached_layer(
        dependencies,
        layer="chart",
        cache_key=key,
        ttl_seconds=dependencies.chart_ttl,
        builder=lambda: dependencies.build_chart(
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


def get_market_flow_payload(
    context: MarketWorkspaceCacheDependencies,
    market_id: int,
    *,
    limit: int = 24,
    offset: int = 0,
    before: Optional[tuple[int, int, str]] = None,
) -> Dict[str, Any]:
    dependencies = context
    safe_limit = min(max(int(limit), 1), 500)
    safe_offset = max(int(offset), 0)
    key = _cache_key(
        {
            "marketId": int(market_id),
            "layer": "flow",
            "limit": safe_limit,
            "offset": safe_offset,
            "before": before,
            "v": 2,
        }
    )

    def build() -> Dict[str, Any]:
        return {
            "marketId": market_id,
            "localMarketId": market_id,
            "items": dependencies.build_flow(
                market_id,
                limit=safe_limit,
                offset=safe_offset,
                **({"before": before} if before is not None else {}),
            ),
            "generatedAt": dependencies.utc_now_iso(),
        }

    result = _cached_layer(
        dependencies,
        layer="flow",
        cache_key=key,
        ttl_seconds=dependencies.flow_ttl,
        builder=build,
    )
    payload = result["payload"]
    if isinstance(payload, dict):
        payload.setdefault("marketId", market_id)
        payload.setdefault("localMarketId", market_id)
        payload.setdefault("items", [])
        return payload
    return {"marketId": market_id, "localMarketId": market_id, "items": []}


def get_market_flow_rows(
    context: MarketWorkspaceCacheDependencies,
    market_id: int,
    *,
    limit: int = 24,
    offset: int = 0,
    before: Optional[tuple[int, int, str]] = None,
) -> list[Dict[str, Any]]:
    payload = get_market_flow_payload(
        context,
        market_id,
        limit=limit,
        offset=offset,
        before=before,
    )
    if payload.get("status") in {"warming", "unavailable"}:
        raise TimeoutError("Market trade data is not ready")
    rows = payload.get("items")
    return rows if isinstance(rows, list) else []


def get_market_orderbook_payload(
    context: MarketWorkspaceCacheDependencies,
    market_id: int,
) -> Dict[str, Any]:
    dependencies = context
    key = _cache_key({"marketId": int(market_id), "layer": "orderbook", "v": 1})
    result = (
        _closed_orderbook_result(
            dependencies,
            market_id=market_id,
            cache_key=key,
        )
        if _market_is_closed(dependencies, market_id)
        else _cached_layer(
            dependencies,
            layer="orderbook",
            cache_key=key,
            ttl_seconds=dependencies.orderbook_ttl,
            builder=lambda: dependencies.build_lob(
                market_id,
            ),
        )
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


def get_market_workspace_payload(
    context: MarketWorkspaceCacheDependencies,
    market_id: int,
) -> Dict[str, Any]:
    dependencies = context
    detail_result = get_market_detail_payload(dependencies, market_id)
    if detail_result.get("_status"):
        return detail_result

    chart = get_market_chart_payload(dependencies, market_id, range_name="1d", interval="5m")
    flow = get_market_flow_payload(dependencies, market_id, limit=24, offset=0)
    orderbook = get_market_orderbook_payload(dependencies, market_id)
    payload = assemble_market_workspace(detail_result, chart=chart, flow=flow, lob=orderbook)
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


def get_market_focus_tile_payload(
    context: MarketWorkspaceCacheDependencies,
    market_id: int,
) -> Dict[str, Any]:
    """Serve the selection-critical detail, chart and LOB without cold-path blocking."""
    dependencies = context
    detail_key = _cache_key({"marketId": int(market_id), "layer": "detail", "v": 4})
    chart_key = _cache_key(
        {
            "marketId": int(market_id),
            "layer": "chart",
            "range": "1d",
            "interval": "5m",
            "v": 5,
        }
    )
    orderbook_key = _cache_key({"marketId": int(market_id), "layer": "orderbook", "v": 1})

    detail_result = _cached_layer(
        dependencies,
        background_only=True,
        layer="detail",
        cache_key=detail_key,
        ttl_seconds=dependencies.detail_ttl,
        builder=lambda: dependencies.build_detail(market_id),
    )
    detail = detail_result["payload"] if isinstance(detail_result["payload"], dict) else {}
    if detail.get("_status"):
        return detail
    chart_result = _cached_layer(
        dependencies,
        background_only=True,
        layer="chart",
        cache_key=chart_key,
        ttl_seconds=dependencies.chart_ttl,
        builder=lambda: dependencies.build_chart(
            market_id,
            range_name="1d",
            interval="5m",
        ),
    )
    orderbook_result = (
        _closed_orderbook_result(
            dependencies,
            market_id=market_id,
            cache_key=orderbook_key,
        )
        if _market_is_closed(dependencies, market_id)
        else _cached_layer(
            dependencies,
            background_only=True,
            layer="orderbook",
            cache_key=orderbook_key,
            ttl_seconds=dependencies.orderbook_ttl,
            builder=lambda: dependencies.build_lob(
                market_id,
            ),
        )
    )

    chart = chart_result["payload"] if isinstance(chart_result["payload"], dict) else _fallback_payload("chart", chart_key)
    orderbook = orderbook_result["payload"] if isinstance(orderbook_result["payload"], dict) else _fallback_payload("orderbook", orderbook_key)
    chart.setdefault("marketId", market_id)
    chart.setdefault("localMarketId", market_id)
    chart.setdefault("range", "1d")
    chart.setdefault("interval", "5m")
    orderbook.setdefault("marketId", market_id)
    orderbook.setdefault("localMarketId", market_id)

    payload = assemble_market_workspace(detail, chart=chart, lob=orderbook)
    payload.setdefault("marketId", market_id)
    payload.setdefault("localMarketId", market_id)
    payload["chart"] = chart
    payload["lob"] = orderbook
    payload["cacheLayers"] = {
        "detail": detail_result["mode"],
        "chart": chart_result["mode"],
        "orderbook": orderbook_result["mode"],
    }
    modes = payload["cacheLayers"].values()
    payload["focusStatus"] = "unavailable" if "live-error" in modes else "warming" if "warming" in modes else "ready"
    payload["generatedAt"] = _utc_now_iso()
    return payload
