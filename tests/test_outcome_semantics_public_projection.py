from __future__ import annotations

from api.routes.markets import MarketRouteDependencies

from copy import deepcopy

import pytest
from flask import Flask


from api.services import clickhouse_orderfilled_service, outcome_semantics_service  # noqa: E402
from api.routes.markets import create_markets_blueprint  # noqa: E402


TOKENS = ("token-a", "token-b")


def _semantics(mode: str, labels: tuple[str, str]) -> dict:
    slots = {
        logical: {
            "tokenId": token,
            "sourceLabel": label,
            "sourceIndex": index,
            "logicalOutcome": logical,
            "logicalOutcomeIndex": index,
        }
        for index, (logical, label, token) in enumerate(zip(("YES", "NO"), labels, TOKENS))
    }
    return {
        "status": "projected",
        "valid": True,
        "marketId": 7,
        "semanticMode": mode,
        "supportsYesNoWording": mode == "yes_no_labels",
        "supportsDirectionalSemantics": mode == "up_down_labels",
        "tokens": {slot["tokenId"]: slot for slot in slots.values()},
        "logicalSlots": slots,
    }


@pytest.fixture
def install_semantics(monkeypatch):
    def install(mode: str, labels: tuple[str, str]):
        semantics = _semantics(mode, labels)

        def load(_ctx, market_ids):
            return {int(value): deepcopy(semantics) for value in market_ids}

        monkeypatch.setattr(outcome_semantics_service, "load_market_outcome_semantics", load)
        return semantics

    return install


