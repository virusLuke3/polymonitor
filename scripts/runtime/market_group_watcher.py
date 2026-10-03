#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Standalone watcher for fixed market group snapshots."""

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

from api.clients import market_data_client
from api.commodity_symbols import COMMODITY_SYMBOLS
from api.clients.http_client import http_json_get
from api.config import load_api_settings
from api.services import runtime_service
from api.services import commodities_service
from runtime.seed_meta import SeedMetaStore, build_seed_meta_payload
from runtime.snapshot_store import SnapshotStore


DEFAULT_INTERVAL_SECONDS = 60
SEED_META_NAMESPACE = "seed-meta:markets"
SEED_META_SERVICE_NAME = "polydata-market-group-seed.service"

CRYPTO_SYMBOLS = [
    ("btc", "BTC", "BTC-USD"),
    ("eth", "ETH", "ETH-USD"),
    ("sol", "SOL", "SOL-USD"),
    ("doge", "DOGE", "DOGE-USD"),
    ("bnb", "BNB", "BNB-USD"),
    ("xrp", "XRP", "XRP-USD"),
    ("ada", "ADA", "ADA-USD"),
    ("avax", "AVAX", "AVAX-USD"),
    ("link", "LINK", "LINK-USD"),
    ("ltc", "LTC", "LTC-USD"),
    ("dot", "DOT", "DOT-USD"),
    ("trx", "TRX", "TRX-USD"),
    ("bch", "BCH", "BCH-USD"),
]

CRYPTO_COINGECKO_IDS = {
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
    "SOL-USD": "solana",
    "DOGE-USD": "dogecoin",
    "BNB-USD": "binancecoin",
    "XRP-USD": "ripple",
    "ADA-USD": "cardano",
    "AVAX-USD": "avalanche-2",
    "LINK-USD": "chainlink",
    "LTC-USD": "litecoin",
    "DOT-USD": "polkadot",
    "TRX-USD": "tron",
    "BCH-USD": "bitcoin-cash",
}


class _LoggerAdapter:
    def exception(self, message: str, *args: Any, **kwargs: Any) -> None:
        print(f"[market-group] ERROR {message % args if args else message}", file=sys.stderr)


class _AppAdapter:
    logger = _LoggerAdapter()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _redis_key(prefix: str, namespace: str, cache_key: str) -> str:
    return f"{str(prefix or '')}{namespace}:{cache_key}"


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


