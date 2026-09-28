"""Fail-closed serving projection for canonical outcome semantics.

One PostgreSQL batch proves the immutable projection receipt/sync state against
the current market-token registry.  Internal YES/NO slots remain diagnostic;
only the exact source label is displayable, and directional consumers require
an explicit validated directional capability.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional

from market import market_token_source_label_projection as projection_ledger


SEMANTIC_MODES = {"yes_no_labels", "up_down_labels", "source_first_second"}
LOGICAL_SLOTS = {("YES", 0), ("NO", 1)}
PROJECTED_STATUS = "PROJECTED"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IdentityMode = Literal["raw", "aggregate", "probe"]
OUTCOMEFILLED_RECEIPT_SCHEMA = "orderfilled-outcome-semantic-receipt-v1"
OUTCOMEFILLED_PUBLIC_PROOF_SCHEMA = "orderfilled-outcome-semantic-public-proof-v1"
_MARKET_IDENTITY_FIELDS = ("market_id", "marketId", "localMarketId")
_TOKEN_IDENTITY_FIELDS = ("token_id", "tokenId")

_YES_NO_PRICE_FIELDS = {
    "latestPrice",
    "latest_price",
    "latestYesPrice",
    "latest_yes_price",
    "latestNoPrice",
    "latest_no_price",
    "yesPrice",
    "yes_price",
    "noPrice",
    "no_price",
    "price24hAgo",
    "price_24h_ago",
    "change1h",
    "change_1h",
    "change24h",
    "change_24h",
    "probability",
}
_DIRECTIONAL_FIELDS = {
    "direction",
    "dominantDirection",
    "dominant_direction",
    "bias",
    "bullishNotional",
    "bullish_notional",
    "bearishNotional",
    "bearish_notional",
    "netDirectionalNotional",
    "net_directional_notional",
    "entryYesPrice",
    "entry_yes_price",
    "yesPriceAfter1m",
    "yes_price_after_1m",
    "yesPriceAfter5m",
    "yes_price_after_5m",
    "yesPriceAfter15m",
    "yes_price_after_15m",
    "upPrice",
    "up_price",
    "downPrice",
    "down_price",
    "latestUpPrice",
    "latest_up_price",
    "latestDownPrice",
    "latest_down_price",
}
_SEMANTIC_ATTESTATION_FIELDS = {
    "outcomeSemanticsStatus",
    "outcomeSemanticsValid",
    "outcomeSemanticsIdentityMode",
    "outcomeSemanticsCapabilities",
    "supportsYesNoWording",
    "supportsDirectionalSemantics",
    "semanticMode",
    "outcome_semantics_status",
    "outcome_semantics_valid",
    "outcome_semantics_identity_mode",
    "outcome_semantics_capabilities",
    "outcome_semantics_capability_reason",
    "supports_yes_no_wording",
    "supports_directional_semantics",
    "semantic_mode",
    "priceProjectionStatus",
    "priceProjectionValid",
    "priceProjectionProof",
    "priceProjectionReason",
    "price_projection_status",
    "price_projection_valid",
    "price_projection_proof",
    "price_projection_reason",
    "outcomeSemanticsCapabilityReason",
    "oracleOutcomeSemanticsStatus",
    "oracleOutcomeSemanticsValid",
    "oracleOutcomeSemanticsReason",
    "oracle_outcome_semantics_status",
    "oracle_outcome_semantics_valid",
    "oracle_outcome_semantics_reason",
}
_PUBLIC_SEMANTIC_FIELDS = (
    _YES_NO_PRICE_FIELDS
    | _DIRECTIONAL_FIELDS
    | _SEMANTIC_ATTESTATION_FIELDS
    | {
        "outcome",
        "logicalOutcome",
        "logical_outcome",
        "outcomeCode",
        "outcome_code",
        "sourceOutcomeLabel",
        "source_outcome_label",
        "outcomePrices",
        "sourcePrices",
        "observedOutcome",
        "observed_outcome",
        "primaryOutcomePrice",
        "primary_outcome_price",
        "tokenPrice",
        "token_price",
        "latestTokenPrice",
        "latest_token_price",
        "settlementOutcome",
        "settlement_outcome",
        "effectiveSettlementOutcome",
        "effective_settlement_outcome",
        "proposedOutcome",
        "proposed_outcome",
        "resolvedOutcome",
        "resolved_outcome",
        "proposedPrice",
        "proposed_price",
        "settledPrice",
        "settled_price",
        "payout",
        "settlementCode",
        "settlement_code",
        "effectiveSettlementCode",
        "effective_settlement_code",
        "settlementRaw",
        "settlement_raw",
        "settlementOutcomeLogicalOutcome",
        "settlement_outcome_logical",
        "effectiveSettlementOutcomeLogicalOutcome",
        "effective_settlement_outcome_logical",
        "proposedOutcomeLogicalOutcome",
        "proposed_outcome_logical",
        "resolvedOutcomeLogicalOutcome",
        "resolved_outcome_logical",
    }
)
_FACT_PRICE_FIELDS = (
    "price",
    "avg_price",
    "latest_token_price",
    "latestTokenPrice",
    "token_price",
    "tokenPrice",
)
_ORACLE_OUTCOME_FIELDS = {
    "settlementOutcome": "settlementOutcomeLogicalOutcome",
    "settlement_outcome": "settlement_outcome_logical",
    "effectiveSettlementOutcome": "effectiveSettlementOutcomeLogicalOutcome",
    "effective_settlement_outcome": "effective_settlement_outcome_logical",
    "proposedOutcome": "proposedOutcomeLogicalOutcome",
    "proposed_outcome": "proposed_outcome_logical",
    "resolvedOutcome": "resolvedOutcomeLogicalOutcome",
    "resolved_outcome": "resolved_outcome_logical",
}
_ORACLE_OUTCOME_ALIAS_GROUPS = (
    ("settlementOutcome", "settlement_outcome"),
    ("effectiveSettlementOutcome", "effective_settlement_outcome"),
    ("proposedOutcome", "proposed_outcome"),
    ("resolvedOutcome", "resolved_outcome"),
)
_ORACLE_RAW_DIRECTIONAL_FIELDS = (
    "proposedPrice",
    "proposed_price",
    "settledPrice",
    "settled_price",
    "payout",
    "settlementCode",
    "settlement_code",
    "effectiveSettlementCode",
    "effective_settlement_code",
    "settlementRaw",
    "settlement_raw",
)
_ORACLE_RAW_ALIAS_GROUPS = (
    ("proposedPrice", "proposed_price"),
    ("settledPrice", "settled_price"),
    ("settlementCode", "settlement_code"),
    ("effectiveSettlementCode", "effective_settlement_code"),
    ("settlementRaw", "settlement_raw"),
)
_AGGREGATE_SEMANTIC_BINDING_FIELDS = (
    "direction",
    "dominantDirection",
    "dominant_direction",
    "trade_count",
    "flow_notional",
    "net_flow_notional",
    "bullish_notional",
    "bearish_notional",
    "opposite_flow_notional",
    "net_direction_strength",
    "entry_yes_price",
    "market_share",
    "window_minutes",
    "baseline_minutes",
    "source_from_block",
    "source_through_block",
)


def bind_trusted_oracle_logical_fields(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """Attach producer-owned logical aliases before public source-label projection.

    Callers must use this only on a freshly normalized database/source record,
    never on a cached public payload.  The sanitizer treats these aliases as
    the raw/projection disambiguator required by reversed ``Yes``/``No`` labels.
    """

    result = dict(payload)
    for outcome_field, logical_field in _ORACLE_OUTCOME_FIELDS.items():
        logical = str(result.get(outcome_field) or "").strip().upper()
        if logical in {"YES", "NO"}:
            result[logical_field] = logical
        else:
            result.pop(logical_field, None)
    return result


def request_local_cache(ctx: Mapping[str, Any], namespace: str) -> Optional[Dict[Any, Any]]:
    """Return a cache whose lifetime is exactly one Flask request.

    Service dependencies live across requests. Storing semantic proof
    (including a transient database failure) on them would leak state.  Background/non-Flask callers get
    no cache, which is safer than inventing an implicit lifetime.
    """

    try:
        from flask import g, has_request_context
    except ImportError:
        return None
    if not has_request_context():
        return None
    root = getattr(g, "_polymonitor_request_local_service_caches", None)
    if not isinstance(root, dict):
        root = {}
        setattr(g, "_polymonitor_request_local_service_caches", root)
    key = (id(ctx), str(namespace))
    cache = root.get(key)
    if not isinstance(cache, dict):
        cache = {}
        root[key] = cache
    return cache


def _market_id(row: Mapping[str, Any]) -> Optional[int]:
    for key in _MARKET_IDENTITY_FIELDS:
        try:
            value = int(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def _normalize_token_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("0x") and re.fullmatch(r"0x[0-9a-f]{64}", text):
        return str(int(text[2:], 16))
    if re.fullmatch(r"[0-9a-f]{64}", text) and any(character in "abcdef" for character in text):
        return str(int(text, 16))
    return text


def _token_id(row: Mapping[str, Any]) -> str:
    for key in _TOKEN_IDENTITY_FIELDS:
        normalized = _normalize_token_id(row.get(key))
        if normalized:
            return normalized
    return ""


def _normalize_fact_identity_aliases(
    row: Mapping[str, Any],
) -> tuple[Dict[str, Any], Optional[str]]:
    normalized = dict(row)
    market_values: set[int] = set()
    market_alias_invalid = False
    for field in _MARKET_IDENTITY_FIELDS:
        if field not in row or row.get(field) in (None, ""):
            continue
        try:
            parsed = int(row.get(field))
        except (TypeError, ValueError):
            market_alias_invalid = True
            continue
        if parsed <= 0:
            market_alias_invalid = True
        else:
            market_values.add(parsed)
    token_values = {
        value
        for field in _TOKEN_IDENTITY_FIELDS
        if field in row and (value := _normalize_token_id(row.get(field)))
    }
    if market_alias_invalid or len(market_values) > 1:
        for field in _MARKET_IDENTITY_FIELDS:
            if field in normalized:
                normalized[field] = None
        return normalized, "market_identity_alias_conflict"
    if len(token_values) > 1:
        for field in _TOKEN_IDENTITY_FIELDS:
            if field in normalized:
                normalized[field] = None
        return normalized, "token_identity_alias_conflict"
    if market_values:
        canonical_market_id = next(iter(market_values))
        for field in _MARKET_IDENTITY_FIELDS:
            if field in normalized:
                normalized[field] = canonical_market_id
    if token_values:
        canonical_token_id = next(iter(token_values))
        for field in _TOKEN_IDENTITY_FIELDS:
            if field in normalized:
                normalized[field] = canonical_token_id
    return normalized, None


def _normalize_fact_price_aliases(
    row: Mapping[str, Any],
) -> tuple[Dict[str, Any], Optional[str]]:
    normalized = dict(row)
    parsed_prices: list[float] = []
    price_alias_invalid = False
    for field in _FACT_PRICE_FIELDS:
        if field not in row or isinstance(row.get(field), Mapping) or row.get(field) in (None, ""):
            continue
        parsed = _probability(row.get(field))
        if parsed is None:
            price_alias_invalid = True
        else:
            parsed_prices.append(parsed)
    distinct_prices = {f"{value:.17g}" for value in parsed_prices}
    if price_alias_invalid or len(distinct_prices) > 1:
        for field in _FACT_PRICE_FIELDS:
            if field in normalized and not isinstance(normalized.get(field), Mapping):
                normalized[field] = None
        return normalized, "fact_price_alias_conflict"
    if parsed_prices:
        canonical_price = f"{parsed_prices[0]:.10f}"
        for field in _FACT_PRICE_FIELDS:
            if field in normalized and not isinstance(normalized.get(field), Mapping):
                normalized[field] = canonical_price
    return normalized, None


def _normalize_explicit_fact_aliases(
    row: Mapping[str, Any],
) -> tuple[Dict[str, Any], Optional[str]]:
    normalized, identity_error = _normalize_fact_identity_aliases(row)
    if identity_error is not None:
        return normalized, identity_error
    return _normalize_fact_price_aliases(normalized)


def _logical_outcome(row: Mapping[str, Any]) -> Optional[str]:
    for key in ("logical_outcome", "logicalOutcome", "outcome"):
        value = str(row.get(key) or "").strip().upper()
        if value in {"YES", "NO"}:
            return value
    try:
        code = int(row.get("outcome_code") or 0)
    except (TypeError, ValueError):
        code = 0
    return "YES" if code == 1 else "NO" if code == 2 else None


def _strict_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    return None


def _normalized_condition(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text and not text.startswith("0x") and len(text) == 64:
        text = f"0x{text}"
    return text


def _failed_semantics(status: str, *, known_source_first: bool = False) -> Dict[str, Any]:
    return {
        "status": status,
        "valid": False,
        "knownSourceFirst": known_source_first,
        "semanticMode": "source_first_second" if known_source_first else None,
        "supportsYesNoWording": False,
        "supportsDirectionalSemantics": False,
        "tokens": {},
        "logicalSlots": {},
    }


def _projection_query(market_count: int) -> str:
    placeholders = ", ".join("?" for _ in range(market_count))
    return f"""
        SELECT
            m.id AS market_id,
            m.condition_id AS market_condition_id,
            m.yes_token_id AS market_yes_token_id,
            m.no_token_id AS market_no_token_id,
            mt.token_id AS registry_token_id,
            mt.market_id AS registry_market_id,
            mt.condition_id AS registry_condition_id,
            mt.outcome AS registry_logical_outcome,
            mt.outcome_index AS registry_logical_outcome_index,
            l.token_id AS label_token_id,
            l.market_id AS label_market_id,
            l.condition_id AS label_condition_id,
            l.source_index AS label_source_index,
            l.source_label AS label_source_label,
            l.logical_outcome AS label_logical_outcome,
            l.logical_outcome_index AS label_logical_outcome_index,
            l.semantic_mode AS label_semantic_mode,
            l.supports_yes_no_wording AS label_supports_yes_no_wording,
            l.supports_directional_semantics AS label_supports_directional_semantics,
            l.evidence_origin AS label_evidence_origin,
            l.evidence_sha256 AS label_evidence_sha256,
            l.plan_sha256 AS label_plan_sha256,
            s.projection_key AS sync_projection_key,
            s.market_id AS sync_market_id,
            s.condition_id AS sync_condition_id,
            s.plan_sha256 AS sync_plan_sha256,
            s.status AS sync_status,
            s.projected_token_count AS sync_projected_token_count,
            r.projection_key AS receipt_projection_key,
            r.plan_sha256 AS receipt_plan_sha256,
            r.record_sha256 AS receipt_record_sha256,
            r.market_id AS receipt_market_id,
            r.condition_id AS receipt_condition_id,
            r.evidence_origin AS receipt_evidence_origin,
            r.evidence_sha256 AS receipt_evidence_sha256,
            r.record_json AS receipt_record_json,
            r.plan_json AS receipt_plan_json,
            r.before_images_json AS receipt_before_images_json,
            r.status AS receipt_status,
            CASE WHEN residual.condition_id IS NULL THEN FALSE ELSE TRUE END AS known_source_first
        FROM core.markets m
        LEFT JOIN core.market_tokens mt
          ON mt.market_id = m.id
        LEFT JOIN core.market_token_source_labels l
          ON l.market_id = m.id
         AND l.token_id = mt.token_id
        LEFT JOIN ops.market_token_source_label_projection_sync_state_v1 s
          ON s.market_id = m.id
        LEFT JOIN ops.market_token_source_label_projection_receipts_v1 r
          ON r.market_id = m.id
         AND r.projection_key = s.projection_key
         AND r.plan_sha256 = s.plan_sha256
        LEFT JOIN ops.market_token_semantics_residuals_v1 residual
          ON residual.condition_id = m.condition_id
         AND residual.reason IN (
             'authoritative_source_slot_zero_one',
             'logical_mapping_rule:source_first_second'
         )
         AND residual.resolved_at IS NOT NULL
        WHERE m.id IN ({placeholders})
        ORDER BY m.id, mt.outcome_index, mt.token_id
    """


def _json_object(value: Any) -> Optional[Dict[str, Any]]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        return dict(parsed) if isinstance(parsed, Mapping) else None
    return None


def _common_value(rows: List[Mapping[str, Any]], field: str) -> tuple[bool, Any]:
    if not rows:
        return False, None
    value = rows[0].get(field)
    return (all(row.get(field) == value for row in rows), value)


def _validate_content_bound_ledger(
    rows: List[Mapping[str, Any]],
    *,
    market_id: int,
    condition_id: str,
) -> Optional[Dict[str, Any]]:
    """Re-prove one immutable receipt using only pure producer functions."""

    receipt_fields = (
        "receipt_projection_key",
        "receipt_plan_sha256",
        "receipt_record_sha256",
        "receipt_market_id",
        "receipt_condition_id",
        "receipt_evidence_origin",
        "receipt_evidence_sha256",
        "receipt_record_json",
        "receipt_plan_json",
        "receipt_before_images_json",
        "receipt_status",
    )
    common: Dict[str, Any] = {}
    for field in receipt_fields:
        consistent, value = _common_value(rows, field)
        if not consistent:
            return None
        common[field] = value

    record_json = _json_object(common["receipt_record_json"])
    plan_json = _json_object(common["receipt_plan_json"])
    before_images_json = _json_object(common["receipt_before_images_json"])
    if record_json is None or plan_json is None or before_images_json is None:
        return None

    try:
        normalized_record = projection_ledger.normalize_projection_record(record_json)
        validated_plan = projection_ledger._validate_plan(plan_json)
        record_sha256 = projection_ledger._sha256(normalized_record)
        projection_key = projection_ledger._projection_key(normalized_record)
        expected_labels = projection_ledger._expected_label_rows(
            normalized_record,
            validated_plan["plan_sha256"],
        )
    except (KeyError, TypeError, ValueError, projection_ledger.ProjectionBlockedError):
        return None

    try:
        receipt_market_id = int(common["receipt_market_id"] or 0)
    except (TypeError, ValueError):
        return None
    receipt_plan_sha = str(common["receipt_plan_sha256"] or "").strip().lower()
    receipt_record_sha = str(common["receipt_record_sha256"] or "").strip().lower()
    receipt_projection_key = str(common["receipt_projection_key"] or "").strip().lower()
    receipt_evidence_origin = str(common["receipt_evidence_origin"] or "").strip()
    receipt_evidence_sha = str(common["receipt_evidence_sha256"] or "").strip().lower()
    record_condition = _normalized_condition(normalized_record.get("condition_id"))
    plan_record = validated_plan.get("record")
    if (
        record_json != normalized_record
        or plan_json != validated_plan
        or plan_record != normalized_record
        or before_images_json != validated_plan.get("before_images")
        or int(normalized_record.get("market_id") or 0) != market_id
        or record_condition != condition_id
        or receipt_market_id != market_id
        or _normalized_condition(common["receipt_condition_id"]) != condition_id
        or common["receipt_status"] != PROJECTED_STATUS
        or receipt_record_sha != record_sha256
        or receipt_record_sha != str(validated_plan.get("record_sha256") or "").lower()
        or receipt_plan_sha != str(validated_plan.get("plan_sha256") or "").lower()
        or receipt_projection_key != projection_key
        or receipt_projection_key != str(validated_plan.get("projection_key") or "").lower()
        or receipt_evidence_origin != str(normalized_record.get("evidence_origin") or "")
        or receipt_evidence_sha != str(normalized_record.get("evidence_sha256") or "").lower()
        or not _SHA256_RE.fullmatch(receipt_record_sha)
        or not _SHA256_RE.fullmatch(receipt_plan_sha)
        or not _SHA256_RE.fullmatch(receipt_evidence_sha)
        or not _SHA256_RE.fullmatch(receipt_projection_key)
    ):
        return None

    expected_by_token = {str(item["token_id"]): item for item in expected_labels}
    actual_by_token: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        token_id = str(row.get("label_token_id") or "").strip()
        yes_no = _strict_bool(row.get("label_supports_yes_no_wording"))
        directional = _strict_bool(row.get("label_supports_directional_semantics"))
        try:
            actual = {
                "token_id": token_id,
                "market_id": int(row.get("label_market_id") or 0),
                "condition_id": _normalized_condition(row.get("label_condition_id")),
                "source_index": int(row.get("label_source_index")),
                "source_label": str(row.get("label_source_label") or "").strip(),
                "logical_outcome": str(row.get("label_logical_outcome") or "").strip().upper(),
                "logical_outcome_index": int(row.get("label_logical_outcome_index")),
                "semantic_mode": str(row.get("label_semantic_mode") or "").strip().lower(),
                "supports_yes_no_wording": yes_no,
                "supports_directional_semantics": directional,
                "evidence_origin": str(row.get("label_evidence_origin") or "").strip(),
                "evidence_sha256": str(row.get("label_evidence_sha256") or "").strip().lower(),
                "plan_sha256": str(row.get("label_plan_sha256") or "").strip().lower(),
            }
        except (TypeError, ValueError):
            return None
        if yes_no is None or directional is None or token_id in actual_by_token:
            return None
        actual_by_token[token_id] = actual
    if actual_by_token != expected_by_token:
        return None

    return {
        "record": normalized_record,
        "plan": validated_plan,
        "projectionKey": projection_key,
        "recordSha256": record_sha256,
        "planSha256": receipt_plan_sha,
        "evidenceOrigin": receipt_evidence_origin,
        "evidenceSha256": receipt_evidence_sha,
    }


def _validate_market_rows(rows: List[Mapping[str, Any]]) -> Dict[str, Any]:
    known_source_first = any(bool(row.get("known_source_first")) for row in rows)
    registry_rows = [row for row in rows if row.get("registry_token_id") not in (None, "")]
    label_rows = [row for row in registry_rows if row.get("label_token_id") not in (None, "")]
    if len(label_rows) == 0:
        return _failed_semantics(
            "source_first_projection_missing" if known_source_first else "projection_missing",
            known_source_first=known_source_first,
        )
    if len(rows) != 2 or len(registry_rows) != 2 or len(label_rows) != 2:
        return _failed_semantics("projection_conflict", known_source_first=known_source_first)

    try:
        market_id = int(rows[0].get("market_id") or 0)
    except (TypeError, ValueError):
        return _failed_semantics("projection_invalid", known_source_first=known_source_first)
    condition_id = _normalized_condition(rows[0].get("market_condition_id"))
    if market_id <= 0 or not re.fullmatch(r"0x[0-9a-f]{64}", condition_id):
        return _failed_semantics("projection_invalid", known_source_first=known_source_first)

    market_yes_token = str(rows[0].get("market_yes_token_id") or "").strip()
    market_no_token = str(rows[0].get("market_no_token_id") or "").strip()
    if (
        not market_yes_token
        or not market_no_token
        or market_yes_token == market_no_token
        or any(str(row.get("market_yes_token_id") or "").strip() != market_yes_token for row in rows)
        or any(str(row.get("market_no_token_id") or "").strip() != market_no_token for row in rows)
    ):
        return _failed_semantics("canonical_market_slot_invalid", known_source_first=known_source_first)

    ledger = _validate_content_bound_ledger(rows, market_id=market_id, condition_id=condition_id)
    if ledger is None:
        return _failed_semantics("ledger_content_invalid", known_source_first=known_source_first)

    tokens: Dict[str, Dict[str, Any]] = {}
    logical_slots: Dict[str, Dict[str, Any]] = {}
    semantic_modes: set[str] = set()
    capability_pairs: set[tuple[bool, bool]] = set()
    plan_hashes: set[str] = set()
    evidence_hashes: set[str] = set()
    source_indices: set[int] = set()
    registry_slots: set[tuple[str, int]] = set()
    projection_keys: set[str] = set()
    for row in rows:
        try:
            registry_market_id = int(row.get("registry_market_id") or 0)
            label_market_id = int(row.get("label_market_id") or 0)
            sync_market_id = int(row.get("sync_market_id") or 0)
            receipt_market_id = int(row.get("receipt_market_id") or 0)
            registry_index = int(row.get("registry_logical_outcome_index"))
            label_index = int(row.get("label_logical_outcome_index"))
            source_index = int(row.get("label_source_index"))
            projected_count = int(row.get("sync_projected_token_count"))
        except (TypeError, ValueError):
            return _failed_semantics("projection_invalid", known_source_first=known_source_first)

        token_id = str(row.get("registry_token_id") or "").strip().lower()
        label_token_id = str(row.get("label_token_id") or "").strip().lower()
        registry_outcome = str(row.get("registry_logical_outcome") or "").strip().upper()
        label_outcome = str(row.get("label_logical_outcome") or "").strip().upper()
        source_label = str(row.get("label_source_label") or "").strip()
        semantic_mode = str(row.get("label_semantic_mode") or "").strip().lower()
        yes_no = _strict_bool(row.get("label_supports_yes_no_wording"))
        directional = _strict_bool(row.get("label_supports_directional_semantics"))
        plan_sha = str(row.get("label_plan_sha256") or "").strip().lower()
        evidence_sha = str(row.get("label_evidence_sha256") or "").strip().lower()
        sync_plan_sha = str(row.get("sync_plan_sha256") or "").strip().lower()
        receipt_plan_sha = str(row.get("receipt_plan_sha256") or "").strip().lower()
        sync_projection_key = str(row.get("sync_projection_key") or "").strip()
        receipt_projection_key = str(row.get("receipt_projection_key") or "").strip()

        if (
            not token_id
            or label_token_id != token_id
            or registry_market_id != market_id
            or label_market_id != market_id
            or sync_market_id != market_id
            or receipt_market_id != market_id
            or registry_outcome != label_outcome
            or registry_index != label_index
            or (registry_outcome, registry_index) not in LOGICAL_SLOTS
            or not source_label
            or semantic_mode not in SEMANTIC_MODES
            or yes_no is None
            or directional is None
            or projected_count != 2
            or str(row.get("sync_status") or "").upper() != PROJECTED_STATUS
            or str(row.get("receipt_status") or "").upper() != PROJECTED_STATUS
            or not sync_projection_key
            or sync_projection_key != receipt_projection_key
            or not _SHA256_RE.fullmatch(plan_sha)
            or plan_sha != sync_plan_sha
            or plan_sha != receipt_plan_sha
            or not _SHA256_RE.fullmatch(evidence_sha)
            or _normalized_condition(row.get("registry_condition_id")) != condition_id
            or _normalized_condition(row.get("label_condition_id")) != condition_id
            or _normalized_condition(row.get("sync_condition_id")) != condition_id
            or _normalized_condition(row.get("receipt_condition_id")) != condition_id
            or (registry_index == 0 and token_id != market_yes_token)
            or (registry_index == 1 and token_id != market_no_token)
        ):
            return _failed_semantics("registry_projection_drift", known_source_first=known_source_first)

        tokens[token_id] = {
            "tokenId": token_id,
            "sourceLabel": source_label,
            "sourceIndex": source_index,
            "logicalOutcome": label_outcome,
            "logicalOutcomeIndex": label_index,
        }
        logical_slots[label_outcome] = tokens[token_id]
        semantic_modes.add(semantic_mode)
        capability_pairs.add((yes_no, directional))
        plan_hashes.add(plan_sha)
        evidence_hashes.add(evidence_sha)
        source_indices.add(source_index)
        registry_slots.add((registry_outcome, registry_index))
        projection_keys.add(sync_projection_key)

    if (
        len(tokens) != 2
        or len(logical_slots) != 2
        or source_indices != {0, 1}
        or registry_slots != LOGICAL_SLOTS
        or len(semantic_modes) != 1
        or len(capability_pairs) != 1
        or len(plan_hashes) != 1
        or len(evidence_hashes) != 1
        or len(projection_keys) != 1
        or len({slot["sourceLabel"].casefold() for slot in tokens.values()}) != 2
    ):
        return _failed_semantics("projection_conflict", known_source_first=known_source_first)

    semantic_mode = next(iter(semantic_modes))
    supports_yes_no, supports_directional = next(iter(capability_pairs))
    label_by_logical = {key: value["sourceLabel"].casefold() for key, value in logical_slots.items()}
    expected_yes_no = semantic_mode == "yes_no_labels" and label_by_logical == {"YES": "yes", "NO": "no"}
    expected_directional = semantic_mode == "up_down_labels" and label_by_logical == {"YES": "up", "NO": "down"}
    if supports_yes_no != expected_yes_no or supports_directional != expected_directional:
        return _failed_semantics("capability_claim_invalid", known_source_first=known_source_first)
    if known_source_first and semantic_mode != "source_first_second":
        return _failed_semantics("residual_projection_conflict", known_source_first=True)

    return {
        "status": "projected",
        "valid": True,
        "knownSourceFirst": known_source_first,
        "marketId": market_id,
        "conditionId": condition_id,
        "semanticMode": semantic_mode,
        "supportsYesNoWording": supports_yes_no,
        "supportsDirectionalSemantics": supports_directional,
        "projectionKey": ledger["projectionKey"],
        "recordSha256": ledger["recordSha256"],
        "planSha256": ledger["planSha256"],
        "evidenceOrigin": ledger["evidenceOrigin"],
        "evidenceSha256": ledger["evidenceSha256"],
        "tokens": tokens,
        "logicalSlots": logical_slots,
    }


def load_market_outcome_semantics(ctx: Mapping[str, Any], market_ids: Iterable[Any]) -> Dict[int, Dict[str, Any]]:
    requested: List[int] = []
    for value in market_ids:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in requested:
            requested.append(parsed)
    requested.sort()
    if not requested:
        return {}

    request_cache = request_local_cache(ctx, "outcome-semantics")
    cache: Dict[int, Dict[str, Any]] = request_cache if request_cache is not None else {}
    missing = [market_id for market_id in requested if market_id not in cache]
    if not missing:
        return {market_id: cache[market_id] for market_id in requested}

    query_all = ctx.get("query_all")
    get_backend = ctx.get("get_backend")
    try:
        backend = str(get_backend() if callable(get_backend) else "").strip().lower()
    except Exception:
        backend = ""
    if backend not in {"postgres", "postgresql"} or not callable(query_all):
        unavailable = {market_id: _failed_semantics("semantics_database_unavailable") for market_id in missing}
        if request_cache is not None:
            cache.update(unavailable)
        return {market_id: cache.get(market_id) or unavailable[market_id] for market_id in requested}

    try:
        rows = query_all(_projection_query(len(missing)), tuple(missing))
    except Exception as exc:
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.warning("Outcome semantics projection batch query failed: %s", exc)
        failed = {market_id: _failed_semantics("semantics_query_failed") for market_id in missing}
        if request_cache is not None:
            cache.update(failed)
        return {market_id: cache.get(market_id) or failed[market_id] for market_id in requested}

    grouped: Dict[int, List[Mapping[str, Any]]] = {market_id: [] for market_id in missing}
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        try:
            market_id = int(row.get("market_id") or 0)
        except (TypeError, ValueError):
            continue
        if market_id in grouped:
            grouped[market_id].append(row)
    cache.update(
        {
            market_id: _validate_market_rows(market_rows)
            if market_rows
            else _failed_semantics("market_or_projection_missing")
            for market_id, market_rows in grouped.items()
        }
    )
    return {market_id: cache[market_id] for market_id in requested}


def annotate_trade_rows(
    ctx: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
    *,
    identity_mode: IdentityMode = "raw",
) -> List[Dict[str, Any]]:
    """Attach freshly verified labels under an explicit identity contract.

    ``raw`` requires the exact token id. ``aggregate`` requires a logical slot
    (or one exact source label). ``probe`` checks only market-level capability
    and deliberately projects no outcome identity.
    """

    if identity_mode not in {"raw", "aggregate", "probe"}:
        raise ValueError(f"unsupported outcome semantics identity mode: {identity_mode}")
    copied = [dict(row) for row in rows]
    semantics_by_market = load_market_outcome_semantics(
        ctx,
        [market_id for row in copied if (market_id := _market_id(row)) is not None],
    )
    annotated: List[Dict[str, Any]] = []
    for row in copied:
        market_id = _market_id(row)
        semantics = semantics_by_market.get(market_id or 0) or _failed_semantics("market_identity_missing")
        logical_outcome = _logical_outcome(row)
        token_id = _token_id(row)
        slot = None
        if identity_mode == "raw":
            if not semantics.get("valid"):
                pass
            elif not token_id:
                semantics = _failed_semantics("trade_token_identity_missing")
            else:
                slot = semantics.get("tokens", {}).get(token_id)
                if slot is None:
                    semantics = _failed_semantics("trade_token_projection_mismatch")
                elif logical_outcome and logical_outcome != slot.get("logicalOutcome"):
                    semantics = _failed_semantics("trade_token_logical_mismatch")
                    slot = None
        elif identity_mode == "aggregate" and semantics.get("valid"):
            if logical_outcome:
                slot = semantics.get("logicalSlots", {}).get(logical_outcome)
            if slot is None:
                outcome_text = str(row.get("outcome") or row.get("sourceOutcomeLabel") or "").strip().casefold()
                source_matches = [
                    candidate
                    for candidate in semantics.get("logicalSlots", {}).values()
                    if outcome_text and str(candidate.get("sourceLabel") or "").strip().casefold() == outcome_text
                ]
                if len(source_matches) == 1:
                    slot = source_matches[0]
            if slot is None:
                semantics = _failed_semantics("aggregate_logical_slot_missing")
        elif identity_mode == "probe":
            logical_outcome = None
        if slot is not None:
            logical_outcome = slot.get("logicalOutcome")
        source_label = slot.get("sourceLabel") if semantics.get("valid") and slot else None
        capabilities = {
            "supportsYesNoWording": bool(semantics.get("valid") and semantics.get("supportsYesNoWording")),
            "supportsDirectionalSemantics": bool(
                semantics.get("valid") and semantics.get("supportsDirectionalSemantics")
            ),
        }
        row.update(
            {
                "outcome": source_label,
                "logicalOutcome": logical_outcome,
                "sourceOutcomeLabel": source_label,
                "semanticMode": semantics.get("semanticMode"),
                "outcomeSemanticsStatus": semantics.get("status"),
                "outcomeSemanticsValid": bool(semantics.get("valid")),
                "outcomeSemanticsIdentityMode": identity_mode,
                "outcomeSemanticsCapabilities": capabilities,
                "supportsYesNoWording": capabilities["supportsYesNoWording"],
                "supportsDirectionalSemantics": capabilities["supportsDirectionalSemantics"],
                "logical_outcome": logical_outcome,
                "source_outcome_label": source_label,
                "semantic_mode": semantics.get("semanticMode"),
                "outcome_semantics_status": semantics.get("status"),
                "outcome_semantics_valid": bool(semantics.get("valid")),
                "outcome_semantics_identity_mode": identity_mode,
                "supports_yes_no_wording": capabilities["supportsYesNoWording"],
                "supports_directional_semantics": capabilities["supportsDirectionalSemantics"],
            }
        )
        annotated.append(row)
    return annotated


def annotate_raw_trade_rows(ctx: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return annotate_trade_rows(ctx, rows, identity_mode="raw")


def annotate_aggregate_rows(ctx: Mapping[str, Any], rows: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return annotate_trade_rows(ctx, rows, identity_mode="aggregate")


def probe_market_outcome_semantics(ctx: Mapping[str, Any], market_id: Any) -> Dict[str, Any]:
    return annotate_trade_rows(ctx, [{"marketId": market_id}], identity_mode="probe")[0]


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _probability(value: Any) -> Optional[float]:
    try:
        parsed = float(str(value))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed) or parsed < 0.0 or parsed > 1.0:
        return None
    return parsed


def _fact_price(row: Mapping[str, Any]) -> Optional[float]:
    for key in _FACT_PRICE_FIELDS:
        value = _probability(row.get(key))
        if value is not None:
            return value
    return None


def _verified_table_receipt(table: Any) -> bool:
    if not isinstance(table, Mapping):
        return False
    current = table.get("current")
    checks = table.get("checks")
    if not isinstance(current, Mapping) or not isinstance(checks, Mapping):
        return False
    required_checks = (
        "conserve_row_count",
        "conserve_unique_key_count",
        "conserve_duplicate_key_count",
        "conserve_non_outcome_hash_sum",
        "conserve_non_outcome_hash_xor",
        "conserve_numeric",
        "old_outcome_scope_zero",
        "new_outcome_scope_exact",
        "unexpected_outcome_scope_zero",
    )
    try:
        return bool(
            table.get("hard_gate_passed") is True
            and str(table.get("status") or "").upper() == "PASS"
            and all(checks.get(name) is True for name in required_checks)
            and int(current.get("old_outcome_rows") or 0) == 0
            and int(current.get("unexpected_outcome_rows") or 0) == 0
            and int(current.get("duplicate_key_count") or 0) == 0
            and int(current.get("row_count", -1)) == int(current.get("unique_key_count", -2))
        )
    except (TypeError, ValueError):
        return False


def _receipt_source_version_sha256(
    receipt: Mapping[str, Any],
    receipt_sha256: str,
) -> str:
    verification = receipt.get("verification")
    verified_fact = verification.get("orderfilled_fact") if isinstance(verification, Mapping) else None
    return _payload_sha256(
        {
            "schemaVersion": "orderfilled-receipt-source-version-v1",
            "receiptSha256": receipt_sha256,
            "sourceTable": "orderfilled_fact",
            "verifiedTable": verified_fact,
        }
    )


def _validate_orderfilled_mutation_proof(
    proof: Any,
    *,
    market_id: int,
    source_from_block: int,
    source_through_block: int,
    row_sha256: str,
) -> bool:
    """Validate a trusted callback's content-bound aggregate outcome proof.

    The row/cache itself is never consulted for this proof.  The callback must
    bind the immutable VERIFIED receipt, the exact market scope, the coverage
    watermark and the zero-residual assertion into one SHA-256 envelope.
    """

    if not isinstance(proof, Mapping):
        return False
    core = {key: deepcopy(value) for key, value in proof.items() if key != "proofSha256"}
    proof_sha = str(proof.get("proofSha256") or "").strip().lower()
    receipt = proof.get("receipt")
    coverage = proof.get("coverage")
    if (
        proof.get("schemaVersion") != OUTCOMEFILLED_PUBLIC_PROOF_SCHEMA
        or not _SHA256_RE.fullmatch(proof_sha)
        or proof_sha != _payload_sha256(core)
        or not isinstance(receipt, Mapping)
        or not isinstance(coverage, Mapping)
    ):
        return False
    receipt_sha = str(proof.get("receiptSha256") or "").strip().lower()
    if not _SHA256_RE.fullmatch(receipt_sha) or receipt_sha != _payload_sha256(receipt):
        return False
    plan_sha = str(receipt.get("plan_sha256") or "").strip().lower()
    report_sha = str(receipt.get("report_payload_sha256") or "").strip().lower()
    verification = receipt.get("verification")
    if (
        receipt.get("schema_version") != OUTCOMEFILLED_RECEIPT_SCHEMA
        or str(receipt.get("state") or "").upper() != "VERIFIED"
        or str(receipt.get("status") or "").upper() != "PASS"
        or not _SHA256_RE.fullmatch(plan_sha)
        or not _SHA256_RE.fullmatch(report_sha)
        or str(proof.get("planSha256") or "").strip().lower() != plan_sha
        or not isinstance(verification, Mapping)
        or verification.get("completion_contract") != "both_tables_verified_only_outcome_code_changed"
        or not _verified_table_receipt(verification.get("orderfilled_fact"))
        or not _verified_table_receipt(verification.get("address_trade_cashflows"))
    ):
        return False
    runtime = verification.get("runtime_gates")
    if not isinstance(runtime, Mapping):
        return False
    active_mutations = runtime.get("active_mutations")
    if (
        not isinstance(active_mutations, list)
        or active_mutations
        or int(runtime.get("scoped_buffer_rows") or 0) != 0
        or runtime.get("scope_snapshot_consistent") is not True
    ):
        return False
    try:
        market_ids = {int(value) for value in coverage.get("marketIds") or []}
        from_block = int(coverage.get("fromBlock") or 0)
        through_block = int(coverage.get("throughBlock") or 0)
        residual_rows = int(coverage.get("residualRows") or 0)
    except (TypeError, ValueError):
        return False
    source_version_sha = str(coverage.get("sourceVersionSha256") or "").strip().lower()
    if (
        market_id not in market_ids
        or from_block <= 0
        or through_block <= 0
        or source_from_block <= 0
        or source_through_block < source_from_block
        or from_block > source_from_block
        or source_through_block > through_block
        or str(coverage.get("sourceTable") or "").strip() != "orderfilled_fact"
        or source_version_sha != _receipt_source_version_sha256(receipt, receipt_sha)
        or str(coverage.get("rowSha256") or "").strip().lower() != row_sha256
        or str(coverage.get("rebuiltFromReceiptSha256") or "").strip().lower()
        != receipt_sha
        or coverage.get("zeroResidual") is not True
        or residual_rows != 0
    ):
        return False
    return True


def _aggregate_source_bounds(row: Mapping[str, Any]) -> tuple[Optional[int], Optional[int]]:
    through_block: Optional[int] = None
    for key in (
        "source_through_block",
        "sourceThroughBlock",
        "block_number",
        "latest_trade_block",
        "latest_block",
    ):
        try:
            candidate = int(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if candidate > 0:
            through_block = candidate
            break
    if through_block is None:
        return None, None
    from_block = through_block
    for key in ("source_from_block", "sourceFromBlock"):
        try:
            candidate = int(row.get(key) or 0)
        except (TypeError, ValueError):
            continue
        if candidate > 0:
            from_block = candidate
            break
    if from_block > through_block:
        return None, None
    return from_block, through_block


def _aggregate_row_sha256(row: Mapping[str, Any]) -> Optional[str]:
    row, identity_error = _normalize_explicit_fact_aliases(row)
    if identity_error is not None:
        return None
    market_id = _market_id(row)
    logical_outcome = _logical_outcome(row)
    price = _fact_price(row)
    source_from_block, source_through_block = _aggregate_source_bounds(row)
    if (
        market_id is None
        or logical_outcome is None
        or price is None
        or source_from_block is None
        or source_through_block is None
    ):
        return None
    semantic_fields = {
        key: row.get(key)
        for key in _AGGREGATE_SEMANTIC_BINDING_FIELDS
        if key in row
    }
    return _payload_sha256(
        {
            "schemaVersion": "orderfilled-aggregate-price-row-binding-v1",
            "marketId": market_id,
            "logicalOutcome": logical_outcome,
            "price": f"{price:.17g}",
            "sourceFromBlock": source_from_block,
            "sourceThroughBlock": source_through_block,
            "semanticFields": semantic_fields,
        }
    )


def _aggregate_mutation_proof_valid(ctx: Mapping[str, Any], row: Mapping[str, Any]) -> bool:
    row, identity_error = _normalize_explicit_fact_aliases(row)
    if identity_error is not None:
        return False
    market_id = _market_id(row)
    if market_id is None:
        return False
    source_from_block, source_through_block = _aggregate_source_bounds(row)
    row_sha256 = _aggregate_row_sha256(row)
    if source_from_block is None or source_through_block is None or row_sha256 is None:
        return False
    provider = ctx.get("get_orderfilled_outcome_mutation_proof")
    if not callable(provider):
        return False
    try:
        proof = provider(
            market_id=market_id,
            from_block=source_from_block,
            through_block=source_through_block,
            row_sha256=row_sha256,
        )
    except Exception as exc:
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.warning("OrderFilled outcome mutation proof lookup failed: %s", exc)
        return False
    try:
        return _validate_orderfilled_mutation_proof(
            proof,
            market_id=market_id,
            source_from_block=source_from_block,
            source_through_block=source_through_block,
            row_sha256=row_sha256,
        )
    except (TypeError, ValueError, OverflowError):
        return False


def project_aggregate_directional_rows(
    ctx: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Project tokenless directional aggregates only after content-bound proof.

    A valid source-label ledger proves what the two market slots mean; it does
    not prove that every ``outcome_code`` used by a derived ClickHouse window
    was remapped.  This boundary therefore drops the entire aggregate unless a
    trusted callback binds its exact row digest and complete source window to a
    VERIFIED, zero-residual mutation receipt.
    """

    proven: List[Dict[str, Any]] = []
    for row in rows:
        normalized, identity_error = _normalize_explicit_fact_aliases(row)
        if identity_error is None and _aggregate_mutation_proof_valid(ctx, normalized):
            proven.append(normalized)
    annotated = annotate_aggregate_rows(ctx, proven)
    for row in annotated:
        row["outcomeMutationProofValid"] = True
        row["outcomeMutationProofStatus"] = "verified"
    return annotated