def _verified_table() -> dict:
    checks = {
        name: True
        for name in (
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
    }
    return {
        "status": "PASS",
        "hard_gate_passed": True,
        "checks": checks,
        "current": {
            "old_outcome_rows": 0,
            "unexpected_outcome_rows": 0,
            "duplicate_key_count": 0,
            "row_count": 11,
            "unique_key_count": 11,
        },
    }


def _aggregate_row() -> dict:
    return {
        "market_id": 7,
        "outcome": "YES",
        "latest_token_price": "0.60",
        "block_number": 90,
    }


def _mutation_proof(row: dict | None = None) -> dict:
    row = row or _aggregate_row()
    receipt = {
        "schema_version": outcome_semantics_service.OUTCOMEFILLED_RECEIPT_SCHEMA,
        "state": "VERIFIED",
        "status": "PASS",
        "plan_sha256": "a" * 64,
        "report_payload_sha256": "b" * 64,
        "verification": {
            "completion_contract": "both_tables_verified_only_outcome_code_changed",
            "orderfilled_fact": _verified_table(),
            "address_trade_cashflows": _verified_table(),
            "runtime_gates": {
                "active_mutations": [],
                "scoped_buffer_rows": 0,
                "scope_snapshot_consistent": True,
            },
        },
    }
    proof = {
        "schemaVersion": outcome_semantics_service.OUTCOMEFILLED_PUBLIC_PROOF_SCHEMA,
        "receipt": receipt,
        "receiptSha256": outcome_semantics_service._payload_sha256(receipt),
        "planSha256": "a" * 64,
        "coverage": {
            "marketIds": [7],
            "fromBlock": 1,
            "throughBlock": 100,
            "sourceTable": "orderfilled_fact",
            "sourceVersionSha256": outcome_semantics_service._receipt_source_version_sha256(
                receipt,
                outcome_semantics_service._payload_sha256(receipt),
            ),
            "rowSha256": outcome_semantics_service._aggregate_row_sha256(row),
            "rebuiltFromReceiptSha256": outcome_semantics_service._payload_sha256(
                receipt
            ),
            "zeroResidual": True,
            "residualRows": 0,
        },
    }
    proof["proofSha256"] = outcome_semantics_service._payload_sha256(proof)
    return proof


def test_reversed_yes_no_source_labels_are_projected_by_exact_token(install_semantics):
    install_semantics("source_first_second", ("No", "Yes"))

    projected = outcome_semantics_service.project_token_price_fact(
        {},
        {"market_id": 7, "token_id": "token-a", "outcome": "YES", "price": "0.70"},
    )

    assert projected["priceProjectionProof"] == "canonical_token"
    assert projected["outcome"] == "No"
    assert [item["sourceLabel"] for item in projected["outcomePrices"]] == ["No", "Yes"]
    assert [item["price"] for item in projected["outcomePrices"]] == ["0.7000000000", "0.3000000000"]
    assert projected.get("yesPrice") is None
    assert projected["sourcePrices"] == projected["outcomePrices"]


def test_reversed_yes_no_source_order_keeps_source_slots_and_logical_prices(monkeypatch):
    semantics = _semantics("yes_no_labels", ("Yes", "No"))
    semantics["logicalSlots"]["YES"]["sourceIndex"] = 1
    semantics["logicalSlots"]["NO"]["sourceIndex"] = 0

    monkeypatch.setattr(
        outcome_semantics_service,
        "load_market_outcome_semantics",
        lambda _ctx, market_ids: {int(value): deepcopy(semantics) for value in market_ids},
    )

    projected = outcome_semantics_service.project_token_price_fact(
        {},
        {"market_id": 7, "token_id": "token-b", "outcome": "NO", "price": "0.30"},
    )

    assert [item["sourceLabel"] for item in projected["outcomePrices"]] == ["No", "Yes"]
    assert [item["price"] for item in projected["outcomePrices"]] == [
        "0.3000000000",
        "0.7000000000",
    ]
    assert projected["yesPrice"] == "0.7000000000"
    assert projected["noPrice"] == "0.3000000000"
    assert projected["primaryOutcomePrice"] == "0.3000000000"


def test_up_down_projection_exposes_directional_pair_without_yes_no_wording(install_semantics):
    install_semantics("up_down_labels", ("Up", "Down"))

    projected = outcome_semantics_service.project_token_price_fact(
        {},
        {"market_id": 7, "token_id": "token-b", "outcome": "NO", "price": "0.25"},
    )

    assert projected["outcome"] == "Down"
    assert projected["upPrice"] == "0.7500000000"
    assert projected["downPrice"] == "0.2500000000"
    assert projected.get("yesPrice") is None
    assert projected["outcomeSemanticsCapabilities"]["supportsDirectionalSemantics"] is True


def test_noncanonical_raw_token_fails_closed_even_with_logical_outcome(install_semantics):
    install_semantics("up_down_labels", ("Up", "Down"))

    projected = outcome_semantics_service.project_token_price_fact(
        {},
        {"market_id": 7, "token_id": "not-canonical", "outcome": "YES", "price": "0.60"},
    )

    assert projected["priceProjectionValid"] is False
    assert projected["outcome"] is None
    assert projected["price"] is None
    assert projected.get("upPrice") is None
    assert projected["outcomeSemanticsStatus"] == "trade_token_projection_mismatch"


def test_conflicting_token_identity_aliases_fail_closed(install_semantics):
    install_semantics("up_down_labels", ("Up", "Down"))

    projected = outcome_semantics_service.project_token_price_fact(
        {},
        {
            "marketId": 7,
            "token_id": "token-a",
            "tokenId": "token-b",
            "price": "0.70",
        },
    )

    assert projected["priceProjectionValid"] is False
    assert projected["outcomeSemanticsStatus"] == "token_identity_alias_conflict"
    assert projected["token_id"] is None
    assert projected["tokenId"] is None
    assert projected["price"] is None


def test_conflicting_price_aliases_and_stale_outcome_code_cannot_escape(install_semantics):
    install_semantics("up_down_labels", ("Up", "Down"))

    conflicting = outcome_semantics_service.project_token_price_fact(
        {},
        {
            "marketId": 7,
            "tokenId": "token-a",
            "price": "0.70",
            "avg_price": "0.90",
            "outcome_code": 2,
        },
    )
    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {
            "marketId": 7,
            "tokenId": "token-a",
            "price": "0.70",
            "avg_price": "0.70",
            "outcome_code": 2,
        },
    )

    assert conflicting["priceProjectionValid"] is False
    assert conflicting["outcomeSemanticsStatus"] == "fact_price_alias_conflict"
    assert conflicting["price"] is None
    assert conflicting["avg_price"] is None
    assert "outcome_code" not in conflicting
    assert sanitized["priceProjectionValid"] is True
    assert sanitized["outcome"] == "Up"
    assert sanitized["price"] == "0.7000000000"
    assert sanitized["avg_price"] == "0.7000000000"
    assert "outcome_code" not in sanitized


