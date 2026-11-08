from __future__ import annotations

from unittest.mock import Mock, patch
import time


from api import cache
from api.context import RuntimeResources


def test_snapshot_refresh_is_deferred_when_capacity_is_full() -> None:
    slots = Mock()
    slots.acquire.return_value = False
    app = Mock()
    resources = RuntimeResources()

    with (
        patch.object(resources, "snapshot_slots", slots),
        patch.object(resources, "start_thread") as thread,
    ):
        cache._refresh_snapshot_payload_async(
            cache.CacheState(resources=resources, application=app, snapshot_store=None),
            "snapshot:test",
            "key",
            lambda: {},
            60,
        )

    thread.assert_not_called()
    app.logger.info.assert_called_once()


def test_rejected_snapshot_write_preserves_old_data_and_applies_failure_cooldown():
    old = {"items": ["old"]}
    store = Mock()
    store.get.return_value = None
    store.get_stale.return_value = old
    store.set.return_value = False
    resources = RuntimeResources()
    ctx = cache.CacheState(resources=resources, application=Mock(), snapshot_store=store)
    with patch.object(resources, "start_thread", side_effect=lambda callback, **kwargs: callback() or True):
        result = cache.get_snapshot_payload(ctx, "snapshot:test", "key", lambda: {"items": ["new"]}, ttl_seconds=60)
        assert result["items"] == ["old"]
        assert ctx.snapshot_retry_at["snapshot:test:key"] > time.monotonic()
        assert not resources.snapshot_refreshing
        store.set.assert_called_once()
        cache.get_snapshot_payload(ctx, "snapshot:test", "key", lambda: {"items": ["new"]}, ttl_seconds=60)
        store.set.assert_called_once()
        ctx.snapshot_retry_at["snapshot:test:key"] = time.monotonic() - 1
        store.set.return_value = True
        cache.get_snapshot_payload(ctx, "snapshot:test", "key", lambda: {"items": ["new"]}, ttl_seconds=60)
        assert "snapshot:test:key" not in ctx.snapshot_retry_at
        assert store.set.call_count == 2
