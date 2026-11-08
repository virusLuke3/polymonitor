from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from api.services import f1_runtime_service, grid_esports_service, jin10_runtime_service, runtime_service, sports_odds_service
from api.services.seed_recovery import read_public_seed
from runtime.snapshot_store import SnapshotStore


NOW = "2026-11-08T03:00:00Z"


@pytest.mark.parametrize("reader", [
    runtime_service.get_nba_scoreboard_snapshot, runtime_service.get_nba_intel_snapshot,
    runtime_service.get_nba_matchup_predictor_snapshot, f1_runtime_service.get_f1_panel_snapshot,
    jin10_runtime_service.get_jin10_panel_snapshot, grid_esports_service.get_grid_esports_snapshot,
    sports_odds_service.get_sports_odds_snapshot,
])
def test_cold_public_reads_do_not_acquire_or_publish(reader, tmp_path):
    forbidden = Mock(side_effect=AssertionError("GET must not acquire or publish"))
    store = SnapshotStore(str(tmp_path / "seed.sqlite"))
    store.set = forbidden
    ctx = {
        "SETTINGS": SimpleNamespace(jin10_flash_api_url="fixture", jin10_flash_channel="1"),
        "SNAPSHOT_STORE": store, "SPORTS_RUNTIME_TTL_SECONDS": 60, "SIGNAL_RUNTIME_TTL_SECONDS": 60,
        "get_cached_json": lambda *args: None, "set_cached_json": forbidden,
        "http_json_get": forbidden, "http_json_post": forbidden,
        "requests": SimpleNamespace(get=forbidden, post=forbidden),
        "get_snapshot_payload": forbidden, "utc_now_iso": lambda: NOW,
    }
    value = reader(ctx)
    assert value["status"] == "warming"
    assert value["generatedAt"] == ""
    forbidden.assert_not_called()


def test_sqlite_seed_precedes_optional_redis_and_never_renews_source_clock(tmp_path):
    store = SnapshotStore(str(tmp_path / "seed.sqlite"))
    value = {"generatedAt": "2026-11-08T02:55:00Z", "status": "ok", "items": [{"id": "game"}]}
    store.set("nba", "ten", value, 3600)
    forbidden = Mock(side_effect=AssertionError("local hit must not touch Redis or write"))
    store.set = forbidden
    result = read_public_seed(namespace="nba", cache_key="ten", snapshot_store=store, redis_get=forbidden,
                              max_age_seconds=180, retain_seconds=900, now=NOW)
    assert result == {**value, "status": "stale", "cacheMode": "sqlite-seed"}
    forbidden.assert_not_called()


@pytest.mark.parametrize("timestamp", ["", "bad", "2026-11-08T02:45:00Z", "2026-11-08T03:02:00Z"])
def test_original_age_rejects_expired_missing_and_future_clocks(timestamp):
    value = {"generatedAt": timestamp, "status": "ok", "items": []}
    assert read_public_seed(namespace="nba", cache_key="ten", snapshot_store=None,
                            redis_get=lambda *args: value, max_age_seconds=180, retain_seconds=900, now=NOW) is None


def test_valid_empty_and_optional_redis_failure_are_distinct():
    value = {"generatedAt": NOW, "status": "empty", "items": []}
    kwargs = dict(namespace="nba", cache_key="ten", snapshot_store=None,
                  max_age_seconds=180, retain_seconds=900, now=NOW)
    assert read_public_seed(**kwargs, redis_get=lambda *args: value)["status"] == "empty"
    assert read_public_seed(**kwargs, redis_get=Mock(side_effect=TimeoutError)) is None
