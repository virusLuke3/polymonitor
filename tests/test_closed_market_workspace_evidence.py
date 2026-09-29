from __future__ import annotations

from unittest.mock import Mock, patch


from api.services import clickhouse_orderfilled_service, market_service, market_workspace_cache_service
from api.context import RuntimeResources


class _Logger:
    def info(self, *_args, **_kwargs) -> None:
        pass

    def warning(self, *_args, **_kwargs) -> None:
        pass

    def exception(self, *_args, **_kwargs) -> None:
        pass


class _SnapshotStore:
    def __init__(self) -> None:
        self.writes = []

    def set(self, namespace, cache_key, payload, ttl_seconds):
        self.writes.append((namespace, cache_key, payload, ttl_seconds))
        return True


def test_stale_flow_preserves_generation_time_and_propagates_status():
    original = {"items": [{"blockNumber": 7}], "generatedAt": "2026-09-28T10:00:00Z"}
    stale = market_workspace_cache_service._with_cache_meta(original, "flow", "stale-hit", "7")
    memory = market_workspace_cache_service._with_cache_meta(stale, "flow", "memory-hit", "7")
    assert memory["status"] == "stale"
    assert memory["marketWorkspaceCache"]["generatedAt"] == original["generatedAt"]
    assert "status" not in original


def test_chart_reads_once_without_nested_cache_or_legacy_trade_fallback():
    from types import SimpleNamespace

    deps = SimpleNamespace(serving=SimpleNamespace(table_exists=lambda _: False), source={})
    for source_rows, status in (([], "missing"), (None, "unavailable")):
        with patch.object(clickhouse_orderfilled_service, "get_price_series", return_value=source_rows) as read:
            result = market_service._get_market_chart_payload(
                deps, 7, market={"id": 7}, price={"volume24h": "1"}, include_runtime_series=False,
            )
        read.assert_called_once_with({}, 7, limit=400)
        assert result["points"] == [] and result["historyStatus"] == status


def test_workspace_evidence_preserves_missing_price_and_oracle_identity_mismatch() -> None:
    identity = {"conditionId": "0xabc"}
    oracle = {"marketId": 8, "timeline": []}
    health = market_service._workspace_health(
        market_id=7, identity=identity, price=None, chart=None,
        oracle_payload=oracle, diagnostics=None, group=None,
        selected_outcome=None, serving_source="postgres",
    )
    evidence = market_service._workspace_evidence(
        market_id=7, identity=identity, price=None, chart=None, trades=[],
        oracle_payload=oracle, group=None, health=health,
        serving_source="postgres", serving_updated_at=None,
        generated_at="2026-09-28T00:00:00Z",
    )

    assert health["level"] == "critical"
    claims = {claim["id"]: claim for claim in evidence["claims"]}
    assert claims["price"]["status"] == "missing"
    assert claims["price"]["recordCount"] == 0
    assert claims["oracle"]["status"] == "mismatch"
    assert evidence["issues"] == ["oracle-market-id-mismatch"]


def test_market_orderfilled_keeps_missing_block_timestamp_unknown() -> None:
    row = {
        "tx_hash": "ab" * 32,
        "log_index": 7,
        "market_id": 3712655,
        "token_id": "0x" + ("0" * 63) + "1",
        "timestamp": None,
        "block_number": 777,
    }

    def query_all(sql, _params):
        if "SELECT yes_token_id, no_token_id FROM core.markets" in sql:
            return [{"yes_token_id": "1", "no_token_id": "2"}]
        raise RuntimeError("semantic evidence database unavailable")

    with patch.object(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        side_effect=[[{"latest_block": 777, "first_block": 0}], [row], []],
    ) as query:
        actual = clickhouse_orderfilled_service.get_market_trades(
            {"normalize_trade": lambda value: value, "query_all": query_all},
            3712655,
        )

    assert actual is not None
    assert actual[0]["timestamp"] is None
    assert actual[0]["block_number"] == 777
    assert actual[0]["outcome"] is None
    assert actual[0]["outcomeSemanticsStatus"] == "semantics_database_unavailable"
    sql = query.call_args.args[1]
    assert "now('UTC')" not in sql
    assert "addSeconds(anchor_time" not in sql


def test_market_price_series_omits_rows_without_real_block_timestamp() -> None:
    row = {
        "outcome": "YES",
        "price": "0.42",
        "timestamp": None,
        "block_number": 777,
        "log_index": 7,
    }
    with patch.object(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        return_value=[row],
    ) as query:
        actual = clickhouse_orderfilled_service.get_price_series({}, 3712655)

    assert actual == []
    sql = query.call_args.args[1]
    assert "now('UTC')" not in sql
    assert "addSeconds(anchor_time" not in sql


