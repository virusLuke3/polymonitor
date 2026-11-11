#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone watcher for F1 trackside panel snapshots."""

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

from runtime.redis_snapshot_store import seed_writer
from api.config import load_api_settings
from api.clients.source_transport import source_session
from api.services import f1_runtime_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, publish_snapshot, retained_snapshot
from runtime.redis_snapshot_store import create_snapshot_store as SnapshotStore


DEFAULT_INTERVAL_SECONDS = 180
DEFAULT_LIMIT = 10
SEED_META_NAMESPACE = "seed-meta:sports"
SEED_META_CACHE_KEY = "f1-trackside"
SEED_META_SERVICE_NAME = "polydata-f1-seed.service"


class _LoggerAdapter:
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[f1] ERROR {message % args if args else message}", file=sys.stderr)


class _AppAdapter:
    logger = _LoggerAdapter()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{str(prefix or '')}{namespace}:{cache_key}"


def _cards(payload: Dict[str, Any]) -> list[Any]:
    cards = payload.get("cards") or payload.get("items")
    return cards if isinstance(cards, list) else []


class F1Watcher:
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
        if redis is None:
            raise RuntimeError("redis package is required. Install scripts/requirements.txt")
        if requests is None:
            raise RuntimeError("requests package is required. Install scripts/requirements.txt")
        if not str(redis_url or "").strip():
            raise RuntimeError("POLYDATA_REDIS_URL is required for F1 watcher")
        self.settings = settings
        self.limit = max(1, int(limit or DEFAULT_LIMIT))
        self.interval_seconds = max(60, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_prefix = str(redis_prefix or "")
        self.redis_client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(
            redis_client=self.redis_client,
            redis_prefix=self.redis_prefix,
            snapshot_store=self.snapshot_store,
        )
        self.requests = source_session(requests)
        self.requests.trust_env = False
        proxy = os.environ.get("POLYDATA_API_HTTP_PROXY_URL", "").strip()
        if proxy:
            self.requests.proxies.update({"http": proxy, "https": proxy})

    def namespace(self) -> str:
        return f1_runtime_service.F1_SNAPSHOT_NAMESPACE

    def cache_key(self) -> str:
        return f1_runtime_service.build_f1_cache_key(limit=self.limit)

    def redis_key(self) -> str:
        return _redis_key(self.redis_prefix, self.namespace(), self.cache_key())

    def seed_meta_namespace(self) -> str:
        return SEED_META_NAMESPACE

    def seed_meta_cache_key(self) -> str:
        return SEED_META_CACHE_KEY

    def ttl_seconds(self) -> int:
        configured = int(os.environ.get("POLYDATA_F1_SEED_TTL_SECONDS", "0") or 0)
        if configured > 0:
            return configured
        return max(300, self.interval_seconds * 3, int(self.settings.sports_runtime_ttl_seconds or 60) * 4)

    def load_seed_meta(self) -> Dict[str, Any]:
        payload = self.seed_meta_store.load(self.seed_meta_namespace(), self.seed_meta_cache_key())
        return payload if isinstance(payload, dict) else {}

    def store_seed_meta(
        self,
        *,
        status: str,
        record_count: int,
        source_states: Optional[Dict[str, Any]] = None,
        error_summary: Optional[str] = None,
        cache_mode: Optional[str] = None,
        payload_status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        preserve_last_success: bool = False,
    ) -> Dict[str, Any]:
        previous = self.load_seed_meta()
        attempted_at = utc_now_iso()
        last_success_at = previous.get("lastSuccessAt")
        if not preserve_last_success and str(status or "").strip().lower() in {"ok", "empty", "degraded"}:
            last_success_at = attempted_at
        payload = build_seed_meta_payload(
            panel_id="f1-trackside",
            namespace=self.seed_meta_namespace(),
            cache_key=self.seed_meta_cache_key(),
            service_name=SEED_META_SERVICE_NAME,
            expected_interval_seconds=self.interval_seconds,
            status=status,
            last_attempt_at=attempted_at,
            last_success_at=last_success_at,
            record_count=record_count,
            source_states=source_states,
            error_summary=error_summary,
            cache_mode=cache_mode,
            payload_status=payload_status,
            metadata=metadata,
        )
        payload["lastSuccessAt"] = last_success_at
        return self.seed_meta_store.store(self.seed_meta_namespace(), self.seed_meta_cache_key(), payload)

    def load_previous_payload(self) -> Dict[str, Any]:
        if getattr(self.snapshot_store, "backend", "sqlite") == "redis":
            return {}
        try:
            raw = self.redis_client.get(self.redis_key())
            if raw:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            print("[f1] WARN redis read failed", file=sys.stderr)
        stale = self.snapshot_store.get_stale(self.namespace(), self.cache_key())
        return stale if isinstance(stale, dict) else {}

    def build_payload(self) -> Dict[str, Any]:
        ctx = {
            "SETTINGS": self.settings,
            "app": _AppAdapter(),
            "requests": self.requests,
            "utc_now_iso": utc_now_iso,
        }
        return f1_runtime_service.fetch_live_f1_panel_payload(ctx, limit=self.limit)

    def store_payload(self, payload: Dict[str, Any]) -> None:
        ttl_seconds = self.ttl_seconds()
        publish_snapshot(snapshot_store=self.snapshot_store, namespace=self.namespace(), cache_key=self.cache_key(),
                         payload=payload, ttl_seconds=ttl_seconds, redis_client=self.redis_client,
                         redis_cache_key=self.redis_key())

    @seed_writer
    def run_once(self) -> Dict[str, Any]:
        previous = self.load_previous_payload()
        payload = self.build_payload()
        sources = payload.get("sources") or {"bwenewsRss": "unknown"}
        healthy_empty = (payload.get("status") == "empty" and bool(sources)
                         and all(state in {"ok", "empty"} for state in sources.values()))
        if previous and not _cards(payload) and not healthy_empty:
            retained = retained_snapshot(previous, sources=sources)
            retained["sourceErrors"] = payload.get("sourceErrors") or {}
            self.store_payload(retained)
            self.store_seed_meta(
                status="preserved",
                record_count=len(_cards(previous)),
                source_states=sources,
                error_summary="Preserved previous snapshot because F1 source refresh was not verified",
                cache_mode=previous.get("cacheMode"),
                payload_status=retained.get("status"),
                metadata={"result": "preserved"},
                preserve_last_success=True,
            )
            return {"status": "preserved", "payload": retained}

        card_count = len(_cards(payload))
        payload_status = str(payload.get("status") or "unknown").strip().lower()
        status = "empty" if healthy_empty else "ok" if payload_status == "ok" and card_count > 0 else "degraded" if card_count else "error"
        error_summary = None if status in {"ok", "empty"} else "F1 sources unavailable or partial"
        payload = {**payload, "cacheMode": "seeded"}
        self.store_payload(payload)
        self.store_seed_meta(
            status=status,
            record_count=card_count,
            source_states=payload.get("sources") or {"bwenewsRss": "ok" if card_count > 0 else "error"},
            error_summary=error_summary,
            cache_mode=payload.get("cacheMode"),
            payload_status=payload.get("status"),
            metadata={
                "result": "stored",
                "limit": self.limit,
                "rssUrlConfigured": bool(str(self.settings.f1_bwenews_rss_url or "").strip()),
            },
            preserve_last_success=status == "error",
        )
        return {"status": "stored", "payload": payload}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed F1 trackside panel snapshots into Redis and SQLite")
    parser.add_argument("--watch", action="store_true", help="Run continuously instead of once")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("POLYDATA_F1_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
        help="Seconds between refresh runs in watch mode",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=int(os.environ.get("POLYDATA_F1_LIMIT", DEFAULT_LIMIT)),
        help="Number of F1 cards to seed",
    )
    return parser


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    parser = build_arg_parser()
    args = parser.parse_args()
    settings = load_api_settings()
    watcher = F1Watcher(
        redis_url=settings.redis_url,
        redis_prefix=settings.redis_prefix,
        snapshot_sqlite_path=settings.snapshot_sqlite_path,
        settings=settings,
        limit=args.limit,
        interval_seconds=args.interval,
    )
    watcher.redis_client.ping()
    print(f"[f1] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        result = watcher.run_once()
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        return 0

    interval_seconds = max(60, int(args.interval or DEFAULT_INTERVAL_SECONDS))
    while True:
        try:
            result = watcher.run_once()
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            watcher.store_seed_meta(
                status="error",
                record_count=0,
                source_states={"bwenewsRss": "error"},
                error_summary=str(exc),
                preserve_last_success=True,
                metadata={"result": "exception"},
            )
            print(f"[f1] ERROR watch loop failed: {exc}", file=sys.stderr)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
