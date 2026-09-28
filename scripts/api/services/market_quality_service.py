from __future__ import annotations

from api.context import RuntimeResources, runtime_resources

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, cast

from api.context import resolve_service_callable


CONTRACT_VERSION = "prediction-market-data-quality.v4"
CACHE_NAMESPACE = "snapshot:market_data_quality"
CACHE_KEY = "v4-observation-authority-gates"
CACHE_TTL_SECONDS = 300

_BASE_SYNC_STATE_KEYS = (
    "market_sync",
    "market_sync_live",
    "trade_sync",
    "trade_sync_live",
    "oracle_sync",
    "oracle_sync_live",
)
_HISTORY_SYNC_STATE_IDS = {
    "gamma_market_history_backfill": "gamma-history-open",
    "gamma_market_history_backfill_closed": "gamma-history-closed",
    "gamma_event_history_backfill": "gamma-event-history-open",
    "gamma_event_history_backfill_closed": "gamma-event-history-closed",
    "market_tokens_backfill_v1": "token-registry-backfill",
    "placeholder_market_reconciliation_v1": "placeholder-reconciliation",
    "market_canonical_identity_reconciliation_v1": "canonical-identity-reconciliation",
    "market_source_semantics_reconciliation_v1": "source-semantics-reconciliation",
}
_HISTORY_SYNC_STATE_KEYS = tuple(_HISTORY_SYNC_STATE_IDS)


_MARKET_HISTORY_SCHEMA = "gamma-history-commit-v4"
_EVENT_HISTORY_SCHEMA = "gamma-event-history-commit-v4"
_HISTORY_COMPOSITE_SCHEMA = "gamma-history-composite-reconciliation-v1"
_HISTORY_COMPOSITE_STATUS = (
    "operationally_reconciled_mutable_traversal_epochs"
)
_HISTORY_COMPOSITE_TABLE = "gamma_history_composite_receipts"
_MARKET_OBSERVATION_SCOPE = "identity_and_hash_only"
_EVENT_OBSERVATION_SCOPE = "identity_relationship_and_hash_only"
_MARKET_OBSERVATION_FIELDS = (
    "observation_index",
    "source_page_index",
    "source_item_index",
    "source_page_sha256",
    "page_start_cursor_chain_sha256",
    "page_end_cursor_chain_sha256",
    "gamma_market_id",
    "condition_id",
    "question_id",
    "yes_token_id",
    "no_token_id",
    "source_payload_sha256",
    "source_request_partition_json",
    "source_page_observed_oldest",
    "source_page_observed_newest",
    "reconstruction_scope",
)
_MARKET_OBSERVATION_FIELDS_EXTENDED = (
    *_MARKET_OBSERVATION_FIELDS[:11],
    "ordered_token_ids_json",
    "ordered_outcomes_json",
    "token_semantics_classification",
    "logical_mapping_reason",
    *_MARKET_OBSERVATION_FIELDS[11:],
)
_EVENT_OBSERVATION_FIELDS = (
    "observation_index",
    "source_page_index",
    "source_event_index",
    "embedded_market_index",
    "source_page_sha256",
    "page_start_cursor_chain_sha256",
    "page_end_cursor_chain_sha256",
    "event_id",
    "event_slug",
    "gamma_market_id",
    "condition_id",
    "question_id",
    "yes_token_id",
    "no_token_id",
    "event_source_payload_sha256",
    "market_source_payload_sha256",
    "relationship_sha256",
    "source_request_partition_json",
    "source_page_observed_oldest",
    "source_page_observed_newest",
    "reconstruction_scope",
)
_EVENT_OBSERVATION_FIELDS_EXTENDED = (
    *_EVENT_OBSERVATION_FIELDS[:14],
    "ordered_token_ids_json",
    "ordered_outcomes_json",
    "token_semantics_classification",
    "logical_mapping_reason",
    *_EVENT_OBSERVATION_FIELDS[14:],
)
_HISTORY_STREAM_SPECS = (
    {
        "kind": "market",
        "source_filter": "open",
        "watermark_id": "gamma-history-open",
        "sync_state_key": "gamma_market_history_backfill",
        "commit_table": "gamma_market_history_commits",
        "residual_table": "gamma_market_history_residuals",
        "observation_table": "gamma_market_history_observations",
        "observation_fields": _MARKET_OBSERVATION_FIELDS,
        "observation_fields_by_evidence_kind": {
            "market_identity_projection": _MARKET_OBSERVATION_FIELDS,
            "market_identity_source_token_semantics_projection": (
                _MARKET_OBSERVATION_FIELDS_EXTENDED
            ),
        },
        "observation_scope": _MARKET_OBSERVATION_SCOPE,
        "observation_evidence_kinds": (
            "market_identity_projection",
            "market_identity_source_token_semantics_projection",
        ),
        "endpoint_suffix": "/markets/keyset",
        "schema_version": _MARKET_HISTORY_SCHEMA,
        "state_residual_count": "skipped",
        "receipt_residual_count": "classified_residual_count",
        "receipt_reason_counts": "classified_residual_reason_counts",
        "source_accounted_field": "source_count_reconciled",
        "completeness_claim_field": "open_closed_union_completeness_claimed",
    },
    {
        "kind": "market",
        "source_filter": "closed",
        "watermark_id": "gamma-history-closed",
        "sync_state_key": "gamma_market_history_backfill_closed",
        "commit_table": "gamma_market_history_commits",
        "residual_table": "gamma_market_history_residuals",
        "observation_table": "gamma_market_history_observations",
        "observation_fields": _MARKET_OBSERVATION_FIELDS,
        "observation_fields_by_evidence_kind": {
            "market_identity_projection": _MARKET_OBSERVATION_FIELDS,
            "market_identity_source_token_semantics_projection": (
                _MARKET_OBSERVATION_FIELDS_EXTENDED
            ),
        },
        "observation_scope": _MARKET_OBSERVATION_SCOPE,
        "observation_evidence_kinds": (
            "market_identity_projection",
            "market_identity_source_token_semantics_projection",
        ),
        "endpoint_suffix": "/markets/keyset",
        "schema_version": _MARKET_HISTORY_SCHEMA,
        "state_residual_count": "skipped",
        "receipt_residual_count": "classified_residual_count",
        "receipt_reason_counts": "classified_residual_reason_counts",
        "source_accounted_field": "source_count_reconciled",
        "completeness_claim_field": "open_closed_union_completeness_claimed",
    },
    {
        "kind": "event",
        "source_filter": "open",
        "watermark_id": "gamma-event-history-open",
        "sync_state_key": "gamma_event_history_backfill",
        "commit_table": "gamma_event_history_commits",
        "residual_table": "gamma_event_history_residuals",
        "observation_table": "gamma_event_history_observations",
        "observation_fields": _EVENT_OBSERVATION_FIELDS,
        "observation_fields_by_evidence_kind": {
            "event_market_relationship_projection": _EVENT_OBSERVATION_FIELDS,
            "event_market_relationship_source_token_semantics_projection": (
                _EVENT_OBSERVATION_FIELDS_EXTENDED
            ),
        },
        "observation_scope": _EVENT_OBSERVATION_SCOPE,
        "observation_evidence_kinds": (
            "event_market_relationship_projection",
            "event_market_relationship_source_token_semantics_projection",
        ),
        "endpoint_suffix": "/events/keyset",
        "schema_version": _EVENT_HISTORY_SCHEMA,
        "state_residual_count": "classified_residuals",
        "receipt_residual_count": "classified_residual_count",
        "receipt_reason_counts": "classified_residual_reason_counts",
        "source_accounted_field": "embedded_market_count_reconciled",
        "completeness_claim_field": "absolute_gamma_history_completeness_claimed",
    },
    {
        "kind": "event",
        "source_filter": "closed",
        "watermark_id": "gamma-event-history-closed",
        "sync_state_key": "gamma_event_history_backfill_closed",
        "commit_table": "gamma_event_history_commits",
        "residual_table": "gamma_event_history_residuals",
        "observation_table": "gamma_event_history_observations",
        "observation_fields": _EVENT_OBSERVATION_FIELDS,
        "observation_fields_by_evidence_kind": {
            "event_market_relationship_projection": _EVENT_OBSERVATION_FIELDS,
            "event_market_relationship_source_token_semantics_projection": (
                _EVENT_OBSERVATION_FIELDS_EXTENDED
            ),
        },
        "observation_scope": _EVENT_OBSERVATION_SCOPE,
        "observation_evidence_kinds": (
            "event_market_relationship_projection",
            "event_market_relationship_source_token_semantics_projection",
        ),
        "endpoint_suffix": "/events/keyset",
        "schema_version": _EVENT_HISTORY_SCHEMA,
        "state_residual_count": "classified_residuals",
        "receipt_residual_count": "classified_residual_count",
        "receipt_reason_counts": "classified_residual_reason_counts",
        "source_accounted_field": "embedded_market_count_reconciled",
        "completeness_claim_field": "absolute_gamma_history_completeness_claimed",
    },
)


class MarketQualityQueryError(RuntimeError):
    """A database read failed, so a new quality snapshot must not be cached."""

    def __init__(self, operation: str, exc: BaseException) -> None:
        self.operation = operation
        self.original_type = type(exc).__name__
        super().__init__(f"{operation} failed: {self.original_type}")

_PLACEHOLDER_SQL = """(
    LOWER(COALESCE(m.category, '')) = 'orderfilled-placeholder'
    OR LOWER(COALESCE(m.slug, '')) LIKE 'trade-indexer-placeholder-%%'
)"""
_ONCHAIN_V2_SQL = """(
    LOWER(COALESCE(m.slug, '')) LIKE 'onchain-condition-v2-%%'
    OR LOWER(COALESCE(m.title, '')) LIKE 'unlisted polymarket ctf v2 condition%%'
)"""
_GAMMA_CANONICAL_SQL = f"""(
    COALESCE(TRIM(m.gamma_market_id), '') <> ''
    AND NOT {_PLACEHOLDER_SQL}
    AND NOT {_ONCHAIN_V2_SQL}
)"""


def _service_callable(context: Mapping[str, Any], name: str) -> Callable[..., Any]:
    return resolve_service_callable(context, name)


@dataclass(frozen=True)
class MarketQualityDependencies:
    resources: RuntimeResources
    application: Any
    query_one: Callable[..., Any]
    query_all: Callable[..., Any]
    table_exists: Callable[[str], bool]
    get_snapshot_payload: Callable[..., Any]
    get_recent_oracle_snapshot: Callable[..., Any]
    utc_now_iso: Callable[[], str]
    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> MarketQualityDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            resources=runtime_resources(context),
            application=context.get("app"),
            query_one=_service_callable(context, "query_one"),
            query_all=_service_callable(context, "query_all"),
            table_exists=cast(Callable[[str], bool], _service_callable(context, "table_exists")),
            get_snapshot_payload=_service_callable(context, "get_snapshot_payload"),
            get_recent_oracle_snapshot=_service_callable(context, "get_recent_oracle_snapshot"),
            utc_now_iso=cast(Callable[[], str], _service_callable(context, "utc_now_iso")),
        )


def _number(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _optional_number(row: Mapping[str, Any], key: str) -> int | None:
    if key not in row or row.get(key) is None:
        return None
    return _number(row.get(key))


def _decode_state(value: Any) -> Any:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(character in "0123456789abcdef" for character in text)


def _state_mapping(watermark: Mapping[str, Any]) -> dict[str, Any]:
    state = watermark.get("state")
    return dict(state) if isinstance(state, Mapping) else {}


def _state_checkpoint_complete(state: Mapping[str, Any]) -> bool:
    if str(state.get("status") or "").strip().lower() not in {"complete", "completed"}:
        return False
    checkpoint = _optional_number(state, "checkpoint")
    audit_hi = _optional_number(state, "audit_hi")
    if checkpoint is None or audit_hi is None:
        return False
    return checkpoint >= audit_hi


def _iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(" GMT") and "," in text:
        try:
            return datetime.strptime(text, "%a, %d %b %Y %H:%M:%S GMT").replace(
                tzinfo=timezone.utc
            ).isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    return text.replace(" ", "T", 1) if " " in text and "T" not in text else text


def _parse_datetime(value: Any) -> datetime | None:
    text = _iso(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _age_seconds(value: Any, now: datetime) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds()))