def test_closed_market_replaces_stale_orderbook_with_authoritative_empty_payload() -> None:
    stale_lob = {
        "marketId": 3712655,
        "bookStatus": "ok",
        "yes": {"bids": [{"price": "0.40", "size": "10"}], "asks": []},
        "no": {"bids": [], "asks": []},
    }
    snapshot_store = _SnapshotStore()
    dependencies = market_workspace_cache_service.MarketWorkspaceCacheDependencies(
        resources=RuntimeResources(),
        cache=Mock(),
        build_detail=Mock(), build_chart=Mock(), build_flow=Mock(), build_lob=Mock(),
        get_market_by_id=lambda market_id: {"id": market_id, "status": "Closed", "is_trading_closed": True},
        application=type("App", (), {"logger": _Logger()})(),
        snapshot_store=snapshot_store,
        utc_now_iso=lambda: "2026-08-16T08:00:00Z",
    )
    runtime_writes = []
    redis_writes = []
    with (
        patch.object(
            market_workspace_cache_service.api_cache,
            "get_cached_runtime_payload",
            return_value=stale_lob,
        ),
        patch.object(
            market_workspace_cache_service.api_cache,
            "set_cached_runtime_payload",
            side_effect=lambda *args: runtime_writes.append(args),
        ),
        patch.object(
            market_workspace_cache_service.api_cache,
            "set_cached_payload",
            side_effect=lambda *args: redis_writes.append(args),
        ),
    ):
        actual = market_workspace_cache_service.get_market_orderbook_payload(
            dependencies,
            3712655,
        )

    assert actual["bookStatus"] == "closed"
    dependencies.build_lob.assert_not_called()
    assert not market_workspace_cache_service._lob_has_levels(actual)
    assert runtime_writes
    assert redis_writes
    assert snapshot_store.writes
    assert not market_workspace_cache_service._lob_has_levels(snapshot_store.writes[-1][2])


def test_detail_builder_does_not_read_chart_or_trades():
    deps = market_service.MarketDetailDependencies(
        source={}, application=Mock(), lookup=Mock(), serving=Mock(), price=Mock(), oracle=Mock(),
        normalize_market=lambda row: dict(row), utc_now_iso=lambda: "2026-09-28T00:00:00Z",
    )
    with (
        patch.object(market_service, "_get_market_by_id", return_value={"id": 7, "condition_id": "c"}) as lookup,
        patch.object(market_service, "_read_market_workspace_detail_payload", return_value={
            "price": {"latestYesPrice": "0.4"}, "chart": {"points": ["stale"]}, "trades": ["stale"],
        }),
        patch.object(market_service, "_get_market_oracle_payload", return_value={"timeline": []}),
        patch.object(market_service, "_get_market_chart_payload", side_effect=AssertionError("unexpected chart read")),
        patch.object(market_service, "get_trades_by_market_id", side_effect=AssertionError("unexpected trade read")),
    ):
        payload = market_service.get_market_detail_payload(deps, 7)
    lookup.assert_called_once()
    assert "chart" not in payload and "trades" not in payload
    assert payload["health"]["chartStatus"] == "not-loaded"
    assert next(c for c in payload["evidence"]["claims"] if c["id"] == "trades")["status"] == "not-loaded"
    combined = market_service.assemble_market_workspace(
        payload, chart={"points": [], "historyStatus": "missing"},
        flow={"items": [], "status": "unavailable"}, lob={"bookStatus": "live"},
    )
    assert combined["health"]["lobStatus"] == "live"
    assert next(c for c in combined["evidence"]["claims"] if c["id"] == "trades")["status"] == "unavailable"


