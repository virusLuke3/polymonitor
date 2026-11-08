#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed DeFi token watch snapshots into Redis and SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
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

from api.clients.source_transport import source_session
from api.config import load_api_settings
from api.services import defi_token_watch_service
from api.services.seed_recovery import bounded_rows, retain_failed_rows
from runtime.seed_meta import retained_snapshot
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, publish_snapshot, SnapshotPublicationError
from runtime.snapshot_store import SnapshotStore


DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_LIMIT = 10
SEED_META_NAMESPACE = "seed-meta:finance"
SEED_META_CACHE_KEY = "defi-token-watch"
SEED_META_SERVICE_NAME = "polydata-defi-token-watch-seed.service"


class _LoggerAdapter:
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[defi-token-watch] ERROR {message % args if args else message}", file=sys.stderr)


class _AppAdapter:
    logger = _LoggerAdapter()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{str(prefix or '')}{namespace}:{cache_key}"


class DefiTokenWatchWatcher:
    def __init__(
        self,
        *,
        redis_url: str,
        redis_prefix: str,
        snapshot_sqlite_path: str,
        settings: Any,
        limit: int = DEFAULT_LIMIT,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        if requests is None:
            raise RuntimeError("requests package is required. Install scripts/requirements.txt")
        self.settings = settings
        self.limit = max(3, int(limit or DEFAULT_LIMIT))
        self.interval_seconds = max(60, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_prefix = str(redis_prefix or "")
        self.redis_client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2) if redis is not None and str(redis_url or "").strip() else None
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)
        self.requests = source_session()
        trust_env_proxy = str(os.environ.get("POLYDATA_DEFI_TOKEN_WATCH_TRUST_ENV_PROXY") or "").strip().lower()
        self.requests.trust_env = trust_env_proxy in {"1", "true", "yes", "on"}

    def ttl_seconds(self) -> int:
        configured = int(os.environ.get("POLYDATA_DEFI_TOKEN_WATCH_SEED_TTL_SECONDS", "0") or 0)
        if configured > 0:
            return configured
        return max(180, self.interval_seconds * 3, int(getattr(self.settings, "defi_token_watch_ttl_seconds", 120) or 120) * 3)

    def cache_key(self) -> str:
        return defi_token_watch_service.build_defi_token_watch_cache_key(self.settings, limit=self.limit)

    def namespace(self) -> str:
        return defi_token_watch_service.DEFI_TOKEN_WATCH_NAMESPACE

    def redis_key(self) -> str:
        return _redis_key(self.redis_prefix, self.namespace(), self.cache_key())

    def http_json_get(self, url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 12, headers: Optional[Dict[str, str]] = None) -> Any:
        response = self.requests.get(url, params=params, timeout=timeout, headers=headers)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def service_context(self) -> Dict[str, Any]:
        return {
            "SETTINGS": self.settings,
            "app": _AppAdapter(),
            "http_json_get": self.http_json_get,
            "utc_now_iso": utc_now_iso,
        }

    def load_previous_payload(self) -> Dict[str, Any]:
        stale = self.snapshot_store.get_stale(self.namespace(), self.cache_key())
        if isinstance(stale, dict):
            return stale
        try:
            raw = self.redis_client.get(self.redis_key())
            if raw:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            print("[defi-token-watch] WARN redis read failed", file=sys.stderr)
        return {}

    def store_payload(self, payload: Dict[str, Any]) -> None:
        try:
            publish_snapshot(snapshot_store=self.snapshot_store, namespace=self.namespace(),
                             cache_key=self.cache_key(), payload=payload, ttl_seconds=self.ttl_seconds(),
                             redis_client=self.redis_client, redis_cache_key=self.redis_key())
        except SnapshotPublicationError as exc:
            self.store_seed_meta(status="error", record_count=0,
                                 source_states={"publication": "error"}, error_summary=str(exc),
                                 preserve_last_success=True)
            raise

    def store_seed_meta(self, *, status: str, record_count: int, source_states: Dict[str, Any], error_summary: str | None, preserve_last_success: bool = False) -> None:
        previous = self.seed_meta_store.load(SEED_META_NAMESPACE, SEED_META_CACHE_KEY) or {}
        attempted_at = utc_now_iso()
        last_success_at = previous.get("lastSuccessAt")
        if not preserve_last_success and status in {"ok", "degraded", "preserved"}:
            last_success_at = attempted_at
        payload = build_seed_meta_payload(
            panel_id="defi-token-watch",
            namespace=SEED_META_NAMESPACE,
            cache_key=SEED_META_CACHE_KEY,
            service_name=SEED_META_SERVICE_NAME,
            expected_interval_seconds=self.interval_seconds,
            status=status,
            last_attempt_at=attempted_at,
            last_success_at=last_success_at or attempted_at,
            record_count=record_count,
            source_states=source_states,
            error_summary=error_summary,
            cache_mode="seeded",
            payload_status=status,
            metadata={"result": "stored", "limit": self.limit},
        )
        payload["lastSuccessAt"] = last_success_at
        self.seed_meta_store.store(SEED_META_NAMESPACE, SEED_META_CACHE_KEY, payload)

    def run_once(self) -> Dict[str, Any]:
        previous = bounded_rows(self.load_previous_payload(), utc_now_iso())
        try:
            payload = defi_token_watch_service.fetch_live_defi_token_watch_payload(self.service_context(), limit=self.limit)
        except Exception as exc:
            if previous.get("items"):
                previous = retained_snapshot(previous, sources={"coingecko": "error"})
                self.store_payload(previous)
                self.store_seed_meta(
                    status="preserved",
                    record_count=len(previous.get("items") or []),
                    source_states={"coingecko": "error"},
                    error_summary=str(exc),
                    preserve_last_success=True,
                )
                return {"status": "preserved", "payload": previous}
            self.store_seed_meta(status="error", record_count=0, source_states={"coingecko": "error"}, error_summary=str(exc), preserve_last_success=True)
            raise

        missing = (payload.get("summary") or {}).get("missingIds") or []
        payload["items"] = (payload.get("items") or []) + retain_failed_rows(previous, missing, utc_now_iso())
        record_count = len(payload.get("items") or [])
        payload["summary"] = {**payload.get("summary", {}), "count": record_count,
                              "retainedCount": sum(bool(row.get("retained")) for row in payload.get("items", []))}
        if previous and record_count <= 0:
            self.store_payload(previous)
            self.store_seed_meta(
                status="preserved",
                record_count=len(previous.get("items") or []),
                source_states=payload.get("sources") if isinstance(payload.get("sources"), dict) else {"coingecko": "empty"},
                error_summary="Preserved previous DeFi token snapshot because new payload was empty",
                preserve_last_success=True,
            )
            return {"status": "preserved", "payload": previous}

        payload = {**payload, "cacheMode": "seeded"}
        self.store_payload(payload)
        status = str(payload.get("status") or ("ok" if record_count else "degraded"))
        self.store_seed_meta(
            status=status if status in {"ok", "degraded"} else "degraded",
            record_count=record_count,
            source_states=payload.get("sources") if isinstance(payload.get("sources"), dict) else {},
            error_summary=None if record_count else "DeFi token payload contained no items",
        )
        return {"status": status, "payload": payload}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed DeFi token watch panel snapshots into Redis and SQLite")
    parser.add_argument("--watch", action="store_true", help="Run continuously instead of once")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLYDATA_DEFI_TOKEN_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("POLYDATA_DEFI_TOKEN_WATCH_LIMIT", DEFAULT_LIMIT)))
    return parser


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    args = build_arg_parser().parse_args()
    settings = load_api_settings()
    watcher = DefiTokenWatchWatcher(
        redis_url=settings.redis_url,
        redis_prefix=settings.redis_prefix,
        snapshot_sqlite_path=settings.snapshot_sqlite_path,
        settings=settings,
        limit=args.limit,
        interval_seconds=args.interval,
    )
    print(f"[defi-token-watch] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        return 0
    interval_seconds = max(60, int(args.interval or DEFAULT_INTERVAL_SECONDS))
    while True:
        try:
            print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"[defi-token-watch] ERROR watch loop failed: {exc}", file=sys.stderr)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
