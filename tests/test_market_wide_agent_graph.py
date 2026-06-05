from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from typing import Any
from unittest.mock import patch

from agent.market_wide.graph import GRAPH_VERSION, run_forecast_intelligence_graph
from agent.market_wide.snapshot import (
    QUANT_HISTORY_NAMESPACE,
    QUANT_SNAPSHOT_NAMESPACE,
    DEFAULT_LENSES,
    build_market_wide_snapshot,
    quant_history_cache_key,
    quant_snapshot_cache_key,
    read_market_wide_quant_snapshot,
    seed_market_wide_snapshots,
    store_market_wide_snapshot,
)


@dataclass
class FakeUsage:
    runtime: str = "chat"
    input_tokens: int = 11
    output_tokens: int = 7
    total_tokens: int = 18
    input_chars: int = 123


class FakeClient:
    configured = True
    model = "fake-model"

    def __init__(self) -> None:
        self.last_usage = FakeUsage()
        self.workflow_names: list[str] = []

    def complete_json(self, messages: list[dict[str, str]], *, max_tokens: int, workflow_name: str) -> str:
        self.workflow_names.append(workflow_name)
        if "panel_writer" in workflow_name:
            return json.dumps({
                "brief": "Liquidity is clustering around the leading market while catalyst risk remains visible.",
                "specialMarkets": [{
                    "title": "Will the event happen?",
                    "why": "It combines close odds with visible trade flow.",
                    "trend": "Knife-edge odds",
                    "severity": "warning",
                    "evidence": "52%",
                }],
                "themes": [{
                    "label": "LIQUIDITY",
                    "title": "Attention concentration",
                    "summary": "The loaded board is concentrating around one active event.",
                    "severity": "neutral",
                    "evidence": "24h volume",
                }],
                "watchlist": [{
                    "title": "Resolution wording",
                    "reason": "Ambiguous criteria can change how users price the event.",
                    "horizon": "event close",
                    "severity": "warning",
                }],
                "focus": [{
                    "label": "SPECIAL",
                    "title": "Close-price market",
                    "summary": "The standout market sits near the repricing zone.",
                    "severity": "warning",
                    "evidence": "52%",
                }],
                "evidence": ["52% top price", "$1.2K volume"],
            })
        return json.dumps({
            "findings": [{
                "label": "LIQUIDITY",
                "title": "Visible flow",
                "summary": "Trade flow is concentrated in the leading market.",
                "severity": "neutral",
                "evidence": "$1.2K",
            }],
            "risks": ["Evidence can go stale quickly."],
            "watch": ["Watch the next large fill."],
            "confidence": "medium",
            "probabilityAdjustment": "market-implied probability remains the anchor",
        })


class MissingClient:
    configured = False
    model = "missing"


class FakeSnapshotStore:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], Any] = {}

    def set(self, namespace: str, cache_key: str, payload: Any, ttl: int) -> None:
        self.values[(namespace, cache_key)] = payload

    def get(self, namespace: str, cache_key: str) -> Any:
        return self.values.get((namespace, cache_key))

    def get_stale(self, namespace: str, cache_key: str) -> Any:
        return self.values.get((namespace, cache_key))


