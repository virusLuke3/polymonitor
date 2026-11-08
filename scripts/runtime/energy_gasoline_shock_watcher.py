#!/usr/bin/env python3
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
import requests
import xlrd

from api.config import load_api_settings
from api.services import energy_gasoline_shock_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, publish_snapshot, retained_snapshot
from runtime.snapshot_store import SnapshotStore

DEFAULT_INTERVAL_SECONDS = 21600
SEED_META_NAMESPACE = "seed-meta:macro"
SEED_META_CACHE_KEY = "energy-gasoline-shock"
SEED_META_SERVICE_NAME = "polydata-energy-gasoline-shock-seed.service"


class _Logger:
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[energy-shock] ERROR {message % args if args else message}", file=sys.stderr)


class _App:
    logger = _Logger()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{prefix or ''}{namespace}:{cache_key}"


class EnergyGasolineShockWatcher:
    def __init__(self, *, redis_url: str, redis_prefix: str, snapshot_sqlite_path: str, settings: Any, interval_seconds: int) -> None:
        self.settings = settings
        self.redis_prefix = redis_prefix or ""
        self.interval_seconds = max(1800, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_client = (redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
                             if redis is not None and str(redis_url or "").strip() else None)
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)
        self.requests = requests.Session()
        self.requests.trust_env = False

    def namespace(self) -> str:
        return energy_gasoline_shock_service.ENERGY_SHOCK_SNAPSHOT_NAMESPACE

    def cache_key(self) -> str:
        return energy_gasoline_shock_service.ENERGY_SHOCK_CACHE_KEY

    def redis_key(self) -> str:
        return _redis_key(self.redis_prefix, self.namespace(), self.cache_key())

    def ttl_seconds(self) -> int:
        return max(1800, int(getattr(self.settings, "energy_shock_ttl_seconds", 21600) or 21600))

    def _http_bytes_get(self, url: str, *, timeout: int = 18, headers: Dict[str, str] | None = None) -> bytes:
        response = self.requests.get(url, timeout=timeout, headers=headers)
        response.raise_for_status()
        return response.content

    def context(self) -> Dict[str, Any]:
        return {
            "SETTINGS": self.settings,
            "app": _App(),
            "http_bytes_get": self._http_bytes_get,
            "SNAPSHOT_STORE": self.snapshot_store,
            "get_cached_json": self._get_cached_json,
            "set_cached_json": self._set_cached_json,
            "utc_now_iso": utc_now_iso,
            "xlrd": xlrd,
        }

    def _get_cached_json(self, namespace: str, cache_key: str) -> Dict[str, Any] | None:
        cached = self.snapshot_store.get(namespace, cache_key)
        if isinstance(cached, dict):
            return cached
        if self.redis_client is None:
            return None
        try:
            raw = self.redis_client.get(_redis_key(self.redis_prefix, namespace, cache_key))
            payload = json.loads(str(raw)) if raw else None
            return payload if isinstance(payload, dict) else None
        except Exception:
            return None

    def _set_cached_json(self, namespace: str, cache_key: str, payload: Dict[str, Any], ttl: int) -> None:
        # Source caches are best effort; formal snapshots use store_payload.
        try:
            self.snapshot_store.set(namespace, cache_key, payload, ttl)
        except Exception:
            pass
        if self.redis_client is not None:
            try:
                self.redis_client.set(_redis_key(self.redis_prefix, namespace, cache_key), json.dumps(payload, ensure_ascii=True, default=str), ex=ttl)
            except Exception:
                pass

    def previous(self) -> Dict[str, Any]:
        stale = self.snapshot_store.get_stale(self.namespace(), self.cache_key())
        if isinstance(stale, dict):
            return stale
        cached = self._get_cached_json(self.namespace(), self.cache_key())
        if cached:
            return cached
        return {}

    def store_payload(self, payload: Dict[str, Any]) -> None:
        ttl = self.ttl_seconds()
        publish_snapshot(
            snapshot_store=self.snapshot_store, namespace=self.namespace(),
            cache_key=self.cache_key(), payload=payload, ttl_seconds=ttl,
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
            metadata={"result": status},
        )
        self.seed_meta_store.store(SEED_META_NAMESPACE, SEED_META_CACHE_KEY, payload)

    def store_meta_fail_soft(self, **kwargs: Any) -> bool:
        try:
            self.store_meta(**kwargs)
            return True
        except Exception as exc:
            print(f"[energy_gasoline_shock] WARN seed meta write failed: {exc.__class__.__name__}", file=sys.stderr)
            return False

    def run_once(self) -> Dict[str, Any]:
        previous = self.previous()
        try:
            payload = energy_gasoline_shock_service.build_energy_gasoline_shock_payload(self.context())
        except Exception as exc:
            if previous:
                self.store_payload(retained_snapshot(previous))
                self.store_meta(status="preserved", record_count=len(previous.get("items") or []), source_states={"eia": "error"}, error_summary=str(exc), preserve=True)
                return {"status": "preserved", "payload": previous, "error": str(exc)}
            self.store_meta(status="error", record_count=0, source_states={"eia": "error"}, error_summary=str(exc), preserve=True)
            return {"status": "error", "error": str(exc)}
        if previous and not payload.get("items"):
            self.store_payload(retained_snapshot(previous))
            self.store_meta(status="preserved", record_count=len(previous.get("items") or []), source_states=payload.get("sources"), error_summary="Preserved previous snapshot because new energy payload was empty", preserve=True)
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
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLYDATA_ENERGY_SHOCK_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    args = parser.parse_args()
    settings = load_api_settings()
    watcher = EnergyGasolineShockWatcher(redis_url=settings.redis_url, redis_prefix=settings.redis_prefix, snapshot_sqlite_path=settings.snapshot_sqlite_path, settings=settings, interval_seconds=args.interval)
    print(f"[energy-shock] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        return 0
    while True:
        try:
            print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            watcher.store_meta_fail_soft(status="error", record_count=0, source_states={"eia": "error"}, error_summary=str(exc), preserve=True)
            print(f"[energy-shock] ERROR {exc}", file=sys.stderr)
        time.sleep(max(1800, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
