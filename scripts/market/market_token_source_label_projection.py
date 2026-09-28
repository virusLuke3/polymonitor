#!/usr/bin/env python3
"""Project exact source outcome labels onto a canonical two-token market.

The logical ``YES``/``NO`` slots in ``core.market_tokens`` are an internal
binary convention.  They are not permission to display those words for a
market whose source outcomes are, for example, ``OVER``/``UNDER`` or two team
names.  This module stores the source label attached to each token without
rewriting the canonical registry.

Preparation and dry-run are read-only and create no schema.  Applying requires
one explicit market record and the exact freshly prepared plan SHA256.  The
apply transaction is SERIALIZABLE, locks the canonical market and its two token
rows, re-proves the complete before-image, performs compare-and-insert writes,
attests the schema and DML-guard triggers, and post-checks the committed
projection.  Under that attested schema the triggers reject UPDATE, DELETE,
and TRUNCATE (including replica-role DML).  PostgreSQL apply/failure writes
also attest a separated runtime role: it must not be superuser/CREATEROLE, an
owner (or owner-member) of the guarded schema/tables/function, belong to any
additional role, hold schema CREATE, or hold guarded-table mutation/trigger
privileges.  Schema bootstrap
is a separate explicit admin operation.  A distinct privileged database admin
remains outside the DML-immutability threat model; this module does not claim
resistance to hostile superuser DDL.

The accepted programmatic/JSON record is intentionally explicit.  It may use
ordered arrays (``source_token_ids`` and ``source_labels``/``source_outcomes``)
or two ``source_slots``.  It must identify the canonical market, condition,
semantic mode, and evidence origin plus SHA256.  Optional evidence payloads are
checksum-verified.  This tool does not scan history and does not mutate
ClickHouse.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from db import (  # noqa: E402
    add_db_cli_args,
    configure_db_from_args,
    describe_db_target,
    get_connection,
)


PLAN_SCHEMA_VERSION = "market-token-source-label-projection-plan-v1"
RECEIPT_SCHEMA_VERSION = "market-token-source-label-projection-receipt-v1"
FAILURE_SCHEMA_VERSION = "market-token-source-label-projection-failure-v1"
PROJECTION_STATUS = "PROJECTED"
ADVISORY_LOCK_NAMESPACE = "polymonitor:market-token-source-label-projection:v1"
IMMUTABILITY_SCOPE = "DML_GUARD_UNDER_ATTESTED_SCHEMA_AND_SEPARATED_RUNTIME_ROLE_PRIVILEGED_ADMIN_DDL_EXCLUDED"
PRIVILEGED_DDL_RESISTANCE = False
RUNTIME_ROLE_SEPARATION_REQUIRED = True

LABEL_TABLE = "core.market_token_source_labels"
RECEIPT_TABLE = "ops.market_token_source_label_projection_receipts_v1"
FAILURE_TABLE = "ops.market_token_source_label_projection_failures_v1"
SYNC_TABLE = "ops.market_token_source_label_projection_sync_state_v1"
IMMUTABLE_FUNCTION = "ops.reject_market_token_source_label_projection_mutation_v1"

SEMANTIC_MODES = ("yes_no_labels", "up_down_labels", "source_first_second")
LOGICAL_OUTCOMES = ("YES", "NO")
MARKET_COLUMNS = ("id", "condition_id", "yes_token_id", "no_token_id")
TOKEN_COLUMNS = (
    "id",
    "market_id",
    "condition_id",
    "token_id",
    "outcome",
    "outcome_index",
)
LABEL_COLUMNS = (
    "token_id",
    "market_id",
    "condition_id",
    "source_index",
    "source_label",
    "logical_outcome",
    "logical_outcome_index",
    "semantic_mode",
    "supports_yes_no_wording",
    "supports_directional_semantics",
    "evidence_origin",
    "evidence_sha256",
    "plan_sha256",
)
RECEIPT_COLUMNS = (
    "projection_key",
    "plan_sha256",
    "record_sha256",
    "market_id",
    "condition_id",
    "evidence_origin",
    "evidence_sha256",
    "record_json",
    "plan_json",
    "before_images_json",
    "status",
)
SYNC_COLUMNS = (
    "projection_key",
    "market_id",
    "condition_id",
    "plan_sha256",
    "status",
    "projected_token_count",
)
FAILURE_COLUMNS = (
    "failure_key",
    "input_sha256",
    "projection_key",
    "market_id",
    "condition_id",
    "reason",
    "details_json",
    "evidence_origin",
    "evidence_sha256",
)

_TABLES = (LABEL_TABLE, RECEIPT_TABLE, FAILURE_TABLE, SYNC_TABLE)
_TRIGGER_NAMES = {
    LABEL_TABLE: "mt_source_labels_reject_mutation",
    RECEIPT_TABLE: "mt_source_label_receipts_reject_mutation",
    FAILURE_TABLE: "mt_source_label_failures_reject_mutation",
    SYNC_TABLE: "mt_source_label_sync_reject_mutation",
}
_TRUNCATE_TRIGGER_NAMES = {
    LABEL_TABLE: "mt_source_labels_reject_truncate",
    RECEIPT_TABLE: "mt_source_label_receipts_reject_truncate",
    FAILURE_TABLE: "mt_source_label_failures_reject_truncate",
    SYNC_TABLE: "mt_source_label_sync_reject_truncate",
}

_POSTGRES_COLUMN_CONTRACT = {
    RECEIPT_TABLE: (
        ("projection_key", "text", True, None),
        ("plan_sha256", "text", True, None),
        ("record_sha256", "text", True, None),
        ("market_id", "bigint", True, None),
        ("condition_id", "text", True, None),
        ("evidence_origin", "text", True, None),
        ("evidence_sha256", "text", True, None),
        ("record_json", "jsonb", True, None),
        ("plan_json", "jsonb", True, None),
        ("before_images_json", "jsonb", True, None),
        ("status", "text", True, None),
        ("committed_at", "timestamp with time zone", True, "now()"),
    ),
    FAILURE_TABLE: (
        ("failure_key", "text", True, None),
        ("input_sha256", "text", True, None),
        ("projection_key", "text", False, None),
        ("market_id", "bigint", False, None),
        ("condition_id", "text", False, None),
        ("reason", "text", True, None),
        ("details_json", "jsonb", True, None),
        ("evidence_origin", "text", False, None),
        ("evidence_sha256", "text", False, None),
        ("failed_at", "timestamp with time zone", True, "now()"),
    ),
    LABEL_TABLE: (
        ("token_id", "text", True, None),
        ("market_id", "bigint", True, None),
        ("condition_id", "text", True, None),
        ("source_index", "smallint", True, None),
        ("source_label", "text", True, None),
        ("logical_outcome", "text", True, None),
        ("logical_outcome_index", "smallint", True, None),
        ("semantic_mode", "text", True, None),
        ("supports_yes_no_wording", "boolean", True, None),
        ("supports_directional_semantics", "boolean", True, None),
        ("evidence_origin", "text", True, None),
        ("evidence_sha256", "text", True, None),
        ("plan_sha256", "text", True, None),
        ("projected_at", "timestamp with time zone", True, "now()"),
    ),
    SYNC_TABLE: (
        ("projection_key", "text", True, None),
        ("market_id", "bigint", True, None),
        ("condition_id", "text", True, None),
        ("plan_sha256", "text", True, None),
        ("status", "text", True, None),
        ("projected_token_count", "smallint", True, None),
        ("projected_at", "timestamp with time zone", True, "now()"),
    ),
}

_POSTGRES_KEY_CONTRACT = {
    RECEIPT_TABLE: (
        ("p", ("projection_key",), None, None, ()),
        ("u", ("plan_sha256",), None, None, ()),
        ("u", ("market_id",), None, None, ()),
        ("u", ("condition_id",), None, None, ()),
        ("f", ("market_id",), "core", "markets", ("id",)),
    ),
    FAILURE_TABLE: (("p", ("failure_key",), None, None, ()),),
    LABEL_TABLE: (
        ("p", ("token_id",), None, None, ()),
        ("u", ("market_id", "source_index"), None, None, ()),
        ("u", ("market_id", "logical_outcome_index"), None, None, ()),
        ("u", ("condition_id", "source_index"), None, None, ()),
        ("f", ("market_id",), "core", "markets", ("id",)),
        ("f", ("token_id",), "core", "market_tokens", ("token_id",)),
        (
            "f",
            ("plan_sha256",),
            "ops",
            RECEIPT_TABLE.split(".", 1)[1],
            ("plan_sha256",),
        ),
    ),
    SYNC_TABLE: (
        ("p", ("projection_key",), None, None, ()),
        ("u", ("market_id",), None, None, ()),
        ("u", ("condition_id",), None, None, ()),
        ("u", ("plan_sha256",), None, None, ()),
        ("f", ("market_id",), "core", "markets", ("id",)),
        (
            "f",
            ("projection_key",),
            "ops",
            RECEIPT_TABLE.split(".", 1)[1],
            ("projection_key",),
        ),
        (
            "f",
            ("plan_sha256",),
            "ops",
            RECEIPT_TABLE.split(".", 1)[1],
            ("plan_sha256",),
        ),
    ),
}

_POSTGRES_CHECK_CONTRACT = {
    RECEIPT_TABLE: (f"status='{PROJECTION_STATUS}'",),
    FAILURE_TABLE: (),
    LABEL_TABLE: (
        "source_index=any(array[0,1])",
        "logical_outcome=any(array['YES','NO'])",
        "logical_outcome_index=any(array[0,1])",
        "semantic_mode=any(array['yes_no_labels','up_down_labels','source_first_second'])",
    ),
    SYNC_TABLE: (
        f"status='{PROJECTION_STATUS}'",
        "projected_token_count=2",
    ),
}


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


def _sha256(value: Any) -> str:
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
        computed_evidence_sha = _sha256(evidence_payload)
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


def _is_sqlite(conn: Any) -> bool:
    return conn.__class__.__module__.split(".", 1)[0] == "sqlite3"


def _row_value(row: Any, index: int, name: str) -> Any:
    try:
        return row[name]
    except (KeyError, IndexError, TypeError):
        return row[index]


def _row_dict(row: Any, columns: Sequence[str]) -> Dict[str, Any]:
    return {name: _row_value(row, index, name) for index, name in enumerate(columns)}


def _require_supported_connection(conn: Any) -> None:
    if _is_sqlite(conn) or conn.__class__.__name__ == "PostgresConnectionWrapper":
        return
    raise ProjectionBlockedError(
        "unsupported_database_backend",
        {"connection_class": f"{conn.__class__.__module__}.{conn.__class__.__name__}"},
    )


def _postgres_transaction_status(conn: Any) -> Tuple[str, Optional[int]]:
    raw_conn = getattr(conn, "_pg_conn", None)
    status = getattr(getattr(raw_conn, "info", None), "transaction_status", None)
    if status is None:
        raise ProjectionBlockedError("postgres_transaction_status_unavailable")
    name = _clean(getattr(status, "name", status)).upper()
    try:
        code: Optional[int] = int(status)
    except (TypeError, ValueError):
        code = None
    return name, code


def _require_idle_connection(conn: Any) -> None:
    if _is_sqlite(conn):
        if bool(getattr(conn, "in_transaction", False)):
            raise ProjectionBlockedError("caller_transaction_already_active")
        return
    name, code = _postgres_transaction_status(conn)
    if name != "IDLE" or code != 0:
        raise ProjectionBlockedError(
            "caller_transaction_already_active",
            {"postgres_transaction_status": name, "postgres_transaction_status_code": code},
        )


def _require_active_owned_transaction(conn: Any) -> None:
    """Require a healthy transaction owned by an enclosing atomic workflow."""

    if _is_sqlite(conn):
        if not bool(getattr(conn, "in_transaction", False)):
            raise ProjectionBlockedError("caller_owned_transaction_missing")
        return
    name, code = _postgres_transaction_status(conn)
    if name != "INTRANS" or code != 2:
        raise ProjectionBlockedError(
            "caller_owned_transaction_missing",
            {
                "postgres_transaction_status": name,
                "postgres_transaction_status_code": code,
            },
        )


def _begin_transaction(conn: Any, *, read_only: bool) -> None:
    _require_idle_connection(conn)
    if _is_sqlite(conn):
        conn.execute("BEGIN IMMEDIATE")
    elif read_only:
        conn.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    else:
        conn.execute("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ WRITE")


def _table_exists(conn: Any, table: str) -> bool:
    if _is_sqlite(conn):
        schema, name = table.split(".", 1)
        row = conn.execute(
            f"SELECT 1 FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        return row is not None
    row = conn.execute("SELECT to_regclass(?)", (table,)).fetchone()
    return row is not None and _row_value(row, 0, "to_regclass") is not None


def _schema_presence(conn: Any) -> bool:
    presence = {table: _table_exists(conn, table) for table in _TABLES}
    if any(presence.values()) and not all(presence.values()):
        raise ProjectionBlockedError("incomplete_projection_schema", presence)
    return all(presence.values())


def _sql_signature(value: Any) -> str:
    text = _clean(value).lower().replace('"', "")
    text = re.sub(r"\bif\s+not\s+exists\b", "", text)
    text = text.replace("core.", "").replace("ops.", "")
    return re.sub(r"\s+", "", text).rstrip(";")


def _postgres_check_signature(value: Any) -> str:
    text = _clean(value)
    output: List[str] = []
    outside: List[str] = []

    def flush_outside() -> None:
        if not outside:
            return
        segment = "".join(outside).lower().replace('"', "")
        segment = re.sub(
            r"::(?:text|integer|smallint|bigint)(?:\[\])?",
            "",
            segment,
        )
        output.append(re.sub(r"[\s()]", "", segment))
        outside.clear()

    index = 0
    while index < len(text):
        if text[index] != "'":
            outside.append(text[index])
            index += 1
            continue
        flush_outside()
        literal = ["'"]
        index += 1
        while index < len(text):
            literal.append(text[index])
            if text[index] == "'":
                if index + 1 < len(text) and text[index + 1] == "'":
                    literal.append(text[index + 1])
                    index += 2
                    continue
                index += 1
                break
            index += 1
        output.append("".join(literal))
    flush_outside()
    return "".join(output)


def _sequence_tuple(value: Any) -> Tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            return tuple(item for item in text[1:-1].split(",") if item)
        return (text,)
    return tuple(_clean(item) for item in value)


def _sqlite_table_ddls() -> Dict[str, str]:
    modes = ", ".join(f"'{value}'" for value in SEMANTIC_MODES)
    return {
        RECEIPT_TABLE: f"""
            CREATE TABLE IF NOT EXISTS {RECEIPT_TABLE} (
                projection_key TEXT PRIMARY KEY,
                plan_sha256 TEXT NOT NULL UNIQUE,
                record_sha256 TEXT NOT NULL,
                market_id INTEGER NOT NULL UNIQUE,
                condition_id TEXT NOT NULL UNIQUE,
                evidence_origin TEXT NOT NULL,
                evidence_sha256 TEXT NOT NULL,
                record_json TEXT NOT NULL,
                plan_json TEXT NOT NULL,
                before_images_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status = '{PROJECTION_STATUS}'),
                committed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
        FAILURE_TABLE: f"""
            CREATE TABLE IF NOT EXISTS {FAILURE_TABLE} (
                failure_key TEXT PRIMARY KEY,
                input_sha256 TEXT NOT NULL,
                projection_key TEXT,
                market_id INTEGER,
                condition_id TEXT,
                reason TEXT NOT NULL,
                details_json TEXT NOT NULL,
                evidence_origin TEXT,
                evidence_sha256 TEXT,
                failed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
        LABEL_TABLE: f"""
            CREATE TABLE IF NOT EXISTS {LABEL_TABLE} (
                token_id TEXT PRIMARY KEY,
                market_id INTEGER NOT NULL,
                condition_id TEXT NOT NULL,
                source_index INTEGER NOT NULL CHECK (source_index IN (0, 1)),
                source_label TEXT NOT NULL,
                logical_outcome TEXT NOT NULL CHECK (logical_outcome IN ('YES', 'NO')),
                logical_outcome_index INTEGER NOT NULL CHECK (logical_outcome_index IN (0, 1)),
                semantic_mode TEXT NOT NULL CHECK (semantic_mode IN ({modes})),
                supports_yes_no_wording INTEGER NOT NULL,
                supports_directional_semantics INTEGER NOT NULL,
                evidence_origin TEXT NOT NULL,
                evidence_sha256 TEXT NOT NULL,
                plan_sha256 TEXT NOT NULL,
                projected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (market_id, source_index),
                UNIQUE (market_id, logical_outcome_index),
                UNIQUE (condition_id, source_index)
            )
        """,
        SYNC_TABLE: f"""
            CREATE TABLE IF NOT EXISTS {SYNC_TABLE} (
                projection_key TEXT PRIMARY KEY,
                market_id INTEGER NOT NULL UNIQUE,
                condition_id TEXT NOT NULL UNIQUE,
                plan_sha256 TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL CHECK (status = '{PROJECTION_STATUS}'),
                projected_token_count INTEGER NOT NULL CHECK (projected_token_count = 2),
                projected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
    }


