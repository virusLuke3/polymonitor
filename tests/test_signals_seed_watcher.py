from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


from api.services import signal_service, alpha_signal_service
from runtime import signals_watcher
from runtime.snapshot_store import SnapshotStore


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def close(self) -> None:
        pass

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.values[key] = value

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.set(key, value, ex=ttl)


class SignalsSeedWatcherTestCase(unittest.TestCase):
    def make_watcher(self, component: str = "whales", limit: int = 14):
        snapshot_dir = tempfile.TemporaryDirectory()
        self.addCleanup(snapshot_dir.cleanup)
        fake_redis = FakeRedis()
        redis_module = SimpleNamespace(from_url=lambda *args, **kwargs: fake_redis)
        with patch.object(signals_watcher, "redis", redis_module):
            watcher = signals_watcher.SignalsWatcher(
                redis_url="redis://test/0",
                redis_prefix="polydata:",
                snapshot_sqlite_path=str(Path(snapshot_dir.name) / "snapshots.sqlite3"),
                component=component,
                limit=limit,
                interval_seconds=45,
            )
        self.addCleanup(watcher.close)
        return watcher, fake_redis

    def test_signal_schedule_and_ttl_share_settings_and_prevent_duplicate_workers(self):
        watcher, _ = self.make_watcher()
        self.assertEqual(120, watcher.interval_seconds)
        self.assertEqual(300, watcher.ttl_seconds())
        with patch.object(signals_watcher, "redis", SimpleNamespace(from_url=lambda *a, **kw: FakeRedis())):
            with self.assertRaisesRegex(RuntimeError, "already running"):
                signals_watcher.SignalsWatcher(
                    redis_url="redis://test/0", redis_prefix="polydata:",
                    snapshot_sqlite_path=str(watcher._lock.name).replace("signals-whales.lock", "snapshots.sqlite3"),
                    component="whales", limit=100, interval_seconds=120,
                )

    def test_watcher_stores_whale_payload_and_seed_meta(self):
        watcher, fake_redis = self.make_watcher(component="whales", limit=14)
        payload = {"items": [{"title": "Whale flow"}], "generatedAt": "2026-05-03T08:00:00Z", "status": "ok"}
        with patch.object(watcher, "fetch_payload", return_value=payload):
            result = watcher.run_once()

        self.assertEqual("ok", result["status"])
        cache_key = signal_service.build_whale_trades_cache_key(limit=14)
        stored = json.loads(fake_redis.get(f"polydata:snapshot:signals:whales:{cache_key}") or "{}")
        self.assertEqual("seeded", stored["cacheMode"])
        self.assertEqual("ok", stored["status"])
        meta = json.loads(fake_redis.get("polydata:seed-meta:signals:whale-trades") or "{}")
        self.assertEqual("ok", meta["status"])
        self.assertEqual(1, meta["recordCount"])

    def test_transient_source_timeout_is_retried_in_the_same_seed_cycle(self):
        watcher, fake_redis = self.make_watcher()
        payload = {"items": [{"title": "Current whale"}], "generatedAt": signals_watcher.utc_now_iso(), "status": "ok"}
        fetcher = Mock(side_effect=[TimeoutError("private connection"), payload])
        with patch.dict(watcher.spec, {"fetcher": fetcher}), patch.object(watcher, "service_context", return_value={}):
            result = watcher.run_once()
        self.assertEqual(2, fetcher.call_count)
        self.assertEqual("ok", result["status"])
        self.assertEqual(payload["generatedAt"], json.loads(fake_redis.get(watcher.redis_key()))["generatedAt"])

    def test_exhausted_source_timeouts_preserve_the_previous_snapshot_and_clock(self):
        watcher, fake_redis = self.make_watcher()
        previous = {"items": [{"title": "Previous whale"}], "generatedAt": "2026-10-03T00:00:00Z", "status": "ok"}
        watcher.store_payload(previous)
        fetcher = Mock(side_effect=TimeoutError("private connection"))
        with patch.dict(watcher.spec, {"fetcher": fetcher}), patch.object(watcher, "service_context", return_value={}):
            result = watcher.run_once()
        stored = json.loads(fake_redis.get(watcher.redis_key()))
        self.assertEqual(2, fetcher.call_count)
        self.assertEqual("preserved", result["status"])
        self.assertEqual(previous["generatedAt"], stored["generatedAt"])
        self.assertEqual(previous["items"], stored["items"])
        self.assertNotIn("private", stored["error"])

    def test_invalid_source_payload_is_not_retried(self):
        watcher, _ = self.make_watcher()
        fetcher = Mock(side_effect=ValueError("invalid source"))
        with patch.dict(watcher.spec, {"fetcher": fetcher}), patch.object(watcher, "service_context", return_value={}):
            result = watcher.run_once()
        fetcher.assert_called_once()
        self.assertEqual("error", result["status"])

    def test_watcher_replaces_previous_payload_when_successful_result_is_empty(self):
        watcher, fake_redis = self.make_watcher(component="alpha", limit=8)
        previous = {"items": [{"title": "Old alpha"}], "generatedAt": "old", "status": "ok", "cacheMode": "seeded"}
        watcher.store_payload(previous)
        with patch.object(
            watcher, "fetch_payload", return_value={"items": [], "generatedAt": "new", "status": "empty"}
        ):
            result = watcher.run_once()

        self.assertEqual("empty", result["status"])
        stored = json.loads(fake_redis.get(watcher.redis_key()) or "{}")
        self.assertEqual([], stored["items"])
        self.assertIsNotNone(signals_watcher._parse_item_timestamp(stored["generatedAt"]))
        self.assertEqual("new", stored["lastAttemptAt"])
        meta = json.loads(fake_redis.get("polydata:seed-meta:signals:alpha-signal") or "{}")
        self.assertEqual("empty", meta["status"])

    def test_api_reads_seeded_signal_redis_without_live_build(self):
        with tempfile.TemporaryDirectory() as snapshot_dir:
            store = SnapshotStore(str(Path(snapshot_dir) / "snapshots.sqlite3"))
            cache_key = signal_service.build_alpha_signal_cache_key(limit=8)
            seeded = {"items": [{"title": "Seeded alpha"}], "generatedAt": "2026-05-03T08:00:00Z", "cacheMode": "seeded"}
            ctx = {
                "SIGNAL_RUNTIME_TTL_SECONDS": 45,
                "SNAPSHOT_STORE": store,
                "get_cached_runtime_payload": lambda namespace, key: None,
                "set_cached_runtime_payload": lambda namespace, key, payload, ttl: payload,
                "get_cached_json": lambda namespace, key: (
                    seeded if (namespace, key) == (signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA, cache_key) else None
                ),
                "threading": SimpleNamespace(Thread=object),
                "app": SimpleNamespace(
                    logger=SimpleNamespace(info=lambda *args, **kwargs: None, exception=lambda *args, **kwargs: None)
                ),
                "utc_now_iso": lambda: "2026-05-03T08:00:00Z",
            }
            with patch.object(
                signal_service,
                "fetch_live_alpha_signal_payload",
                side_effect=AssertionError("live build should not run"),
            ):
                payload = signal_service.get_alpha_signal_snapshot(ctx, limit=8)

        self.assertEqual("seeded", payload["cacheMode"])
        self.assertEqual([], payload["items"])

    def test_api_trims_default_signal_seeds_for_smaller_limits_without_live_build(self):
        seeded_payloads = {
            (signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA, signal_service.build_alpha_signal_cache_key(limit=8)): {
                "items": [{"title": "Alpha 1"}, {"title": "Alpha 2"}],
                "generatedAt": "2026-05-03T08:00:00Z",
                "cacheMode": "seeded",
            },
            (signal_service.SIGNAL_SNAPSHOT_NAMESPACE_WHALES, signal_service.build_whale_trades_cache_key(limit=14)): {
                "items": [{"title": "Whale 1"}, {"title": "Whale 2"}],
                "generatedAt": "2026-05-03T08:00:00Z",
                "cacheMode": "seeded",
            },
            (
                signal_service.SIGNAL_SNAPSHOT_NAMESPACE_SUSPICIOUS,
                signal_service.build_suspicious_trades_cache_key(limit=12),
            ): {
                "items": [{"title": "Suspicious 1"}, {"title": "Suspicious 2"}],
                "generatedAt": "2026-05-03T08:00:00Z",
                "cacheMode": "seeded",
            },
        }
        ctx = {
            "SIGNAL_RUNTIME_TTL_SECONDS": 45,
            "SNAPSHOT_STORE": None,
            "get_cached_runtime_payload": lambda namespace, key: None,
            "set_cached_runtime_payload": lambda namespace, key, payload, ttl: payload,
            "get_cached_json": lambda namespace, key: seeded_payloads.get((namespace, key)),
            "threading": SimpleNamespace(Thread=object),
            "app": SimpleNamespace(
                logger=SimpleNamespace(info=lambda *args, **kwargs: None, exception=lambda *args, **kwargs: None)
            ),
            "utc_now_iso": lambda: "2026-05-03T08:00:00Z",
        }
        with (
            patch.object(
                signal_service,
                "fetch_live_alpha_signal_payload",
                side_effect=AssertionError("live alpha should not run"),
            ),
            patch.object(
                signal_service,
                "fetch_live_whale_trades_payload",
                side_effect=AssertionError("live whales should not run"),
            ),
            patch.object(
                signal_service,
                "fetch_live_suspicious_trades_payload",
                side_effect=AssertionError("live suspicious should not run"),
            ),
        ):
            alpha = signal_service.get_alpha_signal_snapshot(ctx, limit=1)
            whales = signal_service.get_whale_trades_snapshot(ctx, limit=1)
            suspicious = signal_service.get_suspicious_trades_snapshot(ctx, limit=1)

        self.assertEqual([], alpha["items"])
        self.assertEqual(["Whale 1"], [item["title"] for item in whales["items"]])
        self.assertEqual(["Suspicious 1"], [item["title"] for item in suspicious["items"]])
        self.assertEqual("seeded", alpha["cacheMode"])
        self.assertEqual("seeded", whales["cacheMode"])
        self.assertEqual("seeded", suspicious["cacheMode"])

    def test_alpha_live_payload_degrades_when_database_sources_fail(self):
        ctx = {
            "app": SimpleNamespace(logger=SimpleNamespace(exception=lambda *args, **kwargs: None)),
            "utc_now_iso": lambda: "2026-05-03T08:00:00Z",
            "get_recent_trades": lambda limit=24: (_ for _ in ()).throw(RuntimeError("db down")),
            "get_recent_oracle_events": lambda limit=24: (_ for _ in ()).throw(RuntimeError("db down")),
            "get_active_markets_snapshot": lambda page_size=8: (_ for _ in ()).throw(RuntimeError("db down")),
            "get_market_group_snapshot": lambda items, kind: {
                "items": [{"label": "BTC", "changePercent": 3.2, "price": 68000}]
            },
            "get_inflation_nowcast_snapshot": lambda: {"monthOverMonth": {"CPI": "0.41", "Core CPI": "0.21"}},
            "CRYPTO_SYMBOLS": [("btc", "BTC", "BTC-USD")],
            "_safe_decimal": lambda value: None,
            "_safe_float": lambda value: float(value) if value is not None else None,
            "format_trade_decimal": lambda value: value,
            "format_trade_address": lambda value: value,
            "parse_iso_datetime": lambda value: None,
            "utc_date_days_ago": lambda days: "2026-05-01",
        }

        with patch.object(alpha_signal_service, "_candidates", return_value=None):
            payload = signal_service.fetch_live_alpha_signal_payload(ctx, limit=3)

        self.assertEqual("degraded", payload["status"])
        self.assertEqual([], payload["items"])

    def test_alpha_compatibility_entrypoint_uses_its_owned_token_service(self):
        expected = {"items": [], "status": "empty"}
        with patch.object(alpha_signal_service, "fetch_live_alpha_signal_payload", return_value=expected) as fetcher:
            self.assertEqual(expected, signal_service.fetch_live_alpha_signal_payload({}, limit=3))
        fetcher.assert_called_once_with({}, limit=3)

    def test_alpha_worker_exposes_failed_verification_without_faking_empty(self):
        watcher, fake_redis = self.make_watcher(component="alpha", limit=8)
        failed = {"items": [], "generatedAt": "new", "status": "degraded",
                  "coverage": {"candidateCount": 25, "verifiedCount": 0}, "error": "Identity unavailable"}
        with patch.object(watcher, "fetch_payload", return_value=failed):
            result = watcher.run_once()
        stored = json.loads(fake_redis.get(watcher.redis_key()))
        self.assertEqual("degraded", result["status"])
        self.assertEqual(25, stored["coverage"]["candidateCount"])
        self.assertEqual("degraded", stored["freshness"])

    def test_alpha_worker_preserves_good_cards_and_failure_diagnostics(self):
        watcher, fake_redis = self.make_watcher(component="alpha", limit=8)
        previous = {"items": [{"id": "good"}], "generatedAt": "old", "status": "ok"}
        watcher.store_payload(previous)
        failed = {"items": [], "generatedAt": "new", "status": "degraded", "coverage": {"rejectedCount": 3}}
        with patch.object(watcher, "fetch_payload", return_value=failed):
            watcher.run_once()
        stored = json.loads(fake_redis.get(watcher.redis_key()))
        self.assertEqual(previous["items"], stored["items"])
        self.assertEqual("old", stored["generatedAt"])
        self.assertEqual("new", stored["lastAttemptAt"])
        self.assertEqual(3, stored["coverage"]["rejectedCount"])

    def test_alpha_worker_preserves_neutral_candidates_on_source_failure(self):
        watcher, fake_redis = self.make_watcher(component="alpha", limit=8)
        previous = {"items": [], "candidates": [{"id": "observed"}], "generatedAt": "old", "status": "partial"}
        watcher.store_payload(previous)
        failed = {"items": [], "candidates": [], "generatedAt": "new", "status": "degraded"}
        with patch.object(watcher, "fetch_payload", return_value=failed):
            watcher.run_once()
        stored = json.loads(fake_redis.get(watcher.redis_key()))
        self.assertEqual(previous["candidates"], stored["candidates"])
        self.assertEqual("old", stored["generatedAt"])
        self.assertEqual("stale", stored["status"])

    def test_whale_live_payload_uses_clickhouse_volume_rows(self):
        ctx = {
            "app": SimpleNamespace(
                logger=SimpleNamespace(exception=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
            ),
            "utc_now_iso": lambda: "2026-06-06T02:00:00Z",
            "query_all": lambda sql, params=(): [],
            "_safe_decimal": lambda value: signal_service.Decimal(str(value)) if value is not None else None,
            "format_trade_decimal": lambda value: str(value) if value is not None else None,
            "format_trade_address": lambda value: value,
            "parse_iso_datetime": lambda value: None,
            "utc_date_days_ago": lambda days: "2026-05-30T02:00:00Z",
        }
        whale_rows = [
            {
                "market_id": 20,
                "market_title": "Whale market",
                "timestamp": "2026-06-06T01:59:59Z",
                "tx_hash": "0xabc",
                "outcome": "NO",
                "side": "BUY",
                "price": "0.40",
                "size": "25000",
                "notional": "10000",
                "severity": "critical",
                "source_mode": "clickhouse-volume-whales",
                "signal_type": "single-trade",
                "market_share": "0.22",
            }
        ]
        with patch.object(
            signal_service.clickhouse_orderfilled_service, "get_volume_whale_rows", return_value=whale_rows
        ):
            payload = signal_service.fetch_live_whale_trades_payload(ctx, limit=3)

        self.assertEqual("ok", payload["status"])
        self.assertEqual("clickhouse-volume-whales", payload["sourceMode"])
        self.assertEqual("10000", payload["items"][0]["notional"])
        self.assertEqual("single-trade", payload["items"][0]["signalType"])

    def test_whale_live_payload_filters_near_resolved_and_dedupes_router_splits(self):
        ctx = {
            "app": SimpleNamespace(
                logger=SimpleNamespace(exception=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
            ),
            "utc_now_iso": lambda: "2026-06-06T02:00:00Z",
            "query_all": lambda sql, params=(): [],
            "_safe_decimal": lambda value: signal_service.Decimal(str(value)) if value is not None else None,
            "format_trade_decimal": lambda value: str(value) if value is not None else None,
            "format_trade_address": lambda value: value,
            "parse_iso_datetime": lambda value: None,
            "utc_date_days_ago": lambda days: "2026-05-30T02:00:00Z",
        }
        whale_rows = [
            {
                "market_id": 20,
                "market_title": "Near resolved",
                "timestamp": "2026-06-06T01:59:59Z",
                "tx_hash": "0xnear",
                "outcome": "YES",
                "side": "BUY",
                "price": "0.991",
                "size": "25000",
                "notional": "24775",
                "taker": "0xrouter",
                "severity": "critical",
                "source_mode": "clickhouse-volume-whales",
            },
            {
                "market_id": 21,
                "market_title": "Split market",
                "timestamp": "2026-06-06T01:59:58Z",
                "tx_hash": "0xkeep",
                "outcome": "YES",
                "side": "BUY",
                "price": "0.50",
                "size": "20000",
                "notional": "10000",
                "taker": "0xrouter",
                "severity": "critical",
                "source_mode": "clickhouse-volume-whales",
            },
            {
                "market_id": 21,
                "market_title": "Split market",
                "timestamp": "2026-06-06T01:59:57Z",
                "tx_hash": "0xsplit",
                "outcome": "YES",
                "side": "BUY",
                "price": "0.51",
                "size": "12000",
                "notional": "6120",
                "taker": "0xrouter",
                "severity": "critical",
                "source_mode": "clickhouse-volume-whales",
            },
        ]
        with patch.object(
            signal_service.clickhouse_orderfilled_service, "get_volume_whale_rows", return_value=whale_rows
        ):
            payload = signal_service.fetch_live_whale_trades_payload(ctx, limit=3)

        self.assertEqual("ok", payload["status"])
        self.assertEqual(["0xkeep"], [item["txHash"] for item in payload["items"]])

    def test_whale_source_failure_does_not_read_bootstrap_or_market_activity(self):
        ctx = {"get_cached_json": Mock(), "get_active_markets_snapshot": Mock()}
        with patch.object(signal_service.clickhouse_orderfilled_service, "get_volume_whale_rows", return_value=None):
            with self.assertRaises(TimeoutError):
                signal_service.fetch_live_whale_trades_payload(ctx, limit=3)
        ctx["get_cached_json"].assert_not_called()
        ctx["get_active_markets_snapshot"].assert_not_called()

    def test_watcher_runtime_receives_settings_and_closes(self):
        watcher, _ = self.make_watcher()
        with patch("api.runtime.ServiceRuntime") as runtime:
            self.assertIs(watcher.service_context(), runtime.return_value.signal_context)
            runtime.assert_called_once_with(watcher.settings, application=unittest.mock.ANY)
            watcher.close()
            runtime.return_value.close.assert_called_once()

    def test_failed_refresh_preserves_data_time_and_marks_stale(self):
        watcher, redis = self.make_watcher()
        previous = {"items": [{"title": "Old whale"}], "status": "ok", "generatedAt": "2026-09-28T10:00:00Z"}
        watcher.store_payload(previous)
        with patch.object(watcher, "fetch_payload", side_effect=TimeoutError("read failed")):
            watcher.run_once()
        stored = json.loads(redis.get(watcher.redis_key()))
        self.assertEqual("stale", stored["status"])
        self.assertEqual(previous["generatedAt"], stored["generatedAt"])
        self.assertEqual(previous["items"], stored["items"])

    def test_repeated_requests_read_canonical_seed_without_refresh(self):
        old = {"items": [{"title": "old"}], "generatedAt": "2026-09-28T10:00:00Z", "status": "ok"}
        ctx = {"get_cached_json": lambda *a: old, "utc_now_iso": lambda: "2026-09-29T10:00:00Z",
               "SIGNAL_RUNTIME_TTL_SECONDS": 45}
        with patch.object(signal_service, "fetch_live_whale_trades_payload") as refresh:
            for limit in (1, 100, 1):
                result = signal_service.get_whale_trades_snapshot(ctx, limit=limit)
        self.assertEqual("stale", result["status"])
        self.assertEqual(old["generatedAt"], result["generatedAt"])
        refresh.assert_not_called()

    def test_watcher_marks_old_payload_stale_even_with_records(self):
        watcher, fake_redis = self.make_watcher(component="whales", limit=14)
        payload = {
            "items": [{"title": "Old whale", "timestamp": "2026-04-28T11:00:40Z"}],
            "generatedAt": "2026-06-06T01:00:00Z",
            "status": "ok",
        }
        with (
            patch.object(watcher, "fetch_payload", return_value=payload),
            patch.object(
                signals_watcher,
                "datetime",
                SimpleNamespace(
                    now=lambda tz=None: datetime(2026, 6, 6, 1, 0, 0, tzinfo=timezone.utc),
                    fromisoformat=datetime.fromisoformat,
                ),
            ),
        ):
            result = watcher.run_once()

        self.assertEqual("stale", result["status"])
        stored = json.loads(fake_redis.get(watcher.redis_key()) or "{}")
        self.assertEqual("stale", stored["status"])
        meta = json.loads(fake_redis.get("polydata:seed-meta:signals:whale-trades") or "{}")
        self.assertEqual("stale", meta["status"])
        self.assertEqual("2026-04-28T11:00:40Z", meta["metadata"]["maxItemTimestamp"])
        self.assertGreater(meta["metadata"]["dataAgeSeconds"], 7 * 24 * 60 * 60)