class MarketGroupWatcher:
    def __init__(
        self,
        *,
        redis_url: str,
        redis_prefix: str,
        snapshot_sqlite_path: str,
        settings: Any,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    ) -> None:
        if redis is None:
            raise RuntimeError("redis package is required. Install scripts/requirements.txt")
        if requests is None:
            raise RuntimeError("requests package is required. Install scripts/requirements.txt")
        if not str(redis_url or "").strip():
            raise RuntimeError("POLYDATA_REDIS_URL is required for market group watcher")
        self.settings = settings
        self.interval_seconds = max(30, int(interval_seconds or DEFAULT_INTERVAL_SECONDS))
        self.redis_prefix = str(redis_prefix or "")
        self.redis_client = redis.from_url(redis_url, decode_responses=True)
        self.snapshot_store = SnapshotStore(snapshot_sqlite_path)
        self.seed_meta_store = SeedMetaStore(redis_client=self.redis_client, redis_prefix=self.redis_prefix, snapshot_store=self.snapshot_store)
        self.requests = requests.Session()
        self.requests.trust_env = False
        self._runtime_cache: Dict[str, Dict[str, Any]] = {}

    def ttl_seconds(self, kind: str) -> int:
        configured = int(os.environ.get("POLYDATA_MARKET_GROUP_SEED_TTL_SECONDS", "0") or 0)
        if configured > 0:
            return configured
        if kind == "crypto":
            return max(30, self.interval_seconds * 2)
        return max(300, self.interval_seconds * 3, int(self.settings.finance_runtime_ttl_seconds or 300))

    def service_context(self) -> Dict[str, Any]:
        return {
            "SETTINGS": self.settings,
            "FINANCE_RUNTIME_TTL_SECONDS": self.settings.finance_runtime_ttl_seconds,
            "CRYPTO_COINGECKO_IDS": CRYPTO_COINGECKO_IDS,
            "app": _AppAdapter(),
            "requests": self.requests,
            "_safe_float": _safe_float,
            "http_json_get": lambda url, params=None, timeout=12, headers=None: http_json_get(
                {"requests": self.requests},
                url,
                params=params,
                timeout=timeout,
                headers=headers,
            ),
            "get_yahoo_market_snapshot": lambda symbol, interval="30m", range_name="5d", ttl_seconds=None: market_data_client.get_yahoo_market_snapshot(
                {
                    "SETTINGS": self.settings,
                    "FINANCE_RUNTIME_TTL_SECONDS": self.settings.finance_runtime_ttl_seconds,
                    "requests": self.requests,
                    "_safe_float": _safe_float,
                    "get_cached_runtime_payload": self.get_cached_runtime_payload,
                    "set_cached_runtime_payload": self.set_cached_runtime_payload,
                },
                symbol,
                interval=interval,
                range_name=range_name,
                ttl_seconds=ttl_seconds,
            ),
            "utc_now_iso": utc_now_iso,
        }

    def get_cached_runtime_payload(self, namespace: str, cache_key: str) -> Any:
        composite_key = f"{namespace}:{cache_key}"
        cached = self._runtime_cache.get(composite_key)
        if not cached:
            return None
        if float(cached.get("expires_at") or 0.0) <= time.monotonic():
            self._runtime_cache.pop(composite_key, None)
            return None
        return cached.get("payload")

    def set_cached_runtime_payload(self, namespace: str, cache_key: str, payload: Any, ttl_seconds: int) -> Any:
        self._runtime_cache[f"{namespace}:{cache_key}"] = {
            "payload": payload,
            "expires_at": time.monotonic() + max(1, int(ttl_seconds)),
        }
        return payload

    def load_previous_payload(self, namespace: str, cache_key: str) -> Dict[str, Any]:
        try:
            raw = self.redis_client.get(_redis_key(self.redis_prefix, namespace, cache_key))
            if raw:
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    return payload
        except Exception:
            print(f"[market-group] WARN redis read failed namespace={namespace}", file=sys.stderr)
        stale = self.snapshot_store.get_stale(namespace, cache_key)
        return stale if isinstance(stale, dict) else {}

    def store_payload(self, namespace: str, cache_key: str, payload: Dict[str, Any], *, kind: str) -> None:
        ttl_seconds = self.ttl_seconds(kind)
        self.snapshot_store.set(namespace, cache_key, payload, ttl_seconds)
        self.redis_client.set(_redis_key(self.redis_prefix, namespace, cache_key), json.dumps(payload, ensure_ascii=True, default=str), ex=ttl_seconds)

    def store_seed_meta(self, *, panel_id: str, status: str, record_count: int, source_states: Dict[str, Any], error_summary: str | None) -> None:
        previous = self.seed_meta_store.load(SEED_META_NAMESPACE, panel_id) or {}
        attempted_at = utc_now_iso()
        last_success_at = previous.get("lastSuccessAt")
        if status in {"ok", "degraded"} and source_states.get("acquired", record_count) > 0:
            last_success_at = attempted_at
        payload = build_seed_meta_payload(
            panel_id=panel_id,
            namespace=SEED_META_NAMESPACE,
            cache_key=panel_id,
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
            metadata={"result": "stored"},
        )
        # The common builder defaults an absent success clock to the attempt;
        # a failed first scan must keep its success clock explicitly unknown.
        payload["lastSuccessAt"] = last_success_at
        self.seed_meta_store.store(SEED_META_NAMESPACE, panel_id, payload)

    def run_component(self, *, panel_id: str, kind: str, items: list[tuple[str, str, str]]) -> Dict[str, Any]:
        namespace = f"snapshot:markets:{kind}"
        cache_key = runtime_service.build_market_group_cache_key(items, kind=kind)
        previous = self.load_previous_payload(namespace, cache_key)
        try:
            payload = runtime_service.fetch_live_market_group_payload(self.service_context(), items, kind=kind)
        except Exception as exc:
            if kind == "commodities":
                payload = commodities_service.merge_snapshot({"items": [], "generatedAt": utc_now_iso()}, previous, items, utc_now_iso())
                payload["error"] = str(exc)
                self.store_payload(namespace, cache_key, {**payload, "cacheMode": "seeded"}, kind=kind)
                self.store_seed_meta(panel_id=panel_id, status="degraded", record_count=len(payload["items"]),
                                     source_states={kind: "error", "acquired": 0}, error_summary=str(exc))
                return {"status": "degraded", "recordCount": len(payload["items"])}
            if previous:
                self.store_payload(namespace, cache_key, previous, kind=kind)
                status = "preserved"
                error_summary = str(exc)
                record_count = len(previous.get("items") or [])
            else:
                status = "error"
                error_summary = str(exc)
                record_count = 0
            self.store_seed_meta(panel_id=panel_id, status=status, record_count=record_count, source_states={kind: status}, error_summary=error_summary)
            return {"status": status, "error": error_summary, "recordCount": record_count}

        if kind == "commodities":
            payload = commodities_service.merge_snapshot(payload, previous, items, utc_now_iso())
            payload["refreshIntervalSeconds"] = self.interval_seconds
        record_count = len(payload.get("items") or [])
        if previous and record_count <= 0 and kind != "commodities":
            self.store_payload(namespace, cache_key, previous, kind=kind)
            self.store_seed_meta(
                panel_id=panel_id,
                status="preserved",
                record_count=len(previous.get("items") or []),
                source_states={kind: "empty"},
                error_summary=f"Preserved previous {kind} snapshot because new payload was empty",
            )
            return {"status": "preserved", "recordCount": len(previous.get("items") or [])}

        payload = {**payload, "cacheMode": "seeded"}
        self.store_payload(namespace, cache_key, payload, kind=kind)
        status = payload.get("status", "ok") if record_count > 0 else "degraded"
        self.store_seed_meta(
            panel_id=panel_id,
            status=status,
            record_count=record_count,
            source_states={kind: status, "acquired": (payload.get("coverage") or {}).get("succeeded", record_count)},
            error_summary=payload.get("error") or (None if record_count else f"{kind} payload contained no items"),
        )
        return {"status": status, "recordCount": record_count}

    def run_once(self) -> Dict[str, Any]:
        return {
            "commodities-watch": self.run_component(panel_id="commodities-watch", kind="commodities", items=COMMODITY_SYMBOLS),
            "crypto-watch": self.run_component(panel_id="crypto-watch", kind="crypto", items=CRYPTO_SYMBOLS),
        }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed fixed market group snapshots into Redis and SQLite")
    parser.add_argument("--watch", action="store_true", help="Run continuously instead of once")
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("POLYDATA_MARKET_GROUP_WATCH_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)),
        help="Seconds between refresh runs in watch mode",
    )
    return parser


def main() -> int:
    from runtime.environment import load_environment
    load_environment()
    args = build_arg_parser().parse_args()
    settings = load_api_settings()
    watcher = MarketGroupWatcher(
        redis_url=settings.redis_url,
        redis_prefix=settings.redis_prefix,
        snapshot_sqlite_path=settings.snapshot_sqlite_path,
        settings=settings,
        interval_seconds=args.interval,
    )
    watcher.redis_client.ping()
    print(f"[market-group] sqlite={settings.snapshot_sqlite_path}", file=sys.stderr)
    if not args.watch:
        print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        return 0
    interval_seconds = max(30, int(args.interval or DEFAULT_INTERVAL_SECONDS))
    while True:
        started_at = time.monotonic()
        try:
            print(json.dumps(watcher.run_once(), ensure_ascii=False), file=sys.stderr)
        except KeyboardInterrupt:
            return 0
        except Exception as exc:
            print(f"[market-group] ERROR watch loop failed: {exc}", file=sys.stderr)
        # Start-to-start cadence; slow sources still get a minimum cooldown.
        time.sleep(max(5, interval_seconds - (time.monotonic() - started_at)))


if __name__ == "__main__":
    raise SystemExit(main())