def test_conflicting_market_identity_aliases_fail_closed(install_semantics):
    install_semantics("up_down_labels", ("Up", "Down"))

    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {
            "market_id": 7,
            "marketId": 8,
            "tokenId": "token-a",
            "price": "0.70",
        },
    )

    assert sanitized["priceProjectionValid"] is False
    assert sanitized["outcomeSemanticsStatus"] == "market_identity_alias_conflict"
    assert sanitized["market_id"] is None
    assert sanitized["marketId"] is None
    assert sanitized["price"] is None


def test_nested_exact_token_fact_is_projected_and_noncanonical_peer_is_cleared(
    install_semantics,
):
    install_semantics("up_down_labels", ("Up", "Down"))

    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {
            "marketId": 7,
            "canonical": {"marketId": 7, "tokenId": "token-a", "price": "0.70"},
            "noncanonical": {
                "marketId": 7,
                "tokenId": "not-canonical",
                "price": "0.70",
            },
            "missing": {"marketId": 7, "tokenId": "", "price": "0.70"},
            "points": [
                {"tokenId": "token-b", "tokenPrice": "0.20"},
                {"tokenId": "not-canonical", "tokenPrice": "0.30"},
            ],
        },
    )

    assert sanitized["canonical"]["outcome"] == "Up"
    assert sanitized["canonical"]["upPrice"] == "0.7000000000"
    assert sanitized["canonical"]["priceProjectionValid"] is True
    assert sanitized["noncanonical"]["price"] is None
    assert sanitized["noncanonical"]["outcome"] is None
    assert sanitized["noncanonical"]["priceProjectionValid"] is False
    assert sanitized["noncanonical"]["outcomeSemanticsStatus"] == "trade_token_projection_mismatch"
    assert sanitized["missing"]["price"] is None
    assert sanitized["missing"]["priceProjectionValid"] is False
    assert sanitized["points"][0]["outcome"] == "Down"
    assert sanitized["points"][0]["downPrice"] == "0.2000000000"
    assert sanitized["points"][0]["priceProjectionValid"] is True
    assert sanitized["points"][1]["tokenPrice"] is None
    assert sanitized["points"][1]["priceProjectionValid"] is False


def test_underlying_price_chart_points_are_not_treated_as_probability_facts(
    install_semantics,
):
    install_semantics("up_down_labels", ("Up", "Down"))

    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {
            "marketId": 7,
            "kind": "underlying-price",
            "points": [{"timestamp": "2026-08-29T00:00:00Z", "price": 123.45}],
        },
    )

    assert sanitized["points"] == [
        {"timestamp": "2026-08-29T00:00:00Z", "price": 123.45}
    ]


def test_tokenless_aggregate_requires_content_bound_mutation_receipt(install_semantics):
    install_semantics("yes_no_labels", ("Yes", "No"))
    row = _aggregate_row()

    missing = outcome_semantics_service.project_market_pair({}, row)
    valid = outcome_semantics_service.project_market_pair(
        {"get_orderfilled_outcome_mutation_proof": lambda **_kwargs: _mutation_proof()},
        row,
    )

    assert missing["priceProjectionValid"] is False
    assert missing["outcomeSemanticsStatus"] == "aggregate_mutation_proof_missing"
    assert valid["priceProjectionValid"] is True
    assert valid["priceProjectionProof"] == "orderfilled_mutation_receipt"
    assert valid["yesPrice"] == "0.6000000000"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda proof: proof["receipt"].update({"status": "FAIL"}),
        lambda proof: proof["coverage"].update({"throughBlock": 89}),
        lambda proof: proof["coverage"].update({"residualRows": 1}),
    ],
)
def test_tampered_or_undercovered_mutation_proof_is_rejected(install_semantics, tamper):
    install_semantics("yes_no_labels", ("Yes", "No"))
    proof = _mutation_proof()
    tamper(proof)

    projected = outcome_semantics_service.project_market_pair(
        {"get_orderfilled_outcome_mutation_proof": lambda **_kwargs: proof},
        _aggregate_row(),
    )

    assert projected["priceProjectionValid"] is False
    assert projected["outcomeSemanticsStatus"] == "aggregate_mutation_proof_missing"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sourceTable", "wrong_table"),
        ("sourceVersionSha256", "d" * 64),
    ],
)
def test_rehashed_proof_cannot_substitute_source_identity(
    install_semantics,
    field,
    value,
):
    install_semantics("yes_no_labels", ("Yes", "No"))
    proof = _mutation_proof()
    proof["coverage"][field] = value
    proof["proofSha256"] = outcome_semantics_service._payload_sha256(
        {key: item for key, item in proof.items() if key != "proofSha256"}
    )

    projected = outcome_semantics_service.project_market_pair(
        {"get_orderfilled_outcome_mutation_proof": lambda **_kwargs: proof},
        _aggregate_row(),
    )

    assert projected["priceProjectionValid"] is False
    assert projected["outcomeSemanticsStatus"] == "aggregate_mutation_proof_missing"


