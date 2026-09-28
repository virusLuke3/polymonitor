from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from typing import Any

import pytest


from market import market_token_source_label_projection as projection  # noqa: E402


CONDITION = "0x" + "ab" * 32
TOKEN_A = "1000000000000000000000000000000000000001"
TOKEN_B = "2000000000000000000000000000000000000002"


class _FakeTransactionStatus:
    def __init__(self, name: str, code: int) -> None:
        self.name = name
        self.code = code

    def __int__(self) -> int:
        return self.code


class _FakePostgresInfo:
    def __init__(self) -> None:
        self.transaction_status = _FakeTransactionStatus("IDLE", 0)


class _FakePostgresRawConnection:
    def __init__(self) -> None:
        self.info = _FakePostgresInfo()


class _FakePostgresCursor:
    def __init__(self, rows: list[Any] | None = None, *, rowcount: int = 0) -> None:
        self.rows = list(rows or [])
        self.rowcount = rowcount

    def fetchone(self) -> Any:
        return self.rows[0] if self.rows else None

    def fetchall(self) -> list[Any]:
        return list(self.rows)


class UndefinedTable(Exception):
    sqlstate = "42P01"


class PostgresConnectionWrapper:
    """Catalog-contract fake; the class name is part of the supported seam."""

    def __init__(self) -> None:
        self._pg_conn = _FakePostgresRawConnection()
        self.executed: list[tuple[str, Any]] = []
        self.extra_trigger = False
        self.unlogged_relation = False
        self.wrong_default = False
        self.invalid_constraint = False
        self.lowercase_check_literal = False
        self.ordinary_trigger = False
        self.inheritance_parent = False
        self.inheritance_child = False
        self.missing_projection_schema = False
        self.session_current_role_mismatch = False
        self.session_privileged_role = False
        self.authenticated_admin_session = False
        self.settable_privileged_role = False
        self.settable_nonprivileged_role = False
        self.schema_owner_membership = False
        self.schema_create = False
        self.table_owner_membership = False
        self.table_mutation_privilege = False
        self.table_column_update_privilege = False
        self.function_owner_membership = False

    def execute(self, query: str, params: Any = None) -> _FakePostgresCursor:
        normalized = " ".join(query.split())
        self.executed.append((normalized, params))
        if normalized.startswith("BEGIN TRANSACTION"):
            self._pg_conn.info.transaction_status = _FakeTransactionStatus("INTRANS", 2)
            return _FakePostgresCursor()
        if normalized.startswith("LOCK TABLE ") and self.missing_projection_schema:
            raise UndefinedTable("projection schema absent")
        if normalized.startswith("CREATE TABLE"):
            self.missing_projection_schema = False
            return _FakePostgresCursor()
        if normalized.startswith("SELECT to_regclass"):
            return _FakePostgresCursor([{"to_regclass": None if self.missing_projection_schema else params[0]}])
        if "FROM pg_catalog.pg_stat_activity backend" in normalized:
            return _FakePostgresCursor(
                [
                    {
                        "authenticated_role": (
                            "bootstrap_admin" if self.authenticated_admin_session else "runtime_writer"
                        ),
                        "session_role": "runtime_writer",
                        "current_role": (
                            "temporary_low_role" if self.session_current_role_mismatch else "runtime_writer"
                        ),
                        "authenticated_is_superuser": (
                            self.authenticated_admin_session or self.session_privileged_role
                        ),
                        "authenticated_can_create_role": False,
                        "authenticated_can_create_database": False,
                        "authenticated_is_replication_role": False,
                        "authenticated_can_bypass_rls": False,
                        "session_is_superuser": (self.session_privileged_role and not self.authenticated_admin_session),
                        "session_can_create_role": False,
                        "session_can_create_database": False,
                        "session_is_replication_role": False,
                        "session_can_bypass_rls": False,
                        "current_is_superuser": (self.session_privileged_role and not self.authenticated_admin_session),
                        "current_can_create_role": False,
                        "current_can_create_database": False,
                        "current_is_replication_role": False,
                        "current_can_bypass_rls": False,
                        "authenticated_is_current_member": True,
                    }
                ]
            )
        if "FROM pg_catalog.pg_roles candidate" in normalized:
            if self.settable_nonprivileged_role:
                return _FakePostgresCursor(
                    [
                        {
                            "role_name": "trigger_manager",
                            "is_superuser": False,
                            "can_create_role": False,
                            "can_create_database": False,
                            "is_replication_role": False,
                            "can_bypass_rls": False,
                        }
                    ]
                )
            return _FakePostgresCursor(
                [
                    {
                        "role_name": "inherited_admin",
                        "is_superuser": True,
                        "can_create_role": False,
                        "can_create_database": False,
                        "is_replication_role": False,
                        "can_bypass_rls": False,
                    }
                ]
                if self.settable_privileged_role
                else []
            )
        if "FROM pg_catalog.pg_namespace namespace" in normalized:
            return _FakePostgresCursor(
                [
                    {
                        "schema_name": schema,
                        "owner_name": "projection_admin",
                        "owner_or_owner_member": self.schema_owner_membership,
                        "can_create": self.schema_create,
                        "can_use": True,
                    }
                    for schema in ("core", "ops")
                ]
            )
        if "FROM pg_catalog.pg_class table_class" in normalized:
            return _FakePostgresCursor(
                [
                    {
                        "table_name": table,
                        "owner_name": "projection_admin",
                        "owner_or_owner_member": self.table_owner_membership,
                        "can_update": self.table_mutation_privilege,
                        "can_update_any_column": self.table_column_update_privilege,
                        "can_delete": self.table_mutation_privilege,
                        "can_truncate": self.table_mutation_privilege,
                        "can_create_trigger": self.table_mutation_privilege,
                    }
                    for table in projection._TABLES
                ]
            )
        if "FROM pg_catalog.pg_proc function_proc" in normalized:
            return _FakePostgresCursor(
                [
                    {
                        "owner_name": "projection_admin",
                        "owner_or_owner_member": self.function_owner_membership,
                    }
                ]
            )
        if "FROM pg_catalog.pg_class c WHERE c.oid" in normalized:
            return _FakePostgresCursor(
                [
                    {
                        "relation_kind": "r",
                        "relation_persistence": "u" if self.unlogged_relation else "p",
                        "is_partition": False,
                        "row_security_enabled": False,
                        "row_security_forced": False,
                        "has_rules": False,
                        "has_no_inheritance_parent": not self.inheritance_parent,
                        "has_no_inheritance_children": not self.inheritance_child,
                    }
                ]
            )
        if "FROM pg_catalog.pg_attribute" in normalized:
            return _FakePostgresCursor(
                [
                    {
                        "column_name": name,
                        "data_type": data_type,
                        "not_null": not_null,
                        "default_expression": (
                            "clock_timestamp()"
                            if self.wrong_default and default_expression == "now()"
                            else default_expression
                        ),
                    }
                    for name, data_type, not_null, default_expression in projection._POSTGRES_COLUMN_CONTRACT[params[0]]
                ]
            )
        if "FROM pg_catalog.pg_constraint" in normalized:
            table = params[0]
            rows = [
                {
                    "constraint_type": kind,
                    "columns": list(columns),
                    "referenced_schema": referenced_schema,
                    "referenced_table": referenced_table,
                    "referenced_columns": list(referenced_columns),
                    "check_expression": None,
                    "constraint_validated": not self.invalid_constraint,
                    "constraint_deferrable": False,
                    "constraint_initially_deferred": False,
                    "foreign_key_update_action": "a" if kind == "f" else " ",
                    "foreign_key_delete_action": "a" if kind == "f" else " ",
                    "foreign_key_match_type": "s" if kind == "f" else " ",
                    "check_no_inherit": False,
                    "constraint_is_local": True,
                    "constraint_inheritance_count": 0,
                }
                for kind, columns, referenced_schema, referenced_table, referenced_columns in projection._POSTGRES_KEY_CONTRACT[
                    table
                ]
            ]
            rows.extend(
                {
                    "constraint_type": "c",
                    "columns": [],
                    "referenced_schema": None,
                    "referenced_table": None,
                    "referenced_columns": [],
                    "check_expression": (
                        expression.replace("PROJECTED", "projected").replace("'YES'", "'yes'").replace("'NO'", "'no'")
                        if self.lowercase_check_literal
                        else expression
                    ),
                    "constraint_validated": not self.invalid_constraint,
                    "constraint_deferrable": False,
                    "constraint_initially_deferred": False,
                    "foreign_key_update_action": " ",
                    "foreign_key_delete_action": " ",
                    "foreign_key_match_type": " ",
                    "check_no_inherit": False,
                    "constraint_is_local": True,
                    "constraint_inheritance_count": 0,
                }
                for expression in projection._POSTGRES_CHECK_CONTRACT[table]
            )
            return _FakePostgresCursor(rows)
        if "FROM pg_catalog.pg_proc p" in normalized:
            return _FakePostgresCursor(
                [
                    {
                        "return_type": "trigger",
                        "language_name": "plpgsql",
                        "function_source": """
                            BEGIN
                                RAISE EXCEPTION 'market token source label projection rows are immutable';
                                RETURN OLD;
                            END;
                        """,
                    }
                ]
            )
        if "FROM pg_catalog.pg_trigger t" in normalized:
            rows = []
            for table in projection._TABLES:
                for name, trigger_type in (
                    (projection._TRIGGER_NAMES[table], 27),
                    (projection._TRUNCATE_TRIGGER_NAMES[table], 34),
                ):
                    rows.append(
                        {
                            "trigger_name": name,
                            "table_name": table,
                            "trigger_type": trigger_type,
                            "trigger_enabled": "O" if self.ordinary_trigger else "A",
                            "function_schema": "ops",
                            "function_name": projection.IMMUTABLE_FUNCTION.split(".", 1)[1],
                            "no_when": True,
                            "arg_count": 0,
                            "all_columns": True,
                        }
                    )
            rows.sort(key=lambda item: (item["table_name"], item["trigger_name"]))
            if self.extra_trigger:
                rows.append(
                    {
                        **rows[0],
                        "trigger_name": "unexpected_extra_trigger",
                    }
                )
            return _FakePostgresCursor(rows)
        return _FakePostgresCursor()

    def rollback(self) -> None:
        self._pg_conn.info.transaction_status = _FakeTransactionStatus("IDLE", 0)

    def commit(self) -> None:
        self._pg_conn.info.transaction_status = _FakeTransactionStatus("IDLE", 0)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("ATTACH DATABASE ':memory:' AS core")
    conn.execute("ATTACH DATABASE ':memory:' AS ops")
    conn.executescript(
        """
        CREATE TABLE core.markets (
            id INTEGER PRIMARY KEY,
            condition_id TEXT NOT NULL UNIQUE,
            yes_token_id TEXT NOT NULL,
            no_token_id TEXT NOT NULL
        );
        CREATE TABLE core.market_tokens (
            id INTEGER PRIMARY KEY,
            market_id INTEGER NOT NULL,
            condition_id TEXT NOT NULL,
            token_id TEXT NOT NULL UNIQUE,
            outcome TEXT NOT NULL,
            outcome_index INTEGER NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO core.markets VALUES (?, ?, ?, ?)",
        (7, CONDITION, TOKEN_A, TOKEN_B),
    )
    conn.executemany(
        "INSERT INTO core.market_tokens VALUES (?, ?, ?, ?, ?, ?)",
        [
            (71, 7, CONDITION, TOKEN_A, "YES", 0),
            (72, 7, CONDITION, TOKEN_B, "NO", 1),
        ],
    )
    conn.commit()
    return conn


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


def _prepare(conn: sqlite3.Connection, record: dict[str, Any] | None = None) -> dict[str, Any]:
    return projection.run_projection(conn, record or _record())


def _apply(conn: sqlite3.Connection, record: dict[str, Any] | None = None) -> dict[str, Any]:
    candidate = record or _record()
    prepared = _prepare(conn, candidate)
    return projection.run_projection(
        conn,
        candidate,
        apply=True,
        expected_plan_sha256=prepared["plan_sha256"],
    )


def test_default_dry_run_is_read_only_and_checksum_pinned() -> None:
    conn = _connection()
    result = _prepare(conn)
    assert result["status"] == "PREPARED"
    assert result["dry_run"] is True
    assert result["market_id"] == 7
    assert len(result["plan_sha256"]) == 64
    assert result["plan"]["record"]["supports_yes_no_wording"] is False
    assert result["plan"]["record"]["supports_directional_semantics"] is False
    assert result["immutability_scope"] == projection.IMMUTABILITY_SCOPE
    assert result["privileged_ddl_resistance"] is False
    assert result["runtime_role_separation_required"] is True
    assert result["runtime_role_separation_verified"] is False
    assert result["plan"]["expected"]["immutability_contract"] == projection._immutability_contract()
    assert projection._schema_presence(conn) is False


def test_apply_requires_exact_fresh_plan_sha() -> None:
    conn = _connection()
    with pytest.raises(projection.ProjectionBlockedError, match="explicit_plan_sha256_required"):
        projection.run_projection(conn, _record(), apply=True)
    assert projection._schema_presence(conn) is False


def test_apply_projects_two_immutable_rows_receipt_and_sync_state() -> None:
    conn = _connection()
    result = _apply(conn)
    assert result["status"] == projection.PROJECTION_STATUS
    assert result["idempotent"] is False
    assert result["projected_token_count"] == 2
    assert result["clickhouse_mutated"] is False
    assert result["immutability_scope"] == projection.IMMUTABILITY_SCOPE
    assert result["privileged_ddl_resistance"] is False
    assert result["runtime_role_separation_verified"] is False
    rows = conn.execute(
        f"SELECT {', '.join(projection.LABEL_COLUMNS)} FROM {projection.LABEL_TABLE} ORDER BY source_index"
    ).fetchall()
    assert [row["source_label"] for row in rows] == ["OVER", "UNDER"]
    assert [row["logical_outcome"] for row in rows] == ["YES", "NO"]
    assert [row["supports_yes_no_wording"] for row in rows] == [0, 0]
    assert [row["supports_directional_semantics"] for row in rows] == [0, 0]
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.RECEIPT_TABLE}").fetchone()[0] == 1
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.SYNC_TABLE}").fetchone()[0] == 1
    for table in (
        projection.LABEL_TABLE,
        projection.RECEIPT_TABLE,
        projection.SYNC_TABLE,
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(f"DELETE FROM {table}")


def test_exact_replay_is_idempotent_and_revalidates_live_rows() -> None:
    conn = _connection()
    first = _apply(conn)
    second = projection.run_projection(
        conn,
        _record(),
        apply=True,
        expected_plan_sha256=first["plan_sha256"],
    )
    assert second["idempotent"] is True
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.LABEL_TABLE}").fetchone()[0] == 2


def test_changed_evidence_cannot_overwrite_existing_projection() -> None:
    conn = _connection()
    _apply(conn)
    changed = _record()
    changed["evidence_sha256"] = "b" * 64
    with pytest.raises(projection.ProjectionBlockedError, match="existing_receipt_identity_conflict"):
        _prepare(conn, changed)
    stored = conn.execute(f"SELECT DISTINCT evidence_sha256 FROM {projection.LABEL_TABLE}").fetchone()[0]
    assert stored == "a" * 64


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("source_token_ids", [TOKEN_A], "source_tokens_not_exact_binary"),
        ("source_token_ids", [TOKEN_A, TOKEN_A], "source_logical_bijection_invalid"),
        ("source_labels", ["same", " SAME "], "source_logical_bijection_invalid"),
        ("source_labels", ["one"], "source_labels_not_exact_binary"),
        ("semantic_mode", "guessed", "unsupported_semantic_mode"),
        ("evidence_sha256", "not-a-sha", "invalid_sha256"),
    ],
)
def test_invalid_binary_or_evidence_shape_is_rejected(field: str, value: Any, reason: str) -> None:
    conn = _connection()
    record = _record()
    record[field] = value
    with pytest.raises(projection.ProjectionBlockedError, match=reason):
        _prepare(conn, record)
    assert projection._schema_presence(conn) is False


def test_explicit_source_slots_are_supported_without_guessing() -> None:
    conn = _connection()
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
        "source_outcome_target_evidence_sha256": projection._sha256(evidence),
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
    record["source_outcome_target_evidence_sha256"] = projection._sha256(evidence)
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
    record["evidence_sha256"] = projection._sha256(record["evidence_payload"])
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
    record["source_outcome_target_evidence_sha256"] = projection._sha256(target_evidence)
    record["evidence_payload"] = {
        "source_token_ids": [TOKEN_A, TOKEN_B],
        "source_outcomes": ["TEAM RED", "TEAM BLUE"],
        "yes_token_id": TOKEN_A,
        "no_token_id": TOKEN_B,
        "logical_mapping_rule": "source_first_second",
    }
    record["evidence_sha256"] = projection._sha256(record["evidence_payload"])
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


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            lambda conn: conn.execute("UPDATE core.market_tokens SET market_id=99 WHERE token_id=?", (TOKEN_A,)),
            "canonical_registry_bijection_mismatch",
        ),
        (
            lambda conn: conn.execute(
                "UPDATE core.market_tokens SET condition_id=? WHERE token_id=?",
                ("0x" + "cd" * 32, TOKEN_A),
            ),
            "canonical_registry_bijection_mismatch",
        ),
        (
            lambda conn: conn.execute(
                "UPDATE core.market_tokens SET outcome='NO', outcome_index=1 WHERE token_id=?",
                (TOKEN_A,),
            ),
            "canonical_registry_bijection_mismatch",
        ),
        (
            lambda conn: conn.execute(
                "INSERT INTO core.market_tokens VALUES (73, 7, ?, 'extra', 'NO', 1)",
                (CONDITION,),
            ),
            "canonical_registry_bijection_mismatch",
        ),
    ],
)
def test_registry_owner_condition_and_logical_bijection_are_strict(mutation: Any, reason: str) -> None:
    conn = _connection()
    mutation(conn)
    conn.commit()
    with pytest.raises(projection.ProjectionBlockedError, match=reason):
        _prepare(conn)


def test_market_condition_and_logical_slot_must_match_record() -> None:
    conn = _connection()
    conn.execute(
        "UPDATE core.markets SET yes_token_id=?, no_token_id=? WHERE id=7",
        (TOKEN_B, TOKEN_A),
    )
    conn.commit()
    with pytest.raises(projection.ProjectionBlockedError, match="canonical_registry_bijection_mismatch"):
        _prepare(conn)


def test_prepared_before_image_drift_rolls_back_without_rows() -> None:
    conn = _connection()
    prepared = _prepare(conn)
    conn.execute("UPDATE core.market_tokens SET id=99 WHERE token_id=?", (TOKEN_A,))
    conn.commit()
    with pytest.raises(projection.ProjectionBlockedError, match="prepared_plan_before_image_drift"):
        projection.apply_projection(conn, prepared["plan"])
    assert projection._schema_presence(conn) is False


def test_tampered_plan_is_rejected_before_schema_creation() -> None:
    conn = _connection()
    prepared = _prepare(conn)
    tampered = deepcopy(prepared["plan"])
    tampered["record"]["source_slots"][0]["source_label"] = "tampered"
    with pytest.raises(projection.ProjectionBlockedError, match="plan_checksum_mismatch"):
        projection.apply_projection(conn, tampered)
    assert projection._schema_presence(conn) is False


def test_fault_after_first_label_insert_rolls_back_entire_projection() -> None:
    conn = _connection()
    prepared = _prepare(conn)
    with pytest.raises(RuntimeError, match="injected failure"):
        projection.apply_projection(conn, prepared["plan"], fault_after_label_insert=1)
    # Transactional SQLite DDL and every inserted row were rolled back.
    assert projection._schema_presence(conn) is False
    assert conn.execute("SELECT COUNT(*) FROM core.market_tokens").fetchone()[0] == 2


def test_partial_or_modified_projection_schema_is_not_repaired_in_place() -> None:
    conn = _connection()
    conn.execute(projection._sqlite_table_ddls()[projection.RECEIPT_TABLE])
    conn.commit()
    with pytest.raises(projection.ProjectionBlockedError, match="incomplete_projection_schema"):
        _prepare(conn)

    conn = _connection()
    projection._begin_transaction(conn, read_only=False)
    projection._ensure_schema(conn)
    conn.commit()
    conn.execute("DROP TRIGGER core.mt_source_labels_reject_mutation_update")
    conn.commit()
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        _prepare(conn)


def test_unreceipted_existing_labels_are_never_overwritten() -> None:
    conn = _connection()
    projection._begin_transaction(conn, read_only=False)
    projection._ensure_schema(conn)
    conn.execute(
        f"INSERT INTO {projection.LABEL_TABLE} ({', '.join(projection.LABEL_COLUMNS)}) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            TOKEN_A,
            7,
            CONDITION,
            0,
            "OLD",
            "YES",
            0,
            "source_first_second",
            False,
            False,
            "old-origin",
            "b" * 64,
            "c" * 64,
        ),
    )
    conn.commit()
    with pytest.raises(projection.ProjectionBlockedError, match="projection_state_without_receipt"):
        _prepare(conn)
    assert (
        conn.execute(f"SELECT source_label FROM {projection.LABEL_TABLE} WHERE token_id=?", (TOKEN_A,)).fetchone()[0]
        == "OLD"
    )


def test_failure_receipt_is_explicit_deduplicated_and_immutable() -> None:
    conn = _connection()
    error = projection.ProjectionBlockedError("source_labels_not_exact_binary", {"count": 1})
    bad = _record()
    bad["source_labels"] = ["only one"]
    first = projection.record_projection_failure(conn, bad, error)
    second = projection.record_projection_failure(conn, bad, error)
    assert second == first
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.FAILURE_TABLE}").fetchone()[0] == 1
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.LABEL_TABLE}").fetchone()[0] == 0
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.RECEIPT_TABLE}").fetchone()[0] == 0
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.SYNC_TABLE}").fetchone()[0] == 0
    assert conn.in_transaction is False
    assert first["projection_key"] is None
    assert first["immutability_scope"] == projection.IMMUTABILITY_SCOPE
    assert first["runtime_role_separation_verified"] is False
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            f"UPDATE {projection.FAILURE_TABLE} SET reason='changed' WHERE failure_key=?",
            (first["failure_key"],),
        )


def test_failure_recording_is_not_an_implicit_dry_run_side_effect() -> None:
    conn = _connection()
    bad = _record()
    bad["source_labels"] = ["one"]
    with pytest.raises(projection.ProjectionBlockedError):
        _prepare(conn, bad)
    assert projection._schema_presence(conn) is False


def test_postgres_ddl_has_foreign_keys_boolean_types_and_immutable_trigger_contract() -> None:
    ddl = "\n".join(projection._postgres_table_ddls()).lower()
    assert "references core.market_tokens(token_id)" in ddl
    assert f"references {projection.RECEIPT_TABLE}(plan_sha256)" in ddl
    assert "supports_yes_no_wording boolean not null" in ddl
    assert "projected_token_count smallint not null" in ddl
    assert set(projection._POSTGRES_COLUMN_CONTRACT) == set(projection._TABLES)
    assert set(projection._TRIGGER_NAMES) == set(projection._TABLES)
    assert set(projection._TRUNCATE_TRIGGER_NAMES) == set(projection._TABLES)
    assert len(set(projection._TRIGGER_NAMES.values())) == 4
    assert len(set(projection._TRUNCATE_TRIGGER_NAMES.values())) == 4
    assert all(
        len(value) <= 63
        for value in (
            *projection._TRIGGER_NAMES.values(),
            *projection._TRUNCATE_TRIGGER_NAMES.values(),
        )
    )


def test_postgres_catalog_attestation_and_serializable_transaction_contract() -> None:
    conn = PostgresConnectionWrapper()
    projection._attest_postgres_schema(conn)
    projection._begin_transaction(conn, read_only=False)
    assert any(sql == "BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ WRITE" for sql, _params in conn.executed)
    conn.rollback()

    conn.extra_trigger = True
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        projection._attest_postgres_schema(conn)
    conn.extra_trigger = False
    conn.unlogged_relation = True
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        projection._attest_postgres_schema(conn)
    conn.unlogged_relation = False
    conn.inheritance_parent = True
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        projection._attest_postgres_schema(conn)
    conn.inheritance_parent = False
    conn.inheritance_child = True
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        projection._attest_postgres_schema(conn)
    conn.inheritance_child = False
    conn.wrong_default = True
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        projection._attest_postgres_schema(conn)
    conn.wrong_default = False
    conn.lowercase_check_literal = True
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        projection._attest_postgres_schema(conn)
    assert projection._postgres_check_signature("status = 'PROJECTED'::text") != projection._postgres_check_signature(
        "status = 'projected'::text"
    )
    conn.lowercase_check_literal = False
    conn.invalid_constraint = True
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        projection._attest_postgres_schema(conn)
    conn.invalid_constraint = False
    conn.ordinary_trigger = True
    with pytest.raises(projection.ProjectionBlockedError, match="projection_schema_attestation_failed"):
        projection._attest_postgres_schema(conn)


@pytest.mark.parametrize(
    "unsafe_flag",
    [
        "session_current_role_mismatch",
        "session_privileged_role",
        "authenticated_admin_session",
        "settable_privileged_role",
        "settable_nonprivileged_role",
        "schema_owner_membership",
        "schema_create",
        "table_owner_membership",
        "table_mutation_privilege",
        "table_column_update_privilege",
        "function_owner_membership",
    ],
)
def test_postgres_runtime_writer_role_is_strictly_separated(
    unsafe_flag: str,
) -> None:
    conn = PostgresConnectionWrapper()
    report = projection._attest_postgres_runtime_role_security(conn)
    assert report["runtime_role"] == "runtime_writer"
    assert report["runtime_role_separation_verified"] is True
    assert report["settable_role_memberships"] == []

    setattr(conn, unsafe_flag, True)
    with pytest.raises(
        projection.ProjectionBlockedError,
        match="runtime_role_separation_attestation_failed",
    ):
        projection._attest_postgres_runtime_role_security(conn)


def test_set_session_authorization_cannot_hide_authenticated_admin() -> None:
    conn = PostgresConnectionWrapper()
    conn.authenticated_admin_session = True
    report = projection._postgres_runtime_role_security_report(conn)
    assert report["role"]["authenticated_role"] == "bootstrap_admin"
    assert report["role"]["session_role"] == "runtime_writer"
    assert report["role"]["current_role"] == "runtime_writer"
    assert report["role"]["authenticated_is_superuser"] is True
    assert "authenticated_session_current_role_mismatch" in report["violations"]
    assert report["runtime_role_separation_verified"] is False


def test_inherit_false_set_true_role_membership_is_rejected_even_without_role_flags() -> None:
    conn = PostgresConnectionWrapper()
    conn.settable_nonprivileged_role = True
    report = projection._postgres_runtime_role_security_report(conn)
    delegated = report["settable_role_memberships"]
    assert delegated == [
        {
            "role_name": "trigger_manager",
            "is_superuser": False,
            "can_create_role": False,
            "can_create_database": False,
            "is_replication_role": False,
            "can_bypass_rls": False,
        }
    ]
    assert not any(
        table["can_update"]
        or table["can_update_any_column"]
        or table["can_delete"]
        or table["can_truncate"]
        or table["can_create_trigger"]
        for table in report["tables"]
    )
    assert "unexpected_role_memberships" in report["violations"]
    assert report["runtime_role_separation_verified"] is False


def test_postgres_runtime_write_never_bootstraps_missing_schema() -> None:
    conn = PostgresConnectionWrapper()
    conn.missing_projection_schema = True
    projection._begin_transaction(conn, read_only=False)
    with pytest.raises(
        projection.ProjectionBlockedError,
        match="projection_schema_bootstrap_required",
    ):
        projection._ensure_schema(conn)
    assert not any(statement.startswith("CREATE TABLE") for statement, _params in conn.executed)
    conn.rollback()


def test_schema_bootstrap_is_an_explicit_non_projection_operation() -> None:
    conn = _connection()
    result = projection.bootstrap_projection_schema(conn)
    assert result == {
        "status": "SCHEMA_BOOTSTRAPPED",
        "schema_created": True,
        **projection._immutability_contract(),
        "runtime_role_separation_verified": False,
        "market_projected": False,
    }
    assert conn.in_transaction is False
    assert projection._schema_presence(conn) is True
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.LABEL_TABLE}").fetchone()[0] == 0
    assert conn.execute(f"SELECT COUNT(*) FROM {projection.RECEIPT_TABLE}").fetchone()[0] == 0


def test_public_postgres_prepare_owns_read_transaction_and_locks_before_attestation() -> None:
    conn = PostgresConnectionWrapper()
    with pytest.raises(projection.ProjectionBlockedError, match="invalid_market_id"):
        projection.prepare_projection(conn, {"market_id": "not-an-integer"})
    assert conn._pg_conn.info.transaction_status.name == "IDLE"
    sql = [statement for statement, _params in conn.executed]
    begin_index = sql.index("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
    savepoint_index = next(index for index, statement in enumerate(sql) if statement.startswith("SAVEPOINT "))
    lock_index = next(index for index, statement in enumerate(sql) if statement.startswith("LOCK TABLE "))
    catalog_index = next(index for index, statement in enumerate(sql) if "FROM pg_catalog" in statement)
    assert begin_index < savepoint_index < lock_index < catalog_index
    assert sql[lock_index].endswith("IN ACCESS SHARE MODE")

    write_conn = PostgresConnectionWrapper()
    projection._begin_transaction(write_conn, read_only=False)
    projection._ensure_schema(write_conn)
    write_sql = [statement for statement, _params in write_conn.executed]
    write_lock_index = next(index for index, statement in enumerate(write_sql) if statement.startswith("LOCK TABLE "))
    write_catalog_index = next(index for index, statement in enumerate(write_sql) if "FROM pg_catalog" in statement)
    assert write_sql[write_lock_index].endswith("IN ROW EXCLUSIVE MODE")
    assert write_lock_index < write_catalog_index
    write_conn.rollback()


def test_cli_defaults_to_dry_run_and_requires_one_json_record(tmp_path: Path) -> None:
    path = tmp_path / "projection.json"
    path.write_text(json.dumps(_record()), encoding="utf-8")
    args = projection.parse_args(["--projection-json", str(path)])
    assert args.apply is False
    assert args.expected_plan_sha256 is None
    assert args.backend == "postgres"
    bootstrap_args = projection.parse_args(["--bootstrap-schema"])
    assert bootstrap_args.bootstrap_schema is True
    assert bootstrap_args.projection_json is None
