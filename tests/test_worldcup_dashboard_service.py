from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from api.services import worldcup_dashboard_service
from runtime import worldcup_dashboard_watcher


def test_worldcup_dashboard_links_strict_polymarket_market():
    source_schedule = {
        "matches": [
            {
                "num": 1,
                "date": "2026-06-11",
                "time": "13:00 UTC-6",
                "team1": "Mexico",
                "team2": "South Africa",
                "group": "Group A",
                "round": "Matchday 1",
                "ground": "Mexico City",
            }
        ]
    }
    gamma_market = {
        "data": [
            {
                "title": "FIFA World Cup 2026",
                "slug": "fifa-world-cup-2026",
                "markets": [
                    {
                        "question": "Mexico vs South Africa - FIFA World Cup 2026 winner",
                        "slug": "mexico-south-africa-world-cup-2026-winner",
                        "outcomes": '["Mexico","Draw","South Africa"]',
                        "outcomePrices": '["0.52","0.26","0.22"]',
                    }
                ],
            },
            {"title": "Rihanna album 2026", "slug": "rihanna-album-2026"},
        ]
    }

    def http_json_get(url, *, params=None, timeout=12, headers=None):
        if "openfootball" in url:
            return source_schedule
        if "gamma-api.polymarket.com" in url:
            return gamma_market
        raise AssertionError(url)

    ctx = {
        "http_json_get": http_json_get,
        "SETTINGS": SimpleNamespace(worldcup_market_link_scan_limit=4),
    }

    with patch.object(
        worldcup_dashboard_service.worldcup_intel_service,
        "get_worldcup_intel_snapshot",
        return_value={"status": "ok", "weather": [], "news": [], "signals": []},
    ):
        payload = worldcup_dashboard_service.build_worldcup_dashboard_payload(ctx)

    assert payload["providerStates"]["odds"] == "ok"
    assert payload["summary"]["odds"] == 1
    assert payload["summary"]["oddsMatched"] == 1
    assert payload["marketLinker"]["matched"] == 1
    assert payload["marketLinker"]["candidates"] >= 1
    assert payload["matches"][0]["marketLinked"] is True
    assert payload["matches"][0]["oddsLinked"] is True
    odds = payload["odds"][0]
    assert odds["matchId"] == "wc2026-001"
    assert odds["probabilities"][0]["outcome"] == "Mexico"
    assert odds["probabilities"][0]["price"] == "0.52"
    assert "rihanna" not in odds["marketTitle"].lower()


def test_worldcup_dashboard_rejects_event_level_false_positive_market():
    source_schedule = {
        "matches": [
            {
                "num": 2,
                "date": "2026-06-12",
                "time": "02:00 UTC+0",
                "team1": "South Korea",
                "team2": "Czech Republic",
                "group": "Group A",
                "round": "Matchday 1",
                "ground": "Guadalajara (Zapopan)",
            }
        ]
    }
    noisy_gamma_event = {
        "data": [
            {
                "title": "South Korea vs Czech Republic - FIFA World Cup 2026",
                "slug": "south-korea-czech-republic-world-cup-2026",
                "markets": [
                    {
                        "question": "Will China invades Taiwan before GTA VI?",
                        "slug": "will-china-invades-taiwan-before-gta-vi",
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.505","0.495"]',
                    }
                ],
            }
        ]
    }

    def http_json_get(url, *, params=None, timeout=12, headers=None):
        if "openfootball" in url:
            return source_schedule
        if "gamma-api.polymarket.com" in url:
            return noisy_gamma_event
        raise AssertionError(url)

    ctx = {
        "http_json_get": http_json_get,
        "SETTINGS": SimpleNamespace(worldcup_market_link_scan_limit=4),
    }

    with patch.object(
        worldcup_dashboard_service.worldcup_intel_service,
        "get_worldcup_intel_snapshot",
        return_value={"status": "ok", "weather": [], "news": [], "signals": []},
    ):
        payload = worldcup_dashboard_service.build_worldcup_dashboard_payload(ctx)

    assert payload["providerStates"]["odds"] == "empty"
    assert payload["odds"] == []
    assert payload["matches"][0]["marketLinked"] is False
    assert payload["marketLinker"]["matched"] == 0
    assert payload["marketLinker"]["rejections"]["missing-team"] >= 1