def test_malformed_rehashed_receipt_numeric_fails_closed_without_exception(install_semantics):
    install_semantics("yes_no_labels", ("Yes", "No"))
    proof = _mutation_proof()
    receipt = proof["receipt"]
    receipt["verification"]["orderfilled_fact"]["current"]["old_outcome_rows"] = "not-an-int"
    receipt_sha = outcome_semantics_service._payload_sha256(receipt)
    proof["receiptSha256"] = receipt_sha
    proof["coverage"]["rebuiltFromReceiptSha256"] = receipt_sha
    proof["coverage"]["sourceVersionSha256"] = (
        outcome_semantics_service._receipt_source_version_sha256(receipt, receipt_sha)
    )
    proof["proofSha256"] = outcome_semantics_service._payload_sha256(
        {key: item for key, item in proof.items() if key != "proofSha256"}
    )

    projected = outcome_semantics_service.project_market_pair(
        {"get_orderfilled_outcome_mutation_proof": lambda **_kwargs: proof},
        _aggregate_row(),
    )

    assert projected["priceProjectionValid"] is False
    assert projected["outcomeSemanticsStatus"] == "aggregate_mutation_proof_missing"


def test_aggregate_receipt_is_bound_to_exact_row_content(install_semantics):
    install_semantics("yes_no_labels", ("Yes", "No"))
    original = _aggregate_row()
    proof = _mutation_proof(original)
    changed = {**original, "latest_token_price": "0.91"}

    projected = outcome_semantics_service.project_market_pair(
        {"get_orderfilled_outcome_mutation_proof": lambda **_kwargs: proof},
        changed,
    )

    assert projected["priceProjectionValid"] is False
    assert projected["outcomeSemanticsStatus"] == "aggregate_mutation_proof_missing"


def test_aggregate_receipt_without_fact_block_is_rejected(install_semantics):
    install_semantics("yes_no_labels", ("Yes", "No"))
    row = {key: value for key, value in _aggregate_row().items() if key != "block_number"}

    projected = outcome_semantics_service.project_market_pair(
        {"get_orderfilled_outcome_mutation_proof": lambda **_kwargs: _mutation_proof()},
        row,
    )

    assert projected["priceProjectionValid"] is False


def test_stale_cached_valid_payload_cannot_self_attest(install_semantics):
    install_semantics("yes_no_labels", ("Yes", "No"))
    stale = {
        "marketId": 7,
        "latestPrice": "0.90",
        "latestYesPrice": "0.90",
        "latestNoPrice": "0.10",
        "outcome": "YES",
        "outcomeSemanticsValid": True,
        "outcomeSemanticsCapabilities": {
            "supportsYesNoWording": True,
            "supportsDirectionalSemantics": True,
        },
    }

    sanitized = outcome_semantics_service.sanitize_public_market_payload({}, stale)

    assert sanitized["latestPrice"] is None
    assert sanitized["latestYesPrice"] is None
    assert sanitized["latestNoPrice"] is None
    assert sanitized["outcome"] is None
    assert sanitized["outcomeSemanticsValid"] is True
    assert sanitized["outcomeSemanticsCapabilities"]["supportsDirectionalSemantics"] is False
    assert sanitized["outcomeSemanticsCapabilityReason"] == "price_fact_identity_unproven"


