from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import requests

from devtools.probe_esports_odds import (
    NAMESPACE, american_decimal, assess_candidate, match_fixture,
    normalize_quotes, read_sample, scheduled_from_rules,
)


def fixture():
    return {
        "id": "opaque-fixture", "sport_key": "lol", "away_team": "Alpha",
        "home_team": "Beta", "commence_time": "2026-11-14T19:00:00Z",
        "bookmakers": [{"key": "pinnacle", "markets": [{"key": "h2h", "outcomes": [
            {"name": "Beta", "price": -200}, {"name": "Alpha", "price": 150},
        ]}]}],
    }


def market():
    return {
        "gammaMarketId": "1", "conditionId": "0x" + "a" * 64,
        "slug": "fixture", "title": "LoL: Alpha vs Beta (BO5) - Fixture Cup",
        "status": "Active", "description": "Initially scheduled for November 14, 2026 at 2:00 PM ET.",
        "endDate": "2026-11-15T01:00:00Z",
    }


def test_same_event_preserves_direction_and_never_certifies_settlement():
    result = match_fixture(fixture(), [market()])
    assert result["matchStatus"] == "same_event_candidate"
    assert result["settlementCompatibility"] == "unverified"
    assert not result["comparisonReady"]
    outcomes = result["quotes"][0]["outcomes"]
    assert [x["name"] for x in outcomes] == ["Beta", "Alpha"]
    assert outcomes[0]["proportionalNoVig"] == pytest.approx(.625)
    assert sum(x["proportionalNoVig"] for x in outcomes) == pytest.approx(1)


@pytest.mark.parametrize("value", [0, 1.9, 99, -99, float("nan"), float("inf"), True])
def test_reject_decimal_in_american_field_and_invalid_numbers(value):
    with pytest.raises(ValueError):
        american_decimal(value)


@pytest.mark.parametrize("title,reason", [
    ("LoL: Alpha vs Beta - Game 1 Winner", "not_full_series_winner"),
    ("Game Handicap: Alpha (-1.5) vs Beta (+1.5)", "not_full_series_winner"),
    ("Valorant: Alpha vs Beta (BO5) - Fixture Cup", "different_game"),
    ("LoL: Alpha Academy vs Beta (BO5) - Fixture Cup", "team_identity_unverified"),
])
def test_reject_similar_but_different_markets(title, reason):
    row = market()
    row["title"] = title
    assert assess_candidate(fixture(), row) == reason


def test_no_end_date_fallback_and_day_mismatch():
    row = market()
    row["description"] = ""
    row["endDate"] = fixture()["commence_time"]
    assert assess_candidate(fixture(), row) == "kickoff_unknown"
    row["description"] = "scheduled for November 15, 2026 at 2:00 PM ET."
    assert assess_candidate(fixture(), row) == "different_kickoff"
    assert scheduled_from_rules("scheduled for July 14, 2026 at 2:00 PM ET.") == datetime(2026, 7, 14, 18, tzinfo=timezone.utc)


def test_ambiguous_matches_do_not_choose_first():
    other = {**market(), "gammaMarketId": "2", "conditionId": "0x" + "b" * 64}
    result = match_fixture(fixture(), [market(), other])
    assert result["matchStatus"] == "ambiguous"
    assert "polymarket" not in result


def test_exclude_prediction_markets_map_prices_and_one_sided_quotes():
    event = fixture()
    book = event["bookmakers"][0]
    event["bookmakers"].append({**deepcopy(book), "key": "polymarket"})
    book["markets"][0]["period"] = "map1"
    assert normalize_quotes(event)[0] == []
    del book["markets"][0]["period"]
    book["markets"][0]["outcomes"].pop()
    quotes, rejected = normalize_quotes(event)
    assert not quotes
    assert len(rejected) == 1


class MemoryStore:
    def __init__(self):
        self.rows = {}

    def set(self, namespace, key, value, ttl, **kwargs):
        self.rows[namespace, key] = value
        return True

    def get_stale(self, namespace, key, **kwargs):
        return self.rows.get((namespace, key))

    def fetch_lock(self, *args, **kwargs):
        return nullcontext()


def test_failed_request_keeps_original_success_and_replay_spends_nothing(monkeypatch):
    monkeypatch.setenv("POLYDATA_ODDSLINK_TRY_URL", "https://source.invalid/guest")
    store = MemoryStore()
    old = {"status": "ok", "fetchedAt": "2026-11-09T01:00:00Z", "data": [fixture()]}
    store.rows[NAMESPACE, "response:oddslink:lol"] = old
    with patch("devtools.probe_esports_odds.read_with_retry", side_effect=requests.Timeout) as request:
        result = read_sample(None, store, "oddslink", "lol", live=True, deadline=0)
        assert result["status"] == "failed"
        assert request.call_args.kwargs["attempts"] == 1
        replay = read_sample(None, store, "oddslink", "lol", live=False, deadline=0)
        assert replay == old
        assert request.call_count == 1


def test_successful_empty_is_not_request_failure(monkeypatch):
    monkeypatch.setenv("POLYDATA_ODDSLINK_TRY_URL", "https://source.invalid/guest")
    store = MemoryStore()
    response = requests.Response()
    response.status_code = 200
    response._content = b"[]"
    response._content_consumed = True
    with patch("devtools.probe_esports_odds.read_with_retry", side_effect=lambda session, url, read, **kw: read(response)):
        result = read_sample(None, store, "oddslink", "valorant", live=True, deadline=float("inf"))
    assert result["status"] == "ok"
    assert result["data"] == []
    assert store.rows[NAMESPACE, "response:oddslink:valorant"] == result


def test_guest_budget_survives_new_sessions(monkeypatch):
    monkeypatch.setenv("POLYDATA_ODDSLINK_TRY_URL", "https://source.invalid/guest")
    store = MemoryStore()
    with patch("devtools.probe_esports_odds.read_with_retry", side_effect=requests.Timeout) as request:
        for _ in range(5):
            read_sample(None, store, "oddslink", "lol", live=True, deadline=0)
        result = read_sample(None, store, "oddslink", "valorant", live=True, deadline=0)
    assert result["status"] == "daily_budget_exhausted"
    assert request.call_count == 5
