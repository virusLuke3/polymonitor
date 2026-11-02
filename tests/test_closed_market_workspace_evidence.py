from __future__ import annotations
from conftest import missing_route_dependency
from api.routes import markets as _route_markets

from unittest.mock import Mock, patch


from api.services import clickhouse_orderfilled_service
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
    ) as query, patch.object(clickhouse_orderfilled_service, "_latest_fact_block_sql", return_value="SELECT 777"):
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












def test_market_trade_route_cursor_validation_and_unavailable_status():
    from flask import Flask
    from api.routes.markets import MarketRouteDependencies, create_markets_blueprint

    read = Mock(return_value=[])
    app = Flask(__name__)
    app.register_blueprint(
        create_markets_blueprint(
            MarketRouteDependencies(
                sanitize_payload=lambda payload, **kw: (
                    _route_markets.outcome_semantics_service.sanitize_public_market_payload(
                        {
                            "query_all": {
                                "get_trades_by_market_id": read,
                                "get_market_by_slug": lambda slug: {"id": 7},
                            }.get("query_all", None),
                            "get_backend": {
                                "get_trades_by_market_id": read,
                                "get_market_by_slug": lambda slug: {"id": 7},
                            }.get("get_backend", None),
                        },
                        payload,
                        **kw,
                    )
                ),
                get_markets_payload={"get_trades_by_market_id": read, "get_market_by_slug": lambda slug: {"id": 7}}.get(
                    "get_markets_payload", missing_route_dependency
                ),
                get_market_by_id={"get_trades_by_market_id": read, "get_market_by_slug": lambda slug: {"id": 7}}.get(
                    "get_market_by_id", missing_route_dependency
                ),
                get_market_by_slug={"get_trades_by_market_id": read, "get_market_by_slug": lambda slug: {"id": 7}}.get(
                    "get_market_by_slug", missing_route_dependency
                ),
                normalize_market={"get_trades_by_market_id": read, "get_market_by_slug": lambda slug: {"id": 7}}.get(
                    "normalize_market", missing_route_dependency
                ),
                get_trades_by_market_id={
                    "get_trades_by_market_id": read,
                    "get_market_by_slug": lambda slug: {"id": 7},
                }.get("get_trades_by_market_id", missing_route_dependency),
                get_recent_trades_snapshot={
                    "get_trades_by_market_id": read,
                    "get_market_by_slug": lambda slug: {"id": 7},
                }.get("get_recent_trades_snapshot", missing_route_dependency),
                get_market_oracle_payload={
                    "get_trades_by_market_id": read,
                    "get_market_by_slug": lambda slug: {"id": 7},
                }.get("get_market_oracle_payload", missing_route_dependency),
                get_recent_oracle_snapshot={
                    "get_trades_by_market_id": read,
                    "get_market_by_slug": lambda slug: {"id": 7},
                }.get("get_recent_oracle_snapshot", missing_route_dependency),
                get_market_detail_payload={
                    "get_trades_by_market_id": read,
                    "get_market_by_slug": lambda slug: {"id": 7},
                }.get("get_market_detail_payload", missing_route_dependency),
                get_market_chart_payload={
                    "get_trades_by_market_id": read,
                    "get_market_by_slug": lambda slug: {"id": 7},
                }.get("get_market_chart_payload", missing_route_dependency),
                get_market_workspace_payload={
                    "get_trades_by_market_id": read,
                    "get_market_by_slug": lambda slug: {"id": 7},
                }.get("get_market_workspace_payload", missing_route_dependency),
                get_market_focus_tile_payload={
                    "get_trades_by_market_id": read,
                    "get_market_by_slug": lambda slug: {"id": 7},
                }.get("get_market_focus_tile_payload", missing_route_dependency),
            )
        )
    )
    client = app.test_client()
    for market in ("7", "example-slug"):
        read.reset_mock()
        assert client.get(f"/markets/{market}/trades?before=50:3:" + "a" * 64).status_code == 200
        read.assert_called_once_with(7, limit=50, offset=0, before=(50, 3, "a" * 64))
        for query in ("before=bad", "offset=5001", "before=1:2:" + "b" * 64 + "&offset=1"):
            assert client.get(f"/markets/{market}/trades?" + query).status_code == 400
    read.side_effect = TimeoutError("source unavailable")
    response = client.get("/markets/7/trades")
    assert response.status_code == 503 and response.get_json()["status"] == "unavailable"
