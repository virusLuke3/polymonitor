from __future__ import annotations

import json
import math
from datetime import datetime, timezone


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def link(links):
    return next((r["href"] for r in links or [] if isinstance(r, dict)
                 and str(r.get("href", "")).startswith("https://")), None)


def parse_standings(raw):
    p = json.loads(raw)
    if not isinstance(p.get("children"), list):
        raise ValueError("Missing standings groups")
    groups = []
    for group in p["children"][:6]:
        standings = group.get("standings", {})
        rows = []
        for row in standings.get("entries", [])[:40]:
            team = row.get("team", {})
            stats = {s.get("name"): s for s in row.get("stats", [])}
            if not team.get("id"):
                continue
            stat = lambda name: number(stats.get(name, {}).get("value"))
            rows.append({"id": str(team["id"]), "name": team.get("displayName"),
                "short": team.get("abbreviation"), "wins": stat("wins"), "losses": stat("losses"),
                "winPercent": stat("winPercent"), "gamesBehind": stat("gamesBehind"),
                "rank": stat("playoffSeed"), "differential": stat("differential"),
                "streak": stats.get("streak", {}).get("displayValue"), "url": link(team.get("links"))})
        # Order by the provider's actual seed, never invent an alphabetical tiebreak.
        rows.sort(key=lambda r: r["rank"] if r["rank"] is not None else 999)
        groups.append({"id": str(group.get("id", "")), "name": group.get("name"),
            "season": standings.get("seasonDisplayName"), "rows": rows})
    return {"groups": groups}


def parse_leaders(raw):
    p = json.loads(raw)
    categories = p.get("leaders", {}).get("categories")
    if not isinstance(categories, list):
        raise ValueError("Missing leader categories")
    result = []
    for c in categories[:30]:
        rows = []
        for rank, item in enumerate(c.get("leaders", [])[:20], 1):
            athlete = item.get("athlete", {})
            if not athlete.get("id"):
                continue
            team = item.get("team", {})
            rows.append({"id": str(athlete["id"]), "name": athlete.get("displayName"),
                "jersey": athlete.get("jersey"), "team": team.get("abbreviation"),
                "rank": rank, "value": number(item.get("value")), "displayValue": item.get("displayValue"),
                "url": link(athlete.get("links"))})
        result.append({"id": c.get("name"), "name": c.get("displayName"),
            "abbreviation": c.get("abbreviation"), "rows": rows})
    return {"season": p.get("requestedSeason", {}).get("displayName"), "categories": result}


def parse_summary(raw):
    p = json.loads(raw)
    header = p.get("header", {})
    if not header.get("id") or not isinstance(p.get("boxscore"), dict):
        raise ValueError("Missing identified game summary")
    competition = next(iter(header.get("competitions", [])), {})
    teams = []
    for t in competition.get("competitors", [])[:2]:
        teams.append({"id": str(t.get("id", "")), "name": t.get("team", {}).get("displayName"),
            "short": t.get("team", {}).get("abbreviation"), "side": t.get("homeAway"),
            "score": number(t.get("score")), "periods": [number(s.get("displayValue", s.get("value"))) for s in t.get("linescores", [])[:12]]})
    players = []
    for t in p["boxscore"].get("players", [])[:2]:
        for group in t.get("statistics", [])[:3]:
            labels = group.get("labels", group.get("names", []))
            for a in group.get("athletes", [])[:30]:
                athlete = a.get("athlete", {})
                stats = dict(zip(labels, a.get("stats", [])))
                dnp = a.get("didNotPlay") is True
                players.append({"id": str(athlete.get("id", "")), "name": athlete.get("displayName"),
                    "jersey": athlete.get("jersey"), "team": t.get("team", {}).get("abbreviation"),
                    "starter": a.get("starter"), "didNotPlay": dnp, "minutes": None if dnp else stats.get("MIN"),
                    "points": None if dnp else number(stats.get("PTS")),
                    "rebounds": None if dnp else number(stats.get("REB")),
                    "assists": None if dnp else number(stats.get("AST")), "url": link(athlete.get("links"))})
    odds = []
    for o in p.get("pickcenter", [])[:5]:
        home = o.get("homeTeamOdds", {})
        away = o.get("awayTeamOdds", {})
        # ESPN spread is magnitude, favorite side supplies its sign.
        magnitude = number(o.get("spread"))
        home_line = None if magnitude is None or home.get("favorite") is None else -abs(magnitude) if home["favorite"] else abs(magnitude)
        odds.append({"provider": o.get("provider", {}).get("name"), "details": o.get("details"),
            "homeLine": home_line, "totalLine": number(o.get("overUnder")),
            "homePrice": number(home.get("spreadOdds")), "awayPrice": number(away.get("spreadOdds")),
            "overPrice": number(o.get("overOdds")), "underPrice": number(o.get("underOdds")),
            "quoteAt": o.get("lastModified") or o.get("lastUpdated"), "publishedAt": None})
    name = header.get("shortName") or header.get("name") or " vs ".join(t["name"] or t["short"] or t["id"] for t in teams)
    return {"eventId": str(header["id"]), "name": name,
        "eventTime": competition.get("date"), "state": competition.get("status", {}).get("type", {}).get("state"),
        "statusText": competition.get("status", {}).get("type", {}).get("shortDetail"),
        "teams": teams, "players": players, "odds": odds, "url": link(header.get("links"))}


