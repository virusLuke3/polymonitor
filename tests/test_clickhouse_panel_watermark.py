from api.config import ClickHouseSettings
from unittest.mock import patch
import pytest

from api.services import clickhouse_orderfilled_service as service


def test_canonical_watermark_reads_only_latest_partition(canonical_orderfilled_store):
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


def test_primary_watermark_continues_past_newer_raw_only_partition(primary_orderfilled_store):
    with patch.object(service, '_settings', return_value=ClickHouseSettings(table='orderfilled_fact')):
        with patch.object(service, '_query_json_rows', side_effect=[
            [{'partition': '97'}, {'partition': '96'}, {'partition': '95'}],
            [{'latest_block': '0'}], [{'latest_block': '96999999'}],
        ]) as query:
            assert service._latest_fact_block_sql({}) == 'SELECT toUInt64(96999999)'
    assert query.call_count == 3
    assert 'intDiv(block_number,1000000)=97' in query.call_args_list[1].args[1]
    assert 'intDiv(block_number,1000000)=96' in query.call_args_list[2].args[1]


def test_primary_watermark_failure_does_not_become_empty_history(primary_orderfilled_store):
    with patch.object(service, '_settings', return_value=ClickHouseSettings(table='orderfilled_fact')):
        with patch.object(service, '_query_json_rows', side_effect=[[{'partition': '96'}], None]):
            with pytest.raises(TimeoutError, match='unavailable'):
                service._latest_fact_block_sql({})


@pytest.mark.parametrize('flag,column', [('0','block_number'), ('1','canonical_block_number')])
def test_bounded_fact_read_uses_indexed_block_coordinate(monkeypatch, flag, column):
    monkeypatch.setenv('POLYDATA_ORDERFILLED_PRIMARY_STORE', flag)
    ctx = {'get_cached_json': lambda *args: {'latest_block': 96000100, 'first_block': 35000000}}
    with patch.object(service, '_settings', return_value=ClickHouseSettings(table='orderfilled_fact')):
        with patch.object(service, '_query_json_rows', side_effect=[
            [{'block_number': '96000099', 'log_index': 1, 'tx_hash': 'a'*64}],
            [{'block_number': '96000099', 'timestamp': '2026-10-01T00:00:00Z'}],
        ]) as query:
            rows = service._read_fact_trades(ctx, "token_id IN ('"+'b'*64+"')", limit=1)
    assert rows[0]['timestamp'] == '2026-10-01T00:00:00Z'
    assert 'intDiv('+column+', 1000000) BETWEEN' in query.call_args_list[0].args[1]
    assert 'AND '+column+' BETWEEN' in query.call_args_list[0].args[1]


def test_recent_trades_limits_rows_before_timestamp_lookup(canonical_orderfilled_store):
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
