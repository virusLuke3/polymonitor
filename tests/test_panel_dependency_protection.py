from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import Mock

import pytest
from flask import Flask

from api.cache import CacheState, get_snapshot_payload
from api.context import RuntimeResources
from api.db_pool import ApiPostgresConnectionPool
from api.readiness import CachedProbe
from api.routes.system import SystemRouteDependencies, create_system_blueprint


def test_unreachable_database_does_not_reconnect_on_each_request():
    factory = Mock(side_effect=ConnectionError('too many clients'))
    pool = ApiPostgresConnectionPool(factory, max_size=4, acquire_timeout_seconds=.1)
    with pytest.raises(ConnectionError):
        pool.acquire()
    with ThreadPoolExecutor(max_workers=16) as executor:
        def request(_):
            with pytest.raises(TimeoutError):
                pool.acquire()
        list(executor.map(request, range(80)))
    assert factory.call_count == 1
    assert pool._connection_count == 0


def test_blocked_probe_does_not_accumulate_threads():
    release = Event()
    check = Mock(side_effect=lambda: release.wait(2))
    probe = CachedProbe(check)
    try:
        with ThreadPoolExecutor(max_workers=16) as executor:
            assert not any(executor.map(lambda _: probe(), range(32)))
        assert check.call_count == 1
    finally:
        release.set()


def test_health_requires_a_real_probe_and_keeps_liveness_independent():
    app = Flask(__name__)
    app.register_blueprint(create_system_blueprint(SystemRouteDependencies(
        Mock(), Mock(), Mock(), lambda: 'configured-private-database', lambda: Mock(ping=lambda: True))))
    response = app.test_client().get('/health')
    assert response.status_code == 503
    assert response.json['database'] is False
    assert b'private' not in response.data
    assert response.headers['Retry-After'] == '15'
    assert app.test_client().get('/health/live').status_code == 200


def test_cold_snapshot_singleflight_and_failure_cooldown():
    resources = RuntimeResources()
    store = Mock(get=lambda *args: None, get_stale=lambda *args: None)
    ctx = CacheState(resources, Mock(), store)
    started, release = Event(), Event()
    def fail():
        started.set()
        release.wait(2)
        raise ConnectionError('source unavailable')
    builder = Mock(side_effect=fail)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(get_snapshot_payload, ctx, 'panel', 'same', builder, ttl_seconds=10)
        assert started.wait(1)
        for _ in range(20):
            with pytest.raises(TimeoutError):
                get_snapshot_payload(ctx, 'panel', 'same', builder, ttl_seconds=10)
        release.set()
        with pytest.raises(ConnectionError):
            first.result()
    with pytest.raises(TimeoutError):
        get_snapshot_payload(ctx, 'panel', 'same', builder, ttl_seconds=10)
    assert builder.call_count == 1
    assert not resources.snapshot_refreshing
    assert resources.snapshot_slots.acquire(blocking=False)
