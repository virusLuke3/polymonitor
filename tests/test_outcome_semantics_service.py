from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType

import pytest
from flask import Flask


from api.services import outcome_semantics_service
from api.services import outcome_projection as projection_ledger


EVIDENCE = "b" * 64
CONDITION = "0x" + "c" * 64


def _ledger(
    mode: str,
    labels: tuple[str, str],
    *,
    directional: bool,
    yes_no: bool,
    tokens: tuple[str, str],
):
    record = {
        "market_id": 7,
        "condition_id": CONDITION,
        "semantic_mode": mode,
        "supports_yes_no_wording": yes_no,
        "supports_directional_semantics": directional,
        "evidence_origin": "unit-test-evidence",
        "evidence_sha256": EVIDENCE,
        "source_slots": [
            {
                "source_index": index,
                "source_label": label,
                "token_id": token,
                "logical_outcome": logical,
                "logical_outcome_index": index,
            }
            for index, (logical, label, token) in enumerate(zip(("YES", "NO"), labels, tokens))
        ],
    }
    record = projection_ledger.normalize_projection_record(record)
    projection_key = projection_ledger.projection_key(record)
    before_images = {
        "market": {"id": 7, "condition_id": CONDITION},
        "market_tokens": [],
        "token_registry_rows": [],
        "labels": [],
    }
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
    return record, plan, projection_key, before_images


def _rows(
    mode: str,
    labels: tuple[str, str],
    *,
    directional: bool,
    yes_no: bool,
    tokens: tuple[str, str] = ("token-a", "token-b"),
):
    record, plan, projection_key, before_images = _ledger(
        mode,
        labels,
        directional=directional,
        yes_no=yes_no,
        tokens=tokens,
    )
    rows = []
    for index, (logical, label, token) in enumerate(zip(("YES", "NO"), labels, tokens)):
        rows.append(
            {
                "market_id": 7,
                "market_condition_id": CONDITION,
                "market_yes_token_id": tokens[0],
                "market_no_token_id": tokens[1],
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


def _ctx(rows):
    calls = []

    def query_all(sql, params):
        calls.append((sql, params))
        return deepcopy(rows)

    return {"get_backend": lambda: "postgres", "query_all": query_all}, calls


@pytest.mark.parametrize(
    ("mode", "labels", "directional", "yes_no"),
    [
        ("yes_no_labels", ("Yes", "No"), False, True),
        ("up_down_labels", ("Up", "Down"), True, False),
        ("source_first_second", ("Lakers", "Celtics"), False, False),
    ],
)
def test_batch_projection_returns_exact_labels_and_capabilities(mode, labels, directional, yes_no):
    ctx, calls = _ctx(_rows(mode, labels, directional=directional, yes_no=yes_no))

    annotated = outcome_semantics_service.annotate_trade_rows(
        ctx,
        [
            {"market_id": 7, "token_id": "token-a", "outcome": "YES"},
            {"market_id": 7, "token_id": "token-b", "outcome": "NO"},
        ],
    )

    assert len(calls) == 1
    assert "core.market_token_source_labels" in calls[0][0]
    assert "projection_sync_state_v1" in calls[0][0]
    assert "projection_receipts_v1" in calls[0][0]
    assert "authoritative_source_slot_zero_one" in calls[0][0]
    assert [row["outcome"] for row in annotated] == list(labels)
    assert [row["logicalOutcome"] for row in annotated] == ["YES", "NO"]
    assert annotated[0]["semanticMode"] == mode
    assert annotated[0]["outcomeSemanticsCapabilities"] == {
        "supportsYesNoWording": yes_no,
        "supportsDirectionalSemantics": directional,
    }


def test_known_source_first_missing_projection_never_falls_back_to_yes_no():
    rows = _rows("source_first_second", ("A", "B"), directional=False, yes_no=False)
    for row in rows:
        for key in list(row):
            if key.startswith("label_"):
                row[key] = None
    ctx, _calls = _ctx(rows)

    annotated = outcome_semantics_service.annotate_trade_rows(
        ctx, [{"market_id": 7, "token_id": "token-a", "outcome": "YES"}]
    )

    assert annotated[0]["outcome"] is None
    assert annotated[0]["logicalOutcome"] == "YES"
    assert annotated[0]["outcomeSemanticsStatus"] == "source_first_projection_missing"
    assert not outcome_semantics_service.directional_semantics_allowed(annotated[0])


def test_projection_conflict_is_fail_closed():
    rows = _rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False)
    rows.append(deepcopy(rows[0]))
    ctx, _calls = _ctx(rows)

    annotated = outcome_semantics_service.annotate_trade_rows(ctx, [{"market_id": 7, "outcome": "YES"}])

    assert annotated[0]["outcome"] is None
    assert annotated[0]["outcomeSemanticsStatus"] == "projection_conflict"
    assert not outcome_semantics_service.directional_semantics_allowed(annotated[0])


def test_registry_drift_is_fail_closed():
    rows = _rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False)
    rows[0]["registry_token_id"] = "different-token"
    ctx, _calls = _ctx(rows)

    annotated = outcome_semantics_service.annotate_trade_rows(ctx, [{"market_id": 7, "outcome": "YES"}])

    assert annotated[0]["outcome"] is None
    assert annotated[0]["outcomeSemanticsStatus"] == "registry_projection_drift"
    assert not outcome_semantics_service.directional_semantics_allowed(annotated[0])


