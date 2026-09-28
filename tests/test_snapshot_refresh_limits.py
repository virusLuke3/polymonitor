from __future__ import annotations

from unittest.mock import Mock, patch


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