def _sqlite_trigger_ddl(table: str, operation: str) -> str:
    schema, name = table.split(".", 1)
    trigger = f"{_TRIGGER_NAMES[table]}_{operation.lower()}"
    return f"""
        CREATE TRIGGER IF NOT EXISTS {schema}.{trigger}
        BEFORE {operation} ON {name}
        BEGIN
            SELECT RAISE(ABORT, 'market token source label projection rows are immutable');
        END
    """


def _attest_sqlite_schema(conn: Any) -> None:
    failures: Dict[str, Any] = {}
    ddls = _sqlite_table_ddls()
    for table, expected in ddls.items():
        schema, name = table.split(".", 1)
        row = conn.execute(
            f"SELECT sql FROM {schema}.sqlite_master WHERE type='table' AND name=?",
            (name,),
        ).fetchone()
        actual = _row_value(row, 0, "sql") if row is not None else None
        if _sql_signature(actual) != _sql_signature(expected):
            failures[f"table:{table}"] = "definition_mismatch"
        expected_triggers = {
            f"{_TRIGGER_NAMES[table]}_{operation.lower()}": _sqlite_trigger_ddl(table, operation)
            for operation in ("UPDATE", "DELETE")
        }
        rows = conn.execute(
            f"SELECT name, sql FROM {schema}.sqlite_master WHERE type='trigger' AND tbl_name=? ORDER BY name",
            (name,),
        ).fetchall()
        actual_triggers = {_clean(_row_value(item, 0, "name")): _row_value(item, 1, "sql") for item in rows}
        if set(actual_triggers) != set(expected_triggers):
            failures[f"triggers:{table}"] = {
                "expected": sorted(expected_triggers),
                "actual": sorted(actual_triggers),
            }
        elif any(
            _sql_signature(actual_triggers[name]) != _sql_signature(expected)
            for name, expected in expected_triggers.items()
        ):
            failures[f"trigger_definitions:{table}"] = "definition_mismatch"
    if failures:
        raise ProjectionBlockedError("projection_schema_attestation_failed", failures)


