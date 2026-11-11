"""Bootstrap hints only; domain readers remain the key and validity authority.

Parameterized/dynamic evidence readers use the same Redis store on demand.
Prefetch never substitutes a different limit, city, revision or market.
"""
from contextlib import nullcontext

ALIASES = {
    "nba-scoreboard": "snapshot:sports:nba",
    "nba-intel": "snapshot:sports:nba-intel",
    "espn-matchup-predictor": "snapshot:sports:nba-matchup-predictor",
    "esports-intel": "snapshot:esports:esports-intel",
    "sports-odds": "snapshot:sports:sports-odds",
    "f1-trackside": "snapshot:sports:f1",
    "defi-token-watch": "snapshot:finance:defi-token-watch",
    "crypto-funding-watch": "snapshot:crypto:funding-watch",
    "breaking-event-radar": "snapshot:evidence:breaking-event-radar",
    "market-tv-wire": "snapshot:content:market-tv-wire",
    "market-youtube-channels": "snapshot:content:market-tv-wire",
    "weather-market-browser": "snapshot:weather:markets",
    "global-weather-map": "snapshot:weather:global-map",
    "weather-news": "snapshot:weather:news",
    "new-market-signals": "snapshot:markets:new-market-signals",
    "crypto-watch": "snapshot:markets:crypto",
    "commodities-watch": "snapshot:markets:commodities",
    "jin10-flash": "snapshot:macro:jin10",
    "food-retail-basket": "snapshot:macro:food-retail-basket-pressure",
    "geo-sanctions-shock": "snapshot:world:geo-sanctions-shock",
    "natural-hazards": "snapshot:world:natural-hazards",
    "global-transport-shipping": "snapshot:transport:global-shipping",
    "alpha-signal": "snapshot:signals:alpha",
    "whale-tracker": "snapshot:signals:whales",
    "suspicious-flow": "snapshot:signals:suspicious",
    "crypto-order-flow": "snapshot:crypto-strategy",
    "options-implied-probability": "snapshot:crypto-strategy",
    "crypto-exchange-inflow": "snapshot:crypto-strategy",
}


def batch_reads(store, panel_ids):
    if getattr(store, "backend", "sqlite") != "redis":
        return nullcontext()
    namespaces = []
    for panel_id in panel_ids:
        if panel_id in ALIASES:
            namespaces.append(ALIASES[panel_id])
        else:
            namespaces.extend(prefix + panel_id for prefix in (
                "runtime:finance:", "runtime:tech:", "snapshot:macro:", "snapshot:macro-registry:"))
        if panel_id in {"tradfi-perp-radar", "crypto-etf-flow", "stablecoin-monitor"}:
            namespaces.append("runtime:finance:external-sources")
    return store.read_namespaces(namespaces)
