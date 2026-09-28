from __future__ import annotations
from api.context import RuntimeResources


import json
import sqlite3
from types import SimpleNamespace
from typing import Any


from api.services import market_quality_service as subject  # noqa: E402


class _Logger:
    def exception(self, *_args: Any, **_kwargs: Any) -> None:
        pass


def _history_receipt(
    *,
    kind: str,
    sync_state_key: str,
    source_filter: str,
    epoch: str,
    residual_count: int = 0,
    reason_counts: dict[str, int] | None = None,
    open_prerequisite_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reason_counts = reason_counts or {}
    observation_rows = _history_observation_rows(
        kind=kind,
        source_filter=source_filter,
    )
    start_chain = subject._sha256_json([kind, source_filter, "start"])
    end_chain = subject._sha256_json([kind, source_filter, "terminal"])
    page_sha = subject._sha256_json([kind, source_filter, "page-0"])
    partition = _history_source_partition(kind=kind, source_filter=source_filter)
    page_evidence = [
        {
            "source_page_index": 0,
            "source_page_sha256": page_sha,
            "page_start_cursor_chain_sha256": start_chain,
            "page_end_cursor_chain_sha256": end_chain,
            "source_page_observed_oldest": "2026-01-01T00:00:00+00:00",
            "source_page_observed_newest": "2026-01-01T00:00:01+00:00",
            **(
                {"source_market_count": len(observation_rows) + residual_count}
                if kind == "market"
                else {
                    "source_event_count": 1,
                    "embedded_market_count": len(observation_rows) + residual_count,
                }
            ),
            "source_request_partition": partition,
        }
    ]
    for row in observation_rows:
        row.update(
            {
                "source_page_sha256": page_sha,
                "page_start_cursor_chain_sha256": start_chain,
                "page_end_cursor_chain_sha256": end_chain,
            }
        )
    observation_evidence_sha256 = subject._sha256_json(observation_rows)
    residual_evidence_sha256 = subject._sha256_json(
        [kind, source_filter, residual_count, reason_counts]
    )
    core: dict[str, Any] = {
        "schema_version": (
            "gamma-history-commit-v4"
            if kind == "market"
            else "gamma-event-history-commit-v4"
        ),
        "sync_state_key": sync_state_key,
        "source_filter": source_filter,
        "epoch_started_at": epoch,
        "commit_batch": 1,
        "page_count": 1,
        "observation_count": len(observation_rows),
        "observation_evidence_sha256": observation_evidence_sha256,
        "observation_ledger_postcheck": {
            "verified": True,
            "matched_rows": len(observation_rows),
            "evidence_sha256": observation_evidence_sha256,
            "reconstruction_scope": (
                "identity_and_hash_only"
                if kind == "market"
                else "identity_relationship_and_hash_only"
            ),
        },
        "observation_reconstruction_scope": (
            "identity_and_hash_only"
            if kind == "market"
            else "identity_relationship_and_hash_only"
        ),
        "full_source_payload_reconstructable_from_observation_ledger": False,
        "classified_residual_count": residual_count,
        "classified_residual_unique_count": residual_count,
        "classified_residual_reason_counts": reason_counts,
        "classified_residual_evidence_sha256": residual_evidence_sha256,
        "residual_ledger_postcheck": {
            "verified": True,
            "matched_unique_rows": residual_count,
            "evidence_sha256": residual_evidence_sha256,
        },
        "open_prerequisite_evidence": open_prerequisite_evidence,
        "start_cursor_chain_sha256": start_chain,
        "end_cursor_chain_sha256": end_chain,
        "page_sha256": [page_sha],
        "source_partition_sequentially_accounted": True,
        "source_request_partition": partition,
        "page_traversal_evidence": page_evidence,
        "page_traversal_evidence_sha256": subject._sha256_json(page_evidence),
        "terminal_scope": "mutable_keyset_partition_traversal",
        "source_partition_terminal_for_this_traversal": True,
        "source_snapshot_cutoff_claimed": False,
        "same_source_frozen_snapshot_claimed": False,
        "composite_identity_join_evidence_available": True,
        "observation_evidence_kind": (
            "market_identity_projection"
            if kind == "market"
            else "event_market_relationship_projection"
        ),
        "absolute_gamma_history_completeness_claimed": False,
        "terminal": True,
        "source_verified": True,
    }
    if kind == "market":
        core.update(
            source_seen_count=len(observation_rows) + residual_count,
            normalized_count=len(observation_rows),
            source_count_reconciled=True,
            open_closed_union_completeness_claimed=False,
        )
    else:
        core.update(
            source_event_count=1,
            embedded_market_count=len(observation_rows) + residual_count,
            normalized_observation_count=len(observation_rows),
            page_cursor_chain_sha256=[start_chain, end_chain],
            embedded_market_count_reconciled=True,
            absolute_gamma_history_completeness_claimed=False,
        )
    return {**core, "commit_sha256": subject._sha256_json(core)}


def _history_source_partition(*, kind: str, source_filter: str) -> dict[str, Any]:
    return {
        "endpoint": (
            "https://gamma-api.polymarket.com/markets/keyset"
            if kind == "market"
            else "https://gamma-api.polymarket.com/events/keyset"
        ),
        "source_filter": source_filter,
        "closed": source_filter == "closed",
    }


def _history_observation_rows(
    *,
    kind: str,
    source_filter: str,
) -> list[dict[str, Any]]:
    suffix = "open" if source_filter == "open" else "closed"
    partition_json = json.dumps(
        _history_source_partition(kind=kind, source_filter=source_filter),
        sort_keys=True,
        separators=(",", ":"),
    )
    common: dict[str, Any] = {
        "observation_index": 0,
        "source_page_index": 0,
        "source_page_sha256": None,
        "page_start_cursor_chain_sha256": None,
        "page_end_cursor_chain_sha256": None,
        "gamma_market_id": f"gamma-shared-{suffix}",
        "condition_id": f"condition-shared-{suffix}",
        "question_id": f"question-shared-{suffix}",
        "yes_token_id": f"yes-shared-{suffix}",
        "no_token_id": f"no-shared-{suffix}",
        "source_request_partition_json": partition_json,
        "source_page_observed_oldest": "2026-01-01T00:00:00+00:00",
        "source_page_observed_newest": "2026-01-01T00:00:01+00:00",
    }
    if kind == "market":
        return [
            {
                **common,
                "source_item_index": 0,
                "source_payload_sha256": subject._sha256_json(
                    ["market", suffix, "payload"]
                ),
                "reconstruction_scope": "identity_and_hash_only",
            }
        ]
    event_payload_sha = subject._sha256_json(["event", suffix, "payload"])
    market_payload_sha = subject._sha256_json(
        ["event-market", suffix, "payload"]
    )
    relationship = {
        "source_page_index": 0,
        "source_event_index": 0,
        "embedded_market_index": 0,
        "event_id": f"event-{suffix}",
        "event_slug": f"event-{suffix}",
        "gamma_market_id": common["gamma_market_id"],
        "condition_id": common["condition_id"],
        "event_source_payload_sha256": event_payload_sha,
        "market_source_payload_sha256": market_payload_sha,
    }
    return [
        {
            **common,
            "source_event_index": 0,
            "embedded_market_index": 0,
            "event_id": relationship["event_id"],
            "event_slug": relationship["event_slug"],
            "event_source_payload_sha256": event_payload_sha,
            "market_source_payload_sha256": market_payload_sha,
            "relationship_sha256": subject._sha256_json(relationship),
            "reconstruction_scope": "identity_relationship_and_hash_only",
        }
    ]


def _history_state(
    receipt: dict[str, Any],
    *,
    kind: str,
    residual_count: int = 0,
    reason_counts: dict[str, int] | None = None,
    open_prerequisite_evidence: dict[str, Any] | None = None,
    completed_at: str | None = None,
) -> dict[str, Any]:
    reason_counts = reason_counts or {}
    state: dict[str, Any] = {
        "status": "complete",
        "source_filter": receipt["source_filter"],
        "after_cursor": None,
        "source_verified": True,
        "epoch_started_at": receipt["epoch_started_at"],
        "completed_at": completed_at
        or (
            "2026-08-26T00:00:30Z"
            if receipt["source_filter"] == "open"
            else "2026-08-26T00:01:30Z"
        ),
        "commit_batches": 1,
        "pages": 1,
        "last_page_sha256": receipt["page_sha256"][-1],
        "last_commit_sha256": receipt["commit_sha256"],
        "last_commit_page_count": 1,
        "last_commit_start_cursor_chain_sha256": receipt[
            "start_cursor_chain_sha256"
        ],
        "last_commit_end_cursor_chain_sha256": receipt[
            "end_cursor_chain_sha256"
        ],
        "observation_count": receipt["observation_count"],
        "last_commit_observation_count": receipt["observation_count"],
        "last_commit_observation_evidence_sha256": receipt[
            "observation_evidence_sha256"
        ],
        "observation_reconstruction_scope": receipt[
            "observation_reconstruction_scope"
        ],
        "residual_reason_counts": reason_counts,
        "open_prerequisite_evidence": open_prerequisite_evidence,
    }
    if kind == "market":
        state.update(
            seen=receipt["source_seen_count"],
            normalized=receipt["normalized_count"],
            skipped=residual_count,
            last_commit_residual_count=residual_count,
        )
    else:
        state.update(
            source_events=receipt["source_event_count"],
            embedded_markets=receipt["embedded_market_count"],
            normalized_observations=receipt["normalized_observation_count"],
            classified_residuals=residual_count,
            last_commit_residual_count=residual_count,
        )
    return state


def _install_history_composite_receipt(
    conn: sqlite3.Connection,
) -> dict[str, Any]:
    stream_rows = (
        (
            "market-open",
            "market",
            "open",
            "gamma_market_history_backfill",
        ),
        (
            "market-closed",
            "market",
            "closed",
            "gamma_market_history_backfill_closed",
        ),
        (
            "event-open",
            "event",
            "open",
            "gamma_event_history_backfill",
        ),
        (
            "event-closed",
            "event",
            "closed",
            "gamma_event_history_backfill_closed",
        ),
    )
    pins: list[dict[str, Any]] = []
    for stream_id, kind, source_filter, sync_state_key in stream_rows:
        raw_state = conn.execute(
            "SELECT value FROM sync_state WHERE key = ?",
            (sync_state_key,),
        ).fetchone()
        assert raw_state is not None
        state = json.loads(raw_state[0])
        pins.append(
            {
                "stream_id": stream_id,
                "kind": kind,
                "source_filter": source_filter,
                "sync_state_key": sync_state_key,
                "epoch_started_at": state["epoch_started_at"],
                "completed_at": state["completed_at"],
                "terminal": True,
                "source_verified": True,
                "commit_batches": state["commit_batches"],
                "authority_tail_sha256": state["last_commit_sha256"],
                "authority_chain_sha256": subject._sha256_json(
                    [stream_id, "authority-chain"]
                ),
                "state_sha256": subject._sha256_json(state),
                "observation_count": state["observation_count"],
                "residual_observation_count": (
                    state.get("skipped", state.get("classified_residuals", 0))
                ),
                "residual_unique_count": (
                    state.get("skipped", state.get("classified_residuals", 0))
                ),
                "residual_evidence_sha256": subject._sha256_json(
                    [stream_id, "residual-ledger"]
                ),
                "source_manifest_tail_sha256": state["last_commit_sha256"],
                "source_manifest_file_sha256": subject._sha256_json(
                    [stream_id, "manifest-file"]
                ),
                "source_manifest_receipt_count": 1,
                "source_snapshot_cutoff_claimed": False,
                "same_source_frozen_snapshot_claimed": False,
                "absolute_gamma_history_completeness_claimed": False,
            }
        )
    counts = {
        "market_observation_count": 2,
        "market_ordered_identity_count": 2,
        "event_relationship_observation_count": 2,
        "exact_composite_join_count": 2,
        "exact_shared_ordered_identity_count": 2,
        "shared_identity_conflict_count": 0,
        "event_only_relationship_count": 0,
        "market_only_ordered_identity_count": 0,
        "market_identity_ambiguity_count": 0,
        "event_identity_ambiguity_count": 0,
        "invalid_event_relationship_sha_length_count": 0,
        "event_count_conservation_satisfied": True,
        "market_identity_count_conservation_satisfied": True,
        "count_conservation_satisfied": True,
    }
    digests = {
        "digest_algorithm": "sha256-length-prefixed-canonical-json-v1",
        "market_observation_count": 2,
        "market_observation_sha256": subject._sha256_json(
            ["market-observation-ledger"]
        ),
        "event_relationship_observation_count": 2,
        "event_relationship_observation_sha256": subject._sha256_json(
            ["event-observation-ledger"]
        ),
        "full_observation_digest_recomputed": True,
    }
    core = {
        "schema_version": "gamma-history-composite-reconciliation-v1",
        "status": "operationally_reconciled_mutable_traversal_epochs",
        "isolation_level": "repeatable_read",
        "repeatable_read_snapshot": True,
        "stream_pins": pins,
        "stream_pins_sha256": subject._sha256_json(pins),
        "epoch_set_sha256": subject._sha256_json(
            [
                [
                    pin["stream_id"],
                    pin["epoch_started_at"],
                    pin["authority_tail_sha256"],
                    pin["state_sha256"],
                ]
                for pin in pins
            ]
        ),
        "counts": counts,
        "observation_digests": digests,
        "exact_shared_identity_join_recomputed": True,
        "terminal_scope": "four_mutable_keyset_partition_traversal_epochs",
        "source_snapshot_cutoff_claimed": False,
        "same_source_frozen_snapshot_claimed": False,
        "absolute_gamma_history_completeness_claimed": False,
        "claim": "operational_mutable_traversal_epochs_reconciled",
    }
    receipt = {**core, "receipt_sha256": subject._sha256_json(core)}
    conn.execute(
        """
        CREATE TABLE gamma_history_composite_receipts (
            receipt_sha256 TEXT PRIMARY KEY,
            epoch_set_sha256 TEXT NOT NULL UNIQUE,
            receipt_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            manifest_tail_sha256 TEXT,
            manifest_written_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO gamma_history_composite_receipts VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            receipt["receipt_sha256"],
            receipt["epoch_set_sha256"],
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
            receipt["status"],
            "2026-08-27T00:10:00Z",
            receipt["receipt_sha256"],
            "2026-08-27T00:10:01Z",
        ),
    )
    conn.commit()
    return receipt


def _source_semantics_receipt(cycle_id: str) -> dict[str, Any]:
    counts = {
        "resolved": 1,
        "source_clob_absent": 1,
        "source_not_found": 0,
        "source_identity_mismatch": 0,
        "ownership_conflict": 0,
        "superseded_duplicate": 0,
        "retry": 0,
    }
    core = {
        "schema_version": "market-source-semantics-reconciliation-receipt-v1",
        "ledger_schema_version": "market-source-semantics-ledger-v1",
        "cycle_id": cycle_id,
        "run_id": "source-semantics-test-run",
        "batch_number": 1,
        "previous_receipt_sha256": None,
        "batch_kind": "scan",
        "audit_lo": 1,
        "audit_hi": 5,
        "checkpoint_before": 0,
        "checkpoint_after": 5,
        "rows_scanned": 5,
        "attempted_market_ids": [1, 2],
        "attempted_count": 2,
        "classification_counts": counts,
        "classification_conserved": True,
        "source_payload_sha256s": [subject._sha256_json(["official-source"])],
        "update_counts": {"markets": 1, "token_rows": 2},
        "post_update_verified": True,
        "committed_at": "2026-08-27T00:00:00Z",
    }
    return {**core, "receipt_sha256": subject._sha256_json(core)}


def _canonical_receipt(cycle_id: str) -> dict[str, Any]:
    core = {
        "schema_version": "market-canonical-identity-reconciliation-receipt-v1",
        "cycle_id": cycle_id,
        "candidate_contract_version": 2,
        "audit_lo": 1,
        "audit_hi": 5,
        "batch_number": 1,
        "start_checkpoint": 0,
        "end_checkpoint": 5,
        "market_ids": [3, 5],
        "condition_ids_sha256": subject._sha256_json(["condition-3", "condition-5"]),
        "classification_counts": {
            "resolved": 1,
            "not_found": 1,
            "invalid": 0,
            "ambiguous": 0,
            "retry": 0,
        },
        "resolution_sha256": subject._sha256_json(["resolved", "not_found"]),
        "open_query_sha256": subject._sha256_json([]),
        "closed_query_sha256": subject._sha256_json([]),
        "terminal": True,
        "post_upsert_verified": True,
    }
    return {**core, "receipt_sha256": subject._sha256_json(core)}


def _canonical_gate(payload: dict[str, Any]) -> dict[str, Any]:
    return next(
        item
        for item in payload["terminalLedgers"]
        if item["id"] == "canonical-identity-reconciliation"
    )


def _read_canonical_state(conn: sqlite3.Connection) -> dict[str, Any]:
    row = conn.execute(
        "SELECT value FROM sync_state "
        "WHERE key = 'market_canonical_identity_reconciliation_v1'"
    ).fetchone()
    assert row is not None
    return json.loads(row[0])


def _write_canonical_state(
    conn: sqlite3.Connection,
    state: dict[str, Any],
) -> None:
    conn.execute(
        "UPDATE sync_state SET value = ? "
        "WHERE key = 'market_canonical_identity_reconciliation_v1'",
        (json.dumps(state, sort_keys=True, separators=(",", ":")),),
    )
    conn.commit()


def _install_canonical_restart_evidence(conn: sqlite3.Connection) -> dict[str, Any]:
    state = _read_canonical_state(conn)
    restarted_at = "2026-08-26T23:00:00Z"
    state["cycle_started_at"] = restarted_at
    initial_state = dict(state)
    initial_state.update(
        {
            "checkpoint": 0,
            "status": "running",
            "completed_at": None,
            "chunks_completed": 0,
            "candidates_scanned": 0,
            "classification_counts": {
                "resolved": 0,
                "not_found": 0,
                "invalid": 0,
                "ambiguous": 0,
                "retry": 0,
            },
            "last_receipt_sha256": None,
        }
    )
    old_cycle_id = "canonical-legacy-cycle"
    core = {
        "schema_version": "market-canonical-identity-reconciliation-receipt-v1",
        "receipt_kind": "candidate_contract_superseded",
        "cycle_id": old_cycle_id,
        "candidate_contract_version": 1,
        "superseded_cycle_id": old_cycle_id,
        "superseded_status": "running",
        "superseded_audit_lo": 1,
        "superseded_audit_hi": 5,
        "superseded_checkpoint": 3,
        "superseded_chunks_completed": 1,
        "superseded_candidates_scanned": 2,
        "superseded_classification_counts": {
            "resolved": 1,
            "not_found": 1,
            "invalid": 0,
            "ambiguous": 0,
            "retry": 0,
        },
        "superseded_last_receipt_sha256": "a" * 64,
        "superseded_state_sha256": subject._sha256_json(
            {"cycle_id": old_cycle_id, "candidate_contract_version": 1}
        ),
        "restart_reason": "candidate_definition_added_missing_question_id",
        "new_candidate_contract_version": 2,
        "new_cycle_id": state["cycle_id"],
        "new_audit_lo": state["audit_lo"],
        "new_audit_hi": state["audit_hi"],
        "new_checkpoint": 0,
        "new_state_sha256": subject._sha256_json(initial_state),
        "restarted_at": restarted_at,
    }
    receipt = {**core, "receipt_sha256": subject._sha256_json(core)}
    durable_record = {**receipt, "event": "candidate_contract_superseded"}
    state.update(
        {
            "candidate_contract_restart_receipt_sha256": receipt[
                "receipt_sha256"
            ],
            "superseded_cycle_id": old_cycle_id,
            "superseded_candidate_contract_version": 1,
            "candidate_contract_restarted_at": restarted_at,
        }
    )
    _write_canonical_state(conn, state)
    conn.execute(
        """
        INSERT INTO market_canonical_identity_reconciliation_receipts (
            receipt_sha256, cycle_id, event, record_json, committed_at,
            manifest_written_at
        ) VALUES (?, ?, 'candidate_contract_superseded', ?, ?, ?)
        """,
        (
            receipt["receipt_sha256"],
            old_cycle_id,
            json.dumps(durable_record, sort_keys=True, separators=(",", ":")),
            restarted_at,
            restarted_at,
        ),
    )
    conn.commit()
    return receipt


def _database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE markets (
            id INTEGER PRIMARY KEY,
            gamma_market_id TEXT,
            slug TEXT,
            title TEXT,
            category TEXT,
            tags TEXT,
            condition_id TEXT,
            question_id TEXT,
            yes_token_id TEXT,
            no_token_id TEXT,
            end_date TEXT
        );
        CREATE TABLE market_tokens (
            id INTEGER PRIMARY KEY,
            market_id INTEGER,
            active INTEGER,
            updated_at TEXT
        );
        CREATE TABLE market_list_serving (
            market_id INTEGER,
            latest_price REAL,
            last_trade_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE oracle_events (
            market_id INTEGER,
            event_status TEXT,
            event_time TEXT,
            block_number INTEGER
        );
        CREATE TABLE market_status_snapshot (
            market_id INTEGER,
            is_trading_closed INTEGER,
            has_propose INTEGER,
            has_dispute INTEGER,
            has_settle INTEGER,
            is_final INTEGER,
            completion_status TEXT,
            updated_at TEXT
        );
        CREATE TABLE sync_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            last_block INTEGER,
            updated_at TEXT
        );
        CREATE TABLE market_metadata_refresh_failures (
            market_id INTEGER PRIMARY KEY,
            failure_kind TEXT,
            last_failed_at TEXT
        );
        CREATE TABLE market_token_backfill_failures (
            market_id INTEGER PRIMARY KEY,
            status TEXT,
            last_seen_at TEXT
        );
        CREATE TABLE placeholder_market_reconciliation (
            placeholder_market_id INTEGER PRIMARY KEY,
            classification TEXT,
            last_classified_at TEXT
        );
        CREATE TABLE gamma_market_history_residuals (
            sync_state_key TEXT,
            source_filter TEXT,
            gamma_market_id TEXT,
            failure_reason TEXT,
            source_payload_json TEXT,
            source_payload_sha256 TEXT,
            status TEXT,
            attempts INTEGER,
            first_seen_at TEXT,
            last_seen_at TEXT,
            first_epoch_started_at TEXT,
            last_epoch_started_at TEXT
        );
        CREATE TABLE gamma_market_history_commits (
            sync_state_key TEXT,
            source_filter TEXT,
            epoch_started_at TEXT,
            commit_batch INTEGER,
            receipt_sha256 TEXT,
            receipt_json TEXT,
            start_cursor_chain_sha256 TEXT,
            end_cursor_chain_sha256 TEXT,
            committed_at TEXT
        );
        CREATE TABLE gamma_market_history_observations (
            sync_state_key TEXT,
            source_filter TEXT,
            epoch_started_at TEXT,
            commit_batch INTEGER,
            observation_index INTEGER,
            source_page_index INTEGER,
            source_item_index INTEGER,
            source_page_sha256 TEXT,
            page_start_cursor_chain_sha256 TEXT,
            page_end_cursor_chain_sha256 TEXT,
            gamma_market_id TEXT,
            condition_id TEXT,
            question_id TEXT,
            yes_token_id TEXT,
            no_token_id TEXT,
            source_payload_sha256 TEXT,
            source_request_partition_json TEXT,
            source_page_observed_oldest TEXT,
            source_page_observed_newest TEXT,
            reconstruction_scope TEXT,
            observed_at TEXT
        );
        CREATE TABLE gamma_event_history_residuals (
            sync_state_key TEXT,
            source_filter TEXT,
            event_id TEXT,
            gamma_market_id TEXT,
            condition_id TEXT,
            failure_reason TEXT,
            source_payload_json TEXT,
            source_payload_sha256 TEXT,
            status TEXT,
            attempts INTEGER,
            first_seen_at TEXT,
            last_seen_at TEXT,
            first_epoch_started_at TEXT,
            last_epoch_started_at TEXT
        );
        CREATE TABLE gamma_event_history_commits (
            sync_state_key TEXT,
            source_filter TEXT,
            epoch_started_at TEXT,
            commit_batch INTEGER,
            receipt_sha256 TEXT,
            receipt_json TEXT,
            start_cursor_chain_sha256 TEXT,
            end_cursor_chain_sha256 TEXT,
            committed_at TEXT
        );
        CREATE TABLE gamma_event_history_observations (
            sync_state_key TEXT,
            source_filter TEXT,
            epoch_started_at TEXT,
            commit_batch INTEGER,
            observation_index INTEGER,
            source_page_index INTEGER,
            source_event_index INTEGER,
            embedded_market_index INTEGER,
            source_page_sha256 TEXT,
            page_start_cursor_chain_sha256 TEXT,
            page_end_cursor_chain_sha256 TEXT,
            event_id TEXT,
            event_slug TEXT,
            gamma_market_id TEXT,
            condition_id TEXT,
            question_id TEXT,
            yes_token_id TEXT,
            no_token_id TEXT,
            event_source_payload_sha256 TEXT,
            market_source_payload_sha256 TEXT,
            relationship_sha256 TEXT,
            source_request_partition_json TEXT,
            source_page_observed_oldest TEXT,
            source_page_observed_newest TEXT,
            reconstruction_scope TEXT,
            observed_at TEXT
        );
        CREATE TABLE market_canonical_identity_reconciliation (
            market_id INTEGER PRIMARY KEY,
            cycle_id TEXT,
            classification TEXT,
            last_attempted_at TEXT
        );
        CREATE TABLE market_canonical_identity_reconciliation_receipts (
            receipt_sha256 TEXT PRIMARY KEY,
            cycle_id TEXT,
            event TEXT,
            record_json TEXT,
            committed_at TEXT,
            manifest_written_at TEXT
        );
        CREATE TABLE market_source_semantics_reconciliation (
            market_id INTEGER PRIMARY KEY,
            cycle_id TEXT,
            classification TEXT,
            receipt_sha256 TEXT,
            last_attempted_at TEXT
        );
        CREATE TABLE market_source_semantics_reconciliation_receipts (
            receipt_sha256 TEXT PRIMARY KEY,
            cycle_id TEXT,
            batch_number INTEGER,
            previous_receipt_sha256 TEXT,
            record_json TEXT,
            committed_at TEXT
        );
        """
    )
    markets = [
        (
            1,
            "gamma-1",
            "gamma-one",
            "Gamma one",
            "Politics",
            '["politics"]',
            "condition-1",
            "question-1",
            "yes-1",
            "no-1",
            "2026-09-01T00:00:00Z",
        ),
        (
            2,
            "gamma-2",
            "gamma-two",
            "Gamma two",
            "Politics",
            '["politics"]',
            "condition-2",
            "",
            "yes-2",
            "no-2",
            "2026-09-01T00:00:00Z",
        ),
        (
            3,
            "",
            "protocol-shell-3",
            "Protocol identity shell",
            "",
            "[]",
            "condition-3",
            "",
            "yes-3",
            "no-3",
            None,
        ),
        (
            4,
            "gamma-should-not-promote-placeholder",
            "trade-indexer-placeholder-4",
            "OrderFilled placeholder",
            "orderfilled-placeholder",
            "[]",
            "condition-4",
            "",
            "yes-4",
            "no-4",
            None,
        ),
        (
            5,
            "gamma-should-not-promote-v2",
            "onchain-condition-v2-abc",
            "Unlisted Polymarket CTF V2 condition 0xabc",
            "",
            "[]",
            "condition-5",
            "",
            "yes-5",
            "no-5",
            None,
        ),
    ]
    conn.executemany(
        """
        INSERT INTO markets (
            id, gamma_market_id, slug, title, category, tags, condition_id,
            question_id, yes_token_id, no_token_id, end_date
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        markets,
    )
    conn.executemany(
        "INSERT INTO market_tokens (id, market_id, active, updated_at) VALUES (?, ?, 1, ?)",
        [(10, 1, "2026-08-27T00:00:00Z"), (11, 1, "2026-08-27T00:00:00Z")],
    )
    conn.execute(
        "INSERT INTO market_list_serving VALUES (1, 0.55, ?, ?)",
        ("2026-08-27T00:00:00Z", "2026-08-27T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO oracle_events VALUES (1, 'settle', ?, 123)",
        ("2026-08-27T00:00:00Z",),
    )
    conn.execute(
        "INSERT INTO market_status_snapshot VALUES (1, 1, 1, 0, 1, 1, 'SETTLED', ?)",
        ("2026-08-27T00:00:00Z",),
    )

    market_open_epoch = "2026-08-26T00:00:00Z"
    market_closed_epoch = "2026-08-26T00:01:00Z"
    event_open_epoch = "2026-08-26T00:02:00Z"
    event_closed_epoch = "2026-08-26T00:03:00Z"
    market_open_receipt = _history_receipt(
        kind="market",
        sync_state_key="gamma_market_history_backfill",
        source_filter="open",
        epoch=market_open_epoch,
        residual_count=1,
        reason_counts={"missing_condition_identity": 1},
    )
    market_open_evidence = {
        "sync_state_key": "gamma_market_history_backfill",
        "source_filter": "open",
        "epoch_started_at": market_open_epoch,
        "completed_at": "2026-08-26T00:00:30Z",
        "last_commit_sha256": market_open_receipt["commit_sha256"],
        "observation_count": market_open_receipt["observation_count"],
        "last_commit_observation_evidence_sha256": market_open_receipt[
            "observation_evidence_sha256"
        ],
        "state_sha256": "1" * 64,
        "terminal": True,
        "sequential_source_accounted": True,
        "canonical_union_completeness_claimed": False,
    }
    market_closed_receipt = _history_receipt(
        kind="market",
        sync_state_key="gamma_market_history_backfill_closed",
        source_filter="closed",
        epoch=market_closed_epoch,
        open_prerequisite_evidence=market_open_evidence,
    )
    event_open_receipt = _history_receipt(
        kind="event",
        sync_state_key="gamma_event_history_backfill",
        source_filter="open",
        epoch=event_open_epoch,
    )
    event_open_evidence = {
        "sync_state_key": "gamma_event_history_backfill",
        "source_filter": "open",
        "epoch_started_at": event_open_epoch,
        "completed_at": "2026-08-26T00:02:30Z",
        "last_commit_sha256": event_open_receipt["commit_sha256"],
        "source_events": 1,
        "embedded_markets": 1,
        "observation_count": event_open_receipt["observation_count"],
        "last_commit_observation_evidence_sha256": event_open_receipt[
            "observation_evidence_sha256"
        ],
        "state_sha256": "2" * 64,
        "terminal": True,
        "event_keyset_accounted": True,
        "absolute_gamma_history_completeness_claimed": False,
    }
    event_closed_receipt = _history_receipt(
        kind="event",
        sync_state_key="gamma_event_history_backfill_closed",
        source_filter="closed",
        epoch=event_closed_epoch,
        open_prerequisite_evidence=event_open_evidence,
    )
    canonical_cycle_id = "canonical-cycle-1"
    canonical_receipt = _canonical_receipt(canonical_cycle_id)
    source_semantics_cycle_id = "source-semantics-cycle-1"
    source_semantics_receipt = _source_semantics_receipt(
        source_semantics_cycle_id
    )

    states = {
        "market_sync": {"status": "old"},
        "market_sync_live": {"status": "live"},
        "trade_sync_live": {"status": "live"},
        "oracle_sync_live": {"status": "live"},
        "gamma_market_history_backfill": _history_state(
            market_open_receipt,
            kind="market",
            residual_count=1,
            reason_counts={"missing_condition_identity": 1},
            completed_at="2026-08-26T00:00:30Z",
        ),
        "gamma_market_history_backfill_closed": _history_state(
            market_closed_receipt,
            kind="market",
            open_prerequisite_evidence=market_open_evidence,
            completed_at="2026-08-26T00:01:30Z",
        ),
        "gamma_event_history_backfill": _history_state(
            event_open_receipt,
            kind="event",
            completed_at="2026-08-26T00:02:30Z",
        ),
        "gamma_event_history_backfill_closed": _history_state(
            event_closed_receipt,
            kind="event",
            open_prerequisite_evidence=event_open_evidence,
            completed_at="2026-08-26T00:03:30Z",
        ),
        "market_tokens_backfill_v1": {
            "version": 3,
            "status": "completed",
            "audit_lo": 1,
            "audit_hi": 5,
            "coverage_start": 1,
            "previous_audit_hi": None,
            "cycle_number": 1,
            "checkpoint": 5,
        },
        "placeholder_market_reconciliation_v1": {
            "status": "completed",
            "audit_lo": 1,
            "audit_hi": 5,
            "checkpoint": 5,
        },
        "market_canonical_identity_reconciliation_v1": {
            "version": 1,
            "candidate_contract_version": 2,
            "cycle_id": canonical_cycle_id,
            "status": "completed",
            "audit_lo": 1,
            "audit_hi": 5,
            "checkpoint": 5,
            "completed_at": "2026-08-27T00:00:00Z",
            "chunks_completed": 1,
            "candidates_scanned": 2,
            "last_receipt_sha256": canonical_receipt["receipt_sha256"],
            "classification_counts": {
                "resolved": 1,
                "not_found": 1,
                "invalid": 0,
                "ambiguous": 0,
                "retry": 0,
            },
        },
        "market_source_semantics_reconciliation_v1": {
            "schema_version": "market-source-semantics-reconciliation-v1",
            "cycle_id": source_semantics_cycle_id,
            "status": "complete",
            "audit_lo": 1,
            "audit_hi": 5,
            "checkpoint": 5,
            "rows_scanned": 5,
            "candidate_count": 2,
            "attempts_total": 2,
            "classification_counts": source_semantics_receipt[
                "classification_counts"
            ],
            "batch_number": 1,
            "last_receipt_sha256": source_semantics_receipt[
                "receipt_sha256"
            ],
            "started_at": "2026-08-27T00:00:00Z",
            "completed_at": "2026-08-27T00:00:01Z",
        },
    }
    market_open_evidence["state_sha256"] = subject._sha256_json(
        states["gamma_market_history_backfill"]
    )
    states["gamma_market_history_backfill_closed"][
        "open_prerequisite_evidence"
    ] = market_open_evidence
    market_closed_receipt = _history_receipt(
        kind="market",
        sync_state_key="gamma_market_history_backfill_closed",
        source_filter="closed",
        epoch=market_closed_epoch,
        open_prerequisite_evidence=market_open_evidence,
    )
    states["gamma_market_history_backfill_closed"][
        "last_commit_sha256"
    ] = market_closed_receipt["commit_sha256"]
    event_open_evidence["state_sha256"] = subject._sha256_json(
        states["gamma_event_history_backfill"]
    )
    states["gamma_event_history_backfill_closed"][
        "open_prerequisite_evidence"
    ] = event_open_evidence
    event_closed_receipt = _history_receipt(
        kind="event",
        sync_state_key="gamma_event_history_backfill_closed",
        source_filter="closed",
        epoch=event_closed_epoch,
        open_prerequisite_evidence=event_open_evidence,
    )
    states["gamma_event_history_backfill_closed"][
        "last_commit_sha256"
    ] = event_closed_receipt["commit_sha256"]
    conn.executemany(
        "INSERT INTO sync_state (key, value, last_block, updated_at) VALUES (?, ?, ?, ?)",
        [
            (
                key,
                json.dumps(value),
                5
                if key
                in {
                    "market_tokens_backfill_v1",
                    "placeholder_market_reconciliation_v1",
                    "market_canonical_identity_reconciliation_v1",
                    "market_source_semantics_reconciliation_v1",
                }
                else 1
                if key
                in {
                    "gamma_market_history_backfill",
                    "gamma_market_history_backfill_closed",
                    "gamma_event_history_backfill",
                    "gamma_event_history_backfill_closed",
                }
                else index,
                "2026-08-27T00:00:00Z",
            )
            for index, (key, value) in enumerate(states.items(), start=1)
        ],
    )
    conn.execute(
        "INSERT INTO market_token_backfill_failures VALUES (3, 'terminal', ?)",
        ("2026-08-27T00:00:00Z",),
    )
    conn.execute(
        "INSERT INTO placeholder_market_reconciliation VALUES (4, 'exact_unique_target', ?)",
        ("2026-08-27T00:00:00Z",),
    )
    conn.execute(
        """
        INSERT INTO gamma_market_history_residuals VALUES (
            'gamma_market_history_backfill', 'open', 'draft-1',
            'missing_condition_identity', '{}', 'residual-sha',
            'classified_residual', 2, ?, ?, ?, ?
        )
        """,
        (
            "2026-08-26T00:00:00Z",
            "2026-08-27T00:00:00Z",
            "2026-08-26T00:00:00Z",
            "2026-08-26T00:00:00Z",
        ),
    )
    for table, receipt in (
        ("gamma_market_history_commits", market_open_receipt),
        ("gamma_market_history_commits", market_closed_receipt),
        ("gamma_event_history_commits", event_open_receipt),
        ("gamma_event_history_commits", event_closed_receipt),
    ):
        conn.execute(
            f"""
            INSERT INTO {table} (
                sync_state_key, source_filter, epoch_started_at, commit_batch,
                receipt_sha256, receipt_json, start_cursor_chain_sha256,
                end_cursor_chain_sha256, committed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt["sync_state_key"],
                receipt["source_filter"],
                receipt["epoch_started_at"],
                receipt["commit_batch"],
                receipt["commit_sha256"],
                json.dumps(receipt, sort_keys=True, separators=(",", ":")),
                receipt["start_cursor_chain_sha256"],
                receipt["end_cursor_chain_sha256"],
                "2026-08-27T00:00:00Z",
            ),
        )
        kind = "market" if table == "gamma_market_history_commits" else "event"
        observation_table = (
            "gamma_market_history_observations"
            if kind == "market"
            else "gamma_event_history_observations"
        )
        observation_fields = (
            subject._MARKET_OBSERVATION_FIELDS
            if kind == "market"
            else subject._EVENT_OBSERVATION_FIELDS
        )
        observation_rows = _history_observation_rows(
            kind=kind,
            source_filter=receipt["source_filter"],
        )
        page = receipt["page_traversal_evidence"][0]
        for observation in observation_rows:
            observation.update(
                {
                    "source_page_sha256": page["source_page_sha256"],
                    "page_start_cursor_chain_sha256": page[
                        "page_start_cursor_chain_sha256"
                    ],
                    "page_end_cursor_chain_sha256": page[
                        "page_end_cursor_chain_sha256"
                    ],
                }
            )
            columns = ", ".join(
                (
                    "sync_state_key",
                    "source_filter",
                    "epoch_started_at",
                    "commit_batch",
                    *observation_fields,
                    "observed_at",
                )
            )
            placeholders = ", ".join(
                "?" for _ in range(5 + len(observation_fields))
            )
            conn.execute(
                f"INSERT INTO {observation_table} ({columns}) VALUES ({placeholders})",
                (
                    receipt["sync_state_key"],
                    receipt["source_filter"],
                    receipt["epoch_started_at"],
                    receipt["commit_batch"],
                    *(observation[field] for field in observation_fields),
                    "2026-08-27T00:00:00Z",
                ),
            )
    conn.executemany(
        "INSERT INTO market_canonical_identity_reconciliation VALUES (?, ?, ?, ?)",
        [
            (3, canonical_cycle_id, "resolved", "2026-08-27T00:00:00Z"),
            (5, canonical_cycle_id, "not_found", "2026-08-27T00:00:00Z"),
        ],
    )
    conn.execute(
        """
        INSERT INTO market_canonical_identity_reconciliation_receipts (
            receipt_sha256, cycle_id, event, record_json, committed_at,
            manifest_written_at
        ) VALUES (?, ?, 'batch_verified', ?, ?, ?)
        """,
        (
            canonical_receipt["receipt_sha256"],
            canonical_cycle_id,
            json.dumps(
                {**canonical_receipt, "event": "batch_verified", "run_id": "test-run"},
                sort_keys=True,
                separators=(",", ":"),
            ),
            "2026-08-27T00:00:00Z",
            "2026-08-27T00:00:01Z",
        ),
    )
    conn.executemany(
        """
        INSERT INTO market_source_semantics_reconciliation (
            market_id, cycle_id, classification, receipt_sha256,
            last_attempted_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        [
            (
                1,
                source_semantics_cycle_id,
                "resolved",
                source_semantics_receipt["receipt_sha256"],
                "2026-08-27T00:00:00Z",
            ),
            (
                2,
                source_semantics_cycle_id,
                "source_clob_absent",
                source_semantics_receipt["receipt_sha256"],
                "2026-08-27T00:00:00Z",
            ),
        ],
    )
    conn.execute(
        """
        INSERT INTO market_source_semantics_reconciliation_receipts (
            receipt_sha256, cycle_id, batch_number,
            previous_receipt_sha256, record_json, committed_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            source_semantics_receipt["receipt_sha256"],
            source_semantics_cycle_id,
            1,
            None,
            json.dumps(
                source_semantics_receipt,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "2026-08-27T00:00:00Z",
        ),
    )
    conn.commit()
    return conn


def _dependencies(conn: sqlite3.Connection) -> subject.MarketQualityDependencies:
    def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else {}

    def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def table_exists(name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
        return row is not None

    return subject.MarketQualityDependencies(
        resources=RuntimeResources(),
        application=SimpleNamespace(logger=_Logger()),
        query_one=query_one,
        query_all=query_all,
        table_exists=table_exists,
        get_snapshot_payload=lambda *_args, **_kwargs: {},
        get_recent_oracle_snapshot=lambda limit: [{"id": "oracle-1", "limit": limit}],
        utc_now_iso=lambda: "2026-08-27T00:05:00Z",
    )


def test_v4_stratifies_discovered_rows_without_promoting_shells_to_canonical() -> None:
    conn = _database()
    try:
        payload = subject._build_market_data_quality_payload(_dependencies(conn))
    finally:
        conn.close()

    assert payload["contractVersion"] == "prediction-market-data-quality.v4"
    assert payload["summary"]["marketCount"] == 5
    assert payload["summary"]["gammaCanonicalMarketCount"] == 2
    assert payload["marketUniverse"]["discoveredTotal"] == 5
    assert payload["marketUniverse"]["canonicalCount"] == 2
    assert {
        item["id"]: item["count"] for item in payload["marketUniverse"]["strata"]
    } == {
        "gamma-canonical": 2,
        "protocol-identity-shell": 1,
        "orderfilled-placeholder": 1,
        "onchain-v2-shell": 1,
    }
    discovered = next(item for item in payload["lifecycle"] if item["id"] == "discovered")
    assert "not a canonical-market count" in discovered["detail"]


def test_v4_registry_dimension_is_representation_only_and_uses_gamma_denominator() -> None:
    conn = _database()
    try:
        payload = subject._build_market_data_quality_payload(_dependencies(conn))
    finally:
        conn.close()

    identity = next(item for item in payload["dimensions"] if item["id"] == "identity")
    registry = next(item for item in payload["dimensions"] if item["id"] == "token-registry")
    assert (identity["numerator"], identity["denominator"]) == (1, 2)
    assert (registry["numerator"], registry["denominator"]) == (1, 2)
    assert "registry representation only" in registry["detail"].lower()
    assert "not semantic correctness" in registry["detail"].lower()
    assert "historical-source completeness" in registry["detail"].lower()
    assert payload["semantics"]["normalizedTokenMetric"].startswith("registry representation only")


def test_v4_bounds_stream_validation_and_fails_closed_without_composite_receipt() -> None:
    conn = _database()
    try:
        payload = subject._build_market_data_quality_payload(_dependencies(conn))
    finally:
        conn.close()

    watermarks = {item["id"]: item for item in payload["watermarks"]}
    assert watermarks["market_sync"]["key"] == "market_sync_live"
    assert watermarks["gamma-history-open"]["state"]["source_verified"] is True
    assert watermarks["gamma-history-closed"]["state"]["source_verified"] is True
    assert {
        "gamma-history-open",
            "gamma-history-closed",
            "gamma-event-history-open",
            "gamma-event-history-closed",
            "token-registry-backfill",
        "placeholder-reconciliation",
        "canonical-identity-reconciliation",
        "source-semantics-reconciliation",
    }.issubset(watermarks)

    ledgers = {item["id"]: item for item in payload["terminalLedgers"]}
    gamma = ledgers["gamma-history"]
    assert gamma["terminal"] is True
    assert gamma["marketKeysetGateSatisfied"] is True
    assert gamma["gateSatisfied"] is False
    assert gamma["status"] == "incomplete"
    streams = {item["id"]: item for item in gamma["metrics"]["streams"]}
    assert streams["open"]["terminal"] is True
    assert streams["open"]["classifiedResidualCount"] == 1
    assert streams["open"]["reasonCounts"] == {"missing_condition_identity": 1}
    assert streams["open"]["residualLedger"]["classifiedCount"] == 1
    assert streams["open"]["residualLedger"]["reasonCounts"] == {
        "missing_condition_identity": 1
    }
    assert streams["open"]["observationLedger"]["dbObservationCount"] == 1
    assert streams["open"]["observationLedger"]["accountingSatisfied"] is True
    assert streams["open"]["observationLedger"]["tailEvidenceShaVerified"] is True
    assert (
        streams["open"]["observationLedger"]["fullObservationDigestRecomputed"]
        is False
    )
    assert streams["open"]["observationLedger"]["validationScope"] == (
        "all_batch_counts_plus_tail_digest"
    )
    assert streams["open"]["sourceSnapshotCutoffClaimed"] is False
    assert streams["open"]["sameSourceFrozenSnapshotClaimed"] is False
    assert streams["closed"]["terminal"] is True
    assert streams["closed"]["classifiedResidualCount"] == 0
    assert streams["closed"]["residualLedger"]["classifiedCount"] == 0
    composite = gamma["metrics"]["compositeObservation"]
    assert composite["availability"] == "unavailable"
    assert composite["unavailableReason"] == (
        "offline-composite-reconciliation-not-materialized"
    )
    assert composite["offlineCompositeReceiptRequired"] is True
    assert composite["gateSatisfied"] is False
    assert composite["countConservationSatisfied"] is False
    assert composite["sourceSnapshotCutoffClaimed"] is False
    assert composite["sameSourceFrozenSnapshotClaimed"] is False
    assert composite["absoluteGammaHistoryCompletenessClaimed"] is False
    assert composite["fullObservationDigestRecomputed"] is False
    assert composite["validationScope"] == (
        "per-stream-all-batch-counts-plus-tail-digest"
    )
    assert gamma["metrics"]["fullGammaHistoryGateSatisfied"] is False
    event_history = ledgers["gamma-event-history"]
    assert event_history["terminal"] is True
    assert event_history["gateSatisfied"] is True
    assert event_history["metrics"]["absoluteGammaHistoryCompletenessClaimed"] is False
    assert ledgers["token-registry-backfill"]["gateSatisfied"] is True
    assert ledgers["token-registry-backfill"]["metrics"]["terminalCount"] == 1
    assert ledgers["canonical-identity-reconciliation"]["gateSatisfied"] is True
    assert ledgers["canonical-identity-reconciliation"]["metrics"][
        "classificationCounts"
    ] == {
        "resolved": 1,
        "not_found": 1,
        "invalid": 0,
        "ambiguous": 0,
        "retry": 0,
    }
    source_semantics = ledgers["source-semantics-reconciliation"]
    assert source_semantics["terminal"] is True
    assert source_semantics["gateSatisfied"] is False
    assert source_semantics["classificationGateSatisfied"] is True
    assert source_semantics["status"] == "terminal-with-classified-residuals"
    assert source_semantics["metrics"]["terminalResidualCount"] == 1
    assert source_semantics["metrics"]["classificationCounts"] == {
        "resolved": 1,
        "source_clob_absent": 1,
        "source_not_found": 0,
        "source_identity_mismatch": 0,
        "ownership_conflict": 0,
        "superseded_duplicate": 0,
        "retry": 0,
    }
    placeholder = ledgers["placeholder-reconciliation"]
    assert placeholder["gateSatisfied"] is False
    assert placeholder["terminal"] is False
    assert placeholder["metrics"]["classificationLedgerTerminal"] is True
    assert placeholder["metrics"]["classificationGateSatisfied"] is True
    assert placeholder["metrics"]["physicalClickHouseRemap"] == {
        "availability": "unavailable",
        "includedInApiEvidence": False,
        "completionObserved": False,
    }
    taxonomy = ledgers["category-tags"]
    assert taxonomy["status"] == "current-complete"
    assert taxonomy["operationalOk"] is True
    assert taxonomy["terminal"] is False
    assert taxonomy["terminalComplete"] is False
    assert taxonomy["gateSatisfied"] is True
    assert taxonomy["identityTerminalResidualCount"] == 0
    assert taxonomy["metrics"]["ok"] is True
    assert taxonomy["metrics"]["canonicalCount"] == 2
    assert taxonomy["metrics"]["missingCategoryCount"] == 0
    assert taxonomy["metrics"]["missingTagsCount"] == 0
    assert payload["historicalCompleteness"]["claimed"] is False
    assert payload["historicalCompleteness"]["status"] == "not-demonstrated"
    assert "fresh-read-only-full-range-integrity-audit" in payload["historicalCompleteness"][
        "requiredAdditionalEvidence"
    ]
    assert "gamma-event-keyset-terminal-receipts" not in payload[
        "historicalCompleteness"
    ]["requiredAdditionalEvidence"]
    assert "gamma-source-frozen-snapshot-cutoff-or-independent-archive-proof" in payload[
        "historicalCompleteness"
    ]["requiredAdditionalEvidence"]
    assert not any(
        item["id"] == "canonical-category-tags-incomplete"
        for item in payload["gaps"]
    )
    assert any(item["id"] == "gamma-history-not-terminal" for item in payload["gaps"])
    assert not any(
        item["id"] == "source-semantics-reconciliation-not-terminal"
        for item in payload["gaps"]
    )
    assert any(
        item["id"] == "source-semantics-terminal-residuals"
        and item["count"] == 1
        for item in payload["gaps"]
    )
    assert any(
        item["id"] == "placeholder-reconciliation-not-terminal"
        for item in payload["gaps"]
    )


def test_v4_cache_rebuild_uses_bounded_history_and_source_semantics_queries() -> None:
    conn = _database()
    base = _dependencies(conn)
    query_one_sql: list[str] = []
    query_all_sql: list[str] = []

    def query_one(sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
        query_one_sql.append(" ".join(sql.lower().split()))
        return base.query_one(sql, params)

    def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        query_all_sql.append(" ".join(sql.lower().split()))
        return base.query_all(sql, params)

    dependencies = subject.MarketQualityDependencies(
        resources=RuntimeResources(),
        application=base.application,
        query_one=query_one,
        query_all=query_all,
        table_exists=base.table_exists,
        get_snapshot_payload=base.get_snapshot_payload,
        get_recent_oracle_snapshot=base.get_recent_oracle_snapshot,
        utc_now_iso=base.utc_now_iso,
    )
    try:
        payload = subject._build_market_data_quality_payload(dependencies)
    finally:
        conn.close()

    all_sql = query_one_sql + query_all_sql
    assert not any("with market_observations as" in sql for sql in all_sql)
    assert not any(
        "select distinct gamma_market_id, condition_id" in sql
        for sql in all_sql
    )
    assert not any(
        " from market_source_semantics_reconciliation " in sql
        for sql in query_all_sql
    )
    source_aggregate_sql = [
        sql
        for sql in query_one_sql
        if " from market_source_semantics_reconciliation l " in sql
    ]
    assert len(source_aggregate_sql) == 1
    assert "count(*) as classified_count" in source_aggregate_sql[0]
    assert "orphan_receipt_reference_count" in source_aggregate_sql[0]

    ledgers = {item["id"]: item for item in payload["terminalLedgers"]}
    composite = ledgers["gamma-history"]["metrics"]["compositeObservation"]
    assert composite["unavailableReason"] == (
        "offline-composite-reconciliation-not-materialized"
    )
    source_metrics = ledgers["source-semantics-reconciliation"]["metrics"]
    assert source_metrics["classifiedCount"] == 2
    assert source_metrics["receiptCount"] == 1
    assert source_metrics["orphanReceiptReferenceCount"] == 0
    assert source_metrics["invalidClassificationCount"] == 0


def test_canonical_metadata_snapshot_reports_current_gaps() -> None:
    conn = _database()
    conn.execute("UPDATE markets SET category = '', tags = '[]' WHERE id = 2")
    try:
        payload = subject._build_market_data_quality_payload(_dependencies(conn))
    finally:
        conn.close()

    audit = next(
        item for item in payload["terminalLedgers"] if item["id"] == "category-tags"
    )
    assert audit["status"] == "current-gaps"
    assert audit["gateSatisfied"] is False
    assert audit["metrics"]["missingCategoryCount"] == 1
    assert audit["metrics"]["missingTagsCount"] == 1
    assert audit["metrics"]["incompleteCount"] == 1
    gap = next(
        item
        for item in payload["gaps"]
        if item["id"] == "canonical-category-tags-incomplete"
    )
    assert gap["count"] == 1


def test_context_dependencies_do_not_open_a_collector_connection() -> None:
    def unexpected_connection(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("API quality reads must not call collector code")

    dependencies = subject.MarketQualityDependencies.from_context(
        {
            "app": SimpleNamespace(logger=_Logger()),
            "query_one": lambda *_args, **_kwargs: {},
            "query_all": lambda *_args, **_kwargs: [],
            "table_exists": lambda _name: False,
            "get_snapshot_payload": lambda *_args, **_kwargs: {},
            "get_recent_oracle_snapshot": lambda limit: [],
            "utc_now_iso": lambda: "2026-08-27T00:05:00Z",
            "get_connection": unexpected_connection,
        }
    )

    assert dependencies.query_one("SELECT 1") == {}


def test_v4_observation_validation_never_fetches_the_full_current_epoch() -> None:
    conn = _database()
    base = _dependencies(conn)
    detail_queries: list[str] = []

    def query_all(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        detail_queries.append(sql)
        return base.query_all(sql, params)

    dependencies = subject.MarketQualityDependencies(
        resources=RuntimeResources(),
        application=base.application,
        query_one=base.query_one,
        query_all=query_all,
        table_exists=base.table_exists,
        get_snapshot_payload=base.get_snapshot_payload,
        get_recent_oracle_snapshot=base.get_recent_oracle_snapshot,
        utc_now_iso=base.utc_now_iso,
    )
    subject._build_market_data_quality_payload(dependencies)
    conn.close()

    observation_queries = [
        " ".join(sql.split())
        for sql in detail_queries
        if "history_observations" in sql
    ]
    assert observation_queries
    assert any("GROUP BY commit_batch" in sql for sql in observation_queries)
    tail_queries = [
        sql for sql in observation_queries if "observation_index" in sql
    ]
    assert tail_queries
    assert all("AND commit_batch = ?" in sql for sql in tail_queries)
    assert all(
        "GROUP BY commit_batch" in sql or "AND commit_batch = ?" in sql
        for sql in observation_queries
    )


def test_v4_open_only_gamma_state_cannot_pass_market_keyset_gate() -> None:
    conn = _database()
    conn.execute("DELETE FROM sync_state WHERE key = 'gamma_market_history_backfill_closed'")
    conn.commit()
    try:
        payload = subject._build_market_data_quality_payload(_dependencies(conn))
    finally:
        conn.close()

    gamma = next(
        item for item in payload["terminalLedgers"] if item["id"] == "gamma-history"
    )
    streams = {item["id"]: item for item in gamma["metrics"]["streams"]}
    assert streams["open"]["terminal"] is True
    assert streams["closed"]["terminal"] is False
    assert streams["closed"]["status"] == "unknown"
    assert gamma["terminal"] is False
    assert gamma["marketKeysetGateSatisfied"] is False
    assert gamma["gateSatisfied"] is False


def test_market_history_uses_current_epoch_residuals_and_authoritative_tail() -> None:
    conn = _database()
    conn.execute(
        """
        INSERT INTO gamma_market_history_residuals VALUES (
            'gamma_market_history_backfill', 'open', 'old-draft',
            'old_epoch_only', '{}', 'old-residual-sha',
            'classified_residual', 7, ?, ?, ?, ?
        )
        """,
        (
            "2026-08-01T00:00:00Z",
            "2026-08-01T00:00:00Z",
            "2026-08-01T00:00:00Z",
            "2026-08-01T00:00:00Z",
        ),
    )
    conn.commit()
    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    gamma = next(
        item for item in payload["terminalLedgers"] if item["id"] == "gamma-history"
    )
    assert gamma["marketKeysetGateSatisfied"] is True
    open_stream = next(
        stream for stream in gamma["metrics"]["streams"] if stream["id"] == "open"
    )
    assert open_stream["residualLedger"]["reasonCounts"] == {
        "missing_condition_identity": 1
    }

    conn.execute(
        """
        UPDATE gamma_market_history_commits
        SET receipt_sha256 = ?
        WHERE source_filter = 'open'
        """,
        ("f" * 64,),
    )
    conn.commit()
    corrupted = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    corrupted_gamma = next(
        item for item in corrupted["terminalLedgers"] if item["id"] == "gamma-history"
    )
    corrupted_open = next(
        stream
        for stream in corrupted_gamma["metrics"]["streams"]
        if stream["id"] == "open"
    )
    assert corrupted_gamma["marketKeysetGateSatisfied"] is False
    assert corrupted_open["authorityTailValid"] is True
    assert corrupted_open["authorityValid"] is False
    assert "authority-receipt-invalid-batch-1" in corrupted_open["errors"]


def test_closed_market_and_event_streams_must_match_current_open_prerequisite() -> None:
    conn = _database()
    for key in (
        "gamma_market_history_backfill_closed",
        "gamma_event_history_backfill_closed",
    ):
        row = conn.execute("SELECT value FROM sync_state WHERE key = ?", (key,)).fetchone()
        state = json.loads(row[0])
        state["open_prerequisite_evidence"]["last_commit_sha256"] = "e" * 64
        conn.execute(
            "UPDATE sync_state SET value = ? WHERE key = ?",
            (json.dumps(state), key),
        )
    conn.commit()
    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    ledgers = {item["id"]: item for item in payload["terminalLedgers"]}
    assert ledgers["gamma-history"]["marketKeysetGateSatisfied"] is False
    assert ledgers["gamma-event-history"]["gateSatisfied"] is False
    for ledger_id in ("gamma-history", "gamma-event-history"):
        closed = next(
            stream
            for stream in ledgers[ledger_id]["metrics"]["streams"]
            if stream["id"] == "closed"
        )
        assert closed["status"] == "open-prerequisite-mismatch"
        assert closed["openPrerequisiteSatisfied"] is False


def test_event_gate_requires_current_epoch_authoritative_commit_tail() -> None:
    conn = _database()
    conn.execute(
        "DELETE FROM gamma_event_history_commits WHERE source_filter = 'open'"
    )
    conn.commit()
    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    event_history = next(
        item
        for item in payload["terminalLedgers"]
        if item["id"] == "gamma-event-history"
    )
    open_stream = next(
        stream
        for stream in event_history["metrics"]["streams"]
        if stream["id"] == "open"
    )
    assert event_history["terminal"] is True
    assert event_history["gateSatisfied"] is False
    assert open_stream["authorityTailValid"] is False
    assert "authority-commit-count-mismatch" in open_stream["errors"]
    assert "authority-tail-state-mismatch" in open_stream["errors"]


def test_v4_current_epoch_rejects_checksum_valid_legacy_v3_tail() -> None:
    conn = _database()
    row = conn.execute(
        """
        SELECT receipt_json
        FROM gamma_market_history_commits
        WHERE source_filter = 'open'
        """
    ).fetchone()
    receipt = json.loads(row["receipt_json"])
    receipt["schema_version"] = "gamma-history-commit-v3"
    core = {key: value for key, value in receipt.items() if key != "commit_sha256"}
    receipt["commit_sha256"] = subject._sha256_json(core)
    conn.execute(
        """
        UPDATE gamma_market_history_commits
        SET receipt_sha256 = ?, receipt_json = ?
        WHERE source_filter = 'open'
        """,
        (
            receipt["commit_sha256"],
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        ),
    )
    state_row = conn.execute(
        "SELECT value FROM sync_state WHERE key = 'gamma_market_history_backfill'"
    ).fetchone()
    state = json.loads(state_row["value"])
    state["last_commit_sha256"] = receipt["commit_sha256"]
    conn.execute(
        "UPDATE sync_state SET value = ? WHERE key = 'gamma_market_history_backfill'",
        (json.dumps(state),),
    )
    conn.commit()

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    gamma = next(
        item for item in payload["terminalLedgers"] if item["id"] == "gamma-history"
    )
    open_stream = next(
        stream for stream in gamma["metrics"]["streams"] if stream["id"] == "open"
    )
    assert open_stream["authorityTailValid"] is True
    assert open_stream["gateSatisfied"] is False
    assert "authority-receipt-invalid-batch-1" in open_stream["errors"]


def test_v4_event_observation_relationship_and_db_evidence_hash_are_verified() -> None:
    conn = _database()
    conn.execute(
        """
        UPDATE gamma_event_history_observations
        SET relationship_sha256 = ?
        WHERE source_filter = 'open'
        """,
        ("f" * 64,),
    )
    conn.commit()

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    event_history = next(
        item
        for item in payload["terminalLedgers"]
        if item["id"] == "gamma-event-history"
    )
    open_stream = next(
        stream
        for stream in event_history["metrics"]["streams"]
        if stream["id"] == "open"
    )
    assert event_history["gateSatisfied"] is False
    assert "event-relationship-sha-invalid-batch-1-row-0" in open_stream["errors"]
    assert "observation-ledger-evidence-invalid-batch-1" in open_stream["errors"]


def test_v4_observation_state_receipt_and_database_counts_must_conserve() -> None:
    conn = _database()
    row = conn.execute(
        "SELECT value FROM sync_state WHERE key = 'gamma_market_history_backfill'"
    ).fetchone()
    state = json.loads(row["value"])
    state["observation_count"] = 2
    conn.execute(
        "UPDATE sync_state SET value = ? WHERE key = 'gamma_market_history_backfill'",
        (json.dumps(state),),
    )
    conn.commit()

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    gamma = next(
        item for item in payload["terminalLedgers"] if item["id"] == "gamma-history"
    )
    open_stream = next(
        stream for stream in gamma["metrics"]["streams"] if stream["id"] == "open"
    )
    assert gamma["gateSatisfied"] is False
    assert open_stream["observationLedger"] == {
        "tablePresent": True,
        "availability": "available",
        "unavailableReason": None,
        "dbObservationCount": 1,
        "receiptObservationCount": 1,
        "stateObservationCount": 2,
        "accountingSatisfied": False,
        "reconstructionScope": "identity_and_hash_only",
        "fullSourcePayloadReconstructable": False,
        "tailObservationCount": 1,
        "tailEvidenceShaVerified": True,
        "invalidRelationshipShaLengthCount": None,
        "fullObservationDigestRecomputed": False,
        "validationScope": "all_batch_counts_plus_tail_digest",
    }
    assert "current-epoch-observation-accounting-mismatch" in open_stream["errors"]


def test_v4_composite_gate_stays_unavailable_without_offline_receipt() -> None:
    conn = _database()
    conn.execute(
        """
        UPDATE gamma_event_history_observations
        SET no_token_id = 'no-conflicting-source-slot'
        WHERE source_filter = 'open'
        """
    )
    observation = conn.execute(
        f"""
        SELECT {', '.join(subject._EVENT_OBSERVATION_FIELDS)}
        FROM gamma_event_history_observations
        WHERE source_filter = 'open'
        """
    ).fetchone()
    observation_evidence_sha = subject._sha256_json(
        [
            {
                field: observation[field]
                for field in subject._EVENT_OBSERVATION_FIELDS
            }
        ]
    )
    receipt_row = conn.execute(
        """
        SELECT receipt_json FROM gamma_event_history_commits
        WHERE source_filter = 'open'
        """
    ).fetchone()
    receipt = json.loads(receipt_row["receipt_json"])
    receipt["observation_evidence_sha256"] = observation_evidence_sha
    receipt["observation_ledger_postcheck"][
        "evidence_sha256"
    ] = observation_evidence_sha
    core = {key: value for key, value in receipt.items() if key != "commit_sha256"}
    receipt["commit_sha256"] = subject._sha256_json(core)
    conn.execute(
        """
        UPDATE gamma_event_history_commits
        SET receipt_sha256 = ?, receipt_json = ?
        WHERE source_filter = 'open'
        """,
        (
            receipt["commit_sha256"],
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        ),
    )
    state_row = conn.execute(
        "SELECT value FROM sync_state WHERE key = 'gamma_event_history_backfill'"
    ).fetchone()
    open_state = json.loads(state_row["value"])
    open_state["last_commit_sha256"] = receipt["commit_sha256"]
    open_state[
        "last_commit_observation_evidence_sha256"
    ] = observation_evidence_sha
    conn.execute(
        "UPDATE sync_state SET value = ? WHERE key = 'gamma_event_history_backfill'",
        (json.dumps(open_state),),
    )

    prerequisite = {
        "sync_state_key": "gamma_event_history_backfill",
        "source_filter": "open",
        "epoch_started_at": open_state["epoch_started_at"],
        "completed_at": open_state["completed_at"],
        "last_commit_sha256": open_state["last_commit_sha256"],
        "source_events": open_state["source_events"],
        "embedded_markets": open_state["embedded_markets"],
        "observation_count": open_state["observation_count"],
        "last_commit_observation_evidence_sha256": observation_evidence_sha,
        "state_sha256": subject._sha256_json(open_state),
        "terminal": True,
        "event_keyset_accounted": True,
        "absolute_gamma_history_completeness_claimed": False,
    }
    closed_state_row = conn.execute(
        """
        SELECT value FROM sync_state
        WHERE key = 'gamma_event_history_backfill_closed'
        """
    ).fetchone()
    closed_state = json.loads(closed_state_row["value"])
    closed_state["open_prerequisite_evidence"] = prerequisite
    closed_receipt_row = conn.execute(
        """
        SELECT receipt_json FROM gamma_event_history_commits
        WHERE source_filter = 'closed'
        """
    ).fetchone()
    closed_receipt = json.loads(closed_receipt_row["receipt_json"])
    closed_receipt["open_prerequisite_evidence"] = prerequisite
    closed_core = {
        key: value
        for key, value in closed_receipt.items()
        if key != "commit_sha256"
    }
    closed_receipt["commit_sha256"] = subject._sha256_json(closed_core)
    closed_state["last_commit_sha256"] = closed_receipt["commit_sha256"]
    conn.execute(
        """
        UPDATE gamma_event_history_commits
        SET receipt_sha256 = ?, receipt_json = ?
        WHERE source_filter = 'closed'
        """,
        (
            closed_receipt["commit_sha256"],
            json.dumps(closed_receipt, sort_keys=True, separators=(",", ":")),
        ),
    )
    conn.execute(
        """
        UPDATE sync_state SET value = ?
        WHERE key = 'gamma_event_history_backfill_closed'
        """,
        (json.dumps(closed_state),),
    )
    conn.commit()

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    ledgers = {item["id"]: item for item in payload["terminalLedgers"]}
    assert ledgers["gamma-event-history"]["gateSatisfied"] is True
    composite = ledgers["gamma-history"]["metrics"]["compositeObservation"]
    assert composite["availability"] == "unavailable"
    assert composite["unavailableReason"] == (
        "offline-composite-reconciliation-not-materialized"
    )
    assert composite["gateSatisfied"] is False
    assert ledgers["gamma-history"]["gateSatisfied"] is False


def test_v4_consumes_checksum_pinned_offline_composite_receipt() -> None:
    conn = _database()
    receipt = _install_history_composite_receipt(conn)
    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()

    gamma = next(
        item for item in payload["terminalLedgers"] if item["id"] == "gamma-history"
    )
    composite = gamma["metrics"]["compositeObservation"]
    assert gamma["gateSatisfied"] is True
    assert gamma["status"] == "operational-authority-satisfied"
    assert composite["availability"] == "available"
    assert composite["receiptSha256"] == receipt["receipt_sha256"]
    assert composite["gateSatisfied"] is True
    assert composite["countConservationSatisfied"] is True
    assert composite["exactCompositeJoinCount"] == 2
    assert composite["sharedIdentityConflictCount"] == 0
    assert composite["fullObservationDigestRecomputed"] is True
    assert composite["validationScope"] == (
        "offline-repeatable-read-full-four-epoch-digests-exact-identity-join"
    )
    assert composite["sourceSnapshotCutoffClaimed"] is False
    assert composite["sameSourceFrozenSnapshotClaimed"] is False
    assert composite["absoluteGammaHistoryCompletenessClaimed"] is False
    # Even an operationally reconciled mutable traversal is not absolute Gamma
    # history completeness because Gamma publishes no frozen cutoff.
    assert payload["historicalCompleteness"]["claimed"] is False


def test_v4_rejects_composite_receipt_without_manifest_tail_ack() -> None:
    conn = _database()
    _install_history_composite_receipt(conn)
    conn.execute(
        "UPDATE gamma_history_composite_receipts SET manifest_tail_sha256 = ?",
        ("0" * 64,),
    )
    conn.commit()
    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()

    gamma = next(
        item for item in payload["terminalLedgers"] if item["id"] == "gamma-history"
    )
    composite = gamma["metrics"]["compositeObservation"]
    assert gamma["gateSatisfied"] is False
    assert composite["availability"] == "unavailable"
    assert composite["unavailableReason"] == "offline-composite-receipt-invalid"
    assert "receipt-db-manifest-checksum-invalid" in composite["errors"]


def test_v4_stream_tail_accepts_extended_source_token_semantics_projection() -> None:
    conn = _database()
    for column in (
        "ordered_token_ids_json TEXT",
        "ordered_outcomes_json TEXT",
        "token_semantics_classification TEXT",
        "logical_mapping_reason TEXT",
    ):
        conn.execute(f"ALTER TABLE gamma_market_history_observations ADD COLUMN {column}")
    conn.execute(
        """
        UPDATE gamma_market_history_observations
        SET ordered_token_ids_json = ?, ordered_outcomes_json = ?,
            token_semantics_classification = ?, logical_mapping_reason = ?
        WHERE source_filter = 'open'
        """,
        (
            json.dumps(["yes-shared-open", "no-shared-open"]),
            json.dumps(["Yes", "No"]),
            "binary_yes_no_labels",
            "source_outcome_labels",
        ),
    )
    observation = conn.execute(
        f"""
        SELECT {', '.join(subject._MARKET_OBSERVATION_FIELDS_EXTENDED)}
        FROM gamma_market_history_observations
        WHERE source_filter = 'open'
        """
    ).fetchone()
    assert observation is not None
    evidence_sha = subject._sha256_json(
        [
            {
                field: observation[field]
                for field in subject._MARKET_OBSERVATION_FIELDS_EXTENDED
            }
        ]
    )
    receipt_row = conn.execute(
        """
        SELECT receipt_json FROM gamma_market_history_commits
        WHERE source_filter = 'open'
        """
    ).fetchone()
    receipt = json.loads(receipt_row[0])
    receipt["observation_evidence_kind"] = (
        "market_identity_source_token_semantics_projection"
    )
    receipt["token_semantics_classification_counts"] = {
        "binary_yes_no_labels": 1
    }
    receipt["observation_evidence_sha256"] = evidence_sha
    receipt["observation_ledger_postcheck"]["evidence_sha256"] = evidence_sha
    receipt["observation_ledger_postcheck"][
        "token_semantics_classification_counts"
    ] = {"binary_yes_no_labels": 1}
    core = {key: value for key, value in receipt.items() if key != "commit_sha256"}
    receipt["commit_sha256"] = subject._sha256_json(core)
    conn.execute(
        """
        UPDATE gamma_market_history_commits
        SET receipt_sha256 = ?, receipt_json = ?
        WHERE source_filter = 'open'
        """,
        (
            receipt["commit_sha256"],
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        ),
    )
    state_row = conn.execute(
        "SELECT value FROM sync_state WHERE key = 'gamma_market_history_backfill'"
    ).fetchone()
    state = json.loads(state_row[0])
    state["last_commit_sha256"] = receipt["commit_sha256"]
    state["last_commit_observation_evidence_sha256"] = evidence_sha
    conn.execute(
        "UPDATE sync_state SET value = ? WHERE key = 'gamma_market_history_backfill'",
        (json.dumps(state, sort_keys=True, separators=(",", ":")),),
    )
    conn.commit()

    dependencies = _dependencies(conn)
    spec = subject._HISTORY_STREAM_SPECS[0]
    watermark = {
        "id": "gamma-history-open",
        "key": "gamma_market_history_backfill",
        "lastBlock": state["pages"],
        "updatedAt": "2026-08-27T00:00:00Z",
        "state": state,
    }
    evidence = subject._history_stream_evidence(dependencies, watermark, spec)
    validated = subject._validate_history_stream(
        watermark=watermark,
        evidence=evidence,
        spec=spec,
    )
    conn.close()

    assert validated["gateSatisfied"] is True
    assert validated["observationLedger"]["tailEvidenceShaVerified"] is True
    assert validated["errors"] == []


def test_v4_source_partition_endpoint_is_receipt_scoped_and_fail_closed() -> None:
    conn = _database()
    row = conn.execute(
        """
        SELECT receipt_json
        FROM gamma_event_history_commits
        WHERE source_filter = 'open'
        """
    ).fetchone()
    receipt = json.loads(row["receipt_json"])
    invalid_partition = {
        "endpoint": "https://gamma-api.polymarket.com/not-events",
        "source_filter": "open",
        "closed": False,
    }
    receipt["source_request_partition"] = invalid_partition
    receipt["page_traversal_evidence"][0][
        "source_request_partition"
    ] = invalid_partition
    receipt["page_traversal_evidence_sha256"] = subject._sha256_json(
        receipt["page_traversal_evidence"]
    )
    core = {key: value for key, value in receipt.items() if key != "commit_sha256"}
    receipt["commit_sha256"] = subject._sha256_json(core)
    conn.execute(
        """
        UPDATE gamma_event_history_commits
        SET receipt_sha256 = ?, receipt_json = ?
        WHERE source_filter = 'open'
        """,
        (
            receipt["commit_sha256"],
            json.dumps(receipt, sort_keys=True, separators=(",", ":")),
        ),
    )
    state_row = conn.execute(
        "SELECT value FROM sync_state WHERE key = 'gamma_event_history_backfill'"
    ).fetchone()
    state = json.loads(state_row["value"])
    state["last_commit_sha256"] = receipt["commit_sha256"]
    conn.execute(
        "UPDATE sync_state SET value = ? WHERE key = 'gamma_event_history_backfill'",
        (json.dumps(state),),
    )
    conn.commit()

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    event_history = next(
        item
        for item in payload["terminalLedgers"]
        if item["id"] == "gamma-event-history"
    )
    open_stream = next(
        stream
        for stream in event_history["metrics"]["streams"]
        if stream["id"] == "open"
    )
    assert open_stream["authorityTailValid"] is True
    assert "source-request-partition-invalid-batch-1" in open_stream["errors"]
    assert "page-traversal-row-invalid-batch-1-page-0" in open_stream["errors"]


def test_token_gate_rejects_incremental_only_and_broken_rolling_chain() -> None:
    for mutation in (
        {
            "coverage_start": 4,
            "audit_lo": 4,
            "previous_audit_hi": None,
            "cycle_number": 1,
        },
        {
            "coverage_start": 1,
            "audit_lo": 4,
            "previous_audit_hi": 2,
            "cycle_number": 2,
        },
    ):
        conn = _database()
        row = conn.execute(
            "SELECT value FROM sync_state WHERE key = 'market_tokens_backfill_v1'"
        ).fetchone()
        state = {**json.loads(row[0]), **mutation}
        conn.execute(
            "UPDATE sync_state SET value = ? WHERE key = 'market_tokens_backfill_v1'",
            (json.dumps(state),),
        )
        conn.commit()
        payload = subject._build_market_data_quality_payload(_dependencies(conn))
        conn.close()
        gate = next(
            item
            for item in payload["terminalLedgers"]
            if item["id"] == "token-registry-backfill"
        )
        assert gate["gateSatisfied"] is False
        assert gate["metrics"]["rollingChainValid"] is False


def test_canonical_gate_reconciles_current_cycle_state_receipts_and_ledger() -> None:
    conn = _database()
    conn.execute(
        """
        UPDATE market_canonical_identity_reconciliation
        SET classification = 'ambiguous'
        WHERE market_id = 3
        """
    )
    conn.commit()
    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    canonical = next(
        item
        for item in payload["terminalLedgers"]
        if item["id"] == "canonical-identity-reconciliation"
    )
    assert canonical["terminal"] is True
    assert canonical["gateSatisfied"] is False
    assert canonical["metrics"]["receiptTailValid"] is True
    assert canonical["metrics"]["classificationCountsReconciled"] is False
    assert "classification-counts-mismatch" in canonical["metrics"]["errors"]


def test_source_semantics_gate_rejects_ledger_receipt_orphan() -> None:
    conn = _database()
    conn.execute(
        """
        UPDATE market_source_semantics_reconciliation
        SET receipt_sha256 = ?
        WHERE market_id = 2
        """,
        ("f" * 64,),
    )
    conn.commit()

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    gate = next(
        item
        for item in payload["terminalLedgers"]
        if item["id"] == "source-semantics-reconciliation"
    )
    assert gate["terminal"] is True
    assert gate["gateSatisfied"] is False
    assert gate["metrics"]["classificationCountsReconciled"] is True
    assert gate["metrics"]["ledgerReceiptConserved"] is False
    assert "ledger-receipt-conservation-mismatch" in gate["metrics"]["errors"]


def test_source_semantics_terminal_residuals_remain_explicit_not_repaired() -> None:
    conn = _database()
    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    gate = next(
        item
        for item in payload["terminalLedgers"]
        if item["id"] == "source-semantics-reconciliation"
    )
    assert gate["terminal"] is True
    assert gate["classificationGateSatisfied"] is True
    assert gate["gateSatisfied"] is False
    assert gate["status"] == "terminal-with-classified-residuals"
    assert gate["metrics"]["terminalResidualCount"] == 1
    assert gate["metrics"]["retryCount"] == 0
    assert gate["metrics"]["classificationCounts"]["source_clob_absent"] == 1
    assert "not reported as repaired semantics" in gate["detail"]
    gaps = {item["id"]: item for item in payload["gaps"]}
    assert gaps["source-semantics-terminal-residuals"]["severity"] == "critical"
    assert gaps["source-semantics-terminal-residuals"]["count"] == 1
    assert "source-semantics-reconciliation-not-terminal" not in gaps


def test_source_semantics_retry_is_not_counted_as_terminal_residual() -> None:
    cycle_id = "source-semantics-retry-cycle"
    receipt = _source_semantics_receipt(cycle_id)
    counts = {
        "resolved": 1,
        "source_clob_absent": 0,
        "source_not_found": 0,
        "source_identity_mismatch": 0,
        "ownership_conflict": 0,
        "superseded_duplicate": 0,
        "retry": 1,
    }
    receipt["classification_counts"] = counts
    receipt_core = {
        key: value for key, value in receipt.items() if key != "receipt_sha256"
    }
    receipt["receipt_sha256"] = subject._sha256_json(receipt_core)
    watermark = {
        "lastBlock": 5,
        "state": {
            "schema_version": "market-source-semantics-reconciliation-v1",
            "cycle_id": cycle_id,
            "status": "complete",
            "audit_lo": 1,
            "audit_hi": 5,
            "checkpoint": 5,
            "candidate_count": 2,
            "classification_counts": counts,
            "batch_number": 1,
            "last_receipt_sha256": receipt["receipt_sha256"],
            "completed_at": "2026-08-27T00:00:01Z",
        },
    }
    metric = {
        "availability": "available",
        "ledgerTablePresent": True,
        "receiptTablePresent": True,
        "classificationCounts": counts,
        "classifiedCount": 2,
        "invalidClassificationCount": 0,
        "orphanReceiptReferenceCount": 0,
        "invalidReceiptReferenceCount": 0,
        "receiptCount": 1,
        "receiptRows": [
            {
                "receipt_sha256": receipt["receipt_sha256"],
                "cycle_id": cycle_id,
                "batch_number": 1,
                "previous_receipt_sha256": None,
                "record_json": receipt,
            }
        ],
    }

    validation = subject._validate_source_semantics_cycle(
        watermark=watermark,
        metric=metric,
        max_market_id=5,
    )

    assert validation["rangeTerminal"] is True
    assert validation["classificationGateSatisfied"] is False
    assert validation["gateSatisfied"] is False
    assert validation["retryCount"] == 1
    assert validation["terminalResidualCount"] == 0


def test_canonical_gate_rejects_legacy_candidate_contract_state() -> None:
    conn = _database()
    state = _read_canonical_state(conn)
    state["candidate_contract_version"] = 1
    _write_canonical_state(conn, state)

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    canonical = _canonical_gate(payload)

    assert canonical["terminal"] is True
    assert canonical["gateSatisfied"] is False
    assert canonical["metrics"]["candidateContractVersion"] == 1
    assert canonical["metrics"]["candidateContractVersionValid"] is False
    assert "candidate-contract-state-version-mismatch" in canonical["metrics"][
        "errors"
    ]


def test_canonical_gate_rejects_legacy_candidate_contract_batch_receipt() -> None:
    conn = _database()
    row = conn.execute(
        """
        SELECT receipt_sha256, record_json
        FROM market_canonical_identity_reconciliation_receipts
        WHERE event = 'batch_verified'
        """
    ).fetchone()
    assert row is not None
    record = json.loads(row["record_json"])
    record["candidate_contract_version"] = 1
    core = {
        key: value
        for key, value in record.items()
        if key not in {"receipt_sha256", "event", "run_id"}
    }
    replacement_sha256 = subject._sha256_json(core)
    record["receipt_sha256"] = replacement_sha256
    conn.execute(
        """
        UPDATE market_canonical_identity_reconciliation_receipts
        SET receipt_sha256 = ?, record_json = ?
        WHERE receipt_sha256 = ?
        """,
        (
            replacement_sha256,
            json.dumps(record, sort_keys=True, separators=(",", ":")),
            row["receipt_sha256"],
        ),
    )
    state = _read_canonical_state(conn)
    state["last_receipt_sha256"] = replacement_sha256
    _write_canonical_state(conn, state)

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    canonical = _canonical_gate(payload)

    assert canonical["gateSatisfied"] is False
    assert canonical["metrics"]["receiptTailValid"] is True
    assert canonical["metrics"]["receiptCandidateContractVersions"] == [1]
    assert canonical["metrics"]["receiptCandidateContractsValid"] is False
    assert (
        "candidate-contract-receipt-version-mismatch-batch-1"
        in canonical["metrics"]["errors"]
    )


def test_canonical_gate_validates_durable_explicit_supersede_receipt() -> None:
    conn = _database()
    restart_receipt = _install_canonical_restart_evidence(conn)

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    canonical = _canonical_gate(payload)

    assert canonical["gateSatisfied"] is True
    assert canonical["metrics"]["candidateContractVersion"] == 2
    assert canonical["metrics"]["receiptCandidateContractVersions"] == [2]
    assert canonical["metrics"]["restartReceiptRequired"] is True
    assert canonical["metrics"]["restartReceiptValid"] is True
    assert canonical["metrics"]["restartReceiptSha256"] == restart_receipt[
        "receipt_sha256"
    ]
    assert canonical["metrics"]["supersededCycleId"] == (
        "canonical-legacy-cycle"
    )


def test_canonical_gate_rejects_supersede_receipt_without_state_marker() -> None:
    conn = _database()
    _install_canonical_restart_evidence(conn)
    state = _read_canonical_state(conn)
    for field in (
        "candidate_contract_restart_receipt_sha256",
        "superseded_cycle_id",
        "superseded_candidate_contract_version",
        "candidate_contract_restarted_at",
    ):
        state.pop(field)
    _write_canonical_state(conn, state)

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    canonical = _canonical_gate(payload)

    assert canonical["gateSatisfied"] is False
    assert canonical["metrics"]["restartReceiptRequired"] is True
    assert canonical["metrics"]["restartReceiptValid"] is False
    assert (
        "candidate-contract-restart-state-marker-invalid"
        in canonical["metrics"]["errors"]
    )


def test_canonical_gate_rejects_restart_sha_mismatch() -> None:
    conn = _database()
    _install_canonical_restart_evidence(conn)
    state = _read_canonical_state(conn)
    state["candidate_contract_restart_receipt_sha256"] = "f" * 64
    _write_canonical_state(conn, state)

    payload = subject._build_market_data_quality_payload(_dependencies(conn))
    conn.close()
    canonical = _canonical_gate(payload)

    assert canonical["gateSatisfied"] is False
    assert canonical["metrics"]["restartReceiptRequired"] is True
    assert canonical["metrics"]["restartReceiptValid"] is False
    assert (
        "candidate-contract-restart-receipt-invalid"
        in canonical["metrics"]["errors"]
    )


def test_query_failure_preserves_last_good_and_exposes_error_without_empty_cache() -> None:
    conn = _database()
    base = _dependencies(conn)


    def build_now(
        _namespace: str,
        _key: str,
        builder: Any,
        *,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        assert ttl_seconds == 300
        return builder()

    base_context = {
        "app": base.application,
        "query_one": base.query_one,
        "query_all": base.query_all,
        "table_exists": base.table_exists,
        "get_snapshot_payload": build_now,
        "get_recent_oracle_snapshot": base.get_recent_oracle_snapshot,
        "utc_now_iso": base.utc_now_iso,
    }
    good = subject.get_market_data_quality_payload(base_context)
    assert good["summary"]["marketCount"] == 5

    def query_all_unavailable(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        if "gamma_market_history_residuals" in sql:
            raise sqlite3.OperationalError("simulated optional-ledger failure")
        return base.query_all(sql, params)

    try:
        payload = subject.get_market_data_quality_payload(
            {**base_context, "query_all": query_all_unavailable}
        )
    finally:
        conn.close()

    assert payload["summary"]["marketCount"] == 5
    assert payload["snapshotHealth"]["status"] == "stale-last-good"
    assert payload["snapshotHealth"]["error"] == {
        "code": "market-quality-query-failed",
        "operation": "detail-query",
        "type": "OperationalError",
        "observedAt": "2026-08-27T00:05:00Z",
    }
    assert payload["historicalCompleteness"]["claimed"] is False
    assert payload["gaps"][0]["id"] == "market-quality-query-failed"
    assert all(
        gate["gateSatisfied"] is False for gate in payload["terminalLedgers"]
    )


def test_v4_missing_ledgers_remain_unknown_instead_of_implying_completion() -> None:
    dependencies = subject.MarketQualityDependencies(
        resources=RuntimeResources(),
        application=SimpleNamespace(logger=_Logger()),
        query_one=lambda *_args, **_kwargs: {},
        query_all=lambda *_args, **_kwargs: [],
        table_exists=lambda _name: False,
        get_snapshot_payload=lambda *_args, **_kwargs: {},
        get_recent_oracle_snapshot=lambda limit: [],
        utc_now_iso=lambda: "2026-08-27T00:05:00Z",
    )

    payload = subject._build_market_data_quality_payload(dependencies)

    assert payload["marketUniverse"]["discoveredTotal"] == 0
    assert all(item["gateSatisfied"] is False for item in payload["terminalLedgers"])
    assert all(item["status"] == "unknown" for item in payload["terminalLedgers"])
    assert payload["historicalCompleteness"]["claimed"] is False


def test_get_payload_uses_v4_cache_key() -> None:

    captured: dict[str, Any] = {}

    def get_snapshot_payload(
        namespace: str,
        key: str,
        builder: Any,
        *,
        ttl_seconds: int,
    ) -> dict[str, Any]:
        captured.update(
            namespace=namespace,
            key=key,
            builder=builder,
            ttl_seconds=ttl_seconds,
        )
        return {"cached": True}

    payload = subject.get_market_data_quality_payload(
        {
            "app": SimpleNamespace(logger=_Logger()),
            "query_one": lambda *_args, **_kwargs: {},
            "query_all": lambda *_args, **_kwargs: [],
            "table_exists": lambda _name: False,
            "get_snapshot_payload": get_snapshot_payload,
            "get_recent_oracle_snapshot": lambda limit: [],
            "utc_now_iso": lambda: "2026-08-27T00:05:00Z",
        }
    )

    assert payload == {"cached": True}
    assert captured["namespace"] == "snapshot:market_data_quality"
    assert captured["key"] == "v4-observation-authority-gates"
    assert captured["ttl_seconds"] == 300
    assert callable(captured["builder"])
