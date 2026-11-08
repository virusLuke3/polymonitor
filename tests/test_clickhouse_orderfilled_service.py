from __future__ import annotations

import pytest


from api.services import clickhouse_orderfilled_service



# These SQL assertions intentionally exercise the supported compatibility schema.
pytestmark = pytest.mark.usefixtures("canonical_orderfilled_store")

def test_market_trades_falls_back_to_canonical_market_tokens(monkeypatch):
    queries: list[str] = []

    def fake_query_json_rows(ctx, query, *, timeout_seconds=1.8):
        queries.append(query)
        if 'AS latest_block' in query:
            return [{'latest_block': 88548039, 'first_block': 88548039}]
        if 'FROM block_timestamps' in query:
            return [{'block_number': 88548039, 'timestamp': '2026-06-15T12:37:24Z'}]
        assert 'FROM orderfilled_fact' in query
        return [
            {
                "tx_hash": "0xabc",
                "log_index": 7,
                "market_id": 1988103,
                "maker": "0xmaker",
                "taker": "0xtaker",
                "price": "0.53",
                "size": "10",
                "side": "BUY",
                "outcome": "YES",
                "token_id": "5d5506f45b3f09c6415469bdfb09129e313733d1f08cbb15ccbabaf271c19b93",
                "timestamp": "2026-06-15T12:37:24Z",
                "block_number": 88548039,
            }
        ]

    monkeypatch.setattr(clickhouse_orderfilled_service, "_query_json_rows", fake_query_json_rows)

    ctx = {
        "query_all": lambda sql, params: [
            {
                "yes_token_id": "42215324917064355260399497141598209646038001425434350600988074491246907857811",
                "no_token_id": "14345569253404797783338971051362654543283364899603018299935086291225869730704",
                "clob_token_ids": [],
            }
        ],
        "normalize_trade": lambda row: dict(row),
        "app": None,
    }

    rows = clickhouse_orderfilled_service.get_market_trades(ctx, 2014865, limit=12)

    assert rows is not None
    assert rows[0]["market_id"] == 2014865
    assert rows[0]["timestamp"] == "2026-06-15T12:37:24Z"
    assert len(queries) == 3
    assert "AND token_id IN" in queries[1]
    assert "block_number BETWEEN 88548039 AND 88548039" in queries[1]
    assert "f.market_id = 2014865" not in queries[1]
    assert "5d5506f45b3f09c6415469bdfb09129e313733d1f08cbb15ccbabaf271c19b93" in queries[1]
    assert "block_number IN (88548039)" in queries[2]
