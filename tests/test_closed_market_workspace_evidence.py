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
        return_value=[row],
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
