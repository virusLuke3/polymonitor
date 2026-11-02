from __future__ import annotations

import json
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, Optional


from dataclasses import dataclass, field
from api.context import RuntimeResources


@dataclass
class CacheState:
    resources: RuntimeResources
    application: Any
    snapshot_store: Any
    redis_url: str = field(default="", repr=False)
    redis_prefix: str = "polydata:"
    redis_module: Any = None
    redis_client: Any = None
    redis_retry_at: float = 0
    redis_lock: Any = field(default_factory=threading.Lock)
    runtime_cache: dict = field(default_factory=dict)
    runtime_lock: Any = field(default_factory=threading.Lock)
    markets_cache: dict = field(default_factory=dict)
    markets_lock: Any = field(default_factory=threading.Lock)
    snapshot_retry_at: Any = field(default_factory=OrderedDict)


def get_redis_client(ctx: CacheState):
    if not ctx.redis_url or ctx.redis_module is None:
        return None
    existing = ctx.redis_client
    if existing is not None:
        return existing
    with ctx.redis_lock:
        if time.monotonic() < ctx.redis_retry_at:
            return None
        existing = ctx.redis_client
        if existing is not None:
            return existing
        try:
            client = ctx.redis_module.from_url(
                ctx.redis_url,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
                health_check_interval=30,
            )
            client.ping()
            ctx.redis_client = client
            return client
        except Exception as exc:
            # URLs and exception messages may both contain credentials.
            ctx.application.logger.warning("redis-init failed error_type=%s", type(exc).__name__)
            ctx.redis_retry_at = time.monotonic() + 30
            ctx.redis_client = None
            return None


def get_cached_runtime_payload(ctx: CacheState, namespace: str, cache_key: str) -> Optional[Any]:
    now = time.monotonic()
    composite_key = f"{namespace}:{cache_key}"
    with ctx.runtime_lock:
        cached = ctx.runtime_cache.get(composite_key)
        if not cached or cached.get("expires_at", 0.0) <= now:
            if cached:
                ctx.runtime_cache.pop(composite_key, None)
            return None
        return cached.get("payload")


def set_cached_runtime_payload(ctx: CacheState, namespace: str, cache_key: str, payload: Any, ttl_seconds: int) -> Any:
    composite_key = f"{namespace}:{cache_key}"
    with ctx.runtime_lock:
        if len(ctx.runtime_cache) >= 512 and composite_key not in ctx.runtime_cache:
            ctx.runtime_cache.pop(next(iter(ctx.runtime_cache)))
        ctx.runtime_cache[composite_key] = {
            "payload": payload,
            "expires_at": time.monotonic() + max(1, ttl_seconds),
        }
    return payload


def _redis_key(ctx: CacheState, namespace: str, cache_key: str) -> str:
    return f"{ctx.redis_prefix}{namespace}:{cache_key}"


def get_cached_payload(ctx: CacheState, namespace: str, cache_key: str) -> Optional[Any]:
    client = get_redis_client(ctx)
    if client is None:
        return None
    try:
        raw = client.get(_redis_key(ctx, namespace, cache_key))
    except Exception as exc:
        ctx.application.logger.warning("redis-get failed error_type=%s", type(exc).__name__)
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception as exc:
        ctx.application.logger.warning("redis-json decode failed error_type=%s", type(exc).__name__)
        return None


def set_cached_payload(ctx: CacheState, namespace: str, cache_key: str, payload: Any, ttl_seconds: int) -> None:
    client = get_redis_client(ctx)
    if client is None:
        return
    try:
        client.setex(
            _redis_key(ctx, namespace, cache_key), ttl_seconds, json.dumps(payload, ensure_ascii=True, default=str)
        )
    except Exception as exc:
        ctx.application.logger.warning("redis-set failed error_type=%s", type(exc).__name__)


def get_cached_json(ctx: CacheState, namespace: str, cache_key: str) -> Optional[Dict[str, Any]]:
    payload = get_cached_payload(ctx, namespace, cache_key)
    return payload if isinstance(payload, dict) else None


def set_cached_json(ctx: CacheState, namespace: str, cache_key: str, payload: Dict[str, Any], ttl_seconds: int) -> None:
    set_cached_payload(ctx, namespace, cache_key, payload, ttl_seconds)


def _store_snapshot_payload(ctx: CacheState, namespace: str, cache_key: str, payload: Any, ttl_seconds: int) -> None:
    if isinstance(payload, dict) and (payload.get("error") or payload.get("status") in {"error", "unavailable"}):
        raise RuntimeError("Snapshot builder returned an unavailable result")
    ctx.snapshot_store.set(namespace, cache_key, payload, ttl_seconds)


def _admit_snapshot(ctx, namespace, cache_key):
    resources = ctx.resources
    refresh_key = f"{namespace}:{cache_key}"
    with resources.snapshot_lock:
        if refresh_key in resources.snapshot_refreshing or ctx.snapshot_retry_at.get(refresh_key, 0) > time.monotonic():
            return
        if not resources.snapshot_slots.acquire(blocking=False):
            ctx.application.logger.info(
                "snapshot-refresh deferred capacity-full namespace=%s key=%s",
                namespace,
                cache_key,
            )
            return
        resources.snapshot_refreshing.add(refresh_key)
    owner = uuid.uuid4().hex
    client = get_redis_client(ctx)
    lock_key = _redis_key(ctx, "snapshot-admission", refresh_key)
    if client is not None:
        try:
            if not client.set(lock_key, owner, nx=True, ex=120):
                _release_snapshot(ctx, refresh_key, None, lock_key, owner, failed=False)
                return
        except Exception:
            # Keep the process-wide slot bound even if shared admission is down.
            client = None
    return refresh_key, client, lock_key, owner


