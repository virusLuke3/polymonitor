#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed Polymarket macro market map snapshots into Redis and SQLite."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

_scripts_root = Path(__file__).resolve().parents[1]
if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))

try:
    import redis
except ImportError:
    redis = None

from runtime.redis_snapshot_store import seed_writer
from api.config import load_api_settings
from api.db_pool import build_api_connection_factory
from api.services import market_service, polymarket_macro_map_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, retained_snapshot, publish_snapshot
from runtime.macro_collection import start_round, round_evidence, read_text
from runtime.redis_snapshot_store import create_snapshot_store as SnapshotStore
from runtime.telegram_panel_publish import publish_cached_panel_snapshot


DEFAULT_INTERVAL_SECONDS = 180
SEED_META_NAMESPACE = "seed-meta:macro"
SEED_META_CACHE_KEY = "polymarket-macro-map"
SEED_META_SERVICE_NAME = "polydata-polymarket-macro-map-seed.service"


class _LoggerAdapter:
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[macro-map] ERROR {message % args if args else message}", file=sys.stderr)

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[macro-map] WARN {message % args if args else message}", file=sys.stderr)

    def info(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[macro-map] INFO {message % args if args else message}", file=sys.stderr)


class _AppAdapter:
    logger = _LoggerAdapter()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{str(prefix or '')}{namespace}:{cache_key}"


class PolymarketMacroMapWatcher:
    def __init__(
        self,
        *,
        redis_url: str,
        redis_prefix: str,
        snapshot_sqlite_path: str,
        settings: Any,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        self.settings = settings
        self.interval_seconds = max(60, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_prefix = str(redis_prefix or "")
        self.redis_client = (redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
                             if redis is not None and str(redis_url or "").strip() else None)
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)

    def namespace(self) -> str:
        return polymarket_macro_map_service.MACRO_MAP_SNAPSHOT_NAMESPACE

    def cache_key(self) -> str:
        return polymarket_macro_map_service.MACRO_MAP_CACHE_KEY

    def redis_key(self) -> str:
        return _redis_key(self.redis_prefix, self.namespace(), self.cache_key())

    def ttl_seconds(self) -> int:
        return max(60, int(getattr(self.settings, "polymarket_macro_map_ttl_seconds", 180) or 180))

    def service_context(self) -> Dict[str, Any]:
        return {
            "SETTINGS": self.settings,
            "app": _AppAdapter(),
            "read_market_catalog": self.read_market_catalog,
            "utc_now_iso": utc_now_iso,
        }

    def read_market_catalog(self, *, terms: tuple[str, ...]) -> Dict[str, Any]:
        database = self.settings.database
        connector = build_api_connection_factory(database.connect, lambda: database.backend)
        def query(sql, params=()):
            deadline = getattr(self, "collection_deadline", None)
            # Existing connection timeout is 8s and statement timeout is 1s.
            if deadline is not None and time.monotonic() + 10 > deadline:
                raise TimeoutError("macro catalog round budget exhausted")
            result = market_service.read_query(connector, database.sqlite_path, sql, params)
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError("macro catalog round budget exhausted")
            return result
        try:
            return polymarket_macro_map_service.read_macro_market_catalog(
                query,
                terms=terms, backend=database.backend)
        finally:
            # The existing host-wide four-connection ceiling still applies.
            # Do not reserve an idle API connection between 180-second runs.
            connector.close()

    def load_previous_payload(self) -> Dict[str, Any]:
        stale = self.snapshot_store.get_stale(self.namespace(), self.cache_key())
        return stale if isinstance(stale, dict) else {}

    def store_payload(self, payload: Dict[str, Any]) -> None:
        evidence = round_evidence(self)
        if evidence:
            payload = {**payload, "collectionBudget": evidence}
        ttl_seconds = self.ttl_seconds()
        publish_snapshot(
            snapshot_store=self.snapshot_store, namespace=self.namespace(),
            cache_key=self.cache_key(), payload=payload, ttl_seconds=ttl_seconds,
            redis_client=self.redis_client, redis_cache_key=self.redis_key(),
        )

    def store_seed_meta(
        self,
        *,
        status: str,
        record_count: int,
        source_states: Dict[str, Any] | None = None,
        error_summary: str | None = None,
        cache_mode: str | None = None,
        payload_status: str | None = None,
        preserve_last_success: bool = False,
    ) -> Dict[str, Any]:
        previous = self.seed_meta_store.load(SEED_META_NAMESPACE, SEED_META_CACHE_KEY) or {}
        attempted_at = utc_now_iso()
        last_success_at = previous.get("lastSuccessAt")
        if not preserve_last_success and (status == "ok" or (status == "degraded" and record_count > 0)):
            last_success_at = attempted_at
        payload = build_seed_meta_payload(
            panel_id=SEED_META_CACHE_KEY,
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
            cache_mode=cache_mode,
            payload_status=payload_status,
            metadata={"result": status},
        )
        return self.seed_meta_store.store(SEED_META_NAMESPACE, SEED_META_CACHE_KEY, payload)

    def store_seed_meta_fail_soft(self, **kwargs: Any) -> bool:
        try:
            self.store_seed_meta(**kwargs)
            return True
        except Exception as exc:
            print(f"[polymarket_macro_map] WARN seed meta write failed: {exc.__class__.__name__}", file=sys.stderr)
            return False

    @seed_writer
    def run_once(self) -> Dict[str, Any]:
        start_round(self, 'polymarket_macro_map_round_budget_seconds', 30)
        previous = self.load_previous_payload()
        try:
            payload = polymarket_macro_map_service.build_polymarket_macro_map_payload(self.service_context())
        except Exception as exc:
            error = type(exc).__name__
            if previous:
                self.store_payload(retained_snapshot(previous))
                self.store_seed_meta(
                    status="preserved",
                    record_count=len(previous.get("items") or []),
                    source_states={"marketCatalog": "error"},
                    error_summary=error,
                    cache_mode=previous.get("cacheMode"),
                    payload_status=previous.get("status"),
                    preserve_last_success=True,
                )
                return {"status": "preserved", "payload": previous, "error": error}
            self.store_seed_meta(status="error", record_count=0, source_states={"marketCatalog": "error"}, error_summary=error, preserve_last_success=True)
            return {"status": "error", "error": error}

        record_count = len(payload.get("items") or [])
        if previous and record_count <= 0:
            self.store_payload(retained_snapshot(previous))
            self.store_seed_meta(
                status="preserved",
                record_count=len(previous.get("items") or []),
                source_states=payload.get("sources"),
                error_summary="Preserved previous snapshot because new macro map payload was empty",
                cache_mode=previous.get("cacheMode"),
                payload_status=previous.get("status"),
                preserve_last_success=True,
            )
            return {"status": "preserved", "payload": previous}

        payload = {**payload, "cacheMode": "seeded"}
        self.store_payload(payload)
        telegram_sent = publish_cached_panel_snapshot(SEED_META_CACHE_KEY, payload)
        status = "ok" if record_count > 0 and payload.get("status") == "ok" else str(payload.get("status") or "degraded")
        self.store_seed_meta(
            status=status,
            record_count=record_count,
            source_states=payload.get("sources"),
            error_summary=None if record_count else "Macro map payload contained no items",
            cache_mode=payload.get("cacheMode"),
            payload_status=payload.get("status"),
        )
        return {"status": "stored", "payload": payload, "telegramSent": telegram_sent}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed Polymarket macro market map snapshots into Redis and SQLite")
    parser.add_argument("--watch", action="store_true", help="Run continuously instead of once")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("POLYDATA_MACRO_MARKET_MAP_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
        help="Seconds between refresh runs in watch mode",
    )
    return parser


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    args = build_arg_parser().parse_args()
    settings = load_api_settings()
    watcher = PolymarketMacroMapWatcher(
        redis_url=settings.redis_url,
        redis_prefix=settings.redis_prefix,
        snapshot_sqlite_path=settings.snapshot_sqlite_path,
        settings=settings,
        interval_seconds=args.interval,
    )
    print(f"[macro-map] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        return 0

    interval_seconds = max(60, int(args.interval or DEFAULT_INTERVAL_SECONDS))
    while True:
        started_at = time.monotonic()
        try:
            print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            watcher.store_seed_meta_fail_soft(
                status="error",
                record_count=0,
                source_states={"marketCatalog": "error"},
                error_summary=type(exc).__name__,
                preserve_last_success=True,
            )
            print(f"[macro-map] ERROR watch loop failed: {type(exc).__name__}", file=sys.stderr)
        time.sleep(max(30, interval_seconds - (time.monotonic() - started_at)))


if __name__ == "__main__":
    raise SystemExit(main())