def _attest_postgres_schema(conn: Any) -> None:
    failures: Dict[str, Any] = {}
    for table, expected_columns in _POSTGRES_COLUMN_CONTRACT.items():
        relation_rows = conn.execute(
            """
            SELECT c.relkind AS relation_kind,
                   c.relpersistence AS relation_persistence,
                   c.relispartition AS is_partition,
                   c.relrowsecurity AS row_security_enabled,
                   c.relforcerowsecurity AS row_security_forced,
                   c.relhasrules AS has_rules,
                   NOT EXISTS (
                       SELECT 1 FROM pg_catalog.pg_inherits inheritance_parent
                       WHERE inheritance_parent.inhrelid = c.oid
                   ) AS has_no_inheritance_parent,
                   NOT EXISTS (
                       SELECT 1 FROM pg_catalog.pg_inherits inheritance_child
                       WHERE inheritance_child.inhparent = c.oid
                   ) AS has_no_inheritance_children
            FROM pg_catalog.pg_class c
            WHERE c.oid = ?::regclass
            """,
            (table,),
        ).fetchall()
        actual_relation_contract = (
            (
                _clean(_row_value(relation_rows[0], 0, "relation_kind")),
                _clean(_row_value(relation_rows[0], 1, "relation_persistence")),
                bool(_row_value(relation_rows[0], 2, "is_partition")),
                bool(_row_value(relation_rows[0], 3, "row_security_enabled")),
                bool(_row_value(relation_rows[0], 4, "row_security_forced")),
                bool(_row_value(relation_rows[0], 5, "has_rules")),
                bool(_row_value(relation_rows[0], 6, "has_no_inheritance_parent")),
                bool(_row_value(relation_rows[0], 7, "has_no_inheritance_children")),
            )
            if len(relation_rows) == 1
            else None
        )
        expected_relation_contract = (
            "r",
            "p",
            False,
            False,
            False,
            False,
            True,
            True,
        )
        if actual_relation_contract != expected_relation_contract:
            failures[f"relation:{table}"] = {
                "expected": expected_relation_contract,
                "actual": actual_relation_contract,
            }
        rows = conn.execute(
            """
            SELECT a.attname AS column_name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                   a.attnotnull AS not_null,
                   pg_catalog.pg_get_expr(d.adbin, d.adrelid, true) AS default_expression
            FROM pg_catalog.pg_attribute a
            LEFT JOIN pg_catalog.pg_attrdef d
              ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            WHERE a.attrelid = ?::regclass
              AND a.attnum > 0 AND NOT a.attisdropped
            ORDER BY a.attnum
            """,
            (table,),
        ).fetchall()
        actual_columns = tuple(
            (
                _clean(_row_value(row, 0, "column_name")),
                _clean(_row_value(row, 1, "data_type")).lower(),
                bool(_row_value(row, 2, "not_null")),
                _sql_signature(_row_value(row, 3, "default_expression")) or None,
            )
            for row in rows
        )
        if actual_columns != expected_columns:
            failures[f"columns:{table}"] = {
                "expected": expected_columns,
                "actual": actual_columns,
            }
        rows = conn.execute(
            """
            SELECT c.contype AS constraint_type,
                   ARRAY(SELECT a.attname FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
                         JOIN pg_catalog.pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.attnum
                         ORDER BY k.ord) AS columns,
                   rn.nspname AS referenced_schema,
                   rc.relname AS referenced_table,
                   ARRAY(SELECT a.attname FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, ord)
                         JOIN pg_catalog.pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.attnum
                         ORDER BY k.ord) AS referenced_columns,
                   CASE WHEN c.contype='c' THEN pg_catalog.pg_get_expr(c.conbin,c.conrelid,true) END
                     AS check_expression,
                   c.convalidated AS constraint_validated,
                   c.condeferrable AS constraint_deferrable,
                   c.condeferred AS constraint_initially_deferred,
                   c.confupdtype AS foreign_key_update_action,
                   c.confdeltype AS foreign_key_delete_action,
                   c.confmatchtype AS foreign_key_match_type,
                   c.connoinherit AS check_no_inherit,
                   c.conislocal AS constraint_is_local,
                   c.coninhcount AS constraint_inheritance_count
            FROM pg_catalog.pg_constraint c
            LEFT JOIN pg_catalog.pg_class rc ON rc.oid=c.confrelid
            LEFT JOIN pg_catalog.pg_namespace rn ON rn.oid=rc.relnamespace
            WHERE c.conrelid=?::regclass
            ORDER BY c.contype,c.conname
            """,
            (table,),
        ).fetchall()
        keys = []
        checks = []
        invalid_constraint_metadata: List[Dict[str, Any]] = []
        for row in rows:
            kind = _clean(_row_value(row, 0, "constraint_type"))
            columns = _sequence_tuple(_row_value(row, 1, "columns"))
            metadata_mismatches: Dict[str, Any] = {}
            if not bool(_row_value(row, 6, "constraint_validated")):
                metadata_mismatches["validated"] = False
            if bool(_row_value(row, 7, "constraint_deferrable")):
                metadata_mismatches["deferrable"] = True
            if bool(_row_value(row, 8, "constraint_initially_deferred")):
                metadata_mismatches["initially_deferred"] = True
            if kind == "f":
                foreign_key_contract = (
                    _clean(_row_value(row, 9, "foreign_key_update_action")),
                    _clean(_row_value(row, 10, "foreign_key_delete_action")),
                    _clean(_row_value(row, 11, "foreign_key_match_type")),
                )
                if foreign_key_contract != ("a", "a", "s"):
                    metadata_mismatches["foreign_key_action_match"] = foreign_key_contract
            if kind == "c" and bool(_row_value(row, 12, "check_no_inherit")):
                metadata_mismatches["check_no_inherit"] = True
            if not bool(_row_value(row, 13, "constraint_is_local")):
                metadata_mismatches["is_local"] = False
            inheritance_count = int(_row_value(row, 14, "constraint_inheritance_count") or 0)
            if inheritance_count != 0:
                metadata_mismatches["inheritance_count"] = inheritance_count
            if metadata_mismatches:
                invalid_constraint_metadata.append(
                    {
                        "constraint_type": kind,
                        "columns": columns,
                        "mismatches": metadata_mismatches,
                    }
                )
            if kind == "c":
                checks.append(_postgres_check_signature(_row_value(row, 5, "check_expression")))
            else:
                keys.append(
                    (
                        kind,
                        columns,
                        _clean(_row_value(row, 2, "referenced_schema")) or None,
                        _clean(_row_value(row, 3, "referenced_table")) or None,
                        _sequence_tuple(_row_value(row, 4, "referenced_columns")),
                    )
                )
        if invalid_constraint_metadata:
            failures[f"constraint_metadata:{table}"] = invalid_constraint_metadata
        if sorted(keys) != sorted(_POSTGRES_KEY_CONTRACT[table]):
            failures[f"keys:{table}"] = "primary_unique_or_foreign_key_mismatch"
        expected_checks = sorted(_postgres_check_signature(value) for value in _POSTGRES_CHECK_CONTRACT[table])
        if sorted(checks) != expected_checks:
            failures[f"checks:{table}"] = {
                "expected": expected_checks,
                "actual": sorted(checks),
            }

    function_rows = conn.execute(
        """
        SELECT pg_catalog.pg_get_function_result(p.oid), l.lanname, p.prosrc
        FROM pg_catalog.pg_proc p
        JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
        JOIN pg_catalog.pg_language l ON l.oid=p.prolang
        WHERE n.nspname='ops'
          AND p.proname='reject_market_token_source_label_projection_mutation_v1'
          AND pg_catalog.pg_get_function_identity_arguments(p.oid)=''
        """
    ).fetchall()
    expected_source = """
        BEGIN
            RAISE EXCEPTION 'market token source label projection rows are immutable';
            RETURN OLD;
        END;
    """
    function_ok = (
        len(function_rows) == 1
        and _clean(_row_value(function_rows[0], 0, "return_type")).lower() == "trigger"
        and _clean(_row_value(function_rows[0], 1, "language_name")).lower() == "plpgsql"
        and _sql_signature(_row_value(function_rows[0], 2, "function_source")) == _sql_signature(expected_source)
    )
    if not function_ok:
        failures["immutable_trigger_function"] = "definition_mismatch"
    trigger_rows = conn.execute(
        """
        SELECT t.tgname, n.nspname || '.' || c.relname, t.tgtype, t.tgenabled,
               fnn.nspname, p.proname, t.tgqual IS NULL, t.tgnargs,
               t.tgattr::text IN ('', '0')
        FROM pg_catalog.pg_trigger t
        JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_catalog.pg_proc p ON p.oid=t.tgfoid
        JOIN pg_catalog.pg_namespace fnn ON fnn.oid=p.pronamespace
        WHERE NOT t.tgisinternal AND n.nspname IN ('core','ops')
          AND c.relname IN (?, ?, ?, ?)
        ORDER BY n.nspname,c.relname,t.tgname
        """,
        tuple(table.split(".", 1)[1] for table in _TABLES),
    ).fetchall()
    actual_triggers: Dict[str, List[Dict[str, Any]]] = {}
    for row in trigger_rows:
        table_name = _clean(_row_value(row, 1, "table_name"))
        actual_triggers.setdefault(table_name, []).append(
            {
                "name": _clean(_row_value(row, 0, "trigger_name")),
                "type": int(_row_value(row, 2, "trigger_type")),
                "enabled": _clean(_row_value(row, 3, "trigger_enabled")),
                "function_schema": _clean(_row_value(row, 4, "function_schema")),
                "function_name": _clean(_row_value(row, 5, "function_name")),
                "no_when": bool(_row_value(row, 6, "no_when")),
                "arg_count": int(_row_value(row, 7, "arg_count")),
                "all_columns": bool(_row_value(row, 8, "all_columns")),
            }
        )
    for table in _TABLES:
        shared = {
            "enabled": "A",
            "function_schema": "ops",
            "function_name": IMMUTABLE_FUNCTION.split(".", 1)[1],
            "no_when": True,
            "arg_count": 0,
            "all_columns": True,
        }
        expected = sorted(
            [
                {"name": _TRIGGER_NAMES[table], "type": 27, **shared},
                {"name": _TRUNCATE_TRIGGER_NAMES[table], "type": 34, **shared},
            ],
            key=lambda item: item["name"],
        )
        observed = actual_triggers.get(table, [])
        if observed != expected:
            failures[f"immutable_trigger:{table}"] = {
                "expected": expected,
                "actual": observed,
            }
    if failures:
        raise ProjectionBlockedError("projection_schema_attestation_failed", failures)


def _attest_schema(conn: Any) -> None:
    if _is_sqlite(conn):
        _attest_sqlite_schema(conn)
    else:
        _attest_postgres_schema(conn)


def _immutability_contract() -> Dict[str, Any]:
    return {
        "immutability_scope": IMMUTABILITY_SCOPE,
        "privileged_ddl_resistance": PRIVILEGED_DDL_RESISTANCE,
        "runtime_role_separation_required": RUNTIME_ROLE_SEPARATION_REQUIRED,
    }