def _projection_capabilities(
    semantics: Mapping[str, Any],
    *,
    price_valid: bool,
    price_applicable: bool = True,
) -> Dict[str, Any]:
    semantics_valid = bool(semantics.get("valid"))
    yes_no = bool(semantics_valid and semantics.get("supportsYesNoWording"))
    directional = bool(semantics_valid and semantics.get("supportsDirectionalSemantics"))
    price_reason = None if not price_applicable else (
        None
        if price_valid
        else (
            "price_fact_identity_unproven" if semantics_valid else str(semantics.get("status") or "projection_missing")
        )
    )
    return {
        "supportsYesNoWording": yes_no,
        "supportsDirectionalSemantics": directional,
        "yesNoWordingReason": None
        if yes_no
        else (
            "yes_no_wording_unsupported" if semantics_valid else str(semantics.get("status") or "projection_missing")
        ),
        "directionalSemanticsReason": None
        if directional
        else (
            "directional_semantics_unsupported"
            if semantics_valid
            else str(semantics.get("status") or "projection_missing")
        ),
        "priceProjectionValid": price_valid,
        "priceProjectionApplicable": price_applicable,
        "priceProjectionReason": price_reason,
    }


def _project_annotated_price_fact(
    annotated: Mapping[str, Any],
    semantics: Mapping[str, Any],
    *,
    proof_kind: str,
) -> Dict[str, Any]:
    result = dict(annotated)
    price = _fact_price(result)
    valid = bool(result.get("outcomeSemanticsValid") and price is not None)
    logical = str(result.get("logicalOutcome") or "").strip().upper()
    result.pop("outcomeCode", None)
    result.pop("outcome_code", None)
    if logical not in {"YES", "NO"}:
        valid = False
    capabilities = _projection_capabilities(semantics, price_valid=valid)
    result.update(
        {
            "priceProjectionStatus": "projected" if valid else capabilities["priceProjectionReason"],
            "priceProjectionValid": valid,
            "priceProjectionProof": proof_kind if valid else None,
            "priceProjectionReason": capabilities["priceProjectionReason"],
            "outcomeSemanticsCapabilities": capabilities,
            "outcomeSemanticsCapabilityReason": capabilities["priceProjectionReason"],
        }
    )
    for field in (*_YES_NO_PRICE_FIELDS, *_DIRECTIONAL_FIELDS):
        if field != "price" and field in result:
            result[field] = None
    if not valid or price is None:
        for field in (
            "outcome",
            "logicalOutcome",
            "logical_outcome",
            "sourceOutcomeLabel",
            "source_outcome_label",
            "outcomePrices",
            "sourcePrices",
            "primaryOutcomePrice",
            "observedOutcome",
        ):
            if field in result:
                result[field] = None
        for field in _FACT_PRICE_FIELDS:
            if field in result:
                result[field] = None
        return result

    yes_price = price if logical == "YES" else 1.0 - price
    no_price = 1.0 - yes_price
    logical_slots = semantics.get("logicalSlots") if isinstance(semantics.get("logicalSlots"), Mapping) else {}
    outcome_prices: List[Dict[str, Any]] = []
    for slot_name, slot_price in (("YES", yes_price), ("NO", no_price)):
        slot = logical_slots.get(slot_name) if isinstance(logical_slots, Mapping) else None
        if not isinstance(slot, Mapping):
            continue
        outcome_prices.append(
            {
                "tokenId": slot.get("tokenId"),
                "logicalOutcome": slot_name,
                "sourceLabel": slot.get("sourceLabel"),
                "sourceIndex": slot.get("sourceIndex"),
                "price": f"{slot_price:.10f}",
            }
        )
    outcome_prices.sort(key=lambda item: int(item.get("sourceIndex") or 0))
    primary_outcome_price = next(
        (
            item["price"]
            for item in outcome_prices
            if int(item.get("sourceIndex") or 0) == 0
        ),
        None,
    )
    result.update(
        {
            "tokenPrice": f"{price:.10f}",
            "observedOutcome": result.get("sourceOutcomeLabel"),
            "outcomePrices": outcome_prices,
            "primaryOutcomePrice": primary_outcome_price,
        }
    )
    if semantics.get("supportsYesNoWording"):
        result.update(
            {
                "yesPrice": f"{yes_price:.10f}",
                "noPrice": f"{no_price:.10f}",
                "latestPrice": f"{yes_price:.10f}",
                "latestYesPrice": f"{yes_price:.10f}",
                "latestNoPrice": f"{no_price:.10f}",
            }
        )
    elif semantics.get("supportsDirectionalSemantics"):
        result.update(
            {
                "upPrice": f"{yes_price:.10f}",
                "downPrice": f"{no_price:.10f}",
                "latestUpPrice": f"{yes_price:.10f}",
                "latestDownPrice": f"{no_price:.10f}",
            }
        )
    else:
        result["sourcePrices"] = outcome_prices
    return result


