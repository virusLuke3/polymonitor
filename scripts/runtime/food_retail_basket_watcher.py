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

from api.context import worker_application
from runtime.seed_meta import utc_now_iso
from runtime.seed_meta import redis_key as _redis_key
from runtime.redis_snapshot_store import seed_writer
from api.config import load_api_settings
from api.clients.source_transport import source_session
from api.clients.fred_csv import read_fred_text
from api.services import food_retail_basket_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, retained_snapshot, collection_delay, publish_snapshot
from runtime.macro_collection import MacroSourceCache, start_round, round_evidence, read_text
from runtime.redis_snapshot_store import create_snapshot_store as SnapshotStore

DEFAULT_INTERVAL_SECONDS = 21600
SEED_META_NAMESPACE = "seed-meta:macro"
SEED_META_CACHE_KEY = "food-retail-basket-pressure"
SEED_META_SERVICE_NAME = "polydata-food-retail-basket-seed.service"


WORKER_APP = worker_application('food-basket')


class FoodRetailBasketWatcher(MacroSourceCache):
    def __init__(self, *, redis_url: str, redis_prefix: str, snapshot_sqlite_path: str, settings: Any, interval_seconds: int) -> None:
        self.settings = settings
        self.redis_prefix = redis_prefix or ""
        self.interval_seconds = max(1800, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2) if redis_url else None
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)
        self.requests = source_session(requests)
        self.requests.trust_env = str(os.environ.get("POLYDATA_RUNTIME_TRUST_ENV", "0")).lower() in {"1", "true", "yes", "on"}

    def namespace(self) -> str:
        return food_retail_basket_service.FOOD_BASKET_SNAPSHOT_NAMESPACE

    def cache_key(self) -> str:
        return food_retail_basket_service.FOOD_BASKET_CACHE_KEY

    def redis_key(self) -> str:
        return _redis_key(self.redis_prefix, self.namespace(), self.cache_key())

    def _http_text_get(self, url: str, *, timeout: int = 15, headers: Dict[str, str] | None = None) -> str:
        return read_text(self, url, timeout=timeout, headers=headers)

    def context(self) -> Dict[str, Any]:
        return {
            "SETTINGS": self.settings,
            "app": WORKER_APP,
            "http_text_get": self._http_text_get,
            "fred_text_get": lambda url, **kwargs: read_fred_text(self.requests, url, deadline=getattr(self, "collection_deadline", None)),
            "SNAPSHOT_STORE": self.snapshot_store,
            "get_cached_json": self._get_cached_json,
            "set_cached_json": self._set_cached_json,
            "utc_now_iso": utc_now_iso,
        }

    def previous(self) -> Dict[str, Any]:
        stale = self.snapshot_store.get_stale(self.namespace(), self.cache_key())
        if isinstance(stale, dict):
            return stale
        return self._get_cached_json(self.namespace(), self.cache_key()) or {}

    def store_payload(self, payload: Dict[str, Any]) -> None:
        evidence = round_evidence(self)
        if evidence:
            payload = {**payload, "collectionBudget": evidence}
        ttl = max(1800, int(getattr(self.settings, "food_basket_ttl_seconds", 21600) or 21600))
        publish_snapshot(snapshot_store=self.snapshot_store, namespace=self.namespace(),
                         cache_key=self.cache_key(), payload=payload, ttl_seconds=ttl,
                         redis_client=self.redis_client, redis_cache_key=self.redis_key())

    def store_meta(self, *, status: str, record_count: int, source_states: Dict[str, Any] | None = None, error_summary: str | None = None, preserve: bool = False, cache_mode: str | None = None, payload_status: str | None = None) -> None:
        prev = self.seed_meta_store.load(SEED_META_NAMESPACE, SEED_META_CACHE_KEY) or {}
        attempt = utc_now_iso()
        success = prev.get("lastSuccessAt") if preserve or status != "ok" else attempt
        payload = build_seed_meta_payload(panel_id=SEED_META_CACHE_KEY, namespace=SEED_META_NAMESPACE, cache_key=SEED_META_CACHE_KEY, service_name=SEED_META_SERVICE_NAME, expected_interval_seconds=self.interval_seconds, status=status, last_attempt_at=attempt, last_success_at=success, record_count=record_count, source_states=source_states, error_summary=error_summary, cache_mode=cache_mode, payload_status=payload_status, metadata={"result": status})
        payload["lastSuccessAt"] = success
        self.seed_meta_store.store(SEED_META_NAMESPACE, SEED_META_CACHE_KEY, payload)

    @seed_writer
    def run_once(self) -> Dict[str, Any]:
        start_round(self, 'food_basket_round_budget_seconds', 720)
        previous = self.previous()
        try:
            payload = food_retail_basket_service.build_food_retail_basket_payload(self.context())
        except Exception as exc:
            if previous:
                self.store_payload(retained_snapshot(previous))
                self.store_meta(status="preserved", record_count=len(previous.get("items") or []), source_states={"fred": "error"}, error_summary=str(exc), preserve=True)
                return {"status": "preserved", "payload": previous, "error": str(exc)}
            self.store_meta(status="error", record_count=0, source_states={"fred": "error"}, error_summary=str(exc), preserve=True)
            return {"status": "error", "error": str(exc)}
        if previous and not payload.get("items"):
            self.store_payload(retained_snapshot(previous))
            self.store_meta(status="preserved", record_count=len(previous.get("items") or []), source_states=payload.get("sources"), error_summary="Preserved previous snapshot because new food basket payload was empty", preserve=True)
            return {"status": "preserved", "payload": previous}
        payload = {**payload, "cacheMode": "seeded"}
        self.store_payload(payload)
        status = "ok" if payload.get("status") == "ok" else str(payload.get("status") or "degraded")
        self.store_meta(status=status, record_count=len(payload.get("items") or []), source_states=payload.get("sources"), cache_mode="seeded", payload_status=payload.get("status"))
        return {"status": "stored", "payload": payload}


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLYDATA_FOOD_BASKET_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    args = parser.parse_args()
    settings = load_api_settings()
    watcher = FoodRetailBasketWatcher(redis_url=settings.redis_url, redis_prefix=settings.redis_prefix, snapshot_sqlite_path=settings.snapshot_sqlite_path, settings=settings, interval_seconds=args.interval)
    print(f"[food-basket] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        return 0
    failures = 0
    while True:
        started_at = time.monotonic()
        try:
            result = watcher.run_once()
            healthy = result.get("status") == "ok" or (result.get("status") == "stored" and result.get("payload", {}).get("status") == "ok")
            failures = 0 if healthy else failures + 1
            print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            failures += 1
            watcher.store_meta(status="error", record_count=0, source_states={"fred": "error"}, error_summary=str(exc), preserve=True)
            print(f"[food-basket] ERROR {exc}", file=sys.stderr)
        time.sleep(collection_delay(watcher.interval_seconds, failures, time.monotonic() - started_at))


if __name__ == "__main__":
    raise SystemExit(main())
