from __future__ import annotations

import json

from scripts.ops.audit_panel_health import DEFAULT_CONTRACT, build_panel_snapshot, validate_contract


def test_operations_inventory_matches_the_current_frontend_registry():
    contract = json.loads(DEFAULT_CONTRACT.read_text())
    result = validate_contract(contract)
    assert result["errors"] == []
    assert result["contractCount"] == result["activeCount"]
    for group in contract["groups"]:
        assert not {"polysignal-feed", "polybeats-feed"}.intersection(group["panelIds"])
        assert all("polybeats" not in unit and "polysignal" not in unit for unit in group.get("serviceNames", []))


def test_reused_panels_no_longer_claim_retired_or_unrelated_data_owners():
    contract = json.loads(DEFAULT_CONTRACT.read_text())
    owners = {panel: group["owner"] for group in contract["groups"] for panel in group["panelIds"]}
    for panel in ("price-implications", "sample-chain-trades", "oracle-timeline"):
        assert owners[panel] == "market-wide-agent"
    for panel in ("crypto-watch", "crypto-perp-funding", "stablecoin-monitor", "options-implied-probability"):
        assert owners[panel] == "crypto-strategy"
    for panel in ("weather-quote-table", "weather-quote-detail"):
        assert owners[panel] == "weather-markets"
    assert owners["politics-executive"] == "presidential-documents"


def test_current_inventory_does_not_invent_health_when_evidence_is_absent():
    contract = json.loads(DEFAULT_CONTRACT.read_text())
    result = build_panel_snapshot(contract, validate_contract(contract), system={}, seed={})
    assert result["summary"]["healthyCount"] == 0
    assert result["summary"]["panelCount"] == result["contract"]["activeCount"]
    assert all(panel["observedAt"] is None for panel in result["panels"])