def parse_tennis(raw):
    p = json.loads(raw)
    if not isinstance(p.get("events"), list):
        raise ValueError("Missing tournament events")
    tournaments = []
    for event in p["events"][:4]:
        rows = []
        for g in event.get("groupings", []):
            if g.get("grouping", {}).get("slug") != "mens-singles":
                continue
            for c in g.get("competitions", [])[:200]:
                players = [{"id": str(a.get("id", "")), "name": a.get("athlete", {}).get("displayName"),
                    "winner": a.get("winner"), "seed": a.get("tournamentSeed"),
                    "sets": [number(s.get("value")) for s in a.get("linescores", [])[:5]]}
                    for a in c.get("competitors", [])[:2]]
                rows.append({"id": str(c.get("id", "")), "date": c.get("date"),
                    "round": c.get("round", {}).get("displayName"), "roundId": c.get("round", {}).get("id"),
                    "state": c.get("status", {}).get("type", {}).get("state"), "players": players})
        tournaments.append({"id": str(event.get("id", "")), "name": event.get("name"),
            "date": event.get("date"), "endDate": event.get("endDate"), "matches": rows,
            "url": link(event.get("links"))})
    return {"tournaments": tournaments}


def parse_pro_matches(raw):
    p = json.loads(raw)
    if not isinstance(p, list):
        raise ValueError("Missing professional match list")
    rows = []
    for m in p[:100]:
        if not m.get("match_id") or not m.get("radiant_name") or not m.get("dire_name"):
            continue
        start = number(m.get("start_time"))
        rows.append({"id": str(m["match_id"]), "leagueId": str(m.get("leagueid", "")), "league": m.get("league_name"),
            "seriesId": str(m.get("series_id") or ""), "seriesType": m.get("series_type"),
            "radiant": m["radiant_name"], "dire": m["dire_name"], "radiantId": m.get("radiant_team_id"),
            "direId": m.get("dire_team_id"), "radiantScore": number(m.get("radiant_score")),
            "direScore": number(m.get("dire_score")), "radiantWin": m.get("radiant_win"),
            "duration": number(m.get("duration")),
            "eventTime": datetime.fromtimestamp(start, timezone.utc).isoformat() if start else None})
    return {"matches": rows, "sampleSize": len(p), "coverage": "Latest 100 professional match records; named teams only"}


def parse_dota_match(raw):
    p = json.loads(raw)
    if not p.get("match_id") or not isinstance(p.get("players"), list):
        raise ValueError("Missing identified Dota match")
    start = number(p.get("start_time"))
    return {"id": str(p["match_id"]), "league": p.get("league", {}).get("name"),
        "radiant": p.get("radiant_team", {}).get("name"), "dire": p.get("dire_team", {}).get("name"),
        "radiantScore": number(p.get("radiant_score")), "direScore": number(p.get("dire_score")),
        "radiantWin": p.get("radiant_win"), "duration": number(p.get("duration")),
        "eventTime": datetime.fromtimestamp(start, timezone.utc).isoformat() if start else None,
        "patchId": p.get("patch"), "goldAdvantage": [number(n) for n in (p.get("radiant_gold_adv") or [])[:180]],
        "xpAdvantage": [number(n) for n in (p.get("radiant_xp_adv") or [])[:180]],
        "picksBans": [{"heroId": v.get("hero_id"), "team": v.get("team"), "pick": v.get("is_pick"), "order": v.get("order")}
            for v in (p.get("picks_bans") or [])[:40]],
        "players": [{"id": v.get("account_id"), "name": v.get("name") or v.get("personaname"),
            "radiant": int(v.get("player_slot", 128)) < 128, "heroId": v.get("hero_id"),
            "kills": number(v.get("kills")), "deaths": number(v.get("deaths")), "assists": number(v.get("assists")),
            "netWorth": number(v.get("net_worth")), "goldPerMinute": number(v.get("gold_per_min"))}
            for v in p["players"][:10]]}
