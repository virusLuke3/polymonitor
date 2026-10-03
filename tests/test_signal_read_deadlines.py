"""HTTP isolation and semantic acceptance when read verification stalls."""
from copy import deepcopy
from threading import Event
from time import monotonic
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
import pytest

from api.context import RuntimeResources
from api.routes.runtime_signals import create_runtime_signals_blueprint
from api.routes.runtime_panels import create_runtime_panels_blueprint, RuntimePanelRouteDependencies
from api.runtime_panels.types import RuntimePanelContext
from api.http import register_http_hooks
from api.runtime import ServiceRuntime
from api.services import signal_service
from api.services.signal_reads import SignalReadPending, read_verified_seed


def test_tunnel_cold_connection_is_admitted_within_default_budget(monkeypatch):
    from unittest.mock import Mock
    from api import db_pool
    clock, connection = [0.0], Mock()
    def connect(*args, **kwargs):
        clock[0] += 6.3  # Measured production connection setup through the tunnel.
        return connection
    monkeypatch.delenv("POLYDATA_API_POSTGRES_POOL_ACQUIRE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("POLYDATA_API_POSTGRES_POOL_SIZE", raising=False)
    monkeypatch.setattr(db_pool.time, "monotonic", lambda: clock[0])
    factory = db_pool.build_api_connection_factory(connect, lambda: "postgres")
    try:
        factory().close()
        factory().close()  # The admitted session is reusable; no reconnect.
        assert clock[0] == 6.3
        connection.close.assert_not_called()
    finally:
        factory.close()


def test_explicit_short_connection_deadline_still_rejects_late_sessions(monkeypatch):
    from unittest.mock import Mock
    from api import db_pool
    clock, connection = [0.0], Mock()
    def connect(*args, **kwargs):
        clock[0] += 6.3
        return connection
    monkeypatch.setenv("POLYDATA_API_POSTGRES_POOL_ACQUIRE_TIMEOUT_SECONDS", "5")
    monkeypatch.delenv("POLYDATA_API_POSTGRES_POOL_SIZE", raising=False)
    monkeypatch.setattr(db_pool.time, "monotonic", lambda: clock[0])
    factory = db_pool.build_api_connection_factory(connect, lambda: "postgres")
    try:
        with pytest.raises(TimeoutError, match="deadline"):
            factory()
        connection.close.assert_called_once()
    finally:
        factory.close()


@pytest.fixture
def ctx():
    resources = RuntimeResources(shutdown_timeout_seconds=.1)
    value = {"_resources": resources, "utc_now_iso": lambda: "2026-10-03T08:00:00Z",
             "SIGNAL_RUNTIME_TTL_SECONDS": 300}
    yield value
    resources.close()


def test_hung_checks_are_bounded_deduplicated_and_do_not_queue_another_channel(ctx):
    release = Event()
    started = Event()
    calls = []
    seed = {"generatedAt": "2026-10-03T08:00:00Z", "items": [1]}
    def verify(value):
        calls.append(value)
        started.set()
        release.wait(5)
        return value
    try:
        for _ in range(4):
            before = monotonic()
            with pytest.raises(SignalReadPending):
                read_verified_seed(ctx, "whales", seed, verify, wait_seconds=.01)
            assert monotonic() - before < .5
        assert started.is_set() and len(calls) == 1
        assert read_verified_seed(ctx, "flow", seed, lambda value: value) == seed
        with pytest.raises(SignalReadPending):
            read_verified_seed(ctx, "whales", {**seed, "items": [2]}, verify, wait_seconds=.01)
        assert len(calls) == 1
    finally:
        release.set()
        ctx["_resources"].signal_reads["whales"].future.result(timeout=1)
    assert read_verified_seed(ctx, "whales", seed, verify) == seed
    assert len(calls) == 1
    # The next seed must be checked, never served with the old task's result.
    newer = {**seed, "items": [2]}
    assert read_verified_seed(ctx, "whales", newer, verify) == newer
    assert len(calls) == 2


def test_cache_returns_copies_and_rechecks_content_and_expiration(ctx):
    calls = []
    seed = {"items": [1], "generatedAt": "2026-10-03T08:00:00Z"}
    def verify(value):
        calls.append(deepcopy(value))
        return value
    result = read_verified_seed(ctx, "whales", seed, verify)
    result["items"].clear()
    assert read_verified_seed(ctx, "whales", seed, verify) == seed
    assert len(calls) == 1
    ctx["_resources"].signal_reads["whales"].expires = 0
    assert read_verified_seed(ctx, "whales", seed, verify) == seed
    assert len(calls) == 2


def test_stalled_work_has_a_fixed_capacity_and_shutdown_does_not_admit_more(ctx):
    release = Event()
    def blocked(value):
        release.wait(5)
        return value
    try:
        for name in ("alpha", "whales", "flow"):
            with pytest.raises(SignalReadPending):
                read_verified_seed(ctx, name, {}, blocked, wait_seconds=.01)
        with pytest.raises(SignalReadPending, match="capacity"):
            read_verified_seed(ctx, "unexpected", {}, blocked)
        assert len(ctx["_resources"].signal_reads) == 3
    finally:
        release.set()
        for check in ctx["_resources"].signal_reads.values():
            check.future.result(timeout=1)
    ctx["_resources"].close()
    with pytest.raises(RuntimeError, match="closed"):
        read_verified_seed(ctx, "alpha", {"new": True}, lambda value: value)


def test_verifier_exception_is_not_reclassified_as_pending_or_retried_in_a_loop(ctx):
    calls = []
    def broken(value):
        calls.append(value)
        raise TimeoutError("database timed out")
    for _ in range(3):
        with pytest.raises(TimeoutError, match="database timed out"):
            read_verified_seed(ctx, "alpha", {}, broken)
    assert len(calls) == 1


@pytest.mark.parametrize("registry", [False, True])
def test_pending_routes_return_retry_after_and_no_unverified_payload(registry):
    def pending(**_kwargs):
        raise SignalReadPending("internal connection details")
    app = Flask(__name__)
    register_http_hooks(app, set())
    helpers = {
        "get_alpha_signal_snapshot": pending, "get_whale_trades_snapshot": pending,
        "get_suspicious_trades_snapshot": pending,
    }
    dependencies = RuntimePanelRouteDependencies(
        panel_context=RuntimePanelContext.from_context(helpers), utc_now_iso=lambda: "2026-10-03T08:00:00Z",
        natural_hazard_map_snapshot=None, natural_hazard_event_detail=None,
        natural_hazard_related_markets=None, aviation_viewport_snapshot=None,
    )
    app.register_blueprint(create_runtime_panels_blueprint(dependencies) if registry
                           else create_runtime_signals_blueprint(helpers))
    for path in ("/runtime/signals/alpha", "/runtime/trades/whales", "/runtime/trades/suspicious"):
        response = app.test_client().get(path)
        assert response.status_code == 503
        assert response.headers["Retry-After"] == "1"
        assert response.headers["X-Panel-Verification"] == "pending"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.json["errorCode"] == "signal-verification-pending"
        assert "items" not in response.json and "internal" not in response.json["error"]


def test_trade_reads_use_isolated_context_and_keep_the_original_source_clock(ctx):
    seed = {"items": [{"marketId": 1}], "generatedAt": "2026-10-03T07:00:00Z", "status": "ok"}
    read_ctx = {**ctx, "query_all": object()}
    ctx.update(get_cached_json=lambda *_args: seed, alpha_context=read_ctx)
    contexts = []
    def sanitize(current, _namespace, value):
        contexts.append(current)
        return value
    with patch.object(signal_service, "_sanitize_signal_payload", side_effect=sanitize):
        for limit in (1, 10, 1):
            result = signal_service.get_whale_trades_snapshot(ctx, limit=limit)
            assert result["generatedAt"] == seed["generatedAt"] and result["status"] == "stale"
    assert contexts == [read_ctx]
    assert seed["status"] == "ok"


def test_startup_warmers_do_not_delay_serving_cached_panels(ctx):
    started, release = Event(), Event()
    runtime = ServiceRuntime.__new__(ServiceRuntime)
    runtime.resources = ctx["_resources"]
    from threading import Lock
    runtime._runtime_init_lock = Lock()
    runtime._closed = runtime._runtime_initialized = False
    runtime.SETTINGS = SimpleNamespace(snapshot_prewarm_enabled=True)
    runtime.system_health = object()
    runtime._claim_startup_prewarm_slot = lambda: True
    runtime._claim_snapshot_prewarm_owner = lambda: False
    def warm():
        started.set()
        release.wait(5)
    runtime.prewarm_critical_payloads = warm
    try:
        with patch("api.runtime.system_service.prewarm_system_health_payload"):
            before = monotonic()
            runtime.start()
            assert monotonic() - before < .5
            assert started.wait(1) and runtime._runtime_initialized
    finally:
        release.set()
