"""Real Redis integration; opt in with a disposable Redis endpoint."""
import json
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock
from urllib.parse import urlsplit
import uuid

import pytest
import redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from runtime.redis_snapshot_store import RedisSnapshotStore, public_namespace
from runtime.snapshot_store import SnapshotStore
from runtime.seed_meta import publish_snapshot, SeedMetaStore


@pytest.fixture
def store(tmp_path):
    url = os.environ.get("POLYMONITOR_TEST_REDIS_URL")
    if not url:
        pytest.skip("Requires disposable POLYMONITOR_TEST_REDIS_URL")
    parsed = urlsplit(url)
    assert parsed.hostname == "127.0.0.1" and parsed.port != 6379, "Never use the production Redis"
    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=1)
    prefix = "test:" + uuid.uuid4().hex + ":"
    value = RedisSnapshotStore(str(tmp_path / "history.sqlite3"), client=client, prefix=prefix)
    yield value
    keys = list(client.scan_iter(prefix + "*"))
    if keys:
        client.delete(*keys)
    client.close()


def test_clocks_retention_and_no_sqlite_fallback(store):
    now = time.time()
    payload = {"generatedAt": "2026-01-01T00:00:00Z", "items": [1]}
    assert store.import_snapshot("snapshot:test", "v1", payload, now - 3600, now - 1)
    assert store.get("snapshot:test", "v1") is None
    assert store.get_stale("snapshot:test", "v1") == payload
    assert store.get_stale("snapshot:test", "v1", max_age_seconds=60) is None
    assert store.client.ttl(store.key("snapshot:test", "v1")) > 6 * 86400
    assert not Path(store.db_path).exists()
    legacy = SnapshotStore(store.db_path)
    legacy.set("snapshot:test", "missing", {"legacy": True}, 60)
    assert store.get_stale("snapshot:test", "missing") is None
    assert not store.import_snapshot("snapshot:test", "expired", payload, now - 8 * 86400, now - 7 * 86400)


def test_old_writer_and_expired_lease_cannot_overwrite(store):
    ns = "snapshot:test"
    assert store.set(ns, "v1", {"generatedAt": "2026-01-02T00:00:00Z"}, 60)
    assert not store.set(ns, "v1", {"generatedAt": "2026-01-01T00:00:00Z"}, 60)
    with store.fetch_lock(ns, "owner", timeout=0):
        with pytest.raises(TimeoutError):
            with store.fetch_lock(ns, "owner", timeout=0):
                pass
        assert store.set(ns, "v2", {"value": 1}, 60)
        key, _ = store._leases.get()[0]
        store.client.set(key, "replacement-owner", ex=60)
        assert not store.set(ns, "v2", {"value": 2}, 60)
    assert store.client.get(key) == "replacement-owner"
    assert store.get(ns, "v2") == {"value": 1}


def test_pipeline_preserves_identity_and_request_consistency(store):
    ns = "snapshot:test"
    store.set(ns, '{"limit": 1}', {"items": [1]}, 60)
    store.set(ns, '{"limit": 2}', {"items": [1, 2]}, 60)
    with store.read_namespaces([ns]):
        key = store.key(ns, '{"limit": 1}')
        store.client.hset(key, "payload", json.dumps({"items": [3]}))
        assert store.get(ns, '{"limit": 1}') == {"items": [1]}
        assert store.get(ns, '{"limit": 2}') == {"items": [1, 2]}
        assert store.get(ns, '{"limit": 3}') is None
    assert store.get(ns, '{"limit": 1}') == {"items": [3]}


def test_capacity_latest_and_private_history(store):
    for i in range(4):
        assert store.set("snapshot:test", str(i), {"i": i}, 60, max_entries=2)
    assert store.get_stale("snapshot:test", "0") is None
    assert store.get_latest_stale("snapshot:test") == {"i": 3}
    assert store.get_latest_stale("snapshot:test", exclude_cache_key="3") == {"i": 2}
    assert store.set("agent:market-wide:quant-history", "old", {"history": 1}, 60)
    assert store.get("agent:market-wide:quant-history", "old") == {"history": 1}
    assert Path(store.db_path).exists()
    assert not store.client.exists(store.key("agent:market-wide:quant-history", "old"))
    assert store.key("snapshot:a:b", "c") != store.key("snapshot:a", "b:c")