def test_cache_builds_share_admission_and_deduplicate_cold_and_background_reads():
    import threading
    from api.cache import CacheState

    resources = RuntimeResources(workspace_slots=threading.BoundedSemaphore(1))
    store = Mock()
    store.get.return_value = store.get_stale.return_value = None
    app = Mock()
    deps = market_workspace_cache_service.MarketWorkspaceCacheDependencies(
        resources=resources, cache=CacheState(resources, app, store), application=app, snapshot_store=store,
        build_detail=Mock(), build_chart=Mock(), build_flow=Mock(), build_lob=Mock(), get_market_by_id=Mock(),
        utc_now_iso=lambda: "now",
    )
    started, release = threading.Event(), threading.Event()

    def build():
        started.set()
        assert release.wait(2)
        return {"market": {"id": 7}}

    builder = Mock(side_effect=build)
    kwargs = dict(layer="detail", cache_key="7", ttl_seconds=120, builder=builder)
    try:
        first = market_workspace_cache_service._cached_layer(deps, **kwargs, background_only=True)
        assert first["mode"] == "warming" and started.wait(1)
        assert market_workspace_cache_service._cached_layer(deps, **kwargs)["mode"] == "warming"
        assert market_workspace_cache_service._cached_layer(deps, **dict(kwargs, cache_key="8"))["mode"] == "warming"
        builder.assert_called_once()
    finally:
        release.set()
        resources.close()
    assert market_workspace_cache_service._cached_layer(deps, **kwargs)["mode"] == "memory-hit"
    assert not resources.workspace_refreshing
    assert market_workspace_cache_service._cached_layer(deps, **dict(kwargs, cache_key="8"))["mode"] == "warming"
    builder.assert_called_once()


def test_failed_build_releases_local_and_redis_leases():
    import threading
    from api.cache import CacheState

    resources = RuntimeResources(workspace_slots=threading.BoundedSemaphore(1))
    store, app, redis = Mock(), Mock(), Mock()
    store.get.return_value = store.get_stale.return_value = None
    redis.get.return_value = None
    deps = market_workspace_cache_service.MarketWorkspaceCacheDependencies(
        resources=resources, cache=CacheState(resources, app, store, redis_url="redis://test", redis_module=Mock(), redis_client=redis),
        application=app, snapshot_store=store, build_detail=Mock(), build_chart=Mock(), build_flow=Mock(),
        build_lob=Mock(), get_market_by_id=Mock(), utc_now_iso=lambda: "now",
    )
    try:
        result = market_workspace_cache_service._cached_layer(
            deps, layer="flow", cache_key="7", ttl_seconds=8, builder=Mock(side_effect=TimeoutError),
        )
        assert result["payload"]["status"] == "unavailable"
        redis.lock.return_value.release.assert_called_once()
        redis.lock.assert_called_once_with("polydata:build:snapshot:market-workspace:flow:7", timeout=180, thread_local=False)
        assert not resources.workspace_refreshing
        assert resources.workspace_slots.acquire(blocking=False)
        resources.workspace_slots.release()
        redis.lock.return_value.acquire.return_value = False
        builder = Mock()
        result = market_workspace_cache_service._cached_layer(
            deps, layer="flow", cache_key="8", ttl_seconds=8, builder=builder,
        )
        assert result["mode"] == "warming" and not resources.workspace_refreshing
        builder.assert_not_called()
        assert resources.workspace_slots.acquire(blocking=False)
        resources.workspace_slots.release()
    finally:
        resources.close()


def test_replaced_market_does_not_trigger_other_workspace_layers():
    error = {"_status": 409, "error": "superseded"}
    with (
        patch.object(market_workspace_cache_service, "get_market_detail_payload", return_value=error),
        patch.object(market_workspace_cache_service, "_cached_layer", return_value={"payload": error}) as cache,
    ):
        deps = Mock()
        assert market_workspace_cache_service.get_market_workspace_payload(deps, 7) == error
        cache.assert_not_called()
        assert market_workspace_cache_service.get_market_focus_tile_payload(deps, 7) == error
        cache.assert_called_once()


def test_market_trade_route_cursor_validation_and_unavailable_status():
    from flask import Flask
    from api.routes.markets import MarketRouteDependencies, create_markets_blueprint
    read = Mock(return_value=[])
    app = Flask(__name__)
    app.register_blueprint(create_markets_blueprint(MarketRouteDependencies.from_context({
        "get_trades_by_market_id": read,
        "get_market_by_slug": lambda slug: {"id": 7},
    })))
    client = app.test_client()
    for market in ("7", "example-slug"):
        read.reset_mock()
        assert client.get(f"/markets/{market}/trades?before=50:3:" + "a" * 64).status_code == 200
        read.assert_called_once_with(7, limit=100, offset=0, before=(50, 3, "a" * 64))
        for query in ("before=bad", "offset=5001", "before=1:2:" + "b" * 64 + "&offset=1"):
            assert client.get(f"/markets/{market}/trades?" + query).status_code == 400
    read.side_effect = TimeoutError("source unavailable")
    response = client.get("/markets/7/trades")
    assert response.status_code == 503 and response.get_json()["status"] == "unavailable"