def test_nested_attestation_only_payload_is_reproved_and_stale_aliases_are_removed(
    install_semantics,
):
    install_semantics("source_first_second", ("Lakers", "Celtics"))
    stale = {
        "marketId": 7,
        "cached": {
            "outcome_semantics_valid": True,
            "outcome_semantics_capabilities": {"supports_yes_no_wording": True},
            "price_projection_valid": True,
            "tokenPrice": "0.99",
            "primary_outcome_price": "0.99",
            "observed_outcome": "Yes",
        },
    }

    sanitized = outcome_semantics_service.sanitize_public_market_payload({}, stale)
    cached = sanitized["cached"]

    assert "outcome_semantics_valid" not in cached
    assert "outcome_semantics_capabilities" not in cached
    assert "price_projection_valid" not in cached
    assert cached["tokenPrice"] is None
    assert cached["primary_outcome_price"] is None
    assert cached["observed_outcome"] is None
    assert cached["outcomeSemanticsValid"] is True
    assert cached["priceProjectionValid"] is False


def test_source_first_cached_primary_fields_without_exact_fact_are_cleared(install_semantics):
    install_semantics("source_first_second", ("Lakers", "Celtics"))

    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {
            "marketId": 7,
            "primaryOutcomePrice": "0.81",
            "observedOutcome": "Yes",
            "sourcePrices": [{"sourceLabel": "Yes", "price": "0.81"}],
        },
    )
    assert sanitized["primaryOutcomePrice"] is None
    assert sanitized["observedOutcome"] is None
    assert sanitized["sourcePrices"] is None
    assert sanitized["priceProjectionValid"] is False


def test_public_raw_price_without_exact_token_is_cleared(install_semantics):
    install_semantics("yes_no_labels", ("Yes", "No"))

    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {"marketId": 7, "outcome": "YES", "side": "BUY", "price": "0.72"},
    )

    assert sanitized["price"] is None
    assert sanitized["outcome"] is None
    assert sanitized["outcomeSemanticsCapabilityReason"] == "price_fact_identity_unproven"


def test_cached_exact_price_fact_is_reprojected_from_current_semantics(install_semantics):
    install_semantics("up_down_labels", ("Up", "Down"))
    stale = {
        "marketId": 7,
        "tokenId": "token-b",
        "price": "0.20",
        "outcome": "YES",
        "outcomeSemanticsValid": True,
        "upPrice": "0.20",
        "downPrice": "0.80",
    }

    sanitized = outcome_semantics_service.sanitize_public_market_payload({}, stale)

    assert sanitized["outcome"] == "Down"
    assert sanitized["upPrice"] == "0.8000000000"
    assert sanitized["downPrice"] == "0.2000000000"
    assert sanitized["priceProjectionProof"] == "canonical_token"


def test_oracle_fields_fail_closed_when_semantics_ledger_is_unavailable():
    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {
            "marketId": 7,
            "settlementOutcome": "YES",
            "effectiveSettlementOutcome": "NO",
            "proposedPrice": "1",
            "settledPrice": "0",
            "payout": "[1, 0]",
            "settlementCode": 1,
            "effectiveSettlementCode": 2,
            "settlementRaw": "[1, 0]",
            "settlementOutcomeLogicalOutcome": "YES",
        },
    )

    assert sanitized["settlementOutcome"] is None
    assert sanitized["effectiveSettlementOutcome"] is None
    assert sanitized["proposedPrice"] is None
    assert sanitized["settledPrice"] is None
    assert sanitized["payout"] is None
    assert sanitized["settlementCode"] is None
    assert sanitized["effectiveSettlementCode"] is None
    assert sanitized["settlementRaw"] is None
    assert "settlementOutcomeLogicalOutcome" not in sanitized
    assert sanitized["oracleOutcomeSemanticsValid"] is False
    assert sanitized["oracleOutcomeSemanticsReason"] == "semantics_database_unavailable"
    assert sanitized["outcomeSemanticsCapabilities"]["priceProjectionApplicable"] is False


