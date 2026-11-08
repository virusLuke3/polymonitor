from __future__ import annotations


from api.services import clickhouse_orderfilled_service


def test_directional_clickhouse_queries_exclude_unknown_outcomes(monkeypatch) -> None:
    captured: list[str] = []

    def fake_query(_ctx: dict, query: str, **_kwargs):
        captured.append(query)
        return []

    monkeypatch.setattr(clickhouse_orderfilled_service, "_query_json_rows", fake_query)
    monkeypatch.setattr(
        clickhouse_orderfilled_service.outcome_semantics_service,
        "directional_semantics_allowed",
        lambda _row: True,
    )
    clickhouse_orderfilled_service._attach_post_signal_metrics(
        {},
        [
            {
                "market_id": 1,
                "block_number": 100,
                "entry_yes_price": "0.4",
                "direction": "bullish",
                "outcomeSemanticsStatus": "VERIFIED",
                "logicalOutcome": "YES",
            }
        ],
    )
    assert captured
    assert "outcome_code IN (1, 2)" in captured[-1]

    captured.clear()
    clickhouse_orderfilled_service.get_alpha_volume_signal_rows({}, limit=1)
    assert captured and "f.outcome_code IN (1, 2)" in captured[-1]
    assert captured[-1].count("outcome_code IN (1, 2)") >= 3
