from __future__ import annotations

import hashlib
import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest


from api.services import orderfilled_outcome_proof_service as subject  # noqa: E402
from api.services import outcome_semantics_service  # noqa: E402


def _write_json(path: Path, payload: dict) -> str:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _verified_table(row_count: int) -> dict:
    current = {
        "row_count": row_count,
        "unique_key_count": row_count,
        "duplicate_key_count": 0,
        "old_outcome_rows": 0,
        "new_outcome_rows": row_count,
        "unexpected_outcome_rows": 0,
    }
    return {
        "status": "PASS",
        "hard_gate_passed": True,
        "current": current,
        "checks": {
            "conserve_row_count": True,
            "conserve_unique_key_count": True,
            "conserve_duplicate_key_count": True,
            "conserve_non_outcome_hash_sum": True,
            "conserve_non_outcome_hash_xor": True,
            "conserve_numeric": True,
            "old_outcome_scope_zero": True,
            "new_outcome_scope_exact": True,
            "unexpected_outcome_scope_zero": True,
        },
    }


def _fixture(tmp_path: Path, *, plan_market_id: int = 7) -> dict:
    market_id = 7
    plan_sha = "a" * 64
    report_sha = "b" * 64
    row_sha = "c" * 64
    run_id = "canonical-market-7-test-v1"
    plan_path = tmp_path / "plan.json"
    checkpoint_path = tmp_path / "checkpoint.json"
    plan = {
        "schema_version": "orderfilled-outcome-semantic-plan-v2",
        "run_id": run_id,
        "plan_path": str(plan_path),
        "checkpoint_path": str(checkpoint_path),
        "plan_sha256": plan_sha,
        "audit_report": {"report_payload_sha256": report_sha},
        "scope_contract": {
            "authority_mode": "direct_canonical_targets",
            "target_market_count": 1,
        },
        "mappings": [
            {
                "market_id": plan_market_id,
                "token_id_hex": "1" * 64,
                "new_outcome_code": 1,
            },
            {
                "market_id": plan_market_id,
                "token_id_hex": "2" * 64,
                "new_outcome_code": 2,
            },
        ],
        "expected_postgres_before_image": [{"market_id": plan_market_id}],
    }
    plan_file_sha = _write_json(plan_path, plan)
    receipt_paths: dict[str, Path] = {}
    receipt_refs: dict[str, dict] = {}
    verified_receipt = None
    for index, state in enumerate(subject.RECEIPT_STATES):
        receipt = {
            "schema_version": outcome_semantics_service.OUTCOMEFILLED_RECEIPT_SCHEMA,
            "run_id": run_id,
            "from_state": subject.RECEIPT_STATES[index - 1] if index else None,
            "state": state,
            "status": "PASS",
            "plan_sha256": plan_sha,
            "report_payload_sha256": report_sha,
            "verification": {},
        }
        if state == "VERIFIED":
            receipt["verification"] = {
                "completion_contract": "both_tables_verified_only_outcome_code_changed",
                "orderfilled_fact": _verified_table(2),
                "address_trade_cashflows": _verified_table(4),
                "runtime_gates": {
                    "active_mutations": [],
                    "global_storage_buffer_rows": 0,
                    "scoped_buffer_rows": 0,
                    "scope_snapshot_consistent": True,
                },
            }
            verified_receipt = receipt
        path = tmp_path / f"{index:02d}-{state}.json"
        sha = _write_json(path, receipt)
        receipt_paths[state] = path
        receipt_refs[state] = {"path": str(path), "file_sha256": sha}
    assert verified_receipt is not None
    checkpoint = {
        "schema_version": subject.CHECKPOINT_SCHEMA,
        "run_id": run_id,
        "plan_path": str(plan_path),
        "plan_sha256": plan_sha,
        "report_payload_sha256": report_sha,
        "state": "VERIFIED",
        "state_index": 3,
        "completed": True,
        "receipts": receipt_refs,
    }
    checkpoint_file_sha = _write_json(checkpoint_path, checkpoint)
    watermark = {
        "schemaVersion": subject.SOURCE_WATERMARK_SCHEMA,
        "marketId": market_id,
        "sourceTable": "orderfilled_fact",
        "fromBlock": 10,
        "throughBlock": 90,
        "rowCount": 2,
        "uniqueKeyCount": 2,
        "rowHashSum": "123",
        "rowHashXor": "45",
    }
    entry = {
        "marketId": market_id,
        "fromBlock": 10,
        "throughBlock": 90,
        "rowSha256": row_sha,
        "sourceVersionSha256": outcome_semantics_service._receipt_source_version_sha256(
            verified_receipt,
            outcome_semantics_service._payload_sha256(verified_receipt),
        ),
        "sourceWatermark": {
            **watermark,
            "watermarkSha256": subject._payload_sha256(watermark),
        },
        "zeroResidual": True,
        "residualRows": 0,
        "outcomeMappings": [
            {"tokenIdHex": "1" * 64, "outcomeCode": 1},
            {"tokenIdHex": "2" * 64, "outcomeCode": 2},
        ],
        "artifactChain": {
            "plan": {"path": str(plan_path), "fileSha256": plan_file_sha},
            "checkpoint": {
                "path": str(checkpoint_path),
                "fileSha256": checkpoint_file_sha,
            },
            "verifiedReceipt": {
                "path": str(receipt_paths["VERIFIED"]),
                "fileSha256": receipt_refs["VERIFIED"]["file_sha256"],
            },
        },
    }
    manifest = {"schemaVersion": subject.MANIFEST_SCHEMA, "entries": [entry]}
    manifest_path = tmp_path / "manifest.json"
    manifest_sha = _write_json(manifest_path, manifest)
    observation = {
        "schemaVersion": subject.RUNTIME_OBSERVATION_SCHEMA,
        "sourceWatermark": watermark,
        "activeMutations": [],
        "globalBufferRows": 0,
        "scopedBufferRows": 0,
        "zeroResidual": True,
        "residualRows": 0,
        "timedOut": False,
    }
    return {
        "key": {
            "market_id": market_id,
            "from_block": 10,
            "through_block": 90,
            "row_sha256": row_sha,
        },
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha": manifest_sha,
        "observation": observation,
        "verified_path": receipt_paths["VERIFIED"],
    }