def _release_snapshot(ctx, refresh_key, client, lock_key, owner, *, failed):
    if client is not None:
        try:
            # A failed builder retains the distributed lease briefly as cooldown.
            client.eval("if redis.call('get',KEYS[1]) == ARGV[1] then "
                        "if ARGV[2] == '1' then return redis.call('expire',KEYS[1],15) "
                        "else return redis.call('del',KEYS[1]) end end return 0",
                        1, lock_key, owner, '1' if failed else '0')
        except Exception:
            pass
    with ctx.resources.snapshot_lock:
        ctx.resources.snapshot_refreshing.discard(refresh_key)
        if failed:
            ctx.snapshot_retry_at[refresh_key] = time.monotonic() + 15
            while len(ctx.snapshot_retry_at) > 512:
                ctx.snapshot_retry_at.popitem(last=False)
        else:
            ctx.snapshot_retry_at.pop(refresh_key, None)
    ctx.resources.snapshot_slots.release()


def _refresh_snapshot_payload_async(ctx: CacheState, namespace: str, cache_key: str, builder, ttl_seconds: int) -> None:
    admission = _admit_snapshot(ctx, namespace, cache_key)
    if admission is None:
        return

    def refresh() -> None:
        failed = True
        try:
            payload = builder()
            _store_snapshot_payload(ctx, namespace, cache_key, payload, ttl_seconds)
            failed = False
            ctx.application.logger.info("snapshot-refresh completed namespace=%s key=%s", namespace, cache_key)
        except Exception:
            ctx.application.logger.exception("snapshot-refresh failed namespace=%s key=%s", namespace, cache_key)
        finally:
            _release_snapshot(ctx, *admission, failed=failed)

    if not ctx.resources.start_thread(refresh, name=f"snapshot-refresh:{namespace}"):
        _release_snapshot(ctx, *admission, failed=True)


def get_snapshot_payload(ctx: CacheState, namespace: str, cache_key: str, builder, *, ttl_seconds: int) -> Any:
    sqlite_payload = ctx.snapshot_store.get(namespace, cache_key)
    if sqlite_payload is not None:
        return sqlite_payload

    stale_payload = ctx.snapshot_store.get_stale(namespace, cache_key)
    if isinstance(stale_payload, dict):
        ctx.application.logger.info(
            "snapshot-cache stale-hit namespace=%s key=%s scheduling_refresh=true", namespace, cache_key
        )
        _refresh_snapshot_payload_async(ctx, namespace, cache_key, builder, ttl_seconds)
        return {**stale_payload, "stale": True, "cacheStatus": "stale"}

    # Bare lists cannot carry a stale marker; refresh before returning them.
    admission = _admit_snapshot(ctx, namespace, cache_key)
    if admission is None:
        raise TimeoutError("Snapshot refresh is pending or cooling down")
    failed = True
    try:
        payload = builder()
        _store_snapshot_payload(ctx, namespace, cache_key, payload, ttl_seconds)
        failed = False
        return payload
    except Exception:
        ctx.application.logger.exception("snapshot-builder failed namespace=%s key=%s", namespace, cache_key)
        raise

    finally:
        _release_snapshot(ctx, *admission, failed=failed)


def get_markets_payload_cached(
    ctx: CacheState, cache_key: str, builder, *, namespace: str, ttl_seconds: int
) -> Dict[str, Any]:
    local_cache_key = f"{namespace}:{cache_key}"
    redis_payload = get_cached_json(ctx, namespace, cache_key)
    if redis_payload is not None:
        ctx.application.logger.info("%s-cache redis-hit key=%s", namespace, cache_key)
        return redis_payload

    now_monotonic = time.monotonic()
    cached_entry = ctx.markets_cache.get(local_cache_key)
    if cached_entry is not None and cached_entry.get("expires_at", 0.0) > now_monotonic:
        ctx.application.logger.info(
            "markets-cache hit key=%s ttl_remaining_ms=%.2f",
            cache_key,
            (cached_entry["expires_at"] - now_monotonic) * 1000,
        )
        return cached_entry["value"]

    with ctx.markets_lock:
        cached_entry = ctx.markets_cache.get(local_cache_key)
        if cached_entry is not None and cached_entry.get("expires_at", 0.0) > time.monotonic():
            ctx.application.logger.info("markets-cache hit-after-lock key=%s", cache_key)
            return cached_entry["value"]

        payload = builder()
        ctx.markets_cache[local_cache_key] = {
            "value": payload,
            "expires_at": time.monotonic() + ttl_seconds,
        }
        set_cached_json(ctx, namespace, cache_key, payload, ttl_seconds)
        expired_keys = [
            key for key, value in ctx.markets_cache.items() if value.get("expires_at", 0.0) <= time.monotonic()
        ]
        for key in expired_keys:
            ctx.markets_cache.pop(key, None)
        return payload