def _postgres_runtime_role_security_report(conn: Any) -> Dict[str, Any]:
    role_rows = conn.execute(
        """
        SELECT authenticated_role_row.rolname AS authenticated_role,
               session_user AS session_role,
               current_user AS current_role,
               authenticated_role_row.rolsuper AS authenticated_is_superuser,
               authenticated_role_row.rolcreaterole AS authenticated_can_create_role,
               authenticated_role_row.rolcreatedb AS authenticated_can_create_database,
               authenticated_role_row.rolreplication AS authenticated_is_replication_role,
               authenticated_role_row.rolbypassrls AS authenticated_can_bypass_rls,
               session_role_row.rolsuper AS session_is_superuser,
               session_role_row.rolcreaterole AS session_can_create_role,
               session_role_row.rolcreatedb AS session_can_create_database,
               session_role_row.rolreplication AS session_is_replication_role,
               session_role_row.rolbypassrls AS session_can_bypass_rls,
               current_role_row.rolsuper AS current_is_superuser,
               current_role_row.rolcreaterole AS current_can_create_role,
               current_role_row.rolcreatedb AS current_can_create_database,
               current_role_row.rolreplication AS current_is_replication_role,
               current_role_row.rolbypassrls AS current_can_bypass_rls,
               pg_catalog.pg_has_role(
                   authenticated_role_row.oid, current_role_row.oid, 'MEMBER'
               ) AS authenticated_is_current_member
        FROM pg_catalog.pg_stat_activity backend
        JOIN pg_catalog.pg_roles authenticated_role_row
          ON authenticated_role_row.oid = backend.usesysid
        JOIN pg_catalog.pg_roles session_role_row
          ON session_role_row.rolname = session_user
        JOIN pg_catalog.pg_roles current_role_row
          ON current_role_row.rolname = current_user
        WHERE backend.pid = pg_catalog.pg_backend_pid()
        """
    ).fetchall()
    if len(role_rows) != 1:
        raise ProjectionBlockedError("runtime_role_catalog_cardinality", {"row_count": len(role_rows)})
    role = role_rows[0]
    role_report = {
        "authenticated_role": _clean(_row_value(role, 0, "authenticated_role")),
        "session_role": _clean(_row_value(role, 1, "session_role")),
        "current_role": _clean(_row_value(role, 2, "current_role")),
        "authenticated_is_superuser": bool(_row_value(role, 3, "authenticated_is_superuser")),
        "authenticated_can_create_role": bool(_row_value(role, 4, "authenticated_can_create_role")),
        "authenticated_can_create_database": bool(_row_value(role, 5, "authenticated_can_create_database")),
        "authenticated_is_replication_role": bool(_row_value(role, 6, "authenticated_is_replication_role")),
        "authenticated_can_bypass_rls": bool(_row_value(role, 7, "authenticated_can_bypass_rls")),
        "session_is_superuser": bool(_row_value(role, 8, "session_is_superuser")),
        "session_can_create_role": bool(_row_value(role, 9, "session_can_create_role")),
        "session_can_create_database": bool(_row_value(role, 10, "session_can_create_database")),
        "session_is_replication_role": bool(_row_value(role, 11, "session_is_replication_role")),
        "session_can_bypass_rls": bool(_row_value(role, 12, "session_can_bypass_rls")),
        "current_is_superuser": bool(_row_value(role, 13, "current_is_superuser")),
        "current_can_create_role": bool(_row_value(role, 14, "current_can_create_role")),
        "current_can_create_database": bool(_row_value(role, 15, "current_can_create_database")),
        "current_is_replication_role": bool(_row_value(role, 16, "current_is_replication_role")),
        "current_can_bypass_rls": bool(_row_value(role, 17, "current_can_bypass_rls")),
        "authenticated_is_current_member": bool(_row_value(role, 18, "authenticated_is_current_member")),
    }
    authenticated_role = role_report["authenticated_role"]
    settable_role_memberships = [
        {
            "role_name": _clean(_row_value(row, 0, "role_name")),
            "is_superuser": bool(_row_value(row, 1, "is_superuser")),
            "can_create_role": bool(_row_value(row, 2, "can_create_role")),
            "can_create_database": bool(_row_value(row, 3, "can_create_database")),
            "is_replication_role": bool(_row_value(row, 4, "is_replication_role")),
            "can_bypass_rls": bool(_row_value(row, 5, "can_bypass_rls")),
        }
        for row in conn.execute(
            """
            SELECT candidate.rolname AS role_name,
                   candidate.rolsuper AS is_superuser,
                   candidate.rolcreaterole AS can_create_role,
                   candidate.rolcreatedb AS can_create_database,
                   candidate.rolreplication AS is_replication_role,
                   candidate.rolbypassrls AS can_bypass_rls
            FROM pg_catalog.pg_roles candidate
            WHERE pg_catalog.pg_has_role(?, candidate.oid, 'MEMBER')
              AND candidate.rolname <> ?
            ORDER BY candidate.rolname
            """,
            (authenticated_role, authenticated_role),
        ).fetchall()
    ]
    schema_rows = conn.execute(
        """
        SELECT namespace.nspname AS schema_name,
               pg_catalog.pg_get_userbyid(namespace.nspowner) AS owner_name,
               pg_catalog.pg_has_role(?, namespace.nspowner, 'MEMBER')
                 AS owner_or_owner_member,
               pg_catalog.has_schema_privilege(?, namespace.oid, 'CREATE')
                 AS can_create,
               pg_catalog.has_schema_privilege(?, namespace.oid, 'USAGE')
                 AS can_use
        FROM pg_catalog.pg_namespace namespace
        WHERE namespace.nspname IN ('core', 'ops')
        ORDER BY namespace.nspname
        """,
        (authenticated_role, authenticated_role, authenticated_role),
    ).fetchall()
    schemas = [
        {
            "schema_name": _clean(_row_value(row, 0, "schema_name")),
            "owner_name": _clean(_row_value(row, 1, "owner_name")),
            "owner_or_owner_member": bool(_row_value(row, 2, "owner_or_owner_member")),
            "can_create": bool(_row_value(row, 3, "can_create")),
            "can_use": bool(_row_value(row, 4, "can_use")),
        }
        for row in schema_rows
    ]
    table_rows = conn.execute(
        """
        SELECT namespace.nspname || '.' || table_class.relname AS table_name,
               pg_catalog.pg_get_userbyid(table_class.relowner) AS owner_name,
               pg_catalog.pg_has_role(?, table_class.relowner, 'MEMBER')
                 AS owner_or_owner_member,
               pg_catalog.has_table_privilege(?, table_class.oid, 'UPDATE')
                 AS can_update,
               pg_catalog.has_any_column_privilege(?, table_class.oid, 'UPDATE')
                 AS can_update_any_column,
               pg_catalog.has_table_privilege(?, table_class.oid, 'DELETE')
                 AS can_delete,
               pg_catalog.has_table_privilege(?, table_class.oid, 'TRUNCATE')
                 AS can_truncate,
               pg_catalog.has_table_privilege(?, table_class.oid, 'TRIGGER')
                 AS can_create_trigger
        FROM pg_catalog.pg_class table_class
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = table_class.relnamespace
        WHERE namespace.nspname || '.' || table_class.relname IN (?, ?, ?, ?)
        ORDER BY namespace.nspname, table_class.relname
        """,
        (
            authenticated_role,
            authenticated_role,
            authenticated_role,
            authenticated_role,
            authenticated_role,
            authenticated_role,
            *_TABLES,
        ),
    ).fetchall()
    tables = [
        {
            "table_name": _clean(_row_value(row, 0, "table_name")),
            "owner_name": _clean(_row_value(row, 1, "owner_name")),
            "owner_or_owner_member": bool(_row_value(row, 2, "owner_or_owner_member")),
            "can_update": bool(_row_value(row, 3, "can_update")),
            "can_update_any_column": bool(_row_value(row, 4, "can_update_any_column")),
            "can_delete": bool(_row_value(row, 5, "can_delete")),
            "can_truncate": bool(_row_value(row, 6, "can_truncate")),
            "can_create_trigger": bool(_row_value(row, 7, "can_create_trigger")),
        }
        for row in table_rows
    ]
    function_rows = conn.execute(
        """
        SELECT pg_catalog.pg_get_userbyid(function_proc.proowner) AS owner_name,
               pg_catalog.pg_has_role(?, function_proc.proowner, 'MEMBER')
                 AS owner_or_owner_member
        FROM pg_catalog.pg_proc function_proc
        JOIN pg_catalog.pg_namespace namespace ON namespace.oid = function_proc.pronamespace
        WHERE namespace.nspname = 'ops'
          AND function_proc.proname = 'reject_market_token_source_label_projection_mutation_v1'
          AND pg_catalog.pg_get_function_identity_arguments(function_proc.oid) = ''
        """,
        (authenticated_role,),
    ).fetchall()
    function_report = (
        {
            "owner_name": _clean(_row_value(function_rows[0], 0, "owner_name")),
            "owner_or_owner_member": bool(_row_value(function_rows[0], 1, "owner_or_owner_member")),
        }
        if len(function_rows) == 1
        else {"row_count": len(function_rows)}
    )
    violations: Dict[str, Any] = {}
    identity_roles = {
        role_report["authenticated_role"],
        role_report["session_role"],
        role_report["current_role"],
    }
    if len(identity_roles) != 1:
        violations["authenticated_session_current_role_mismatch"] = {
            "authenticated_role": role_report["authenticated_role"],
            "session_role": role_report["session_role"],
            "current_role": role_report["current_role"],
        }
    if not role_report["authenticated_is_current_member"]:
        violations["authenticated_cannot_set_current_role"] = True
    forbidden_identity_flags = {
        field: role_report[field]
        for field in (
            "authenticated_is_superuser",
            "authenticated_can_create_role",
            "authenticated_can_create_database",
            "authenticated_is_replication_role",
            "authenticated_can_bypass_rls",
            "session_is_superuser",
            "session_can_create_role",
            "session_can_create_database",
            "session_is_replication_role",
            "session_can_bypass_rls",
            "current_is_superuser",
            "current_can_create_role",
            "current_can_create_database",
            "current_is_replication_role",
            "current_can_bypass_rls",
        )
        if role_report[field]
    }
    if forbidden_identity_flags:
        violations["role_flags"] = forbidden_identity_flags
    if settable_role_memberships:
        # PostgreSQL 16 permits INHERIT FALSE, SET TRUE memberships.  In that
        # case privileges held only by the candidate role are intentionally
        # absent from has_*_privilege(current_user, ...), yet the same login
        # can SET ROLE in another session and replace a guard trigger.  The
        # immutable-writer credential therefore has no role memberships at all.
        violations["unexpected_role_memberships"] = settable_role_memberships
    if {item["schema_name"] for item in schemas} != {"core", "ops"}:
        violations["schema_cardinality"] = [item["schema_name"] for item in schemas]
    unsafe_schemas = [
        item for item in schemas if item["owner_or_owner_member"] or item["can_create"] or not item["can_use"]
    ]
    if unsafe_schemas:
        violations["schemas"] = unsafe_schemas
    if {item["table_name"] for item in tables} != set(_TABLES):
        violations["table_cardinality"] = [item["table_name"] for item in tables]
    unsafe_tables = [
        item
        for item in tables
        if item["owner_or_owner_member"]
        or item["can_update"]
        or item["can_update_any_column"]
        or item["can_delete"]
        or item["can_truncate"]
        or item["can_create_trigger"]
    ]
    if unsafe_tables:
        violations["tables"] = unsafe_tables
    if "row_count" in function_report:
        violations["function_cardinality"] = function_report
    elif function_report.get("owner_or_owner_member"):
        violations["function_owner_membership"] = function_report
    return {
        **_immutability_contract(),
        "runtime_role": role_report["authenticated_role"],
        "runtime_role_separation_verified": not violations,
        "role": role_report,
        "settable_role_memberships": settable_role_memberships,
        "schemas": schemas,
        "tables": tables,
        "trigger_function": function_report,
        "violations": violations,
    }


