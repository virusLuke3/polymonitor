from __future__ import annotations

from unittest.mock import patch
from urllib.parse import parse_qs, urlparse


from api.services import clickhouse_orderfilled_service


class Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return b""


def test_http_reads_carry_server_side_resource_limits() -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return Response()

    with (
        patch.dict(
            clickhouse_orderfilled_service.os.environ,
            {
                "POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL": "http://127.0.0.1:18123",
                "POLYDATA_ORDERFILLED_CLICKHOUSE_USER": "reader",
                "POLYDATA_ORDERFILLED_CLICKHOUSE_PASSWORD": "secret",
            },
            clear=False,
        ),
        patch.object(clickhouse_orderfilled_service, "urlopen", side_effect=fake_urlopen),
    ):
        assert clickhouse_orderfilled_service._query_json_rows_http(
            {"app": None}, "SELECT 1 FORMAT JSONEachRow", timeout_seconds=5.0
        ) == []

    params = parse_qs(urlparse(captured["url"]).query)
    assert params["max_threads"] == ["2"]
    assert params["cancel_http_readonly_queries_on_client_close"] == ["1"]
    assert int(params["max_execution_time"][0]) <= 6
    assert int(params["max_memory_usage"][0]) == 512 * 1024 * 1024
    assert params["query_id"][0].startswith("polydata-api-")


def test_price_series_uses_market_pruned_selection() -> None:
    with patch.object(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        return_value=[],
    ) as query:
        assert clickhouse_orderfilled_service.get_price_series(
            {"normalize_trade": lambda row: row}, 42, limit=400
        ) == []

    sql = query.call_args.args[1]
    assert "WHERE market_id = 42" in sql
    assert "FROM selected f" in sql
    assert "max(block_number), 0) FROM orderfilled_fact" not in sql


def test_http_read_is_deferred_when_process_capacity_is_full() -> None:
    class FullSlots:
        def acquire(self, *, blocking):
            assert blocking is False
            return False

    with (
        patch.dict(
            clickhouse_orderfilled_service.os.environ,
            {"POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL": "http://127.0.0.1:18123"},
            clear=False,
        ),
        patch.object(clickhouse_orderfilled_service, "_HTTP_QUERY_SLOTS", FullSlots()),
        patch.object(clickhouse_orderfilled_service, "urlopen") as urlopen,
    ):
        assert clickhouse_orderfilled_service._query_json_rows_http(
            {"app": None}, "SELECT 1", timeout_seconds=5.0
        ) is None

    urlopen.assert_not_called()
