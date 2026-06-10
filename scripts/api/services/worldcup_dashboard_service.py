from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

from api.services import worldcup_intel_service


WORLDCUP_DASHBOARD_NAMESPACE = "snapshot:sports:worldcup-dashboard"
WORLDCUP_DASHBOARD_CACHE_KEY = "dashboard-v1"
DEFAULT_TTL_SECONDS = 900
OPENFOOTBALL_2026_URL = "https://raw.githubusercontent.com/openfootball/worldcup.json/master/2026/worldcup.json"
POLYMARKET_GAMMA_API_BASE = "https://gamma-api.polymarket.com"
WORLDCUP_ODDS_SPORT_KEY = "soccer_fifa_world_cup"
WORLDCUP_ODDS_REGIONS = "us,uk,eu,au"
MS_PER_MINUTE = 60 * 1000

_REFRESH_LOCK = threading.Lock()
_REFRESHING: set[str] = set()

WORLD_CUP_CITIES: List[Dict[str, Any]] = [
    {"id": "atlanta", "city": "Atlanta", "country": "US", "countryName": "United States", "venue": "Mercedes-Benz Stadium", "latitude": 33.7554, "longitude": -84.4008, "timezone": "America/New_York", "capacity": 71000},
    {"id": "boston", "city": "Boston / Foxborough", "country": "US", "countryName": "United States", "venue": "Gillette Stadium", "latitude": 42.0909, "longitude": -71.2643, "timezone": "America/New_York", "capacity": 65878},
    {"id": "dallas", "city": "Dallas / Arlington", "country": "US", "countryName": "United States", "venue": "AT&T Stadium", "latitude": 32.7473, "longitude": -97.0945, "timezone": "America/Chicago", "capacity": 80000},
    {"id": "houston", "city": "Houston", "country": "US", "countryName": "United States", "venue": "NRG Stadium", "latitude": 29.6847, "longitude": -95.4107, "timezone": "America/Chicago", "capacity": 72220},
    {"id": "kansas-city", "city": "Kansas City", "country": "US", "countryName": "United States", "venue": "Arrowhead Stadium", "latitude": 39.0489, "longitude": -94.4839, "timezone": "America/Chicago", "capacity": 76416},
    {"id": "los-angeles", "city": "Los Angeles / Inglewood", "country": "US", "countryName": "United States", "venue": "SoFi Stadium", "latitude": 33.9535, "longitude": -118.3392, "timezone": "America/Los_Angeles", "capacity": 70240},
    {"id": "miami", "city": "Miami Gardens", "country": "US", "countryName": "United States", "venue": "Hard Rock Stadium", "latitude": 25.958, "longitude": -80.2389, "timezone": "America/New_York", "capacity": 65326},
    {"id": "new-york-new-jersey", "city": "New York / New Jersey", "country": "US", "countryName": "United States", "venue": "MetLife Stadium", "latitude": 40.8135, "longitude": -74.0745, "timezone": "America/New_York", "capacity": 82500},
    {"id": "philadelphia", "city": "Philadelphia", "country": "US", "countryName": "United States", "venue": "Lincoln Financial Field", "latitude": 39.9008, "longitude": -75.1675, "timezone": "America/New_York", "capacity": 67594},
    {"id": "san-francisco", "city": "San Francisco Bay Area", "country": "US", "countryName": "United States", "venue": "Levi's Stadium", "latitude": 37.403, "longitude": -121.97, "timezone": "America/Los_Angeles", "capacity": 68500},
    {"id": "seattle", "city": "Seattle", "country": "US", "countryName": "United States", "venue": "Lumen Field", "latitude": 47.5952, "longitude": -122.3316, "timezone": "America/Los_Angeles", "capacity": 69000},
    {"id": "guadalajara", "city": "Guadalajara / Zapopan", "country": "MX", "countryName": "Mexico", "venue": "Estadio Akron", "latitude": 20.6818, "longitude": -103.4623, "timezone": "America/Mexico_City", "capacity": 49850},
    {"id": "mexico-city", "city": "Mexico City", "country": "MX", "countryName": "Mexico", "venue": "Estadio Azteca", "latitude": 19.3029, "longitude": -99.1505, "timezone": "America/Mexico_City", "capacity": 87523},
    {"id": "monterrey", "city": "Monterrey / Guadalupe", "country": "MX", "countryName": "Mexico", "venue": "Estadio BBVA", "latitude": 25.6683, "longitude": -100.2446, "timezone": "America/Monterrey", "capacity": 53500},
    {"id": "toronto", "city": "Toronto", "country": "CA", "countryName": "Canada", "venue": "BMO Field", "latitude": 43.6332, "longitude": -79.4186, "timezone": "America/Toronto", "capacity": 45000},
    {"id": "vancouver", "city": "Vancouver", "country": "CA", "countryName": "Canada", "venue": "BC Place", "latitude": 49.2767, "longitude": -123.1119, "timezone": "America/Vancouver", "capacity": 54500},
]

GROUND_TO_CITY_ID = {
    "Atlanta": "atlanta",
    "Boston (Foxborough)": "boston",
    "Dallas (Arlington)": "dallas",
    "Houston": "houston",
    "Kansas City": "kansas-city",
    "Los Angeles (Inglewood)": "los-angeles",
    "Miami (Miami Gardens)": "miami",
    "New York/New Jersey (East Rutherford)": "new-york-new-jersey",
    "Philadelphia": "philadelphia",
    "San Francisco Bay Area (Santa Clara)": "san-francisco",
    "Seattle": "seattle",
    "Guadalajara (Zapopan)": "guadalajara",
    "Mexico City": "mexico-city",
    "Monterrey (Guadalupe)": "monterrey",
    "Toronto": "toronto",
    "Vancouver": "vancouver",
}

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _headers() -> Dict[str, str]:
    return {"Accept": "application/json", "User-Agent": "polydata-worldcup-dashboard/1.0"}


def _city_by_id(city_id: str) -> Dict[str, Any]:
    return next((city for city in WORLD_CUP_CITIES if city["id"] == city_id), WORLD_CUP_CITIES[7])


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _mean(values: Iterable[float]) -> Optional[float]:
    rows = [value for value in values if value == value]
    return sum(rows) / len(rows) if rows else None


def _parse_kickoff(match: Dict[str, Any]) -> datetime:
    date_value = str(match.get("date") or "2026-06-11")
    time_value = str(match.get("time") or "00:00 UTC+0")
    parsed = re.match(r"^(\d{1,2}):(\d{2})\s+UTC([+-]\d{1,2})(?::?(\d{2}))?$", time_value)
    if not parsed:
        return datetime.fromisoformat(f"{date_value}T00:00:00+00:00")
    hour, minute, offset_hours, offset_minutes = parsed.groups()
    naive_utc = datetime(
        int(date_value[:4]),
        int(date_value[5:7]),
        int(date_value[8:10]),
        int(hour),
        int(minute),
        tzinfo=timezone.utc,
    )
    sign = -1 if str(offset_hours).startswith("-") else 1
    offset_total_minutes = sign * (abs(int(offset_hours)) * 60 + int(offset_minutes or 0))
    return datetime.fromtimestamp(naive_utc.timestamp() - offset_total_minutes * 60, tz=timezone.utc)


def _stage_from_round(round_name: str = "", group: str = "") -> str:
    text = f"{round_name} {group}".lower()
    if "final" in text and "third" in text:
        return "third_place"
    if "final" in text:
        return "final"
    if "semi" in text:
        return "semifinal"
    if "quarter" in text:
        return "quarterfinal"
    if "round of 16" in text:
        return "round16"
    if "round of 32" in text:
        return "round32"
    return "group"


def _format_in_timezone(value: datetime, timezone_name: str) -> str:
    try:
        return value.astimezone(ZoneInfo(timezone_name)).strftime("%a, %d %b, %H:%M")
    except Exception:
        return value.strftime("%a, %d %b, %H:%M")


def _normalize_team(team: Any) -> str:
    text = str(team or "").strip()
    if not text:
        return "TBD"
    winner = re.match(r"^W(\d+)$", text)
    if winner:
        return f"Winner M{winner.group(1)}"
    loser = re.match(r"^L(\d+)$", text)
    if loser:
        return f"Loser M{loser.group(1)}"
    group_rank = re.match(r"^([123])([A-L])$", text)
    if group_rank:
        return f"{group_rank.group(2)}{group_rank.group(1)}"
    third_place = re.match(r"^3([A-L](?:/[A-L])*)$", text)
    if third_place:
        return f"3rd {third_place.group(1)}"
    return text