def test_database_failure_is_fail_closed_for_whole_batch():
    def fail_query(_sql, _params):
        raise RuntimeError("postgres unavailable")

    ctx = {"get_backend": lambda: "postgres", "query_all": fail_query}
    annotated = outcome_semantics_service.annotate_trade_rows(
        ctx,
        [
            {"market_id": 7, "outcome": "YES"},
            {"market_id": 8, "outcome": "NO"},
        ],
    )

    assert {row["outcomeSemanticsStatus"] for row in annotated} == {"semantics_query_failed"}
    assert all(row["outcome"] is None for row in annotated)
    assert all(not outcome_semantics_service.directional_semantics_allowed(row) for row in annotated)


def test_request_cache_prevents_per_consumer_postgres_queries():
    ctx, calls = _ctx(_rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False))
    app = Flask(__name__)

    with app.test_request_context("/"):
        first = outcome_semantics_service.annotate_raw_trade_rows(
            ctx, [{"market_id": 7, "token_id": "token-a", "outcome": "YES"}]
        )
        second = outcome_semantics_service.annotate_raw_trade_rows(
            ctx, [{"market_id": 7, "token_id": "token-b", "outcome": "NO"}]
        )

    assert len(calls) == 1
    assert first[0]["outcome"] == "Up"
    assert second[0]["outcome"] == "Down"


def test_clickhouse_hex_token_is_matched_to_decimal_registry_token():
    token_hex = "ab" * 32
    token_decimal = str(int(token_hex, 16))
    rows = _rows(
        "up_down_labels",
        ("Up", "Down"),
        directional=True,
        yes_no=False,
        tokens=(token_decimal, "token-b"),
    )
    ctx, _calls = _ctx(rows)

    annotated = outcome_semantics_service.annotate_trade_rows(
        ctx,
        [{"market_id": 7, "token_id": token_hex, "outcome": "YES"}],
    )

    assert annotated[0]["outcome"] == "Up"
    assert annotated[0]["logicalOutcome"] == "YES"


def test_raw_trade_token_mismatch_never_falls_back_to_logical_slot():
    ctx, _calls = _ctx(_rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False))

    annotated = outcome_semantics_service.annotate_trade_rows(
        ctx,
        [{"market_id": 7, "token_id": "wrong-token", "outcome": "YES"}],
    )

    assert annotated[0]["outcome"] is None
    assert annotated[0]["logicalOutcome"] == "YES"
    assert annotated[0]["outcomeSemanticsStatus"] == "trade_token_projection_mismatch"
    assert not outcome_semantics_service.directional_semantics_allowed(annotated[0])


def test_exact_source_label_can_recover_logical_slot_without_token():
    ctx, _calls = _ctx(_rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False))

    annotated = outcome_semantics_service.annotate_aggregate_rows(
        ctx,
        [{"market_id": 7, "outcome": "Down"}],
    )

    assert annotated[0]["outcome"] == "Down"
    assert annotated[0]["logicalOutcome"] == "NO"
    assert outcome_semantics_service.directional_semantics_allowed(annotated[0])


def test_missing_trade_slot_blocks_directional_use_even_when_market_projection_is_valid():
    ctx, _calls = _ctx(_rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False))

    annotated = outcome_semantics_service.annotate_trade_rows(ctx, [{"market_id": 7}])

    assert annotated[0]["outcomeSemanticsStatus"] == "trade_token_identity_missing"
    assert not outcome_semantics_service.directional_semantics_allowed(annotated[0])


