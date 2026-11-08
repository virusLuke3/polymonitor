"""Read-only sports projections and shared, bounded source collection.

NBA discovery is owned by the existing NBA watcher. These projections only
acquire the detail/stats that that owner does not already retain.
"""
from __future__ import annotations

import json
import time
from datetime import datetime

from api.services.panel_evidence_store import SourceSpec, collect_one, collect_sources, fetch_bytes, payload, read_source
from api.services.sports_expansion.parsers import (
    parse_dota_match, parse_leaders, parse_pro_matches, parse_standings, parse_summary, parse_tennis,
)
from data_sources import source_value

PANEL_IDS = (
    "sports-spread-monitor", "sports-total-monitor", "sports-player-props", "sports-tournament-path",
    "sports-season-race", "sports-awards-watch", "esports-map-state", "esports-tournament-path",
)
STANDINGS = SourceSpec("sports:nba-standings:v1", "ESPN NBA standings", "POLYDATA_SPORTS_ESPN_STANDINGS_URL", parse_standings, cadence=21600, stale_after=64800, retain_for=3*86400)
LEADERS = SourceSpec("sports:nba-leaders:v1", "ESPN NBA season statistics", "POLYDATA_SPORTS_ESPN_LEADERS_URL", parse_leaders, cadence=21600, stale_after=64800, retain_for=3*86400)
TENNIS = SourceSpec("sports:atp-tournament:v1", "ESPN ATP tournament results", "POLYDATA_SPORTS_ESPN_TENNIS_URL", parse_tennis, cadence=900, stale_after=2700, retain_for=86400)
PRO_MATCHES = SourceSpec("sports:dota-pro-matches:v1", "OpenDota professional results", "POLYDATA_ESPORTS_OPENDOTA_PRO_MATCHES_URL", parse_pro_matches, cadence=900, stale_after=2700, retain_for=86400)
SUMMARY = SourceSpec("sports:nba-game-summary:v1", "ESPN NBA game box score and reference lines", "POLYDATA_SPORTS_ESPN_SUMMARY_URL", parse_summary, cadence=600, stale_after=1800, retain_for=86400)
DOTA_MATCH = SourceSpec("sports:dota-map:v1", "OpenDota completed match replay", "POLYDATA_ESPORTS_OPENDOTA_MATCH_URL", parse_dota_match, cadence=900, stale_after=2700, retain_for=86400)


def _nba(store):
    source = store.get_stale("snapshot:sports:nba", json.dumps({"limit": 10}, sort_keys=True)) or {}
    generated = source.get("generatedAt")
    try:
        age = time.time() - datetime.fromisoformat(generated.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, AttributeError):
        age = float("inf")
    usable = 0 <= age <= 900 and isinstance(source.get("items"), list)
    return source if usable else {}, {"id": "nba-scoreboard", "label": "Shared NBA scoreboard owner",
        "lastSuccessAt": generated, "usable": usable, "stale": age > 180,
        "error": None if usable else "scoreboard-unavailable"}


def collect(store, *, force=False):
    result = collect_sources(store, [STANDINGS, LEADERS, TENNIS, PRO_MATCHES], force=force, budget=300)
    board, _ = _nba(store)
    games = board.get("items", [])
    # Live first, then newest completed game; pregame is useful if no final exists.
    candidates = sorted(games, key=lambda g: (g.get("state") == "in", g.get("state") == "post", str(g.get("tipoff") or "")), reverse=True)
    selected = next((g for g in candidates if str(g.get("id", "")).isdigit()), None)
    def summary():
        if not selected:
            raise ValueError("NBA owner has no recent identified game")
        url = source_value(SUMMARY.url_env).format(event_id=selected["id"])
        raw = fetch_bytes(url, max_bytes=SUMMARY.max_bytes, timeout=SUMMARY.timeout)
        data = parse_summary(raw)
        if data["eventId"] != str(selected["id"]):
            raise ValueError("NBA game identity mismatch")
        return raw, data
    state = collect_one(store, SUMMARY, acquire=summary, force=force)
    result[SUMMARY.key] = state.get("error") or "stored-or-not-due"
    matches, _ = read_source(store, PRO_MATCHES)
    latest = next(iter(matches.get("matches", [])), None)
    def detail():
        if not latest or not str(latest["id"]).isdigit():
            raise ValueError("No identified professional Dota match")
        raw = fetch_bytes(source_value(DOTA_MATCH.url_env).format(match_id=latest["id"]), max_bytes=DOTA_MATCH.max_bytes, timeout=DOTA_MATCH.timeout)
        data = parse_dota_match(raw)
        if data["id"] != latest["id"]:
            raise ValueError("Dota match identity mismatch")
        return raw, data
    state = collect_one(store, DOTA_MATCH, acquire=detail, force=force)
    result[DOTA_MATCH.key] = state.get("error") or "stored-or-not-due"
    return result


def get_snapshot(store, panel_id, *, limit=100):
    if panel_id not in PANEL_IDS:
        raise ValueError("Unknown sports expansion panel")
    if panel_id in {"sports-spread-monitor", "sports-total-monitor", "sports-player-props"}:
        data, meta = read_source(store, SUMMARY)
        return payload(panel_id, [meta], game=data or None,
            coverage="One identified NBA game; official game facts via ESPN, bookmaker reference lines are not executable quotes.")
    if panel_id == "sports-season-race":
        data, meta = read_source(store, STANDINGS)
        return payload(panel_id, [meta], groups=data.get("groups", []), coverage="NBA conference standings as ranked by ESPN; no final-seeding forecast.")
    if panel_id == "sports-awards-watch":
        data, meta = read_source(store, LEADERS)
        return payload(panel_id, [meta], **data, eligibility=None, voting=None,
            coverage="Current NBA statistical leaders provide award research context, not official candidates, eligibility or award probabilities.")
    if panel_id == "sports-tournament-path":
        data, meta = read_source(store, TENNIS)
        return payload(panel_id, [meta], tournaments=data.get("tournaments", []),
            coverage="ATP men's singles rounds and actual results; future opponent edges are not inferred.")
    if panel_id == "esports-map-state":
        data, meta = read_source(store, DOTA_MATCH)
        return payload(panel_id, [meta], match=data or None, coverage="Latest acquired named-team Dota 2 professional match replay; completed game, not a live feed.")
    data, meta = read_source(store, PRO_MATCHES)
    return payload(panel_id, [meta], matches=data.get("matches", [])[:max(1,min(100,limit))],
        bracket=None, coverage=data.get("coverage", "Recent Dota 2 professional results") + "; observed series games only, full bracket and advancement rules not supplied.")
