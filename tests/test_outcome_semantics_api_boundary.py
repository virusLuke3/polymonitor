from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType

from flask import Flask


from api.services import (  # noqa: E402
    clickhouse_orderfilled_service,
    outcome_semantics_service,
    signal_service,
)
from api.services import outcome_projection as projection_ledger  # noqa: E402


EVIDENCE = "b" * 64
CONDITION = "0x" + "c" * 64
TOKEN_A_HEX = "ab" * 32
TOKEN_B_HEX = "cd" * 32
TOKEN_A = str(int(TOKEN_A_HEX, 16))
TOKEN_B = str(int(TOKEN_B_HEX, 16))


def _projection_rows(mode: str, labels: tuple[str, str], directional: bool):
    yes_no = mode == "yes_no_labels"
    record = projection_ledger.normalize_projection_record(
        {
            "market_id": 7,
            "condition_id": CONDITION,
            "semantic_mode": mode,
            "supports_yes_no_wording": yes_no,
            "supports_directional_semantics": directional,
            "evidence_origin": "api-boundary-test",
            "evidence_sha256": EVIDENCE,
            "source_slots": [
                {
                    "source_index": index,
                    "source_label": label,
                    "token_id": token,
                    "logical_outcome": logical,
                    "logical_outcome_index": index,
                }
                for index, (logical, label, token) in enumerate(
                    zip(("YES", "NO"), labels, (TOKEN_A, TOKEN_B))
                )
            ],
        }
    )
    projection_key = projection_ledger.projection_key(record)
    before_images = {"market": {}, "market_tokens": [], "token_registry_rows": [], "labels": []}
    core = {
        "schema_version": projection_ledger.PLAN_SCHEMA_VERSION,
        "projection_key": projection_key,
        "record_sha256": projection_ledger.record_digest(record),
        "record": deepcopy(record),
        "before_images": before_images,
        "expected": {
            "status": projection_ledger.PROJECTION_STATUS,
            "projected_token_count": 2,
            "label_rows_without_plan_sha256": projection_ledger.expected_labels(record),
            "immutability_contract": projection_ledger.immutability_contract(),
        },
    }
    plan = {**core, "plan_sha256": projection_ledger.record_digest(core)}
    rows = []
    for index, (logical, label, token) in enumerate(zip(("YES", "NO"), labels, (TOKEN_A, TOKEN_B))):
        rows.append(
            {
                "market_id": 7,
                "market_condition_id": CONDITION,
                "market_yes_token_id": TOKEN_A,
                "market_no_token_id": TOKEN_B,
                "registry_token_id": token,
                "registry_market_id": 7,
                "registry_condition_id": CONDITION,
                "registry_logical_outcome": logical,
                "registry_logical_outcome_index": index,
                "label_token_id": token,
                "label_market_id": 7,
                "label_condition_id": CONDITION,
                "label_source_index": index,
                "label_source_label": label,
                "label_logical_outcome": logical,
                "label_logical_outcome_index": index,
                "label_semantic_mode": mode,
                "label_supports_yes_no_wording": yes_no,
                "label_supports_directional_semantics": directional,
                "label_evidence_origin": record["evidence_origin"],
                "label_evidence_sha256": EVIDENCE,
                "label_plan_sha256": plan["plan_sha256"],
                "sync_projection_key": projection_key,
                "sync_market_id": 7,
                "sync_condition_id": CONDITION,
                "sync_plan_sha256": plan["plan_sha256"],
                "sync_status": "PROJECTED",
                "sync_projected_token_count": 2,
                "receipt_projection_key": projection_key,
                "receipt_plan_sha256": plan["plan_sha256"],
                "receipt_record_sha256": projection_ledger.record_digest(record),
                "receipt_market_id": 7,
                "receipt_condition_id": CONDITION,
                "receipt_evidence_origin": record["evidence_origin"],
                "receipt_evidence_sha256": record["evidence_sha256"],
                "receipt_record_json": deepcopy(record),
                "receipt_plan_json": deepcopy(plan),
                "receipt_before_images_json": deepcopy(before_images),
                "receipt_status": "PROJECTED",
                "known_source_first": mode == "source_first_second",
            }
        )
    return rows


def _ctx(projection_rows):
    def query_all(sql, _params=()):
        if "market_token_source_labels" in sql:
            return projection_rows
        if "SELECT yes_token_id" in sql:
            return [{"yes_token_id": TOKEN_A, "no_token_id": TOKEN_B}]
        if "SELECT id, title" in sql:
            return [{"id": 7, "title": "Projected market"}]
        return []

    return {
        "get_backend": lambda: "postgres",
        "query_all": query_all,
        "normalize_trade": lambda row: dict(row),
        "app": None,
    }


