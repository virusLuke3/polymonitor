from __future__ import annotations
from conftest import missing_route_dependency
from api.routes import runtime_panels as _route_runtime_panels

from api.routes.runtime_panels import RuntimePanelRouteDependencies

import unittest
from types import SimpleNamespace
from typing import Any, Dict

from flask import Flask


from api.routes.runtime_panels import create_runtime_panels_blueprint
from api.services import crypto_funding_service


class CryptoFundingWatchTestCase(unittest.TestCase):
    def test_runtime_panel_route_clamps_invalid_and_large_limits(self):
        seen_limits = []
        app = Flask(__name__)
        helpers = {
            "COMMODITY_SYMBOLS": [],
            "CRYPTO_SYMBOLS": [],
            "get_market_group_snapshot": lambda symbols, kind: {"kind": kind, "items": symbols},
            "get_f1_panel_snapshot": lambda limit=10: {"limit": limit},
            "get_geo_sanctions_shock_snapshot": lambda limit=6: {"limit": limit},
            "get_jin10_panel_snapshot": lambda limit=24: {"limit": limit},
            "get_nba_scoreboard_snapshot": lambda limit=10: {"limit": limit},
            "get_nba_intel_snapshot": lambda limit=12: {"limit": limit},
            "get_nba_matchup_predictor_snapshot": lambda limit=8: {"limit": limit},
            "get_inflation_nowcast_snapshot": lambda: {"items": []},
            "get_alpha_signal_snapshot": lambda limit=8: {"limit": limit},
            "get_crypto_funding_watch_snapshot": lambda limit=80: seen_limits.append(limit) or {"limit": limit},
            "get_cpi_release_calendar_snapshot": lambda limit=8: {"limit": limit},
            "get_energy_gasoline_shock_snapshot": lambda limit=6: {"limit": limit},
            "get_food_retail_basket_snapshot": lambda limit=8: {"limit": limit},
            "get_polymarket_macro_map_snapshot": lambda limit=12: {"limit": limit},
            "get_whale_trades_snapshot": lambda limit=14: {"limit": limit},
            "get_suspicious_trades_snapshot": lambda limit=12: {"limit": limit},
            "get_new_market_signals_snapshot": lambda limit=12: {"limit": limit},
        }
        app.register_blueprint(
            create_runtime_panels_blueprint(
                RuntimePanelRouteDependencies(
                    panel_context=_route_runtime_panels.RuntimePanelContext.from_context(helpers),
                    utc_now_iso=helpers.get("utc_now_iso", missing_route_dependency),
                    natural_hazard_map_snapshot=helpers.get("get_natural_hazard_map_snapshot", None),
                    natural_hazard_event_detail=helpers.get("get_natural_hazard_event_detail", None),
                    natural_hazard_related_markets=helpers.get("get_natural_hazard_related_markets", None),
                    aviation_viewport_snapshot=helpers.get("get_aviation_viewport_snapshot", None),
                )
            )
        )

        with app.test_client() as client:
            invalid = client.get("/runtime/crypto/funding-watch?limit=nope")
            large = client.get("/runtime/crypto/funding-watch?limit=999")

        self.assertEqual(200, invalid.status_code)
        self.assertEqual(200, large.status_code)
        self.assertEqual([80, 120], seen_limits)