def _lookup(fixture: dict, observation: dict | None = None):
    return subject.get_orderfilled_outcome_mutation_proof(
        **fixture["key"],
        manifest_path=fixture["manifest_path"],
        manifest_sha256=fixture["manifest_sha"],
        runtime_probe=lambda **_kwargs: deepcopy(fixture["observation"] if observation is None else observation),
    )


def test_exact_key_returns_content_bound_public_proof(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    proof = _lookup(fixture)

    assert proof is not None
    assert proof["manifestSha256"] == fixture["manifest_sha"]
    assert proof["coverage"]["marketIds"] == [7]
    assert outcome_semantics_service._validate_orderfilled_mutation_proof(
        proof,
        market_id=7,
        source_from_block=10,
        source_through_block=90,
        row_sha256="c" * 64,
    )


def test_lookup_is_exact_not_containment_or_latest(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["key"]["from_block"] = 11

    assert _lookup(fixture) is None


def test_manifest_tamper_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    fixture["manifest"]["entries"][0]["throughBlock"] = 91
    _write_json(fixture["manifest_path"], fixture["manifest"])

    assert _lookup(fixture) is None


def test_verified_receipt_tamper_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    receipt = json.loads(fixture["verified_path"].read_text(encoding="utf-8"))
    receipt["status"] = "FAIL"
    _write_json(fixture["verified_path"], receipt)

    assert _lookup(fixture) is None


def test_broader_or_wrong_plan_scope_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path, plan_market_id=8)

    assert _lookup(fixture) is None


def test_stale_append_watermark_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    observation = deepcopy(fixture["observation"])
    observation["sourceWatermark"]["throughBlock"] = 91
    observation["sourceWatermark"]["rowCount"] = 3
    observation["sourceWatermark"]["uniqueKeyCount"] = 3

    assert _lookup(fixture, observation) is None


def test_active_mutation_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    observation = deepcopy(fixture["observation"])
    observation["activeMutations"] = [{"mutation_id": "mutation_1"}]

    assert _lookup(fixture, observation) is None


@pytest.mark.parametrize("field", ["globalBufferRows", "scopedBufferRows"])
def test_buffer_rows_fail_closed(tmp_path: Path, field: str) -> None:
    fixture = _fixture(tmp_path)
    observation = deepcopy(fixture["observation"])
    observation[field] = 1

    assert _lookup(fixture, observation) is None


def test_residual_rows_fail_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    observation = deepcopy(fixture["observation"])
    observation["zeroResidual"] = False
    observation["residualRows"] = 1

    assert _lookup(fixture, observation) is None


def test_probe_timeout_or_missing_configuration_fails_closed(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)

    def timeout(**_kwargs):
        raise TimeoutError

    assert (
        subject.get_orderfilled_outcome_mutation_proof(
            **fixture["key"],
            manifest_path=fixture["manifest_path"],
            manifest_sha256=fixture["manifest_sha"],
            runtime_probe=timeout,
        )
        is None
    )
    assert subject.get_orderfilled_outcome_mutation_proof(**fixture["key"]) is None


def test_docker_probe_transport_keeps_password_out_of_argv(monkeypatch) -> None:
    captured = {}

    def run(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":1}\n', stderr="")

    monkeypatch.setattr(subject.shutil, "which", lambda _name: "/usr/bin/docker")
    monkeypatch.setattr(subject.subprocess, "run", run)
    monkeypatch.setattr(
        subject.clickhouse_orderfilled_service,
        "_settings",
        lambda: {
            "http_url": "",
            "container": "clickhouse",
            "database": "poly_orderfilled",
            "user": "reader",
            "password": "top-secret",
            "table": "orderfilled_fact",
        },
    )

    rows = subject._query_json_rows_safe(
        {"app": object()},
        "SELECT 1 FORMAT JSONEachRow",
        timeout_seconds=0.5,
    )

    assert rows == [{"ok": 1}]
    assert "top-secret" not in captured["command"]
    assert "--password" not in captured["command"]
    assert captured["env"]["CLICKHOUSE_PASSWORD"] == "top-secret"