def _coverage(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round((numerator / denominator) * 100, 2)


def _coverage_status(value: float | None, *, warning_at: float = 95.0, ok_at: float = 99.0) -> str:
    if value is None:
        return "unknown"
    if value >= ok_at:
        return "ok"
    if value >= warning_at:
        return "warning"
    return "critical"


def _freshness_status(age_seconds: int | None, *, fresh_seconds: int, stale_seconds: int) -> str:
    if age_seconds is None:
        return "missing"
    if age_seconds <= fresh_seconds:
        return "fresh"
    if age_seconds <= stale_seconds:
        return "aging"
    return "stale"


def _freshness_score(status: str) -> float:
    return {
        "fresh": 100.0,
        "aging": 60.0,
        "stale": 0.0,
        "missing": 0.0,
    }.get(status, 0.0)


def _query_one(
    dependencies: MarketQualityDependencies,
    sql: str,
    params: tuple[Any, ...] = (),
) -> dict[str, Any]:
    try:
        payload = dependencies.query_one(sql, params) if params else dependencies.query_one(sql)
        return dict(payload or {})
    except Exception as exc:
        dependencies.application.logger.exception("market-data-quality aggregate query failed")
        raise MarketQualityQueryError("aggregate-query", exc) from exc


def _query_all(
    dependencies: MarketQualityDependencies,
    sql: str,
    params: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    try:
        rows = dependencies.query_all(sql, params) if params else dependencies.query_all(sql)
        return [dict(row) for row in rows or []]
    except Exception as exc:
        dependencies.application.logger.exception("market-data-quality detail query failed")
        raise MarketQualityQueryError("detail-query", exc) from exc


def _query_one_with_availability(
    dependencies: MarketQualityDependencies,
    sql: str,
    params: tuple[Any, ...] = (),
) -> tuple[dict[str, Any], bool]:
    try:
        payload = dependencies.query_one(sql, params) if params else dependencies.query_one(sql)
        return dict(payload or {}), True
    except Exception as exc:
        dependencies.application.logger.exception(
            "market-data-quality optional aggregate query unavailable"
        )
        raise MarketQualityQueryError("optional-aggregate-query", exc) from exc


def _query_all_with_availability(
    dependencies: MarketQualityDependencies,
    sql: str,
    params: tuple[Any, ...] = (),
) -> tuple[list[dict[str, Any]], bool]:
    try:
        rows = dependencies.query_all(sql, params) if params else dependencies.query_all(sql)
        return [dict(row) for row in rows or []], True
    except Exception as exc:
        dependencies.application.logger.exception(
            "market-data-quality optional detail query unavailable"
        )
        raise MarketQualityQueryError("optional-detail-query", exc) from exc


def _optional_table_exists(
    dependencies: MarketQualityDependencies,
    table_name: str,
) -> bool:
    try:
        return bool(dependencies.table_exists(table_name))
    except Exception as exc:
        dependencies.application.logger.exception(
            "market-data-quality optional table check unavailable table=%s",
            table_name,
        )
        raise MarketQualityQueryError("optional-table-check", exc) from exc


def _count_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(key): _number(count)
        for key, count in sorted(value.items(), key=lambda item: str(item[0]))
        if _number(count) > 0
    }


def _canonical_metadata_audit(market_metrics: Mapping[str, Any]) -> dict[str, Any]:
    observed = "gamma_canonical_count" in market_metrics
    canonical = _number(market_metrics.get("gamma_canonical_count"))
    category_complete = _number(
        market_metrics.get("gamma_canonical_category_complete")
    )
    tags_complete = _number(market_metrics.get("gamma_canonical_tags_complete"))
    metadata_complete = _number(
        market_metrics.get("gamma_canonical_metadata_complete")
    )
    incomplete = max(0, canonical - metadata_complete)
    return {
        "validationAvailable": observed,
        "ok": bool(observed and incomplete == 0),
        "observed": {
            "canonicalCount": canonical,
            "categoryCompleteCount": category_complete,
            "tagsCompleteCount": tags_complete,
            "metadataCompleteCount": metadata_complete,
        },
        "canonicalCount": canonical,
        "missingCategoryCount": max(0, canonical - category_complete),
        "missingTagsCount": max(0, canonical - tags_complete),
        "incompleteCount": incomplete,
    }


def _dimension(
    *,
    dimension_id: str,
    label: str,
    numerator: int,
    denominator: int,
    source: str,
    detail: str,
    observed_at: Any = None,
    warning_at: float = 95.0,
    ok_at: float = 99.0,
) -> dict[str, Any]:
    coverage = _coverage(numerator, denominator)
    return {
        "id": dimension_id,
        "label": label,
        "status": _coverage_status(coverage, warning_at=warning_at, ok_at=ok_at),
        "numerator": numerator,
        "denominator": denominator,
        "coveragePct": coverage,
        "source": source,
        "observedAt": _iso(observed_at),
        "detail": detail,
    }


def _sync_watermarks(
    dependencies: MarketQualityDependencies,
) -> list[dict[str, Any]]:
    if not dependencies.table_exists("sync_state"):
        return []
    rows = _query_all(
        dependencies,
        """
        SELECT key, value, last_block, updated_at
        FROM sync_state
        WHERE key IN (
            'market_sync', 'market_sync_live',
            'trade_sync', 'trade_sync_live',
            'oracle_sync', 'oracle_sync_live',
            'gamma_market_history_backfill',
            'gamma_market_history_backfill_closed',
            'gamma_event_history_backfill',
            'gamma_event_history_backfill_closed',
            'market_tokens_backfill_v1',
            'placeholder_market_reconciliation_v1',
            'market_canonical_identity_reconciliation_v1',
            'market_source_semantics_reconciliation_v1'
        )
        ORDER BY key
        """,
    )
    preferred: dict[str, dict[str, Any]] = {}
    history: dict[str, dict[str, Any]] = {}
    for row in rows:
        raw_key = str(row.get("key") or "")
        item = {
            "id": _HISTORY_SYNC_STATE_IDS.get(raw_key, raw_key),
            "key": raw_key,
            "lastBlock": row.get("last_block"),
            "updatedAt": _iso(row.get("updated_at")),
            "state": _decode_state(row.get("value")),
        }
        if raw_key in _HISTORY_SYNC_STATE_IDS:
            history[raw_key] = item
            continue
        if raw_key not in _BASE_SYNC_STATE_KEYS:
            continue
        family = raw_key.replace("_live", "")
        current = preferred.get(family)
        if current is None or raw_key.endswith("_live"):
            item["id"] = family
            preferred[family] = item
    live_items = [
        preferred[key]
        for key in ("market_sync", "trade_sync", "oracle_sync")
        if key in preferred
    ]
    history_items = [history[key] for key in _HISTORY_SYNC_STATE_KEYS if key in history]
    return live_items + history_items


def _history_stream_evidence(
    dependencies: MarketQualityDependencies,
    watermark: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    state = _state_mapping(watermark)
    epoch_started_at = state.get("epoch_started_at")
    commit_table = str(spec["commit_table"])
    residual_table = str(spec["residual_table"])
    observation_table = str(spec["observation_table"])
    commit_table_present = _optional_table_exists(dependencies, commit_table)
    residual_table_present = _optional_table_exists(dependencies, residual_table)
    observation_table_present = _optional_table_exists(
        dependencies,
        observation_table,
    )

    commit_rows: list[dict[str, Any]] = []
    residual_rows: list[dict[str, Any]] = []
    observation_count_rows: list[dict[str, Any]] = []
    tail_observation_rows: list[dict[str, Any]] = []
    if commit_table_present and epoch_started_at:
        commit_rows = _query_all(
            dependencies,
            f"""
            SELECT
                epoch_started_at,
                commit_batch,
                receipt_sha256,
                receipt_json,
                start_cursor_chain_sha256,
                end_cursor_chain_sha256,
                committed_at
            FROM {commit_table}
            WHERE sync_state_key = ?
              AND source_filter = ?
              AND epoch_started_at = ?
            ORDER BY commit_batch
            """,
            (
                str(spec["sync_state_key"]),
                str(spec["source_filter"]),
                epoch_started_at,
            ),
        )
    if observation_table_present and epoch_started_at:
        relationship_projection = (
            """,
                SUM(CASE
                    WHEN LENGTH(COALESCE(relationship_sha256, '')) = 64
                    THEN 0 ELSE 1
                END) AS invalid_relationship_sha_length_count"""
            if spec["kind"] == "event"
            else ""
        )
        observation_count_rows = _query_all(
            dependencies,
            f"""
            SELECT
                commit_batch,
                COUNT(*) AS observation_count
                {relationship_projection}
            FROM {observation_table}
            WHERE sync_state_key = ?
              AND source_filter = ?
              AND epoch_started_at = ?
            GROUP BY commit_batch
            ORDER BY commit_batch
            """,
            (
                str(spec["sync_state_key"]),
                str(spec["source_filter"]),
                epoch_started_at,
            ),
        )
        tail_receipt = (
            _decode_receipt(commit_rows[-1].get("receipt_json"))
            if commit_rows
            else None
        )
        evidence_kind = (
            tail_receipt.get("observation_evidence_kind")
            if isinstance(tail_receipt, Mapping)
            else None
        )
        fields_by_kind = spec.get("observation_fields_by_evidence_kind")
        selected_fields = (
            fields_by_kind.get(evidence_kind)
            if isinstance(fields_by_kind, Mapping)
            else None
        )
        if not isinstance(selected_fields, tuple):
            selected_fields = spec["observation_fields"]
        observation_fields = ",\n                ".join(
            str(field) for field in selected_fields
        )
        tail_batch = _optional_number(state, "commit_batches")
        if tail_batch is not None and tail_batch > 0:
            tail_observation_rows = _query_all(
                dependencies,
                f"""
                SELECT
                    commit_batch,
                    {observation_fields}
                FROM {observation_table}
                WHERE sync_state_key = ?
                  AND source_filter = ?
                  AND epoch_started_at = ?
                  AND commit_batch = ?
                ORDER BY observation_index
                """,
                (
                    str(spec["sync_state_key"]),
                    str(spec["source_filter"]),
                    epoch_started_at,
                    tail_batch,
                ),
            )
    if residual_table_present and epoch_started_at:
        residual_rows = _query_all(
            dependencies,
            f"""
            SELECT
                status,
                failure_reason,
                COUNT(*) AS classified_count,
                SUM(attempts) AS total_attempts,
                MAX(last_seen_at) AS updated_at
            FROM {residual_table}
            WHERE sync_state_key = ?
              AND source_filter = ?
              AND last_epoch_started_at = ?
            GROUP BY status, failure_reason
            ORDER BY status, failure_reason
            """,
            (
                str(spec["sync_state_key"]),
                str(spec["source_filter"]),
                epoch_started_at,
            ),
        )

    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    residual_count = 0
    total_attempts = 0
    updated_at: str | None = None
    for row in residual_rows:
        count = _number(row.get("classified_count"))
        status = str(row.get("status") or "unknown").strip() or "unknown"
        reason = str(row.get("failure_reason") or "unknown").strip() or "unknown"
        residual_count += count
        total_attempts += _number(row.get("total_attempts"))
        status_counts[status] = status_counts.get(status, 0) + count
        reason_counts[reason] = reason_counts.get(reason, 0) + count
        observed = _iso(row.get("updated_at"))
        if observed and (updated_at is None or observed > updated_at):
            updated_at = observed

    return {
        "kind": spec["kind"],
        "sourceFilter": spec["source_filter"],
        "syncStateKey": spec["sync_state_key"],
        "epochStartedAt": _iso(epoch_started_at),
        "authority": {
            "tablePresent": commit_table_present,
            "availability": "available" if commit_table_present else "unavailable",
            "unavailableReason": None if commit_table_present else "table-missing",
            "rows": commit_rows,
        },
        "residualLedger": {
            "tablePresent": residual_table_present,
            "availability": "available" if residual_table_present else "unavailable",
            "unavailableReason": None if residual_table_present else "table-missing",
            "classifiedCount": residual_count if residual_table_present else None,
            "statusCounts": _count_mapping(status_counts),
            "reasonCounts": _count_mapping(reason_counts),
            "totalAttempts": total_attempts if residual_table_present else None,
            "updatedAt": updated_at,
            "epochStartedAt": _iso(epoch_started_at),
        },
        "observationLedger": {
            "tablePresent": observation_table_present,
            "availability": (
                "available" if observation_table_present else "unavailable"
            ),
            "unavailableReason": (
                None if observation_table_present else "table-missing"
            ),
            "countRows": observation_count_rows,
            "tailRows": tail_observation_rows,
        },
    }


def _decode_receipt(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    return dict(decoded) if isinstance(decoded, Mapping) else None


def _strict_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _history_source_partition(
    receipt: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any] | None:
    raw = receipt.get("source_request_partition")
    if not isinstance(raw, Mapping):
        return None
    partition = dict(raw)
    endpoint = str(partition.get("endpoint") or "").strip().rstrip("/")
    source_filter = str(spec["source_filter"])
    expected = {
        "endpoint": endpoint,
        "source_filter": source_filter,
        "closed": source_filter == "closed",
    }
    if (
        not endpoint.endswith(str(spec["endpoint_suffix"]))
        or partition != expected
    ):
        return None
    return partition


def _validate_history_page_traversal(
    receipt: Mapping[str, Any],
    spec: Mapping[str, Any],
    partition: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    batch = _number(receipt.get("commit_batch"))
    errors: list[str] = []
    page_count = _strict_nonnegative_int(receipt.get("page_count"))
    page_hashes = receipt.get("page_sha256")
    page_evidence = receipt.get("page_traversal_evidence")
    if (
        page_count is None
        or page_count <= 0
        or not isinstance(page_hashes, list)
        or len(page_hashes) != page_count
        or any(not _is_sha256(value) for value in page_hashes)
        or not isinstance(page_evidence, list)
        or len(page_evidence) != page_count
    ):
        return [], [f"page-traversal-shape-invalid-batch-{batch}"]

    normalized_pages: list[dict[str, Any]] = []
    for expected_index, raw_page in enumerate(page_evidence):
        if not isinstance(raw_page, Mapping):
            errors.append(f"page-traversal-row-invalid-batch-{batch}")
            continue
        page = dict(raw_page)
        if (
            _strict_nonnegative_int(page.get("source_page_index"))
            != expected_index
            or page.get("source_page_sha256") != page_hashes[expected_index]
            or not _is_sha256(page.get("source_page_sha256"))
            or not _is_sha256(page.get("page_start_cursor_chain_sha256"))
            or not _is_sha256(page.get("page_end_cursor_chain_sha256"))
            or partition is None
            or page.get("source_request_partition") != partition
        ):
            errors.append(
                f"page-traversal-row-invalid-batch-{batch}-page-{expected_index}"
            )
        count_fields = (
            ("source_market_count",)
            if spec["kind"] == "market"
            else ("source_event_count", "embedded_market_count")
        )
        if any(
            _strict_nonnegative_int(page.get(field)) is None
            for field in count_fields
        ):
            errors.append(
                f"page-traversal-count-invalid-batch-{batch}-page-{expected_index}"
            )
        normalized_pages.append(page)

    if normalized_pages:
        if (
            normalized_pages[0].get("page_start_cursor_chain_sha256")
            != receipt.get("start_cursor_chain_sha256")
            or normalized_pages[-1].get("page_end_cursor_chain_sha256")
            != receipt.get("end_cursor_chain_sha256")
        ):
            errors.append(f"page-cursor-boundary-invalid-batch-{batch}")
        for previous, current in zip(
            normalized_pages,
            normalized_pages[1:],
        ):
            if (
                previous.get("page_end_cursor_chain_sha256")
                != current.get("page_start_cursor_chain_sha256")
            ):
                errors.append(f"page-cursor-chain-broken-batch-{batch}")
                break

    if receipt.get("page_traversal_evidence_sha256") != _sha256_json(
        normalized_pages
    ):
        errors.append(f"page-traversal-sha-invalid-batch-{batch}")

    if spec["kind"] == "market":
        if sum(
            _number(page.get("source_market_count"))
            for page in normalized_pages
        ) != _number(receipt.get("source_seen_count")):
            errors.append(f"page-source-count-mismatch-batch-{batch}")
    else:
        if sum(
            _number(page.get("source_event_count"))
            for page in normalized_pages
        ) != _number(receipt.get("source_event_count")):
            errors.append(f"page-event-count-mismatch-batch-{batch}")
        if sum(
            _number(page.get("embedded_market_count"))
            for page in normalized_pages
        ) != _number(receipt.get("embedded_market_count")):
            errors.append(f"page-embedded-count-mismatch-batch-{batch}")
        page_cursor_chain = receipt.get("page_cursor_chain_sha256")
        expected_cursor_chain = [receipt.get("start_cursor_chain_sha256")]
        expected_cursor_chain.extend(
            page.get("page_end_cursor_chain_sha256")
            for page in normalized_pages
        )
        if (
            not isinstance(page_cursor_chain, list)
            or page_cursor_chain != expected_cursor_chain
            or any(not _is_sha256(value) for value in page_cursor_chain)
        ):
            errors.append(f"page-cursor-evidence-invalid-batch-{batch}")
    return normalized_pages, errors


def _validate_history_observation_group(
    *,
    raw_rows: list[dict[str, Any]],
    receipt: Mapping[str, Any],
    spec: Mapping[str, Any],
    partition: Mapping[str, Any] | None,
    pages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    batch = _number(receipt.get("commit_batch"))
    errors: list[str] = []
    fields_by_kind = spec.get("observation_fields_by_evidence_kind")
    selected_fields = (
        fields_by_kind.get(receipt.get("observation_evidence_kind"))
        if isinstance(fields_by_kind, Mapping)
        else None
    )
    fields = tuple(
        str(field)
        for field in (
            selected_fields
            if isinstance(selected_fields, tuple)
            else spec["observation_fields"]
        )
    )
    rows = [{field: raw.get(field) for field in fields} for raw in raw_rows]
    rows.sort(key=lambda row: _number(row.get("observation_index")))
    indexes = [
        _strict_nonnegative_int(row.get("observation_index")) for row in rows
    ]
    if indexes != list(range(len(rows))):
        errors.append(f"observation-index-chain-invalid-batch-{batch}")

    coordinate_fields = (
        ("source_page_index", "source_item_index")
        if spec["kind"] == "market"
        else (
            "source_page_index",
            "source_event_index",
            "embedded_market_index",
        )
    )
    coordinates: set[tuple[int, ...]] = set()
    for index, row in enumerate(rows):
        coordinate_values = tuple(
            _strict_nonnegative_int(row.get(field)) for field in coordinate_fields
        )
        if any(value is None for value in coordinate_values):
            errors.append(
                f"observation-coordinate-invalid-batch-{batch}-row-{index}"
            )
            continue
        coordinate = tuple(cast(int, value) for value in coordinate_values)
        if coordinate in coordinates:
            errors.append(f"observation-coordinate-duplicate-batch-{batch}")
        coordinates.add(coordinate)

        page_index = coordinate[0]
        if page_index >= len(pages):
            errors.append(f"observation-page-missing-batch-{batch}-row-{index}")
            continue
        page = pages[page_index]
        if (
            row.get("source_page_sha256")
            != page.get("source_page_sha256")
            or row.get("page_start_cursor_chain_sha256")
            != page.get("page_start_cursor_chain_sha256")
            or row.get("page_end_cursor_chain_sha256")
            != page.get("page_end_cursor_chain_sha256")
            or row.get("source_page_observed_oldest")
            != page.get("source_page_observed_oldest")
            or row.get("source_page_observed_newest")
            != page.get("source_page_observed_newest")
        ):
            errors.append(f"observation-page-evidence-mismatch-batch-{batch}-row-{index}")

        hash_fields = [
            "source_page_sha256",
            "page_start_cursor_chain_sha256",
            "page_end_cursor_chain_sha256",
        ]
        if spec["kind"] == "market":
            hash_fields.append("source_payload_sha256")
        else:
            hash_fields.extend(
                (
                    "event_source_payload_sha256",
                    "market_source_payload_sha256",
                    "relationship_sha256",
                )
            )
        if any(not _is_sha256(row.get(field)) for field in hash_fields):
            errors.append(f"observation-hash-invalid-batch-{batch}-row-{index}")

        if row.get("reconstruction_scope") != spec["observation_scope"]:
            errors.append(f"observation-scope-invalid-batch-{batch}-row-{index}")
        try:
            row_partition = json.loads(
                str(row.get("source_request_partition_json") or "")
            )
        except (TypeError, ValueError):
            row_partition = None
        if partition is None or row_partition != partition:
            errors.append(f"observation-partition-invalid-batch-{batch}-row-{index}")
        required_identity_fields = [
            "gamma_market_id",
            "condition_id",
            "yes_token_id",
            "no_token_id",
        ]
        if spec["kind"] == "event":
            required_identity_fields.insert(0, "event_id")
        if any(
            not str(row.get(field) or "").strip()
            for field in required_identity_fields
        ) or row.get("yes_token_id") == row.get("no_token_id"):
            errors.append(f"observation-identity-invalid-batch-{batch}-row-{index}")

        if "token_semantics_classification" in fields:
            try:
                ordered_token_ids = json.loads(
                    str(row.get("ordered_token_ids_json") or "")
                )
                ordered_outcomes = json.loads(
                    str(row.get("ordered_outcomes_json") or "")
                )
            except (TypeError, ValueError):
                ordered_token_ids = None
                ordered_outcomes = None
            if (
                not isinstance(ordered_token_ids, list)
                or len(ordered_token_ids) != 2
                or any(not str(value or "").strip() for value in ordered_token_ids)
                or ordered_token_ids[0] == ordered_token_ids[1]
                or not isinstance(ordered_outcomes, list)
                or len(ordered_outcomes) != 2
                or not str(row.get("token_semantics_classification") or "").strip()
                or not str(row.get("logical_mapping_reason") or "").strip()
            ):
                errors.append(
                    f"observation-token-semantics-invalid-batch-{batch}-row-{index}"
                )

        if spec["kind"] == "event":
            relationship = {
                "source_page_index": row.get("source_page_index"),
                "source_event_index": row.get("source_event_index"),
                "embedded_market_index": row.get("embedded_market_index"),
                "event_id": row.get("event_id"),
                "event_slug": row.get("event_slug"),
                "gamma_market_id": row.get("gamma_market_id"),
                "condition_id": row.get("condition_id"),
                "event_source_payload_sha256": row.get(
                    "event_source_payload_sha256"
                ),
                "market_source_payload_sha256": row.get(
                    "market_source_payload_sha256"
                ),
            }
            if row.get("relationship_sha256") != _sha256_json(relationship):
                errors.append(
                    f"event-relationship-sha-invalid-batch-{batch}-row-{index}"
                )

    observation_count = _strict_nonnegative_int(receipt.get("observation_count"))
    evidence_sha = _sha256_json(rows)
    postcheck = receipt.get("observation_ledger_postcheck")
    if (
        observation_count is None
        or observation_count != len(rows)
        or receipt.get("observation_evidence_sha256") != evidence_sha
        or not isinstance(postcheck, Mapping)
        or postcheck.get("verified") is not True
        or _strict_nonnegative_int(postcheck.get("matched_rows")) != len(rows)
        or postcheck.get("evidence_sha256") != evidence_sha
        or postcheck.get("reconstruction_scope") != spec["observation_scope"]
    ):
        errors.append(f"observation-ledger-evidence-invalid-batch-{batch}")
    return rows, errors


def _validate_history_stream(
    *,
    watermark: Mapping[str, Any],
    evidence: Mapping[str, Any],
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    state = _state_mapping(watermark)
    errors: list[str] = []
    epoch = _iso(state.get("epoch_started_at"))
    terminal_state = bool(
        str(state.get("status") or "").strip().lower() == "complete"
        and str(state.get("source_filter") or "").strip().lower()
        == str(spec["source_filter"])
        and state.get("source_verified") is True
        and state.get("after_cursor") in (None, "")
        and epoch
        and state.get("completed_at")
        and _is_sha256(state.get("last_commit_sha256"))
        and _number(state.get("commit_batches")) > 0
    )
    if not terminal_state:
        errors.append("sync-state-not-terminal")

    authority = dict(evidence.get("authority") or {})
    rows = authority.pop("rows", [])
    if not isinstance(rows, list):
        rows = []
    if authority.get("availability") != "available":
        errors.append("authority-table-unavailable")
    observation_ledger = dict(evidence.get("observationLedger") or {})
    observation_count_rows = observation_ledger.pop("countRows", [])
    tail_observation_rows = observation_ledger.pop("tailRows", [])
    if not isinstance(observation_count_rows, list):
        observation_count_rows = []
    if not isinstance(tail_observation_rows, list):
        tail_observation_rows = []
    if observation_ledger.get("availability") != "available":
        errors.append("observation-ledger-unavailable")
    db_observation_counts: dict[int, int] = {}
    invalid_relationship_sha_length_count = 0
    for count_row in observation_count_rows:
        if not isinstance(count_row, Mapping):
            errors.append("observation-count-row-invalid")
            continue
        batch = _strict_nonnegative_int(count_row.get("commit_batch"))
        count = _strict_nonnegative_int(count_row.get("observation_count"))
        if (
            batch is None
            or batch <= 0
            or count is None
            or batch in db_observation_counts
        ):
            errors.append("observation-count-row-invalid")
            continue
        db_observation_counts[batch] = count
        invalid_relationship_sha_length_count += _number(
            count_row.get("invalid_relationship_sha_length_count")
        )
    if spec["kind"] == "event" and invalid_relationship_sha_length_count > 0:
        errors.append("event-relationship-sha-length-invalid")

    receipts: list[dict[str, Any]] = []
    receipt_partitions: list[dict[str, Any]] = []
    validated_tail_observations: list[dict[str, Any]] = []
    tail_evidence_sha_verified = False
    expected_batch = 1
    expected_commit_batches = _optional_number(state, "commit_batches")
    previous_end_chain: str | None = None
    receipt_residual_count = 0
    receipt_reason_counts: dict[str, int] = {}
    receipt_observation_count = 0
    receipt_page_count = 0
    receipt_source_count = 0
    receipt_embedded_count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("authority-row-invalid")
            continue
        receipt = _decode_receipt(row.get("receipt_json"))
        if receipt is None:
            errors.append("authority-receipt-json-invalid")
            continue
        claimed_sha = str(receipt.get("commit_sha256") or "")
        checksum_core = dict(receipt)
        checksum_core.pop("commit_sha256", None)
        if (
            receipt.get("schema_version") != spec["schema_version"]
            or str(receipt.get("sync_state_key") or "") != spec["sync_state_key"]
            or str(receipt.get("source_filter") or "").lower()
            != spec["source_filter"]
            or _iso(receipt.get("epoch_started_at")) != epoch
            or _number(receipt.get("commit_batch")) != expected_batch
            or claimed_sha != _sha256_json(checksum_core)
            or claimed_sha != str(row.get("receipt_sha256") or "")
            or str(receipt.get("start_cursor_chain_sha256") or "")
            != str(row.get("start_cursor_chain_sha256") or "")
            or str(receipt.get("end_cursor_chain_sha256") or "")
            != str(row.get("end_cursor_chain_sha256") or "")
            or not _is_sha256(receipt.get("start_cursor_chain_sha256"))
            or not _is_sha256(receipt.get("end_cursor_chain_sha256"))
            or receipt.get("source_verified") is not True
            or receipt.get(spec["source_accounted_field"]) is not True
            or receipt.get(spec["completeness_claim_field"]) is not False
            or receipt.get("source_partition_sequentially_accounted") is not True
            or receipt.get("terminal_scope")
            != "mutable_keyset_partition_traversal"
            or type(receipt.get("terminal")) is not bool
            or receipt.get("source_partition_terminal_for_this_traversal")
            is not receipt.get("terminal")
            or receipt.get("source_snapshot_cutoff_claimed") is not False
            or receipt.get("same_source_frozen_snapshot_claimed") is not False
            or receipt.get("absolute_gamma_history_completeness_claimed")
            is not False
            or receipt.get("composite_identity_join_evidence_available")
            is not True
            or receipt.get("observation_evidence_kind")
            not in spec["observation_evidence_kinds"]
            or receipt.get("observation_reconstruction_scope")
            != spec["observation_scope"]
            or receipt.get(
                "full_source_payload_reconstructable_from_observation_ledger"
            )
            is not False
        ):
            errors.append(f"authority-receipt-invalid-batch-{expected_batch}")
        if (
            previous_end_chain is not None
            and receipt.get("start_cursor_chain_sha256") != previous_end_chain
        ):
            errors.append(f"authority-cursor-chain-broken-batch-{expected_batch}")
        postcheck = receipt.get("residual_ledger_postcheck")
        receipt_evidence_sha = receipt.get("classified_residual_evidence_sha256")
        receipt_unique_count = _optional_number(
            receipt, "classified_residual_unique_count"
        )
        if (
            not isinstance(postcheck, Mapping)
            or postcheck.get("verified") is not True
            or not _is_sha256(receipt_evidence_sha)
            or postcheck.get("evidence_sha256") != receipt_evidence_sha
            or _optional_number(postcheck, "matched_unique_rows")
            != receipt_unique_count
            or receipt_unique_count is None
            or receipt_unique_count
            > _number(receipt.get(spec["receipt_residual_count"]))
        ):
            errors.append(f"authority-residual-postcheck-invalid-batch-{expected_batch}")

        observation_count = _strict_nonnegative_int(
            receipt.get("observation_count")
        )
        page_count = _strict_nonnegative_int(receipt.get("page_count"))
        residual_count = _strict_nonnegative_int(
            receipt.get(spec["receipt_residual_count"])
        )
        if observation_count is None or page_count is None or residual_count is None:
            errors.append(f"authority-counter-invalid-batch-{expected_batch}")
        if spec["kind"] == "market":
            normalized_count = _strict_nonnegative_int(
                receipt.get("normalized_count")
            )
            source_count = _strict_nonnegative_int(
                receipt.get("source_seen_count")
            )
            if (
                normalized_count is None
                or source_count is None
                or observation_count != normalized_count
                or source_count != _number(observation_count) + _number(residual_count)
                or receipt.get("open_closed_union_completeness_claimed")
                is not False
            ):
                errors.append(f"authority-source-accounting-invalid-batch-{expected_batch}")
            receipt_source_count += _number(source_count)
        else:
            normalized_count = _strict_nonnegative_int(
                receipt.get("normalized_observation_count")
            )
            source_count = _strict_nonnegative_int(
                receipt.get("source_event_count")
            )
            embedded_count = _strict_nonnegative_int(
                receipt.get("embedded_market_count")
            )
            if (
                normalized_count is None
                or source_count is None
                or embedded_count is None
                or observation_count != normalized_count
                or embedded_count
                != _number(observation_count) + _number(residual_count)
            ):
                errors.append(f"authority-source-accounting-invalid-batch-{expected_batch}")
            receipt_source_count += _number(source_count)
            receipt_embedded_count += _number(embedded_count)

        partition = _history_source_partition(receipt, spec)
        if partition is None:
            errors.append(f"source-request-partition-invalid-batch-{expected_batch}")
        else:
            receipt_partitions.append(partition)
        pages, page_errors = _validate_history_page_traversal(
            receipt,
            spec,
            partition,
        )
        errors.extend(page_errors)
        if db_observation_counts.get(expected_batch, 0) != _number(
            observation_count
        ):
            errors.append(
                f"observation-db-count-mismatch-batch-{expected_batch}"
            )
        if expected_batch == expected_commit_batches:
            tail_rows = [
                dict(raw)
                for raw in tail_observation_rows
                if isinstance(raw, Mapping)
                and _number(raw.get("commit_batch")) == expected_batch
            ]
            if len(tail_rows) != len(tail_observation_rows):
                errors.append("tail-observation-row-shape-invalid")
            observation_rows, observation_errors = (
                _validate_history_observation_group(
                    raw_rows=tail_rows,
                    receipt=receipt,
                    spec=spec,
                    partition=partition,
                    pages=pages,
                )
            )
            errors.extend(observation_errors)
            validated_tail_observations.extend(observation_rows)
            tail_evidence_sha_verified = not observation_errors
        receipt_observation_count += _number(observation_count)
        receipt_page_count += _number(page_count)
        receipt_residual_count += _number(receipt.get(spec["receipt_residual_count"]))
        for reason, count in _count_mapping(
            receipt.get(spec["receipt_reason_counts"])
        ).items():
            receipt_reason_counts[reason] = receipt_reason_counts.get(reason, 0) + count
        previous_end_chain = str(receipt.get("end_cursor_chain_sha256") or "")
        receipts.append(receipt)
        expected_batch += 1

    unexpected_observation_batches = sorted(
        set(db_observation_counts) - set(range(1, len(receipts) + 1))
    )
    if unexpected_observation_batches:
        errors.append("observation-ledger-has-unreceipted-batches")
    if receipt_partitions and any(
        partition != receipt_partitions[0] for partition in receipt_partitions[1:]
    ):
        errors.append("source-request-partition-drift")

    if expected_commit_batches is None or len(receipts) != expected_commit_batches:
        errors.append("authority-commit-count-mismatch")
    tail = receipts[-1] if receipts else {}
    tail_valid = bool(
        receipts
        and tail.get("terminal") is True
        and _number(tail.get("commit_batch")) == expected_commit_batches
        and str(tail.get("commit_sha256") or "")
        == str(state.get("last_commit_sha256") or "")
        and not any(receipt.get("terminal") is True for receipt in receipts[:-1])
    )
    if not tail_valid:
        errors.append("authority-tail-state-mismatch")
    if (
        str(spec["source_filter"]) == "closed"
        and tail.get("open_prerequisite_evidence")
        != state.get("open_prerequisite_evidence")
    ):
        errors.append("authority-open-prerequisite-mismatch")

    state_residual_count = _optional_number(state, str(spec["state_residual_count"]))
    state_reason_counts = _count_mapping(state.get("residual_reason_counts"))
    residual = dict(evidence.get("residualLedger") or {})
    ledger_count = residual.get("classifiedCount")
    ledger_reason_counts = _count_mapping(residual.get("reasonCounts"))
    residual_accounting_satisfied = bool(
        residual.get("availability") == "available"
        and state_residual_count is not None
        and ledger_count == state_residual_count == receipt_residual_count
        and ledger_reason_counts == state_reason_counts == receipt_reason_counts
        and set(_count_mapping(residual.get("statusCounts"))) <= {"classified_residual"}
    )
    if not residual_accounting_satisfied:
        errors.append("current-epoch-residual-accounting-mismatch")

    state_observation_count = _optional_number(state, "observation_count")
    state_normalized_count = _optional_number(
        state,
        "normalized" if spec["kind"] == "market" else "normalized_observations",
    )
    observation_accounting_satisfied = bool(
        observation_ledger.get("availability") == "available"
        and state.get("observation_reconstruction_scope")
        == spec["observation_scope"]
        and state_observation_count is not None
        and state_normalized_count is not None
        and state_observation_count
        == state_normalized_count
        == receipt_observation_count
        == sum(db_observation_counts.values())
        and _optional_number(state, "pages") == receipt_page_count
        and _optional_number(state, "last_commit_observation_count")
        == _optional_number(tail, "observation_count")
        and state.get("last_commit_observation_evidence_sha256")
        == tail.get("observation_evidence_sha256")
        and _optional_number(state, "last_commit_page_count")
        == _optional_number(tail, "page_count")
        and state.get("last_page_sha256")
        == ((tail.get("page_sha256") or [None])[-1] if tail else None)
    )
    if spec["kind"] == "market":
        observation_accounting_satisfied = bool(
            observation_accounting_satisfied
            and _optional_number(state, "seen") == receipt_source_count
            and _optional_number(state, "skipped") == receipt_residual_count
            and state.get("last_commit_start_cursor_chain_sha256")
            == tail.get("start_cursor_chain_sha256")
            and state.get("last_commit_end_cursor_chain_sha256")
            == tail.get("end_cursor_chain_sha256")
        )
    else:
        observation_accounting_satisfied = bool(
            observation_accounting_satisfied
            and _optional_number(state, "source_events") == receipt_source_count
            and _optional_number(state, "embedded_markets")
            == receipt_embedded_count
            and _optional_number(state, "classified_residuals")
            == receipt_residual_count
            and state.get("last_commit_start_cursor_chain_sha256")
            == tail.get("start_cursor_chain_sha256")
            and state.get("last_commit_end_cursor_chain_sha256")
            == tail.get("end_cursor_chain_sha256")
        )
    if not observation_accounting_satisfied:
        errors.append("current-epoch-observation-accounting-mismatch")

    watermark_pages = _optional_number(watermark, "lastBlock")
    if watermark_pages is not None and watermark_pages != _optional_number(state, "pages"):
        errors.append("sync-state-page-watermark-mismatch")

    authority_valid = not errors
    return {
        "id": spec["source_filter"],
        "syncStateKey": spec["sync_state_key"],
        "epochStartedAt": epoch,
        "terminal": terminal_state,
        "authorityTailValid": tail_valid,
        "authorityValid": authority_valid,
        "gateSatisfied": authority_valid,
        "status": "satisfied" if authority_valid else "incomplete" if watermark else "unknown",
        "commitBatches": expected_commit_batches,
        "authoritativeReceiptCount": len(receipts),
        "lastCommitSha256": state.get("last_commit_sha256"),
        "lastCommitObservationEvidenceSha256": state.get(
            "last_commit_observation_evidence_sha256"
        ),
        "observationCount": state_observation_count,
        "completedAt": _iso(state.get("completed_at")),
        "stateEvidenceSha256": _sha256_json(state),
        "sourceEvents": _optional_number(state, "source_events"),
        "embeddedMarkets": _optional_number(state, "embedded_markets"),
        "classifiedResidualCount": state_residual_count,
        "reasonCounts": state_reason_counts,
        "residualAccountingSatisfied": residual_accounting_satisfied,
        "residualLedger": residual,
        "observationLedger": {
            **observation_ledger,
            "dbObservationCount": sum(db_observation_counts.values()),
            "receiptObservationCount": receipt_observation_count,
            "stateObservationCount": state_observation_count,
            "accountingSatisfied": observation_accounting_satisfied,
            "reconstructionScope": state.get("observation_reconstruction_scope"),
            "fullSourcePayloadReconstructable": False,
            "tailObservationCount": len(validated_tail_observations),
            "tailEvidenceShaVerified": tail_evidence_sha_verified,
            "invalidRelationshipShaLengthCount": (
                invalid_relationship_sha_length_count
                if spec["kind"] == "event"
                else None
            ),
            "fullObservationDigestRecomputed": False,
            "validationScope": "all_batch_counts_plus_tail_digest",
        },
        "sourceRequestPartition": (
            receipt_partitions[0] if receipt_partitions else None
        ),
        "terminalScope": "mutable_keyset_partition_traversal",
        "sourceSnapshotCutoffClaimed": False,
        "sameSourceFrozenSnapshotClaimed": False,
        "absoluteGammaHistoryCompletenessClaimed": False,
        "fullObservationDigestRecomputed": False,
        "validationScope": "all_batch_counts_plus_tail_digest",
        "openPrerequisiteEvidence": state.get("open_prerequisite_evidence"),
        "errors": sorted(set(errors)),
        "updatedAt": watermark.get("updatedAt"),
    }


def _closed_prerequisite_matches(
    open_stream: Mapping[str, Any],
    closed_stream: Mapping[str, Any],
    *,
    event_stream: bool,
) -> bool:
    evidence = closed_stream.get("openPrerequisiteEvidence")
    if not isinstance(evidence, Mapping):
        return False
    expected_key = (
        "gamma_event_history_backfill" if event_stream else "gamma_market_history_backfill"
    )
    claim_key = (
        "absolute_gamma_history_completeness_claimed"
        if event_stream
        else "canonical_union_completeness_claimed"
    )
    return bool(
        open_stream.get("gateSatisfied") is True
        and evidence.get("sync_state_key") == expected_key
        and evidence.get("source_filter") == "open"
        and _iso(evidence.get("epoch_started_at")) == open_stream.get("epochStartedAt")
        and _iso(evidence.get("completed_at")) == open_stream.get("completedAt")
        and evidence.get("last_commit_sha256") == open_stream.get("lastCommitSha256")
        and _optional_number(evidence, "observation_count")
        == open_stream.get("observationCount")
        and evidence.get("last_commit_observation_evidence_sha256")
        == open_stream.get("lastCommitObservationEvidenceSha256")
        and evidence.get("terminal") is True
        and evidence.get("state_sha256") == open_stream.get("stateEvidenceSha256")
        and evidence.get(claim_key) is False
        and (
            evidence.get("event_keyset_accounted") is True
            if event_stream
            else evidence.get("sequential_source_accounted") is True
        )
        and (
            (
                _optional_number(evidence, "source_events")
                == open_stream.get("sourceEvents")
                and _optional_number(evidence, "embedded_markets")
                == open_stream.get("embeddedMarkets")
            )
            if event_stream
            else True
        )
    )


def _market_event_composite_observation_gate(
    market_streams: list[Mapping[str, Any]],
    event_streams: list[Mapping[str, Any]],
    evidence: Mapping[str, Any],
) -> dict[str, Any]:
    composite = dict(evidence)
    expected_market_observations = sum(
        _number((stream.get("observationLedger") or {}).get("dbObservationCount"))
        for stream in market_streams
    )
    expected_event_observations = sum(
        _number((stream.get("observationLedger") or {}).get("dbObservationCount"))
        for stream in event_streams
    )
    event_count = composite.get("eventRelationshipObservationCount")
    exact_count = composite.get("exactCompositeJoinCount")
    conflict_count = composite.get("sharedIdentityConflictCount")
    event_only_count = composite.get("eventOnlyRelationshipCount")
    count_conservation_satisfied = bool(
        composite.get("marketObservationCount") == expected_market_observations
        and event_count == expected_event_observations
        and all(
            isinstance(value, int)
            for value in (
                event_count,
                exact_count,
                conflict_count,
                event_only_count,
                composite.get("marketOrderedIdentityCount"),
                composite.get("marketOnlyOrderedIdentityCount"),
            )
        )
        and event_count == exact_count + conflict_count + event_only_count
        and composite.get("marketOrderedIdentityCount")
        <= expected_market_observations
        and composite.get("marketOnlyOrderedIdentityCount")
        <= composite.get("marketOrderedIdentityCount")
    )
    streams_valid = all(
        stream.get("gateSatisfied") is True
        for stream in (*market_streams, *event_streams)
    )
    gate = bool(
        streams_valid
        and composite.get("availability") == "available"
        and count_conservation_satisfied
        and composite.get("sharedIdentityConflictCount") == 0
        and composite.get("marketIdentityAmbiguityCount") == 0
        and composite.get("eventIdentityAmbiguityCount") == 0
        and composite.get("invalidEventRelationshipShaLengthCount") == 0
    )
    composite_available = composite.get("availability") == "available"
    return {
        **composite,
        "gateSatisfied": gate,
        "countConservationSatisfied": count_conservation_satisfied,
        "claim": "operational-mutable-traversal-composite-authority",
        "eventRelationshipHashValidated": all(
            stream.get("gateSatisfied") is True
            and (stream.get("observationLedger") or {}).get(
                "tailEvidenceShaVerified"
            )
            is True
            for stream in event_streams
        ),
        "fullObservationDigestRecomputed": (
            composite.get("fullObservationDigestRecomputed") is True
        ),
        "validationScope": composite.get("validationScope")
        or "offline-checksum-pinned-composite-receipt",
        "sourceSnapshotCutoffClaimed": False,
        "sameSourceFrozenSnapshotClaimed": False,
        "absoluteGammaHistoryCompletenessClaimed": False,
        "detail": (
            "An offline checksum-pinned composite receipt reconciles the four current "
            "market/event epochs; the API only consumes that bounded receipt."
            if composite_available
            else "Cross-stream composite evidence is unavailable until an offline, "
            "checksum-pinned reconciliation receipt is materialized; the API cache path "
            "does not scan all observation epochs."
        ),
    }


_CANONICAL_CLASSIFICATIONS = ("resolved", "not_found", "invalid", "ambiguous", "retry")
_CANONICAL_CANDIDATE_CONTRACT_VERSION = 2
_CANONICAL_LEGACY_CANDIDATE_CONTRACT_VERSION = 1
_CANONICAL_RESTART_REASON = "candidate_definition_added_missing_question_id"
_CANONICAL_RESTART_MARKER_FIELDS = (
    "candidate_contract_restart_receipt_sha256",
    "superseded_cycle_id",
    "superseded_candidate_contract_version",
    "candidate_contract_restarted_at",
)


def _classification_counts(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    result: dict[str, int] = {}
    for classification in _CANONICAL_CLASSIFICATIONS:
        if classification not in value or value.get(classification) is None:
            return None
        result[classification] = _number(value.get(classification))
    return result


def _canonical_restart_initial_state(
    state: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    projection = dict(state)
    for field in (*_CANONICAL_RESTART_MARKER_FIELDS, "next_cycle_at"):
        projection.pop(field, None)
    audit_lo = _number(receipt.get("new_audit_lo"))
    audit_hi = _number(receipt.get("new_audit_hi"))
    projection.update(
        {
            "checkpoint": _number(receipt.get("new_checkpoint")),
            "status": "completed" if audit_hi < audit_lo else "running",
            "completed_at": (
                _iso(receipt.get("restarted_at")) if audit_hi < audit_lo else None
            ),
            "chunks_completed": 0,
            "candidates_scanned": 0,
            "classification_counts": {
                classification: 0
                for classification in _CANONICAL_CLASSIFICATIONS
            },
            "last_receipt_sha256": None,
        }
    )
    return projection


def _validate_canonical_cycle(
    *,
    watermark: Mapping[str, Any],
    metric: Mapping[str, Any],
    max_market_id: int,
) -> dict[str, Any]:
    state = _state_mapping(watermark)
    errors: list[str] = []
    audit_lo = _optional_number(state, "audit_lo")
    audit_hi = _optional_number(state, "audit_hi")
    checkpoint = _optional_number(state, "checkpoint")
    last_block = _optional_number(watermark, "lastBlock")
    cycle_id = str(state.get("cycle_id") or "").strip()
    state_counts = _classification_counts(state.get("classification_counts"))
    ledger_counts = _classification_counts(metric.get("classificationCounts"))
    state_candidate_contract_version = _optional_number(
        state,
        "candidate_contract_version",
    )
    state_candidate_contract_valid = bool(
        state_candidate_contract_version == _CANONICAL_CANDIDATE_CONTRACT_VERSION
    )
    if not state_candidate_contract_valid:
        errors.append("candidate-contract-state-version-mismatch")
    range_terminal = bool(
        str(state.get("status") or "").lower() in {"complete", "completed"}
        and audit_lo == 1
        and audit_hi is not None
        and checkpoint == audit_hi
        and last_block == checkpoint
        and audit_hi >= max_market_id
        and cycle_id
        and state.get("completed_at")
    )
    if not range_terminal:
        errors.append("range-state-not-terminal")

    receipt_rows = metric.get("receiptRows")
    if not isinstance(receipt_rows, list):
        receipt_rows = []
    receipts: list[dict[str, Any]] = []
    for row in receipt_rows:
        if not isinstance(row, Mapping):
            errors.append("receipt-row-invalid")
            continue
        record = _decode_receipt(row.get("record_json"))
        if record is None:
            errors.append("receipt-json-invalid")
            continue
        core = {
            key: value
            for key, value in record.items()
            if key not in {"receipt_sha256", "event", "run_id"}
        }
        if (
            record.get("schema_version")
            != "market-canonical-identity-reconciliation-receipt-v1"
            or str(record.get("cycle_id") or "") != cycle_id
            or record.get("receipt_sha256") != _sha256_json(core)
            or record.get("receipt_sha256") != row.get("receipt_sha256")
            or record.get("post_upsert_verified") is not True
            or _optional_number(record, "audit_lo") != audit_lo
            or _optional_number(record, "audit_hi") != audit_hi
        ):
            errors.append("receipt-invalid")
        receipts.append(record)
    receipts.sort(key=lambda receipt: _number(receipt.get("batch_number")))

    receipt_counts = {classification: 0 for classification in _CANONICAL_CLASSIFICATIONS}
    receipt_candidate_contract_versions: list[int | None] = []
    expected_start = (audit_lo - 1) if audit_lo is not None else None
    for expected_batch, receipt in enumerate(receipts, start=1):
        receipt_batch = _optional_number(receipt, "batch_number")
        start_checkpoint = _optional_number(receipt, "start_checkpoint")
        end_checkpoint = _optional_number(receipt, "end_checkpoint")
        counts = _classification_counts(receipt.get("classification_counts"))
        market_ids = receipt.get("market_ids")
        receipt_candidate_contract_version = _optional_number(
            receipt,
            "candidate_contract_version",
        )
        receipt_candidate_contract_versions.append(
            receipt_candidate_contract_version
        )
        if (
            receipt_candidate_contract_version
            != _CANONICAL_CANDIDATE_CONTRACT_VERSION
        ):
            errors.append(
                f"candidate-contract-receipt-version-mismatch-batch-{expected_batch}"
            )
        if (
            receipt_batch != expected_batch
            or start_checkpoint != expected_start
            or end_checkpoint is None
            or start_checkpoint is None
            or end_checkpoint < start_checkpoint
            or counts is None
            or not isinstance(market_ids, list)
            or (counts is not None and sum(counts.values()) != len(market_ids))
        ):
            errors.append(f"receipt-chain-invalid-batch-{expected_batch}")
        if counts is not None:
            for classification, count in counts.items():
                receipt_counts[classification] += count
        expected_start = end_checkpoint

    receipt_candidate_contracts_valid = bool(receipts) and all(
        version == _CANONICAL_CANDIDATE_CONTRACT_VERSION
        for version in receipt_candidate_contract_versions
    )

    tail = receipts[-1] if receipts else {}
    receipt_tail_valid = bool(
        receipts
        and tail.get("terminal") is True
        and _optional_number(tail, "end_checkpoint") == checkpoint
        and tail.get("receipt_sha256") == state.get("last_receipt_sha256")
        and _is_sha256(state.get("last_receipt_sha256"))
    )
    if any(receipt.get("terminal") is True for receipt in receipts[:-1]):
        receipt_tail_valid = False
    if not receipt_tail_valid:
        errors.append("receipt-tail-state-mismatch")

    counts_reconciled = bool(
        state_counts is not None
        and ledger_counts is not None
        and state_counts == ledger_counts == receipt_counts
        and metric.get("classifiedCount") == sum(state_counts.values())
    )
    if not counts_reconciled:
        errors.append("classification-counts-mismatch")

    restart_rows = metric.get("restartReceiptRows")
    if not isinstance(restart_rows, list):
        restart_rows = []
    restart_marker_sha256 = str(
        state.get("candidate_contract_restart_receipt_sha256") or ""
    ).strip()
    state_superseded_cycle_id = str(state.get("superseded_cycle_id") or "").strip()
    state_superseded_contract_version = _optional_number(
        state,
        "superseded_candidate_contract_version",
    )
    state_restarted_at = _iso(state.get("candidate_contract_restarted_at"))
    marker_values = (
        restart_marker_sha256,
        state_superseded_cycle_id,
        state_superseded_contract_version,
        state_restarted_at,
    )
    marker_present = any(value not in (None, "") for value in marker_values)
    relevant_restart_rows: list[tuple[Mapping[str, Any], dict[str, Any] | None]] = []
    for row in restart_rows:
        if not isinstance(row, Mapping):
            continue
        record = _decode_receipt(row.get("record_json"))
        if (
            str(row.get("receipt_sha256") or "").strip()
            == restart_marker_sha256
            and restart_marker_sha256
        ) or (
            record is not None
            and str(record.get("new_cycle_id") or "").strip() == cycle_id
        ):
            relevant_restart_rows.append((row, record))

    restart_receipt_required = bool(marker_present or relevant_restart_rows)
    restart_errors: list[str] = []
    restart_receipt_valid = not restart_receipt_required
    restart_receipt_record: dict[str, Any] | None = None
    if restart_receipt_required:
        if (
            not _is_sha256(restart_marker_sha256)
            or not state_superseded_cycle_id
            or state_superseded_cycle_id == cycle_id
            or state_superseded_contract_version
            != _CANONICAL_LEGACY_CANDIDATE_CONTRACT_VERSION
            or _parse_datetime(state_restarted_at) is None
        ):
            restart_errors.append("candidate-contract-restart-state-marker-invalid")
        if len(relevant_restart_rows) != 1:
            restart_errors.append("candidate-contract-restart-receipt-not-unique")
        else:
            row, record = relevant_restart_rows[0]
            restart_receipt_record = record
            if record is None:
                restart_errors.append("candidate-contract-restart-receipt-json-invalid")
            else:
                checksum_core = {
                    key: value
                    for key, value in record.items()
                    if key not in {"receipt_sha256", "event"}
                }
                initial_state = _canonical_restart_initial_state(state, record)
                restart_receipt_valid = bool(
                    record.get("schema_version")
                    == "market-canonical-identity-reconciliation-receipt-v1"
                    and record.get("receipt_kind")
                    == "candidate_contract_superseded"
                    and str(row.get("event") or "")
                    == "candidate_contract_superseded"
                    and record.get("receipt_sha256") == _sha256_json(checksum_core)
                    and record.get("receipt_sha256") == row.get("receipt_sha256")
                    and record.get("receipt_sha256") == restart_marker_sha256
                    and str(record.get("cycle_id") or "").strip()
                    == str(row.get("cycle_id") or "").strip()
                    and str(record.get("superseded_cycle_id") or "").strip()
                    == state_superseded_cycle_id
                    == str(row.get("cycle_id") or "").strip()
                    and _optional_number(record, "candidate_contract_version")
                    == state_superseded_contract_version
                    == _CANONICAL_LEGACY_CANDIDATE_CONTRACT_VERSION
                    and _optional_number(
                        record,
                        "new_candidate_contract_version",
                    )
                    == state_candidate_contract_version
                    == _CANONICAL_CANDIDATE_CONTRACT_VERSION
                    and str(record.get("new_cycle_id") or "").strip() == cycle_id
                    and _optional_number(record, "new_audit_lo") == audit_lo
                    and _optional_number(record, "new_audit_hi") == audit_hi
                    and _optional_number(record, "new_checkpoint")
                    == ((audit_lo - 1) if audit_lo is not None else None)
                    and _iso(record.get("restarted_at")) == state_restarted_at
                    and state_restarted_at == _iso(state.get("cycle_started_at"))
                    and record.get("restart_reason") == _CANONICAL_RESTART_REASON
                    and _is_sha256(record.get("superseded_state_sha256"))
                    and record.get("new_state_sha256")
                    == _sha256_json(initial_state)
                )
                if not restart_receipt_valid:
                    restart_errors.append(
                        "candidate-contract-restart-receipt-invalid"
                    )
        if restart_errors:
            restart_receipt_valid = False
        errors.extend(restart_errors)

    gate = bool(
        range_terminal
        and state_candidate_contract_valid
        and receipt_candidate_contracts_valid
        and restart_receipt_valid
        and metric.get("availability") == "available"
        and metric.get("receiptTablePresent") is True
        and receipt_tail_valid
        and counts_reconciled
        and state_counts is not None
        and state_counts.get("retry") == 0
        and not errors
    )
    return {
        "gateSatisfied": gate,
        "rangeTerminal": range_terminal,
        "rangeCoversCurrentMarketMax": bool(
            audit_hi is not None and audit_hi >= max_market_id
        ),
        "cycleId": cycle_id or None,
        "candidateContractVersion": state_candidate_contract_version,
        "candidateContractVersionValid": state_candidate_contract_valid,
        "receiptCandidateContractVersions": receipt_candidate_contract_versions,
        "receiptCandidateContractsValid": receipt_candidate_contracts_valid,
        "restartReceiptRequired": restart_receipt_required,
        "restartReceiptValid": restart_receipt_valid,
        "restartReceiptSha256": (
            restart_receipt_record.get("receipt_sha256")
            if restart_receipt_record
            else None
        ),
        "supersededCycleId": state_superseded_cycle_id or None,
        "receiptTailValid": receipt_tail_valid,
        "receiptCount": len(receipts),
        "classificationCountsReconciled": counts_reconciled,
        "stateClassificationCounts": state_counts,
        "receiptClassificationCounts": receipt_counts,
        "errors": sorted(set(errors)),
    }


_SOURCE_SEMANTICS_STATE_SCHEMA = "market-source-semantics-reconciliation-v1"
_SOURCE_SEMANTICS_RECEIPT_SCHEMA = (
    "market-source-semantics-reconciliation-receipt-v1"
)
_SOURCE_SEMANTICS_LEDGER_SCHEMA = "market-source-semantics-ledger-v1"
_SOURCE_SEMANTICS_CLASSIFICATIONS = (
    "resolved",
    "source_clob_absent",
    "source_not_found",
    "source_identity_mismatch",
    "ownership_conflict",
    "superseded_duplicate",
    "retry",
)
_SOURCE_SEMANTICS_TERMINAL_RESIDUAL_CLASSIFICATIONS = (
    "source_clob_absent",
    "source_not_found",
    "source_identity_mismatch",
    "ownership_conflict",
    "superseded_duplicate",
)


def _source_semantics_counts(value: Any) -> dict[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    if set(value) != set(_SOURCE_SEMANTICS_CLASSIFICATIONS):
        return None
    result: dict[str, int] = {}
    for classification in _SOURCE_SEMANTICS_CLASSIFICATIONS:
        count = _strict_nonnegative_int(value.get(classification))
        if count is None:
            return None
        result[classification] = count
    return result


def _validate_source_semantics_cycle(
    *,
    watermark: Mapping[str, Any],
    metric: Mapping[str, Any],
    max_market_id: int,
) -> dict[str, Any]:
    state = _state_mapping(watermark)
    errors: list[str] = []
    cycle_id = str(state.get("cycle_id") or "").strip()
    audit_lo = _optional_number(state, "audit_lo")
    audit_hi = _optional_number(state, "audit_hi")
    checkpoint = _optional_number(state, "checkpoint")
    state_batch_number = _optional_number(state, "batch_number")
    state_counts = _source_semantics_counts(state.get("classification_counts"))
    ledger_counts = _source_semantics_counts(metric.get("classificationCounts"))
    state_schema_valid = state.get("schema_version") == _SOURCE_SEMANTICS_STATE_SCHEMA
    if not state_schema_valid:
        errors.append("state-schema-invalid")

    range_terminal = bool(
        str(state.get("status") or "").strip().lower() == "complete"
        and cycle_id
        and audit_lo is not None
        and audit_hi is not None
        and checkpoint is not None
        and checkpoint >= audit_hi
        and _optional_number(watermark, "lastBlock") == checkpoint
        and audit_hi >= max_market_id
        and state.get("completed_at")
    )
    if not range_terminal:
        errors.append("range-state-not-terminal")

    receipt_rows = metric.get("receiptRows")
    if not isinstance(receipt_rows, list):
        receipt_rows = []
    receipts: list[dict[str, Any]] = []
    expected_previous: str | None = None
    expected_checkpoint = (audit_lo - 1) if audit_lo is not None else None
    for expected_batch, row in enumerate(receipt_rows, start=1):
        if not isinstance(row, Mapping):
            errors.append(f"receipt-row-invalid-batch-{expected_batch}")
            continue
        receipt = _decode_receipt(row.get("record_json"))
        if receipt is None:
            errors.append(f"receipt-json-invalid-batch-{expected_batch}")
            continue
        claimed_sha = str(receipt.get("receipt_sha256") or "")
        checksum_core = dict(receipt)
        checksum_core.pop("receipt_sha256", None)
        counts = _source_semantics_counts(receipt.get("classification_counts"))
        attempted_ids = receipt.get("attempted_market_ids")
        attempted_count = _strict_nonnegative_int(receipt.get("attempted_count"))
        checkpoint_before = _optional_number(receipt, "checkpoint_before")
        checkpoint_after = _optional_number(receipt, "checkpoint_after")
        batch_kind = str(receipt.get("batch_kind") or "").strip()
        receipt_valid = bool(
            receipt.get("schema_version") == _SOURCE_SEMANTICS_RECEIPT_SCHEMA
            and receipt.get("ledger_schema_version")
            == _SOURCE_SEMANTICS_LEDGER_SCHEMA
            and str(receipt.get("cycle_id") or "") == cycle_id
            and _optional_number(receipt, "batch_number") == expected_batch
            and _optional_number(row, "batch_number") == expected_batch
            and claimed_sha == _sha256_json(checksum_core)
            and claimed_sha == str(row.get("receipt_sha256") or "")
            and (receipt.get("previous_receipt_sha256") or None)
            == expected_previous
            and (row.get("previous_receipt_sha256") or None)
            == expected_previous
            and _optional_number(receipt, "audit_lo") == audit_lo
            and _optional_number(receipt, "audit_hi") == audit_hi
            and checkpoint_before == expected_checkpoint
            and checkpoint_after is not None
            and checkpoint_before is not None
            and checkpoint_after >= checkpoint_before
            and (batch_kind != "retry" or checkpoint_after == checkpoint_before)
            and isinstance(attempted_ids, list)
            and attempted_count == len(attempted_ids)
            and counts is not None
            and attempted_count == sum(counts.values())
            and receipt.get("classification_conserved") is True
            and receipt.get("post_update_verified") is True
        )
        if not receipt_valid:
            errors.append(f"receipt-invalid-batch-{expected_batch}")
        expected_previous = claimed_sha
        expected_checkpoint = checkpoint_after
        receipts.append(receipt)

    receipt_tail_valid = bool(
        state_batch_number is not None
        and state_batch_number == len(receipts)
        and (
            (
                receipts
                and expected_previous == state.get("last_receipt_sha256")
                and expected_checkpoint == checkpoint
                and _is_sha256(state.get("last_receipt_sha256"))
            )
            or (
                not receipts
                and state_batch_number == 0
                and state.get("last_receipt_sha256") in (None, "")
                and audit_lo is not None
                and audit_hi is not None
                and audit_hi < audit_lo
            )
        )
    )
    if not receipt_tail_valid:
        errors.append("receipt-tail-state-mismatch")

    receipt_count = _strict_nonnegative_int(metric.get("receiptCount"))
    if receipt_count is None or receipt_count != len(receipts):
        errors.append("receipt-count-mismatch")

    classified_count = _strict_nonnegative_int(metric.get("classifiedCount"))
    invalid_classification_count = _strict_nonnegative_int(
        metric.get("invalidClassificationCount")
    )
    orphan_receipt_reference_count = _strict_nonnegative_int(
        metric.get("orphanReceiptReferenceCount")
    )
    invalid_receipt_reference_count = _strict_nonnegative_int(
        metric.get("invalidReceiptReferenceCount")
    )
    ledger_receipts_valid = bool(
        invalid_classification_count == 0
        and orphan_receipt_reference_count == 0
        and invalid_receipt_reference_count == 0
    )
    if not ledger_receipts_valid:
        errors.append("ledger-receipt-conservation-mismatch")

    counts_reconciled = bool(
        state_counts is not None
        and ledger_counts is not None
        and state_counts == ledger_counts
        and _optional_number(state, "candidate_count") == sum(state_counts.values())
        and classified_count == sum(state_counts.values())
    )
    if not counts_reconciled:
        errors.append("classification-counts-mismatch")

    classification_gate = bool(
        range_terminal
        and state_schema_valid
        and metric.get("availability") == "available"
        and metric.get("ledgerTablePresent") is True
        and metric.get("receiptTablePresent") is True
        and receipt_tail_valid
        and ledger_receipts_valid
        and counts_reconciled
        and state_counts is not None
        and state_counts.get("retry") == 0
        and not errors
    )
    terminal_residual_count = (
        sum(
            state_counts[classification]
            for classification in _SOURCE_SEMANTICS_TERMINAL_RESIDUAL_CLASSIFICATIONS
        )
        if state_counts is not None
        else None
    )
    gate = bool(classification_gate and terminal_residual_count == 0)
    return {
        "gateSatisfied": gate,
        "classificationGateSatisfied": classification_gate,
        "rangeTerminal": range_terminal,
        "rangeCoversCurrentMarketMax": bool(
            audit_hi is not None and audit_hi >= max_market_id
        ),
        "cycleId": cycle_id or None,
        "auditLo": audit_lo,
        "auditHi": audit_hi,
        "checkpoint": checkpoint,
        "receiptCount": len(receipts),
        "receiptTailValid": receipt_tail_valid,
        "ledgerReceiptConserved": ledger_receipts_valid,
        "classificationCountsReconciled": counts_reconciled,
        "classificationCounts": state_counts,
        "terminalResidualCount": terminal_residual_count,
        "retryCount": state_counts.get("retry") if state_counts else None,
        "errors": sorted(set(errors)),
    }


def _history_composite_evidence(
    dependencies: MarketQualityDependencies,
    watermarks_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    unavailable = {
        "availability": "unavailable",
        "unavailableReason": (
            "offline-composite-reconciliation-not-materialized"
        ),
        "offlineCompositeReceiptRequired": True,
        "fullObservationDigestRecomputed": False,
        "validationScope": "per-stream-all-batch-counts-plus-tail-digest",
    }
    # Never rebuild the cross-stream join in the API request/cache path.  The
    # offline reconciler scans the four exact epochs under REPEATABLE READ and
    # persists one bounded, checksum-pinned receipt instead.
    if not _optional_table_exists(dependencies, _HISTORY_COMPOSITE_TABLE):
        return unavailable

    rows = _query_all(
        dependencies,
        f"""
        SELECT receipt_sha256, epoch_set_sha256, receipt_json, status,
               created_at, manifest_tail_sha256, manifest_written_at
        FROM {_HISTORY_COMPOSITE_TABLE}
        WHERE manifest_written_at IS NOT NULL
        ORDER BY created_at DESC, receipt_sha256 DESC
        LIMIT 1
        """,
    )
    if not rows:
        return unavailable

    row = rows[0]
    receipt = _decode_receipt(row.get("receipt_json"))
    errors: list[str] = []
    if receipt is None:
        errors.append("receipt-json-invalid")
        receipt = {}
    claimed_sha = str(receipt.get("receipt_sha256") or "")
    checksum_core = dict(receipt)
    checksum_core.pop("receipt_sha256", None)
    if (
        receipt.get("schema_version") != _HISTORY_COMPOSITE_SCHEMA
        or receipt.get("status") != _HISTORY_COMPOSITE_STATUS
        or claimed_sha != _sha256_json(checksum_core)
        or claimed_sha != str(row.get("receipt_sha256") or "")
        or receipt.get("epoch_set_sha256")
        != str(row.get("epoch_set_sha256") or "")
        or receipt.get("status") != str(row.get("status") or "")
        or claimed_sha != str(row.get("manifest_tail_sha256") or "")
        or not row.get("manifest_written_at")
    ):
        errors.append("receipt-db-manifest-checksum-invalid")

    if (
        receipt.get("repeatable_read_snapshot") is not True
        or receipt.get("isolation_level") != "repeatable_read"
        or receipt.get("terminal_scope")
        != "four_mutable_keyset_partition_traversal_epochs"
        or receipt.get("claim")
        != "operational_mutable_traversal_epochs_reconciled"
        or receipt.get("source_snapshot_cutoff_claimed") is not False
        or receipt.get("same_source_frozen_snapshot_claimed") is not False
        or receipt.get("absolute_gamma_history_completeness_claimed") is not False
        or receipt.get("exact_shared_identity_join_recomputed") is not True
    ):
        errors.append("receipt-scope-or-isolation-invalid")

    raw_pins = receipt.get("stream_pins")
    pins = (
        [dict(pin) for pin in raw_pins if isinstance(pin, Mapping)]
        if isinstance(raw_pins, list)
        else []
    )
    expected_stream_ids = [
        "market-open",
        "market-closed",
        "event-open",
        "event-closed",
    ]
    if (
        len(pins) != 4
        or [pin.get("stream_id") for pin in pins] != expected_stream_ids
        or receipt.get("stream_pins_sha256") != _sha256_json(pins)
    ):
        errors.append("stream-pin-set-invalid")
    pin_by_id = {str(pin.get("stream_id") or ""): pin for pin in pins}
    watermark_by_stream_id = {
        "market-open": "gamma-history-open",
        "market-closed": "gamma-history-closed",
        "event-open": "gamma-event-history-open",
        "event-closed": "gamma-event-history-closed",
    }
    expected_sync_keys = {
        "market-open": "gamma_market_history_backfill",
        "market-closed": "gamma_market_history_backfill_closed",
        "event-open": "gamma_event_history_backfill",
        "event-closed": "gamma_event_history_backfill_closed",
    }
    expected_epoch_set: list[list[Any]] = []
    for stream_id in expected_stream_ids:
        pin = pin_by_id.get(stream_id, {})
        watermark = watermarks_by_id.get(watermark_by_stream_id[stream_id], {})
        state = _state_mapping(watermark)
        expected_kind, expected_filter = stream_id.split("-", 1)
        if (
            pin.get("kind") != expected_kind
            or pin.get("source_filter") != expected_filter
            or pin.get("sync_state_key") != expected_sync_keys[stream_id]
            or pin.get("terminal") is not True
            or pin.get("source_verified") is not True
            or pin.get("source_snapshot_cutoff_claimed") is not False
            or pin.get("same_source_frozen_snapshot_claimed") is not False
            or pin.get("absolute_gamma_history_completeness_claimed") is not False
            or str(state.get("status") or "").strip().lower() != "complete"
            or state.get("source_verified") is not True
            or state.get("after_cursor") not in (None, "")
            or _iso(pin.get("epoch_started_at"))
            != _iso(state.get("epoch_started_at"))
            or _iso(pin.get("completed_at")) != _iso(state.get("completed_at"))
            or pin.get("authority_tail_sha256")
            != state.get("last_commit_sha256")
            or pin.get("source_manifest_tail_sha256")
            != pin.get("authority_tail_sha256")
            or _optional_number(pin, "commit_batches")
            != _optional_number(state, "commit_batches")
            or _optional_number(pin, "observation_count")
            != _optional_number(state, "observation_count")
            or pin.get("state_sha256") != _sha256_json(state)
            or not _is_sha256(pin.get("authority_chain_sha256"))
            or not _is_sha256(pin.get("source_manifest_file_sha256"))
            or not _is_sha256(pin.get("residual_evidence_sha256"))
        ):
            errors.append(f"stream-pin-current-state-mismatch-{stream_id}")
        expected_epoch_set.append(
            [
                stream_id,
                pin.get("epoch_started_at"),
                pin.get("authority_tail_sha256"),
                pin.get("state_sha256"),
            ]
        )
    if receipt.get("epoch_set_sha256") != _sha256_json(expected_epoch_set):
        errors.append("epoch-set-checksum-invalid")

    counts = receipt.get("counts")
    counts = dict(counts) if isinstance(counts, Mapping) else {}
    count_fields = (
        "market_observation_count",
        "market_ordered_identity_count",
        "event_relationship_observation_count",
        "exact_composite_join_count",
        "exact_shared_ordered_identity_count",
        "shared_identity_conflict_count",
        "event_only_relationship_count",
        "market_only_ordered_identity_count",
        "market_identity_ambiguity_count",
        "event_identity_ambiguity_count",
        "invalid_event_relationship_sha_length_count",
    )
    if any(_strict_nonnegative_int(counts.get(field)) is None for field in count_fields):
        errors.append("composite-count-shape-invalid")
    event_conserved = bool(
        _strict_nonnegative_int(counts.get("event_relationship_observation_count"))
        is not None
        and counts.get("event_relationship_observation_count")
        == _number(counts.get("exact_composite_join_count"))
        + _number(counts.get("shared_identity_conflict_count"))
        + _number(counts.get("event_only_relationship_count"))
    )
    market_conserved = bool(
        _strict_nonnegative_int(counts.get("market_ordered_identity_count"))
        is not None
        and counts.get("market_ordered_identity_count")
        == _number(counts.get("exact_shared_ordered_identity_count"))
        + _number(counts.get("market_only_ordered_identity_count"))
    )
    if (
        counts.get("event_count_conservation_satisfied") is not True
        or counts.get("market_identity_count_conservation_satisfied") is not True
        or counts.get("count_conservation_satisfied") is not True
        or not event_conserved
        or not market_conserved
    ):
        errors.append("composite-count-conservation-invalid")

    digests = receipt.get("observation_digests")
    digests = dict(digests) if isinstance(digests, Mapping) else {}
    if (
        digests.get("digest_algorithm")
        != "sha256-length-prefixed-canonical-json-v1"
        or digests.get("full_observation_digest_recomputed") is not True
        or _optional_number(digests, "market_observation_count")
        != _optional_number(counts, "market_observation_count")
        or _optional_number(digests, "event_relationship_observation_count")
        != _optional_number(counts, "event_relationship_observation_count")
        or not _is_sha256(digests.get("market_observation_sha256"))
        or not _is_sha256(digests.get("event_relationship_observation_sha256"))
    ):
        errors.append("full-observation-digest-invalid")

    if errors:
        return {
            **unavailable,
            "unavailableReason": "offline-composite-receipt-invalid",
            "receiptSha256": claimed_sha or None,
            "errors": sorted(set(errors)),
        }
    return {
        "availability": "available",
        "unavailableReason": None,
        "offlineCompositeReceiptRequired": True,
        "receiptSha256": claimed_sha,
        "epochSetSha256": receipt.get("epoch_set_sha256"),
        "materializedAt": _iso(row.get("manifest_written_at")),
        "streamPins": pins,
        "marketObservationCount": counts["market_observation_count"],
        "marketOrderedIdentityCount": counts["market_ordered_identity_count"],
        "eventRelationshipObservationCount": counts[
            "event_relationship_observation_count"
        ],
        "exactCompositeJoinCount": counts["exact_composite_join_count"],
        "exactSharedOrderedIdentityCount": counts[
            "exact_shared_ordered_identity_count"
        ],
        "sharedIdentityConflictCount": counts[
            "shared_identity_conflict_count"
        ],
        "eventOnlyRelationshipCount": counts["event_only_relationship_count"],
        "marketOnlyOrderedIdentityCount": counts[
            "market_only_ordered_identity_count"
        ],
        "marketIdentityAmbiguityCount": counts[
            "market_identity_ambiguity_count"
        ],
        "eventIdentityAmbiguityCount": counts[
            "event_identity_ambiguity_count"
        ],
        "invalidEventRelationshipShaLengthCount": counts[
            "invalid_event_relationship_sha_length_count"
        ],
        "fullObservationDigestRecomputed": True,
        "observationDigests": digests,
        "validationScope": (
            "offline-repeatable-read-full-four-epoch-digests-exact-identity-join"
        ),
        "sourceSnapshotCutoffClaimed": False,
        "sameSourceFrozenSnapshotClaimed": False,
        "absoluteGammaHistoryCompletenessClaimed": False,
    }


def _history_ledger_metrics(
    dependencies: MarketQualityDependencies,
    watermarks: list[dict[str, Any]],
    market_metrics: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    watermarks_by_id = {str(item.get("id") or ""): item for item in watermarks}
    category_validation = _canonical_metadata_audit(market_metrics)

    token_present = dependencies.table_exists("market_token_backfill_failures")
    token_row = (
        _query_one(
            dependencies,
            """
            SELECT
                COUNT(*) AS classified_count,
                SUM(CASE WHEN status = 'terminal' THEN 1 ELSE 0 END) AS terminal_count,
                SUM(CASE WHEN status = 'retry' THEN 1 ELSE 0 END) AS retry_count,
                MAX(last_seen_at) AS updated_at
            FROM market_token_backfill_failures
            """,
        )
        if token_present
        else {}
    )

    placeholder_present = dependencies.table_exists("placeholder_market_reconciliation")
    placeholder_row = (
        _query_one(
            dependencies,
            """
            SELECT
                COUNT(*) AS classified_count,
                SUM(CASE WHEN classification = 'exact_unique_target' THEN 1 ELSE 0 END) AS exact_count,
                SUM(CASE WHEN classification = 'already_superseded' THEN 1 ELSE 0 END) AS superseded_count,
                SUM(CASE WHEN classification = 'ambiguous' THEN 1 ELSE 0 END) AS ambiguous_count,
                SUM(CASE WHEN classification = 'unresolved' THEN 1 ELSE 0 END) AS unresolved_count,
                MAX(last_classified_at) AS updated_at
            FROM placeholder_market_reconciliation
            """,
        )
        if placeholder_present
        else {}
    )

    history_stream_evidence = {
        str(spec["watermark_id"]): _history_stream_evidence(
            dependencies,
            watermarks_by_id.get(str(spec["watermark_id"]), {}),
            spec,
        )
        for spec in _HISTORY_STREAM_SPECS
    }
    history_composite_evidence = _history_composite_evidence(
        dependencies,
        watermarks_by_id,
    )

    canonical_identity_present = _optional_table_exists(
        dependencies,
        "market_canonical_identity_reconciliation",
    )
    canonical_watermark = watermarks_by_id.get("canonical-identity-reconciliation", {})
    canonical_state = _state_mapping(canonical_watermark)
    canonical_cycle_id = str(canonical_state.get("cycle_id") or "").strip()
    canonical_identity_row, canonical_identity_query_available = (
        _query_one_with_availability(
            dependencies,
            """
            SELECT
                COUNT(*) AS classified_count,
                SUM(CASE WHEN classification = 'resolved' THEN 1 ELSE 0 END) AS resolved_count,
                SUM(CASE WHEN classification = 'not_found' THEN 1 ELSE 0 END) AS not_found_count,
                SUM(CASE WHEN classification = 'invalid' THEN 1 ELSE 0 END) AS invalid_count,
                SUM(CASE WHEN classification = 'ambiguous' THEN 1 ELSE 0 END) AS ambiguous_count,
                SUM(CASE WHEN classification = 'retry' THEN 1 ELSE 0 END) AS retry_count,
                MAX(last_attempted_at) AS updated_at
            FROM market_canonical_identity_reconciliation
            WHERE cycle_id = ?
            """,
            (canonical_cycle_id,),
        )
        if canonical_identity_present and canonical_cycle_id
        else ({}, False)
    )
    canonical_receipt_present = _optional_table_exists(
        dependencies,
        "market_canonical_identity_reconciliation_receipts",
    )
    canonical_receipt_rows = (
        _query_all(
            dependencies,
            """
            SELECT receipt_sha256, cycle_id, event, record_json, committed_at
            FROM market_canonical_identity_reconciliation_receipts
            WHERE cycle_id = ?
            ORDER BY committed_at, receipt_sha256
            """,
            (canonical_cycle_id,),
        )
        if canonical_receipt_present and canonical_cycle_id
        else []
    )
    canonical_restart_receipt_rows = (
        _query_all(
            dependencies,
            """
            SELECT receipt_sha256, cycle_id, event, record_json, committed_at
            FROM market_canonical_identity_reconciliation_receipts
            WHERE event = 'candidate_contract_superseded'
            ORDER BY committed_at, receipt_sha256
            """,
        )
        if canonical_receipt_present
        else []
    )

    source_semantics_watermark = watermarks_by_id.get(
        "source-semantics-reconciliation",
        {},
    )
    source_semantics_state = _state_mapping(source_semantics_watermark)
    source_semantics_cycle_id = str(
        source_semantics_state.get("cycle_id") or ""
    ).strip()
    source_semantics_ledger_present = _optional_table_exists(
        dependencies,
        "market_source_semantics_reconciliation",
    )
    source_semantics_receipt_present = _optional_table_exists(
        dependencies,
        "market_source_semantics_reconciliation_receipts",
    )
    source_semantics_ledger_aggregate, source_semantics_aggregate_available = (
        _query_one_with_availability(
            dependencies,
            """
            SELECT
                COUNT(*) AS classified_count,
                COALESCE(SUM(CASE WHEN l.classification = 'resolved' THEN 1 ELSE 0 END), 0)
                    AS resolved_count,
                COALESCE(SUM(CASE WHEN l.classification = 'source_clob_absent' THEN 1 ELSE 0 END), 0)
                    AS source_clob_absent_count,
                COALESCE(SUM(CASE WHEN l.classification = 'source_not_found' THEN 1 ELSE 0 END), 0)
                    AS source_not_found_count,
                COALESCE(SUM(CASE WHEN l.classification = 'source_identity_mismatch' THEN 1 ELSE 0 END), 0)
                    AS source_identity_mismatch_count,
                COALESCE(SUM(CASE WHEN l.classification = 'ownership_conflict' THEN 1 ELSE 0 END), 0)
                    AS ownership_conflict_count,
                COALESCE(SUM(CASE WHEN l.classification = 'superseded_duplicate' THEN 1 ELSE 0 END), 0)
                    AS superseded_duplicate_count,
                COALESCE(SUM(CASE WHEN l.classification = 'retry' THEN 1 ELSE 0 END), 0)
                    AS retry_count,
                COALESCE(SUM(CASE WHEN l.classification NOT IN (
                    'resolved', 'source_clob_absent', 'source_not_found',
                    'source_identity_mismatch', 'ownership_conflict',
                    'superseded_duplicate', 'retry'
                ) OR l.classification IS NULL THEN 1 ELSE 0 END), 0)
                    AS invalid_classification_count,
                COALESCE(SUM(CASE WHEN r.receipt_sha256 IS NULL THEN 1 ELSE 0 END), 0)
                    AS orphan_receipt_reference_count,
                COALESCE(SUM(CASE WHEN
                    l.receipt_sha256 IS NULL
                    OR LENGTH(TRIM(l.receipt_sha256)) <> 64
                    OR r.receipt_sha256 IS NULL
                    OR COALESCE(r.cycle_id, '') <> l.cycle_id
                    THEN 1 ELSE 0 END), 0)
                    AS invalid_receipt_reference_count,
                COUNT(DISTINCT l.receipt_sha256)
                    AS distinct_receipt_reference_count,
                MAX(l.last_attempted_at) AS updated_at
            FROM market_source_semantics_reconciliation l
            LEFT JOIN market_source_semantics_reconciliation_receipts r
              ON r.receipt_sha256 = l.receipt_sha256
            WHERE l.cycle_id = ?
            """,
            (source_semantics_cycle_id,),
        )
        if source_semantics_ledger_present
        and source_semantics_receipt_present
        and source_semantics_cycle_id
        else ({}, False)
    )
    source_semantics_receipt_rows = (
        _query_all(
            dependencies,
            """
            SELECT receipt_sha256, cycle_id, batch_number,
                   previous_receipt_sha256, record_json, committed_at
            FROM market_source_semantics_reconciliation_receipts
            WHERE cycle_id = ?
            ORDER BY batch_number
            """,
            (source_semantics_cycle_id,),
        )
        if source_semantics_receipt_present and source_semantics_cycle_id
        else []
    )
    source_semantics_counts = {
        classification: _optional_number(
            source_semantics_ledger_aggregate,
            f"{classification}_count",
        )
        for classification in _SOURCE_SEMANTICS_CLASSIFICATIONS
    }

    return {
        "gamma-history-evidence": history_stream_evidence,
        "gamma-history-composite-evidence": history_composite_evidence,
        "category-tags": {
            **category_validation,
            "updatedAt": watermarks_by_id.get("market_sync", {}).get("updatedAt"),
        },
        "token-registry-backfill": {
            "tablePresent": token_present,
            "observed": "classified_count" in token_row,
            "classifiedCount": _optional_number(token_row, "classified_count"),
            "terminalCount": _optional_number(token_row, "terminal_count"),
            "retryCount": _optional_number(token_row, "retry_count"),
            "updatedAt": _iso(token_row.get("updated_at")),
        },
        "placeholder-reconciliation": {
            "tablePresent": placeholder_present,
            "observed": "classified_count" in placeholder_row,
            "classifiedCount": _optional_number(placeholder_row, "classified_count"),
            "exactCount": _optional_number(placeholder_row, "exact_count"),
            "supersededCount": _optional_number(placeholder_row, "superseded_count"),
            "ambiguousCount": _optional_number(placeholder_row, "ambiguous_count"),
            "unresolvedCount": _optional_number(placeholder_row, "unresolved_count"),
            "updatedAt": _iso(placeholder_row.get("updated_at")),
        },
        "canonical-identity-reconciliation": {
            "tablePresent": canonical_identity_present,
            "availability": (
                "available" if canonical_identity_query_available else "unavailable"
            ),
            "unavailableReason": (
                None
                if canonical_identity_query_available
                else "query-failed"
                if canonical_identity_present
                else "table-missing"
            ),
            "observed": canonical_identity_query_available,
            "classifiedCount": _optional_number(
                canonical_identity_row,
                "classified_count",
            ),
            "classificationCounts": {
                classification: _optional_number(
                    canonical_identity_row,
                    f"{classification}_count",
                )
                for classification in (
                    "resolved",
                    "not_found",
                    "invalid",
                    "ambiguous",
                    "retry",
                )
            },
            "updatedAt": _iso(canonical_identity_row.get("updated_at")),
            "cycleId": canonical_cycle_id or None,
            "receiptTablePresent": canonical_receipt_present,
            "receiptRows": canonical_receipt_rows,
            "restartReceiptRows": canonical_restart_receipt_rows,
        },
        "source-semantics-reconciliation": {
            "availability": (
                "available"
                if source_semantics_ledger_present
                and source_semantics_receipt_present
                and source_semantics_aggregate_available
                else "unavailable"
            ),
            "ledgerTablePresent": source_semantics_ledger_present,
            "receiptTablePresent": source_semantics_receipt_present,
            "cycleId": source_semantics_cycle_id or None,
            "classificationCounts": source_semantics_counts,
            "classifiedCount": _optional_number(
                source_semantics_ledger_aggregate,
                "classified_count",
            ),
            "invalidClassificationCount": _optional_number(
                source_semantics_ledger_aggregate,
                "invalid_classification_count",
            ),
            "orphanReceiptReferenceCount": _optional_number(
                source_semantics_ledger_aggregate,
                "orphan_receipt_reference_count",
            ),
            "invalidReceiptReferenceCount": _optional_number(
                source_semantics_ledger_aggregate,
                "invalid_receipt_reference_count",
            ),
            "distinctReceiptReferenceCount": _optional_number(
                source_semantics_ledger_aggregate,
                "distinct_receipt_reference_count",
            ),
            "receiptCount": len(source_semantics_receipt_rows),
            "updatedAt": _iso(
                source_semantics_ledger_aggregate.get("updated_at")
            ),
            "receiptRows": source_semantics_receipt_rows,
        },
    }


def _history_terminal_ledgers(
    watermarks: list[dict[str, Any]],
    ledger_metrics: Mapping[str, Mapping[str, Any]],
    market_metrics: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_id = {str(item.get("id") or ""): item for item in watermarks}

    history_evidence = ledger_metrics.get("gamma-history-evidence")
    if not isinstance(history_evidence, Mapping):
        history_evidence = {}
    validated_history_streams: dict[str, dict[str, Any]] = {}
    for spec in _HISTORY_STREAM_SPECS:
        watermark_id = str(spec["watermark_id"])
        validated_history_streams[watermark_id] = _validate_history_stream(
            watermark=by_id.get(watermark_id, {}),
            evidence=dict(history_evidence.get(watermark_id) or {}),
            spec=spec,
        )

    gamma_streams = [
        validated_history_streams["gamma-history-open"],
        validated_history_streams["gamma-history-closed"],
    ]
    market_prerequisite_satisfied = _closed_prerequisite_matches(
        gamma_streams[0], gamma_streams[1], event_stream=False
    )
    gamma_streams[1]["openPrerequisiteSatisfied"] = market_prerequisite_satisfied
    if gamma_streams[1]["terminal"] and not market_prerequisite_satisfied:
        gamma_streams[1]["gateSatisfied"] = False
        gamma_streams[1]["authorityValid"] = False
        gamma_streams[1]["status"] = "open-prerequisite-mismatch"
        gamma_streams[1]["errors"] = sorted(
            set(gamma_streams[1]["errors"]) | {"open-prerequisite-mismatch"}
        )

    event_streams = [
        validated_history_streams["gamma-event-history-open"],
        validated_history_streams["gamma-event-history-closed"],
    ]
    event_prerequisite_satisfied = _closed_prerequisite_matches(
        event_streams[0], event_streams[1], event_stream=True
    )
    event_streams[1]["openPrerequisiteSatisfied"] = event_prerequisite_satisfied
    if event_streams[1]["terminal"] and not event_prerequisite_satisfied:
        event_streams[1]["gateSatisfied"] = False
        event_streams[1]["authorityValid"] = False
        event_streams[1]["status"] = "open-prerequisite-mismatch"
        event_streams[1]["errors"] = sorted(
            set(event_streams[1]["errors"]) | {"open-prerequisite-mismatch"}
        )

    gamma_market_keyset_terminal = all(stream["terminal"] for stream in gamma_streams)
    gamma_market_keyset_gate = all(stream["gateSatisfied"] for stream in gamma_streams)
    gamma_event_keyset_terminal = all(stream["terminal"] for stream in event_streams)
    gamma_event_keyset_gate = all(stream["gateSatisfied"] for stream in event_streams)
    composite_observation_gate = _market_event_composite_observation_gate(
        gamma_streams,
        event_streams,
        dict(ledger_metrics.get("gamma-history-composite-evidence") or {}),
    )
    mutable_traversal_composite_gate = bool(
        gamma_market_keyset_gate
        and gamma_event_keyset_gate
        and composite_observation_gate["gateSatisfied"]
    )
    gamma_watermark_observed = any(by_id.get(item_id) for item_id in (
        "gamma-history-open",
        "gamma-history-closed",
    ))
    gamma_event_watermark_observed = any(by_id.get(item_id) for item_id in (
        "gamma-event-history-open",
        "gamma-event-history-closed",
    ))

    category_metric = dict(ledger_metrics.get("category-tags") or {})
    category_observed = category_metric.get("validationAvailable") is True
    category_gate = category_metric.get("ok") is True
    if category_gate:
        category_status = "current-complete"
        category_detail = (
            "Every current Gamma-backed canonical row has nonempty category and tags."
        )
    elif category_observed:
        category_status = "current-gaps"
        category_detail = (
            "The current canonical snapshot contains rows without category or tags."
        )
    else:
        category_status = "unknown"
        category_detail = (
            "The current canonical market snapshot is unavailable."
        )

    token_watermark = by_id.get("token-registry-backfill", {})
    token_state = _state_mapping(token_watermark)
    token_metric = dict(ledger_metrics.get("token-registry-backfill") or {})
    max_market_id = _number(market_metrics.get("max_market_id"))
    token_audit_lo = _optional_number(token_state, "audit_lo")
    token_audit_hi = _optional_number(token_state, "audit_hi")
    token_checkpoint = _optional_number(token_state, "checkpoint")
    token_verified_checkpoint = _optional_number(token_watermark, "lastBlock")
    token_coverage_start = _optional_number(token_state, "coverage_start")
    token_previous_audit_hi = _optional_number(token_state, "previous_audit_hi")
    token_cycle_number = _optional_number(token_state, "cycle_number")
    token_chain_valid = bool(
        token_coverage_start == 1
        and token_audit_lo is not None
        and token_audit_hi is not None
        and token_checkpoint == token_audit_hi
        and token_verified_checkpoint == token_checkpoint
        and token_audit_hi >= token_audit_lo - 1
        and token_cycle_number is not None
        and token_cycle_number >= 1
        and (
            (
                token_cycle_number == 1
                and token_audit_lo == 1
                and token_previous_audit_hi is None
            )
            or (
                token_cycle_number > 1
                and token_previous_audit_hi is not None
                and token_audit_lo == token_previous_audit_hi + 1
                and token_previous_audit_hi >= 1
            )
        )
    )
    token_terminal = bool(
        str(token_state.get("status") or "").lower() in {"complete", "completed"}
        and token_chain_valid
        and token_audit_hi is not None
        and token_audit_hi >= max_market_id
    )
    token_gate = bool(
        token_terminal
        and token_metric.get("observed")
        and token_metric.get("retryCount") == 0
    )

    placeholder_watermark = by_id.get("placeholder-reconciliation", {})
    placeholder_state = _state_mapping(placeholder_watermark)
    placeholder_metric = dict(ledger_metrics.get("placeholder-reconciliation") or {})
    placeholder_count = _number(market_metrics.get("orderfilled_placeholder_count"))
    placeholder_max_id = _number(market_metrics.get("orderfilled_placeholder_max_id"))
    placeholder_audit_hi = _optional_number(placeholder_state, "audit_hi")
    placeholder_ledger_count = placeholder_metric.get("classifiedCount")
    placeholder_terminal = bool(
        _state_checkpoint_complete(placeholder_state)
        and placeholder_audit_hi is not None
        and placeholder_audit_hi >= placeholder_max_id
        and isinstance(placeholder_ledger_count, int)
        and placeholder_ledger_count >= placeholder_count
    )
    placeholder_classification_gate = bool(
        placeholder_terminal
        and placeholder_metric.get("ambiguousCount") == 0
        and placeholder_metric.get("unresolvedCount") == 0
    )

    canonical_watermark = by_id.get("canonical-identity-reconciliation", {})
    canonical_metric = dict(
        ledger_metrics.get("canonical-identity-reconciliation") or {}
    )
    canonical_validation = _validate_canonical_cycle(
        watermark=canonical_watermark,
        metric=canonical_metric,
        max_market_id=max_market_id,
    )
    canonical_public_metric = dict(canonical_metric)
    canonical_public_metric.pop("receiptRows", None)
    canonical_public_metric.pop("restartReceiptRows", None)
    canonical_range_terminal = bool(canonical_validation["rangeTerminal"])
    canonical_gate = bool(canonical_validation["gateSatisfied"])

    source_semantics_watermark = by_id.get(
        "source-semantics-reconciliation",
        {},
    )
    source_semantics_metric = dict(
        ledger_metrics.get("source-semantics-reconciliation") or {}
    )
    source_semantics_validation = _validate_source_semantics_cycle(
        watermark=source_semantics_watermark,
        metric=source_semantics_metric,
        max_market_id=max_market_id,
    )
    source_semantics_public_metric = dict(source_semantics_metric)
    source_semantics_public_metric.pop("receiptRows", None)
    source_semantics_gate = bool(source_semantics_validation["gateSatisfied"])
    source_semantics_classification_gate = bool(
        source_semantics_validation["classificationGateSatisfied"]
    )
    source_semantics_terminal_residual_count = _number(
        source_semantics_validation.get("terminalResidualCount")
    )

    return [
        {
            "id": "gamma-history",
            "label": "Gamma operational mutable-traversal authority",
            "ledgerKind": "v4-observation-ledger-mutable-keyset-traversal",
            "status": (
                "operational-authority-satisfied"
                if mutable_traversal_composite_gate
                else "incomplete"
                if gamma_watermark_observed
                else "unknown"
            ),
            "terminal": gamma_market_keyset_terminal,
            "gateSatisfied": mutable_traversal_composite_gate,
            "marketKeysetGateSatisfied": gamma_market_keyset_gate,
            "source": (
                "ops.sync_state.gamma_market_history_backfill + "
                "ops.sync_state.gamma_market_history_backfill_closed + "
                "ops.gamma_market_history_commits + "
                "ops.gamma_market_history_residuals + "
                "ops.gamma_market_history_observations + "
                "ops.gamma_event_history_observations"
            ),
            "updatedAt": max(
                (
                    str(stream.get("updatedAt"))
                    for stream in gamma_streams
                    if stream.get("updatedAt")
                ),
                default=None,
            ),
            "metrics": {
                "marketKeysetTerminal": gamma_market_keyset_terminal,
                "marketKeysetGateSatisfied": gamma_market_keyset_gate,
                "eventKeysetGateSatisfied": gamma_event_keyset_gate,
                "mutableTraversalCompositeGateSatisfied": (
                    mutable_traversal_composite_gate
                ),
                "fullGammaHistoryGateSatisfied": False,
                "streams": gamma_streams,
                "compositeObservation": composite_observation_gate,
                "sourceSnapshotCutoffClaimed": False,
                "sameSourceFrozenSnapshotClaimed": False,
                "absoluteGammaHistoryCompletenessClaimed": False,
            },
            "detail": (
                "The API validates each v4 stream with all-batch counts and a bounded tail "
                "digest. Cross-stream composite authority remains fail-closed until an offline, "
                "checksum-pinned composite reconciliation receipt is materialized. Gamma also "
                "exposes no frozen cutoff, so this cannot prove absolute immutable history."
            ),
        },
        {
            "id": "gamma-event-history",
            "label": "Gamma open + closed event-keyset history",
            "ledgerKind": "v4-event-relationship-observation-ledger",
            "status": (
                "satisfied"
                if gamma_event_keyset_gate
                else "incomplete"
                if gamma_event_watermark_observed
                else "unknown"
            ),
            "terminal": gamma_event_keyset_terminal,
            "gateSatisfied": gamma_event_keyset_gate,
            "eventKeysetGateSatisfied": gamma_event_keyset_gate,
            "source": (
                "ops.sync_state.gamma_event_history_backfill + "
                "ops.sync_state.gamma_event_history_backfill_closed + "
                "ops.gamma_event_history_commits + "
                "ops.gamma_event_history_residuals + "
                "ops.gamma_event_history_observations"
            ),
            "updatedAt": max(
                (
                    str(stream.get("updatedAt"))
                    for stream in event_streams
                    if stream.get("updatedAt")
                ),
                default=None,
            ),
            "metrics": {
                "eventKeysetTerminal": gamma_event_keyset_terminal,
                "eventKeysetGateSatisfied": gamma_event_keyset_gate,
                "sourceSnapshotCutoffClaimed": False,
                "sameSourceFrozenSnapshotClaimed": False,
                "absoluteGammaHistoryCompletenessClaimed": False,
                "streams": event_streams,
            },
            "detail": (
                "This gate passes only when current-epoch open and closed event streams have "
                "checksum-valid authoritative commit chains, terminal tails, exact current-epoch "
                "residual accounting, and closed/open prerequisite identity. It does not prove an "
                "absolute or immutable Gamma history."
            ),
        },
        {
            "id": "category-tags",
            "label": "Gamma canonical category/tag snapshot",
            "ledgerKind": "live-canonical-aggregate",
            "status": category_status,
            "operationalOk": category_observed,
            "terminal": False,
            "terminalComplete": False,
            "gateSatisfied": category_gate,
            "source": "core.markets",
            "updatedAt": category_metric.get("updatedAt"),
            "metrics": category_metric,
            "identityTerminalResidualCount": 0,
            "detail": category_detail,
        },
        {
            "id": "token-registry-backfill",
            "label": "Normalized token registry backfill",
            "ledgerKind": "range-terminal-with-classified-exclusions",
            "status": "satisfied" if token_gate else "incomplete" if token_watermark else "unknown",
            "terminal": token_terminal,
            "gateSatisfied": token_gate,
            "source": "ops.sync_state + ops.market_token_backfill_failures",
            "updatedAt": token_metric.get("updatedAt") or token_watermark.get("updatedAt"),
            "metrics": {
                **token_metric,
                "coverageStart": token_coverage_start,
                "auditLo": token_audit_lo,
                "auditHi": token_audit_hi,
                "checkpoint": token_checkpoint,
                "verifiedCheckpoint": token_verified_checkpoint,
                "previousAuditHi": token_previous_audit_hi,
                "cycleNumber": token_cycle_number,
                "rollingChainValid": token_chain_valid,
                "coversCurrentMarketMax": bool(
                    token_audit_hi is not None and token_audit_hi >= max_market_id
                ),
            },
            "detail": (
                "Completion requires coverage_start=1, a checkpoint/last_block verified frozen "
                "cycle, a contiguous rolling-chain boundary, and coverage through the current local "
                "market maximum. Incremental-only ranges cannot pass. Terminal non-binary "
                "classifications remain explicit registry exclusions."
            ),
        },
        {
            "id": "canonical-identity-reconciliation",
            "label": "Canonical identity reconciliation",
            "ledgerKind": "range-terminal-classification-ledger",
            "status": (
                "satisfied"
                if canonical_gate
                else "incomplete"
                if canonical_watermark or canonical_metric.get("tablePresent")
                else "unknown"
            ),
            "terminal": canonical_range_terminal,
            "gateSatisfied": canonical_gate,
            "source": (
                "ops.sync_state.market_canonical_identity_reconciliation_v1 + "
                "ops.market_canonical_identity_reconciliation"
            ),
            "updatedAt": canonical_metric.get("updatedAt") or canonical_watermark.get("updatedAt"),
            "metrics": {
                **canonical_public_metric,
                **canonical_validation,
            },
            "detail": (
                "A satisfied range gate means every candidate through the frozen/current high-water "
                "mark was durably classified with no retry rows. Invalid and not-found classifications "
                "remain explicit source residuals; they are not promoted to Gamma identity."
            ),
        },
        {
            "id": "source-semantics-reconciliation",
            "label": "Official Gamma ordered token/source semantics reconciliation",
            "ledgerKind": "range-terminal-source-classification-receipt-chain",
            "status": (
                "satisfied"
                if source_semantics_gate
                else "terminal-with-classified-residuals"
                if source_semantics_classification_gate
                and source_semantics_terminal_residual_count > 0
                else "incomplete"
                if source_semantics_watermark
                or source_semantics_metric.get("ledgerTablePresent")
                else "unknown"
            ),
            "terminal": bool(source_semantics_validation["rangeTerminal"]),
            "gateSatisfied": source_semantics_gate,
            "classificationGateSatisfied": source_semantics_classification_gate,
            "source": (
                "ops.sync_state.market_source_semantics_reconciliation_v1 + "
                "ops.market_source_semantics_reconciliation + "
                "ops.market_source_semantics_reconciliation_receipts"
            ),
            "updatedAt": (
                source_semantics_metric.get("updatedAt")
                or source_semantics_watermark.get("updatedAt")
            ),
            "metrics": {
                **source_semantics_public_metric,
                **source_semantics_validation,
            },
            "detail": (
                "The classification gate proves that the frozen local ID range, receipt "
                "chain, database-aggregated ledger classifications, cursor and retry count "
                "conserve exactly. The strong gate additionally requires zero terminal "
                "source residuals. "
                "source_clob_absent, source_not_found, identity mismatch, ownership "
                "conflict and superseded duplicate remain explicit terminal source "
                "residuals; they are not reported as repaired semantics."
            ),
        },
        {
            "id": "placeholder-reconciliation",
            "label": "OrderFilled placeholder reconciliation",
            "ledgerKind": "classification-ledger-with-external-physical-remap-gate",
            "status": (
                "classification-terminal-physical-remap-unobserved"
                if placeholder_terminal
                else "incomplete"
                if placeholder_watermark or placeholder_metric.get("observed")
                else "unknown"
            ),
            "terminal": False,
            "gateSatisfied": False,
            "source": "ops.sync_state + ops.placeholder_market_reconciliation",
            "updatedAt": placeholder_metric.get("updatedAt") or placeholder_watermark.get("updatedAt"),
            "metrics": {
                **placeholder_metric,
                "classificationLedgerTerminal": placeholder_terminal,
                "classificationGateSatisfied": placeholder_classification_gate,
                "physicalClickHouseRemap": {
                    "availability": "unavailable",
                    "includedInApiEvidence": False,
                    "completionObserved": False,
                },
            },
            "detail": (
                "Classification is only a mapping decision. This PostgreSQL API does not currently "
                "observe the ClickHouse physical-remap checkpoint, batch receipts, conflict checks "
                "or conservation proof, so it cannot satisfy the placeholder-remediation gate."
            ),
        },
    ]


def _build_market_data_quality_payload(
    dependencies: MarketQualityDependencies,
) -> dict[str, Any]:
    generated_at = dependencies.utc_now_iso()
    now = _parse_datetime(generated_at) or datetime.now(timezone.utc)
    market_metrics = (
        _query_one(
            dependencies,
            f"""
            SELECT
                COUNT(*) AS total,
                MAX(m.id) AS max_market_id,
                SUM(CASE WHEN {_GAMMA_CANONICAL_SQL} THEN 1 ELSE 0 END) AS gamma_canonical_count,
                SUM(CASE
                        WHEN {_PLACEHOLDER_SQL} THEN 0
                        WHEN {_ONCHAIN_V2_SQL} THEN 0
                        WHEN {_GAMMA_CANONICAL_SQL} THEN 0
                        ELSE 1
                    END) AS protocol_identity_shell_count,
                SUM(CASE WHEN {_PLACEHOLDER_SQL} THEN 1 ELSE 0 END) AS orderfilled_placeholder_count,
                MAX(CASE WHEN {_PLACEHOLDER_SQL} THEN m.id ELSE NULL END) AS orderfilled_placeholder_max_id,
                SUM(CASE
                        WHEN NOT {_PLACEHOLDER_SQL} AND {_ONCHAIN_V2_SQL} THEN 1
                        ELSE 0
                    END) AS onchain_v2_count,
                SUM(CASE
                        WHEN {_GAMMA_CANONICAL_SQL}
                         AND COALESCE(TRIM(m.condition_id), '') <> ''
                         AND COALESCE(TRIM(m.question_id), '') <> ''
                         AND COALESCE(TRIM(m.yes_token_id), '') <> ''
                         AND COALESCE(TRIM(m.no_token_id), '') <> ''
                        THEN 1 ELSE 0
                    END) AS gamma_canonical_fully_identified,
                SUM(CASE
                        WHEN {_GAMMA_CANONICAL_SQL}
                         AND COALESCE(TRIM(m.question_id), '') <> ''
                        THEN 1 ELSE 0
                    END) AS gamma_canonical_question_bound,
                SUM(CASE
                        WHEN {_GAMMA_CANONICAL_SQL}
                         AND COALESCE(TRIM(m.category), '') <> ''
                        THEN 1 ELSE 0
                    END) AS gamma_canonical_category_complete,
                SUM(CASE
                        WHEN {_GAMMA_CANONICAL_SQL}
                         AND COALESCE(TRIM(CAST(m.tags AS TEXT)), '')
                             NOT IN ('', '[]', 'null')
                        THEN 1 ELSE 0
                    END) AS gamma_canonical_tags_complete,
                SUM(CASE
                        WHEN {_GAMMA_CANONICAL_SQL}
                         AND COALESCE(TRIM(m.category), '') <> ''
                         AND COALESCE(TRIM(CAST(m.tags AS TEXT)), '')
                             NOT IN ('', '[]', 'null')
                        THEN 1 ELSE 0
                    END) AS gamma_canonical_metadata_complete
            FROM markets m
            """,
        )
        if dependencies.table_exists("markets")
        else {}
    )
    serving_metrics = (
        _query_one(
            dependencies,
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN latest_price IS NOT NULL THEN 1 ELSE 0 END) AS priced,
                SUM(CASE WHEN last_trade_at IS NOT NULL THEN 1 ELSE 0 END) AS traded,
                MAX(last_trade_at) AS latest_trade_at,
                MAX(updated_at) AS updated_at
            FROM market_list_serving
            """,
        )
        if dependencies.table_exists("market_list_serving")
        else {}
    )
    active_cutoff = (now - timedelta(days=7)).isoformat()
    active_metrics = (
        _query_one(
            dependencies,
            """
            SELECT COUNT(*) AS total
            FROM market_list_serving
            WHERE last_trade_at >= ?
            """,
            (active_cutoff,),
        )
        if dependencies.table_exists("market_list_serving")
        else {}
    )
    token_metrics = (
        _query_one(
            dependencies,
            f"""
            SELECT
                COUNT(*) AS tokens,
                COUNT(DISTINCT mt.market_id) AS markets,
                COUNT(DISTINCT CASE
                    WHEN {_GAMMA_CANONICAL_SQL} THEN mt.market_id
                    ELSE NULL
                END) AS gamma_canonical_markets,
                SUM(CASE WHEN mt.active THEN 1 ELSE 0 END) AS active_tokens,
                MAX(mt.updated_at) AS updated_at
            FROM market_tokens mt
            JOIN markets m ON m.id = mt.market_id
            """,
        )
        if dependencies.table_exists("market_tokens") and dependencies.table_exists("markets")
        else {}
    )
    oracle_metrics = (
        _query_one(
            dependencies,
            """
            SELECT
                COUNT(*) AS events,
                COUNT(DISTINCT market_id) AS bound_markets,
                SUM(CASE WHEN market_id IS NOT NULL THEN 1 ELSE 0 END) AS bound_events,
                SUM(CASE WHEN market_id IS NULL THEN 1 ELSE 0 END) AS unbound_events,
                SUM(CASE WHEN LOWER(event_status) = 'request' THEN 1 ELSE 0 END) AS request_count,
                SUM(CASE WHEN LOWER(event_status) = 'propose' THEN 1 ELSE 0 END) AS propose_count,
                SUM(CASE WHEN LOWER(event_status) = 'dispute' THEN 1 ELSE 0 END) AS dispute_count,
                SUM(CASE WHEN LOWER(event_status) = 'settle' THEN 1 ELSE 0 END) AS settle_count,
                MAX(event_time) AS latest_event_at,
                MAX(block_number) AS latest_block
            FROM oracle_events
            """,
        )
        if dependencies.table_exists("oracle_events")
        else {}
    )
    resolution_metrics = (
        _query_one(
            dependencies,
            """
            SELECT
                COUNT(*) AS snapshots,
                SUM(CASE WHEN is_trading_closed THEN 1 ELSE 0 END) AS closed,
                SUM(CASE WHEN has_propose THEN 1 ELSE 0 END) AS proposed,
                SUM(CASE WHEN has_dispute THEN 1 ELSE 0 END) AS disputed,
                SUM(CASE WHEN has_settle THEN 1 ELSE 0 END) AS settled,
                SUM(CASE WHEN is_final THEN 1 ELSE 0 END) AS final,
                SUM(CASE WHEN is_trading_closed AND NOT has_propose AND NOT has_settle THEN 1 ELSE 0 END) AS awaiting,
                SUM(CASE WHEN completion_status = 'ENDED_AWAITING_ORACLE' THEN 1 ELSE 0 END) AS ended_awaiting_oracle,
                MAX(updated_at) AS updated_at
            FROM market_status_snapshot
            """,
        )
        if dependencies.table_exists("market_status_snapshot")
        else {}
    )

    watermarks = _sync_watermarks(dependencies)
    ledger_metrics = _history_ledger_metrics(
        dependencies,
        watermarks,
        market_metrics,
    )
    terminal_ledgers = _history_terminal_ledgers(watermarks, ledger_metrics, market_metrics)
    oracle_watermark = next((item for item in watermarks if item["id"] == "oracle_sync"), {})
    trade_watermark = next((item for item in watermarks if item["id"] == "trade_sync"), {})
    latest_oracle_at = oracle_metrics.get("latest_event_at") or oracle_watermark.get("updatedAt")
    latest_trade_at = serving_metrics.get("latest_trade_at") or trade_watermark.get("updatedAt")
    oracle_age = _age_seconds(latest_oracle_at, now)
    trade_age = _age_seconds(latest_trade_at, now)
    oracle_freshness = _freshness_status(
        oracle_age,
        fresh_seconds=3_600,
        stale_seconds=7 * 86_400,
    )
    trade_freshness = _freshness_status(
        trade_age,
        fresh_seconds=900,
        stale_seconds=86_400,
    )

    market_total = _number(market_metrics.get("total"))
    gamma_canonical = _number(market_metrics.get("gamma_canonical_count"))
    gamma_fully_identified = _number(market_metrics.get("gamma_canonical_fully_identified"))
    protocol_identity_shells = _number(market_metrics.get("protocol_identity_shell_count"))
    orderfilled_placeholders = _number(market_metrics.get("orderfilled_placeholder_count"))
    onchain_v2_shells = _number(market_metrics.get("onchain_v2_count"))
    serving_total = _number(serving_metrics.get("total"))
    serving_priced = _number(serving_metrics.get("priced"))
    oracle_events = _number(oracle_metrics.get("events"))
    oracle_bound_events = _number(oracle_metrics.get("bound_events"))
    closed_markets = _number(resolution_metrics.get("closed"))
    final_markets = _number(resolution_metrics.get("final"))
    gamma_token_markets = _number(token_metrics.get("gamma_canonical_markets"))

    dimensions = [
        _dimension(
            dimension_id="identity",
            label="Gamma canonical identity completeness",
            numerator=gamma_fully_identified,
            denominator=gamma_canonical,
            source="core.markets",
            detail=(
                "Condition, question and YES/NO token identifiers are present within the "
                "Gamma-backed canonical stratum; protocol shells and placeholders are excluded."
            ),
            warning_at=90.0,
            ok_at=99.0,
        ),
        _dimension(
            dimension_id="token-registry",
            label="Normalized token registry representation",
            numerator=gamma_token_markets,
            denominator=gamma_canonical,
            source="core.market_tokens",
            detail=(
                "Gamma canonical markets represented by at least one normalized token row. "
                "This is registry representation only, not semantic correctness or historical-source completeness."
            ),
            observed_at=token_metrics.get("updated_at"),
            warning_at=90.0,
            ok_at=99.0,
        ),
        _dimension(
            dimension_id="serving-price",
            label="Serving price coverage",
            numerator=serving_priced,
            denominator=serving_total,
            source="core.market_list_serving",
            detail="Serving-universe markets with a current probability snapshot.",
            observed_at=serving_metrics.get("updated_at"),
        ),
        _dimension(
            dimension_id="oracle-binding",
            label="Oracle event binding",
            numerator=oracle_bound_events,
            denominator=oracle_events,
            source="oracle.oracle_events",
            detail="Oracle events linked to a canonical local market identifier.",
            observed_at=latest_oracle_at,
            warning_at=90.0,
            ok_at=99.0,
        ),
        _dimension(
            dimension_id="resolution",
            label="Closed-market finality",
            numerator=final_markets,
            denominator=closed_markets,
            source="core.market_status_snapshot",
            detail="Closed markets with a final settlement snapshot.",
            observed_at=resolution_metrics.get("updated_at"),
            warning_at=85.0,
            ok_at=98.0,
        ),
        {
            "id": "oracle-freshness",
            "label": "Oracle index freshness",
            "status": oracle_freshness,
            "numerator": None,
            "denominator": None,
            "coveragePct": _freshness_score(oracle_freshness),
            "source": "ops.sync_state + oracle.oracle_events",
            "observedAt": _iso(latest_oracle_at),
            "ageSeconds": oracle_age,
            "detail": "Latest indexed request, proposal, dispute or settlement observation.",
        },
        {
            "id": "trade-freshness",
            "label": "OrderFilled serving freshness",
            "status": trade_freshness,
            "numerator": None,
            "denominator": None,
            "coveragePct": _freshness_score(trade_freshness),
            "source": "core.market_list_serving",
            "observedAt": _iso(latest_trade_at),
            "ageSeconds": trade_age,
            "detail": "Latest local trade observation used by serving prices.",
        },
    ]

    weighted_dimensions = [
        (dimensions[0], 0.20),
        (dimensions[1], 0.15),
        (dimensions[2], 0.15),
        (dimensions[3], 0.20),
        (dimensions[4], 0.15),
        (dimensions[5], 0.10),
        (dimensions[6], 0.05),
    ]
    score = round(
        sum(float(item.get("coveragePct") or 0.0) * weight for item, weight in weighted_dimensions),
        1,
    )
    critical_dimensions = [
        item["id"]
        for item in dimensions
        if item.get("status") in {"critical", "stale", "missing"}
    ]
    warning_dimensions = [
        item["id"]
        for item in dimensions
        if item.get("status") in {"warning", "aging"}
    ]
    status = "critical" if critical_dimensions else ("degraded" if warning_dimensions else "ok")

    missing_question = max(
        0,
        gamma_canonical - _number(market_metrics.get("gamma_canonical_question_bound")),
    )
    missing_token_registry = max(0, gamma_canonical - gamma_token_markets)
    ended_awaiting = _number(resolution_metrics.get("ended_awaiting_oracle"))
    unbound_oracle = _number(oracle_metrics.get("unbound_events"))
    gaps: list[dict[str, Any]] = []
    if oracle_freshness in {"stale", "missing"}:
        gaps.append(
            {
                "id": "oracle-index-stale",
                "severity": "critical",
                "label": "Oracle index is stale",
                "count": 1,
                "detail": "The latest indexed lifecycle event is older than the seven-day hard limit.",
                "observedAt": _iso(latest_oracle_at),
                "source": "oracle.oracle_events",
            }
        )
    if ended_awaiting:
        gaps.append(
            {
                "id": "closed-awaiting-oracle",
                "severity": "warning",
                "label": "Closed markets awaiting Oracle",
                "count": ended_awaiting,
                "detail": "Trading is closed but no final Oracle-backed settlement is recorded.",
                "source": "core.market_status_snapshot",
            }
        )
    if unbound_oracle:
        gaps.append(
            {
                "id": "unbound-oracle-events",
                "severity": "warning",
                "label": "Oracle events without local market binding",
                "count": unbound_oracle,
                "detail": "Events are durable on-chain observations but cannot yet be joined to a local market record.",
                "source": "oracle.oracle_events",
            }
        )
    if missing_question:
        gaps.append(
            {
                "id": "missing-question-id",
                "severity": "warning",
                "label": "Gamma canonical markets without question ID",
                "count": missing_question,
                "detail": "The Gamma canonical stratum has identity rows without an Oracle question bridge.",
                "source": "core.markets",
            }
        )
    if missing_token_registry:
        gaps.append(
            {
                "id": "missing-normalized-token-registry",
                "severity": "warning",
                "label": "Gamma canonical markets absent from normalized token registry",
                "count": missing_token_registry,
                "detail": (
                    "No normalized registry representation is present. This count does not test "
                    "mapping semantics or source-history completeness."
                ),
                "source": "core.market_tokens",
            }
        )

    ledgers_by_id = {item["id"]: item for item in terminal_ledgers}
    gamma_history_gate = ledgers_by_id["gamma-history"]
    if not gamma_history_gate["gateSatisfied"]:
        market_keyset_satisfied = bool(
            gamma_history_gate.get("marketKeysetGateSatisfied")
        )
        gaps.append(
            {
                "id": "gamma-history-not-terminal",
                "severity": "critical",
                "label": (
                    "Gamma mutable traversal lacks event/composite proof"
                    if market_keyset_satisfied
                    else "Gamma open + closed market-keyset traversal is not terminally verified"
                ),
                "count": 1,
                "detail": gamma_history_gate["detail"],
                "observedAt": gamma_history_gate.get("updatedAt"),
                "source": gamma_history_gate["source"],
            }
        )

    gamma_event_history_gate = ledgers_by_id["gamma-event-history"]
    if not gamma_event_history_gate["gateSatisfied"]:
        gaps.append(
            {
                "id": "gamma-event-history-not-terminal",
                "severity": "critical",
                "label": "Gamma open + closed event-keyset history is not terminally verified",
                "count": 1,
                "detail": gamma_event_history_gate["detail"],
                "observedAt": gamma_event_history_gate.get("updatedAt"),
                "source": gamma_event_history_gate["source"],
            }
        )

    canonical_gate = ledgers_by_id["canonical-identity-reconciliation"]
    if not canonical_gate["gateSatisfied"]:
        canonical_metrics = canonical_gate.get("metrics") or {}
        classification_counts = canonical_metrics.get("classificationCounts") or {}
        retry_count = _number(classification_counts.get("retry"))
        gaps.append(
            {
                "id": "canonical-identity-reconciliation-not-terminal",
                "severity": "warning",
                "label": "Canonical identity reconciliation is not terminally verified",
                "count": retry_count or 1,
                "detail": canonical_gate["detail"],
                "observedAt": canonical_gate.get("updatedAt"),
                "source": canonical_gate["source"],
            }
        )

    source_semantics_gate = ledgers_by_id["source-semantics-reconciliation"]
    source_semantics_metrics = source_semantics_gate.get("metrics") or {}
    source_semantics_classification_gate = bool(
        source_semantics_metrics.get("classificationGateSatisfied")
    )
    source_semantics_terminal_residual_count = _number(
        source_semantics_metrics.get("terminalResidualCount")
    )
    if not source_semantics_classification_gate:
        gaps.append(
            {
                "id": "source-semantics-reconciliation-not-terminal",
                "severity": "critical",
                "label": "Official source token semantics are not terminally reconciled",
                "count": _number(source_semantics_metrics.get("retryCount")) or 1,
                "detail": source_semantics_gate["detail"],
                "observedAt": source_semantics_gate.get("updatedAt"),
                "source": source_semantics_gate["source"],
            }
        )
    elif source_semantics_terminal_residual_count > 0:
        gaps.append(
            {
                "id": "source-semantics-terminal-residuals",
                "severity": "critical",
                "label": "Official source token semantics have classified terminal residuals",
                "count": source_semantics_terminal_residual_count,
                "detail": source_semantics_gate["detail"],
                "observedAt": source_semantics_gate.get("updatedAt"),
                "source": source_semantics_gate["source"],
            }
        )

    category_gate = ledgers_by_id["category-tags"]
    if not category_gate["gateSatisfied"]:
        category_metrics = category_gate.get("metrics") or {}
        gaps.append(
            {
                "id": "canonical-category-tags-incomplete",
                "severity": "warning",
                "label": "Gamma canonical markets missing category or tags",
                "count": _number(category_metrics.get("incompleteCount")) or 1,
                "detail": category_gate["detail"],
                "observedAt": category_gate.get("updatedAt"),
                "source": category_gate["source"],
            }
        )

    token_gate = ledgers_by_id["token-registry-backfill"]
    if not token_gate["gateSatisfied"]:
        token_retries = (token_gate.get("metrics") or {}).get("retryCount")
        gaps.append(
            {
                "id": "token-registry-backfill-not-terminal",
                "severity": "critical",
                "label": "Token registry backfill is not terminally verified",
                "count": token_retries if isinstance(token_retries, int) and token_retries > 0 else 1,
                "detail": token_gate["detail"],
                "observedAt": token_gate.get("updatedAt"),
                "source": token_gate["source"],
            }
        )

    placeholder_gate = ledgers_by_id["placeholder-reconciliation"]
    if orderfilled_placeholders and not placeholder_gate["gateSatisfied"]:
        placeholder_metrics = placeholder_gate.get("metrics") or {}
        unresolved_placeholders = _number(placeholder_metrics.get("ambiguousCount")) + _number(
            placeholder_metrics.get("unresolvedCount")
        )
        gaps.append(
            {
                "id": "placeholder-reconciliation-not-terminal",
                "severity": "warning",
                "label": "OrderFilled placeholder physical remap is not evidenced",
                "count": unresolved_placeholders or orderfilled_placeholders,
                "detail": placeholder_gate["detail"],
                "observedAt": placeholder_gate.get("updatedAt"),
                "source": placeholder_gate["source"],
            }
        )

    if any(item["severity"] == "critical" for item in gaps):
        status = "critical"
    elif gaps and status == "ok":
        status = "degraded"

    gap_markets = (
        _query_all(
            dependencies,
            """
            SELECT
                m.id AS market_id,
                m.title,
                m.slug,
                m.category,
                m.end_date,
                s.completion_status,
                s.updated_at
            FROM market_status_snapshot s
            JOIN markets m ON m.id = s.market_id
            WHERE s.completion_status = 'ENDED_AWAITING_ORACLE'
              AND m.title IS NOT NULL
              AND m.title <> ''
            ORDER BY s.updated_at DESC
            LIMIT 12
            """,
        )
        if dependencies.table_exists("market_status_snapshot") and dependencies.table_exists("markets")
        else []
    )
    normalized_gap_markets = [
        {
            "marketId": row.get("market_id"),
            "title": row.get("title"),
            "slug": row.get("slug"),
            "category": row.get("category"),
            "endDate": _iso(row.get("end_date")),
            "completionStatus": row.get("completion_status"),
            "observedAt": _iso(row.get("updated_at")),
        }
        for row in gap_markets
    ]

    recent_oracle = dependencies.get_recent_oracle_snapshot(limit=24)
    if not isinstance(recent_oracle, list):
        recent_oracle = []

    satisfied_terminal_gates = [
        item["id"] for item in terminal_ledgers if item.get("gateSatisfied") is True
    ]
    unsatisfied_terminal_gates = [
        item["id"] for item in terminal_ledgers if item.get("gateSatisfied") is not True
    ]
    required_additional_evidence = [
        "gamma-source-frozen-snapshot-cutoff-or-independent-archive-proof",
        "placeholder-clickhouse-physical-remap-completion-and-conservation-proof",
        "fresh-read-only-full-range-integrity-audit",
    ]
    if not gamma_event_history_gate.get("gateSatisfied"):
        required_additional_evidence.insert(0, "gamma-event-keyset-terminal-receipts")

    return {
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": generated_at,
        "status": status,
        "score": score,
        "summary": {
            "marketCount": market_total,
            "discoveredMarketCount": market_total,
            "gammaCanonicalMarketCount": gamma_canonical,
            "protocolIdentityShellCount": protocol_identity_shells,
            "orderFilledPlaceholderCount": orderfilled_placeholders,
            "onchainV2ShellCount": onchain_v2_shells,
            "normalizedRegistryMarketCount": _number(token_metrics.get("markets")),
            "servingMarketCount": serving_total,
            "recentlyTradedMarketCount": _number(active_metrics.get("total")),
            "oracleEventCount": oracle_events,
            "oracleBoundMarketCount": _number(oracle_metrics.get("bound_markets")),
            "activeGapCount": len(gaps),
            "criticalDimensionCount": len(critical_dimensions),
            "warningDimensionCount": len(warning_dimensions),
            "latestTradeAt": _iso(latest_trade_at),
            "latestOracleAt": _iso(latest_oracle_at),
        },
        "marketUniverse": {
            "discoveredTotal": market_total,
            "canonicalCount": gamma_canonical,
            "canonicalStratumId": "gamma-canonical",
            "strataAreDisjoint": True,
            "strata": [
                {
                    "id": "gamma-canonical",
                    "label": "Gamma canonical",
                    "count": gamma_canonical,
                    "canonical": True,
                    "definition": (
                        "Non-placeholder, non-V2-shell rows with a nonempty Gamma market id. "
                        "Canonical classification does not by itself prove metadata or history completeness."
                    ),
                },
                {
                    "id": "protocol-identity-shell",
                    "label": "Protocol identity shell",
                    "count": protocol_identity_shells,
                    "canonical": False,
                    "definition": (
                        "Residual local identity rows without Gamma canonical identity after the "
                        "OrderFilled placeholder and on-chain V2 strata are removed."
                    ),
                },
                {
                    "id": "orderfilled-placeholder",
                    "label": "OrderFilled placeholder",
                    "count": orderfilled_placeholders,
                    "canonical": False,
                    "definition": (
                        "Rows marked by category orderfilled-placeholder or the "
                        "trade-indexer-placeholder slug prefix."
                    ),
                },
                {
                    "id": "onchain-v2-shell",
                    "label": "On-chain V2 identity shell",
                    "count": onchain_v2_shells,
                    "canonical": False,
                    "definition": (
                        "Non-placeholder rows identified by the onchain-condition-v2 slug or "
                        "Unlisted Polymarket CTF V2 title marker."
                    ),
                },
            ],
        },
        "dimensions": dimensions,
        "lifecycle": [
            {
                "id": "discovered",
                "label": "Discovered",
                "count": market_total,
                "source": "core.markets",
                "detail": (
                    "All locally discovered rows across canonical, shell and placeholder strata; "
                    "this is not a canonical-market count."
                ),
            },
            {
                "id": "gamma-canonical",
                "label": "Gamma canonical",
                "count": gamma_canonical,
                "source": "core.markets.gamma_market_id",
                "detail": "Gamma-backed canonical stratum before completeness gates are applied.",
            },
            {
                "id": "tradeable",
                "label": "Tradeable / served",
                "count": serving_priced,
                "source": "core.market_list_serving",
                "detail": "Markets with a serving probability snapshot.",
            },
            {
                "id": "active",
                "label": "Recently active",
                "count": _number(active_metrics.get("total")),
                "source": "core.market_list_serving",
                "detail": "Markets with a local trade in the last seven days.",
            },
            {
                "id": "closed",
                "label": "Closed",
                "count": closed_markets,
                "source": "core.market_status_snapshot",
                "detail": "Trading-close state observed.",
            },
            {
                "id": "proposed",
                "label": "Proposed",
                "count": _number(resolution_metrics.get("proposed")),
                "source": "core.market_status_snapshot",
                "detail": "At least one Oracle proposal is observed.",
            },
            {
                "id": "disputed",
                "label": "Disputed",
                "count": _number(resolution_metrics.get("disputed")),
                "source": "core.market_status_snapshot",
                "detail": "At least one dispute is observed.",
            },
            {
                "id": "resolved",
                "label": "Resolved / final",
                "count": final_markets,
                "source": "core.market_status_snapshot",
                "detail": "A final settlement outcome is available.",
            },
            {
                "id": "redeemed",
                "label": "Redeemed",
                "count": None,
                "source": "not-collected",
                "detail": "Redemption coverage is outside the current read-only quality contract.",
                "status": "not-collected",
            },
        ],
        "oracleLifecycle": {
            "source": "oracle.oracle_events",
            "latestEventAt": _iso(latest_oracle_at),
            "latestBlock": oracle_metrics.get("latest_block"),
            "stages": [
                {"id": "request", "label": "Request", "count": _number(oracle_metrics.get("request_count"))},
                {"id": "propose", "label": "Propose", "count": _number(oracle_metrics.get("propose_count"))},
                {"id": "dispute", "label": "Dispute", "count": _number(oracle_metrics.get("dispute_count"))},
                {"id": "settle", "label": "Settle", "count": _number(oracle_metrics.get("settle_count"))},
            ],
            "recentEvents": recent_oracle,
        },
        "gaps": gaps,
        "gapMarkets": normalized_gap_markets,
        "watermarks": watermarks,
        "terminalLedgers": terminal_ledgers,
        "historicalCompleteness": {
            "claimed": False,
            "status": "not-demonstrated",
            "gateSatisfied": False,
            "satisfiedTerminalGateIds": satisfied_terminal_gates,
            "unsatisfiedTerminalGateIds": unsatisfied_terminal_gates,
            "requiredAdditionalEvidence": required_additional_evidence,
            "detail": (
                "This endpoint reports current registry representation, identity strata and durable "
                "PostgreSQL job ledgers. A v4 history gate can prove mutable traversal and composite "
                "identity reconstruction, but Gamma provides no frozen same-source snapshot cutoff. "
                "The endpoint also does not observe the ClickHouse placeholder-remap proof or replace "
                "an independent fresh full-range audit, so absolute historical completeness is not claimed."
            ),
        },
        "semantics": {
            "eventIdentity": "tx_hash + log_index",
            "canonicalOrder": "block_number + log_index",
            "marketBridge": (
                "local market_id + condition_id + question_id + token_id; field presence is an "
                "identity bridge, not a completeness proof"
            ),
            "marketUniverse": (
                "discoveredTotal includes Gamma canonical rows, protocol identity shells, "
                "OrderFilled placeholders and on-chain V2 shells"
            ),
            "normalizedTokenMetric": (
                "registry representation only; it does not establish semantic mapping correctness "
                "or historical-source completeness"
            ),
            "score": (
                "Weighted current coverage and freshness signal; lifecycle counts use different "
                "historical universes and are not a funnel or a historical-completeness claim."
            ),
        },
    }


def _query_error_record(exc: BaseException, observed_at: str) -> dict[str, Any]:
    return {
        "code": "market-quality-query-failed",
        "operation": (
            exc.operation if isinstance(exc, MarketQualityQueryError) else "snapshot-build"
        ),
        "type": (
            exc.original_type
            if isinstance(exc, MarketQualityQueryError)
            else type(exc).__name__
        ),
        "observedAt": observed_at,
    }


def _payload_with_query_error(
    payload: Mapping[str, Any],
    error: Mapping[str, Any],
) -> dict[str, Any]:
    stale = deepcopy(dict(payload))
    stale["status"] = "critical"
    stale["snapshotHealth"] = {
        "status": "stale-last-good",
        "lastGoodGeneratedAt": stale.get("generatedAt"),
        "error": dict(error),
    }
    historical = stale.get("historicalCompleteness")
    if isinstance(historical, Mapping):
        terminal_ledgers = stale.get("terminalLedgers")
        terminal_ledger_ids = [
            str(item.get("id"))
            for item in terminal_ledgers
            if isinstance(item, Mapping) and item.get("id")
        ] if isinstance(terminal_ledgers, list) else []
        stale["historicalCompleteness"] = {
            **dict(historical),
            "claimed": False,
            "gateSatisfied": False,
            "status": "not-demonstrated",
            "satisfiedTerminalGateIds": [],
            "unsatisfiedTerminalGateIds": terminal_ledger_ids,
        }
    terminal_ledgers = stale.get("terminalLedgers")
    if isinstance(terminal_ledgers, list):
        stale["terminalLedgers"] = [
            {
                **dict(item),
                "lastGoodGateSatisfied": item.get("gateSatisfied"),
                "gateSatisfied": False,
                "status": "stale-last-good",
            }
            if isinstance(item, Mapping)
            else item
            for item in terminal_ledgers
        ]
    gaps = stale.get("gaps")
    normalized_gaps = list(gaps) if isinstance(gaps, list) else []
    if not any(
        isinstance(gap, Mapping) and gap.get("id") == "market-quality-query-failed"
        for gap in normalized_gaps
    ):
        normalized_gaps.insert(
            0,
            {
                "id": "market-quality-query-failed",
                "severity": "critical",
                "label": "Market quality snapshot is serving last-good evidence",
                "count": 1,
                "detail": (
                    "A current database evidence query failed. The last-good payload is preserved "
                    "and is not replaced by an empty five-minute snapshot."
                ),
                "observedAt": error.get("observedAt"),
                "source": "market-quality-query-layer",
                "error": dict(error),
            },
        )
    stale["gaps"] = normalized_gaps
    summary = stale.get("summary")
    if isinstance(summary, Mapping):
        stale["summary"] = {
            **dict(summary),
            "activeGapCount": len(normalized_gaps),
        }
    return stale


def _error_payload(error: Mapping[str, Any], generated_at: str) -> dict[str, Any]:
    return {
        "contractVersion": CONTRACT_VERSION,
        "generatedAt": generated_at,
        "status": "error",
        "snapshotHealth": {
            "status": "error-no-last-good",
            "lastGoodGeneratedAt": None,
            "error": dict(error),
        },
        "gaps": [
            {
                "id": "market-quality-query-failed",
                "severity": "critical",
                "label": "Market quality evidence query failed",
                "count": 1,
                "source": "market-quality-query-layer",
                "error": dict(error),
            }
        ],
        "historicalCompleteness": {
            "claimed": False,
            "status": "not-demonstrated",
            "gateSatisfied": False,
        },
    }




def get_market_data_quality_payload(ctx: Mapping[str, Any]) -> dict[str, Any]:

    dependencies = MarketQualityDependencies.from_context(ctx)

    def builder() -> dict[str, Any]:

        try:
            payload = _build_market_data_quality_payload(dependencies)
        except Exception as exc:
            error = _query_error_record(exc, dependencies.utc_now_iso())
            with dependencies.resources.quality_lock:
                dependencies.resources.quality_last_error = error
            raise
        with dependencies.resources.quality_lock:
            dependencies.resources.quality_last_good = deepcopy(payload)
            dependencies.resources.quality_last_error = None
        return payload

    try:
        payload = dependencies.get_snapshot_payload(
            CACHE_NAMESPACE,
            CACHE_KEY,
            builder,
            ttl_seconds=CACHE_TTL_SECONDS,
        )
    except Exception as exc:
        error = _query_error_record(exc, dependencies.utc_now_iso())
        with dependencies.resources.quality_lock:
            last_good = deepcopy(dependencies.resources.quality_last_good)
            known_error = dict(dependencies.resources.quality_last_error or error)
        if last_good is not None:
            return _payload_with_query_error(last_good, known_error)
        return _error_payload(known_error, dependencies.utc_now_iso())

    if not isinstance(payload, Mapping):
        error = _query_error_record(
            TypeError("snapshot cache returned a non-object"),
            dependencies.utc_now_iso(),
        )
        with dependencies.resources.quality_lock:
            last_good = deepcopy(dependencies.resources.quality_last_good)
        if last_good is not None:
            return _payload_with_query_error(last_good, error)
        return _error_payload(error, dependencies.utc_now_iso())

    normalized = dict(payload)
    with dependencies.resources.quality_lock:
        if normalized.get("contractVersion") == CONTRACT_VERSION:
            dependencies.resources.quality_last_good = deepcopy(normalized)
        known_error = deepcopy(dependencies.resources.quality_last_error)
    return (
        _payload_with_query_error(normalized, known_error)
        if known_error is not None
        else normalized
    )
