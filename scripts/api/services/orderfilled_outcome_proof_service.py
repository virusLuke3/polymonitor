"""Checksum-pinned public proof provider for OrderFilled outcome repairs.

The serving layer must not infer that a correction receipt covers an arbitrary
aggregate.  This provider therefore accepts only an explicitly configured,
checksum-pinned manifest whose entries are indexed by the *exact* aggregate
identity ``(market_id, from_block, through_block, row_sha256)``.

Each lookup revalidates the pinned plan/checkpoint/receipt file chain and a
small, market-scoped ClickHouse watermark.  Missing configuration, stale
source data, active mutations, buffered rows, residual rows, and timeouts all
fail closed by returning ``None``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from . import clickhouse_orderfilled_service, outcome_semantics_service


MANIFEST_SCHEMA = "orderfilled-outcome-public-proof-manifest-v1"
RUNTIME_OBSERVATION_SCHEMA = "orderfilled-outcome-public-proof-runtime-observation-v1"
SOURCE_WATERMARK_SCHEMA = "orderfilled-outcome-public-proof-source-watermark-v1"
CHECKPOINT_SCHEMA = "orderfilled-outcome-semantic-checkpoint-v1"
PLAN_SCHEMAS = {"orderfilled-outcome-semantic-plan-v2"}
RECEIPT_STATES = ("PREPARED", "FACT_CORRECTED", "CASHFLOW_CORRECTED", "VERIFIED")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TOKEN_HEX_RE = re.compile(r"^[0-9a-f]{64}$")
_MAX_MANIFEST_BYTES = 8 * 1024 * 1024
_MAX_ARTIFACT_BYTES = 32 * 1024 * 1024

RuntimeProbe = Callable[..., Optional[Mapping[str, Any]]]


class ProofManifestInvalid(ValueError):
    """Raised internally when a configured proof artifact fails closed."""


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _payload_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _require_sha256(value: Any, *, field: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise ProofManifestInvalid(f"{field} must be a lowercase SHA-256")
    return normalized


def _positive_int(value: Any, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ProofManifestInvalid(f"{field} must be an integer") from exc
    if parsed <= 0:
        raise ProofManifestInvalid(f"{field} must be positive")
    return parsed


def _nonnegative_int(value: Any, *, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ProofManifestInvalid(f"{field} must be an integer") from exc
    if parsed < 0:
        raise ProofManifestInvalid(f"{field} must be nonnegative")
    return parsed


def _read_pinned_json(
    path_value: Any,
    expected_sha256: Any,
    *,
    field: str,
    maximum_bytes: int,
) -> tuple[dict[str, Any], Path, str]:
    expected = _require_sha256(expected_sha256, field=f"{field}.fileSha256")
    raw_path = str(path_value or "").strip()
    if not raw_path:
        raise ProofManifestInvalid(f"{field}.path is required")
    try:
        path = Path(raw_path).expanduser().resolve(strict=True)
        if not path.is_file() or path.stat().st_size > maximum_bytes:
            raise ProofManifestInvalid(f"{field} is not a bounded regular file")
        raw = path.read_bytes()
    except (OSError, RuntimeError) as exc:
        raise ProofManifestInvalid(f"{field} is unreadable") from exc
    if len(raw) > maximum_bytes:
        raise ProofManifestInvalid(f"{field} exceeds the size limit")
    observed = hashlib.sha256(raw).hexdigest()
    if observed != expected:
        raise ProofManifestInvalid(f"{field} checksum mismatch")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProofManifestInvalid(f"{field} is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ProofManifestInvalid(f"{field} must contain a JSON object")
    return payload, path, observed


def _entry_key(
    market_id: Any,
    from_block: Any,
    through_block: Any,
    row_sha256: Any,
) -> tuple[int, int, int, str]:
    market = _positive_int(market_id, field="marketId")
    lower = _positive_int(from_block, field="fromBlock")
    upper = _positive_int(through_block, field="throughBlock")
    if lower > upper:
        raise ProofManifestInvalid("fromBlock must not exceed throughBlock")
    return market, lower, upper, _require_sha256(row_sha256, field="rowSha256")


def _load_manifest(
    path: Any,
    expected_sha256: Any,
) -> tuple[
    dict[str, Any],
    str,
    dict[tuple[int, int, int, str], Mapping[str, Any]],
]:
    manifest, _resolved, observed_sha = _read_pinned_json(
        path,
        expected_sha256,
        field="manifest",
        maximum_bytes=_MAX_MANIFEST_BYTES,
    )
    if manifest.get("schemaVersion") != MANIFEST_SCHEMA:
        raise ProofManifestInvalid("manifest schema mismatch")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ProofManifestInvalid("manifest entries are required")
    index: dict[tuple[int, int, int, str], Mapping[str, Any]] = {}
    for raw_entry in entries:
        if not isinstance(raw_entry, Mapping):
            raise ProofManifestInvalid("manifest entry must be an object")
        key = _entry_key(
            raw_entry.get("marketId"),
            raw_entry.get("fromBlock"),
            raw_entry.get("throughBlock"),
            raw_entry.get("rowSha256"),
        )
        if key in index:
            raise ProofManifestInvalid("manifest contains a duplicate exact key")
        index[key] = raw_entry
    return manifest, observed_sha, index


def _normalized_outcome_mappings(
    raw_mappings: Any,
    *,
    token_field: str,
    code_field: str,
) -> set[tuple[str, int]]:
    if not isinstance(raw_mappings, list) or not raw_mappings:
        raise ProofManifestInvalid("outcome mappings are required")
    normalized: set[tuple[str, int]] = set()
    for raw in raw_mappings:
        if not isinstance(raw, Mapping):
            raise ProofManifestInvalid("outcome mapping is invalid")
        token = str(raw.get(token_field) or "").strip().lower().removeprefix("0x")
        try:
            code = int(raw.get(code_field))
        except (TypeError, ValueError) as exc:
            raise ProofManifestInvalid("outcome mapping code is invalid") from exc
        pair = (token, code)
        if not _TOKEN_HEX_RE.fullmatch(token) or code not in {1, 2} or pair in normalized:
            raise ProofManifestInvalid("outcome mapping identity is invalid")
        normalized.add(pair)
    if len({token for token, _code in normalized}) != len(normalized):
        raise ProofManifestInvalid("outcome mapping token is duplicated")
    if len(normalized) != 2 or {code for _token, code in normalized} != {1, 2}:
        raise ProofManifestInvalid("outcome mapping must be one strict binary pair")
    return normalized


def _validate_plan_scope(
    plan: Mapping[str, Any],
    *,
    market_id: int,
    entry: Mapping[str, Any],
) -> tuple[str, str, str]:
    if plan.get("schema_version") not in PLAN_SCHEMAS:
        raise ProofManifestInvalid("plan schema mismatch")
    plan_sha = _require_sha256(plan.get("plan_sha256"), field="plan.plan_sha256")
    report_sha = _require_sha256(
        (plan.get("audit_report") or {}).get("report_payload_sha256"),
        field="plan.audit_report.report_payload_sha256",
    )
    run_id = str(plan.get("run_id") or "").strip()
    # Older plans derive run_id from their filename/checkpoint.  The canonical
    # v2 plan currently deployed does not persist a top-level run_id.
    scope = plan.get("scope_contract")
    mappings = plan.get("mappings")
    before = plan.get("expected_postgres_before_image")
    if (
        not isinstance(scope, Mapping)
        or scope.get("authority_mode") != "direct_canonical_targets"
        or int(scope.get("target_market_count") or 0) != 1
        or not isinstance(mappings, list)
        or not mappings
        or not isinstance(before, list)
        or not before
    ):
        raise ProofManifestInvalid("plan is not a narrow direct-canonical target")
    try:
        mapping_markets = {int(item.get("market_id")) for item in mappings if isinstance(item, Mapping)}
        before_markets = {int(item.get("market_id")) for item in before if isinstance(item, Mapping)}
    except (TypeError, ValueError) as exc:
        raise ProofManifestInvalid("plan market scope is invalid") from exc
    if mapping_markets != {market_id} or before_markets != {market_id}:
        raise ProofManifestInvalid("plan market scope does not exactly match the entry")
    plan_mappings = _normalized_outcome_mappings(
        mappings,
        token_field="token_id_hex",
        code_field="new_outcome_code",
    )
    entry_mappings = _normalized_outcome_mappings(
        entry.get("outcomeMappings"),
        token_field="tokenIdHex",
        code_field="outcomeCode",
    )
    if plan_mappings != entry_mappings:
        raise ProofManifestInvalid("manifest outcome mappings do not match the pinned plan")
    return plan_sha, report_sha, run_id


def _artifact_reference(entry: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    chain = entry.get("artifactChain")
    reference = chain.get(name) if isinstance(chain, Mapping) else None
    if not isinstance(reference, Mapping):
        raise ProofManifestInvalid(f"artifactChain.{name} is required")
    return reference


def _path_matches(value: Any, expected: Path) -> bool:
    try:
        return Path(str(value or "")).expanduser().resolve(strict=True) == expected
    except (OSError, RuntimeError):
        return False


def _validate_receipt_transition(
    receipt: Mapping[str, Any],
    *,
    state: str,
    run_id: str,
    plan_sha: str,
    report_sha: str,
) -> None:
    index = RECEIPT_STATES.index(state)
    expected_from = RECEIPT_STATES[index - 1] if index else None
    expected = {
        "schema_version": outcome_semantics_service.OUTCOMEFILLED_RECEIPT_SCHEMA,
        "run_id": run_id,
        "from_state": expected_from,
        "state": state,
        "status": "PASS",
        "plan_sha256": plan_sha,
        "report_payload_sha256": report_sha,
    }
    if any(receipt.get(field) != value for field, value in expected.items()):
        raise ProofManifestInvalid(f"{state} receipt identity mismatch")


def _load_artifact_chain(
    entry: Mapping[str, Any],
    *,
    market_id: int,
) -> tuple[dict[str, Any], dict[str, str]]:
    plan_ref = _artifact_reference(entry, "plan")
    checkpoint_ref = _artifact_reference(entry, "checkpoint")
    verified_ref = _artifact_reference(entry, "verifiedReceipt")
    plan, plan_path, plan_file_sha = _read_pinned_json(
        plan_ref.get("path"),
        plan_ref.get("fileSha256"),
        field="artifactChain.plan",
        maximum_bytes=_MAX_ARTIFACT_BYTES,
    )
    checkpoint, checkpoint_path, checkpoint_file_sha = _read_pinned_json(
        checkpoint_ref.get("path"),
        checkpoint_ref.get("fileSha256"),
        field="artifactChain.checkpoint",
        maximum_bytes=_MAX_ARTIFACT_BYTES,
    )
    verified, verified_path, verified_file_sha = _read_pinned_json(
        verified_ref.get("path"),
        verified_ref.get("fileSha256"),
        field="artifactChain.verifiedReceipt",
        maximum_bytes=_MAX_ARTIFACT_BYTES,
    )
    plan_sha, report_sha, plan_run_id = _validate_plan_scope(
        plan,
        market_id=market_id,
        entry=entry,
    )
    run_id = str(checkpoint.get("run_id") or "").strip()
    if not run_id or (plan_run_id and plan_run_id != run_id):
        raise ProofManifestInvalid("plan/checkpoint run_id mismatch")
    if (
        not _path_matches(plan.get("plan_path"), plan_path)
        or not _path_matches(plan.get("checkpoint_path"), checkpoint_path)
        or not _path_matches(checkpoint.get("plan_path"), plan_path)
    ):
        raise ProofManifestInvalid("plan/checkpoint path chain mismatch")
    if (
        checkpoint.get("schema_version") != CHECKPOINT_SCHEMA
        or checkpoint.get("state") != "VERIFIED"
        or checkpoint.get("state_index") != 3
        or checkpoint.get("completed") is not True
        or checkpoint.get("plan_sha256") != plan_sha
        or checkpoint.get("report_payload_sha256") != report_sha
    ):
        raise ProofManifestInvalid("checkpoint is not a matching completed VERIFIED chain")
    receipts = checkpoint.get("receipts")
    if not isinstance(receipts, Mapping) or set(receipts) != set(RECEIPT_STATES):
        raise ProofManifestInvalid("checkpoint receipt chain is incomplete")
    loaded_verified: Optional[dict[str, Any]] = None
    for state in RECEIPT_STATES:
        reference = receipts.get(state)
        if not isinstance(reference, Mapping):
            raise ProofManifestInvalid(f"checkpoint {state} reference is invalid")
        payload, path, file_sha = _read_pinned_json(
            reference.get("path"),
            reference.get("file_sha256"),
            field=f"checkpoint.receipts.{state}",
            maximum_bytes=_MAX_ARTIFACT_BYTES,
        )
        _validate_receipt_transition(
            payload,
            state=state,
            run_id=run_id,
            plan_sha=plan_sha,
            report_sha=report_sha,
        )
        if state == "VERIFIED":
            if path != verified_path or file_sha != verified_file_sha or payload != verified:
                raise ProofManifestInvalid("manifest VERIFIED receipt does not match checkpoint")
            loaded_verified = payload
    if loaded_verified is None:
        raise ProofManifestInvalid("VERIFIED receipt is unavailable")
    verification = loaded_verified.get("verification")
    runtime = verification.get("runtime_gates") if isinstance(verification, Mapping) else None
    if (
        not isinstance(verification, Mapping)
        or verification.get("completion_contract") != "both_tables_verified_only_outcome_code_changed"
        or not outcome_semantics_service._verified_table_receipt(verification.get("orderfilled_fact"))
        or not outcome_semantics_service._verified_table_receipt(verification.get("address_trade_cashflows"))
        or not isinstance(runtime, Mapping)
        or runtime.get("active_mutations") != []
        or int(runtime.get("global_storage_buffer_rows") or 0) != 0
        or int(runtime.get("scoped_buffer_rows") or 0) != 0
        or runtime.get("scope_snapshot_consistent") is not True
    ):
        raise ProofManifestInvalid("VERIFIED receipt hard gates are incomplete")
    return loaded_verified, {
        "planFileSha256": plan_file_sha,
        "checkpointFileSha256": checkpoint_file_sha,
        "verifiedReceiptFileSha256": verified_file_sha,
    }


def _source_watermark_core(value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schemaVersion") != SOURCE_WATERMARK_SCHEMA:
        raise ProofManifestInvalid("source watermark schema mismatch")
    result = {
        "schemaVersion": SOURCE_WATERMARK_SCHEMA,
        "marketId": _positive_int(value.get("marketId"), field="sourceWatermark.marketId"),
        "sourceTable": str(value.get("sourceTable") or "").strip(),
        "fromBlock": _positive_int(value.get("fromBlock"), field="sourceWatermark.fromBlock"),
        "throughBlock": _positive_int(value.get("throughBlock"), field="sourceWatermark.throughBlock"),
        "rowCount": _positive_int(value.get("rowCount"), field="sourceWatermark.rowCount"),
        "uniqueKeyCount": _positive_int(value.get("uniqueKeyCount"), field="sourceWatermark.uniqueKeyCount"),
        "rowHashSum": str(value.get("rowHashSum") or "").strip(),
        "rowHashXor": str(value.get("rowHashXor") or "").strip(),
    }
    if (
        result["sourceTable"] != "orderfilled_fact"
        or result["fromBlock"] > result["throughBlock"]
        or result["rowCount"] != result["uniqueKeyCount"]
        or not result["rowHashSum"].isdigit()
        or not result["rowHashXor"].isdigit()
    ):
        raise ProofManifestInvalid("source watermark is invalid")
    return result


def _validate_manifest_coverage(
    entry: Mapping[str, Any],
    *,
    key: tuple[int, int, int, str],
    receipt: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    market_id, from_block, through_block, _row_sha = key
    if entry.get("zeroResidual") is not True or int(entry.get("residualRows") or 0) != 0:
        raise ProofManifestInvalid("manifest does not assert zero residual")
    source_version = _require_sha256(entry.get("sourceVersionSha256"), field="sourceVersionSha256")
    receipt_payload_sha = outcome_semantics_service._payload_sha256(receipt)
    expected_source_version = outcome_semantics_service._receipt_source_version_sha256(
        receipt,
        receipt_payload_sha,
    )
    if source_version != expected_source_version:
        raise ProofManifestInvalid("manifest source version is not bound to VERIFIED receipt")
    raw_watermark = entry.get("sourceWatermark")
    if not isinstance(raw_watermark, Mapping):
        raise ProofManifestInvalid("sourceWatermark is required")
    watermark = _source_watermark_core(raw_watermark)
    watermark_sha = _require_sha256(raw_watermark.get("watermarkSha256"), field="sourceWatermark.watermarkSha256")
    if watermark_sha != _payload_sha256(watermark):
        raise ProofManifestInvalid("source watermark checksum mismatch")
    if (
        watermark["marketId"] != market_id
        or watermark["fromBlock"] != from_block
        or watermark["throughBlock"] != through_block
    ):
        raise ProofManifestInvalid("source watermark does not exactly match aggregate window")
    verification = receipt.get("verification")
    fact = verification.get("orderfilled_fact") if isinstance(verification, Mapping) else None
    current = fact.get("current") if isinstance(fact, Mapping) else None
    if (
        not isinstance(current, Mapping)
        or int(current.get("row_count") or 0) != watermark["rowCount"]
        or int(current.get("unique_key_count") or 0) != watermark["uniqueKeyCount"]
    ):
        raise ProofManifestInvalid("source watermark count is not bound to VERIFIED receipt")
    return watermark, source_version


def _mapping_predicate(entry: Mapping[str, Any]) -> str:
    mappings = _normalized_outcome_mappings(
        entry.get("outcomeMappings"),
        token_field="tokenIdHex",
        code_field="outcomeCode",
    )
    predicates = []
    for token, code in sorted(mappings):
        predicates.append(f"(token_id = '{token}' AND outcome_code = {code})")
    return " OR ".join(predicates)


def _query_json_rows_safe(
    query_context: Mapping[str, Any],
    query: str,
    *,
    timeout_seconds: float,
) -> Optional[list[dict[str, Any]]]:
    """Use the API transport without placing a ClickHouse password on argv."""

    if not clickhouse_orderfilled_service.clickhouse_orderfilled_enabled():
        return None
    settings = clickhouse_orderfilled_service._settings()
    if settings["http_url"]:
        # A configured HTTP tunnel is authoritative.  A timeout must fail
        # closed instead of silently spending a second timeout on docker.
        return clickhouse_orderfilled_service._query_json_rows_http(
            dict(query_context),
            query,
            timeout_seconds=timeout_seconds,
        )
    if query_context.get("app") is None or shutil.which("docker") is None:
        return None
    command = ["docker", "exec", "-i"]
    environment = os.environ.copy()
    if settings["password"]:
        command.extend(["--env", "CLICKHOUSE_PASSWORD"])
        environment["CLICKHOUSE_PASSWORD"] = settings["password"]
    command.extend(
        [
            settings["container"],
            "clickhouse-client",
            "--database",
            settings["database"],
            "--user",
            settings["user"],
            "--query",
            query,
        ]
    )
    try:
        completed = subprocess.run(
            command,
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    rows: list[dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _clickhouse_runtime_probe(
    *,
    entry: Mapping[str, Any],
    timeout_seconds: float,
    query_context: Optional[Mapping[str, Any]] = None,
    **_kwargs: Any,
) -> Optional[Mapping[str, Any]]:
    """Collect one bounded, exact-market source watermark and runtime gate."""

    market_id = _positive_int(entry.get("marketId"), field="entry.marketId")
    table = clickhouse_orderfilled_service._table_sql()
    if table != "orderfilled_fact":
        return None
    mapping_predicate = _mapping_predicate(entry)
    query = f"""
        SELECT
            toUInt64(count()) AS row_count,
            toUInt64(uniqExact(tuple(tx_hash, log_index))) AS unique_key_count,
            toUInt64(min(block_number)) AS from_block,
            toUInt64(max(block_number)) AS through_block,
            toString(sum(cityHash64(
                tx_hash, toString(log_index), toString(market_id), condition_id,
                token_id, toString(outcome_code), maker, taker, toString(side_code),
                toString(price), toString(size), toString(block_number), order_hash,
                toString(contract), toString(maker_amount), toString(taker_amount),
                toString(fee), toString(ingested_at)
            ))) AS row_hash_sum,
            toString(groupBitXor(cityHash64(
                tx_hash, toString(log_index), toString(market_id), condition_id,
                token_id, toString(outcome_code), maker, taker, toString(side_code),
                toString(price), toString(size), toString(block_number), order_hash,
                toString(contract), toString(maker_amount), toString(taker_amount),
                toString(fee), toString(ingested_at)
            ))) AS row_hash_xor,
            toUInt64(countIf(NOT ({mapping_predicate}))) AS residual_rows,
            (
                SELECT count()
                FROM system.mutations
                WHERE database = currentDatabase()
                  AND table IN ('orderfilled_fact', 'address_trade_cashflows')
                  AND is_done = 0
            ) AS active_mutation_count,
            (
                SELECT toUInt64(any(value))
                FROM system.metrics
                WHERE metric = 'StorageBufferRows'
            ) AS global_buffer_rows,
            toInt64((
                SELECT count() FROM orderfilled_fact_buffer WHERE market_id = {market_id}
            )) - toInt64(count()) AS scoped_buffer_rows
        FROM {table}
        PREWHERE market_id = {market_id}
        FORMAT JSONEachRow
    """
    rows = _query_json_rows_safe(
        dict(query_context or {}),
        query,
        timeout_seconds=timeout_seconds,
    )
    if not rows or len(rows) != 1:
        return None
    row = rows[0]
    watermark = {
        "schemaVersion": SOURCE_WATERMARK_SCHEMA,
        "marketId": market_id,
        "sourceTable": "orderfilled_fact",
        "fromBlock": row.get("from_block"),
        "throughBlock": row.get("through_block"),
        "rowCount": row.get("row_count"),
        "uniqueKeyCount": row.get("unique_key_count"),
        "rowHashSum": row.get("row_hash_sum"),
        "rowHashXor": row.get("row_hash_xor"),
    }
    try:
        normalized_watermark = _source_watermark_core(watermark)
        active_count = _nonnegative_int(row.get("active_mutation_count"), field="runtime.activeMutationCount")
        global_buffer = _nonnegative_int(row.get("global_buffer_rows"), field="runtime.globalBufferRows")
        scoped_buffer = _nonnegative_int(row.get("scoped_buffer_rows"), field="runtime.scopedBufferRows")
        residual_rows = _nonnegative_int(row.get("residual_rows"), field="runtime.residualRows")
    except ProofManifestInvalid:
        return None
    return {
        "schemaVersion": RUNTIME_OBSERVATION_SCHEMA,
        "sourceWatermark": normalized_watermark,
        "activeMutations": [] if active_count == 0 else [{"count": active_count}],
        "globalBufferRows": global_buffer,
        "scopedBufferRows": scoped_buffer,
        "zeroResidual": residual_rows == 0,
        "residualRows": residual_rows,
        "timedOut": False,
    }


def _runtime_observation_valid(
    observation: Any,
    *,
    expected_watermark: Mapping[str, Any],
) -> bool:
    if not isinstance(observation, Mapping):
        return False
    watermark = observation.get("sourceWatermark")
    if not isinstance(watermark, Mapping):
        return False
    try:
        normalized = _source_watermark_core(watermark)
        active = observation.get("activeMutations")
        return bool(
            observation.get("schemaVersion") == RUNTIME_OBSERVATION_SCHEMA
            and observation.get("timedOut") is False
            and normalized == dict(expected_watermark)
            and isinstance(active, list)
            and not active
            and _nonnegative_int(observation.get("globalBufferRows"), field="runtime.globalBufferRows") == 0
            and _nonnegative_int(observation.get("scopedBufferRows"), field="runtime.scopedBufferRows") == 0
            and observation.get("zeroResidual") is True
            and _nonnegative_int(observation.get("residualRows"), field="runtime.residualRows") == 0
        )
    except ProofManifestInvalid:
        return False


def _timeout_seconds(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = 1.0
    return min(max(parsed, 0.05), 5.0)


def get_orderfilled_outcome_mutation_proof(
    *,
    market_id: int,
    from_block: int,
    through_block: int,
    row_sha256: str,
    manifest_path: Any = None,
    manifest_sha256: Any = None,
    runtime_probe: Optional[RuntimeProbe] = None,
    query_context: Optional[Mapping[str, Any]] = None,
    timeout_seconds: Any = None,
) -> Optional[dict[str, Any]]:
    """Return an exact, live-revalidated public proof or ``None``.

    The manifest path and SHA must both be explicit (arguments or environment);
    no directory scan and no "latest receipt" selection is performed.
    """

    configured_path = manifest_path or os.environ.get("POLYDATA_ORDERFILLED_OUTCOME_PROOF_MANIFEST_PATH")
    configured_sha = manifest_sha256 or os.environ.get("POLYDATA_ORDERFILLED_OUTCOME_PROOF_MANIFEST_SHA256")
    if not configured_path or not configured_sha:
        return None
    try:
        key = _entry_key(market_id, from_block, through_block, row_sha256)
        _manifest, observed_manifest_sha, manifest_index = _load_manifest(
            configured_path,
            configured_sha,
        )
        entry = manifest_index.get(key)
        if entry is None:
            return None
        receipt, artifact_hashes = _load_artifact_chain(entry, market_id=key[0])
        expected_watermark, source_version = _validate_manifest_coverage(
            entry,
            key=key,
            receipt=receipt,
        )
        probe = runtime_probe or _clickhouse_runtime_probe
        timeout = _timeout_seconds(
            timeout_seconds
            if timeout_seconds is not None
            else os.environ.get("POLYDATA_ORDERFILLED_OUTCOME_PROOF_TIMEOUT_SECONDS", "1.0")
        )
        try:
            observation = probe(
                entry=deepcopy(entry),
                timeout_seconds=timeout,
                query_context=query_context,
            )
        except Exception:
            return None
        if not _runtime_observation_valid(
            observation,
            expected_watermark=expected_watermark,
        ):
            return None
        receipt_payload_sha = outcome_semantics_service._payload_sha256(receipt)
        proof: dict[str, Any] = {
            "schemaVersion": outcome_semantics_service.OUTCOMEFILLED_PUBLIC_PROOF_SCHEMA,
            "manifestSha256": observed_manifest_sha,
            "artifactChain": artifact_hashes,
            "receipt": receipt,
            "receiptSha256": receipt_payload_sha,
            "planSha256": receipt["plan_sha256"],
            "coverage": {
                "marketIds": [key[0]],
                "fromBlock": key[1],
                "throughBlock": key[2],
                "sourceTable": "orderfilled_fact",
                "sourceVersionSha256": source_version,
                "sourceWatermarkSha256": _payload_sha256(expected_watermark),
                "rowSha256": key[3],
                "rebuiltFromReceiptSha256": receipt_payload_sha,
                "zeroResidual": True,
                "residualRows": 0,
            },
        }
        proof["proofSha256"] = outcome_semantics_service._payload_sha256(proof)
        if not outcome_semantics_service._validate_orderfilled_mutation_proof(
            proof,
            market_id=key[0],
            source_from_block=key[1],
            source_through_block=key[2],
            row_sha256=key[3],
        ):
            return None
        return proof
    except Exception:
        return None