def test_clickhouse_raw_trade_uses_exact_token_label_and_keeps_logical_slot(monkeypatch):
    def read(_ctx, query, *, timeout_seconds=1.8):
        if 'AS latest_block' in query:
            return [{'latest_block': 100, 'first_block': 100}]
        if 'FROM block_timestamps' in query:
            return [{'block_number': 100, 'timestamp': '2026-09-28T00:00:00Z'}]
        assert 'AND token_id IN' in query
        return [{
            "market_id": 7, "block_number": 100, "token_id": TOKEN_A_HEX,
            "outcome": "YES", "side": "BUY", "price": "0.6", "size": "10",
        }]

    monkeypatch.setattr(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        read,
    )

    rows = clickhouse_orderfilled_service.get_market_trades(
        _ctx(_projection_rows("up_down_labels", ("Up", "Down"), True)),
        7,
    )

    assert rows is not None
    assert rows[0]["outcome"] == "Up"
    assert rows[0]["sourceOutcomeLabel"] == "Up"
    assert rows[0]["logicalOutcome"] == "YES"
    assert rows[0]["outcomeSemanticsCapabilities"]["supportsDirectionalSemantics"] is True


def test_clickhouse_market_trade_discards_a_row_with_another_token(monkeypatch):
    def read(_ctx, query, *, timeout_seconds=1.8):
        if 'AS latest_block' in query:
            return [{'latest_block': 100, 'first_block': 100}]
        if 'FROM block_timestamps' in query:
            return [{'block_number': 100, 'timestamp': '2026-09-28T00:00:00Z'}]
        assert 'AND token_id IN' in query
        return [{
            "market_id": 7, "block_number": 100, "token_id": "ef" * 32,
            "outcome": "YES", "side": "BUY",
        }]

    monkeypatch.setattr(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        read,
    )

    rows = clickhouse_orderfilled_service.get_market_trades(
        _ctx(_projection_rows("up_down_labels", ("Up", "Down"), True)),
        7,
    )

    assert rows == []


def test_clickhouse_non_directional_modes_cannot_escape_as_alpha(monkeypatch):
    monkeypatch.setattr(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        lambda _ctx, _query, timeout_seconds=1.8: [
            {
                "market_id": 7,
                "outcome": "YES",
                "direction": "bullish",
                "side": "BUY",
                "latest_block": 100,
                "entry_yes_price": "0.6",
                "score": "90",
            }
        ],
    )

    for mode, labels in (
        ("yes_no_labels", ("Yes", "No")),
        ("source_first_second", ("Lakers", "Celtics")),
    ):
        rows = clickhouse_orderfilled_service.get_alpha_volume_signal_rows(
            _ctx(_projection_rows(mode, labels, False)),
            limit=4,
        )
        assert rows == []










def test_cached_alpha_market_item_cannot_self_attest_without_current_identity():
    stale = {
        "status": "ok",
        "items": [
            {
                "kind": "whale",
                "marketId": 7,
                "bias": "bullish",
                "outcome": "Up",
                "outcomeSemanticsValid": True,
                "outcomeSemanticsCapabilities": {"supportsDirectionalSemantics": True},
            }
        ],
    }
    ctx = {
        "get_backend": lambda: "postgres",
        "query_all": lambda _sql, _params=(): (_ for _ in ()).throw(RuntimeError("db down")),
        "app": None,
    }

    from api.services.alpha_signal_service import AlphaVerificationUnavailable
    with pytest.raises(AlphaVerificationUnavailable, match="could not be checked"):
        signal_service._sanitize_signal_payload(
            ctx, signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA, stale,
        )
    # A failed verification remains an error and cannot manufacture an empty success.
    assert stale["items"] and stale["status"] == "ok"


def test_cached_alpha_raw_item_still_requires_token_when_projection_is_current():
    stale = {
        "status": "ok",
        "items": [
            {
                "kind": "whale",
                "marketId": 7,
                "outcome": "Up",
                "logicalOutcome": "YES",
                "outcomeSemanticsValid": True,
                "outcomeSemanticsCapabilities": {"supportsDirectionalSemantics": True},
            }
        ],
    }

    sanitized = signal_service._sanitize_signal_payload(
        _ctx(_projection_rows("up_down_labels", ("Up", "Down"), True)),
        signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA,
        stale,
    )

    assert sanitized["items"] == []


def test_cached_alpha_capability_field_is_overwritten_by_current_projection():
    stale = {
        "status": "ok",
        "items": [
            {
                "kind": "whale",
                "marketId": 7,
                "tokenId": TOKEN_A,
                "outcome": "Yes",
                "logicalOutcome": "YES",
                "outcomeSemanticsValid": True,
                "supportsDirectionalSemantics": True,
                "outcomeSemanticsCapabilities": {"supportsDirectionalSemantics": True},
            }
        ],
    }

    sanitized = signal_service._sanitize_signal_payload(
        _ctx(_projection_rows("yes_no_labels", ("Yes", "No"), False)),
        signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA,
        stale,
    )

    assert sanitized["items"] == []


def test_cached_alpha_item_without_market_identity_cannot_self_attest():
    stale = {
        "status": "ok",
        "items": [
            {
                "kind": "whale",
                "outcome": "Up",
                "outcomeSemanticsValid": True,
                "outcomeSemanticsIdentityMode": "raw",
                "outcomeSemanticsCapabilities": {"supportsDirectionalSemantics": True},
            }
        ],
    }

    sanitized = signal_service._sanitize_signal_payload(
        {},
        signal_service.SIGNAL_SNAPSHOT_NAMESPACE_ALPHA,
        stale,
    )

    assert sanitized["items"] == []






# These SQL fixtures model the canonical store; primary tests opt in explicitly.
import pytest
pytestmark = pytest.mark.usefixtures("legacy_orderfilled_store")