def test_raw_fact_without_token_cannot_downgrade_to_logical_aggregate():
    ctx, _calls = _ctx(_rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False))

    raw = outcome_semantics_service.annotate_raw_trade_rows(ctx, [{"market_id": 7, "outcome": "YES"}])
    aggregate = outcome_semantics_service.annotate_aggregate_rows(
        ctx,
        [{"market_id": 7, "logicalOutcome": "YES"}],
    )

    assert raw[0]["outcome"] is None
    assert raw[0]["outcomeSemanticsStatus"] == "trade_token_identity_missing"
    assert aggregate[0]["outcome"] == "Up"
    assert aggregate[0]["outcomeSemanticsIdentityMode"] == "aggregate"


def test_database_failure_is_not_cached_into_a_future_request():
    rows = _rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False)
    query_count = 0

    def query_all(_sql, _params):
        nonlocal query_count
        query_count += 1
        if query_count == 1:
            raise RuntimeError("temporary outage")
        return deepcopy(rows)

    ctx = {"get_backend": lambda: "postgres", "query_all": query_all}
    app = Flask(__name__)
    fact = {"market_id": 7, "token_id": "token-a", "outcome": "YES"}

    with app.test_request_context("/first"):
        failed = outcome_semantics_service.annotate_raw_trade_rows(ctx, [fact])[0]
    with app.test_request_context("/second"):
        recovered = outcome_semantics_service.annotate_raw_trade_rows(ctx, [fact])[0]

    assert failed["outcomeSemanticsStatus"] == "semantics_query_failed"
    assert recovered["outcome"] == "Up"
    assert query_count == 2


def test_request_cache_accepts_a_read_only_service_context_mapping():
    mutable_ctx, calls = _ctx(_rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False))
    ctx = MappingProxyType(mutable_ctx)
    app = Flask(__name__)
    fact = {"market_id": 7, "token_id": "token-a", "outcome": "YES"}

    with app.test_request_context("/"):
        first = outcome_semantics_service.annotate_raw_trade_rows(ctx, [fact])[0]
        second = outcome_semantics_service.annotate_raw_trade_rows(ctx, [fact])[0]

    assert first["outcome"] == second["outcome"] == "Up"
    assert len(calls) == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("receipt_evidence_origin", "tampered-origin"),
        ("receipt_evidence_sha256", "d" * 64),
        ("receipt_record_sha256", "d" * 64),
        ("receipt_plan_sha256", "d" * 64),
        ("receipt_projection_key", "d" * 64),
    ],
)
def test_receipt_scalar_tampering_is_rejected(field, replacement):
    rows = _rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False)
    for row in rows:
        row[field] = replacement
    ctx, _calls = _ctx(rows)

    annotated = outcome_semantics_service.annotate_raw_trade_rows(
        ctx,
        [{"market_id": 7, "token_id": "token-a", "outcome": "YES"}],
    )

    assert annotated[0]["outcome"] is None
    assert annotated[0]["outcomeSemanticsStatus"] == "ledger_content_invalid"


@pytest.mark.parametrize("json_field", ["receipt_record_json", "receipt_plan_json"])
def test_receipt_json_tampering_is_rejected(json_field):
    rows = _rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False)
    for row in rows:
        row[json_field] = deepcopy(row[json_field])
        row[json_field]["tampered"] = True
    ctx, _calls = _ctx(rows)

    annotated = outcome_semantics_service.annotate_raw_trade_rows(
        ctx,
        [{"market_id": 7, "token_id": "token-a", "outcome": "YES"}],
    )

    assert annotated[0]["outcomeSemanticsStatus"] == "ledger_content_invalid"


def test_label_content_and_core_yes_slot_are_bound_to_receipt():
    rows = _rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False)
    rows[0]["label_source_label"] = "Higher"
    ctx, _calls = _ctx(rows)
    label_tamper = outcome_semantics_service.annotate_raw_trade_rows(
        ctx,
        [{"market_id": 7, "token_id": "token-a", "outcome": "YES"}],
    )[0]

    rows = _rows("up_down_labels", ("Up", "Down"), directional=True, yes_no=False)
    for row in rows:
        row["market_yes_token_id"] = "token-b"
    ctx, _calls = _ctx(rows)
    slot_tamper = outcome_semantics_service.annotate_raw_trade_rows(
        ctx,
        [{"market_id": 7, "token_id": "token-a", "outcome": "YES"}],
    )[0]

    assert label_tamper["outcomeSemanticsStatus"] == "ledger_content_invalid"
    assert slot_tamper["outcomeSemanticsStatus"] == "canonical_market_slot_invalid"