def test_source_first_oracle_outcomes_use_source_labels_and_suppress_raw_yes_no_values(
    install_semantics,
):
    install_semantics("source_first_second", ("Lakers", "Celtics"))

    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {
            "marketId": 7,
            "settlementOutcome": "YES",
            "effectiveSettlementOutcome": "NO",
            "proposedPrice": "1",
            "payout": "[1, 0]",
            "settlementCode": 1,
        },
    )

    assert sanitized["settlementOutcome"] == "Lakers"
    assert sanitized["effectiveSettlementOutcome"] == "Celtics"
    assert sanitized["settlementOutcomeLogicalOutcome"] == "YES"
    assert sanitized["effectiveSettlementOutcomeLogicalOutcome"] == "NO"
    assert sanitized["proposedPrice"] is None
    assert sanitized["payout"] is None
    assert sanitized["settlementCode"] is None
    assert sanitized["oracleOutcomeSemanticsValid"] is True
    assert sanitized["oracleOutcomeSemanticsReason"] == "oracle_raw_yes_no_values_suppressed"


def test_conflicting_oracle_camel_snake_aliases_fail_closed(install_semantics):
    install_semantics("up_down_labels", ("Up", "Down"))
    trusted = outcome_semantics_service.bind_trusted_oracle_logical_fields(
        {
            "marketId": 7,
            "settlementOutcome": "YES",
            "settlement_outcome": "NO",
        }
    )

    sanitized = outcome_semantics_service.sanitize_public_market_payload({}, trusted)

    assert sanitized["settlementOutcome"] is None
    assert sanitized["settlement_outcome"] is None
    assert "settlementOutcomeLogicalOutcome" not in sanitized
    assert "settlement_outcome_logical" not in sanitized
    assert sanitized["oracleOutcomeSemanticsValid"] is False
    assert sanitized["oracleOutcomeSemanticsReason"] == "oracle_outcome_alias_conflict"


def test_conflicting_oracle_raw_value_aliases_are_not_publicly_retained(install_semantics):
    install_semantics("yes_no_labels", ("Yes", "No"))
    trusted = outcome_semantics_service.bind_trusted_oracle_logical_fields(
        {
            "marketId": 7,
            "settlementOutcome": "YES",
            "proposedPrice": "1",
            "proposed_price": "0",
        }
    )

    sanitized = outcome_semantics_service.sanitize_public_market_payload({}, trusted)

    assert sanitized["proposedPrice"] is None
    assert sanitized["proposed_price"] is None
    assert sanitized["oracleOutcomeSemanticsValid"] is False
    assert sanitized["oracleOutcomeSemanticsReason"] == "oracle_raw_alias_conflict"


def test_oracle_cached_source_label_is_revalidated_and_unknown_label_is_rejected(
    install_semantics,
):
    install_semantics("source_first_second", ("Lakers", "Celtics"))

    sanitized = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {
            "marketId": 7,
            "settlementOutcome": "lakers",
            "effectiveSettlementOutcome": "Warriors",
        },
    )
    sanitized_again = outcome_semantics_service.sanitize_public_market_payload(
        {},
        sanitized,
    )

    assert sanitized["settlementOutcome"] == "Lakers"
    assert sanitized["settlementOutcomeLogicalOutcome"] == "YES"
    assert sanitized["effectiveSettlementOutcome"] is None
    assert "effectiveSettlementOutcomeLogicalOutcome" not in sanitized
    assert sanitized["oracleOutcomeSemanticsValid"] is False
    assert sanitized["oracleOutcomeSemanticsReason"] == "oracle_outcome_unverified"
    assert sanitized_again["effectiveSettlementOutcome"] is None
    assert sanitized_again["oracleOutcomeSemanticsValid"] is False


def test_reversed_yes_no_oracle_projection_is_idempotent_and_requires_logical_binding(
    install_semantics,
):
    install_semantics("source_first_second", ("No", "Yes"))
    fresh = {
        "marketId": 7,
        "settlementOutcome": "YES",
        "settlementOutcomeLogicalOutcome": "YES",
    }

    first = outcome_semantics_service.sanitize_public_market_payload({}, fresh)
    second = outcome_semantics_service.sanitize_public_market_payload({}, first)
    ambiguous = outcome_semantics_service.sanitize_public_market_payload(
        {},
        {"marketId": 7, "settlementOutcome": "YES"},
    )
    ambiguous_again = outcome_semantics_service.sanitize_public_market_payload(
        {},
        ambiguous,
    )

    assert first["settlementOutcome"] == "No"
    assert first["settlementOutcomeLogicalOutcome"] == "YES"
    assert second["settlementOutcome"] == "No"
    assert second["settlementOutcomeLogicalOutcome"] == "YES"
    assert ambiguous["settlementOutcome"] is None
    assert ambiguous["oracleOutcomeSemanticsValid"] is False
    assert ambiguous_again["settlementOutcome"] is None
    assert ambiguous_again["oracleOutcomeSemanticsValid"] is False
    assert (
        ambiguous_again["oracleOutcomeSemanticsReason"]
        == "cached_oracle_projection_previously_rejected"
    )


