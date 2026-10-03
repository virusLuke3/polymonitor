from __future__ import annotations
from conftest import missing_route_dependency
from api.routes import runtime_panels as _route_runtime_panels

from api.routes.runtime_panels import RuntimePanelRouteDependencies


from flask import Flask


from api.routes.runtime_panels import create_runtime_panels_blueprint
from api.runtime_panels import RUNTIME_PANEL_MODULES, get_default_panel_ids
from api.services.bootstrap_service import BootstrapPrewarmDependencies


def test_hazard_http_cache_never_outlives_source_freshness(monkeypatch):
    monkeypatch.setattr(_route_runtime_panels.time, "time", lambda: 1790836920.0)  # 2026-10-01 06:42 UTC
    source = {"status": "ok", "staleAfter": "2026-10-01T06:42:12Z"}
    assert _route_runtime_panels._hazard_http_cache_control({"sources": [source]}, 30) == "public, max-age=2, must-revalidate"
    source["staleAfter"] = "2026-10-01T06:41:00Z"
    assert _route_runtime_panels._hazard_http_cache_control({"sources": [source]}, 30) == "no-store"
    source.update(status="degraded", staleAfter="2026-10-01T06:45:00Z")
    assert _route_runtime_panels._hazard_http_cache_control({"sources": [source]}, 30) == "no-store"


def test_hazard_http_cache_releases_old_body_before_scheduled_browser_refresh(monkeypatch):
    now = 1790836920.0
    monkeypatch.setattr(_route_runtime_panels.time, "time", lambda: now)
    source = {"status": "partial", "staleAfter": "2026-10-01T06:42:30Z",
              "lastSuccessAt": "2026-10-01T06:40:30Z"}
    payload = {"sources": [source]}
    original = dict(source)
    # Mirrors the production edge-cache failure: thirty seconds remain in an
    # old snapshot, but its replacement is available before the browser polls.
    assert _route_runtime_panels._hazard_http_cache_control(payload, 30) == "public, max-age=20, must-revalidate"
    now += 20
    assert _route_runtime_panels._hazard_http_cache_control(payload, 30) == "no-store"
    assert source == original


def test_runtime_panel_modules_have_unique_ids_and_routes():
    panel_ids = [panel.panel_id for panel in RUNTIME_PANEL_MODULES]
    routes = [panel.route for panel in RUNTIME_PANEL_MODULES]

    assert len(panel_ids) == len(set(panel_ids))
    assert len(routes) == len(set(routes))
    assert all(route.startswith("/runtime/") for route in routes)


