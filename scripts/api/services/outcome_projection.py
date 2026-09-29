"""Read-only validation of the persisted source-label contract.

No database connections, schema creation, repair or projection writes belong
in the consumer. Unknown or unproven labels remain unavailable.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

PLAN_SCHEMA_VERSION = "market-token-source-label-projection-plan-v1"


PROJECTION_STATUS = "PROJECTED"


IMMUTABILITY_SCOPE = "DML_GUARD_UNDER_ATTESTED_SCHEMA_AND_SEPARATED_RUNTIME_ROLE_PRIVILEGED_ADMIN_DDL_EXCLUDED"


PRIVILEGED_DDL_RESISTANCE = False


RUNTIME_ROLE_SEPARATION_REQUIRED = True


SEMANTIC_MODES = ("yes_no_labels", "up_down_labels", "source_first_second")


LOGICAL_OUTCOMES = ("YES", "NO")


class ProjectionBlockedError(RuntimeError):
    """The requested projection failed a provenance or registry proof."""

    def __init__(self, reason: str, details: Optional[Mapping[str, Any]] = None) -> None:
        self.reason = reason
        self.details = dict(details or {})
        super().__init__(f"source label projection blocked: {reason}")


def _clean(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _compact_label(value: Any) -> str:
    return " ".join(_clean(value).split())


def _label_key(value: Any) -> str:
    return _compact_label(value).upper()


def _normalize_condition(value: Any) -> str:
    text = _clean(value)
    if not text:
        return ""
    return (text if text.lower().startswith("0x") else f"0x{text}").lower()


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(
        _json_safe(value),
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def record_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _strict_json_object(value: Any, *, field: str) -> Dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ProjectionBlockedError("record_field_not_object", {"field": field})
    try:
        cloned = json.loads(_canonical_json(value))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProjectionBlockedError("record_not_canonical_json", {"field": field}) from exc
    if not isinstance(cloned, dict):
        raise ProjectionBlockedError("record_field_not_object", {"field": field})
    return cloned


def _as_explicit_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    raise ProjectionBlockedError("boolean_field_not_explicit", {"field": field, "value": value})


def _exact_sha(value: Any, *, field: str) -> str:
    normalized = _clean(value).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise ProjectionBlockedError("invalid_sha256", {"field": field, "value": normalized})
    return normalized


def _semantic_flags(slots: Sequence[Mapping[str, Any]], *, semantic_mode: str) -> Tuple[bool, bool]:
    labels_by_logical = {_clean(slot["logical_outcome"]).upper(): _label_key(slot["source_label"]) for slot in slots}
    supports_yes_no = semantic_mode == "yes_no_labels" and labels_by_logical == {
        "YES": "YES",
        "NO": "NO",
    }
    # Directional serving semantics are deliberately narrower than merely
    # recognizing an antonym pair.  Arbitrary source_first_second labels such
    # as OVER/UNDER must remain non-directional so downstream APIs cannot
    # silently reinterpret the internal YES/NO slots as bullish/bearish.
    supports_directional = semantic_mode == "up_down_labels" and labels_by_logical == {
        "YES": "UP",
        "NO": "DOWN",
    }
    return supports_yes_no, supports_directional


def _extract_source_slots(record: Mapping[str, Any]) -> List[Dict[str, Any]]:
    nested = record.get("normalized")
    source = nested if isinstance(nested, Mapping) else record
    evidence = record.get("source_outcome_target_evidence")
    evidence_slots = evidence.get("source_slots") if isinstance(evidence, Mapping) else None

    def normalize_slots(raw_slots: Any) -> List[Dict[str, Any]]:
        if not isinstance(raw_slots, list) or len(raw_slots) != 2:
            raise ProjectionBlockedError("source_slots_not_exact_binary")
        slots: List[Dict[str, Any]] = []
        for raw in raw_slots:
            if not isinstance(raw, Mapping):
                raise ProjectionBlockedError("source_slot_not_object")
            logical_outcome = _clean(raw.get("logical_outcome") or raw.get("target_outcome")).upper()
            logical_index = raw.get("logical_outcome_index")
            if logical_index is None:
                logical_index = raw.get("target_outcome_index")
            slots.append(
                {
                    "source_index": raw.get("source_index"),
                    "source_label": _compact_label(raw.get("source_label")),
                    "token_id": _clean(raw.get("token_id")),
                    "logical_outcome": logical_outcome,
                    "logical_outcome_index": logical_index,
                }
            )
        return slots

    raw_slot_candidates = [
        value
        for value in (
            record.get("source_slots"),
            source.get("source_slots") if source is not record else None,
            evidence_slots,
        )
        if value is not None
    ]
    normalized_slot_candidates = [normalize_slots(value) for value in raw_slot_candidates]
    if normalized_slot_candidates:
        slots = normalized_slot_candidates[0]
        if any(candidate != slots for candidate in normalized_slot_candidates[1:]):
            raise ProjectionBlockedError("source_slots_evidence_conflict")
        raw_tokens = source.get("source_token_ids")
        raw_labels = source.get("source_labels")
        if raw_labels is None:
            raw_labels = source.get("source_outcomes")
        if raw_tokens is not None or raw_labels is not None:
            if not isinstance(raw_tokens, (list, tuple)) or len(raw_tokens) != 2:
                raise ProjectionBlockedError("source_tokens_not_exact_binary")
            if not isinstance(raw_labels, (list, tuple)) or len(raw_labels) != 2:
                raise ProjectionBlockedError("source_labels_not_exact_binary")
            ordered = sorted(slots, key=lambda item: int(item["source_index"]))
            array_identity = [(_clean(token), _compact_label(label)) for token, label in zip(raw_tokens, raw_labels)]
            slot_identity = [(_clean(slot["token_id"]), _compact_label(slot["source_label"])) for slot in ordered]
            if array_identity != slot_identity:
                raise ProjectionBlockedError("source_slots_array_conflict")
        yes_token = _clean(source.get("yes_token_id") or record.get("yes_token_id"))
        no_token = _clean(source.get("no_token_id") or record.get("no_token_id"))
        logical_by_token = {_clean(slot["token_id"]): _clean(slot["logical_outcome"]).upper() for slot in slots}
        if yes_token and logical_by_token.get(yes_token) != "YES":
            raise ProjectionBlockedError("source_slots_logical_token_conflict")
        if no_token and logical_by_token.get(no_token) != "NO":
            raise ProjectionBlockedError("source_slots_logical_token_conflict")
        return slots

    raw_tokens = source.get("source_token_ids")
    raw_labels = source.get("source_labels")
    if raw_labels is None:
        raw_labels = source.get("source_outcomes")
    if not isinstance(raw_tokens, (list, tuple)) or len(raw_tokens) != 2:
        raise ProjectionBlockedError("source_tokens_not_exact_binary")
    if not isinstance(raw_labels, (list, tuple)) or len(raw_labels) != 2:
        raise ProjectionBlockedError("source_labels_not_exact_binary")
    tokens = [_clean(value) for value in raw_tokens]
    labels = [_compact_label(value) for value in raw_labels]
    yes_token = _clean(source.get("yes_token_id") or record.get("yes_token_id"))
    no_token = _clean(source.get("no_token_id") or record.get("no_token_id"))
    semantic_mode = _clean(
        record.get("semantic_mode")
        or record.get("logical_mapping_rule")
        or source.get("semantic_mode")
        or source.get("logical_mapping_rule")
    ).lower()
    label_keys = [_label_key(value) for value in labels]
    if not yes_token and not no_token:
        if semantic_mode == "yes_no_labels" and set(label_keys) == {"YES", "NO"}:
            yes_token = tokens[label_keys.index("YES")]
            no_token = tokens[label_keys.index("NO")]
        elif semantic_mode == "up_down_labels" and set(label_keys) == {"UP", "DOWN"}:
            yes_token = tokens[label_keys.index("UP")]
            no_token = tokens[label_keys.index("DOWN")]
        elif semantic_mode == "source_first_second":
            yes_token, no_token = tokens
    slots = []
    for index, (token, label) in enumerate(zip(tokens, labels)):
        if token == yes_token:
            logical_outcome, logical_index = "YES", 0
        elif token == no_token:
            logical_outcome, logical_index = "NO", 1
        else:
            logical_outcome, logical_index = "", None
        slots.append(
            {
                "source_index": index,
                "source_label": label,
                "token_id": token,
                "logical_outcome": logical_outcome,
                "logical_outcome_index": logical_index,
            }
        )
    return slots


def normalize_projection_record(record: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize and strictly validate one explicit source-label record."""

    source_record = _strict_json_object(record, field="record")
    nested = source_record.get("normalized")
    normalized = nested if isinstance(nested, Mapping) else source_record
    try:
        market_id = int(
            source_record.get("market_id")
            or source_record.get("canonical_market_id")
            or normalized.get("market_id")
            or normalized.get("canonical_market_id")
        )
    except (TypeError, ValueError) as exc:
        raise ProjectionBlockedError("invalid_market_id") from exc
    if market_id <= 0:
        raise ProjectionBlockedError("invalid_market_id", {"market_id": market_id})
    condition_id = _normalize_condition(source_record.get("condition_id") or normalized.get("condition_id"))
    if not re.fullmatch(r"0x[0-9a-f]{64}", condition_id):
        raise ProjectionBlockedError("condition_id_not_bytes32", {"condition_id": condition_id})

    semantic_mode = _clean(
        source_record.get("semantic_mode")
        or source_record.get("logical_mapping_rule")
        or normalized.get("semantic_mode")
        or normalized.get("logical_mapping_rule")
    ).lower()
    if semantic_mode not in SEMANTIC_MODES:
        raise ProjectionBlockedError(
            "unsupported_semantic_mode",
            {"semantic_mode": semantic_mode, "allowed": list(SEMANTIC_MODES)},
        )

    slots = _extract_source_slots(source_record)
    try:
        slots.sort(key=lambda item: int(item["source_index"]))
    except (TypeError, ValueError) as exc:
        raise ProjectionBlockedError("invalid_source_index") from exc
    source_indices = [int(item["source_index"]) for item in slots]
    token_ids = [_clean(item["token_id"]) for item in slots]
    labels = [_compact_label(item["source_label"]) for item in slots]
    logical_outcomes = [_clean(item["logical_outcome"]).upper() for item in slots]
    try:
        logical_indices = [int(item["logical_outcome_index"]) for item in slots]
    except (TypeError, ValueError) as exc:
        raise ProjectionBlockedError("invalid_logical_outcome_index") from exc
    shape_failures: Dict[str, Any] = {}
    if source_indices != [0, 1]:
        shape_failures["source_indices"] = source_indices
    if any(not value for value in token_ids) or len(set(token_ids)) != 2:
        shape_failures["token_ids"] = token_ids
    if any(not value for value in labels) or len({_label_key(value) for value in labels}) != 2:
        shape_failures["source_labels"] = labels
    if set(logical_outcomes) != set(LOGICAL_OUTCOMES):
        shape_failures["logical_outcomes"] = logical_outcomes
    if set(logical_indices) != {0, 1}:
        shape_failures["logical_outcome_indices"] = logical_indices
    for outcome, index in zip(logical_outcomes, logical_indices):
        if (outcome, index) not in {("YES", 0), ("NO", 1)}:
            shape_failures.setdefault("logical_slot_pairs", []).append([outcome, index])
    if shape_failures:
        raise ProjectionBlockedError("source_logical_bijection_invalid", shape_failures)

    label_keys = [_label_key(value) for value in labels]
    logical_by_label = {label_keys[index]: (logical_outcomes[index], logical_indices[index]) for index in range(2)}
    if semantic_mode == "yes_no_labels" and logical_by_label != {
        "YES": ("YES", 0),
        "NO": ("NO", 1),
    }:
        raise ProjectionBlockedError("semantic_mode_label_mapping_mismatch")
    if semantic_mode == "up_down_labels" and logical_by_label != {
        "UP": ("YES", 0),
        "DOWN": ("NO", 1),
    }:
        raise ProjectionBlockedError("semantic_mode_label_mapping_mismatch")
    if semantic_mode == "source_first_second" and logical_indices != [0, 1]:
        raise ProjectionBlockedError("semantic_mode_label_mapping_mismatch")

    normalized_slots = [
        {
            "source_index": source_indices[index],
            "source_label": labels[index],
            "token_id": token_ids[index],
            "logical_outcome": logical_outcomes[index],
            "logical_outcome_index": logical_indices[index],
        }
        for index in range(2)
    ]
    computed_yes_no, computed_directional = _semantic_flags(normalized_slots, semantic_mode=semantic_mode)
    provided_yes_no = source_record.get("supports_yes_no_wording")
    if provided_yes_no is None:
        provided_yes_no = normalized.get("supports_yes_no_wording")
    provided_directional = source_record.get("supports_directional_semantics")
    if provided_directional is None:
        provided_directional = normalized.get("supports_directional_semantics")
    if (
        provided_yes_no is not None
        and _as_explicit_bool(provided_yes_no, field="supports_yes_no_wording") != computed_yes_no
    ):
        raise ProjectionBlockedError(
            "semantic_capability_claim_mismatch",
            {"field": "supports_yes_no_wording", "computed": computed_yes_no},
        )
    if (
        provided_directional is not None
        and _as_explicit_bool(provided_directional, field="supports_directional_semantics") != computed_directional
    ):
        raise ProjectionBlockedError(
            "semantic_capability_claim_mismatch",
            {"field": "supports_directional_semantics", "computed": computed_directional},
        )

    evidence = source_record.get("evidence")
    evidence_map = evidence if isinstance(evidence, Mapping) else {}
    origin_candidates = [
        _clean(value)
        for value in (
            source_record.get("evidence_origin"),
            normalized.get("evidence_origin") if normalized is not source_record else None,
            evidence_map.get("origin"),
        )
        if value is not None
    ]
    if not origin_candidates or any(not value for value in origin_candidates):
        raise ProjectionBlockedError("evidence_origin_missing")
    if len(set(origin_candidates)) != 1:
        raise ProjectionBlockedError("evidence_origin_alias_conflict", {"origins": origin_candidates})
    evidence_origin = origin_candidates[0]

    explicit_evidence_payload = source_record.get("evidence_payload")
    target_evidence_payload = source_record.get("source_outcome_target_evidence")
    if target_evidence_payload is not None and not isinstance(target_evidence_payload, Mapping):
        raise ProjectionBlockedError("source_outcome_target_evidence_not_object")
    if (
        explicit_evidence_payload is not None
        and target_evidence_payload is not None
        and _canonical_json(explicit_evidence_payload) != _canonical_json(target_evidence_payload)
    ):
        raise ProjectionBlockedError("multiple_evidence_payload_conflict")
    evidence_payload = explicit_evidence_payload if explicit_evidence_payload is not None else target_evidence_payload

    sha_candidates: Dict[str, str] = {}
    raw_sha_candidates = (
        ("evidence_sha256", source_record.get("evidence_sha256")),
        (
            "source_outcome_target_evidence_sha256",
            source_record.get("source_outcome_target_evidence_sha256"),
        ),
        (
            "normalized.evidence_sha256",
            normalized.get("evidence_sha256") if normalized is not source_record else None,
        ),
        ("evidence.sha256", evidence_map.get("sha256")),
    )
    for field, value in raw_sha_candidates:
        if value is not None:
            sha_candidates[field] = _exact_sha(value, field=field)
    if len(set(sha_candidates.values())) > 1:
        raise ProjectionBlockedError("evidence_sha256_alias_conflict", {"sha256_by_field": sha_candidates})
    if evidence_payload is not None:
        if not isinstance(evidence_payload, Mapping):
            raise ProjectionBlockedError("evidence_payload_not_object")
        try:
            payload_slots = _extract_source_slots(evidence_payload)
            payload_slots.sort(key=lambda item: int(item["source_index"]))
            payload_slot_identity = [
                {
                    "source_index": int(slot["source_index"]),
                    "source_label": _compact_label(slot["source_label"]),
                    "token_id": _clean(slot["token_id"]),
                    "logical_outcome": _clean(slot["logical_outcome"]).upper(),
                    "logical_outcome_index": int(slot["logical_outcome_index"]),
                }
                for slot in payload_slots
            ]
        except (ProjectionBlockedError, TypeError, ValueError) as exc:
            raise ProjectionBlockedError(
                "evidence_payload_source_semantics_invalid",
                {"cause": getattr(exc, "reason", exc.__class__.__name__)},
            ) from exc
        if payload_slot_identity != normalized_slots:
            raise ProjectionBlockedError(
                "evidence_payload_source_semantics_mismatch",
                {"expected": normalized_slots, "actual": payload_slot_identity},
            )
        payload_mode = _clean(
            evidence_payload.get("semantic_mode") or evidence_payload.get("logical_mapping_rule")
        ).lower()
        if payload_mode and payload_mode != semantic_mode:
            raise ProjectionBlockedError(
                "evidence_payload_semantic_mode_mismatch",
                {"expected": semantic_mode, "actual": payload_mode},
            )
        alignment_contract = evidence_payload.get("source_alignment_contract")
        if alignment_contract is not None and _clean(alignment_contract) != ("clobTokenIds[i]<->outcomes[i]"):
            raise ProjectionBlockedError(
                "evidence_payload_alignment_contract_mismatch",
                {"actual": alignment_contract},
            )
        computed_evidence_sha = record_digest(evidence_payload)
        mismatched_sha_fields = {
            field: value for field, value in sha_candidates.items() if value != computed_evidence_sha
        }
        if mismatched_sha_fields:
            raise ProjectionBlockedError(
                "evidence_checksum_mismatch",
                {
                    "supplied_sha256_by_field": mismatched_sha_fields,
                    "actual_evidence_sha256": computed_evidence_sha,
                },
            )
        evidence_sha256 = computed_evidence_sha
    else:
        if not sha_candidates:
            raise ProjectionBlockedError("evidence_sha256_missing")
        evidence_sha256 = next(iter(sha_candidates.values()))

    return {
        "market_id": market_id,
        "condition_id": condition_id,
        "semantic_mode": semantic_mode,
        "supports_yes_no_wording": computed_yes_no,
        "supports_directional_semantics": computed_directional,
        "evidence_origin": evidence_origin,
        "evidence_sha256": evidence_sha256,
        "source_slots": normalized_slots,
    }