def _attest_postgres_runtime_role_security(conn: Any) -> Dict[str, Any]:
    report = _postgres_runtime_role_security_report(conn)
    if not report["runtime_role_separation_verified"]:
        raise ProjectionBlockedError("runtime_role_separation_attestation_failed", report)
    return report


def _is_missing_relation_error(exc: Exception) -> bool:
    sqlstate = _clean(getattr(exc, "sqlstate", None) or getattr(exc, "pgcode", None))
    return sqlstate in {"42P01", "3F000"} or exc.__class__.__name__ in {
        "UndefinedTable",
        "InvalidSchemaName",
    }


def _lock_projection_relations_if_present(conn: Any, *, write_intent: bool) -> bool:
    """Lock every ledger relation before reading any schema contract.

    The savepoint is only an absent-schema probe.  On success, releasing it
    preserves all relation locks until the caller commits or rolls back.  That
    prevents concurrent ALTER/DROP/TRUNCATE from invalidating a successful
    attestation between the catalog read and immutable-ledger writes.  A write
    path uses ROW EXCLUSIVE because it conflicts with ALTER TABLE's SHARE ROW
    EXCLUSIVE lock; read-only preparation uses ACCESS SHARE and is re-attested
    under the stronger lock before any eventual apply.
    """

    if _is_sqlite(conn):
        return _schema_presence(conn)
    savepoint = "market_token_source_label_schema_probe"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        mode = "ROW EXCLUSIVE" if write_intent else "ACCESS SHARE"
        conn.execute("LOCK TABLE " + ", ".join(_TABLES) + f" IN {mode} MODE")
    except Exception as exc:
        conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        if _is_missing_relation_error(exc):
            return False
        raise
    conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    return True


def _attest_schema_if_present(conn: Any) -> None:
    if _is_sqlite(conn):
        if _schema_presence(conn):
            _attest_schema(conn)
        return
    if _lock_projection_relations_if_present(conn, write_intent=False):
        _attest_schema(conn)
        return
    # A failed all-table lock must mean either no schema or a partial schema.
    # The latter is terminal; it must never be filled in opportunistically.
    if _schema_presence(conn):
        if not _lock_projection_relations_if_present(conn, write_intent=False):
            raise ProjectionBlockedError("projection_schema_lock_race")
        _attest_schema(conn)


def _postgres_table_ddls() -> List[str]:
    modes = ", ".join(f"'{value}'" for value in SEMANTIC_MODES)
    return [
        f"""
        CREATE TABLE IF NOT EXISTS {RECEIPT_TABLE} (
            projection_key TEXT PRIMARY KEY,
            plan_sha256 TEXT NOT NULL UNIQUE,
            record_sha256 TEXT NOT NULL,
            market_id BIGINT NOT NULL UNIQUE REFERENCES core.markets(id),
            condition_id TEXT NOT NULL UNIQUE,
            evidence_origin TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            record_json JSONB NOT NULL,
            plan_json JSONB NOT NULL,
            before_images_json JSONB NOT NULL,
            status TEXT NOT NULL CHECK (status = '{PROJECTION_STATUS}'),
            committed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {FAILURE_TABLE} (
            failure_key TEXT PRIMARY KEY,
            input_sha256 TEXT NOT NULL,
            projection_key TEXT,
            market_id BIGINT,
            condition_id TEXT,
            reason TEXT NOT NULL,
            details_json JSONB NOT NULL,
            evidence_origin TEXT,
            evidence_sha256 TEXT,
            failed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {LABEL_TABLE} (
            token_id TEXT PRIMARY KEY REFERENCES core.market_tokens(token_id),
            market_id BIGINT NOT NULL REFERENCES core.markets(id),
            condition_id TEXT NOT NULL,
            source_index SMALLINT NOT NULL CHECK (source_index IN (0, 1)),
            source_label TEXT NOT NULL,
            logical_outcome TEXT NOT NULL CHECK (logical_outcome IN ('YES', 'NO')),
            logical_outcome_index SMALLINT NOT NULL CHECK (logical_outcome_index IN (0, 1)),
            semantic_mode TEXT NOT NULL CHECK (semantic_mode IN ({modes})),
            supports_yes_no_wording BOOLEAN NOT NULL,
            supports_directional_semantics BOOLEAN NOT NULL,
            evidence_origin TEXT NOT NULL,
            evidence_sha256 TEXT NOT NULL,
            plan_sha256 TEXT NOT NULL REFERENCES {RECEIPT_TABLE}(plan_sha256),
            projected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (market_id, source_index),
            UNIQUE (market_id, logical_outcome_index),
            UNIQUE (condition_id, source_index)
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS {SYNC_TABLE} (
            projection_key TEXT PRIMARY KEY REFERENCES {RECEIPT_TABLE}(projection_key),
            market_id BIGINT NOT NULL UNIQUE REFERENCES core.markets(id),
            condition_id TEXT NOT NULL UNIQUE,
            plan_sha256 TEXT NOT NULL UNIQUE REFERENCES {RECEIPT_TABLE}(plan_sha256),
            status TEXT NOT NULL CHECK (status = '{PROJECTION_STATUS}'),
            projected_token_count SMALLINT NOT NULL CHECK (projected_token_count = 2),
            projected_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """,
    ]


def _ensure_schema(conn: Any, *, allow_bootstrap: bool = False) -> bool:
    """Lock and attest the ledger schema, creating it only for bootstrap.

    SQLite remains a transactional test seam and may create its in-memory
    schema on first use.  PostgreSQL runtime write paths are deliberately
    unable to turn a missing schema into owner-controlled ledger objects.
    """

    if _is_sqlite(conn):
        if _schema_presence(conn):
            _attest_schema(conn)
            return False
        for ddl in _sqlite_table_ddls().values():
            conn.execute(ddl)
        for table in _TABLES:
            for operation in ("UPDATE", "DELETE"):
                conn.execute(_sqlite_trigger_ddl(table, operation))
        _attest_schema(conn)
        return True
    if _lock_projection_relations_if_present(conn, write_intent=True):
        _attest_schema(conn)
        return False
    if _schema_presence(conn):
        if not _lock_projection_relations_if_present(conn, write_intent=True):
            raise ProjectionBlockedError("projection_schema_lock_race")
        _attest_schema(conn)
        return False
    if not allow_bootstrap:
        raise ProjectionBlockedError("projection_schema_bootstrap_required")
    conn.execute("CREATE SCHEMA IF NOT EXISTS ops")
    for ddl in _postgres_table_ddls():
        conn.execute(ddl)
    conn.execute(
        """
        DO $outer$
        BEGIN
            CREATE FUNCTION ops.reject_market_token_source_label_projection_mutation_v1()
            RETURNS trigger LANGUAGE plpgsql AS $function$
            BEGIN
                RAISE EXCEPTION 'market token source label projection rows are immutable';
                RETURN OLD;
            END;
            $function$;
        EXCEPTION WHEN duplicate_function THEN NULL;
        END;
        $outer$
        """
    )
    for table in _TABLES:
        conn.execute(
            f"""
            DO $block$
            BEGIN
                CREATE TRIGGER {_TRIGGER_NAMES[table]}
                BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION {IMMUTABLE_FUNCTION}();
            EXCEPTION WHEN duplicate_object THEN NULL;
            END;
            $block$
            """
        )
        conn.execute(
            f"""
            DO $block$
            BEGIN
                CREATE TRIGGER {_TRUNCATE_TRIGGER_NAMES[table]}
                BEFORE TRUNCATE ON {table}
                FOR EACH STATEMENT EXECUTE FUNCTION {IMMUTABLE_FUNCTION}();
            EXCEPTION WHEN duplicate_object THEN NULL;
            END;
            $block$
            """
        )
        conn.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {_TRIGGER_NAMES[table]}")
        conn.execute(f"ALTER TABLE {table} ENABLE ALWAYS TRIGGER {_TRUNCATE_TRIGGER_NAMES[table]}")
    if not _lock_projection_relations_if_present(conn, write_intent=True):
        raise ProjectionBlockedError("projection_schema_missing_after_create")
    _attest_schema(conn)
    return True


def bootstrap_projection_schema(conn: Any) -> Dict[str, Any]:
    """Explicit admin-only schema bootstrap; it never projects a market."""

    _require_supported_connection(conn)
    _require_idle_connection(conn)
    _begin_transaction(conn, read_only=False)
    try:
        created = _ensure_schema(conn, allow_bootstrap=True)
        conn.commit()
        return {
            "status": "SCHEMA_BOOTSTRAPPED" if created else "SCHEMA_READY",
            "schema_created": bool(created),
            **_immutability_contract(),
            "runtime_role_separation_verified": False,
            "market_projected": False,
        }
    except Exception:
        conn.rollback()
        raise


def _decoded_json(value: Any, *, field: str) -> Any:
    if isinstance(value, (dict, list)):
        return deepcopy(value)
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ProjectionBlockedError("invalid_ledger_json", {"field": field}) from exc


def _fetch_market(conn: Any, market_id: int) -> Dict[str, Any]:
    rows = conn.execute(
        f"SELECT {', '.join(MARKET_COLUMNS)} FROM core.markets WHERE id=?",
        (int(market_id),),
    ).fetchall()
    if len(rows) != 1:
        raise ProjectionBlockedError("canonical_market_not_unique", {"market_id": market_id, "row_count": len(rows)})
    row = _row_dict(rows[0], MARKET_COLUMNS)
    row["id"] = int(row["id"])
    for field in ("condition_id", "yes_token_id", "no_token_id"):
        row[field] = _clean(row[field])
    row["condition_id"] = _normalize_condition(row["condition_id"])
    return row


