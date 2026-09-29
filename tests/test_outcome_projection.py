from __future__ import annotations
from copy import deepcopy
import json
from typing import Any
import pytest
from api.services import outcome_projection as projection

CONDITION = "0x" + "ab" * 32


TOKEN_A = "1000000000000000000000000000000000000001"


TOKEN_B = "2000000000000000000000000000000000000002"


def _record(
    *,
    labels: tuple[str, str] = ("OVER", "UNDER"),
    semantic_mode: str = "source_first_second",
) -> dict[str, Any]:
    return {
        "market_id": 7,
        "condition_id": CONDITION,
        "source_token_ids": [TOKEN_A, TOKEN_B],
        "source_labels": list(labels),
        "yes_token_id": TOKEN_A,
        "no_token_id": TOKEN_B,
        "semantic_mode": semantic_mode,
        "evidence_origin": "gamma-history:closed:market-42",
        "evidence_sha256": "a" * 64,
    }


def test_explicit_source_slots_are_supported_without_guessing() -> None:
    evidence = {
        "schema_version": "source-outcome-target-evidence-v1",
        "source_alignment_contract": "clobTokenIds[i]<->outcomes[i]",
        "logical_mapping_rule": "source_first_second",
        "source_slots": [
            {
                "source_index": 0,
                "source_label": "Candidate A",
                "token_id": TOKEN_A,
                "target_outcome": "YES",
                "target_outcome_index": 0,
            },
            {
                "source_index": 1,
                "source_label": "Candidate B",
                "token_id": TOKEN_B,
                "target_outcome": "NO",
                "target_outcome_index": 1,
            },
        ],
    }
    record = {
        "canonical_market_id": 7,
        "condition_id": CONDITION,
        "semantic_mode": "source_first_second",
        "source_outcome_target_evidence": evidence,
        "source_outcome_target_evidence_sha256": projection.record_digest(evidence),
        "evidence_origin": "bridge-batch:item-17",
    }
    normalized = projection.normalize_projection_record(record)
    assert [slot["source_label"] for slot in normalized["source_slots"]] == [
        "Candidate A",
        "Candidate B",
    ]
    assert normalized["supports_yes_no_wording"] is False
    assert normalized["supports_directional_semantics"] is False


def test_conflicting_slot_and_checksum_pinned_evidence_is_rejected() -> None:
    evidence = {
        "source_slots": [
            {
                "source_index": 0,
                "source_label": "OVER",
                "token_id": TOKEN_A,
                "target_outcome": "YES",
                "target_outcome_index": 0,
            },
            {
                "source_index": 1,
                "source_label": "UNDER",
                "token_id": TOKEN_B,
                "target_outcome": "NO",
                "target_outcome_index": 1,
            },
        ]
    }
    record = _record()
    record["source_outcome_target_evidence"] = evidence
    record["source_outcome_target_evidence_sha256"] = projection.record_digest(evidence)
    record["source_slots"] = deepcopy(evidence["source_slots"])
    record["source_slots"][0]["source_label"] = "TEAM RED"
    with pytest.raises(projection.ProjectionBlockedError, match="source_slots_evidence_conflict"):
        projection.normalize_projection_record(record)


def test_nested_normalized_record_form_is_supported_and_claims_are_checked() -> None:
    base = _record()
    record = {
        "canonical_market_id": base.pop("market_id"),
        "normalized": base,
    }
    normalized = projection.normalize_projection_record(record)
    assert normalized["market_id"] == 7
    record["normalized"]["supports_yes_no_wording"] = True
    with pytest.raises(projection.ProjectionBlockedError, match="semantic_capability_claim_mismatch"):
        projection.normalize_projection_record(record)


def test_embedded_evidence_payload_must_match_supplied_sha() -> None:
    record = _record()
    record["evidence_payload"] = {
        "source_token_ids": [TOKEN_A, TOKEN_B],
        "source_outcomes": ["OVER", "UNDER"],
        "yes_token_id": TOKEN_A,
        "no_token_id": TOKEN_B,
        "logical_mapping_rule": "source_first_second",
    }
    record["evidence_sha256"] = "f" * 64
    with pytest.raises(projection.ProjectionBlockedError, match="evidence_checksum_mismatch"):
        projection.normalize_projection_record(record)
    record["evidence_sha256"] = projection.record_digest(record["evidence_payload"])
    assert projection.normalize_projection_record(record)["evidence_sha256"] == record["evidence_sha256"]


def test_two_evidence_payloads_or_sha_aliases_cannot_describe_different_evidence() -> None:
    target_evidence = {
        "logical_mapping_rule": "source_first_second",
        "source_slots": [
            {
                "source_index": 0,
                "source_label": "OVER",
                "token_id": TOKEN_A,
                "target_outcome": "YES",
                "target_outcome_index": 0,
            },
            {
                "source_index": 1,
                "source_label": "UNDER",
                "token_id": TOKEN_B,
                "target_outcome": "NO",
                "target_outcome_index": 1,
            },
        ],
    }
    record = _record()
    record["source_outcome_target_evidence"] = target_evidence
    record["source_outcome_target_evidence_sha256"] = projection.record_digest(target_evidence)
    record["evidence_payload"] = {
        "source_token_ids": [TOKEN_A, TOKEN_B],
        "source_outcomes": ["TEAM RED", "TEAM BLUE"],
        "yes_token_id": TOKEN_A,
        "no_token_id": TOKEN_B,
        "logical_mapping_rule": "source_first_second",
    }
    record["evidence_sha256"] = projection.record_digest(record["evidence_payload"])
    with pytest.raises(projection.ProjectionBlockedError, match="multiple_evidence_payload_conflict"):
        projection.normalize_projection_record(record)

    record.pop("evidence_payload")
    record["evidence_sha256"] = "f" * 64
    with pytest.raises(projection.ProjectionBlockedError, match="evidence_sha256_alias_conflict"):
        projection.normalize_projection_record(record)


def test_yes_no_and_up_down_modes_compute_conservative_capabilities() -> None:
    yes_no = projection.normalize_projection_record(_record(labels=("YES", "NO"), semantic_mode="yes_no_labels"))
    assert yes_no["supports_yes_no_wording"] is True
    assert yes_no["supports_directional_semantics"] is False
    up_down = projection.normalize_projection_record(_record(labels=("UP", "DOWN"), semantic_mode="up_down_labels"))
    assert up_down["supports_yes_no_wording"] is False
    assert up_down["supports_directional_semantics"] is True


def test_capability_overclaim_is_fail_closed() -> None:
    record = _record(labels=("Team Red", "Team Blue"))
    record["supports_yes_no_wording"] = True
    with pytest.raises(projection.ProjectionBlockedError, match="semantic_capability_claim_mismatch"):
        projection.normalize_projection_record(record)
    record["supports_yes_no_wording"] = False
    record["supports_directional_semantics"] = True
    with pytest.raises(projection.ProjectionBlockedError, match="semantic_capability_claim_mismatch"):
        projection.normalize_projection_record(record)