def test_runtime_panel_blueprint_registers_all_routes(monkeypatch):
    from telegram.topics import runtime_bridge

    published = []
    monkeypatch.setattr(runtime_bridge, "publish_panel_snapshot", lambda *args: published.append(args))
    app = Flask(__name__)
    helpers = {
        "COMMODITY_SYMBOLS": [],
        "CRYPTO_SYMBOLS": [],
        "get_market_group_snapshot": lambda symbols, kind: {"kind": kind, "items": symbols},
        "get_polymarket_macro_map_snapshot": lambda limit=12: {"limit": limit},
        "get_f1_panel_snapshot": lambda limit=10: {"limit": limit},
        "get_geo_sanctions_shock_snapshot": lambda limit=6: {"limit": limit},
        "get_global_transport_shipping_snapshot": lambda limit=14: {"limit": limit},
        "get_aviation_viewport_snapshot": lambda bbox, zoom=2, limit=180: {
            "schemaVersion": "aviation-viewport.v1",
            "generatedAt": "2026-08-16T00:00:00Z",
            "bbox": list(bbox),
            "zoom": zoom,
            "aircraft": [],
            "aircraftCount": 0,
            "availableAircraftCount": 0,
            "source": "fixture",
            "limitations": [],
            "limit": limit,
        },
        "get_global_weather_map_snapshot": lambda limit=34: {"limit": limit},
        "get_grid_esports_snapshot": lambda limit=10: {"limit": limit},
        "get_sports_odds_snapshot": lambda limit=8: {"limit": limit},
        "get_jin10_panel_snapshot": lambda limit=24: {"limit": limit},
        "get_nba_scoreboard_snapshot": lambda limit=10: {"limit": limit},
        "get_nba_intel_snapshot": lambda limit=12: {"limit": limit},
        "get_nba_matchup_predictor_snapshot": lambda limit=8: {"limit": limit},
        "get_inflation_nowcast_snapshot": lambda: {"items": []},
        "get_alpha_signal_snapshot": lambda limit=8: {"limit": limit},
        "get_crypto_funding_watch_snapshot": lambda limit=16: {"limit": limit},
        "get_commodity_equity_transmission_snapshot": lambda limit=8: {"limit": limit},
        "get_cpi_release_calendar_snapshot": lambda limit=8: {"limit": limit},
        "get_cpi_release_command_center_snapshot": lambda limit=36: {"limit": limit},
        "get_cpi_components_pressure_registry_snapshot": lambda limit=48: {"limit": limit},
        "get_energy_gasoline_shock_snapshot": lambda limit=6: {"limit": limit},
        "get_fed_reaction_growth_risk_board_snapshot": lambda limit=36: {"limit": limit},
        "get_food_retail_basket_snapshot": lambda limit=8: {"limit": limit},
        "get_goods_tariff_supply_watch_snapshot": lambda limit=36: {"limit": limit},
        "get_supply_tariff_import_watch_snapshot": lambda limit=8: {"limit": limit},
        "get_shelter_rent_oer_pressure_snapshot": lambda limit=8: {"limit": limit},
        "get_labor_wage_services_pressure_snapshot": lambda limit=8: {"limit": limit},
        "get_labor_services_inflation_monitor_snapshot": lambda limit=36: {"limit": limit},
        "get_growth_demand_recession_tracker_snapshot": lambda limit=8: {"limit": limit},
        "get_fed_rates_polymarket_gap_snapshot": lambda limit=8: {"limit": limit},
        "get_new_market_signals_snapshot": lambda limit=12: {"limit": limit},
        "get_whale_trades_snapshot": lambda limit=14: {"limit": limit},
        "get_suspicious_trades_snapshot": lambda limit=12: {"limit": limit},
        "get_weather_news_snapshot": lambda limit=24: {"limit": limit},
        "get_natural_hazard_map_snapshot": lambda source, limit=1200, zoom=2: {
            "schemaVersion": "natural-hazards-map.v1",
            "generatedAt": "2026-08-16T00:00:00Z",
            "events": [],
            "sources": [],
            "isPartial": False,
            "errors": [],
            "counts": {"events": 0, "byHazardKind": {}},
            "meta": {"source": source, "limit": limit, "zoom": zoom},
        },
        "get_natural_hazard_event_detail": lambda event_id: {
            "schemaVersion": "natural-hazard-detail.v1",
            "generatedAt": "2026-08-16T00:00:00Z",
            "event": {"id": event_id},
        },
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
    registered_routes = {rule.rule for rule in app.url_map.iter_rules()}

    for panel in RUNTIME_PANEL_MODULES:
        assert panel.route in registered_routes

    client = app.test_client()
    commodity_response = client.get(
        "/runtime/finance/commodity-equity-transmission?limit=3",
    )
    assert commodity_response.status_code == 200
    assert commodity_response.get_json()["limit"] == 3
    map_response = client.get("/runtime/world/natural-hazards/map?source=usgs&zoom=2")
    assert map_response.status_code == 200
    assert map_response.headers["Cache-Control"] == "public, max-age=30, must-revalidate"
    assert map_response.headers["ETag"]
    assert map_response.headers["X-Map-Source"] == "usgs"
    assert map_response.headers["Server-Timing"].startswith("hazard-map;dur=")
    assert map_response.get_json()["meta"]["zoom"] == 2.0
    conditional = client.get(
        "/runtime/world/natural-hazards/map?source=usgs&zoom=2",
        headers={"If-None-Match": map_response.headers["ETag"]},
    )
    assert conditional.status_code == 304

    aviation_response = client.get(
        "/runtime/transport/aviation-viewport?bbox=-75,39,-72,42&zoom=5&limit=120",
    )
    assert aviation_response.status_code == 200
    assert aviation_response.headers["Cache-Control"] == "public, max-age=15, stale-while-revalidate=30"
    assert aviation_response.headers["ETag"]
    assert aviation_response.get_json()["bbox"] == [-75.0, 39.0, -72.0, 42.0]
    aviation_conditional = client.get(
        "/runtime/transport/aviation-viewport?bbox=-75,39,-72,42&zoom=5&limit=120",
        headers={"If-None-Match": aviation_response.headers["ETag"]},
    )
    assert aviation_conditional.status_code == 304
    assert (
        client.get(
            "/runtime/transport/aviation-viewport?bbox=75,39,-72,42&zoom=5",
        ).status_code
        == 400
    )

    detail_response = client.get("/runtime/world/natural-hazards/events/earthquake%3Ausgs%3Atest")
    assert detail_response.status_code == 200
    assert detail_response.get_json()["event"]["id"] == "earthquake:usgs:test"
    assert published == []


def test_default_workspace_panel_ids_include_runtime_and_static_panels():
    panel_ids = get_default_panel_ids()

    assert "active-markets" in panel_ids
    assert "espn-matchup-predictor" in panel_ids
    assert "esports-intel" in panel_ids
    assert "sports-odds" in panel_ids
    assert "crypto-funding-watch" in panel_ids
    assert "global-transport-shipping" in panel_ids
    assert "cpi-release-command-center" in panel_ids
    assert "cpi-components-pressure-registry" in panel_ids
    assert "goods-tariff-supply-watch" in panel_ids
    assert "labor-services-inflation-monitor" in panel_ids
    assert "fed-reaction-growth-risk-board" in panel_ids
    assert "f1-trackside" in panel_ids
    assert len(panel_ids) == len(set(panel_ids))


def test_api_server_context_satisfies_bootstrap_prewarm_contract():
    from api.runtime import ServiceRuntime

    with ServiceRuntime() as runtime:
        assert callable(runtime.bootstrap_prewarm.get_active_markets_snapshot)
