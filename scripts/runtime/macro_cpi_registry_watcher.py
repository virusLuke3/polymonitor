#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict

_scripts_root = Path(__file__).resolve().parents[1]
if str(_scripts_root) not in sys.path:
    sys.path.insert(0, str(_scripts_root))

import redis
import requests

from runtime.seed_meta import utc_now_iso
from runtime.seed_meta import redis_key as _redis_key
from runtime.redis_snapshot_store import seed_writer
from api.config import load_api_settings
from api.clients.source_transport import source_session
from api.clients.fred_csv import read_fred_text
from api.services import macro_cpi_registry_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, retained_snapshot, collection_delay, publish_snapshot
from runtime.macro_collection import MacroSourceCache, start_round, round_evidence, read_text
from runtime.redis_snapshot_store import create_snapshot_store as SnapshotStore
from runtime.telegram_panel_publish import publish_cached_panel_snapshot


DEFAULT_INTERVAL_SECONDS = 1800
SEED_META_NAMESPACE = "seed-meta:macro"
SEED_META_SERVICE_NAME = "polydata-macro-cpi-registry-seed.service"


class MacroCpiRegistryWatcher(MacroSourceCache):
    def __init__(self, *, redis_url: str, redis_prefix: str, snapshot_sqlite_path: str, settings: Any, interval_seconds: int) -> None:
        self.settings = settings
        self.redis_prefix = redis_prefix or ""
        self.interval_seconds = max(300, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2) if redis_url else None
        self.requests = source_session(requests)
        self.requests.trust_env = str(os.environ.get("POLYDATA_RUNTIME_TRUST_ENV", "0")).lower() in {"1", "true", "yes", "on"}
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)

    def ttl_seconds(self) -> int:
        return max(self.interval_seconds * 3, macro_cpi_registry_service.ttl_seconds({"SETTINGS": self.settings}))

    def namespace(self, panel_id: str) -> str:
        return macro_cpi_registry_service._snapshot_namespace(panel_id)

    def cache_key(self) -> str:
        return macro_cpi_registry_service.CACHE_KEY

    def redis_key(self, panel_id: str) -> str:
        return _redis_key(self.redis_prefix, self.namespace(panel_id), self.cache_key())

    def _http_text_get(self, url: str, **kwargs: Any) -> str:
        return read_text(self, url, **kwargs)

    def context(self) -> Dict[str, Any]:
        return {
            "SETTINGS": self.settings,
            "SNAPSHOT_STORE": self.snapshot_store,
            "get_cached_json": self._get_cached_json,
            "set_cached_json": self._set_cached_json,
            "utc_now_iso": utc_now_iso,
            "http_text_get": self._http_text_get,
            "fred_text_get": lambda url, **kwargs: read_fred_text(self.requests, url, deadline=getattr(self, "collection_deadline", None)),
        }

    def previous(self, panel_id: str) -> Dict[str, Any]:
        stale = self.snapshot_store.get_stale(self.namespace(panel_id), self.cache_key())
        if isinstance(stale, dict):
            return stale
        return self._get_cached_json(self.namespace(panel_id), self.cache_key()) or {}

    def store_payload(self, panel_id: str, payload: Dict[str, Any]) -> None:
        evidence = round_evidence(self)
        if evidence:
            payload = {**payload, "collectionBudget": evidence}
        ttl = self.ttl_seconds()
        publish_snapshot(snapshot_store=self.snapshot_store, namespace=self.namespace(panel_id),
                         cache_key=self.cache_key(), payload=payload, ttl_seconds=ttl,
                         redis_client=self.redis_client, redis_cache_key=self.redis_key(panel_id))

    def store_meta(self, panel_id: str, *, status: str, record_count: int, source_states: Dict[str, Any] | None = None, error_summary: str | None = None, preserve: bool = False, cache_mode: str | None = None, payload_status: str | None = None) -> None:
        previous = self.seed_meta_store.load(SEED_META_NAMESPACE, panel_id) or {}
        attempted = utc_now_iso()
        last_success = previous.get("lastSuccessAt") if preserve or status != "ok" else attempted
        payload = build_seed_meta_payload(
            panel_id=panel_id,
            namespace=SEED_META_NAMESPACE,
            cache_key=panel_id,
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
            metadata={"result": status},
        )
        payload["lastSuccessAt"] = last_success
        self.seed_meta_store.store(SEED_META_NAMESPACE, panel_id, payload)

    def run_panel(self, panel_id: str) -> Dict[str, Any]:
        previous = self.previous(panel_id)
        try:
            payload = macro_cpi_registry_service.build_macro_cpi_registry_payload({**self.context(), "previousRegistry": previous}, panel_id, limit=macro_cpi_registry_service.MAX_ITEM_LIMIT)
        except Exception as exc:
            if previous:
                self.store_payload(panel_id, retained_snapshot(previous))
                self.store_meta(panel_id, status="preserved", record_count=len(previous.get("items") or []), source_states={"registry": "error"}, error_summary=str(exc), preserve=True)
                return {"panelId": panel_id, "status": "preserved", "error": str(exc)}
            self.store_meta(panel_id, status="error", record_count=0, source_states={"registry": "error"}, error_summary=str(exc), preserve=True)
            return {"panelId": panel_id, "status": "error", "error": str(exc)}
        if previous and not payload.get("items"):
            self.store_payload(panel_id, retained_snapshot(previous))
            self.store_meta(panel_id, status="preserved", record_count=len(previous.get("items") or []), source_states=payload.get("sources"), error_summary="Preserved previous registry snapshot because new payload was empty", preserve=True)
            return {"panelId": panel_id, "status": "preserved"}
        payload = {**payload, "cacheMode": "redis-seed", "expectedIntervalSeconds": self.interval_seconds}
        self.store_payload(panel_id, payload)
        telegram_sent = publish_cached_panel_snapshot(panel_id, payload)
        status = "ok" if payload.get("status") == "ok" else str(payload.get("status") or "degraded")
        self.store_meta(panel_id, status=status, record_count=len(payload.get("items") or []), source_states=payload.get("sources"), cache_mode="redis-seed", payload_status=payload.get("status"))
        return {"panelId": panel_id, "status": "stored", "payloadStatus": payload.get("status"), "items": len(payload.get("items") or []), "telegramSent": telegram_sent}

    @seed_writer
    def run_once(self) -> Dict[str, Any]:
        start_round(self, 'macro_cpi_registry_round_budget_seconds', 450)
        results = [self.run_panel(panel_id) for panel_id in macro_cpi_registry_service.MACRO_CPI_REGISTRY_PANEL_IDS]
        status = "ok" if all(result.get("status") == "stored" and result.get("payloadStatus") == "ok" for result in results) else "degraded"
        return {"status": status, "results": results}


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    parser = argparse.ArgumentParser(description="Seed composed CPI macro registry panel snapshots into Redis and SQLite")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLYDATA_MACRO_CPI_REGISTRY_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    args = parser.parse_args()
    settings = load_api_settings()
    watcher = MacroCpiRegistryWatcher(redis_url=settings.redis_url, redis_prefix=settings.redis_prefix, snapshot_sqlite_path=settings.snapshot_sqlite_path, settings=settings, interval_seconds=args.interval)
    print(f"[macro-cpi-registry] panels={','.join(macro_cpi_registry_service.MACRO_CPI_REGISTRY_PANEL_IDS)} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        return 0
    failures = 0
    while True:
        started_at = time.monotonic()
        try:
            result = watcher.run_once()
            failures = 0 if result.get("status") == "ok" else failures + 1
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            failures += 1
            print(f"[macro-cpi-registry] ERROR {exc}", file=sys.stderr)
        time.sleep(collection_delay(watcher.interval_seconds, failures, time.monotonic() - started_at))


if __name__ == "__main__":
    raise SystemExit(main())
