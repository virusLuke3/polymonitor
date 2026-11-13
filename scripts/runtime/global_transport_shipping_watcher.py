#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

_scripts_root = Path(__file__).resolve().parents[1]
if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))

try:
    import redis
except ImportError:
    redis = None

try:
    import requests
except ImportError:
    requests = None

from runtime.redis_snapshot_store import seed_writer
from api.config import load_api_settings
from api.clients.source_transport import read_response_bytes, read_with_retry, source_session
from api.context import RuntimeResources
from api.services import global_transport_shipping_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, utc_now_iso, publish_snapshot, retained_snapshot
from runtime.redis_snapshot_store import create_snapshot_store as SnapshotStore
from runtime.telegram_panel_publish import publish_cached_panel_snapshot


DEFAULT_INTERVAL_SECONDS = 3600
DEFAULT_LIMIT = 14
SEED_META_NAMESPACE = "seed-meta:transport"
SEED_META_CACHE_KEY = "global-transport-shipping"
SEED_META_SERVICE_NAME = "polydata-global-transport-shipping-seed.service"


class _Logger:
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[global-transport-shipping] ERROR {message % args if args else message}", file=sys.stderr)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[global-transport-shipping] WARN {message % args if args else message}", file=sys.stderr)


class _App:
    logger = _Logger()


def _redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{str(prefix or '')}{namespace}:{cache_key}"


