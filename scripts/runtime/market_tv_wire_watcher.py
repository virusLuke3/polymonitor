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

try:
    import redis
except ImportError:
    redis = None

from api.context import worker_application
from runtime.seed_meta import redis_key as _redis_key
from runtime.redis_snapshot_store import seed_writer
from api.clients.source_transport import source_session
from api.config import load_api_settings
from api.services import live_video_source_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload, retained_snapshot, utc_now_iso, publish_snapshot
from runtime.redis_snapshot_store import create_snapshot_store as SnapshotStore


DEFAULT_INTERVAL_SECONDS = 900
SEED_META_NAMESPACE = "seed-meta:content"
SEED_META_CACHE_KEY = "market-tv-wire"
SEED_META_SERVICE_NAME = "polydata-market-tv-wire-seed.service"
YOUTUBE_RSS_REFRESH_STATE_NAMESPACE = "state:content"
YOUTUBE_RSS_REFRESH_STATE_KEY = "market-tv-wire:youtube-rss-refresh"
DEFAULT_YOUTUBE_RSS_REFRESH_SECONDS = 86400


WORKER_APP = worker_application('market-tv-wire')


class MarketTvWireWatcher:
    def __init__(self, *, redis_url: str, redis_prefix: str, snapshot_sqlite_path: str, settings: Any, interval_seconds: int) -> None:
        self.settings = settings
        self.redis_prefix = redis_prefix or ""
        self.interval_seconds = max(60, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_client = (redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
                             if redis is not None and str(redis_url or "").strip() else None)
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)
        self.requests = source_session()
        trust_env = str(os.environ.get("POLYDATA_RUNTIME_TRUST_ENV", "0")).strip().lower() in {"1", "true", "yes", "on"}
        self.requests.trust_env = trust_env

    def namespace(self) -> str:
        return live_video_source_service.MARKET_TV_WIRE_SNAPSHOT_NAMESPACE

    def cache_key(self) -> str:
        return live_video_source_service.MARKET_TV_WIRE_CACHE_KEY

    def redis_key(self) -> str:
        return _redis_key(self.redis_prefix, self.namespace(), self.cache_key())

    def _http_text_get(self, url: str, *, timeout: int = 10, headers: Dict[str, str] | None = None) -> str:
        response = self.requests.get(url, timeout=max(3, min(15, int(timeout or 10))), headers=headers)
        response.raise_for_status()
        return response.text

    def _http_json_get(self, url: str, *, params: Dict[str, Any] | None = None, timeout: int = 10, headers: Dict[str, str] | None = None) -> Any:
        response = self.requests.get(url, params=params, timeout=max(3, min(15, int(timeout or 10))), headers=headers)
        response.raise_for_status()
        return response.json()

    def _youtube_rss_refresh_seconds(self) -> int:
        try:
            return max(3600, int(os.environ.get("POLYDATA_MARKET_YOUTUBE_RSS_REFRESH_SECONDS", DEFAULT_YOUTUBE_RSS_REFRESH_SECONDS)))
        except Exception:
            return DEFAULT_YOUTUBE_RSS_REFRESH_SECONDS

    def _youtube_rss_refresh_due(self) -> bool:
        if self.snapshot_store.get(YOUTUBE_RSS_REFRESH_STATE_NAMESPACE, YOUTUBE_RSS_REFRESH_STATE_KEY):
            return False
        if self.redis_client is not None:
            try:
                return not bool(self.redis_client.get(_redis_key(self.redis_prefix, YOUTUBE_RSS_REFRESH_STATE_NAMESPACE, YOUTUBE_RSS_REFRESH_STATE_KEY)))
            except Exception:
                pass
        return True

    def _mark_youtube_rss_refresh_attempted(self) -> None:
        publish_snapshot(
            snapshot_store=self.snapshot_store, namespace=YOUTUBE_RSS_REFRESH_STATE_NAMESPACE,
            cache_key=YOUTUBE_RSS_REFRESH_STATE_KEY, payload={"attemptedAt": utc_now_iso()},
            ttl_seconds=self._youtube_rss_refresh_seconds(), redis_client=self.redis_client,
            redis_cache_key=_redis_key(self.redis_prefix, YOUTUBE_RSS_REFRESH_STATE_NAMESPACE, YOUTUBE_RSS_REFRESH_STATE_KEY),
        )

    def context(self, *, youtube_rss_refresh_due: bool = False) -> Dict[str, Any]:
        return {
            "SETTINGS": self.settings,
            "app": WORKER_APP,
            "http_text_get": self._http_text_get,
            "http_json_get": self._http_json_get,
            "SNAPSHOT_STORE": self.snapshot_store,
            "get_cached_json": self.seed_meta_store.get,
            "set_cached_json": self.seed_meta_store.cache_source,
            "utc_now_iso": utc_now_iso,
            "market_tv_youtube_rss_fallback_enabled": youtube_rss_refresh_due,
            "market_tv_youtube_rss_refresh_existing": youtube_rss_refresh_due,
        }

    def previous(self) -> Dict[str, Any]:
        stale = self.snapshot_store.get_stale(self.namespace(), self.cache_key())
        if isinstance(stale, dict):
            return stale
        cached = self.seed_meta_store.get(self.namespace(), self.cache_key())
        if cached:
            return cached
        return {}

    def store_payload(self, payload: Dict[str, Any]) -> None:
        ttl = max(60, int(os.environ.get("POLYDATA_MARKET_TV_WIRE_TTL_SECONDS", live_video_source_service.MARKET_TV_WIRE_TTL_SECONDS)))
        publish_snapshot(
            snapshot_store=self.snapshot_store, namespace=self.namespace(),
            cache_key=self.cache_key(), payload=payload, ttl_seconds=ttl,
            redis_client=self.redis_client, redis_cache_key=self.redis_key(),
        )

    def store_meta(
        self,
        *,
        status: str,
        record_count: int,
        source_states: Dict[str, Any] | None = None,
        error_summary: str | None = None,
        preserve: bool = False,
        cache_mode: str | None = None,
        payload_status: str | None = None,
    ) -> None:
        prev = self.seed_meta_store.load(SEED_META_NAMESPACE, SEED_META_CACHE_KEY) or {}
        attempt = utc_now_iso()
        success = prev.get("lastSuccessAt")
        if not preserve and (status in {"ok", "empty"} or (status == "degraded" and record_count > 0)):
            success = attempt
        payload = build_seed_meta_payload(
            panel_id=SEED_META_CACHE_KEY,
            namespace=SEED_META_NAMESPACE,
            cache_key=SEED_META_CACHE_KEY,
            service_name=SEED_META_SERVICE_NAME,
            expected_interval_seconds=self.interval_seconds,
            status=status,
            last_attempt_at=attempt,
            last_success_at=success,
            record_count=record_count,
            source_states=source_states,
            error_summary=error_summary,
            cache_mode=cache_mode,
            payload_status=payload_status,
            metadata={"workerVersion": "v1", "gcpOnly": True},
        )
        self.seed_meta_store.store(SEED_META_NAMESPACE, SEED_META_CACHE_KEY, payload)

    def store_meta_fail_soft(self, **kwargs: Any) -> bool:
        try:
            self.store_meta(**kwargs)
            return True
        except Exception as exc:
            print(
                f"[market-tv-wire] WARN seed meta write failed: {exc.__class__.__name__}",
                file=sys.stderr,
            )
            return False

    @seed_writer
    def run_once(self) -> Dict[str, Any]:
        previous = self.previous()
        youtube_rss_refresh_due = self._youtube_rss_refresh_due()
        if youtube_rss_refresh_due:
            self._mark_youtube_rss_refresh_attempted()
        try:
            payload = live_video_source_service.build_market_tv_wire_payload(
                self.context(youtube_rss_refresh_due=youtube_rss_refresh_due),
                include_iptv=True,
            )
        except Exception as exc:
            if previous:
                self.store_payload(retained_snapshot(previous))
                self.store_meta(
                    status="preserved",
                    record_count=len(previous.get("items") or []),
                    source_states={"marketTvWire": {"status": "error"}},
                    error_summary=str(exc),
                    preserve=True,
                )
                return {"status": "preserved", "payload": previous, "error": str(exc)}
            self.store_meta(status="error", record_count=0, source_states={"marketTvWire": {"status": "error"}}, error_summary=str(exc), preserve=True)
            return {"status": "error", "error": str(exc)}

        if previous and not payload.get("items"):
            self.store_payload(retained_snapshot(previous))
            self.store_meta(
                status="preserved",
                record_count=len(previous.get("items") or []),
                source_states=payload.get("sources"),
                error_summary="Preserved previous snapshot because new market TV wire payload was empty",
                preserve=True,
            )
            return {"status": "preserved", "payload": previous}

        stored_payload = {**payload, "cacheMode": "seeded"}
        self.store_payload(stored_payload)
        payload_status = str(stored_payload.get("status") or "degraded")
        meta_status = "ok" if payload_status == "ok" else payload_status
        self.store_meta(
            status=meta_status,
            record_count=len(stored_payload.get("items") or []),
            source_states=stored_payload.get("sources"),
            error_summary="; ".join(stored_payload.get("errors") or []) or None,
            cache_mode="seeded",
            payload_status=payload_status,
        )
        return {"status": "stored", "payload": stored_payload}