def project_token_price_fact(ctx: Mapping[str, Any], row: Mapping[str, Any]) -> Dict[str, Any]:
    """Project one raw price fact using its exact canonical token identity."""

    normalized, identity_error = _normalize_explicit_fact_aliases(row)
    if identity_error is not None:
        normalized.update(
            {
                "outcome": None,
                "logicalOutcome": None,
                "logical_outcome": None,
                "sourceOutcomeLabel": None,
                "source_outcome_label": None,
                "outcomeSemanticsValid": False,
                "outcomeSemanticsStatus": identity_error,
            }
        )
        return _project_annotated_price_fact(
            normalized,
            _failed_semantics(identity_error),
            proof_kind="canonical_token",
        )
    annotated = annotate_raw_trade_rows(ctx, [normalized])[0]
    market_id = _market_id(annotated)
    semantics = load_market_outcome_semantics(ctx, [market_id]).get(market_id or 0) or _failed_semantics(
        "market_identity_missing"
    )
    return _project_annotated_price_fact(annotated, semantics, proof_kind="canonical_token")


def project_market_pair(ctx: Mapping[str, Any], row: Mapping[str, Any]) -> Dict[str, Any]:
    """Project an aggregate market price pair under an explicit proof mode.

    Exact canonical token identity wins.  A tokenless aggregate is accepted
    only when a trusted context callback returns a content-bound VERIFIED
    OrderFilled mutation receipt with a covering watermark and zero residual.
    """

    normalized, identity_error = _normalize_explicit_fact_aliases(row)
    if identity_error is not None:
        normalized.update(
            {
                "outcome": None,
                "logicalOutcome": None,
                "logical_outcome": None,
                "sourceOutcomeLabel": None,
                "source_outcome_label": None,
                "outcomeSemanticsValid": False,
                "outcomeSemanticsStatus": identity_error,
            }
        )
        return _project_annotated_price_fact(
            normalized,
            _failed_semantics(identity_error),
            proof_kind="orderfilled_mutation_receipt",
        )
    market_id = _market_id(normalized)
    if _token_id(normalized):
        return project_token_price_fact(ctx, normalized)
    if not _aggregate_mutation_proof_valid(ctx, normalized):
        failed = annotate_trade_rows(ctx, [normalized], identity_mode="probe")[0]
        failed.update(
            {
                "outcome": None,
                "logicalOutcome": None,
                "sourceOutcomeLabel": None,
                "outcomeSemanticsValid": False,
                "outcomeSemanticsStatus": "aggregate_mutation_proof_missing",
            }
        )
        semantics = load_market_outcome_semantics(ctx, [market_id]).get(market_id or 0) or _failed_semantics(
            "market_identity_missing"
        )
        return _project_annotated_price_fact(failed, semantics, proof_kind="orderfilled_mutation_receipt")
    annotated = annotate_aggregate_rows(ctx, [normalized])[0]
    semantics = load_market_outcome_semantics(ctx, [market_id]).get(market_id or 0) or _failed_semantics(
        "market_identity_missing"
    )
    return _project_annotated_price_fact(
        annotated,
        semantics,
        proof_kind="orderfilled_mutation_receipt",
    )


