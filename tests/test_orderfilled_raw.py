from datetime import datetime, timezone

from trade.orderfilled_raw import (
    compare_orderfilled_raw_event_keys,
    normalize_block_time,
)


def test_normalize_block_time_uses_sql_null_for_missing_or_invalid_values() -> None:
    assert normalize_block_time(None) is None
    assert normalize_block_time("") is None
    assert normalize_block_time("not-a-timestamp") is None


def test_normalize_block_time_normalizes_to_utc() -> None:
    value = datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc)

    assert normalize_block_time(value) == "2026-08-02 09:00:00"


def test_raw_event_key_comparison_normalizes_exact_chain_identity() -> None:
    contract = "0x" + "ab" * 20
    tx_hash = "0x" + "cd" * 32

    result = compare_orderfilled_raw_event_keys(
        [(contract.upper(), tx_hash.upper(), 7)],
        [(contract, tx_hash, 7)],
    )

    assert result["exact"] is True
    assert result["missing_keys"] == 0
    assert result["extra_keys"] == 0
    assert result["chain_duplicate_rows"] == 0
    assert result["sink_duplicate_rows"] == 0


def test_raw_event_key_comparison_rejects_missing_extra_and_duplicates() -> None:
    contract = "0x" + "ab" * 20
    expected_tx = "0x" + "cd" * 32
    stale_tx = "0x" + "ef" * 32

    result = compare_orderfilled_raw_event_keys(
        [(contract, expected_tx, 7)],
        [(contract, stale_tx, 8), (contract, stale_tx, 8)],
    )

    assert result["exact"] is False
    assert result["missing_keys"] == 1
    assert result["extra_keys"] == 1
    assert result["sink_duplicate_rows"] == 1