def test_publish_and_meta_never_use_legacy_mirror(store):
    mirror = Mock()
    publish_snapshot(snapshot_store=store, namespace="snapshot:test", cache_key="v1",
                     payload={"items": [1]}, ttl_seconds=60, redis_client=mirror, redis_cache_key="old")
    mirror.set.assert_not_called()
    meta = SeedMetaStore(snapshot_store=store, redis_client=mirror, redis_prefix="old:")
    assert meta.load("seed-meta:test", "missing") is None
    mirror.get.assert_not_called()


def test_api_public_seed_does_not_collect_on_missing_redis(store):
    from api.services.seed_recovery import read_watch_seed
    builder, legacy = Mock(), Mock()
    value = read_watch_seed(namespace="snapshot:test", cache_key="v1", panel_id="test",
                            snapshot_store=store, redis_get=legacy, redis_set=legacy,
                            builder=builder, ttl_seconds=60)
    assert value["status"] == "warming"
    builder.assert_not_called()
    legacy.assert_not_called()


def test_unavailable_redis_does_not_read_sqlite_or_advance_success(store):
    store.client = Mock()
    store.client.hmget.side_effect = redis.ConnectionError("offline")
    with pytest.raises(redis.ConnectionError):
        store.get_stale("snapshot:test", "v1")
    assert not Path(store.db_path).exists()


def test_namespace_ownership():
    for namespace in ("snapshot:weather:global-map", "runtime:finance:defi", "source:external-panels:v1",
                      "seed-meta:sports", "agent:market-wide:snapshot"):
        assert public_namespace(namespace)
    for namespace in ("auth:acled", "state:source-transport", "source:open-meteo", "agent:market-wide:quant-history"):
        assert not public_namespace(namespace)


def test_factory_seed_identity_is_independent_of_legacy_queue_prefix(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from api import config
    from runtime.redis_snapshot_store import create_snapshot_store
    monkeypatch.setenv("POLYMONITOR_SEED_BACKEND", "redis")
    monkeypatch.setenv("POLYMONITOR_SEED_REDIS_URL", "redis://127.0.0.1:12345/0")
    monkeypatch.setenv("POLYMONITOR_SEED_REDIS_PREFIX", "shared:")
    settings = SimpleNamespace(redis_url="", redis_prefix="worker-queue:")
    monkeypatch.setattr(config, "load_api_settings", lambda: settings)
    worker = create_snapshot_store(str(tmp_path / "worker.sqlite"))
    settings.redis_prefix = "api-queue:"
    reader = create_snapshot_store(str(tmp_path / "api.sqlite"))
    assert worker.key("snapshot:test", "v1") == reader.key("snapshot:test", "v1")
    assert worker.client is reader.client


def test_finance_api_reads_collector_universe_without_yahoo_or_republication(store):
    from api.services import finance_panels_service
    forbidden = Mock(side_effect=AssertionError("Public GET must not collect or publish"))
    context = {"SNAPSHOT_STORE": store, "get_snapshot_payload": forbidden,
               "get_yahoo_market_snapshot": forbidden, "get_market_groups_payload": forbidden}
    reader = finance_panels_service.get_equity_event_command_snapshot
    assert reader(context, limit=4)["status"] == "warming"
    now = time.time()
    value = {"status": "ok", "generatedAt": "2026-01-01T00:00:00Z",
             "items": [{"symbol": str(i)} for i in range(12)]}
    store.import_snapshot("runtime:finance:equity-event-command", "v3:24", value, now - 100, now - 1)
    key = store.key("runtime:finance:equity-event-command", "v3:24")
    before = store.client.hgetall(key)
    result = reader(context, limit=4)
    assert result["status"] == "stale" and len(result["items"]) == 4
    assert result["generatedAt"] == value["generatedAt"]
    assert store.client.hgetall(key) == before
    forbidden.assert_not_called()