class MarketWideAgentGraphTestCase(unittest.TestCase):
    def test_forecast_graph_runs_specialists_and_preserves_response_schema(self):
        payload = {"lens": "overview", "forecastRunId": "fig-test", "markets": []}
        context = {
            "metrics": {"coveredMarkets": 1, "topCategories": ["politics 1"]},
            "marketCandidates": [{
                "title": "Will the event happen?",
                "category": "politics",
                "latestPrice": 0.52,
                "price24hAgo": 0.47,
                "bestBid": 0.50,
                "bestAsk": 0.55,
                "volume24h": 1200,
                "tradeCount24h": 8,
            }],
            "trades": [
                {"market": "Will the event happen?", "price": 0.47},
                {"market": "Will the event happen?", "price": 0.52},
                {"market": "Will the event happen?", "price": 0.57},
            ],
            "contextChars": 777,
        }
        client = FakeClient()

        response = run_forecast_intelligence_graph(
            payload,
            "overview",
            context,
            [],
            client,
            normalize=lambda raw, _payload, lens, _search, model: {"status": "live", "lens": lens, "model": model, **raw},
            fallback=lambda _payload, lens, reason, _search: {"status": reason, "lens": lens, "brief": "fallback"},
        )

        self.assertEqual(response["status"], "live")
        self.assertEqual(response["forecastRunId"], "fig-test")
        self.assertEqual(response["agentArchitecture"], GRAPH_VERSION)
        self.assertIn("specialMarkets", response)
        self.assertEqual(response["agentGraph"]["mode"], "supervisor-worker")
        self.assertEqual(response["agentGraph"]["nodes"], [
            "evidence_builder",
            "quant_forecaster",
            "related_markets",
            "microstructure",
            "catalyst",
            "resolution",
            "skeptic",
            "panel_writer",
        ])
        self.assertEqual(response["usage"]["requests"], 5)
        self.assertEqual(response["usage"]["contextChars"], 777)
        self.assertIn("quantForecaster", response["agentGraph"])
        self.assertIn("relatedMarkets", response["agentGraph"])
        self.assertEqual(response["agentGraph"]["quantForecaster"]["priceDriftLeaders"][0]["drift24h"], "+5.0 pts")
        self.assertEqual(response["agentGraph"]["quantForecaster"]["lobSpreads"][0]["spread"], "5.0 pts")
        self.assertEqual(response["agentGraph"]["quantForecaster"]["volatilityLeaders"][0]["priceRange"], "10.0 pts")

    def test_forecast_graph_adds_quant_and_related_market_structure(self):
        payload = {"lens": "overview", "forecastRunId": "fig-structure", "markets": []}
        context = {
            "metrics": {"coveredMarkets": 2, "topCategories": ["politics 2"]},
            "marketCandidates": [{
                "title": "Peace deal by August?",
                "category": "politics",
                "latestPrice": 0.51,
                "change24h": 0.04,
                "volume24h": 592650,
                "tradeCount24h": 423,
            }],
            "marketGroups": [{
                "title": "Strait of Hormuz traffic returns to normal",
                "volume24h": 106903,
                "tradeCount24h": 1,
                "outcomes": [
                    {"label": "By July 31", "yesPrice": 0.455, "volume24h": 82787},
                    {"label": "By December 31", "yesPrice": 0.745, "volume24h": 24116},
                ],
            }],
            "contextChars": 888,
        }

        response = run_forecast_intelligence_graph(
            payload,
            "overview",
            context,
            [],
            FakeClient(),
            normalize=lambda raw, _payload, lens, _search, model: {"status": "live", "lens": lens, "model": model, **raw},
            fallback=lambda _payload, lens, reason, _search: {"status": reason, "lens": lens, "brief": "fallback"},
        )

        quant = response["agentGraph"]["quantForecaster"]
        related = response["agentGraph"]["relatedMarkets"]
        self.assertEqual(quant["repricingZones"][0]["title"], "Peace deal by August?")
        self.assertEqual(quant["repricingZones"][0]["price"], "51.0%")
        self.assertEqual(related["ladders"][0]["title"], "Strait of Hormuz traffic returns to normal")
        self.assertEqual(related["ladders"][0]["spread"], "29.0 pts")
        self.assertEqual(quant["priceDriftLeaders"][0]["drift24h"], "+4.0 pts")
        self.assertEqual(quant["relatedMarketArbitrageScores"][0]["title"], "Strait of Hormuz traffic returns to normal")
        self.assertGreater(quant["relatedMarketArbitrageScores"][0]["score"], 0)

    def test_missing_api_key_still_exposes_deterministic_structure_nodes(self):
        response = run_forecast_intelligence_graph(
            {"lens": "overview", "forecastRunId": "fig-missing"},
            "overview",
            {
                "marketCandidates": [{"title": "Market A", "latestPrice": 0.5, "volume24h": 1000, "tradeCount24h": 10}],
                "marketGroups": [],
            },
            [],
            MissingClient(),
            normalize=lambda raw, _payload, lens, _search, model: {"status": "live", "lens": lens, "model": model, **raw},
            fallback=lambda _payload, lens, reason, _search: {"status": reason, "lens": lens, "brief": "fallback"},
        )

        self.assertEqual(response["status"], "missing-api-key")
        self.assertEqual(response["agentGraph"]["nodes"], ["evidence_builder", "quant_forecaster", "related_markets"])
        self.assertEqual(response["agentGraph"]["quantForecaster"]["repricingZones"][0]["title"], "Market A")

    def test_store_market_wide_snapshot_persists_quant_snapshot_separately(self):
        redis_values: dict[tuple[str, str], Any] = {}
        store = FakeSnapshotStore()
        helpers = {
            "set_cached_json": lambda namespace, cache_key, payload, ttl: redis_values.__setitem__((namespace, cache_key), payload),
            "get_cached_json": lambda namespace, cache_key: redis_values.get((namespace, cache_key)),
            "SNAPSHOT_STORE": store,
        }
        snapshot = {
            "schemaVersion": 1,
            "lens": "overview",
            "generatedAt": "2026-06-05T00:00:00Z",
            "expiresAt": "2026-06-05T12:00:00Z",
            "data": {
                "lens": "overview",
                "status": "live",
                "model": "fake-model",
                "forecastRunId": "fig-quant-test",
                "agentArchitecture": GRAPH_VERSION,
                "agentGraph": {
                    "runId": "fig-quant-test",
                    "version": GRAPH_VERSION,
                    "quantForecaster": {"node": "quant_forecaster", "priceDriftLeaders": [{"title": "A"}]},
                    "relatedMarkets": {"node": "related_markets", "arbitrageScores": [{"title": "Group A", "score": 22.0}]},
                },
            },
        }

        store_market_wide_snapshot(helpers, snapshot)

        latest_key = quant_snapshot_cache_key("overview")
        history_key = quant_history_cache_key("overview", "fig-quant-test")
        self.assertIn((QUANT_SNAPSHOT_NAMESPACE, latest_key), redis_values)
        self.assertIn((QUANT_HISTORY_NAMESPACE, history_key), redis_values)
        self.assertIn((QUANT_SNAPSHOT_NAMESPACE, latest_key), store.values)
        quant_snapshot = read_market_wide_quant_snapshot(helpers, "overview")
        self.assertEqual(quant_snapshot["runId"], "fig-quant-test")
        self.assertEqual(quant_snapshot["quantForecaster"]["priceDriftLeaders"][0]["title"], "A")

    def test_seed_all_lenses_share_one_forecast_run_id_when_timer_runs_default(self):
        stored: dict[tuple[str, str], Any] = {}
        helpers = {
            "get_active_markets_snapshot": lambda limit: {"items": [{"title": "A", "category": "politics"}]},
            "get_market_groups_payload": lambda query, page, page_size, status: {"items": [{"title": "B", "category": "sports"}]},
            "get_latest_content_payload": lambda limit: {"items": []},
            "get_recent_trades_snapshot": lambda limit: [],
            "get_recent_oracle_snapshot": lambda limit: [],
            "get_cached_json": lambda namespace, cache_key: stored.get((namespace, cache_key)),
            "set_cached_json": lambda namespace, cache_key, payload, ttl: stored.__setitem__((namespace, cache_key), payload),
        }

        snapshots = seed_market_wide_snapshots(helpers, live=False, force=True)

        self.assertEqual([snapshot["lens"] for snapshot in snapshots], list(DEFAULT_LENSES))
        run_ids = {snapshot["data"].get("forecastRunId") for snapshot in snapshots}
        self.assertEqual(len(run_ids), 1)
        self.assertTrue(next(iter(run_ids)).startswith("fig-seed-"))

    def test_gateway_seed_delegates_budget_to_gateway_host(self):
        helpers = {
            "get_active_markets_snapshot": lambda limit: {"items": []},
            "get_market_groups_payload": lambda query, page, page_size, status: {"items": []},
            "get_latest_content_payload": lambda limit: {"items": []},
            "get_recent_trades_snapshot": lambda limit: [],
            "get_recent_oracle_snapshot": lambda limit: [],
            "get_cached_json": lambda namespace, cache_key: None,
        }

        with patch("agent.market_wide.snapshot._seed_live_enabled", return_value=True), \
             patch("agent.market_wide.snapshot.gateway_configured", return_value=True), \
             patch("agent.market_wide.snapshot.claim_agent_live_call", side_effect=AssertionError("seed should not double-claim budget")), \
             patch("agent.market_wide.snapshot.call_market_wide_insight_gateway", return_value={"status": "live", "generatedAt": "2026-06-05T00:00:00Z"}):
            snapshot = build_market_wide_snapshot(helpers, "trend", live=True, force=True, run_id="fig-test")

        self.assertTrue(snapshot["liveAttempted"])
        self.assertTrue(snapshot["budget"]["delegatedToGateway"])
        self.assertEqual(snapshot["data"]["forecastRunId"], "fig-test")


if __name__ == "__main__":
    unittest.main()