def _fetch_market_tokens(conn: Any, market_id: int) -> List[Dict[str, Any]]:
    rows = conn.execute(
        f"SELECT {', '.join(TOKEN_COLUMNS)} FROM core.market_tokens WHERE market_id=? ORDER BY id, token_id",
        (int(market_id),),
    ).fetchall()
    result = []
    for item in rows:
        row = _row_dict(item, TOKEN_COLUMNS)
        row["id"] = int(row["id"])
        row["market_id"] = int(row["market_id"])
        row["condition_id"] = _normalize_condition(row["condition_id"])
        row["token_id"] = _clean(row["token_id"])
        row["outcome"] = _clean(row["outcome"]).upper()
        row["outcome_index"] = int(row["outcome_index"])
        result.append(row)
    return result


def _fetch_token_registry_rows(conn: Any, token_ids: Iterable[str]) -> List[Dict[str, Any]]:
    ordered_ids = sorted({_clean(value) for value in token_ids if _clean(value)})
    if not ordered_ids:
        return []
    placeholders = ",".join("?" for _ in ordered_ids)
    rows = conn.execute(
        f"SELECT {', '.join(TOKEN_COLUMNS)} FROM core.market_tokens "
        f"WHERE token_id IN ({placeholders}) ORDER BY token_id, id",
        tuple(ordered_ids),
    ).fetchall()
    result = []
    for item in rows:
        row = _row_dict(item, TOKEN_COLUMNS)
        row["id"] = int(row["id"])
        row["market_id"] = int(row["market_id"])
        row["condition_id"] = _normalize_condition(row["condition_id"])
        row["token_id"] = _clean(row["token_id"])
        row["outcome"] = _clean(row["outcome"]).upper()
        row["outcome_index"] = int(row["outcome_index"])
        result.append(row)
    return result


def _fetch_labels(conn: Any, market_id: int) -> List[Dict[str, Any]]:
    if not _table_exists(conn, LABEL_TABLE):
        return []
    rows = conn.execute(
        f"SELECT {', '.join(LABEL_COLUMNS)} FROM {LABEL_TABLE} WHERE market_id=? ORDER BY source_index, token_id",
        (int(market_id),),
    ).fetchall()
    result = []
    for item in rows:
        row = _row_dict(item, LABEL_COLUMNS)
        row["market_id"] = int(row["market_id"])
        row["source_index"] = int(row["source_index"])
        row["logical_outcome_index"] = int(row["logical_outcome_index"])
        row["supports_yes_no_wording"] = bool(row["supports_yes_no_wording"])
        row["supports_directional_semantics"] = bool(row["supports_directional_semantics"])
        result.append(_json_safe(row))
    return result


def _conflicting_ledger_rows(conn: Any, *, market_id: int, condition_id: str) -> Dict[str, List[Dict[str, Any]]]:
    conflicts: Dict[str, List[Dict[str, Any]]] = {"receipts": [], "sync_states": []}
    for table, key in ((RECEIPT_TABLE, "receipts"), (SYNC_TABLE, "sync_states")):
        if not _table_exists(conn, table):
            continue
        rows = conn.execute(
            f"SELECT projection_key, market_id, condition_id, plan_sha256 FROM {table} "
            "WHERE market_id=? OR lower(condition_id)=? ORDER BY projection_key",
            (int(market_id), condition_id.lower()),
        ).fetchall()
        conflicts[key] = [
            {
                "projection_key": _clean(_row_value(row, 0, "projection_key")),
                "market_id": int(_row_value(row, 1, "market_id")),
                "condition_id": _clean(_row_value(row, 2, "condition_id")),
                "plan_sha256": _clean(_row_value(row, 3, "plan_sha256")),
            }
            for row in rows
        ]
    return conflicts


def _projection_key(record: Mapping[str, Any]) -> str:
    return _sha256(
        {
            "schema_version": PLAN_SCHEMA_VERSION,
            "market_id": int(record["market_id"]),
            "condition_id": record["condition_id"],
        }
    )


def _expected_label_rows(record: Mapping[str, Any], plan_sha256: str = "") -> List[Dict[str, Any]]:
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


def _validate_registry(
    market: Mapping[str, Any],
    tokens: Sequence[Mapping[str, Any]],
    registry_rows: Sequence[Mapping[str, Any]],
    record: Mapping[str, Any],
) -> None:
    failures: Dict[str, Any] = {}
    if market["condition_id"] != record["condition_id"]:
        failures["market_condition_id"] = {
            "expected": record["condition_id"],
            "actual": market["condition_id"],
        }
    if len(tokens) != 2:
        failures["market_token_count"] = len(tokens)
    token_ids = [slot["token_id"] for slot in record["source_slots"]]
    token_by_id = {row["token_id"]: row for row in tokens}
    if len(token_by_id) != len(tokens) or set(token_by_id) != set(token_ids):
        failures["registry_token_ids"] = {
            "expected": sorted(token_ids),
            "actual": sorted(token_by_id),
        }
    registry_by_id: Dict[str, List[Mapping[str, Any]]] = {}
    for row in registry_rows:
        registry_by_id.setdefault(str(row["token_id"]), []).append(row)
    registry_cardinality = {token_id: len(registry_by_id.get(token_id, [])) for token_id in token_ids}
    if registry_cardinality != {token_id: 1 for token_id in token_ids}:
        failures["registry_token_global_cardinality"] = registry_cardinality
    else:
        wrong_owners = {
            token_id: int(registry_by_id[token_id][0]["market_id"])
            for token_id in token_ids
            if int(registry_by_id[token_id][0]["market_id"]) != int(record["market_id"])
        }
        if wrong_owners:
            failures["registry_token_owners"] = wrong_owners
    logical_market = {0: market["yes_token_id"], 1: market["no_token_id"]}
    for slot in record["source_slots"]:
        token_id = slot["token_id"]
        logical_index = int(slot["logical_outcome_index"])
        if logical_market[logical_index] != token_id:
            failures[f"market_logical_slot:{logical_index}"] = {
                "expected": token_id,
                "actual": logical_market[logical_index],
            }
        token = token_by_id.get(token_id)
        if token is None:
            continue
        expected = {
            "market_id": int(record["market_id"]),
            "condition_id": record["condition_id"],
            "outcome": slot["logical_outcome"],
            "outcome_index": logical_index,
        }
        actual = {field: token[field] for field in expected}
        if actual != expected:
            failures[f"registry_token:{token_id}"] = {
                "expected": expected,
                "actual": actual,
            }
    if failures:
        raise ProjectionBlockedError("canonical_registry_bijection_mismatch", failures)


def _build_new_plan(conn: Any, record: Mapping[str, Any]) -> Dict[str, Any]:
    market = _fetch_market(conn, int(record["market_id"]))
    tokens = _fetch_market_tokens(conn, int(record["market_id"]))
    registry_rows = _fetch_token_registry_rows(conn, [slot["token_id"] for slot in record["source_slots"]])
    _validate_registry(market, tokens, registry_rows, record)
    existing_labels = _fetch_labels(conn, int(record["market_id"]))
    if existing_labels:
        raise ProjectionBlockedError("unreceipted_projection_evidence", {"rows": existing_labels})
    ledger_rows = _conflicting_ledger_rows(
        conn,
        market_id=int(record["market_id"]),
        condition_id=str(record["condition_id"]),
    )
    if ledger_rows["receipts"] or ledger_rows["sync_states"]:
        raise ProjectionBlockedError("conflicting_projection_ledger_state", ledger_rows)
    projection_key = _projection_key(record)
    core = {
        "schema_version": PLAN_SCHEMA_VERSION,
        "projection_key": projection_key,
        "record_sha256": _sha256(record),
        "record": deepcopy(dict(record)),
        "before_images": {
            "market": market,
            "market_tokens": tokens,
            "token_registry_rows": registry_rows,
            "labels": [],
        },
        "expected": {
            "status": PROJECTION_STATUS,
            "projected_token_count": 2,
            "label_rows_without_plan_sha256": _expected_label_rows(record),
            "immutability_contract": _immutability_contract(),
        },
    }
    plan = deepcopy(core)
    plan["plan_sha256"] = _sha256(core)
    return plan


def _validate_plan(plan: Mapping[str, Any]) -> Dict[str, Any]:
    candidate = _strict_json_object(plan, field="plan")
    stored_sha = _exact_sha(candidate.pop("plan_sha256", ""), field="plan_sha256")
    actual_sha = _sha256(candidate)
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
    if candidate.get("record_sha256") != _sha256(normalized):
        mismatches["record_sha256"] = "mismatch"
    if candidate.get("projection_key") != _projection_key(normalized):
        mismatches["projection_key"] = "mismatch"
    expected = candidate.get("expected")
    if not isinstance(expected, Mapping):
        mismatches["expected"] = "missing"
    else:
        if expected.get("status") != PROJECTION_STATUS:
            mismatches["expected.status"] = "mismatch"
        if expected.get("projected_token_count") != 2:
            mismatches["expected.projected_token_count"] = "mismatch"
        if expected.get("label_rows_without_plan_sha256") != _expected_label_rows(normalized):
            mismatches["expected.label_rows_without_plan_sha256"] = "mismatch"
        if expected.get("immutability_contract") != _immutability_contract():
            mismatches["expected.immutability_contract"] = "mismatch"
    if mismatches:
        raise ProjectionBlockedError("plan_semantics_mismatch", mismatches)
    candidate["plan_sha256"] = stored_sha
    return candidate


def _load_receipt(conn: Any, projection_key: str, *, for_update: bool = False) -> Optional[Dict[str, Any]]:
    if not _table_exists(conn, RECEIPT_TABLE):
        return None
    suffix = " FOR UPDATE" if for_update and not _is_sqlite(conn) else ""
    row = conn.execute(
        f"SELECT {', '.join(RECEIPT_COLUMNS)} FROM {RECEIPT_TABLE} WHERE projection_key=?{suffix}",
        (projection_key,),
    ).fetchone()
    if row is None:
        return None
    result = _row_dict(row, RECEIPT_COLUMNS)
    result["market_id"] = int(result["market_id"])
    for field in ("record_json", "plan_json", "before_images_json"):
        result[field] = _decoded_json(result[field], field=field)
    return _json_safe(result)


def _load_sync(conn: Any, projection_key: str) -> Optional[Dict[str, Any]]:
    if not _table_exists(conn, SYNC_TABLE):
        return None
    row = conn.execute(
        f"SELECT {', '.join(SYNC_COLUMNS)} FROM {SYNC_TABLE} WHERE projection_key=?",
        (projection_key,),
    ).fetchone()
    if row is None:
        return None
    result = _row_dict(row, SYNC_COLUMNS)
    result["market_id"] = int(result["market_id"])
    result["projected_token_count"] = int(result["projected_token_count"])
    return result