def immutability_contract() -> Dict[str, Any]:
    return {
        "immutability_scope": IMMUTABILITY_SCOPE,
        "privileged_ddl_resistance": PRIVILEGED_DDL_RESISTANCE,
        "runtime_role_separation_required": RUNTIME_ROLE_SEPARATION_REQUIRED,
    }


def projection_key(record: Mapping[str, Any]) -> str:
    return record_digest(
        {
            "schema_version": PLAN_SCHEMA_VERSION,
            "market_id": int(record["market_id"]),
            "condition_id": record["condition_id"],
        }
    )


def expected_labels(record: Mapping[str, Any], plan_sha256: str = "") -> List[Dict[str, Any]]:
    rows = []
    for slot in record["source_slots"]:
        rows.append(
            {
                "token_id": slot["token_id"],
                "market_id": int(record["market_id"]),
                "condition_id": record["condition_id"],
                "source_index": int(slot["source_index"]),
                "source_label": slot["source_label"],
                "logical_outcome": slot["logical_outcome"],
                "logical_outcome_index": int(slot["logical_outcome_index"]),
                "semantic_mode": record["semantic_mode"],
                "supports_yes_no_wording": bool(record["supports_yes_no_wording"]),
                "supports_directional_semantics": bool(record["supports_directional_semantics"]),
                "evidence_origin": record["evidence_origin"],
                "evidence_sha256": record["evidence_sha256"],
                "plan_sha256": plan_sha256,
            }
        )
    return rows


