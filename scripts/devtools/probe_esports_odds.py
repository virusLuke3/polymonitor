"""Bounded anonymous odds assessment against the existing local Market reader.

Run with PYTHONPATH=scripts. Default replays the last research responses;
--live spends at most two OddsLink guest calls, plus two KashRock demo reads.
This is not a collector, production Panel payload, or trading signal.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import re
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from api.clients.source_transport import SourceSession, read_response_bytes, read_with_retry
from data_sources import source_value
from runtime.environment import load_environment
from runtime.snapshot_store import SnapshotStore

NAMESPACE = "research:esports:anonymous-odds:v1"
TARGET_BOOKS = {"bet365", "pinnacle", "stake", "ggbet", "thunderpick"}
GAMES = {"lol": "LoL", "valorant": "Valorant"}
RETAIN_SECONDS = 86400  # Research replay only, never a freshness promise.


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def parse_time(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (TypeError, ValueError):
        return None


def name_key(value):
    # Deliberately keep Team/Gaming/Academy: removing them creates false matches.
    return re.sub(r"[^\w]", "", str(value).casefold())


def american_decimal(value):
    if isinstance(value, bool):
        raise ValueError("invalid American odds")
    number = float(value)
    if not math.isfinite(number) or abs(number) < 100 or not number.is_integer():
        raise ValueError("invalid American odds")
    return 1 + (number / 100 if number > 0 else 100 / abs(number))


def normalize_quotes(fixture):
    """Keep only complete two-sided full-series prices at requested sportsbooks."""
    teams = {name_key(fixture.get("home_team")), name_key(fixture.get("away_team"))}
    quotes, rejected = [], []
    for book in fixture.get("bookmakers", []):
        if book.get("key") not in TARGET_BOOKS:
            continue
        for market in book.get("markets", []):
            if market.get("key") != "h2h" or market.get("period") not in (None, "full"):
                continue
            try:
                outcomes = market["outcomes"]
                if len(outcomes) != 2 or len(teams) != 2 or "" in teams:
                    raise ValueError("incomplete two-sided market")
                if {name_key(o["name"]) for o in outcomes} != teams:
                    raise ValueError("outcome identity mismatch")
                decimal = [american_decimal(o["price"]) for o in outcomes]
                implied = [1 / price for price in decimal]
                quotes.append({
                    "bookmaker": book["key"], "provider": "oddslink",
                    "market": "h2h", "period": "full_series",
                    "sourceUpdatedAt": market.get("last_update") or book.get("last_update"),
                    "overround": sum(implied) - 1,
                    "outcomes": [{"name": o["name"], "americanOdds": o["price"],
                                  "decimalOdds": decimal[i],
                                  "proportionalNoVig": implied[i] / sum(implied)}
                                 for i, o in enumerate(outcomes)],
                    "settlementCompatibility": "unverified",
                })
            except (KeyError, TypeError, ValueError, OverflowError) as exc:
                rejected.append({"bookmaker": book.get("key"), "reason": type(exc).__name__})
    return quotes, rejected


def scheduled_from_rules(description):
    # endDate is settlement/close time, never a fallback for match kickoff.
    match = re.search(r"scheduled for ([A-Za-z]+ \d{1,2}, \d{4} at \d{1,2}:\d{2} [AP]M) ET\b",
                      description or "")
    if not match:
        return None
    try:
        local = datetime.strptime(match[1], "%B %d, %Y at %I:%M %p")
        return local.replace(tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc)
    except ValueError:
        return None


def assess_candidate(fixture, market):
    title = market.get("title") or ""
    parsed = re.fullmatch(r"(LoL|Valorant): (.+?) vs (.+?) \(BO([13579])\) - (.+)", title)
    if not parsed:
        return "not_full_series_winner"
    if parsed[1] != GAMES.get(fixture.get("sport_key")):
        return "different_game"
    if market.get("status") != "Active" or market.get("isTradingClosed") or market.get("isFinal"):
        return "inactive_market"
    start = scheduled_from_rules(market.get("description"))
    source_start = parse_time(fixture.get("commence_time"))
    if not start or not source_start:
        return "kickoff_unknown"
    if abs((start - source_start).total_seconds()) > 300:
        return "different_kickoff"
    actual = {name_key(parsed[2]), name_key(parsed[3])}
    expected = {name_key(fixture.get("home_team")), name_key(fixture.get("away_team"))}
    if len(expected) != 2 or "" in expected or actual != expected:
        return "team_identity_unverified"
    if not re.fullmatch(r"0x[0-9a-fA-F]{64}", market.get("conditionId") or ""):
        return "condition_identity_unknown"
    return "same_event_candidate"


def match_fixture(fixture, candidates):
    decisions = [{"marketId": row.get("gammaMarketId"), "slug": row.get("slug"),
                  "reason": assess_candidate(fixture, row)} for row in candidates]
    accepted = [row for row, decision in zip(candidates, decisions)
                if decision["reason"] == "same_event_candidate"]
    # Search pagination is intentionally bounded. A full page cannot establish uniqueness.
    ambiguous = len(accepted) > 1
    result = {"fixtureId": fixture["id"], "teams": [fixture["away_team"], fixture["home_team"]],
              "game": fixture["sport_key"], "scheduledAt": fixture["commence_time"],
              "tournament": fixture.get("tournament"), "candidateCount": len(candidates),
              "decisions": decisions, "matchStatus": "ambiguous" if ambiguous else
              "same_event_candidate" if accepted else "unmatched",
              "settlementCompatibility": "unverified", "comparisonReady": False,
              "unverifiedDimensions": ["bookmaker_settlement_rules", "bookmaker_best_of", "competition_alias"]}
    if len(accepted) == 1:
        row = accepted[0]
        result["polymarket"] = {k: row.get(k) for k in
                                ("gammaMarketId", "conditionId", "yesTokenId", "noTokenId", "slug", "title")}
        quote = row.get("_catalogQuote") or {}
        tokens = [row.get("yesTokenId"), row.get("noTokenId")]
        if (quote.get("conditionId") == row.get("conditionId") and quote.get("tokenIds") == tokens
                and len(quote.get("labels", [])) == 2
                and {name_key(x) for x in quote["labels"]} ==
                {name_key(fixture["away_team"]), name_key(fixture["home_team"])}):
            result["polymarket"]["catalogQuote"] = quote
            result["polymarket"]["sourceUpdatedAt"] = row.get("quoteUpdatedAt")
            result["polymarket"]["observedAt"] = row.get("observedAt")
            result["polymarket"]["priceKind"] = "indicative_catalog_not_executable"
    result["quotes"], result["rejectedQuotes"] = normalize_quotes(fixture)
    return result


def read_sample(session, store, source, game, *, live, deadline):
    key = f"response:{source}:{game}"
    if not live:
        return store.get_stale(NAMESPACE, key, max_age_seconds=RETAIN_SECONDS) or {
            "status": "not_sampled", "data": None}
    config = {"oddslink": "POLYDATA_ODDSLINK_TRY_URL", "kashrock": "POLYDATA_KASHROCK_DEMO_PROPS_URL"}
    url = source_value(config[source])
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return {"status": "unconfigured", "data": None}
    if source == "oddslink":
        # Persist a conservative local cap across CLI sessions, even if guest
        # cookies or upstream quota headers reset. Reserve before the request.
        quota_key = "quota:oddslink:" + datetime.now(timezone.utc).date().isoformat()
        with store.fetch_lock(NAMESPACE, "guest-budget", timeout=1):
            used = (store.get_stale(NAMESPACE, quota_key) or {}).get("attempts", 0)
            if used >= 5:
                return {"status": "daily_budget_exhausted", "data": None}
            if not store.set(NAMESPACE, quota_key, {"attempts": used + 1}, RETAIN_SECONDS, max_entries=16):
                return {"status": "budget_write_failed", "data": None}
    params = {"path": f"/v1/sports/{game}/odds?markets=h2h&oddsFormat=american"} if source == "oddslink" else {"sport": game}
    attempted = utc_now()

    def read(response):
        body = read_response_bytes(response, 2_000_000, deadline=deadline)
        payload = json.loads(body)
        if source == "oddslink":
            valid = (isinstance(payload, list) and len(payload) <= 200 and
                     all(isinstance(x, dict) and x.get("sport_key") == game and
                         all(isinstance(x.get(k), str) and x[k] for k in
                             ("id", "home_team", "away_team", "commence_time")) and
                         isinstance(x.get("bookmakers"), list) for x in payload))
        else:
            valid = (isinstance(payload, dict) and payload.get("sport") == game and
                     isinstance(payload.get("props"), list) and len(payload["props"]) <= 1)
        if not valid:
            raise ValueError("source shape or identity mismatch")
        return {"status": "ok", "fetchedAt": utc_now(), "data": payload,
                "guestRemaining": response.headers.get("x-tryit-remaining"),
                "guestResetAt": response.headers.get("x-tryit-reset")}

    try:
        # One request only: do not spend guest quota on retries or exit rotation.
        receipt = read_with_retry(session, url, read, attempts=1, deadline=deadline,
                                  timeout=45, params=params, stream=True, allow_redirects=False)
        if not store.set(NAMESPACE, key, receipt, RETAIN_SECONDS, max_entries=16):
            raise RuntimeError("snapshot write failed")
        return receipt
    except Exception as exc:
        # No raw exception/URL/proxy text in receipts. Keep prior successful sample intact.
        response = getattr(exc, "response", None)
        receipt = {"status": "failed", "attemptedAt": attempted, "errorType": type(exc).__name__,
                   "httpStatus": response.status_code if response is not None else None, "data": None}
        store.set(NAMESPACE, f"attempt:{source}:{game}", receipt, RETAIN_SECONDS, max_entries=16)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make four bounded anonymous source reads")
    args = parser.parse_args()
    load_environment()
    from api.config import load_api_settings
    from runtime.market_search import build_market_search
    settings = load_api_settings()
    store = SnapshotStore(settings.snapshot_sqlite_path)
    search = build_market_search(settings)
    deadline = time.monotonic() + 180
    report = {"schemaVersion": 1, "assessmentAt": utc_now(), "mode": "live" if args.live else "replay",
              "productionConnected": False, "sources": {}, "matches": [], "errors": []}
    with SourceSession() as session:
        session.trust_env = False
        for source in ("oddslink", "kashrock"):
            for game in GAMES:
                receipt = read_sample(session, store, source, game, live=args.live, deadline=deadline)
                report["sources"][f"{source}:{game}"] = receipt
        for fixture in (report["sources"]["oddslink:lol"].get("data") or [])[:5] + (report["sources"]["oddslink:valorant"].get("data") or [])[:5]:
            if time.monotonic() >= deadline:
                report["errors"].append("assessment_deadline")
                break
            candidates = []
            try:
                for team in (fixture["away_team"], fixture["home_team"]):
                    candidates = search(team, 50)["items"]
                    if candidates:
                        break
                result = match_fixture(fixture, candidates)
                if len(candidates) >= 50:
                    result["matchStatus"] = "search_truncated"
                report["matches"].append(result)
            except Exception as exc:
                report["errors"].append({"fixtureId": fixture["id"], "errorType": type(exc).__name__})
    report["counts"] = {
        "sampledFixtures": len(report["matches"]),
        "sameEventCandidates": sum(x["matchStatus"] == "same_event_candidate" for x in report["matches"]),
        "targetBookPairs": sum(len(x["quotes"]) for x in report["matches"]),
        "settlementVerified": 0,
    }
    if not store.set(NAMESPACE, "assessment:latest", report, RETAIN_SECONDS, max_entries=16):
        raise RuntimeError("assessment persistence failed")
    # Full raw source samples remain in the shared research namespace, not tmp files.
    public = {**report, "sources": {k: {**{a: b for a, b in v.items() if a != "data"},
               "records": len(v["data"]) if isinstance(v.get("data"), list) else
               len(v["data"].get("props", [])) if isinstance(v.get("data"), dict) else None}
               for k, v in report["sources"].items()}}
    print(json.dumps(public, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