def _postcheck(conn: Any, plan: Mapping[str, Any], receipt: Mapping[str, Any]) -> None:
    record = plan["record"]
    market = _fetch_market(conn, int(record["market_id"]))
    tokens = _fetch_market_tokens(conn, int(record["market_id"]))
    registry_rows = _fetch_token_registry_rows(conn, [slot["token_id"] for slot in record["source_slots"]])
    _validate_registry(market, tokens, registry_rows, record)
    if (
        market != plan["before_images"]["market"]
        or tokens != plan["before_images"]["market_tokens"]
        or registry_rows != plan["before_images"]["token_registry_rows"]
    ):
        raise ProjectionBlockedError("canonical_registry_changed_postcheck")
    expected_labels = _expected_label_rows(record, plan["plan_sha256"])
    actual_labels = _fetch_labels(conn, int(record["market_id"]))
    if actual_labels != expected_labels:
        raise ProjectionBlockedError(
            "label_projection_postcheck_failed",
            {"expected": expected_labels, "actual": actual_labels},
        )
    expected_receipt = {
        "projection_key": plan["projection_key"],
        "plan_sha256": plan["plan_sha256"],
        "record_sha256": plan["record_sha256"],
        "market_id": int(record["market_id"]),
        "condition_id": record["condition_id"],
        "evidence_origin": record["evidence_origin"],
        "evidence_sha256": record["evidence_sha256"],
        "record_json": record,
        "plan_json": plan,
        "before_images_json": plan["before_images"],
        "status": PROJECTION_STATUS,
    }
    if dict(receipt) != expected_receipt:
        raise ProjectionBlockedError("immutable_receipt_content_mismatch")
    sync = _load_sync(conn, plan["projection_key"])
    expected_sync = {
        "projection_key": plan["projection_key"],
        "market_id": int(record["market_id"]),
        "condition_id": record["condition_id"],
        "plan_sha256": plan["plan_sha256"],
        "status": PROJECTION_STATUS,
        "projected_token_count": 2,
    }
    if sync != expected_sync:
        raise ProjectionBlockedError("sync_state_postcheck_failed", {"expected": expected_sync, "actual": sync})


def _validate_existing_receipt(conn: Any, receipt: Mapping[str, Any], record: Mapping[str, Any]) -> Dict[str, Any]:
    plan = _validate_plan(receipt["plan_json"])
    expected_fields = {
        "projection_key": _projection_key(record),
        "plan_sha256": plan["plan_sha256"],
        "record_sha256": _sha256(record),
        "market_id": int(record["market_id"]),
        "condition_id": record["condition_id"],
        "evidence_origin": record["evidence_origin"],
        "evidence_sha256": record["evidence_sha256"],
        "status": PROJECTION_STATUS,
    }
    mismatches = {
        field: {"expected": expected, "actual": receipt.get(field)}
        for field, expected in expected_fields.items()
        if receipt.get(field) != expected
    }
    if receipt.get("record_json") != record:
        mismatches["record_json"] = "conflict"
    if receipt.get("before_images_json") != plan["before_images"]:
        mismatches["before_images_json"] = "conflict"
    if mismatches:
        raise ProjectionBlockedError("existing_receipt_identity_conflict", mismatches)
    _postcheck(conn, plan, receipt)
    return plan


def _prepare_projection_in_current_transaction(conn: Any, record: Mapping[str, Any]) -> Dict[str, Any]:
    _attest_schema_if_present(conn)
    normalized = normalize_projection_record(record)
    projection_key = _projection_key(normalized)
    receipt = _load_receipt(conn, projection_key)
    if receipt is not None:
        return _validate_existing_receipt(conn, receipt, normalized)
    if _schema_presence(conn):
        labels = _fetch_labels(conn, int(normalized["market_id"]))
        sync = _load_sync(conn, projection_key)
        if labels or sync:
            raise ProjectionBlockedError("projection_state_without_receipt", {"labels": labels, "sync": sync})
    return _build_new_plan(conn, normalized)


def prepare_projection(conn: Any, record: Mapping[str, Any]) -> Dict[str, Any]:
    """Read and checksum-pin one projection, returning the connection idle.

    PostgreSQL callers must provide an idle connection.  This public entrypoint
    owns a REPEATABLE READ READ ONLY transaction and always rolls it back,
    including normalization/schema failures.  Transaction-owning workflows may
    use the private current-transaction helper deliberately.
    """

    _require_supported_connection(conn)
    if _is_sqlite(conn):
        return _prepare_projection_in_current_transaction(conn, record)
    _begin_transaction(conn, read_only=True)
    try:
        return _prepare_projection_in_current_transaction(conn, record)
    finally:
        conn.rollback()


def dry_run_projection(conn: Any, record: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a no-write plan from one consistent read snapshot."""

    plan = prepare_projection(conn, record)
    return {
        "status": "PREPARED",
        "dry_run": True,
        "projection_key": plan["projection_key"],
        "plan_sha256": plan["plan_sha256"],
        "market_id": int(plan["record"]["market_id"]),
        "condition_id": plan["record"]["condition_id"],
        **_immutability_contract(),
        "runtime_role_separation_verified": False,
        "plan": plan,
    }


def _acquire_locks(conn: Any, plan: Mapping[str, Any]) -> None:
    if _is_sqlite(conn):
        return
    conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(?, 0))",
        (f"{ADVISORY_LOCK_NAMESPACE}:{plan['projection_key']}",),
    )
    market_id = int(plan["record"]["market_id"])
    conn.execute("SELECT id FROM core.markets WHERE id=? FOR UPDATE", (market_id,)).fetchall()
    conn.execute(
        "SELECT id FROM core.market_tokens WHERE market_id=? OR token_id IN (?, ?) ORDER BY id FOR UPDATE",
        (
            market_id,
            plan["record"]["source_slots"][0]["token_id"],
            plan["record"]["source_slots"][1]["token_id"],
        ),
    ).fetchall()


def _insert_receipt(conn: Any, plan: Mapping[str, Any]) -> Dict[str, Any]:
    record = plan["record"]
    casts = "?, ?, ?" if _is_sqlite(conn) else "?::jsonb, ?::jsonb, ?::jsonb"
    cursor = conn.execute(
        f"""
        INSERT INTO {RECEIPT_TABLE} (
            projection_key, plan_sha256, record_sha256, market_id, condition_id,
            evidence_origin, evidence_sha256, record_json, plan_json,
            before_images_json, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, {casts}, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            plan["projection_key"],
            plan["plan_sha256"],
            plan["record_sha256"],
            int(record["market_id"]),
            record["condition_id"],
            record["evidence_origin"],
            record["evidence_sha256"],
            _canonical_json(record),
            _canonical_json(plan),
            _canonical_json(plan["before_images"]),
            PROJECTION_STATUS,
        ),
    )
    if int(cursor.rowcount or 0) != 1:
        raise ProjectionBlockedError("receipt_insert_cas_failed")
    receipt = _load_receipt(conn, plan["projection_key"], for_update=True)
    if receipt is None:
        raise ProjectionBlockedError("receipt_missing_after_insert")
    return receipt


def _insert_labels(conn: Any, plan: Mapping[str, Any], *, fault_after: Optional[int]) -> None:
    rows = _expected_label_rows(plan["record"], plan["plan_sha256"])
    for index, row in enumerate(rows, start=1):
        cursor = conn.execute(
            f"""
            INSERT INTO {LABEL_TABLE} ({", ".join(LABEL_COLUMNS)})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            tuple(row[column] for column in LABEL_COLUMNS),
        )
        if int(cursor.rowcount or 0) != 1:
            raise ProjectionBlockedError("label_insert_cas_failed", {"token_id": row["token_id"]})
        if fault_after == index:
            raise RuntimeError(f"injected failure after label insert {index}")


def _insert_sync(conn: Any, plan: Mapping[str, Any]) -> None:
    record = plan["record"]
    cursor = conn.execute(
        f"""
        INSERT INTO {SYNC_TABLE} ({", ".join(SYNC_COLUMNS)})
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (
            plan["projection_key"],
            int(record["market_id"]),
            record["condition_id"],
            plan["plan_sha256"],
            PROJECTION_STATUS,
            2,
        ),
    )
    if int(cursor.rowcount or 0) != 1:
        raise ProjectionBlockedError("sync_state_insert_cas_failed")


def apply_projection_in_owned_transaction(
    conn: Any,
    record: Mapping[str, Any],
    *,
    fault_after_label_insert: Optional[int] = None,
) -> Dict[str, Any]:
    """Project one record inside an enclosing transaction without finishing it.

    This entrypoint exists for a larger atomic registry workflow whose own
    checksum-pinned plan authorizes the record before the canonical market id
    exists.  It never commits or rolls back.  The caller must own a healthy
    transaction and must roll the entire workflow back on any exception.
    """

    _require_supported_connection(conn)
    _require_active_owned_transaction(conn)
    if fault_after_label_insert not in (None, 1, 2):
        raise ValueError("fault_after_label_insert must be 1, 2, or None")
    _ensure_schema(conn)
    runtime_role_separation_verified = False
    if not _is_sqlite(conn):
        runtime_security = _attest_postgres_runtime_role_security(conn)
        runtime_role_separation_verified = bool(runtime_security["runtime_role_separation_verified"])
    normalized = normalize_projection_record(record)
    lock_plan = {
        "projection_key": _projection_key(normalized),
        "record": normalized,
    }
    _acquire_locks(conn, lock_plan)
    existing = _load_receipt(conn, lock_plan["projection_key"], for_update=True)
    if existing is not None:
        stored = _validate_existing_receipt(conn, existing, normalized)
        return _result(
            stored,
            idempotent=True,
            runtime_role_separation_verified=runtime_role_separation_verified,
        )
    plan = _build_new_plan(conn, normalized)
    receipt = _insert_receipt(conn, plan)
    _insert_labels(conn, plan, fault_after=fault_after_label_insert)
    _insert_sync(conn, plan)
    _postcheck(conn, plan, receipt)
    return _result(
        plan,
        idempotent=False,
        runtime_role_separation_verified=runtime_role_separation_verified,
    )


