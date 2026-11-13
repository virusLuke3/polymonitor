from __future__ import annotations

from typing import Any, Callable, Dict, Optional
from runtime.seed_meta import publish_snapshot



def read_cached(
    ctx: Dict[str, Any],
    *,
    namespace: str,
    cache_key: str,
    normalize_payload: Callable[[Dict[str, Any]], Dict[str, Any]],
    has_generated_fallback_artifacts: Callable[[Dict[str, Any]], bool],
) -> Optional[Dict[str, Any]]:
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        cached = store.get(namespace, cache_key)
        if isinstance(cached, dict):
            if has_generated_fallback_artifacts(cached):
                return None
            return {**normalize_payload(cached), "cacheMode": getattr(store, "backend", "sqlite")}
        stale = store.get_stale(namespace, cache_key)
        if isinstance(stale, dict):
            if has_generated_fallback_artifacts(stale):
                return None
            return {**normalize_payload(stale), "cacheMode": "stale"}
    reader = ctx.get("get_cached_json")
    if callable(reader):
        try:
            cached = reader(namespace, cache_key)
        except Exception:
            cached = None
        if isinstance(cached, dict) and not has_generated_fallback_artifacts(cached):
            return {**normalize_payload(cached), "cacheMode": "redis"}
    return None


def store_payload(ctx: Dict[str, Any], *, namespace: str, cache_key: str, payload: Dict[str, Any], ttl_seconds: int) -> None:
    store = ctx.get("SNAPSHOT_STORE")
    setter = ctx.get("set_cached_json")
    if store is not None:
        publish_snapshot(
            snapshot_store=store, namespace=namespace, cache_key=cache_key,
            payload=payload, ttl_seconds=ttl_seconds,
            redis_client=None if callable(setter) else ctx.get("redis_client") or ctx.get("REDIS_CLIENT"),
            redis_cache_key=f"{ctx.get('redis_prefix') or ctx.get('REDIS_PREFIX') or ''}{namespace}:{cache_key}",
        )
    if callable(setter) and getattr(store, "backend", "sqlite") != "redis":
        try:
            setter(namespace, cache_key, payload, ttl_seconds)
        except Exception:
            if store is None:
                raise
            log_exception(ctx, "worldcup snapshot mirror failed namespace=%s", namespace)


def log_exception(ctx: Dict[str, Any], message: str, *args: Any) -> None:
    app = ctx.get("app")
    logger = getattr(app, "logger", None)
    if logger is not None:
        logger.exception(message, *args)