def validate_plan(plan: Mapping[str, Any]) -> Dict[str, Any]:
    candidate = _strict_json_object(plan, field="plan")
    stored_sha = _exact_sha(candidate.pop("plan_sha256", ""), field="plan_sha256")
    actual_sha = record_digest(candidate)
    if actual_sha != stored_sha:
        raise ProjectionBlockedError(
            "plan_checksum_mismatch",
            {"expected_plan_sha256": stored_sha, "actual_plan_sha256": actual_sha},
        )
    if candidate.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ProjectionBlockedError("unsupported_plan_schema", {"schema_version": candidate.get("schema_version")})
    normalized = normalize_projection_record(candidate.get("record") or {})
    mismatches: Dict[str, Any] = {}
    if candidate.get("record") != normalized:
        mismatches["record"] = "not_normalized"
    if candidate.get("record_sha256") != record_digest(normalized):
        mismatches["record_sha256"] = "mismatch"
    if candidate.get("projection_key") != projection_key(normalized):
        mismatches["projection_key"] = "mismatch"
    expected = candidate.get("expected")
    if not isinstance(expected, Mapping):
        mismatches["expected"] = "missing"
    else:
        if expected.get("status") != PROJECTION_STATUS:
            mismatches["expected.status"] = "mismatch"
        if expected.get("projected_token_count") != 2:
            mismatches["expected.projected_token_count"] = "mismatch"
        if expected.get("label_rows_without_plan_sha256") != expected_labels(normalized):
            mismatches["expected.label_rows_without_plan_sha256"] = "mismatch"
        if expected.get("immutability_contract") != immutability_contract():
            mismatches["expected.immutability_contract"] = "mismatch"
    if mismatches:
        raise ProjectionBlockedError("plan_semantics_mismatch", mismatches)
    candidate["plan_sha256"] = stored_sha
    return candidate