def attest_projection_in_owned_transaction(
    conn: Any,
    record: Mapping[str, Any],
    *,
    expected_plan_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Re-prove an existing projection inside the enclosing transaction."""

    _require_supported_connection(conn)
    _require_active_owned_transaction(conn)
    _ensure_schema(conn)
    runtime_role_separation_verified = False
    if not _is_sqlite(conn):
        runtime_security = _attest_postgres_runtime_role_security(conn)
        runtime_role_separation_verified = bool(runtime_security["runtime_role_separation_verified"])
    normalized = normalize_projection_record(record)
    lock_plan = {
        "projection_key": _projection_key(normalized),
        "record": normalized,
    }
    _acquire_locks(conn, lock_plan)
    receipt = _load_receipt(conn, lock_plan["projection_key"], for_update=True)
    if receipt is None:
        raise ProjectionBlockedError("projection_receipt_missing_for_attestation")
    stored = _validate_existing_receipt(conn, receipt, normalized)
    if expected_plan_sha256 is not None:
        expected_sha = _exact_sha(
            expected_plan_sha256,
            field="expected_plan_sha256",
        )
        if stored["plan_sha256"] != expected_sha:
            raise ProjectionBlockedError(
                "projection_plan_sha256_mismatch",
                {
                    "expected_plan_sha256": expected_sha,
                    "actual_plan_sha256": stored["plan_sha256"],
                },
            )
    return _result(
        stored,
        idempotent=True,
        runtime_role_separation_verified=runtime_role_separation_verified,
    )


def attest_projection_read_only(
    conn: Any,
    record: Mapping[str, Any],
) -> Dict[str, Any]:
    """Validate an existing receipt/state in the caller's read snapshot."""

    _require_supported_connection(conn)
    _attest_schema_if_present(conn)
    normalized = normalize_projection_record(record)
    projection_key = _projection_key(normalized)
    receipt = _load_receipt(conn, projection_key)
    if receipt is None:
        raise ProjectionBlockedError("projection_receipt_missing_for_attestation")
    stored = _validate_existing_receipt(conn, receipt, normalized)
    return _result(
        stored,
        idempotent=True,
        runtime_role_separation_verified=False,
    )


def apply_projection(
    conn: Any,
    plan: Mapping[str, Any],
    *,
    fault_after_label_insert: Optional[int] = None,
) -> Dict[str, Any]:
    """Atomically apply one exact plan; ``fault_after`` is a rollback test seam."""

    _require_supported_connection(conn)
    _require_idle_connection(conn)
    checked = _validate_plan(plan)
    if fault_after_label_insert not in (None, 1, 2):
        raise ValueError("fault_after_label_insert must be 1, 2, or None")
    _begin_transaction(conn, read_only=False)
    try:
        _ensure_schema(conn)
        runtime_role_separation_verified = False
        if not _is_sqlite(conn):
            runtime_security = _attest_postgres_runtime_role_security(conn)
            runtime_role_separation_verified = bool(runtime_security["runtime_role_separation_verified"])
        _acquire_locks(conn, checked)
        existing = _load_receipt(conn, checked["projection_key"], for_update=True)
        if existing is not None:
            stored = _validate_existing_receipt(conn, existing, checked["record"])
            if stored["plan_sha256"] != checked["plan_sha256"]:
                raise ProjectionBlockedError(
                    "idempotent_plan_sha_mismatch",
                    {
                        "stored_plan_sha256": stored["plan_sha256"],
                        "requested_plan_sha256": checked["plan_sha256"],
                    },
                )
            conn.commit()
            return _result(
                stored,
                idempotent=True,
                runtime_role_separation_verified=runtime_role_separation_verified,
            )
        fresh = _build_new_plan(conn, checked["record"])
        if fresh != checked:
            raise ProjectionBlockedError(
                "prepared_plan_before_image_drift",
                {
                    "prepared_plan_sha256": checked["plan_sha256"],
                    "current_plan_sha256": fresh["plan_sha256"],
                },
            )
        receipt = _insert_receipt(conn, checked)
        _insert_labels(conn, checked, fault_after=fault_after_label_insert)
        _insert_sync(conn, checked)
        _postcheck(conn, checked, receipt)
        conn.commit()
        return _result(
            checked,
            idempotent=False,
            runtime_role_separation_verified=runtime_role_separation_verified,
        )
    except Exception:
        conn.rollback()
        raise


def _result(
    plan: Mapping[str, Any],
    *,
    idempotent: bool,
    runtime_role_separation_verified: bool,
) -> Dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "status": PROJECTION_STATUS,
        "idempotent": bool(idempotent),
        "projection_key": plan["projection_key"],
        "plan_sha256": plan["plan_sha256"],
        "market_id": int(plan["record"]["market_id"]),
        "condition_id": plan["record"]["condition_id"],
        "projected_token_count": 2,
        "clickhouse_mutated": False,
        **_immutability_contract(),
        "runtime_role_separation_verified": bool(runtime_role_separation_verified),
    }


def run_projection(
    conn: Any,
    record: Mapping[str, Any],
    *,
    apply: bool = False,
    expected_plan_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Dry-run by default; apply only with the exact prepared plan checksum."""

    prepared = dry_run_projection(conn, record)
    if not apply:
        return prepared
    expected = _clean(expected_plan_sha256).lower()
    if expected != prepared["plan_sha256"]:
        raise ProjectionBlockedError(
            "explicit_plan_sha256_required",
            {
                "expected_plan_sha256": expected,
                "prepared_plan_sha256": prepared["plan_sha256"],
            },
        )
    return apply_projection(conn, prepared["plan"])


def record_projection_failure(
    conn: Any,
    raw_record: Mapping[str, Any],
    error: ProjectionBlockedError,
) -> Dict[str, Any]:
    """Explicitly append one immutable, deduplicated failure observation.

    Failure recording is deliberately separate from dry-run/apply.  Callers
    must opt in after handling the original exception; a failed projection
    transaction never partially commits a failure row.
    """

    _require_supported_connection(conn)
    _require_idle_connection(conn)
    safe_input = _json_safe(raw_record)
    input_sha = _sha256(safe_input)
    market_id: Optional[int] = None
    condition_id: Optional[str] = None
    projection_key: Optional[str] = None
    evidence_origin: Optional[str] = None
    evidence_sha: Optional[str] = None
    try:
        normalized = normalize_projection_record(raw_record)
    except ProjectionBlockedError:
        normalized = None
    if normalized is not None:
        market_id = int(normalized["market_id"])
        condition_id = normalized["condition_id"]
        projection_key = _projection_key(normalized)
        evidence_origin = normalized["evidence_origin"]
        evidence_sha = normalized["evidence_sha256"]
    core = {
        "schema_version": FAILURE_SCHEMA_VERSION,
        "input_sha256": input_sha,
        "projection_key": projection_key,
        "market_id": market_id,
        "condition_id": condition_id,
        "reason": error.reason,
        "details": _json_safe(error.details),
        "evidence_origin": evidence_origin,
        "evidence_sha256": evidence_sha,
        "immutability_contract": _immutability_contract(),
    }
    failure_key = _sha256(core)
    _begin_transaction(conn, read_only=False)
    try:
        _ensure_schema(conn)
        runtime_role_separation_verified = False
        if not _is_sqlite(conn):
            runtime_security = _attest_postgres_runtime_role_security(conn)
            runtime_role_separation_verified = bool(runtime_security["runtime_role_separation_verified"])
        casts = "?" if _is_sqlite(conn) else "?::jsonb"
        conn.execute(
            f"""
            INSERT INTO {FAILURE_TABLE} ({", ".join(FAILURE_COLUMNS)})
            VALUES (?, ?, ?, ?, ?, ?, {casts}, ?, ?)
            ON CONFLICT DO NOTHING
            """,
            (
                failure_key,
                input_sha,
                projection_key,
                market_id,
                condition_id,
                error.reason,
                _canonical_json(error.details),
                evidence_origin,
                evidence_sha,
            ),
        )
        row = conn.execute(
            f"SELECT {', '.join(FAILURE_COLUMNS)} FROM {FAILURE_TABLE} WHERE failure_key=?",
            (failure_key,),
        ).fetchone()
        if row is None:
            raise ProjectionBlockedError("failure_receipt_insert_failed")
        stored = _row_dict(row, FAILURE_COLUMNS)
        stored["details_json"] = _decoded_json(stored["details_json"], field="details_json")
        expected = {
            "failure_key": failure_key,
            "input_sha256": input_sha,
            "projection_key": projection_key,
            "market_id": market_id,
            "condition_id": condition_id,
            "reason": error.reason,
            "details_json": _json_safe(error.details),
            "evidence_origin": evidence_origin,
            "evidence_sha256": evidence_sha,
        }
        if stored != expected:
            raise ProjectionBlockedError("immutable_failure_receipt_conflict")
        conn.commit()
        return {
            **expected,
            **_immutability_contract(),
            "runtime_role_separation_verified": runtime_role_separation_verified,
        }
    except Exception:
        conn.rollback()
        raise


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_db_cli_args(parser)
    parser.set_defaults(backend="postgres")
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--projection-json", help="Path to one explicit projection record.")
    operation.add_argument(
        "--bootstrap-schema",
        action="store_true",
        help="Admin-only: create and attest the projection ledger schema.",
    )
    parser.add_argument("--apply", action="store_true", help="Apply the checksum-pinned projection.")
    parser.add_argument(
        "--expected-plan-sha256",
        help="Required with --apply; must equal the freshly prepared plan SHA256.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    from runtime.environment import load_environment
    load_environment()
    args = parse_args(argv)
    configure_db_from_args(args)
    conn = get_connection(args.sqlite_path, backend=args.backend)
    try:
        if not _is_sqlite(conn):
            # Finish only get_connection's setup transaction so this command
            # can prove ownership of the SERIALIZABLE apply transaction.
            conn.commit()
            _require_idle_connection(conn)
        if args.bootstrap_schema:
            if args.apply or args.expected_plan_sha256:
                raise ProjectionBlockedError(
                    "bootstrap_projection_options_conflict",
                    {
                        "apply": bool(args.apply),
                        "expected_plan_sha256": args.expected_plan_sha256,
                    },
                )
            result = bootstrap_projection_schema(conn)
            result["db_target"] = describe_db_target()
            print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
            return 0
        path = Path(args.projection_json).expanduser()
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ProjectionBlockedError("source_record_not_object", {"path": str(path)})
        result = run_projection(
            conn,
            raw,
            apply=bool(args.apply),
            expected_plan_sha256=args.expected_plan_sha256,
        )
        result["db_target"] = describe_db_target()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