def _result_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
    return {
        "status": result.get("status"),
        "payloadStatus": payload.get("status"),
        "cacheMode": payload.get("cacheMode"),
        "items": len(payload.get("items") or []),
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else None,
        "errors": payload.get("errors") or ([result.get("error")] if result.get("error") else []),
    }


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    parser = argparse.ArgumentParser(description="Seed Market TV Wire snapshots into Redis and SQLite")
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("POLYDATA_MARKET_TV_WIRE_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    args = parser.parse_args()
    settings = load_api_settings()
    watcher = MarketTvWireWatcher(
        redis_url=settings.redis_url,
        redis_prefix=settings.redis_prefix,
        snapshot_sqlite_path=settings.snapshot_sqlite_path,
        settings=settings,
        interval_seconds=args.interval,
    )
    print(f"[market-tv-wire] redis_key={watcher.redis_key()} sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        print(json.dumps(_result_summary(watcher.run_once()), ensure_ascii=False), file=sys.stderr)
        return 0
    while True:
        started_at = time.monotonic()
        try:
            print(json.dumps(_result_summary(watcher.run_once()), ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            watcher.store_meta_fail_soft(status="error", record_count=0, source_states={"marketTvWire": {"status": "error"}}, error_summary=str(exc), preserve=True)
            print(f"[market-tv-wire] ERROR {exc}", file=sys.stderr)
        # Probing the catalog can take minutes. Count that work toward the
        # refresh interval so each cycle does not drift by the probe duration.
        time.sleep(max(60, args.interval - (time.monotonic() - started_at)))


if __name__ == "__main__":
    raise SystemExit(main())
