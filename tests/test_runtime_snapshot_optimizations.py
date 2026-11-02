from __future__ import annotations

import json
import threading
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import Mock, patch
from api.context import RuntimeResources


from api.services import signal_service


class FakeLogger:
    def info(self, *args, **kwargs) -> None:
        return None

    def warning(self, *args, **kwargs) -> None:
        return None

    def exception(self, *args, **kwargs) -> None:
        return None


class FakeApp:
    logger = FakeLogger()


class FakeSnapshotStore:
    def __init__(
        self, fresh: Optional[Dict[tuple[str, str], Any]] = None, stale: Optional[Dict[tuple[str, str], Any]] = None
    ):
        self.fresh = dict(fresh or {})
        self.stale = dict(stale or {})

    def get(self, namespace: str, cache_key: str):
        return self.fresh.get((namespace, cache_key))

    def get_stale(self, namespace: str, cache_key: str):
        return self.stale.get((namespace, cache_key))

    def set(self, namespace: str, cache_key: str, payload: Any, ttl_seconds: int) -> None:
        self.fresh[(namespace, cache_key)] = payload
        self.stale[(namespace, cache_key)] = payload


class SignalSnapshotOptimizationTestCase(unittest.TestCase):
    def make_signal_context(
        self,
        *,
        snapshot_store: Optional[FakeSnapshotStore] = None,
    ) -> Dict[str, Any]:
        return {
            "SIGNAL_RUNTIME_TTL_SECONDS": 45,
            "SNAPSHOT_STORE": snapshot_store or FakeSnapshotStore(),
            "_resources": RuntimeResources(),
            "app": FakeApp(),
            "utc_now_iso": lambda: "2026-04-21T00:00:00Z",
        }

    def test_alpha_snapshot_returns_stale_without_scheduling_refresh(self):
        cache_key = json.dumps({"limit": 8}, sort_keys=True, ensure_ascii=True)
        stale_payload = {"items": [{"title": "stale alpha"}], "generatedAt": "stale"}
        ctx = self.make_signal_context(
            snapshot_store=FakeSnapshotStore(
                stale={(signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA, cache_key): stale_payload}
            ),
        )

        with patch.object(
            signal_service,
            "_build_alpha_signal_payload",
            return_value={"items": [{"title": "fresh"}], "generatedAt": "fresh"},
        ) as builder:
            first = signal_service.get_alpha_signal_snapshot(ctx, limit=8)
            second = signal_service.get_alpha_signal_snapshot(ctx, limit=8)

        self.assertEqual(first["items"], [])
        self.assertEqual(second["items"], [])
        self.assertEqual(first["generatedAt"], stale_payload["generatedAt"])
        # Read verification is allowed; request-driven collection remains forbidden.
        builder.assert_not_called()

    def test_alpha_snapshot_cold_miss_waits_for_watcher(self):
        cache_key = json.dumps({"limit": 8}, sort_keys=True, ensure_ascii=True)
        snapshot_store = FakeSnapshotStore()
        ctx = self.make_signal_context(snapshot_store=snapshot_store)
        payload = {"items": [{"title": "fresh alpha"}], "generatedAt": "fresh"}

        with patch.object(signal_service, "_build_alpha_signal_payload", return_value=payload) as builder:
            result = signal_service.get_alpha_signal_snapshot(ctx, limit=8)

        self.assertEqual(result["items"], [])
        self.assertEqual("warming", result["status"])
        self.assertEqual("seeded", result["cacheMode"])
        builder.assert_not_called()
        self.assertIsNone(snapshot_store.get(signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA, cache_key))


def test_shared_snapshot_refresh_accepts_empty_results_and_marks_stale(tmp_path):
    from api.cache import CacheState, get_snapshot_payload
    from runtime.snapshot_store import SnapshotStore

    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    resources = RuntimeResources()
    ctx = CacheState(resources, FakeApp(), store)
    with patch("runtime.snapshot_store.time.time", return_value=100):
        store.set("test", "key", {"items": ["old"]}, 10)
    with patch("runtime.snapshot_store.time.time", return_value=111):
        result = get_snapshot_payload(ctx, "test", "key", lambda: {"items": []}, ttl_seconds=10)
        assert result["stale"] is True
        resources.close()
        assert store.get("test", "key") == {"items": []}


def test_snapshot_read_does_not_extend_expiry_or_hide_refresh_failure(tmp_path):
    from api.cache import CacheState, get_snapshot_payload
    from runtime.snapshot_store import SnapshotStore

    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    resources = RuntimeResources()
    ctx = CacheState(resources, FakeApp(), store)
    with patch("runtime.snapshot_store.time.time", return_value=100):
        store.set("test", "key", {"items": ["old"]}, 10)
    with patch("runtime.snapshot_store.time.time", return_value=109):
        assert get_snapshot_payload(ctx, "test", "key", Mock(side_effect=AssertionError), ttl_seconds=10) == {
            "items": ["old"]
        }
    with patch("runtime.snapshot_store.time.time", return_value=111):
        builder = Mock(return_value={"status": "unavailable", "items": []})
        result = get_snapshot_payload(ctx, "test", "key", builder, ttl_seconds=10)
        resources.close()
        assert result["cacheStatus"] == "stale"
        builder.assert_called_once()
        assert store.get("test", "key") is None
        assert store.get_stale("test", "key") == {"items": ["old"]}


def test_expired_list_snapshot_never_returns_unmarked_old_rows(tmp_path):
    from api.cache import CacheState, get_snapshot_payload
    from runtime.snapshot_store import SnapshotStore
    import pytest

    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    resources = RuntimeResources()
    ctx = CacheState(resources, FakeApp(), store)
    with patch("runtime.snapshot_store.time.time", return_value=100):
        store.set("trades", "key", [{"timestamp": "old"}], 10)
    with patch("runtime.snapshot_store.time.time", return_value=111):
        with pytest.raises(TimeoutError):
            get_snapshot_payload(ctx, "trades", "key", Mock(side_effect=TimeoutError), ttl_seconds=10)
        with pytest.raises(TimeoutError):
            get_snapshot_payload(ctx, "trades", "key", lambda: [], ttl_seconds=10)
        # Retry only after the failure cooldown; empty success is then valid.
        ctx.snapshot_retry_at.clear()
        assert get_snapshot_payload(ctx, "trades", "key", lambda: [], ttl_seconds=10) == []
        assert store.get("trades", "key") == []
    resources.close()