def project_token_price_series(
    ctx: Mapping[str, Any],
    rows: Iterable[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Project raw series points in one semantics batch; invalid points remain fail-closed."""

    copied = [_normalize_explicit_fact_aliases(row) for row in rows]
    valid_positions = [index for index, (_row, error) in enumerate(copied) if error is None]
    annotated_valid = annotate_raw_trade_rows(ctx, [copied[index][0] for index in valid_positions])
    annotated_by_position = dict(zip(valid_positions, annotated_valid))
    annotated: List[Dict[str, Any]] = []
    for index, (row, identity_error) in enumerate(copied):
        if identity_error is None:
            annotated.append(annotated_by_position[index])
            continue
        failed = dict(row)
        failed.update(
            {
                "outcome": None,
                "logicalOutcome": None,
                "logical_outcome": None,
                "sourceOutcomeLabel": None,
                "source_outcome_label": None,
                "outcomeSemanticsValid": False,
                "outcomeSemanticsStatus": identity_error,
            }
        )
        annotated.append(failed)
    market_ids = [_market_id(row) for row in annotated]
    semantics_by_market = load_market_outcome_semantics(
        ctx,
        [market_id for market_id in market_ids if market_id is not None],
    )
    return [
        _project_annotated_price_fact(
            row,
            (
                _failed_semantics(str(row.get("outcomeSemanticsStatus")))
                if str(row.get("outcomeSemanticsStatus") or "").endswith("_alias_conflict")
                else semantics_by_market.get(_market_id(row) or 0)
                or _failed_semantics("market_identity_missing")
            ),
            proof_kind="canonical_token",
        )
        for row in annotated
    ]


def _clear_public_semantic_fields(row: Dict[str, Any], *, clear_outcome: bool) -> None:
    for field in (*_YES_NO_PRICE_FIELDS, *_DIRECTIONAL_FIELDS):
        if field in row:
            row[field] = None
    for field in (
        "outcomePrices",
        "sourcePrices",
        "primaryOutcomePrice",
        "primary_outcome_price",
        "observedOutcome",
        "observed_outcome",
    ):
        if field in row:
            row[field] = None
    if clear_outcome:
        for field in (
            "outcome",
            "logicalOutcome",
            "logical_outcome",
            "sourceOutcomeLabel",
            "source_outcome_label",
        ):
            if field in row:
                row[field] = None


def _public_price_projection_applicable(row: Mapping[str, Any]) -> bool:
    if any(field in row for field in (*_YES_NO_PRICE_FIELDS, *_DIRECTIONAL_FIELDS)):
        return True
    if any(
        field in row and row.get(field) is not None and not isinstance(row.get(field), Mapping)
        for field in _FACT_PRICE_FIELDS
    ):
        return True
    return any(
        field in row
        for field in (
            "outcomePrices",
            "sourcePrices",
            "primaryOutcomePrice",
            "primary_outcome_price",
            "observedOutcome",
            "observed_outcome",
        )
    )


def _oracle_raw_fingerprint(value: Any) -> str:
    parsed = value
    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = text
    return _canonical_json(parsed)


def _project_public_oracle_fields(
    row: Dict[str, Any],
    semantics: Mapping[str, Any],
    *,
    inherited_rejection: bool = False,
) -> Optional[str]:
    present = inherited_rejection or any(
        field in row
        for field in (
            *_ORACLE_OUTCOME_FIELDS,
            *_ORACLE_OUTCOME_FIELDS.values(),
            *_ORACLE_RAW_DIRECTIONAL_FIELDS,
        )
    )
    if not present:
        return None
    semantics_valid = bool(semantics.get("valid"))
    logical_slots = semantics.get("logicalSlots")
    if not isinstance(logical_slots, Mapping):
        logical_slots = {}
    projection_valid = semantics_valid and not inherited_rejection
    original_outcome_fields = {field for field in _ORACLE_OUTCOME_FIELDS if field in row}
    resolved_markers: Dict[str, str] = {}
    rejected_fields: set[str] = set()
    rejection_reason: Optional[str] = None
    for field, logical_field in _ORACLE_OUTCOME_FIELDS.items():
        claimed_logical = str(row.pop(logical_field, None) or "").strip().upper()
        if field not in row:
            continue
        outcome_text = str(row.get(field) or "").strip()
        logical = outcome_text.upper()
        if logical in {"", "UNKNOWN", "CANCELLED"}:
            row[field] = logical or None
            resolved_markers[field] = f"safe:{logical or 'empty'}"
            continue
        if inherited_rejection:
            row[field] = None
            rejected_fields.add(field)
            continue
        if not semantics_valid:
            row[field] = None
            projection_valid = False
            rejected_fields.add(field)
            continue
        source_matches = [
            candidate
            for candidate in logical_slots.values()
            if isinstance(candidate, Mapping)
            and outcome_text.casefold()
            == str(candidate.get("sourceLabel") or "").strip().casefold()
        ]
        source_match_logical = (
            str(source_matches[0].get("logicalOutcome") or "").strip().upper()
            if len(source_matches) == 1
            else None
        )
        literal_logical = logical if logical in {"YES", "NO"} else None
        if claimed_logical in {"YES", "NO"}:
            claimed_slot = logical_slots.get(claimed_logical)
            claimed_label = (
                str(claimed_slot.get("sourceLabel") or "").strip()
                if isinstance(claimed_slot, Mapping)
                else ""
            )
            if not claimed_label or not (
                literal_logical == claimed_logical
                or outcome_text.casefold() == claimed_label.casefold()
            ):
                row[field] = None
                projection_valid = False
                rejected_fields.add(field)
                rejection_reason = "oracle_outcome_unverified"
                continue
            logical = claimed_logical
        elif literal_logical is not None:
            if source_match_logical is not None and source_match_logical != literal_logical:
                row[field] = None
                projection_valid = False
                rejected_fields.add(field)
                rejection_reason = "oracle_outcome_alias_conflict"
                continue
            logical = literal_logical
        elif source_match_logical in {"YES", "NO"}:
            logical = source_match_logical
        else:
            row[field] = None
            projection_valid = False
            rejected_fields.add(field)
            rejection_reason = "oracle_outcome_unverified"
            continue
        slot = logical_slots.get(logical)
        source_label = str(slot.get("sourceLabel") or "").strip() if isinstance(slot, Mapping) else ""
        if not source_label:
            row[field] = None
            projection_valid = False
            rejected_fields.add(field)
            rejection_reason = "oracle_logical_slot_missing"
            continue
        row[logical_field] = logical
        row[field] = source_label
        resolved_markers[field] = logical
    for alias_group in _ORACLE_OUTCOME_ALIAS_GROUPS:
        present_aliases = [field for field in alias_group if field in original_outcome_fields]
        if len(present_aliases) < 2:
            continue
        markers = {resolved_markers.get(field) for field in present_aliases}
        if rejected_fields.intersection(present_aliases) or len(markers) != 1:
            projection_valid = False
            rejection_reason = "oracle_outcome_alias_conflict"
            for field in alias_group:
                if field in row:
                    row[field] = None
                row.pop(_ORACLE_OUTCOME_FIELDS[field], None)
    for alias_group in _ORACLE_RAW_ALIAS_GROUPS:
        present_aliases = [field for field in alias_group if field in row]
        if len(present_aliases) >= 2 and len(
            {_oracle_raw_fingerprint(row.get(field)) for field in present_aliases}
        ) != 1:
            projection_valid = False
            rejection_reason = "oracle_raw_alias_conflict"
            for field in alias_group:
                row[field] = None
    raw_values_supported = bool(projection_valid and semantics.get("supportsYesNoWording"))
    if not raw_values_supported:
        for field in _ORACLE_RAW_DIRECTIONAL_FIELDS:
            if field in row:
                row[field] = None
    row["oracleOutcomeSemanticsStatus"] = semantics.get("status")
    row["oracleOutcomeSemanticsValid"] = projection_valid
    if inherited_rejection:
        row["oracleOutcomeSemanticsReason"] = "cached_oracle_projection_previously_rejected"
        return "cached_oracle_projection_previously_rejected"
    if not semantics_valid:
        reason = str(semantics.get("status") or "projection_missing")
        row["oracleOutcomeSemanticsReason"] = reason
        return reason
    if not projection_valid:
        reason = rejection_reason or "oracle_logical_slot_missing"
        row["oracleOutcomeSemanticsReason"] = reason
        return reason
    if not semantics.get("supportsYesNoWording"):
        row["oracleOutcomeSemanticsReason"] = "oracle_raw_yes_no_values_suppressed"
        return "oracle_raw_yes_no_values_suppressed"
    row["oracleOutcomeSemanticsReason"] = None
    return None


def sanitize_public_market_payload(
    ctx: Mapping[str, Any],
    payload: Any,
    *,
    market_id: Any = None,
) -> Any:
    """Re-prove and sanitize public market payloads at the serving boundary.

    Cached capability flags and price pairs are deliberately discarded.  A
    price survives only when this request can bind it to an exact canonical
    token, or to the trusted aggregate mutation-proof callback above.
    """

    copied = deepcopy(payload)
    root_market_id: Optional[int]
    try:
        root_market_id = int(market_id) if int(market_id or 0) > 0 else None
    except (TypeError, ValueError):
        root_market_id = None

    requested_market_ids: set[int] = set()

    def collect_market_ids(value: Any, inherited_market_id: Optional[int]) -> None:
        if isinstance(value, list):
            for item in value:
                collect_market_ids(item, inherited_market_id)
            return
        if not isinstance(value, Mapping):
            return
        normalized, identity_error = _normalize_fact_identity_aliases(value)
        current_market_id = (
            _market_id(normalized) if identity_error is None else None
        ) or inherited_market_id
        if current_market_id is not None:
            requested_market_ids.add(current_market_id)
        for item in value.values():
            if isinstance(item, (Mapping, list)):
                collect_market_ids(item, current_market_id)

    collect_market_ids(copied, root_market_id)
    semantics_by_market = load_market_outcome_semantics(ctx, requested_market_ids)

    def visit(value: Any, inherited_market_id: Optional[int], *, root: bool = False) -> Any:
        if isinstance(value, list):
            return [visit(item, inherited_market_id) for item in value]
        if not isinstance(value, Mapping):
            return value
        row, identity_error = _normalize_fact_identity_aliases(value)
        declared_fact_price = any(
            field in value and not isinstance(value.get(field), Mapping)
            for field in _FACT_PRICE_FIELDS
        )
        declared_token_alias = any(field in value for field in _TOKEN_IDENTITY_FIELDS)
        semantic_field_present = bool(_PUBLIC_SEMANTIC_FIELDS & set(row))
        should_validate_fact_price = bool(
            declared_fact_price
            and (root or declared_token_alias or semantic_field_present)
        )
        if identity_error is None and should_validate_fact_price:
            row, identity_error = _normalize_fact_price_aliases(row)
        own_market_id = _market_id(row)
        if root and root_market_id is not None and own_market_id not in {None, root_market_id}:
            identity_error = "market_route_identity_mismatch"
            for field in _MARKET_IDENTITY_FIELDS:
                if field in row:
                    row[field] = None
            own_market_id = None
        current_market_id = own_market_id or inherited_market_id
        has_token_price_shape = bool(declared_fact_price and declared_token_alias)
        is_semantic_payload = (
            root
            or identity_error is not None
            or has_token_price_shape
            or semantic_field_present
        )
        inherited_oracle_rejection = any(
            _strict_bool(row.get(field)) is False
            for field in ("oracleOutcomeSemanticsValid", "oracle_outcome_semantics_valid")
            if field in row
        )
        if is_semantic_payload:
            for field in _SEMANTIC_ATTESTATION_FIELDS:
                row.pop(field, None)
            row.pop("outcomeCode", None)
            row.pop("outcome_code", None)
        projection: Optional[Dict[str, Any]] = None
        semantics = _failed_semantics("market_identity_missing")
        if is_semantic_payload:
            if identity_error is not None:
                semantics = _failed_semantics(identity_error)
            elif current_market_id is not None:
                semantics = semantics_by_market.get(current_market_id) or _failed_semantics(
                    "market_or_projection_missing"
                )
            price_applicable = has_token_price_shape or _public_price_projection_applicable(row)
            has_exact_fact = bool(
                identity_error is None and _token_id(row) and _fact_price(row) is not None
            )
            proof_row = dict(row)
            if current_market_id is not None and _market_id(proof_row) is None:
                proof_row["marketId"] = current_market_id
            if has_exact_fact:
                untrusted_cached_fact = proof_row
                for field in (
                    "outcome",
                    "logicalOutcome",
                    "logical_outcome",
                    "sourceOutcomeLabel",
                    "source_outcome_label",
                    "outcome_code",
                    "outcomeCode",
                ):
                    untrusted_cached_fact.pop(field, None)
                projection = project_token_price_fact(ctx, untrusted_cached_fact)
            elif _fact_price(row) is not None and _aggregate_mutation_proof_valid(ctx, proof_row):
                projection = project_market_pair(ctx, proof_row)
            price_valid = bool(projection and projection.get("priceProjectionValid"))
            clear_outcome = not bool(projection and projection.get("outcomeSemanticsValid"))
            _clear_public_semantic_fields(row, clear_outcome=clear_outcome)
            if not price_valid:
                for field in _FACT_PRICE_FIELDS:
                    if field in row and not isinstance(row.get(field), Mapping):
                        row[field] = None
            if projection is not None:
                for field in (
                    "outcome",
                    "logicalOutcome",
                    "logical_outcome",
                    "sourceOutcomeLabel",
                    "source_outcome_label",
                    "outcomePrices",
                    "sourcePrices",
                    "primaryOutcomePrice",
                    "observedOutcome",
                    "upPrice",
                    "downPrice",
                    "latestUpPrice",
                    "latestDownPrice",
                    "yesPrice",
                    "noPrice",
                    "latestPrice",
                    "latestYesPrice",
                    "latestNoPrice",
                    "tokenPrice",
                    "priceProjectionStatus",
                    "priceProjectionValid",
                    "priceProjectionProof",
                    "priceProjectionReason",
                ):
                    if field in projection:
                        row[field] = projection[field]
            oracle_reason = _project_public_oracle_fields(
                row,
                semantics,
                inherited_rejection=inherited_oracle_rejection,
            )
            capabilities = _projection_capabilities(
                semantics,
                price_valid=price_valid,
                price_applicable=price_applicable,
            )
            reason = capabilities["priceProjectionReason"]
            if reason is None:
                reason = oracle_reason
            if reason is None and not semantics.get("valid"):
                reason = str(semantics.get("status") or "projection_missing")
            effective_semantics_status = (
                projection.get("outcomeSemanticsStatus")
                if projection is not None
                else semantics.get("status")
            )
            effective_semantics_valid = (
                bool(projection.get("outcomeSemanticsValid"))
                if projection is not None
                else bool(semantics.get("valid"))
            )
            row.update(
                {
                    "outcomeSemanticsStatus": effective_semantics_status,
                    "outcomeSemanticsValid": effective_semantics_valid,
                    "semanticMode": semantics.get("semanticMode"),
                    "outcomeSemanticsCapabilities": capabilities,
                    "outcomeSemanticsCapabilityReason": reason,
                    "supportsYesNoWording": capabilities["supportsYesNoWording"],
                    "supportsDirectionalSemantics": capabilities["supportsDirectionalSemantics"],
                    "priceProjectionStatus": (
                        "projected"
                        if price_valid
                        else capabilities["priceProjectionReason"] or "not_applicable"
                    ),
                    "priceProjectionValid": price_valid,
                    "priceProjectionProof": (
                        projection.get("priceProjectionProof") if projection is not None else None
                    ),
                    "priceProjectionReason": capabilities["priceProjectionReason"],
                }
            )
        for key, item in list(row.items()):
            if key in _SEMANTIC_ATTESTATION_FIELDS or key in {"outcomePrices", "sourcePrices"}:
                continue
            if isinstance(item, (Mapping, list)):
                row[key] = visit(item, current_market_id)
        return row

    return visit(copied, root_market_id, root=True)


def directional_semantics_allowed(row: Mapping[str, Any]) -> bool:
    capabilities = row.get("outcomeSemanticsCapabilities")
    nested_directional = (
        capabilities.get("supportsDirectionalSemantics") if isinstance(capabilities, Mapping) else False
    )
    return bool(
        row.get("outcomeSemanticsValid", row.get("outcome_semantics_valid"))
        and row.get(
            "supportsDirectionalSemantics",
            row.get("supports_directional_semantics", nested_directional),
        )
    )