class GlobalTransportShippingWatcher:
    def __init__(self, *, redis_url: str, redis_prefix: str, snapshot_sqlite_path: str, settings: Any, limit: int, interval_seconds: int) -> None:
        self.resources = RuntimeResources()
        if requests is None:
            raise RuntimeError("requests package is required. Install scripts/requirements.txt")
        self.settings = settings
        self.limit = max(1, int(limit or DEFAULT_LIMIT))
        self.interval_seconds = max(300, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_prefix = str(redis_prefix or "")
        self.redis_client = (redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
                             if redis is not None and str(redis_url or "").strip() else None)
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)
        self.requests = source_session(requests_lib=requests)
        self.requests.trust_env = str(os.environ.get("POLYDATA_RUNTIME_TRUST_ENV", "0")).strip().lower() in {"1", "true", "yes", "on"}
        self.requests.headers.update({"User-Agent": "polydata-global-transport/1.0"})

    def ttl_seconds(self) -> int:
        configured = int(os.environ.get("POLYDATA_GLOBAL_TRANSPORT_SEED_TTL_SECONDS", "0") or 0)
        if configured > 0:
            return configured
        return max(1800, self.interval_seconds * 3)

    def redis_key(self) -> str:
        return _redis_key(
            self.redis_prefix,
            global_transport_shipping_service.GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE,
            global_transport_shipping_service.GLOBAL_TRANSPORT_CACHE_KEY,
        )

    def http_text_get(self, url: str, timeout: int = 45, headers: Optional[Dict[str, str]] = None) -> str:
        now = time.monotonic()
        deadline = min(now + 90, getattr(self, "_collection_deadline", now + 90))
        if deadline - now < 45:
            raise requests.exceptions.Timeout("transport collection budget exhausted")

        def read(response):
            body = read_response_bytes(response, 12 * 1024 * 1024, deadline=deadline)
            return body.decode(response.encoding or "utf-8", errors="replace")

        return read_with_retry(self.requests, url, read, attempts=2, deadline=deadline,
                               timeout=45, headers=headers, stream=True)

    def http_json_get(self, url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 18, headers: Optional[Dict[str, str]] = None) -> Any:
        response = self.requests.get(url, params=params, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response.json()

    def http_form_post(self, url: str, data: Dict[str, Any], timeout: int = 18, headers: Optional[Dict[str, str]] = None) -> Any:
        response = self.requests.post(url, data=data, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response.json()

    def close(self) -> None:
        self.resources.close()
        self.requests.close()
        if self.redis_client is not None:
            self.redis_client.close()

    def context(self) -> Dict[str, Any]:
        return {
            "_resources": self.resources,
            "SETTINGS": self.settings,
            "SNAPSHOT_STORE": self.snapshot_store,
            "app": _App(),
            "http_text_get": self.http_text_get,
            "http_json_get": self.http_json_get,
            "http_form_post": self.http_form_post,
            "get_cached_json": self.seed_meta_store.get,
            "set_cached_json": self.seed_meta_store.cache_source,
            "utc_now_iso": utc_now_iso,
        }

    def previous(self) -> Dict[str, Any]:
        stale = self.snapshot_store.get_stale(
            global_transport_shipping_service.GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE,
            global_transport_shipping_service.GLOBAL_TRANSPORT_CACHE_KEY,
        )
        if isinstance(stale, dict):
            return stale
        cached = self.seed_meta_store.get(
            global_transport_shipping_service.GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE,
            global_transport_shipping_service.GLOBAL_TRANSPORT_CACHE_KEY,
        )
        if cached:
            return cached
        return {}

    def store_payload(self, payload: Dict[str, Any]) -> None:
        ttl = self.ttl_seconds()
        publish_snapshot(
            snapshot_store=self.snapshot_store, namespace=global_transport_shipping_service.GLOBAL_TRANSPORT_SNAPSHOT_NAMESPACE,
            cache_key=global_transport_shipping_service.GLOBAL_TRANSPORT_CACHE_KEY, payload=payload, ttl_seconds=ttl,
            redis_client=self.redis_client, redis_cache_key=self.redis_key(),
        )

    def store_meta(self, *, status: str, record_count: int, source_states: Dict[str, Any] | None = None, error_summary: str | None = None, cache_mode: str | None = None, payload_status: str | None = None, preserve: bool = False) -> None:
        previous = self.seed_meta_store.load(SEED_META_NAMESPACE, SEED_META_CACHE_KEY) or {}
        attempted = utc_now_iso()
        last_success = previous.get("lastSuccessAt")
        if not preserve and (status in {"ok", "empty"} or (status == "degraded" and record_count > 0)):
            last_success = attempted
        payload = build_seed_meta_payload(
            panel_id=SEED_META_CACHE_KEY,
            namespace=SEED_META_NAMESPACE,
            cache_key=SEED_META_CACHE_KEY,
            service_name=SEED_META_SERVICE_NAME,
            expected_interval_seconds=self.interval_seconds,
            status=status,
            last_attempt_at=attempted,
            last_success_at=last_success,
            record_count=record_count,
            source_states=source_states,
            error_summary=error_summary,
            cache_mode=cache_mode,
            payload_status=payload_status,
        )
        self.seed_meta_store.store(SEED_META_NAMESPACE, SEED_META_CACHE_KEY, payload)

    def store_meta_fail_soft(self, **kwargs: Any) -> bool:
        try:
            self.store_meta(**kwargs)
            return True
        except Exception as exc:
            print(f"[global_transport_shipping] WARN seed meta write failed: {exc.__class__.__name__}", file=sys.stderr)
            return False

    @seed_writer
    def run_once(self) -> Dict[str, Any]:
        previous = self.previous()
        self._collection_deadline = time.monotonic() + 240
        try:
            payload = global_transport_shipping_service.build_global_transport_shipping_payload(self.context(), limit=self.limit)
        except Exception as exc:
            if previous:
                preserved = {**retained_snapshot(previous), "freshness": "stale",
                             "sourceHealth": {key: "stale" if value == "fresh" else value
                                              for key, value in (previous.get("sourceHealth") or {}).items()}}
                self.store_payload(preserved)
                self.store_meta(status="preserved", record_count=len(preserved.get("items") or []), source_states={"transport": "error"}, error_summary=str(exc), preserve=True)
                return {"status": "preserved", "payload": preserved, "error": str(exc)}
            self.store_meta(status="error", record_count=0, source_states={"transport": "error"}, error_summary=str(exc), preserve=True)
            return {"status": "error", "error": str(exc)}

        payload = {**payload, "cacheMode": "seeded", "freshness": "seeded"}
        self.store_payload(payload)
        telegram_sent = publish_cached_panel_snapshot(SEED_META_CACHE_KEY, payload)
        sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
        source_states = {key: value.get("status") if isinstance(value, dict) else value for key, value in sources.items()}
        self.store_meta(status=str(payload.get("status") or "ok"), record_count=len(payload.get("items") or []), source_states=source_states, cache_mode="seeded", payload_status=payload.get("status"))
        return {"status": "stored", "payload": payload, "telegramSent": telegram_sent}


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLYDATA_GLOBAL_TRANSPORT_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("POLYDATA_GLOBAL_TRANSPORT_LIMIT", DEFAULT_LIMIT)))
    args = parser.parse_args()
    settings = load_api_settings()
    watcher = GlobalTransportShippingWatcher(
        redis_url=settings.redis_url,
        redis_prefix=settings.redis_prefix,
        snapshot_sqlite_path=settings.snapshot_sqlite_path,
        settings=settings,
        limit=args.limit,
        interval_seconds=args.interval,
    )
    try:
        print(f"[global-transport-shipping] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
        if not args.watch:
            print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
            return 0
        while True:
            try:
                print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
            except KeyboardInterrupt:
                return 0
            except Exception as exc:
                watcher.store_meta_fail_soft(status="error", record_count=0, source_states={"transport": "error"}, error_summary=str(exc), preserve=True)
                print(f"[global-transport-shipping] ERROR {exc}", file=sys.stderr)
            time.sleep(max(300, args.interval))
    finally:
        watcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