def test_market_price_route_rechecks_stale_detail_cache(install_semantics):
    install_semantics("yes_no_labels", ("Yes", "No"))
    stale_price = {
        "marketId": 7,
        "latestPrice": "0.88",
        "latestYesPrice": "0.88",
        "latestNoPrice": "0.12",
        "outcomeSemanticsValid": True,
    }
    context = {
        "get_markets_payload": lambda **_kwargs: {"items": []},
        "get_market_by_id": lambda market_id: {"id": market_id},
        "get_market_by_slug": lambda _slug: {"id": 7},
        "normalize_market": lambda row: {"marketId": row["id"]},
        "get_trades_by_market_id": lambda *_args, **_kwargs: [],
        "get_recent_trades_snapshot": lambda **_kwargs: [],
        "get_market_oracle_payload": lambda market_id: {"marketId": market_id},
        "get_recent_oracle_snapshot": lambda **_kwargs: [],
        "get_market_detail_payload": lambda market_id: {
            "marketId": market_id,
            "price": deepcopy(stale_price),
        },
        "get_market_chart_payload": lambda market_id, **_kwargs: {
            "marketId": market_id,
            "points": [],
        },
        "get_market_workspace_payload": lambda market_id: {"marketId": market_id},
        "get_market_focus_tile_payload": lambda market_id: {"marketId": market_id},
    }
    app = Flask(__name__)
    app.register_blueprint(create_markets_blueprint(MarketRouteDependencies.from_context(context)))

    response = app.test_client().get("/markets/7/price")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["latestPrice"] is None
    assert payload["latestYesPrice"] is None
    assert payload["outcomeSemanticsCapabilityReason"] == "price_fact_identity_unproven"


def test_oracle_routes_apply_fresh_source_label_projection(install_semantics):
    install_semantics("source_first_second", ("Lakers", "Celtics"))
    oracle_event = {
        "marketId": 7,
        "settlementOutcome": "YES",
        "proposedPrice": "1",
        "payout": "[1, 0]",
    }
    context = {
        "get_markets_payload": lambda **_kwargs: {"items": []},
        "get_market_by_id": lambda market_id: {"id": market_id},
        "get_market_by_slug": lambda _slug: {"id": 7},
        "normalize_market": lambda row: {"marketId": row["id"]},
        "get_trades_by_market_id": lambda *_args, **_kwargs: [],
        "get_recent_trades_snapshot": lambda **_kwargs: [],
        "get_market_oracle_payload": lambda market_id: {
            "marketId": market_id,
            "settlementOutcome": "NO",
            "timeline": [deepcopy(oracle_event)],
        },
        "get_recent_oracle_snapshot": lambda **_kwargs: [deepcopy(oracle_event)],
        "get_market_detail_payload": lambda market_id: {"marketId": market_id},
        "get_market_chart_payload": lambda market_id, **_kwargs: {
            "marketId": market_id,
            "points": [],
        },
        "get_market_workspace_payload": lambda market_id: {"marketId": market_id},
        "get_market_focus_tile_payload": lambda market_id: {"marketId": market_id},
    }
    app = Flask(__name__)
    app.register_blueprint(create_markets_blueprint(MarketRouteDependencies.from_context(context)))
    client = app.test_client()

    market_payload = client.get("/markets/7/oracle").get_json()
    recent_payload = client.get("/oracle/recent").get_json()

    assert market_payload["settlementOutcome"] == "Celtics"
    assert market_payload["timeline"][0]["settlementOutcome"] == "Lakers"
    assert market_payload["timeline"][0]["payout"] is None
    assert recent_payload[0]["settlementOutcome"] == "Lakers"
    assert recent_payload[0]["proposedPrice"] is None


