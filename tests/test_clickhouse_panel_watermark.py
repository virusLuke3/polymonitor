from unittest.mock import patch

from api.services import clickhouse_orderfilled_service as service


def test_canonical_watermark_reads_only_latest_partition():
    with patch.object(service, "_settings", return_value={"table": "orderfilled_fact", "database": "poly_orderfilled"}):
        sql = service._latest_fact_block_sql()
    assert "PREWHERE intDiv(block_number, 1000000)" in sql
    assert "max(toUInt64(partition))" in sql
    assert "database = 'poly_orderfilled'" in sql
    assert "max(block_number)" in sql


def test_custom_table_does_not_assume_canonical_partition_scheme():
    with patch.object(service, "_settings", return_value={"table": "custom_facts", "database": "other"}):
        assert service._latest_fact_block_sql() == "SELECT ifNull(max(block_number), 0) FROM custom_facts"


def test_recent_trades_limits_rows_before_timestamp_join():
    with patch.object(service, "_query_json_rows", return_value=[]) as query:
        assert service.get_recent_trades({"normalize_trade": lambda row: row}, limit=3) == []
    sql = query.call_args.args[1]
    assert "FROM selected f" in sql
    assert "block_number IN (SELECT block_number FROM selected)" in sql
    assert "argMax(block_time, ingested_at)" in sql
