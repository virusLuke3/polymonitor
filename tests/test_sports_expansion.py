import json
import time

import pytest

from api.services.sports_expansion.parsers import parse_dota_match, parse_leaders, parse_pro_matches, parse_standings, parse_summary, parse_tennis
from api.services.sports_expansion.snapshot_service import LEADERS, PANEL_IDS, SUMMARY, get_snapshot
from api.services.panel_evidence_store import NAMESPACE, collect_one
from runtime.snapshot_store import SnapshotStore


def raw(value):
    return json.dumps(value).encode()


def test_summary_preserves_zero_and_dnp_and_handicap_direction():
    result = parse_summary(raw({"header": {"id": "11", "competitions": [{"status": {"type": {"state": "post"}}, "competitors": []}]},
        "boxscore": {"players": [{"team": {"abbreviation": "A"}, "statistics": [{"labels": ["MIN", "PTS", "REB", "AST"], "athletes": [
            {"athlete": {"id": "p1", "displayName": "Player One"}, "stats": ["21", "0", "1", "2"], "didNotPlay": False},
            {"athlete": {"id": "p2", "displayName": "Player Two"}, "stats": [], "didNotPlay": True},
        ]}]}]}, "pickcenter": [{"spread": 4.5, "overUnder": 212.5, "homeTeamOdds": {"favorite": False}, "awayTeamOdds": {"favorite": True}}]}))
    assert result["players"][0]["points"] == 0
    assert result["players"][1]["points"] is None
    assert result["players"][1]["minutes"] is None
    assert result["odds"][0]["homeLine"] == 4.5
    assert result["odds"][0]["quoteAt"] is None
    assert result["state"] == "post"


def test_unknown_favorite_cannot_invent_handicap_sign():
    p = parse_summary(raw({"header": {"id": "11"}, "boxscore": {}, "pickcenter": [{"spread": 3.5}]}))
    assert p["odds"][0]["homeLine"] is None


def test_standings_use_source_rank_not_wins_or_name():
    p = parse_standings(raw({"children": [{"id": "e", "standings": {"entries": [
        {"team": {"id": "a", "displayName": "Alphabetical first"}, "stats": [{"name": "playoffSeed", "value": 2}, {"name": "wins", "value": 8}]},
        {"team": {"id": "z", "displayName": "Last name"}, "stats": [{"name": "playoffSeed", "value": 1}, {"name": "wins", "value": 8}]},
    ]}}]}))
    assert [r["id"] for r in p["groups"][0]["rows"]] == ["z", "a"]
    assert p["groups"][0]["rows"][0]["losses"] is None


def test_tennis_keeps_unplayed_sets_unknown_and_round_identity():
    p = parse_tennis(raw({"events": [{"id": "event", "groupings": [{"grouping": {"slug": "mens-singles"}, "competitions": [
        {"id": "final", "round": {"id": "7", "displayName": "Final"}, "competitors": [{"id": "a", "athlete": {"displayName": "Player"}}]}
    ]}]}]}))
    match = p["tournaments"][0]["matches"][0]
    assert match["round"] == "Final"
    assert match["players"][0]["sets"] == []
    assert match["players"][0]["winner"] is None


def test_dota_recent_results_are_not_complete_bracket_or_map_numbers():
    p = parse_pro_matches(raw([
        {"match_id": 9, "radiant_name": "Alpha", "dire_name": "Beta", "series_id": 7, "radiant_score": 0, "dire_score": 3, "radiant_win": False},
        {"match_id": 10, "radiant_name": None, "dire_name": "Beta"},
    ]))
    assert len(p["matches"]) == 1
    assert p["matches"][0]["radiantScore"] == 0
    assert p["matches"][0]["radiantWin"] is False
    assert "bracket" not in p and "mapNumber" not in p["matches"][0]


def test_dota_resource_gaps_are_not_zeroes():
    p = parse_dota_match(raw({"match_id": 1, "players": [{"player_slot": 128, "kills": 0}], "radiant_gold_adv": [0, None, -30]}))
    assert p["goldAdvantage"] == [0, None, -30]
    assert p["xpAdvantage"] == []
    assert p["players"][0]["kills"] == 0
    assert p["players"][0]["netWorth"] is None
    assert p["players"][0]["radiant"] is False


@pytest.mark.parametrize("parser", [parse_standings, parse_leaders, parse_summary, parse_tennis, parse_dota_match])
def test_structurally_invalid_response_is_not_a_successful_empty(parser):
    with pytest.raises(ValueError):
        parser(b"{}")


def test_read_projection_preserves_source_clock_and_never_acquires(tmp_path, monkeypatch):
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    success = time.time() - 120
    store.set(NAMESPACE, LEADERS.key, {"lastSuccessAt": success, "data": {"season": "2026-27", "categories": []}}, 3600)
    monkeypatch.setenv(LEADERS.url_env, "https://source.invalid/leaders")
    monkeypatch.setattr("api.services.sports_expansion.snapshot_service.fetch_bytes", lambda *a, **kw: pytest.fail("GET must not acquire"))
    first = get_snapshot(store, "sports-awards-watch")
    second = get_snapshot(store, "sports-awards-watch")
    assert first["generatedAt"] == second["generatedAt"]
    assert first["categories"] == [] and first["eligibility"] is None and first["voting"] is None


def test_failed_refresh_retains_game_identity_and_original_success(tmp_path, monkeypatch):
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    monkeypatch.setenv("POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH", str(tmp_path / "evidence.sqlite3"))
    monkeypatch.setenv(SUMMARY.url_env, "https://source.invalid/summary?event={event_id}")
    collect_one(store, SUMMARY, acquire=lambda: (b"game-one", {"eventId": "1"}), force=True, now=time.time() - 60)
    before = store.get_stale(NAMESPACE, SUMMARY.key)
    def fail():
        raise TimeoutError("upstream")
    collect_one(store, SUMMARY, acquire=fail, force=True)
    after = store.get_stale(NAMESPACE, SUMMARY.key)
    assert after["data"]["eventId"] == "1"
    assert after["lastSuccessAt"] == before["lastSuccessAt"]
    assert after["error"] == "TimeoutError"


def test_expired_game_not_shown_as_current(tmp_path, monkeypatch):
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    monkeypatch.setenv(SUMMARY.url_env, "https://source.invalid/summary")
    store.set(NAMESPACE, SUMMARY.key, {"lastSuccessAt": time.time() - 86401, "data": {"eventId": "old"}}, 999999)
    p = get_snapshot(store, "sports-total-monitor")
    assert p["game"] is None and p["status"] == "unavailable"


def test_all_eight_panels_have_read_only_unavailable_contract(tmp_path):
    store = SnapshotStore(str(tmp_path / "snapshots.sqlite3"))
    for panel_id in PANEL_IDS:
        p = get_snapshot(store, panel_id)
        assert p["panelId"] == panel_id and p["schemaVersion"] == 1
        assert p["generatedAt"] is None and p["status"] == "unavailable"