def test_basic_market_routes_bind_fresh_raw_settlement_before_reversed_projection(
    install_semantics,
):
    install_semantics("source_first_second", ("No", "Yes"))
    context = {
        "get_markets_payload": lambda **_kwargs: {"items": []},
        "get_market_by_id": lambda market_id: {"id": market_id},
        "get_market_by_slug": lambda _slug: {"id": 7},
        "normalize_market": lambda row: {
            "marketId": row["id"],
            "settlementOutcome": "YES",
        },
        "get_trades_by_market_id": lambda *_args, **_kwargs: [],
        "get_recent_trades_snapshot": lambda **_kwargs: [],
        "get_market_oracle_payload": lambda market_id: {"marketId": market_id},
        "get_recent_oracle_snapshot": lambda **_kwargs: [],
        "get_market_detail_payload": lambda market_id: {"marketId": market_id},
        "get_market_chart_payload": lambda market_id, **_kwargs: {
            "marketId": market_id,
            "points": [],
        },
        "get_market_workspace_payload": lambda market_id: {"marketId": market_id},
        "get_market_focus_tile_payload": lambda market_id: {"marketId": market_id},
    }
    app = Flask(__name__)
    app.register_blueprint(create_markets_blueprint(MarketRouteDependencies.from_context(context)))
    client = app.test_client()

    by_id = client.get("/markets/7").get_json()
    by_slug = client.get("/markets/example-slug").get_json()

    assert by_id["settlementOutcome"] == "No"
    assert by_id["settlementOutcomeLogicalOutcome"] == "YES"
    assert by_slug["settlementOutcome"] == "No"
    assert by_slug["settlementOutcomeLogicalOutcome"] == "YES"


def test_clickhouse_series_projects_exact_up_down_token(monkeypatch, install_semantics):
    install_semantics("up_down_labels", ("Up", "Down"))
    monkeypatch.setattr(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        lambda *_args, **_kwargs: [
            {
                "market_id": 7,
                "token_id": "token-b",
                "outcome": "NO",
                "price": "0.20",
                "timestamp": "2026-08-29T00:00:00Z",
                "block_number": 90,
                "log_index": 1,
            }
        ],
    )

    points = clickhouse_orderfilled_service.get_price_series({}, 7)

    assert points is not None
    assert points[0]["upPrice"] == "0.8000000000"
    assert points[0]["downPrice"] == "0.2000000000"
    assert "yesPrice" not in points[0]
    assert points[0]["tokenId"] == "token-b"


def test_clickhouse_stats_do_not_emit_yes_price_for_source_first(monkeypatch, install_semantics):
    install_semantics("source_first_second", ("Lakers", "Celtics"))
    monkeypatch.setattr(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        lambda *_args, **_kwargs: [
            {
                "market_id": 7,
                "token_id": "token-a",
                "outcome": "YES",
                "latest_token_price": "0.65",
                "latest_trade_block": 90,
                "trade_count_24h": 3,
                "volume_24h": "100",
            }
        ],
    )

    stats = clickhouse_orderfilled_service.get_market_stats({}, [7])

    assert stats is not None
    assert stats[7]["latest_price"] is None
    assert stats[7]["latest_token_id"] == "token-a"
    assert stats[7]["latest_token_price"] == "0.6500000000"
    assert [item["sourceLabel"] for item in stats[7]["outcome_prices"]] == [
        "Lakers",
        "Celtics",
    ]


def test_clickhouse_directional_aggregate_without_receipt_is_dropped(
    monkeypatch,
    install_semantics,
):
    install_semantics("up_down_labels", ("Up", "Down"))
    monkeypatch.setattr(
        clickhouse_orderfilled_service,
        "_query_json_rows",
        lambda *_args, **_kwargs: [
            {
                "market_id": 7,
                "outcome": "YES",
                "direction": "bullish",
                "avg_price": "0.60",
                "entry_yes_price": "0.60",
                "latest_block": 100,
                "source_from_block": 70,
                "source_through_block": 100,
                "score": "90",
            }
        ],
    )

    rows = clickhouse_orderfilled_service.get_alpha_volume_signal_rows({}, limit=4)

    assert rows == []
