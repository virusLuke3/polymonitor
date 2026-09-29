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


def test_whale_window_uses_clock_and_one_fact_scan_without_repeating_watermark():
    with patch.object(clickhouse_orderfilled_service, "_query_json_rows", side_effect=[
        [{"first_block": 93999000, "last_block": 94003000}], [],
    ]) as read:
        assert clickhouse_orderfilled_service.get_volume_whale_rows({}, limit=14) == []
    window, facts = [call.args[1] for call in read.call_args_list]
    assert "block_time BETWEEN now() - INTERVAL 60 MINUTE AND now()" in window
    assert "BETWEEN 93 AND 94" in facts
    assert "block_number BETWEEN 93999000 AND 94003000" in facts
    assert facts.count("FROM orderfilled_fact") == 1
    assert "max(block_number)" not in facts
    assert "quantilesTDigest(0.99, 0.995, 0.999)" in facts


def test_recent_window_missing_is_unavailable_not_an_empty_trade_feed():
    with patch.object(clickhouse_orderfilled_service, "_query_json_rows", return_value=[
        {"first_block": 0, "last_block": 0},
    ]) as read:
        assert clickhouse_orderfilled_service.get_recent_trades({}) is None
    assert read.call_count == 1


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


def test_streamed_query_error_discards_partial_rows_without_falling_back_to_docker():
    class PartialResponse(Response):
        def read(self):
            return b'{"block_number": 50}\nCode: 158. DB::Exception: Limit exceeded\n'

    with (
        patch.dict(clickhouse_orderfilled_service.os.environ, {"POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL": "http://localhost"}),
        patch.object(clickhouse_orderfilled_service, "urlopen", return_value=PartialResponse()),
        patch.object(clickhouse_orderfilled_service.subprocess, "run") as docker,
    ):
        assert clickhouse_orderfilled_service._query_json_rows({"app": object()}, "SELECT 1") is None
    docker.assert_not_called()


def test_market_trades_expand_disjoint_windows_keep_legacy_owner_and_join_times_once():
    queries = []
    rows = [
        {"market_id": 999, "token_id": "0x" + "1".zfill(64), "block_number": 49999, "log_index": 3, "tx_hash": "a" * 64},
        {"market_id": 7, "token_id": "0x" + "2".zfill(64), "block_number": 29999, "log_index": 2, "tx_hash": "b" * 64},
    ]
    responses = iter([
        [{"latest_block": 50000, "first_block": 0}], rows[:1], rows[1:],
        [{"block_number": 49999, "timestamp": "2026-09-28T00:00:00Z"}],
    ])

    def read(_ctx, sql, **_kwargs):
        queries.append(sql)
        return next(responses)

    context = {"query_all": lambda *a: [{"yes_token_id": "1", "no_token_id": "2"}], "normalize_trade": lambda row: row}
    with patch.object(clickhouse_orderfilled_service, "_query_json_rows", side_effect=read):
        result = clickhouse_orderfilled_service.get_market_trades(context, 7, limit=2)
    assert [r["block_number"] for r in result] == [49999, 29999]
    assert [r["market_id"] for r in result] == [7, 7]
    assert result[0]["timestamp"] == "2026-09-28T00:00:00Z" and result[1]["timestamp"] is None
    assert "BETWEEN 30001 AND 50000" in queries[1]
    assert "BETWEEN 0 AND 30000" in queries[2]
    assert "market_id = 7" not in queries[1]
    assert "block_number IN (49999, 29999)" in queries[3]
    assert sum("FROM block_timestamps" in sql for sql in queries) == 1


def test_trade_cursor_keeps_same_block_events_and_source_failure_is_not_empty():
    import pytest
    context = {"query_all": lambda *a: [{"yes_token_id": "1", "no_token_id": "2"}], "normalize_trade": lambda row: row}
    with patch.object(clickhouse_orderfilled_service, "_query_json_rows", side_effect=[
        [{"latest_block": 100, "first_block": 0}], [],
    ]) as read:
        assert clickhouse_orderfilled_service.get_market_trades(context, 7, before=(50, 3, "a" * 64)) == []
    sql = read.call_args.args[1]
    assert "BETWEEN 0 AND 50" in sql
    assert "(block_number, log_index, tx_hash) < (50, 3," in sql
    with patch.object(clickhouse_orderfilled_service, "_query_json_rows", return_value=None):
        with pytest.raises(TimeoutError, match="source unavailable"):
            clickhouse_orderfilled_service.get_market_trades(context, 7)
    with patch.object(clickhouse_orderfilled_service, "_query_json_rows", side_effect=[
        [{"latest_block": 90000000, "first_block": 1000000}], *([[]] * 8),
    ]):
        with pytest.raises(TimeoutError, match="bounded read window"):
            clickhouse_orderfilled_service.get_market_trades(context, 7)


def test_trade_watermark_reuses_existing_cache_without_repeating_fact_scan():
    cache = {}
    context = {
        "query_all": lambda *a: [{"yes_token_id": "1", "no_token_id": "2"}], "normalize_trade": lambda row: row,
        "get_cached_json": lambda namespace, key: cache.get((namespace, key)),
        "set_cached_json": lambda namespace, key, value, ttl_seconds: cache.update({(namespace, key): value}),
    }
    with patch.object(clickhouse_orderfilled_service, "_query_json_rows", side_effect=[
        [{"latest_block": 100, "first_block": 0}], [], [],
    ]) as read:
        assert clickhouse_orderfilled_service.get_market_trades(context, 7) == []
        assert clickhouse_orderfilled_service.get_market_trades(context, 7) == []
    assert sum("AS latest_block" in call.args[1] for call in read.call_args_list) == 1