def test_worldcup_dashboard_links_match_result_market_group():
    source_schedule = {
        "matches": [
            {
                "num": 1,
                "date": "2026-06-11",
                "time": "13:00 UTC-6",
                "team1": "Mexico",
                "team2": "South Africa",
                "group": "Group A",
                "round": "Matchday 1",
                "ground": "Mexico City",
            }
        ]
    }
    gamma_event = {
        "data": [
            {
                "title": "Mexico vs South Africa - FIFA World Cup 2026",
                "slug": "mexico-vs-south-africa-fifa-world-cup-2026",
                "active": True,
                "closed": False,
                "markets": [
                    {
                        "id": "m1",
                        "question": "Mexico",
                        "groupItemTitle": "Mexico",
                        "slug": "mexico-vs-south-africa-mexico",
                        "active": True,
                        "closed": False,
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.49","0.51"]',
                    },
                    {
                        "id": "m2",
                        "question": "Draw",
                        "groupItemTitle": "Draw",
                        "slug": "mexico-vs-south-africa-draw",
                        "active": True,
                        "closed": False,
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.29","0.71"]',
                    },
                    {
                        "id": "m3",
                        "question": "South Africa",
                        "groupItemTitle": "South Africa",
                        "slug": "mexico-vs-south-africa-south-africa",
                        "active": True,
                        "closed": False,
                        "outcomes": '["Yes","No"]',
                        "outcomePrices": '["0.22","0.78"]',
                    },
                ],
            }
        ]
    }

    def http_json_get(url, *, params=None, timeout=12, headers=None):
        if "openfootball" in url:
            return source_schedule
        if "gamma-api.polymarket.com" in url:
            return gamma_event
        raise AssertionError(url)

    ctx = {
        "http_json_get": http_json_get,
        "SETTINGS": SimpleNamespace(worldcup_market_link_scan_limit=4),
    }

    with patch.object(
        worldcup_dashboard_service.worldcup_intel_service,
        "get_worldcup_intel_snapshot",
        return_value={"status": "ok", "weather": [], "news": [], "signals": []},
    ):
        payload = worldcup_dashboard_service.build_worldcup_dashboard_payload(ctx)

    assert payload["providerStates"]["odds"] == "ok"
    odds = payload["odds"][0]
    assert odds["marketUrl"] == "https://polymarket.com/event/mexico-vs-south-africa-fifa-world-cup-2026"
    assert odds["tradeUrl"] == odds["marketUrl"]
    assert odds["probabilities"][:3] == [
        {
            "outcome": "Mexico",
            "price": "0.49",
            "marketTitle": "Mexico",
            "marketUrl": "https://polymarket.com/event/mexico-vs-south-africa-fifa-world-cup-2026/mexico-vs-south-africa-mexico",
            "clobTokenId": "",
        },
        {
            "outcome": "Draw",
            "price": "0.29",
            "marketTitle": "Draw",
            "marketUrl": "https://polymarket.com/event/mexico-vs-south-africa-fifa-world-cup-2026/mexico-vs-south-africa-draw",
            "clobTokenId": "",
        },
        {
            "outcome": "South Africa",
            "price": "0.22",
            "marketTitle": "South Africa",
            "marketUrl": "https://polymarket.com/event/mexico-vs-south-africa-fifa-world-cup-2026/mexico-vs-south-africa-south-africa",
            "clobTokenId": "",
        },
    ]


def test_worldcup_dashboard_watcher_builds_new_odds_alert_candidate():
    previous = {"odds": [{"matchId": "wc2026-001"}]}
    current = {
        "odds": [
            {"matchId": "wc2026-001"},
            {
                "matchId": "wc2026-002",
                "homeTeam": "South Korea",
                "awayTeam": "Czech Republic",
                "marketTitle": "South Korea vs Czech Republic - FIFA World Cup 2026 winner",
                "marketUrl": "https://polymarket.com/event/south-korea-czech-republic",
                "probabilities": [{"outcome": "South Korea", "price": "0.42"}],
            },
        ]
    }

    new_rows = worldcup_dashboard_watcher._new_odds(previous, current)
    candidate = worldcup_dashboard_watcher._odds_alert_candidate(new_rows[0])

    assert len(new_rows) == 1
    assert candidate.topic == "worldcup"
    assert candidate.priority == "normal"
    assert "World Cup odds listed" in candidate.text
    assert "South Korea vs Czech Republic" in candidate.text
    assert candidate.reply_markup
