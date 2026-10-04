#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone watcher for crypto funding panel snapshots."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
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

from api.config import load_api_settings
from api.services import crypto_funding_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload
from runtime.snapshot_store import SnapshotStore


DEFAULT_INTERVAL_SECONDS = 30
DEFAULT_LIMIT = crypto_funding_service.DEFAULT_CRYPTO_FUNDING_LIMIT
SEED_META_NAMESPACE = "seed-meta:crypto"
SEED_META_CACHE_KEY = "funding-watch"
SEED_META_SERVICE_NAME = "polydata-crypto-funding-seed.service"


class _LoggerAdapter:
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[crypto-funding] ERROR {message % args if args else message}", file=sys.stderr)


class _AppAdapter:
    logger = _LoggerAdapter()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{str(prefix or '')}{namespace}:{cache_key}"


class CryptoFundingWatcher:
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
            raise RuntimeError("POLYDATA_REDIS_URL is required for crypto funding watcher")
        self.settings = settings
        self.limit = max(1, int(limit or DEFAULT_LIMIT))
        self.interval_seconds = max(15, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_prefix = str(redis_prefix or "")
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)
        self.http_local = threading.local()
        self.http_sessions = []
        self.http_lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="funding-venue")
        self.market_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="funding-market")
        self.market_jobs = {}

    def ttl_seconds(self) -> int:
        configured = int(os.environ.get("POLYDATA_CRYPTO_FUNDING_SEED_TTL_SECONDS", "0") or 0)
        if configured > 0:
            return configured
        return max(30, self.interval_seconds * 3, int(self.settings.crypto_funding_watch_ttl_seconds or 15) * 4)

    def cache_key(self) -> str:
        return crypto_funding_service.build_crypto_funding_cache_key(self.settings, limit=self.limit)

    def namespace(self) -> str:
        return crypto_funding_service.CRYPTO_FUNDING_NAMESPACE

    def redis_key(self) -> str:
        return _redis_key(self.redis_prefix, self.namespace(), self.cache_key())

    def http_json_get(self, url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 12, headers: Optional[Dict[str, str]] = None) -> Any:
        session = getattr(self.http_local, "session", None)
        if session is None:
            session = requests.Session()
            session.trust_env = False
            self.http_local.session = session
            with self.http_lock:
                self.http_sessions.append(session)
        response = session.get(url, params=params, timeout=timeout, headers=headers)
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
            "SNAPSHOT_STORE": self.snapshot_store,
            "get_cached_json": self.get_cached_json,
            "set_cached_json": self.set_cached_json,
            "funding_executor": self.executor,
            "funding_market_executor": self.market_executor,
            "funding_market_jobs": self.market_jobs,
        }

    def get_cached_json(self, namespace: str, key: str) -> dict | None:
        raw = self.redis_client.get(_redis_key(self.redis_prefix, namespace, key))
        return json.loads(raw) if raw else None

    def set_cached_json(self, namespace: str, key: str, value: dict, ttl: int) -> None:
        self.redis_client.set(_redis_key(self.redis_prefix, namespace, key), json.dumps(value, allow_nan=False), ex=ttl)

    def close(self) -> None:
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.market_executor.shutdown(wait=True, cancel_futures=True)
        for session in self.http_sessions:
            session.close()

    def load_previous_payload(self) -> Dict[str, Any]:
        try:
            raw = self.redis_client.get(self.redis_key())
            if raw:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            print("[crypto-funding] WARN redis read failed", file=sys.stderr)
        stale = self.snapshot_store.get_stale(self.namespace(), self.cache_key())
        return stale if isinstance(stale, dict) else {}

    def store_payload(self, payload: Dict[str, Any]) -> None:
        ttl_seconds = self.ttl_seconds()
        self.snapshot_store.set(self.namespace(), self.cache_key(), payload, ttl_seconds)
        self.redis_client.set(self.redis_key(), json.dumps(payload, ensure_ascii=True, default=str), ex=ttl_seconds)

    def store_seed_meta(self, *, status: str, record_count: int, source_states: Dict[str, Any], error_summary: str | None, preserve_last_success: bool = False) -> None:
        previous = self.seed_meta_store.load(SEED_META_NAMESPACE, SEED_META_CACHE_KEY) or {}
        attempted_at = utc_now_iso()
        last_success_at = previous.get("lastSuccessAt")
        if not preserve_last_success and status in {"ok", "degraded", "preserved"}:
            last_success_at = attempted_at
        payload = build_seed_meta_payload(
            panel_id="crypto-funding-watch",
            namespace=SEED_META_NAMESPACE,
            cache_key=SEED_META_CACHE_KEY,
            service_name=SEED_META_SERVICE_NAME,
            expected_interval_seconds=self.interval_seconds,
            status=status,
            last_attempt_at=attempted_at,
            last_success_at=last_success_at,
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
        previous = self.load_previous_payload()
        try:
            payload = crypto_funding_service.fetch_live_crypto_funding_watch_payload(
                self.service_context(), limit=self.limit, previous=previous)
        except Exception as exc:
            # Publish the failure without moving the saved snapshot's clock.
            attempted_at = utc_now_iso()
            items = [{**quote, "acquisitionState": "retained"} for quote in previous.get("items", [])]
            by_id = {quote["id"]: quote for quote in items}
            payload = {**previous, "schemaVersion": 3, "kind": "crypto-funding",
                "generatedAt": previous.get("generatedAt"), "lastAttemptAt": attempted_at,
                "lastSuccessAt": previous.get("lastSuccessAt"), "status": "stale" if items else "unavailable",
                "sources": {"binance": "error", "bybit": "error"}, "items": items,
                "sourceDetails": {name: {**previous.get("sourceDetails", {}).get(name, {}),
                    "status": "error", "lastAttemptAt": attempted_at, "errorCode": type(exc).__name__}
                    for name in ("binance", "bybit")},
                "assets": [{**asset, "quotes": [by_id[q["id"]] for q in asset.get("quotes", []) if q["id"] in by_id],
                            "strongestFundingPercent8h": None, "consensusFundingPercent8h": None, "status": "stale"}
                           for asset in previous.get("assets", [])],
                "coverage": {**previous.get("coverage", {}), "succeeded": 0, "retained": len(items)},
                "errorCode": type(exc).__name__}
        payload["refreshIntervalSeconds"] = self.interval_seconds
        self.store_payload(payload)
        status = str(payload.get("status") or "unavailable")
        succeeded = int(payload.get("coverage", {}).get("succeeded", 0))
        self.store_seed_meta(status=status, record_count=len(payload.get("assets", [])),
            source_states=payload.get("sources", {}),
            error_summary=None if status == "ok" else "Some sources or qualifications are unavailable; usable quotes retained",
            preserve_last_success=succeeded <= 0)
        return {"status": status, "generatedAt": payload.get("generatedAt"),
                "assets": len(payload.get("assets", [])), "sources": payload.get("sources", {}),
                "succeeded": succeeded, "retained": payload.get("coverage", {}).get("retained", 0),
                "missing": payload.get("coverage", {}).get("missing", 0),
                "marketUniverse": payload.get("marketUniverse", {}).get("status")}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed crypto funding panel snapshots into Redis and SQLite")
    parser.add_argument("--watch", action="store_true", help="Run continuously instead of once")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLYDATA_CRYPTO_FUNDING_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    parser.add_argument("--limit", type=int, default=int(os.environ.get("POLYDATA_CRYPTO_FUNDING_LIMIT", DEFAULT_LIMIT)))
    return parser


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    args = build_arg_parser().parse_args()
    settings = load_api_settings()
    watcher = CryptoFundingWatcher(
        redis_url=settings.redis_url,
        redis_prefix=settings.redis_prefix,
        snapshot_sqlite_path=settings.snapshot_sqlite_path,
        settings=settings,
        limit=args.limit,
        interval_seconds=args.interval,
    )
    watcher.redis_client.ping()
    print(f"[crypto-funding] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    try:
        if not args.watch:
            print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
            return 0
        interval_seconds = max(15, int(args.interval or DEFAULT_INTERVAL_SECONDS))
        while True:
            started = time.monotonic()
            try:
                print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
            except KeyboardInterrupt:
                return 0
            except Exception as exc:
                watcher.store_seed_meta(status="error", record_count=0, source_states={"collector": "error"},
                    error_summary=type(exc).__name__, preserve_last_success=True)
                print(f"[crypto-funding] ERROR watch loop failed: {type(exc).__name__}", file=sys.stderr)
            time.sleep(max(1, interval_seconds - (time.monotonic() - started)))
    except KeyboardInterrupt:
        return 0
    finally:
        watcher.close()


if __name__ == "__main__":
    raise SystemExit(main())