def _fetch_schedule_source(ctx: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str]:
    getter = ctx.get("http_json_get")
    if callable(getter):
        try:
            payload = getter(OPENFOOTBALL_2026_URL, timeout=12, headers=_headers())
            matches = payload.get("matches") if isinstance(payload, dict) else None
            if isinstance(matches, list) and matches:
                return [row for row in matches if isinstance(row, dict)], "openfootball/worldcup.json"
        except Exception:
            pass
    return [], "source-required"


def _normalize_matches(source_matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    rows: List[Dict[str, Any]] = []
    for index, match in enumerate(source_matches):
        kickoff = _parse_kickoff(match)
        city_id = GROUND_TO_CITY_ID.get(str(match.get("ground") or ""), "new-york-new-jersey")
        city = _city_by_id(city_id)
        home_team = _normalize_team(match.get("team1"))
        away_team = _normalize_team(match.get("team2"))
        match_number = _safe_int(match.get("num") or match.get("match") or index + 1, index + 1)
        rows.append(
            {
                "id": f"wc2026-{match_number:03d}",
                "fifaMatchNumber": match_number,
                "stage": _stage_from_round(str(match.get("round") or ""), str(match.get("group") or "")),
                "group": str(match.get("group") or ""),
                "round": str(match.get("round") or "World Cup"),
                "kickoffUtc": kickoff.isoformat().replace("+00:00", "Z"),
                "kickoffBeijing": _format_in_timezone(kickoff, "Asia/Shanghai"),
                "kickoffLocal": _format_in_timezone(kickoff, str(city.get("timezone") or "UTC")),
                "cityId": city_id,
                "city": city["city"],
                "venue": city["venue"],
                "homeTeam": home_team,
                "awayTeam": away_team,
                "status": "finished" if kickoff < now else "scheduled",
                "marketLinked": False,
                "oddsLinked": False,
            }
        )
    return sorted(rows, key=lambda row: str(row.get("kickoffUtc") or ""))


def _tokenize(value: Any) -> List[str]:
    return [part for part in re.split(r"[^0-9a-z]+", str(value or "").lower()) if part]


def _team_tokens(value: Any) -> set[str]:
    text = str(value or "").lower().replace("&", " and ")
    aliases = {
        "usa": "united states america us",
        "us": "united states america usa",
        "south korea": "korea republic korea",
        "czechia": "czech republic czech",
        "bosnia herzegovina": "bosnia herzogovina",
        "bosnia and herzegovina": "bosnia herzegovina",
    }
    expanded = text
    for alias, extra in aliases.items():
        if alias in text:
            expanded += " " + extra
    return {token for token in _tokenize(expanded) if len(token) > 1}


def _market_text(row: Dict[str, Any]) -> str:
    values = [
        row.get("title"),
        row.get("question"),
        row.get("marketTitle"),
        row.get("eventTitle"),
        row.get("slug"),
        row.get("eventSlug"),
        row.get("description"),
        row.get("groupItemTitle"),
        " ".join(str(value or "") for value in _safe_list(row.get("outcomes"))),
    ]
    for child in _safe_list(row.get("outcomeMarkets")):
        if isinstance(child, dict):
            values.extend([child.get("title"), child.get("slug"), child.get("eventTitle"), child.get("eventSlug")])
    return " ".join(str(value or "") for value in values).lower()


def _market_primary_text(row: Dict[str, Any]) -> str:
    values = [
        row.get("title"),
        row.get("question"),
        row.get("marketTitle"),
        row.get("slug"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _safe_json_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _polymarket_url(row: Dict[str, Any]) -> str:
    for key in ("marketUrl", "eventUrl", "url"):
        value = str(row.get(key) or "").strip()
        if value.startswith("http"):
            return value
    event_slug = str(row.get("eventSlug") or "").strip()
    slug = str(row.get("slug") or row.get("eventSlug") or "").strip()
    if event_slug and slug and slug != event_slug:
        return f"https://polymarket.com/event/{event_slug}/{slug}"
    if slug:
        return f"https://polymarket.com/event/{slug}"
    title = str(row.get("title") or row.get("question") or "").strip()
    return f"https://polymarket.com/search?query={quote_plus(title)}" if title else ""


def _serving_market_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    outcomes = [item for item in _safe_json_list(row.get("outcomes")) if isinstance(item, dict)]
    top_outcomes = [item for item in _safe_json_list(row.get("top_outcomes")) if isinstance(item, dict)]
    priced = top_outcomes or outcomes
    labels: List[str] = []
    prices: List[Any] = []
    token_ids: List[Any] = []
    for outcome in priced:
        label = outcome.get("label") or outcome.get("title") or outcome.get("outcomeKey") or outcome.get("name")
        price = outcome.get("yesPrice")
        if label in (None, "") or price in (None, ""):
            continue
        labels.append(str(label))
        prices.append(price)
        token_ids.append(outcome.get("yesTokenId") or outcome.get("tokenId") or "")
    return {
        "title": row.get("title"),
        "question": row.get("title"),
        "marketTitle": row.get("title"),
        "eventTitle": row.get("event_title"),
        "eventSlug": row.get("event_slug"),
        "eventId": row.get("event_id"),
        "slug": row.get("event_slug"),
        "gammaMarketId": row.get("default_gamma_market_id"),
        "conditionId": row.get("default_condition_id"),
        "outcomes": labels,
        "outcomePrices": prices,
        "clobTokenIds": token_ids,
        "volume24hr": row.get("volume_24h"),
        "volume24h": row.get("volume_24h"),
        "active": not bool(row.get("is_trading_closed")),
        "closed": bool(row.get("is_trading_closed")),
        "source": "local-db",
    }


def _market_table_candidate(row: Dict[str, Any]) -> Dict[str, Any]:
    clob_token_ids = _safe_json_list(row.get("clob_token_ids"))
    yes_token_id = str(row.get("yes_token_id") or (clob_token_ids[0] if clob_token_ids else "") or "").strip()
    no_token_id = str(row.get("no_token_id") or (clob_token_ids[1] if len(clob_token_ids) > 1 else "") or "").strip()
    latest_yes = row.get("latest_yes_price")
    latest_price = row.get("latest_price")
    return {
        "id": row.get("id"),
        "localMarketId": row.get("id"),
        "title": row.get("title"),
        "question": row.get("title"),
        "marketTitle": row.get("title"),
        "eventTitle": row.get("event_title"),
        "eventSlug": row.get("event_slug"),
        "eventId": row.get("event_id"),
        "slug": row.get("slug"),
        "gammaMarketId": row.get("gamma_market_id"),
        "conditionId": row.get("condition_id"),
        "yes_token_id": yes_token_id,
        "no_token_id": no_token_id,
        "clobTokenIds": clob_token_ids or [token for token in (yes_token_id, no_token_id) if token],
        "latestPrice": latest_price,
        "latestYesPrice": latest_yes if latest_yes not in (None, "") else latest_price,
        "latestNoPrice": row.get("latest_no_price"),
        "outcomes": ["YES", "NO"],
        "outcomePrices": [latest_yes if latest_yes not in (None, "") else latest_price]
        if (latest_yes not in (None, "") or latest_price not in (None, ""))
        else [],
        "volume24hr": row.get("volume_24h"),
        "volume24h": row.get("volume_24h"),
        "active": not bool(row.get("is_trading_closed")),
        "closed": bool(row.get("is_trading_closed")),
        "source": "local-db-market",
    }


_WORLDCUP_MARKET_SLUG_RE = re.compile(r"^(fifwc-[a-z0-9]+-[a-z0-9]+-\d{4}-\d{2}-\d{2})-(.+)$")


def _worldcup_market_slug_base(slug: Any) -> str:
    match = _WORLDCUP_MARKET_SLUG_RE.match(str(slug or "").strip().lower())
    return match.group(1) if match else ""


def _moneyline_bundle_title(children: List[Dict[str, Any]], slug_base: str) -> str:
    for child in children:
        title = str(child.get("title") or "")
        draw_match = re.search(r"Will\s+(.+?)\s+vs\.?\s+(.+?)\s+end in a draw\?", title, flags=re.IGNORECASE)
        if draw_match:
            return f"{draw_match.group(1).strip()} vs. {draw_match.group(2).strip()} - Match Winner"
    return f"{slug_base} - Match Winner"


def _moneyline_bundle_candidate(slug_base: str, children: List[Dict[str, Any]]) -> Dict[str, Any]:
    children = sorted(children, key=lambda row: str(row.get("slug") or ""))
    return {
        "id": slug_base,
        "title": _moneyline_bundle_title(children, slug_base),
        "question": _moneyline_bundle_title(children, slug_base),
        "marketTitle": _moneyline_bundle_title(children, slug_base),
        "eventTitle": _moneyline_bundle_title(children, slug_base),
        "eventSlug": slug_base,
        "slug": slug_base,
        "outcomes": [],
        "outcomePrices": [],
        "outcomeMarkets": children,
        "volume24hr": sum(_safe_float(child.get("volume24h") or child.get("volume24hr")) or 0 for child in children),
        "volume24h": sum(_safe_float(child.get("volume24h") or child.get("volume24hr")) or 0 for child in children),
        "active": any(child.get("active") is not False for child in children),
        "closed": all(bool(child.get("closed")) for child in children),
        "source": "local-db-moneyline",
    }


def _candidate_event_payload(item: Dict[str, Any], event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if isinstance(event, dict) and event:
        return event
    events = item.get("events")
    if isinstance(events, list):
        for row in events:
            if isinstance(row, dict):
                return row
    return {}


def _market_is_inactive(row: Dict[str, Any]) -> bool:
    if row.get("active") is False:
        return True
    if row.get("closed") is True or row.get("archived") is True:
        return True
    return False


def _canonical_outcome_label(match: Dict[str, Any], label: Any, *, allow_yes_no: bool = False) -> str:
    text = str(label or "").strip()
    if not text:
        return ""
    lower = text.lower()
    home = str(match.get("homeTeam") or "").strip()
    away = str(match.get("awayTeam") or "").strip()
    if lower in {"draw", "tie", "x"} or "draw" in lower:
        return "Draw"
    if allow_yes_no and lower == "yes":
        return text
    if allow_yes_no and lower == "no":
        return text
    home_tokens = _team_tokens(home)
    away_tokens = _team_tokens(away)
    label_tokens = _team_tokens(text) | set(_tokenize(text))

    def _score(team_name: str, team_token_set: set[str]) -> int:
        team_lower = str(team_name or "").lower()
        if not team_lower:
            return 0
        if lower == team_lower:
            return 100
        score = len(team_token_set & label_tokens)
        if team_lower in lower or lower in team_lower:
            score += 4
        return score

    home_score = _score(home, home_tokens)
    away_score = _score(away, away_tokens)
    if home_score > away_score and home_score > 0:
        return home
    if away_score > home_score and away_score > 0:
        return away
    return text


def _match_outcome_hint(match: Dict[str, Any], row: Dict[str, Any]) -> str:
    candidates = [
        row.get("groupItemTitle"),
        row.get("outcome"),
        row.get("name"),
        row.get("title"),
        row.get("question"),
        row.get("marketTitle"),
    ]
    for value in candidates:
        label = _canonical_outcome_label(match, value)
        if label in {str(match.get("homeTeam") or ""), str(match.get("awayTeam") or ""), "Draw"}:
            return label
    return ""


def _candidate_outcome_text(row: Dict[str, Any]) -> str:
    values: List[Any] = [
        row.get("groupItemTitle"),
        row.get("outcome"),
        row.get("name"),
    ]
    values.extend(_safe_list(row.get("outcomes")))
    return " ".join(str(value or "") for value in values).lower()


def _worldcup_market_reject_reason(match: Dict[str, Any], row: Dict[str, Any]) -> str:
    if _market_is_inactive(row):
        return "inactive"
    text = _market_text(row)
    primary_text = _market_primary_text(row)
    event_match_text = " ".join(
        str(row.get(key) or "") for key in ("title", "question", "marketTitle", "slug", "eventTitle", "eventSlug")
    ).lower()
    tokens = set(_tokenize(primary_text))
    event_tokens = set(_tokenize(event_match_text))
    outcome_text = _candidate_outcome_text(row)
    outcome_tokens = set(_tokenize(outcome_text))
    home_tokens = _team_tokens(match.get("homeTeam"))
    away_tokens = _team_tokens(match.get("awayTeam"))
    home_text = str(match.get("homeTeam") or "").lower()
    away_text = str(match.get("awayTeam") or "").lower()
    primary_home_hit = bool(home_tokens & tokens) or home_text in primary_text
    primary_away_hit = bool(away_tokens & tokens) or away_text in primary_text
    event_home_hit = bool(home_tokens & event_tokens) or home_text in event_match_text
    event_away_hit = bool(away_tokens & event_tokens) or away_text in event_match_text
    outcome_home_hit = bool(home_tokens & outcome_tokens) or home_text in outcome_text
    outcome_away_hit = bool(away_tokens & outcome_tokens) or away_text in outcome_text
    primary_has_match = primary_home_hit and primary_away_hit
    event_has_match = event_home_hit and event_away_hit
    outcome_hint = _match_outcome_hint(match, row)
    outcome_has_match = (outcome_home_hit and outcome_away_hit) or bool(outcome_hint)
    if _safe_list(row.get("outcomeMarkets")):
        child_hints = {
            _match_outcome_hint(match, child)
            for child in _safe_list(row.get("outcomeMarkets"))
            if isinstance(child, dict)
        }
        if {home_text and str(match.get("homeTeam") or ""), "Draw", away_text and str(match.get("awayTeam") or "")} - {""} <= child_hints:
            outcome_has_match = True
            primary_has_match = True
    if not (primary_has_match or (event_has_match and outcome_has_match) or (outcome_home_hit and outcome_away_hit)):
        return "missing-team"
    worldcup_hit = any(term in text for term in ("world cup", "fifa", "fifwc", "wc2026", "2026"))
    if not worldcup_hit:
        return "not-worldcup"
    prop_terms = (
        "spread",
        " o/u ",
        "over/under",
        "total",
        "corners",
        "first team to score",
        "first-to-score",
        "exact score",
        "halftime",
        "player props",
        "goals-",
        " goals",
        "both teams to score",
        "btts",
        "cards",
    )
    outright_terms = (
        "group a last place",
        "group a second place",
        "group a winner",
        "highest-scoring team",
        "highest scoring team",
        "fair play award",
        "award winner",
    )
    market_terms = ("winner", "winning", "win", "match result", "moneyline", "draw", "beat", "advance")
    if any(term in primary_text for term in outright_terms):
        return "not-match-market"
    if not _safe_list(row.get("outcomeMarkets")) and any(term in f" {primary_text} {text} " for term in prop_terms):
        if not any(term in primary_text for term in market_terms):
            return "not-match-market"
    if event_has_match and not outcome_has_match:
        if not any(term in primary_text for term in market_terms):
            return "not-match-market"
    return ""


def _worldcup_market_score(match: Dict[str, Any], row: Dict[str, Any]) -> int:
    if _worldcup_market_reject_reason(match, row):
        return 0
    text = _market_text(row)
    score = 80
    child_hints = {
        _match_outcome_hint(match, child)
        for child in _safe_list(row.get("outcomeMarkets"))
        if isinstance(child, dict)
    }
    expected = {str(match.get("homeTeam") or ""), "Draw", str(match.get("awayTeam") or "")}
    if expected <= child_hints:
        score += 60
    if "draw" in text or "winner" in text or "moneyline" in text:
        score += 8
    if _match_outcome_hint(match, row):
        score += 6
    if len(_extract_probability_rows(match, row)) >= 2:
        score += 10
    kickoff = str(match.get("kickoffUtc") or "")[:10]
    if kickoff and kickoff in text:
        score += 5
    return score


def _normalize_market_candidate(item: Dict[str, Any], event: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    event = _candidate_event_payload(item, event)
    title = str(item.get("question") or item.get("title") or event.get("title") or "").strip()
    slug = str(item.get("slug") or event.get("slug") or "").strip()
    event_slug = str(event.get("slug") or item.get("eventSlug") or "").strip()
    token_ids = _safe_list(item.get("clobTokenIds") or item.get("clob_token_ids"))
    return {
        **item,
        "title": title,
        "marketTitle": title,
        "slug": slug,
        "eventTitle": event.get("title") or item.get("eventTitle"),
        "eventSlug": event_slug,
        "eventId": event.get("id") or item.get("eventId"),
        "gammaMarketId": item.get("id") or item.get("gamma_market_id"),
        "conditionId": item.get("conditionId") or item.get("condition_id"),
        "groupItemTitle": item.get("groupItemTitle"),
        "clobTokenIds": token_ids,
        "yes_token_id": item.get("yes_token_id") or item.get("yesTokenId") or (token_ids[0] if token_ids else ""),
        "no_token_id": item.get("no_token_id") or item.get("noTokenId") or (token_ids[1] if len(token_ids) > 1 else ""),
        "marketUrl": _polymarket_url({**event, **item, "slug": slug or event_slug, "eventSlug": event_slug}),
        "source": "gamma",
    }


def _gamma_search(ctx: Dict[str, Any], query: str, *, limit: int = 8) -> List[Dict[str, Any]]:
    getter = ctx.get("http_json_get")
    if not callable(getter):
        return []
    settings = ctx.get("SETTINGS")
    base_url = str(getattr(settings, "gamma_api_base", "") or POLYMARKET_GAMMA_API_BASE).rstrip("/")
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for path in ("/markets", "/events"):
        try:
            payload = getter(f"{base_url}{path}", params={"q": query, "limit": limit}, timeout=8, headers=_headers())
        except Exception:
            continue
        items = payload if isinstance(payload, list) else payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            nested_markets = item.get("markets") if isinstance(item.get("markets"), list) else []
            candidates = nested_markets if nested_markets else [item]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                normalized = _normalize_market_candidate(candidate, item if nested_markets else None)
                key = str(normalized.get("slug") or normalized.get("marketTitle") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                rows.append(normalized)
                if len(rows) >= limit:
                    return rows
    return rows


def _gamma_scan_active(ctx: Dict[str, Any], *, limit: int = 120) -> List[Dict[str, Any]]:
    getter = ctx.get("http_json_get")
    if not callable(getter):
        return []
    settings = ctx.get("SETTINGS")
    base_url = str(getattr(settings, "gamma_api_base", "") or POLYMARKET_GAMMA_API_BASE).rstrip("/")
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    param_sets = [
        {"active": "true", "closed": "false", "limit": limit, "offset": 0, "order": "id", "ascending": "false"},
        {"active": "true", "closed": "false", "limit": limit, "offset": 0, "order": "volume24hr", "ascending": "false"},
        {"active": "true", "closed": "false", "limit": limit, "offset": 0, "q": "world cup"},
        {"active": "true", "closed": "false", "limit": limit, "offset": 0, "q": "fifa"},
        {"active": "true", "closed": "false", "limit": limit, "offset": 0, "q": "soccer"},
        {"active": "true", "closed": "false", "limit": limit, "offset": 0, "tag_slug": "soccer"},
        {"active": "true", "closed": "false", "limit": limit, "offset": 0, "tag_slug": "sports"},
    ]
    for path in ("/events", "/markets"):
        for params in param_sets:
            try:
                payload = getter(f"{base_url}{path}", params=params, timeout=10, headers=_headers())
            except Exception:
                continue
            items = payload if isinstance(payload, list) else payload.get("data") if isinstance(payload, dict) else []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                nested_markets = item.get("markets") if isinstance(item.get("markets"), list) else []
                candidates = nested_markets if nested_markets else [item]
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    normalized = _normalize_market_candidate(candidate, item if nested_markets else None)
                    key = str(normalized.get("slug") or normalized.get("gammaMarketId") or normalized.get("marketTitle") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    rows.append({**normalized, "source": "gamma-scan"})
    return rows


def _significant_market_search_tokens(query: Any) -> List[str]:
    stop = {"and", "the", "vs", "v", "world", "cup", "fifa", "soccer", "football", "match", "market"}
    tokens: List[str] = []
    for token in _tokenize(query):
        if token in stop or len(token) < 2:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens[:8]


def _local_event_serving_search(ctx: Dict[str, Any], query: str, *, limit: int) -> List[Dict[str, Any]]:
    query_all = ctx.get("query_all")
    if not callable(query_all):
        return []
    tokens = _significant_market_search_tokens(query)
    search_text = """
        (
          COALESCE(title, '') || ' ' ||
          COALESCE(event_slug, '') || ' ' ||
          COALESCE(event_title, '') || ' ' ||
          COALESCE(category, '') || ' ' ||
          COALESCE(CAST(tags AS TEXT), '') || ' ' ||
          COALESCE(CAST(outcomes AS TEXT), '') || ' ' ||
          COALESCE(CAST(top_outcomes AS TEXT), '')
        )
    """
    if tokens:
        token_filter = " AND ".join(f"{search_text} ILIKE ?" for _ in tokens)
        params: List[Any] = [f"%{token}%" for token in tokens]
    else:
        token_filter = f"{search_text} ILIKE ?"
        params = [f"%{query}%"]
    try:
        rows = query_all(
            f"""
            SELECT
              event_id, event_slug, event_title, title, category, tags,
              volume_24h, outcome_count, default_market_id,
              default_condition_id, default_gamma_market_id,
              top_outcomes, outcomes, completion_status,
              is_trading_closed, active_rank, updated_at
            FROM event_market_serving
            WHERE outcome_count > 0
              AND is_trading_closed = FALSE
              AND completion_status NOT IN ('SETTLED', 'CANCELLED', 'CLOSED_UNRESOLVED')
              AND ({token_filter})
            ORDER BY active_rank DESC NULLS LAST, volume_24h DESC NULLS LAST, updated_at DESC NULLS LAST
            LIMIT ?
            """,
            [*params, int(max(limit, 16))],
        )
    except Exception:
        return []
    return [{**_serving_market_candidate(row), "source": "local-db"} for row in rows if isinstance(row, dict)]


def _local_moneyline_bundle_search(ctx: Dict[str, Any], query: str, *, limit: int) -> List[Dict[str, Any]]:
    query_all = ctx.get("query_all")
    if not callable(query_all):
        return []
    tokens = _significant_market_search_tokens(query)
    if not tokens:
        return []
    search_text = """
        (
          COALESCE(m.title, '') || ' ' ||
          COALESCE(m.slug, '') || ' ' ||
          COALESCE(m.event_slug, '') || ' ' ||
          COALESCE(m.event_title, '') || ' ' ||
          COALESCE(CAST(m.tags AS TEXT), '')
        )
    """
    token_filter = " OR ".join(f"{search_text} ILIKE ?" for _ in tokens)
    params: List[Any] = [f"%{token}%" for token in tokens]
    try:
        rows = query_all(
            f"""
            SELECT
              m.id, m.gamma_market_id, m.slug, m.condition_id, m.yes_token_id,
              m.no_token_id, m.clob_token_ids, m.title, m.category, m.tags,
              m.end_date, m.event_id, m.event_slug, m.event_title,
              p.latest_price, p.latest_yes_price, p.latest_no_price,
              s.completion_status, s.is_trading_closed
            FROM markets m
            LEFT JOIN market_latest_prices p ON p.market_id = m.id
            LEFT JOIN market_status_snapshot s ON s.market_id = m.id
            WHERE COALESCE(s.is_trading_closed, FALSE) = FALSE
              AND COALESCE(s.completion_status, 'OPEN') NOT IN ('SETTLED', 'CANCELLED', 'CLOSED_UNRESOLVED')
              AND (m.slug ILIKE ? OR m.slug ILIKE ? OR COALESCE(m.event_slug, '') ILIKE ?)
              AND ({token_filter})
            ORDER BY m.end_date ASC NULLS LAST, m.id DESC
            LIMIT ?
            """,
            ["%fifwc%", "%wc2026%", "%fifwc%", *params, int(max(limit * 20, 120))],
        )
    except Exception:
        return []
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        candidate = _market_table_candidate(row)
        slug_base = _worldcup_market_slug_base(candidate.get("slug"))
        if not slug_base:
            continue
        slug = str(candidate.get("slug") or "").lower()
        title = str(candidate.get("title") or "").lower()
        if not ("end in a draw" in title or re.match(r"^will .+ win on \d{4}-\d{2}-\d{2}\?$", title)):
            continue
        groups.setdefault(slug_base, []).append(candidate)
    bundles: List[Dict[str, Any]] = []
    for slug_base, children in groups.items():
        if len(children) < 2:
            continue
        bundles.append(_moneyline_bundle_candidate(slug_base, children))
    return bundles[:limit]


def _local_market_search(ctx: Dict[str, Any], query: str, *, limit: int = 8) -> List[Dict[str, Any]]:
    moneyline_rows = _local_moneyline_bundle_search(ctx, query, limit=limit)
    if moneyline_rows:
        return moneyline_rows[:limit]
    local_rows = _local_event_serving_search(ctx, query, limit=limit)
    if local_rows:
        seen: set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for row in local_rows:
            key = str(row.get("slug") or row.get("id") or row.get("marketTitle") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(row)
            if len(deduped) >= limit:
                return deduped

    getter = ctx.get("get_markets_payload")
    if not callable(getter):
        return []
    try:
        payload = getter(status="active", query=query, page=1, page_size=limit)
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) and isinstance(payload.get("items"), list) else []
    rows: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            rows.append({**_normalize_market_candidate(item), "source": "local-markets"})
    return rows[:limit]


def _percent_from_price(value: Any) -> Optional[float]:
    number = _safe_float(value)
    if number is None:
        return None
    if 0 <= number <= 1:
        return number * 100
    return number


def _snapshot_outcomes_from_probabilities(probabilities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    outcomes: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for probability in probabilities:
        if not isinstance(probability, dict):
            continue
        name = str(probability.get("outcome") or probability.get("name") or "").strip()
        implied = _percent_from_price(probability.get("price") if probability.get("price") is not None else probability.get("impliedProbability"))
        if not name or implied is None or name.lower() in seen:
            continue
        seen.add(name.lower())
        outcomes.append(
            {
                "name": name,
                "impliedProbability": round(implied, 2),
                "price": probability.get("price"),
                "marketUrl": probability.get("marketUrl"),
            }
        )
    return outcomes


def _ordered_outcomes(match: Dict[str, Any], outcomes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_name = {str(outcome.get("name") or "").lower(): outcome for outcome in outcomes if isinstance(outcome, dict)}
    ordered: List[Dict[str, Any]] = []
    for label in (str(match.get("homeTeam") or ""), "Draw", str(match.get("awayTeam") or "")):
        row = by_name.pop(label.lower(), None)
        if row:
            ordered.append(row)
    ordered.extend(by_name.values())
    return ordered


def _team_match_score(left: Any, right: Any) -> int:
    left_text = str(left or "").strip().lower()
    right_text = str(right or "").strip().lower()
    if not left_text or not right_text:
        return 0
    if left_text == right_text:
        return 4
    left_tokens = _team_tokens(left_text)
    right_tokens = _team_tokens(right_text)
    overlap = left_tokens & right_tokens
    if not overlap:
        return 0
    return 3 if len(overlap) >= min(len(left_tokens), len(right_tokens), 2) else 1


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _bookmaker_event_score(match: Dict[str, Any], event: Dict[str, Any]) -> int:
    home_score = _team_match_score(match.get("homeTeam"), event.get("home_team"))
    away_score = _team_match_score(match.get("awayTeam"), event.get("away_team"))
    reversed_home_score = _team_match_score(match.get("homeTeam"), event.get("away_team"))
    reversed_away_score = _team_match_score(match.get("awayTeam"), event.get("home_team"))
    team_score = max(home_score + away_score, reversed_home_score + reversed_away_score)
    if team_score < 4:
        return 0
    match_time = _parse_iso(match.get("kickoffUtc"))
    event_time = _parse_iso(event.get("commence_time"))
    time_score = 0
    if match_time and event_time:
        delta_hours = abs((match_time - event_time).total_seconds()) / 3600
        if delta_hours <= 2:
            time_score = 8
        elif delta_hours <= 8:
            time_score = 4
        elif match_time.date() == event_time.date():
            time_score = 2
    return team_score * 4 + time_score


def _bookmaker_h2h_outcomes(match: Dict[str, Any], event: Dict[str, Any]) -> List[Dict[str, Any]]:
    buckets: Dict[str, Dict[str, Any]] = {}
    for bookmaker in event.get("bookmakers") or []:
        if not isinstance(bookmaker, dict):
            continue
        book_title = str(bookmaker.get("title") or bookmaker.get("key") or "Book").strip()
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, dict) or market.get("key") != "h2h":
                continue
            raw_rows = []
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, dict):
                    continue
                price = _safe_float(outcome.get("price"))
                name = _canonical_outcome_label(match, outcome.get("name"))
                if not name or price is None or price <= 1:
                    continue
                raw_rows.append({"name": name, "price": price})
            overround = sum(1 / row["price"] for row in raw_rows)
            if overround <= 0:
                continue
            for row in raw_rows:
                implied = (1 / row["price"]) / overround * 100
                bucket = buckets.setdefault(row["name"], {"prices": [], "probabilities": [], "books": []})
                bucket["prices"].append(row["price"])
                bucket["probabilities"].append(implied)
                bucket["books"].append(book_title)
    outcomes: List[Dict[str, Any]] = []
    for name, bucket in buckets.items():
        implied = _mean([float(value) for value in bucket.get("probabilities") or []])
        prices = [float(value) for value in bucket.get("prices") or []]
        if implied is None or not prices:
            continue
        outcomes.append(
            {
                "name": name,
                "decimalOdds": round(max(prices), 3),
                "impliedProbability": round(implied, 2),
                "bookCount": len(prices),
                "source": "bookmaker-consensus",
            }
        )
    return _ordered_outcomes(match, outcomes)


def _fetch_bookmaker_events(ctx: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    getter = ctx.get("http_json_get")
    settings = ctx.get("SETTINGS")
    api_key = str(getattr(settings, "the_odds_api_key", "") or "").strip()
    if not callable(getter) or not api_key:
        return [], "missing-key", {"sportKey": WORLDCUP_ODDS_SPORT_KEY, "events": 0, "matched": 0}
    base_url = str(getattr(settings, "the_odds_api_base_url", "") or "https://api.the-odds-api.com").rstrip("/")
    try:
        payload = getter(
            f"{base_url}/v4/sports/{WORLDCUP_ODDS_SPORT_KEY}/odds/",
            params={
                "apiKey": api_key,
                "regions": WORLDCUP_ODDS_REGIONS,
                "markets": "h2h",
                "oddsFormat": "decimal",
                "dateFormat": "iso",
            },
            timeout=12,
            headers=_headers(),
        )
    except Exception:
        return [], "error", {"sportKey": WORLDCUP_ODDS_SPORT_KEY, "events": 0, "matched": 0}
    events = [item for item in (payload if isinstance(payload, list) else []) if isinstance(item, dict)]
    return events, "ok" if events else "empty", {"sportKey": WORLDCUP_ODDS_SPORT_KEY, "events": len(events), "matched": 0}


def _link_bookmaker_odds(ctx: Dict[str, Any], matches: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    events, state, stats = _fetch_bookmaker_events(ctx)
    if not events or not matches:
        return [], state, stats
    generated_at = _utc_now_iso()
    rows: List[Dict[str, Any]] = []
    used_events: set[str] = set()
    for match in matches:
        if str(match.get("status") or "") == "finished":
            continue
        best: Optional[Dict[str, Any]] = None
        best_score = 0
        for event in events:
            event_id = str(event.get("id") or event.get("commence_time") or "")
            if event_id in used_events:
                continue
            score = _bookmaker_event_score(match, event)
            if score > best_score:
                best = event
                best_score = score
        if not best or best_score <= 0:
            continue
        outcomes = _bookmaker_h2h_outcomes(match, best)
        if not outcomes:
            continue
        event_id = str(best.get("id") or best.get("commence_time") or "")
        used_events.add(event_id)
        book_count = max((int(outcome.get("bookCount") or 0) for outcome in outcomes), default=0)
        rows.append(
            {
                "id": f"{match.get('id')}:bookmaker-h2h",
                "matchId": match.get("id"),
                "homeTeam": match.get("homeTeam"),
                "awayTeam": match.get("awayTeam"),
                "kickoffUtc": match.get("kickoffUtc"),
                "provider": "The Odds API consensus",
                "providerType": "online_bookmaker",
                "marketType": "moneyline",
                "outcomes": outcomes,
                "generatedAt": generated_at,
                "source": "the-odds-api",
                "sourceUrl": str(getattr(ctx.get("SETTINGS"), "the_odds_source_url", "") or "https://the-odds-api.com/"),
                "bookmakerCount": book_count,
                "eventId": event_id,
                "commenceTime": best.get("commence_time"),
                "confidence": min(99, best_score),
            }
        )
        match["oddsLinked"] = True
    stats["matched"] = len(rows)
    return rows, "ok" if rows else state, stats


def _search_market_sources(ctx: Dict[str, Any], query: str, *, limit: int = 8) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    local_candidates = _local_market_search(ctx, query, limit=limit)
    for candidate in local_candidates:
        key = str(candidate.get("slug") or candidate.get("id") or candidate.get("marketTitle") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(candidate)
        if len(rows) >= limit:
            return rows
    if any(str(candidate.get("source") or "").startswith("local-db-moneyline") for candidate in rows):
        return rows
    for candidate in _gamma_search(ctx, query, limit=limit):
        key = str(candidate.get("slug") or candidate.get("id") or candidate.get("marketTitle") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(candidate)
        if len(rows) >= limit:
            return rows
    return rows


def _new_market_linker_stats(*, scan_limit: int, scheduled_count: int) -> Dict[str, Any]:
    return {
        "version": "worldcup-market-linker-v2",
        "scanLimit": scan_limit,
        "scheduledMatches": scheduled_count,
        "matchesScanned": 0,
        "queries": 0,
        "candidates": 0,
        "matched": 0,
        "sources": {},
        "rejections": {
            "no-candidates": 0,
            "missing-team": 0,
            "inactive": 0,
            "not-worldcup": 0,
            "not-match-market": 0,
            "duplicate": 0,
        },
    }


def _clob_snapshot(ctx: Dict[str, Any], market: Dict[str, Any]) -> Dict[str, Any]:
    getter = ctx.get("get_market_clob_price_snapshot")
    if not callable(getter):
        return {}
    try:
        snapshot = getter(market)
    except Exception:
        return {}
    return snapshot if isinstance(snapshot, dict) else {}


def _gamma_market_price_snapshot(ctx: Dict[str, Any], market: Dict[str, Any]) -> Dict[str, Any]:
    getter = ctx.get("http_json_get")
    requests_module = ctx.get("requests")
    if not callable(getter) and requests_module is None:
        return {}
    gamma_market_id = str(market.get("gammaMarketId") or market.get("gamma_market_id") or "").strip()
    slug = str(market.get("slug") or "").strip()
    settings = ctx.get("SETTINGS")
    base_url = str(getattr(settings, "gamma_api_base", "") or POLYMARKET_GAMMA_API_BASE).rstrip("/")
    url = f"{base_url}/markets/{gamma_market_id}" if gamma_market_id else f"{base_url}/markets"
    params = None if gamma_market_id else {"slug": slug, "limit": 1}
    payload: Any = {}
    if requests_module is not None:
        try:
            response = requests_module.get(url, params=params, timeout=8, headers=_headers())
            response.raise_for_status()
            payload = response.json()
        except Exception:
            payload = {}
    if not payload and callable(getter):
        try:
            payload = getter(url, params=params, timeout=8, headers=_headers())
        except Exception:
            payload = {}
    if isinstance(payload, list):
        payload = payload[0] if payload else {}
    if not isinstance(payload, dict):
        return {}
    prices = _safe_json_list(payload.get("outcomePrices"))
    latest = payload.get("lastTradePrice")
    if latest in (None, "") and prices:
        latest = prices[0]
    return {
        "marketId": market.get("id") or market.get("localMarketId"),
        "gammaMarketId": payload.get("id") or gamma_market_id,
        "latestYesPrice": latest,
        "latestPrice": latest,
        "latestNoPrice": (1 - (_safe_float(latest) or 0)) if _safe_float(latest) is not None else None,
        "volume": payload.get("volume"),
        "volume24h": payload.get("volume24hr") or payload.get("volume24h"),
        "liquidity": payload.get("liquidity"),
        "updatedAt": _utc_now_iso(),
        "source": "gamma-direct",
    }


def _extract_probability_rows(match: Dict[str, Any], market: Dict[str, Any]) -> List[Dict[str, Any]]:
    outcomes = _safe_list(market.get("outcomes"))
    prices = _safe_list(market.get("outcomePrices"))
    rows: List[Dict[str, Any]] = []
    if outcomes and prices:
        if len(outcomes) == 2 and {str(outcome).strip().lower() for outcome in outcomes} <= {"yes", "no"}:
            hinted = _match_outcome_hint(match, market)
            if hinted and prices[0] not in (None, ""):
                rows.append(
                    {
                        "outcome": hinted,
                        "price": prices[0],
                        "marketTitle": market.get("marketTitle") or market.get("title"),
                        "marketUrl": _polymarket_url(market),
                        "clobTokenId": (market.get("clobTokenIds") or [""])[0] if isinstance(market.get("clobTokenIds"), list) else "",
                    }
                )
        else:
            for label, price in zip(outcomes, prices):
                if price in (None, ""):
                    continue
                rows.append(
                    {
                        "outcome": _canonical_outcome_label(match, label, allow_yes_no=True),
                        "price": price,
                        "marketTitle": market.get("marketTitle") or market.get("title"),
                        "marketUrl": _polymarket_url(market),
                    }
                )
    return rows


def _best_probability_rows(match: Dict[str, Any], markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_label: Dict[str, Dict[str, Any]] = {}
    for market in sorted(markets, key=lambda row: _worldcup_market_score(match, row), reverse=True):
        for probability in _extract_probability_rows(match, market):
            label = str(probability.get("outcome") or "").strip()
            if not label or label in by_label:
                continue
            by_label[label] = probability
    ordered: List[Dict[str, Any]] = []
    for label in (str(match.get("homeTeam") or ""), "Draw", str(match.get("awayTeam") or "")):
        if label in by_label:
            ordered.append(by_label.pop(label))
    ordered.extend(by_label.values())
    return ordered[:6]


def _bundle_probability_rows(ctx: Dict[str, Any], match: Dict[str, Any], market: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    children = [child for child in _safe_list(market.get("outcomeMarkets")) if isinstance(child, dict)]
    runtime_by_slug: Dict[str, Dict[str, Any]] = {}
    gamma_children = [
        child
        for child in children
        if (child.get("latestYesPrice") in (None, "") and child.get("latestPrice") in (None, ""))
    ]
    if gamma_children:
        with ThreadPoolExecutor(max_workers=min(3, len(gamma_children))) as executor:
            future_map = {executor.submit(_gamma_market_price_snapshot, ctx, child): str(child.get("slug") or child.get("id") or "") for child in gamma_children}
            for future in as_completed(future_map):
                try:
                    runtime_by_slug[future_map[future]] = future.result() or {}
                except Exception:
                    runtime_by_slug[future_map[future]] = {}
    for child in children:
        if not isinstance(child, dict):
            continue
        label = _match_outcome_hint(match, child)
        if label not in {str(match.get("homeTeam") or ""), "Draw", str(match.get("awayTeam") or "")}:
            continue
        if label in seen:
            continue
        price = child.get("latestYesPrice") if child.get("latestYesPrice") not in (None, "") else child.get("latestPrice")
        runtime = runtime_by_slug.get(str(child.get("slug") or child.get("id") or ""), {})
        if price in (None, ""):
            price = runtime.get("latestYesPrice") if isinstance(runtime, dict) else None
        if price in (None, ""):
            runtime = _clob_snapshot(ctx, child)
            price = runtime.get("latestYesPrice") if isinstance(runtime, dict) else None
        rows.append(
            {
                "outcome": label,
                "price": price,
                "marketTitle": child.get("marketTitle") or child.get("title"),
                "marketUrl": _polymarket_url(child),
                "clobTokenId": child.get("yes_token_id") or ((child.get("clobTokenIds") or [""])[0] if isinstance(child.get("clobTokenIds"), list) else ""),
                "source": runtime.get("source") if isinstance(runtime, dict) and runtime else child.get("source") or "local-db-market",
            }
        )
        seen.add(label)
    return _ordered_probability_rows(match, rows)


def _ordered_probability_rows(match: Dict[str, Any], rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_label = {str(row.get("outcome") or row.get("name") or ""): row for row in rows if isinstance(row, dict)}
    ordered: List[Dict[str, Any]] = []
    for label in (str(match.get("homeTeam") or ""), "Draw", str(match.get("awayTeam") or "")):
        row = by_label.pop(label, None)
        if row:
            ordered.append(row)
    ordered.extend(by_label.values())
    return ordered


def _link_worldcup_markets(ctx: Dict[str, Any], matches: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], str, Dict[str, Any]]:
    if not matches:
        return [], "empty", _new_market_linker_stats(scan_limit=0, scheduled_count=0)
    settings = ctx.get("SETTINGS")
    configured_scan_limit = int(getattr(settings, "worldcup_market_link_scan_limit", 12) or 12)
    scan_limit = min(configured_scan_limit, 12)
    scheduled = [match for match in matches if str(match.get("status") or "") != "finished"][: max(1, scan_limit)]
    stats = _new_market_linker_stats(scan_limit=scan_limit, scheduled_count=len(scheduled))
    rows: List[Dict[str, Any]] = []
    seen: set[str] = set()
    scan_candidates: List[Dict[str, Any]] = []
    for match in scheduled:
        stats["matchesScanned"] += 1
        home = str(match.get("homeTeam") or "").strip()
        away = str(match.get("awayTeam") or "").strip()
        if not home or not away or home == "TBD" or away == "TBD":
            continue
        queries = [
            f"{home} {away} world cup",
            f"{home} vs {away} fifa world cup",
            f"{away} {home} world cup",
        ]
        best: Optional[Dict[str, Any]] = None
        best_score = 0
        accepted: List[Dict[str, Any]] = []
        match_candidates = 0
        for query_index, query in enumerate(queries):
            stats["queries"] += 1
            candidates = _search_market_sources(ctx, query, limit=8)
            if query_index == 0 and scan_candidates:
                candidates = [*candidates, *scan_candidates]
            match_candidates += len(candidates)
            stats["candidates"] += len(candidates)
            for candidate in candidates:
                source = str(candidate.get("source") or "unknown")
                stats["sources"][source] = int(stats["sources"].get(source) or 0) + 1
                reason = _worldcup_market_reject_reason(match, candidate)
                if reason:
                    stats["rejections"][reason] = int(stats["rejections"].get(reason) or 0) + 1
                    continue
                score = _worldcup_market_score(match, candidate)
                accepted.append(candidate)
                if score > best_score:
                    best = candidate
                    best_score = score
            if best_score >= 140 and str((best or {}).get("source") or "").startswith("local-db-moneyline"):
                break
        if not best or best_score <= 0:
            if match_candidates <= 0:
                stats["rejections"]["no-candidates"] = int(stats["rejections"].get("no-candidates") or 0) + 1
            continue
        key = str(best.get("slug") or best.get("marketTitle") or match.get("id"))
        if key in seen:
            stats["rejections"]["duplicate"] = int(stats["rejections"].get("duplicate") or 0) + 1
            continue
        seen.add(key)
        outcomes = _safe_list(best.get("outcomes"))
        outcome_prices = _safe_list(best.get("outcomePrices"))
        clob = {}
        if _safe_list(best.get("outcomeMarkets")):
            probabilities = _bundle_probability_rows(ctx, match, best)
            outcomes = [row.get("outcome") for row in probabilities]
            outcome_prices = [row.get("price") for row in probabilities]
        else:
            clob = _clob_snapshot(ctx, best)
            if not outcome_prices and clob.get("latestYesPrice") is not None:
                outcome_prices = [clob.get("latestYesPrice")]
                outcomes = outcomes or ["YES"]
            probabilities = _best_probability_rows(match, accepted) or [
                {"outcome": str(label), "price": price, "marketUrl": _polymarket_url(best)}
                for label, price in zip(outcomes, outcome_prices)
            ]
        snapshot_outcomes = _ordered_outcomes(match, _snapshot_outcomes_from_probabilities(probabilities))
        market_url = _polymarket_url(best)
        if len(probabilities) > 1 and str(best.get("eventSlug") or "").strip():
            market_url = f"https://polymarket.com/event/{str(best.get('eventSlug')).strip()}"
        rows.append(
            {
                "id": f"{match.get('id')}:polymarket",
                "matchId": match.get("id"),
                "homeTeam": home,
                "awayTeam": away,
                "kickoffUtc": match.get("kickoffUtc"),
                "title": best.get("marketTitle") or best.get("title"),
                "marketTitle": best.get("marketTitle") or best.get("title"),
                "slug": best.get("slug"),
                "eventTitle": best.get("eventTitle"),
                "eventSlug": best.get("eventSlug"),
                "eventId": best.get("eventId"),
                "gammaMarketId": best.get("gammaMarketId"),
                "conditionId": best.get("conditionId"),
                "marketUrl": market_url,
                "tradeUrl": market_url,
                "outcomes": snapshot_outcomes,
                "rawOutcomes": outcomes,
                "outcomePrices": outcome_prices,
                "probabilities": probabilities,
                "clobTokenIds": best.get("clobTokenIds"),
                "clob": clob or None,
                "source": best.get("source") or "polymarket-gamma",
                "provider": "Polymarket local/Gamma/CLOB",
                "providerType": "prediction_market",
                "marketType": "moneyline",
                "generatedAt": _utc_now_iso(),
                "confidence": min(99, best_score),
            }
        )
        stats["matched"] += 1
        match["marketLinked"] = True
        match["oddsLinked"] = bool(outcome_prices)
    return rows, "ok" if rows else "empty", stats


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    matches = payload.get("matches") if isinstance(payload.get("matches"), list) else []
    cities = payload.get("cities") if isinstance(payload.get("cities"), list) else WORLD_CUP_CITIES
    weather = payload.get("weather") if isinstance(payload.get("weather"), list) else []
    news = payload.get("news") if isinstance(payload.get("news"), list) else []
    rosters = payload.get("rosters") if isinstance(payload.get("rosters"), list) else []
    odds = payload.get("odds") if isinstance(payload.get("odds"), list) else []
    market_linker = payload.get("marketLinker") if isinstance(payload.get("marketLinker"), dict) else {}
    bookmaker_linker = payload.get("bookmakerLinker") if isinstance(payload.get("bookmakerLinker"), dict) else {}
    return {
        "generatedAt": str(payload.get("generatedAt") or _utc_now_iso()),
        "cacheMode": str(payload.get("cacheMode") or "remote"),
        "tournament": payload.get("tournament") if isinstance(payload.get("tournament"), dict) else {
            "id": "fifa-world-cup-2026",
            "name": "FIFA World Cup 2026",
            "startsAt": "2026-06-11T19:00:00Z",
            "endsAt": "2026-07-19T19:00:00Z",
            "timezone": "Asia/Shanghai",
        },
        "cities": cities,
        "matches": matches,
        "news": news,
        "weather": weather,
        "rosters": rosters,
        "odds": odds,
        "intelligence": payload.get("intelligence") if isinstance(payload.get("intelligence"), dict) else None,
        "source": str(payload.get("source") or "World Cup verified dashboard"),
        "sourceUrl": str(payload.get("sourceUrl") or OPENFOOTBALL_2026_URL),
        "providerStates": payload.get("providerStates") if isinstance(payload.get("providerStates"), dict) else {},
        "marketLinker": market_linker,
        "bookmakerLinker": bookmaker_linker,
        "summary": {
            "cities": len(cities),
            "matches": len(matches),
            "news": len(news),
            "weatherCities": len(weather),
            "rosters": len(rosters),
            "odds": len(odds),
            "oddsCandidates": int(market_linker.get("candidates") or 0),
            "oddsMatched": int(market_linker.get("matched") or len(odds)),
            "bookmakerEvents": int(bookmaker_linker.get("events") or 0),
            "bookmakerMatched": int(bookmaker_linker.get("matched") or 0),
        },
    }


def _has_generated_fallback_artifacts(payload: Dict[str, Any]) -> bool:
    cache_mode = str(payload.get("cacheMode") or "").lower()
    source = str(payload.get("source") or "").lower()
    provider_states = payload.get("providerStates") if isinstance(payload.get("providerStates"), dict) else {}
    odds = payload.get("odds") if isinstance(payload.get("odds"), list) else []
    weather = payload.get("weather") if isinstance(payload.get("weather"), list) else []
    return (
        cache_mode in {"seed", "seeded"}
        or "dashboard seed" in source
        or "fallback" in source
        or "dashboardSeed" in provider_states
        or any(str(row.get("provider") or "") == "Model consensus watch" for row in odds if isinstance(row, dict))
        or any(str(row.get("source") or "") == "seed-estimate" for row in weather if isinstance(row, dict))
    )


def build_worldcup_dashboard_payload(
    ctx: Dict[str, Any],
    *,
    include_intel: bool = True,
    include_live_market_links: bool = True,
) -> Dict[str, Any]:
    generated_at = _utc_now_iso()
    source_matches, schedule_source = _fetch_schedule_source(ctx)
    matches = _normalize_matches(source_matches)
    intel: Optional[Dict[str, Any]] = None
    if include_intel:
        try:
            intel = worldcup_intel_service.get_worldcup_intel_snapshot(ctx, limit=120)
        except Exception as exc:
            intel = {"status": "error", "cacheMode": "source-required", "error": exc.__class__.__name__, "news": [], "weather": [], "signals": []}
    weather = intel.get("weather") if isinstance(intel, dict) and isinstance(intel.get("weather"), list) else []
    intel_news = intel.get("news") if isinstance(intel, dict) and isinstance(intel.get("news"), list) else []
    news = intel_news[:24]
    if include_live_market_links:
        bookmaker_odds, bookmaker_state, bookmaker_linker = _link_bookmaker_odds(ctx, matches)
        market_odds, market_state, market_linker = _link_worldcup_markets(ctx, matches)
        odds = [*bookmaker_odds, *market_odds]
        odds_state = "ok" if odds else market_state if market_state != "empty" else bookmaker_state
    else:
        odds = []
        odds_state = "deferred"
        bookmaker_linker = {"sportKey": WORLDCUP_ODDS_SPORT_KEY, "events": 0, "matched": 0, "mode": "deferred"}
        market_linker = {
            **_new_market_linker_stats(scan_limit=0, scheduled_count=sum(1 for match in matches if str(match.get("status") or "") != "finished")),
            "mode": "deferred",
            "reason": "live-market-linking-disabled-for-request",
        }
    starts_at = matches[0]["kickoffUtc"] if matches else "2026-06-11T19:00:00Z"
    ends_at = matches[-1]["kickoffUtc"] if matches else "2026-07-19T19:00:00Z"
    return _normalize_payload(
        {
            "generatedAt": generated_at,
            "cacheMode": "remote" if matches else "source-required",
            "tournament": {
                "id": "fifa-world-cup-2026",
                "name": "FIFA World Cup 2026",
                "startsAt": starts_at,
                "endsAt": ends_at,
                "timezone": "Asia/Shanghai",
            },
            "cities": WORLD_CUP_CITIES,
            "matches": matches,
            "news": news,
            "weather": weather,
            "rosters": [],
            "odds": odds,
            "marketLinker": market_linker,
            "intelligence": intel,
            "source": f"{schedule_source} / {intel.get('source') if isinstance(intel, dict) else 'runtime intel deferred'}",
            "sourceUrl": OPENFOOTBALL_2026_URL,
            "providerStates": {
                "schedule": "ok" if len(matches) >= 100 else "source-required",
                "worldcupIntel": str((intel or {}).get("status") or "unknown"),
                "weather": "ok" if weather else "empty",
                "odds": odds_state,
                "bookmakerOdds": bookmaker_state if include_live_market_links else "deferred",
                "rosters": "source-required",
            },
            "bookmakerLinker": bookmaker_linker,
        }
    )


def _read_cached(ctx: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    reader = ctx.get("get_cached_json")
    if callable(reader):
        cached = reader(WORLDCUP_DASHBOARD_NAMESPACE, WORLDCUP_DASHBOARD_CACHE_KEY)
        if isinstance(cached, dict):
            if _has_generated_fallback_artifacts(cached):
                return None
            return {**_normalize_payload(cached), "cacheMode": "redis"}
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        cached = store.get(WORLDCUP_DASHBOARD_NAMESPACE, WORLDCUP_DASHBOARD_CACHE_KEY)
        if isinstance(cached, dict):
            if _has_generated_fallback_artifacts(cached):
                return None
            return {**_normalize_payload(cached), "cacheMode": "sqlite"}
        stale = store.get_stale(WORLDCUP_DASHBOARD_NAMESPACE, WORLDCUP_DASHBOARD_CACHE_KEY)
        if isinstance(stale, dict):
            if _has_generated_fallback_artifacts(stale):
                return None
            return {**_normalize_payload(stale), "cacheMode": "stale"}
    return None


def _store(ctx: Dict[str, Any], payload: Dict[str, Any], ttl_seconds: int) -> None:
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        store.set(WORLDCUP_DASHBOARD_NAMESPACE, WORLDCUP_DASHBOARD_CACHE_KEY, payload, ttl_seconds)
    setter = ctx.get("set_cached_json")
    if callable(setter):
        setter(WORLDCUP_DASHBOARD_NAMESPACE, WORLDCUP_DASHBOARD_CACHE_KEY, payload, ttl_seconds)


def _log_exception(ctx: Dict[str, Any], message: str, *args: Any) -> None:
    app = ctx.get("app")
    logger = getattr(app, "logger", None)
    if logger is not None:
        logger.exception(message, *args)


def _preserve_stale_sections(payload: Dict[str, Any], stale_payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not stale_payload:
        return payload
    next_payload = dict(payload)
    if not next_payload.get("odds") and isinstance(stale_payload.get("odds"), list):
        next_payload["odds"] = stale_payload.get("odds")
        if isinstance(stale_payload.get("marketLinker"), dict):
            next_payload["marketLinker"] = stale_payload.get("marketLinker")
    if not next_payload.get("news") and isinstance(stale_payload.get("news"), list):
        next_payload["news"] = stale_payload.get("news")
    if not next_payload.get("weather") and isinstance(stale_payload.get("weather"), list):
        next_payload["weather"] = stale_payload.get("weather")
    return next_payload


def _refresh_async(
    ctx: Dict[str, Any],
    *,
    ttl_seconds: int,
    builder: Callable[[], Dict[str, Any]],
    stale_payload: Optional[Dict[str, Any]] = None,
) -> None:
    refresh_key = f"{WORLDCUP_DASHBOARD_NAMESPACE}:{WORLDCUP_DASHBOARD_CACHE_KEY}"
    with _REFRESH_LOCK:
        if refresh_key in _REFRESHING:
            return
        _REFRESHING.add(refresh_key)

    def refresh() -> None:
        try:
            payload = builder()
            if isinstance(payload, dict) and not _has_generated_fallback_artifacts(payload):
                payload = _preserve_stale_sections(payload, stale_payload)
                _store(ctx, payload, ttl_seconds)
        except Exception:
            _log_exception(ctx, "worldcup-dashboard async refresh failed key=%s", refresh_key)
        finally:
            with _REFRESH_LOCK:
                _REFRESHING.discard(refresh_key)

    thread = threading.Thread(target=refresh, name="worldcup-dashboard-refresh", daemon=True)
    thread.start()


def get_worldcup_dashboard_snapshot(ctx: Dict[str, Any]) -> Dict[str, Any]:
    ttl_seconds = max(300, int(getattr(ctx.get("SETTINGS"), "sports_runtime_ttl_seconds", DEFAULT_TTL_SECONDS) or DEFAULT_TTL_SECONDS))
    cached = _read_cached(ctx)
    if cached:
        cached_odds = cached.get("odds") if isinstance(cached.get("odds"), list) else []
        provider_states = cached.get("providerStates") if isinstance(cached.get("providerStates"), dict) else {}
        if cached.get("cacheMode") == "stale":
            _refresh_async(
                ctx,
                ttl_seconds=ttl_seconds,
                builder=lambda: build_worldcup_dashboard_payload(ctx, include_intel=True, include_live_market_links=True),
                stale_payload=cached,
            )
            return {**cached, "status": "stale"}
        if not cached_odds or provider_states.get("odds") in {"deferred", "empty", "source-required"}:
            _refresh_async(
                ctx,
                ttl_seconds=ttl_seconds,
                builder=lambda: build_worldcup_dashboard_payload(ctx, include_intel=True, include_live_market_links=True),
                stale_payload=cached,
            )
        return cached
    try:
        payload = build_worldcup_dashboard_payload(ctx, include_intel=False, include_live_market_links=False)
        _store(ctx, payload, ttl_seconds)
        _refresh_async(
            ctx,
            ttl_seconds=ttl_seconds,
            builder=lambda: build_worldcup_dashboard_payload(ctx, include_intel=True, include_live_market_links=True),
            stale_payload=payload,
        )
        return payload
    except Exception as exc:
        if cached:
            return {**cached, "status": "stale", "error": exc.__class__.__name__}
        return _normalize_payload(
            {
                "generatedAt": _utc_now_iso(),
                "cacheMode": "source-required",
                "matches": [],
                "cities": WORLD_CUP_CITIES,
                "weather": [],
                "news": [],
                "rosters": [],
                "odds": [],
                "providerStates": {"worldcupDashboard": f"error:{exc.__class__.__name__}"},
            }
        )
