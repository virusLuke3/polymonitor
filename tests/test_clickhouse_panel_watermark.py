from api.config import ClickHouseSettings
from unittest.mock import patch

from api.services import clickhouse_orderfilled_service as service


def test_canonical_watermark_reads_only_latest_partition():
    with patch.object(
        service, "_settings", return_value=ClickHouseSettings(table="orderfilled_fact", database="poly_orderfilled")
    ):
        sql = service._latest_fact_block_sql({})
    assert "PREWHERE intDiv(block_number, 1000000)" in sql
    assert "max(toUInt64(partition))" in sql
    assert "database = 'poly_orderfilled'" in sql
    assert "max(block_number)" in sql


def test_custom_table_does_not_assume_canonical_partition_scheme():
    with patch.object(service, "_settings", return_value=ClickHouseSettings(table="custom_facts", database="other")):
        assert service._latest_fact_block_sql({}) == "SELECT ifNull(max(block_number), 0) FROM custom_facts"


def test_recent_trades_limits_rows_before_timestamp_lookup():
    with patch.object(
        service,
        "_query_json_rows",
        side_effect=[
            [{"first_block": 100, "last_block": 200}],
            [{"market_id": 1, "block_number": 180, "log_index": 1, "token_id": "1" * 64, "tx_hash": "a" * 64}],
            [{"block_number": 180, "log_index": 1, "token_id": "0x" + "1" * 64, "tx_hash": "0x" + "a" * 64}],
            [{"block_number": 180, "timestamp": "2026-09-29T01:00:00Z"}],
        ],
    ) as query:
        rows = service.get_recent_trades({"normalize_trade": lambda row: row}, limit=3)
    assert rows[0]["timestamp"] == "2026-09-29T01:00:00Z"
    assert "LIMIT 3" in query.call_args_list[1].args[1]
    assert "block_number IN (180)" in query.call_args.args[1]
    assert "SELECT block_number FROM selected" not in query.call_args.args[1]
