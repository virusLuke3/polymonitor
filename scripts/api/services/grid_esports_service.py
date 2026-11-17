from __future__ import annotations

from api.services.seed_recovery import read_public_seed

from data_sources import source_value

import hashlib
import json
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from api.context import resolve_optional_service_callable
from requests import exceptions as request_errors


GRID_ESPORTS_NAMESPACE = "snapshot:esports:esports-intel"
DEFAULT_GRID_ESPORTS_LIMIT = 10
DEFAULT_GRID_PM_SEARCH_LIMIT = 12
DEFAULT_GRID_SERIES_CANDIDATE_LIMIT = 50

NEARBY_SERIES_QUERY = """
query EsportsIntelSeries($recentGte: String!, $now: String!, $upcomingLte: String!, $first: Int!) {
  recent: allSeries(
    first: $first
    filter: { startTimeScheduled: { gte: $recentGte, lte: $now } }
    orderBy: StartTimeScheduled
    orderDirection: DESC
  ) {
    totalCount
    edges {
      node {
        id
        startTimeScheduled
        format { nameShortened }
        teams { baseInfo { id name logoUrl } }
        tournament { id name }
        title { id nameShortened }
      }
    }
  }
  upcoming: allSeries(
    first: $first
    filter: { startTimeScheduled: { gte: $now, lte: $upcomingLte } }
    orderBy: StartTimeScheduled
    orderDirection: ASC
  ) {
    totalCount
    edges {
      node {
        id
        startTimeScheduled
        format { nameShortened }
        teams { baseInfo { id name logoUrl } }
        tournament { id name }
        title { id nameShortened }
      }
    }
  }
}
"""

SERIES_STATE_FIELDS = """
  id valid format startedAt updatedAt started finished
  teams { id name score won kills deaths }
  games {
    id sequenceNumber startedAt started finished
    map { name }
    teams { id name score won }
  }
"""


@dataclass(frozen=True)
class GridEsportsDependencies:
    settings: Any
    application: Any
    requests_lib: Any
    http_json_post: Callable[..., Any] | None
    search_markets: Callable[..., Any] | None
    get_cached_json: Callable[..., Any] | None
    set_cached_json: Callable[..., Any] | None
    snapshot_store: Any
    utc_now_iso: Callable[..., Any] | None
    previous_payload: Dict[str, Any] | None = None
    http_json_get: Callable[..., Any] | None = None

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> GridEsportsDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            settings=context.get("SETTINGS"),
            application=context.get("app"),
            requests_lib=context.get("requests"),
            http_json_post=resolve_optional_service_callable(
                context,
                "http_json_post",
            ),
            search_markets=resolve_optional_service_callable(
                context,
                "search_markets",
            ),
            http_json_get=resolve_optional_service_callable(context, "http_json_get"),
            get_cached_json=resolve_optional_service_callable(
                context,
                "get_cached_json",
            ),
            set_cached_json=resolve_optional_service_callable(
                context,
                "set_cached_json",
            ),
            snapshot_store=context.get("SNAPSHOT_STORE"),
            previous_payload=context.get("previous_grid_snapshot"),
            utc_now_iso=resolve_optional_service_callable(
                context,
                "utc_now_iso",
            ),
        )


GridEsportsContext = Mapping[str, Any] | GridEsportsDependencies


def _dependencies(
    context: GridEsportsContext,
) -> GridEsportsDependencies:
    return GridEsportsDependencies.from_context(context)


def _generated_at(dependencies: GridEsportsDependencies) -> str:
    if dependencies.utc_now_iso is not None:
        return str(dependencies.utc_now_iso())
    return _iso(_utc_now())


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safe_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _status_from_state(state: Optional[Dict[str, Any]], start_time: Optional[str]) -> str:
    if isinstance(state, dict):
        if state.get("finished") is True:
            return "finished"
        if state.get("started") is True:
            return "live"
    parsed = _parse_iso(start_time)
    if parsed is None:
        return "scheduled"
    return "upcoming" if parsed > _utc_now() else "pending-state"


def _source_status(has_key: bool, central_status: str, state_statuses: Iterable[str]) -> Dict[str, str]:
    states = list(state_statuses)
    queried_states = [status for status in states if status != "not-due"]
    if not queried_states and states:
        state_status = "not-required"
    elif any(status == "ok" for status in queried_states) and any(
        status != "ok" for status in queried_states
    ):
        state_status = "partial"
    elif any(status == "ok" for status in queried_states):
        state_status = "ok"
    else:
        state_status = ("empty" if all(s == "empty" for s in queried_states) else "error") if queried_states else "not-queried"
    return {
        "gridCentralData": central_status if has_key else "missing-key",
        "gridSeriesState": state_status,
        "polymarket": "optional-local-match",
    }


def _graphql_headers(settings: Any) -> Dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "polydata-runtime/1.0",
    }
    api_key = str(getattr(settings, "grid_api_key", "") or "").strip()
    if api_key:
        headers["x-api-key"] = api_key
    return headers


def _post_graphql_once(
    ctx: GridEsportsContext,
    url: str,
    query: str,
    variables: Dict[str, Any],
    timeout: int = 15,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    poster = dependencies.http_json_post
    if poster is not None:
        payload = poster(
            url,
            {"query": query, "variables": variables},
            timeout=timeout,
            headers=_graphql_headers(dependencies.settings),
        )
        if isinstance(payload, dict):
            return payload
        raise RuntimeError("GRID GraphQL returned non-object payload")

    requests = dependencies.requests_lib
    if requests is None:
        raise RuntimeError("requests is not available")
    close_client = False
    client = requests
    if hasattr(requests, "Session"):
        client = requests.Session()
        client.trust_env = False
        close_client = True
    try:
        response = client.post(
            url,
            json={"query": query, "variables": variables},
            timeout=timeout,
            headers=_graphql_headers(dependencies.settings),
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if close_client:
            client.close()
    if not isinstance(payload, dict):
        raise RuntimeError("GRID GraphQL returned non-object payload")
    return payload


def _post_graphql(ctx: GridEsportsContext, url: str, query: str, variables: Dict[str, Any],
                  timeout: int = 45, *, deadline: float | None = None) -> Dict[str, Any]:
    """Retry these read-only queries within one collector budget, never denials."""
    deadline = time.monotonic() + 90 if deadline is None else deadline
    for attempt in range(2):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("GRID collection budget exhausted")
        try:
            return _post_graphql_once(ctx, url, query, variables, timeout=min(timeout, remaining))
        except (request_errors.Timeout, request_errors.ConnectionError, TimeoutError):
            if attempt:
                raise
        except request_errors.HTTPError as exc:
            if attempt or getattr(exc.response, "status_code", None) not in {500, 502, 503, 504}:
                raise
        if time.monotonic() + 1 >= deadline:
            raise TimeoutError("GRID collection budget exhausted")
        time.sleep(1)


def _raise_graphql_errors(payload: Dict[str, Any]) -> None:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        message = str(first.get("message") or "GRID GraphQL error")
        raise RuntimeError(message)


def _extract_series_nodes(
    payload: Dict[str, Any],
    connection_name: str = "allSeries",
) -> Tuple[List[Dict[str, Any]], int]:
    all_series = (
        (payload.get("data") or {}).get(connection_name)
        if isinstance(payload.get("data"), dict)
        else None
    )
    if not isinstance(all_series, dict):
        return [], 0
    total_count = _safe_int(all_series.get("totalCount")) or 0
    nodes: List[Dict[str, Any]] = []
    for edge in all_series.get("edges") or []:
        node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict):
            nodes.append(node)
    return nodes, total_count


def _metadata_teams(node: Dict[str, Any]) -> Dict[str, str]:
    teams = {}
    for team in node.get("teams") or []:
        if not isinstance(team, dict):
            continue
        base_info = team.get("baseInfo") if isinstance(team.get("baseInfo"), dict) else {}
        team_id = str(base_info.get("id") or "").strip()
        name = str(base_info.get("name") or "").strip()
        if team_id:
            teams[team_id] = name
    return teams


def _named_team(name: str) -> bool:
    return bool(name) and not re.fullmatch(r"(?i)(?:tbd|tba|unknown|(?:team|cs2|dota2?|lol|valorant)[ -]?\d+)", name)


def _state_teams(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(team["id"]): team for team in state.get("teams") or []
            if isinstance(team, dict) and team.get("id")}


def _state_team_metrics(state: Dict[str, Any], team_ids: List[str]) -> List[Dict[str, Any]]:
    teams = _state_teams(state)
    if len(team_ids) != 2 or set(teams) != set(team_ids):
        return []
    return [{"id": team_id, "score": _safe_int(teams[team_id].get("score")),
             "kills": _safe_int(teams[team_id].get("kills")), "deaths": _safe_int(teams[team_id].get("deaths")),
             "won": teams[team_id].get("won") is True} for team_id in team_ids]


def _score_label(metrics: List[Dict[str, Any]]) -> str | None:
    if len(metrics) == 2 and all(item["score"] is not None and item["score"] >= 0 for item in metrics):
        return f"{metrics[0]['score']}-{metrics[1]['score']}"
    return None


def _game_states(state: Dict[str, Any], team_ids: List[str]) -> List[Dict[str, Any]]:
    games = []
    for game in state.get("games") or []:
        if not isinstance(game, dict) or not game.get("id") or not game.get("started"):
            continue
        sequence = _safe_int(game.get("sequenceNumber"))
        if sequence is None or sequence < 1:
            continue
        map_data = game.get("map") or {}
        metrics = _state_team_metrics(game, team_ids)
        games.append({
            "id": str(game["id"]), "number": sequence, "map": map_data.get("name"),
            "startedAt": game.get("startedAt"), "state": "finished" if game.get("finished") is True else "live",
            "score": _score_label(metrics), "teams": metrics,
        })
    return sorted(games, key=lambda game: game["number"])


def _series_states(
    ctx: GridEsportsContext,
    series_ids: List[str],
    *, deadline: float | None = None,
) -> Dict[str, Tuple[Optional[Dict[str, Any]], str]]:
    if not series_ids:
        return {}
    dependencies = _dependencies(ctx)
    settings = dependencies.settings
    url = str(getattr(settings, "grid_series_state_graphql_url", "") or "").strip()
    if not url:
        return {series_id: (None, "missing-url") for series_id in series_ids}
    variables = {f"series{i}": series_id for i, series_id in enumerate(series_ids)}
    declarations = ", ".join(f"${alias}: ID!" for alias in variables)
    selections = " ".join(f"{alias}: seriesState(id: ${alias}) {{ {SERIES_STATE_FIELDS} }}" for alias in variables)
    query = f"query EsportsIntelSeriesStates({declarations}) {{ {selections} }}"
    try:
        payload = _post_graphql(dependencies, url, query, variables, timeout=30, deadline=deadline)
        data = payload.get("data")
        if not isinstance(data, dict):
            _raise_graphql_errors(payload)
            data = {}
        failed = {err["path"][0] for err in payload.get("errors") or [] if isinstance(err, dict) and err.get("path")}
        states = {}
        for alias, series_id in variables.items():
            state = data.get(alias)
            if alias in failed:
                states[series_id] = None, "error"
            elif isinstance(state, dict) and str(state.get("id")) == series_id and state.get("valid") is True:
                states[series_id] = state, "ok"
            else:
                states[series_id] = None, "invalid" if state else "empty"
        return states
    except Exception as exc:
        logger = getattr(dependencies.application, "logger", None)
        if logger is not None:
            logger.warning("GRID series-state batch unavailable: count=%s error=%s http=%s", len(series_ids), type(exc).__name__, getattr(getattr(exc, "response", None), "status_code", None))
        return {series_id: (None, "error") for series_id in series_ids}


def _market_text(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _market_score(market: Dict[str, Any], team_names: List[str]) -> int:
    title = _market_text(market.get("title") or market.get("question") or market.get("name"))
    if not title:
        return -100

    teams = [_market_text(name) for name in team_names[:2]]
    score = 0
    if len(teams) >= 2:
        forward = f"{teams[0]} vs {teams[1]}"
        reverse = f"{teams[1]} vs {teams[0]}"
        if forward in title or reverse in title:
            score += 100
        if all(team and team in title for team in teams):
            score += 40

    if "counter strike" in title or "cs2" in title:
        score += 15
    if "bo1" in title or "bo3" in title or "bo5" in title or "winner" in title:
        score += 25
    if any(term in title for term in ("handicap", "total rounds", "rounds handicap", "over under", "odd even", "kills")):
        score -= 90
    return score


def _best_market(candidate_items: List[Any], team_names: List[str]) -> Dict[str, Any]:
    markets = [item for item in candidate_items if isinstance(item, dict)]
    if not markets:
        return {}
    return max(enumerate(markets), key=lambda row: (_market_score(row[1], team_names), -row[0]))[1]


def _pm_context(
    ctx: GridEsportsContext,
    team_names: List[str],
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    settings = dependencies.settings
    if not bool(getattr(settings, "grid_esports_pm_search_enabled", False)):
        return {"status": "not-matched", "probability": None, "delta": None, "signal": "PM SEARCH OFF", "matchQuality": "none"}
    search = dependencies.search_markets
    if search is None or len(team_names) < 2:
        return {"status": "not-matched", "probability": None, "delta": None, "signal": "NO PM MATCH", "matchQuality": "none"}
    try:
        query = f"{team_names[0]} {team_names[1]}"
        matches = search(query, limit=DEFAULT_GRID_PM_SEARCH_LIMIT)
    except Exception:
        return {"status": "error", "probability": None, "delta": None, "signal": "PM SEARCH ERR", "matchQuality": "low"}
    if isinstance(matches, dict):
        candidate_items = matches.get("items") or matches.get("markets") or []
    else:
        candidate_items = matches
    if not isinstance(candidate_items, list):
        candidate_items = []
    if not candidate_items:
        return {"status": "not-matched", "probability": None, "delta": None, "signal": "NO PM MATCH", "matchQuality": "none"}
    market = _best_market(candidate_items, team_names)
    price = _safe_float(market.get("latestYesPrice") or market.get("latestPrice"))
    return {
        "status": "matched",
        "marketId": market.get("id"),
        "gammaMarketId": market.get("gammaMarketId"),
        "conditionId": market.get("conditionId"),
        "slug": market.get("slug"),
        "title": market.get("title"),
        "probability": price,
        "delta": None,
        "signal": "PM LINKED" if price is not None else "PM MATCH",
        "matchQuality": "medium",
    }


def _gamma_array(value: Any) -> list:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def _verified_market_context(dependencies: GridEsportsDependencies, event: dict, hint: dict, *, timeout: float) -> dict:
    get = dependencies.http_json_get
    base = str(getattr(dependencies.settings, "gamma_api_base", "") or "").rstrip("/")
    slug = str(hint.get("slug") or "")
    condition = str(hint.get("conditionId") or "").lower()
    scheduled = _parse_iso(event.get("scheduledAt"))
    if not get or not base or not scheduled or not re.fullmatch(r"[a-z0-9-]{1,160}", slug) or not condition:
        return {}
    try:
        payload = get(f"{base}/events/slug/{slug}", timeout=timeout)
    except (request_errors.RequestException, OSError, ValueError):
        return {}
    if not isinstance(payload, dict) or payload.get("slug") != slug:
        return {}
    start = _parse_iso(payload.get("startTime"))
    title = str(payload.get("title") or "")
    title_head, _, tournament = title.partition(" - ")
    game = {"CS2": "counter strike", "DOTA": "dota", "DOTA2": "dota"}.get(event.get("gameTitle"))
    fmt = _market_text(event.get("format"))
    if (not start or abs(start - scheduled) > timedelta(hours=1) or not game
            or not _market_text(title_head).startswith(game + " ") or not fmt
            or fmt not in _market_text(title_head).split()):
        return {}

    def competition(value: str) -> set[str]:
        words = _market_text(value.split("(", 1)[0]).split()
        return {word for word in words if not word.isdigit()} - {"group", "stage", "playoffs", "series", "season"}

    grid_words = competition(event["tournament"])
    required_words = min(len(grid_words), max(2, len(grid_words) - 1))
    if not required_words or len(grid_words & competition(tournament)) < required_words:
        return {}
    markets = payload.get("markets")
    if not isinstance(markets, list):
        return {}
    markets = [row for row in markets if isinstance(row, dict)]
    main = next((row for row in markets if row.get("sportsMarketType") == "moneyline"
                 and row.get("slug") == slug and str(row.get("conditionId") or "").lower() == condition
                 and str(row.get("id")) == str(hint.get("gammaMarketId"))), None)
    if not main:
        return {}
    teams = _gamma_array(main.get("outcomes"))

    def team_name(value: Any) -> str:
        return re.sub(r" (?:esports?|gaming)$", "", _market_text(value))

    if len(teams) != 2 or {team_name(x) for x in teams} != {team_name(x) for x in event["teams"]}:
        return {}

    available = {row.get("sportsMarketType") for row in markets if isinstance(row.get("sportsMarketType"), str)}
    resolution = str(main.get("umaResolutionStatus") or "").lower()
    prices = [_safe_float(value) for value in _gamma_array(main.get("outcomePrices"))]
    winner = None
    if resolution == "resolved" and main.get("closed") is True and prices in ([0, 1], [1, 0]):
        winner = teams[prices.index(1)]
    return {
        "eventSlug": slug, "gammaMarketId": str(main["id"]), "conditionId": condition,
        "resolution": resolution, "winner": winner, "closed": main.get("closed") is True,
        "acceptingOrders": main.get("acceptingOrders") is True, "checkedAt": _iso(_utc_now()),
        "types": [kind for kind in ("moneyline", "child_moneyline", "map_handicap", "totals") if kind in available],
    }


def _normalize_series(
    node: Dict[str, Any],
    state: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    metadata = _metadata_teams(node)
    official = _state_teams(state or {})
    team_ids = list(metadata)
    if len(official) == 2 and (len(metadata) != 2 or not all(_named_team(name) for name in metadata.values())):
        team_ids = list(official)
    team_names = []
    for team_id in team_ids:
        name = str(official.get(team_id, {}).get("name") or "").strip()
        team_names.append(name if _named_team(name) else metadata.get(team_id, ""))
    title = node.get("title") if isinstance(node.get("title"), dict) else {}
    tournament = node.get("tournament") if isinstance(node.get("tournament"), dict) else {}
    metrics = _state_team_metrics(state or {}, team_ids)
    updated = _parse_iso((state or {}).get("updatedAt"))
    if not metrics or not updated or updated > _utc_now() + timedelta(seconds=60):
        state, updated, metrics = None, None, []
    status = _status_from_state(state, node.get("startTimeScheduled"))
    games = _game_states(state or {}, team_ids)
    current = next((game for game in reversed(games) if game["state"] == "live"), games[-1] if games else None)
    game_title = str(title.get("nameShortened") or title.get("name") or "ESPORTS").upper()
    team_a, team_b = (team_names + ["", ""])[:2]
    team_a = team_a if _named_team(team_a) else "TBD"
    team_b = team_b if _named_team(team_b) else "TBD"
    format_label = (node.get("format") or {}).get("nameShortened") or (state or {}).get("format")
    return {
        "id": str(node.get("id") or ""),
        "gameTitle": game_title,
        "tournament": str(tournament.get("name") or "GRID Series"),
        "series": f"{team_a} vs {team_b}",
        "teamA": team_a,
        "teamB": team_b,
        "teamIds": team_ids,
        "format": format_label,
        "startTime": node.get("startTimeScheduled"),
        "startedAt": (state or {}).get("startedAt"),
        "stateUpdatedAt": _iso(updated) if updated else None,
        "sourceStatus": "ok" if status in {"live", "finished"} else "schedule",
        "state": status,
        "score": _score_label(metrics) if status in {"live", "finished"} else None,
        "currentMap": " · ".join(str(part) for part in (f"Game {current['number']}", current["map"], current["score"]) if part) if current else None,
        "games": games,
        "liveContext": "Official state snapshot" if state else "Series metadata only",
        "teamMetrics": metrics,
    }


def _verified_events(items: List[Dict[str, Any]], previous: Dict[str, Any], reference: datetime) -> Tuple[str, List[Dict[str, Any]]]:
    since = _parse_iso(previous.get("eventsSince")) or reference
    cutoff = max(since, reference - timedelta(minutes=20))
    old = {row["id"]: row for row in previous.get("items") or [] if row.get("stateUpdatedAt")}
    events = {row["id"]: row for row in previous.get("events") or []
              if (stamp := _parse_iso(row.get("occurredAt"))) and cutoff < stamp <= reference}
    for item in items:
        if item["sourceStatus"] != "ok":
            continue
        series_id = item["id"]
        title = f"{item['gameTitle']} · {item['series']}"

        def record(key: str, action: str, stamp: datetime | None, score: str | None = None) -> None:
            if stamp and cutoff < stamp <= reference:
                event_id = f"{series_id}:{key}"
                events.setdefault(event_id, {"id": event_id, "title": title, "tournament": item["tournament"],
                                            "format": item["format"], "action": action, "score": score, "occurredAt": _iso(stamp),
                                            "gameTitle": item["gameTitle"], "teams": [item["teamA"], item["teamB"]],
                                            "scheduledAt": item["startTime"], "seriesScore": item["score"],
                                            "maps": [{name: game[name] for name in ("number", "map", "score")}
                                                     for game in item["games"] if game["state"] == "finished" and game["score"]]
                                            if key == "final" else []})

        prior = old.get(series_id)
        started = _parse_iso(item["startedAt"])
        if item["state"] == "live" and not (prior and prior["state"] == "finished"):
            record("started", "Series started", started)
        stamp = _parse_iso(item["stateUpdatedAt"])
        previous_stamp = _parse_iso(prior["stateUpdatedAt"]) if prior else None
        if not previous_stamp or prior["state"] != "live" or not stamp or stamp <= previous_stamp:
            continue
        if item["state"] == "finished" and item["score"]:
            record("final", "Final series score", stamp, item["score"])
            continue
        previous_games = {game["id"]: game for game in prior.get("games") or []}
        for game in item["games"]:
            former = previous_games.get(game["id"])
            game_start = _parse_iso(game["startedAt"])
            if game["state"] == "finished" and game["score"] and (
                (former and former["state"] == "live") or
                (not former and game_start is not None and game_start > previous_stamp)
            ):
                label = f"Game {game['number']} finished"
                if game["map"]:
                    label += f" · {game['map']}"
                record(f"game:{game['id']}", label, stamp, game["score"])
    return _iso(since), list(events.values())


def _window(settings: Any, now_iso: str | None = None) -> Tuple[str, str]:
    now = _parse_iso(now_iso) or _utc_now()
    lookback = max(0, int(getattr(settings, "grid_esports_lookback_days", 2) or 2))
    lookahead = max(1, int(getattr(settings, "grid_esports_lookahead_days", 14) or 14))
    return _iso(now - timedelta(days=lookback)), _iso(now + timedelta(days=lookahead))


def _select_relevant_series(
    nodes: List[Dict[str, Any]],
    *,
    limit: int,
    reference_at: str,
) -> List[Dict[str, Any]]:
    reference = _parse_iso(reference_at) or _utc_now()

    def distance(row: Tuple[int, Dict[str, Any]]) -> Tuple[float, int]:
        index, node = row
        scheduled = _parse_iso(node.get("startTimeScheduled"))
        seconds = abs((scheduled - reference).total_seconds()) if scheduled else float("inf")
        return seconds, index

    ranked = sorted(enumerate(nodes), key=distance)
    return [node for _, node in ranked[: max(1, int(limit or DEFAULT_GRID_ESPORTS_LIMIT))]]


def build_grid_esports_cache_key(settings: Any, *, limit: int = DEFAULT_GRID_ESPORTS_LIMIT) -> str:
    fingerprint = hashlib.sha256(
        "|".join(
            [
                str(getattr(settings, "grid_central_data_graphql_url", "") or ""),
                str(getattr(settings, "grid_series_state_graphql_url", "") or ""),
                str(getattr(settings, "grid_esports_lookback_days", "") or ""),
                str(getattr(settings, "grid_esports_lookahead_days", "") or ""),
            ]
        ).encode("utf-8")
    ).hexdigest()[:12]
    return json.dumps({"limit": int(limit), "source": fingerprint, "version": 2}, sort_keys=True, ensure_ascii=True)


def normalize_grid_esports_payload(payload: Any, *, settings: Any, limit: int = DEFAULT_GRID_ESPORTS_LIMIT, generated_at: str | None = None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)][:limit]
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    if not summary:
        summary = {
            "totalSeries": len(items),
            "liveSeries": sum(1 for item in items if item.get("state") == "live"),
            "officialSnapshots": sum(1 for item in items if item.get("teamMetrics")),
            "pmLinked": sum(1 for item in items if isinstance(item.get("pm"), dict) and item["pm"].get("status") == "matched"),
        }
    return {
        **payload,
        "generatedAt": str(payload.get("generatedAt") or generated_at or ""),
        "source": str(payload.get("source") or "GRID Open Access"),
        "sourceUrl": str(payload.get("sourceUrl") or getattr(settings, "grid_source_url", "") or source_value('POLYDATA_GRID_SOURCE_URL')),
        "status": str(payload.get("status") or ("ok" if items else "empty")),
        "cacheMode": str(payload.get("cacheMode") or ""),
        "sources": payload.get("sources") if isinstance(payload.get("sources"), dict) else {},
        "window": payload.get("window") if isinstance(payload.get("window"), dict) else {},
        "summary": summary,
        "items": items,
    }


def _read_seeded_snapshot(
    dependencies: GridEsportsDependencies,
    *,
    namespace: str,
    cache_key: str,
    ttl_seconds: int,
) -> Optional[Dict[str, Any]]:
    return read_public_seed(
        namespace=namespace, cache_key=cache_key,
        snapshot_store=dependencies.snapshot_store, redis_get=dependencies.get_cached_json,
        max_age_seconds=240, retain_seconds=900,
        now=dependencies.utc_now_iso() if dependencies.utc_now_iso is not None else None,
    )


def fetch_live_grid_esports_payload(
    ctx: GridEsportsContext,
    limit: int = DEFAULT_GRID_ESPORTS_LIMIT,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    deadline = time.monotonic() + 90
    settings = dependencies.settings
    generated_at = _generated_at(dependencies)
    api_key = str(getattr(settings, "grid_api_key", "") or "").strip()
    if not api_key:
        return normalize_grid_esports_payload(
            {
                "generatedAt": generated_at,
                "source": "GRID Open Access",
                "sourceUrl": getattr(settings, "grid_source_url", ""),
                "status": "degraded",
                "sources": _source_status(False, "missing-key", []),
                "items": [],
            },
            settings=settings,
            limit=limit,
            generated_at=generated_at,
        )

    gte, lte = _window(settings, generated_at)
    central_url = str(getattr(settings, "grid_central_data_graphql_url", "") or "").strip()
    if not central_url:
        raise RuntimeError("GRID central data URL is missing")

    candidate_limit = max(DEFAULT_GRID_SERIES_CANDIDATE_LIMIT, int(limit or DEFAULT_GRID_ESPORTS_LIMIT) * 5)
    payload = _post_graphql(
        dependencies,
        central_url,
        NEARBY_SERIES_QUERY,
        {
            "recentGte": gte,
            "now": generated_at,
            "upcomingLte": lte,
            "first": candidate_limit,
        },
        timeout=45, deadline=deadline,
    )
    _raise_graphql_errors(payload)
    recent_nodes, recent_count = _extract_series_nodes(payload, "recent")
    upcoming_nodes, upcoming_count = _extract_series_nodes(payload, "upcoming")
    data = payload["data"] if isinstance(payload.get("data"), dict) else {}
    uses_nearby_windows = "recent" in data and "upcoming" in data
    if not uses_nearby_windows:
        # Compatibility for fixtures and older GraphQL proxies that expose a
        # single allSeries connection.
        nodes, total_count = _extract_series_nodes(payload)
    else:
        nodes_by_id: Dict[str, Dict[str, Any]] = {}
        for node in [*recent_nodes, *upcoming_nodes]:
            series_id = str(node.get("id") or "").strip()
            if series_id:
                nodes_by_id.setdefault(series_id, node)
        nodes = list(nodes_by_id.values())
        total_count = recent_count + upcoming_count
    reference_at = _parse_iso(generated_at) or _utc_now()
    previous = dependencies.previous_payload or {}
    prior_items = {row["id"]: row for row in previous.get("items") or [] if row.get("stateUpdatedAt")}
    selected = _select_relevant_series(nodes, limit=len(nodes), reference_at=generated_at)
    due, upcoming = [], []
    for node in selected:
        if not node.get("id"):
            continue
        scheduled = _parse_iso(node.get("startTimeScheduled"))
        if scheduled and scheduled > reference_at:
            if len(upcoming) < limit:
                upcoming.append(node)
        else:
            due.append(node)
    due.sort(key=lambda node: prior_items.get(str(node["id"]), {}).get("state") != "live")
    due = due[:limit]
    states = _series_states(dependencies, [str(node["id"]) for node in due], deadline=deadline)
    reference_at = _utc_now()
    generated_at = _iso(reference_at)
    items, state_statuses = [], []
    for node in (*due, *upcoming):
        series_id = str(node["id"])
        state, status = states.get(series_id, (None, "not-due"))
        row = _normalize_series(node, state)
        if status == "ok" and not row["stateUpdatedAt"]:
            status = "invalid"
        state_statuses.append(status)
        if status != "ok" and (prior := prior_items.get(series_id)):
            prior_stamp = _parse_iso(prior["stateUpdatedAt"])
            if prior_stamp and reference_at - timedelta(minutes=15) <= prior_stamp <= reference_at:
                row = {**prior, "sourceStatus": "stale"}
        stamp = _parse_iso(row["stateUpdatedAt"])
        if row["state"] == "live" and stamp and reference_at - stamp > timedelta(minutes=8):
            row["sourceStatus"] = "stale"
        if row["teamA"] != "TBD" and row["teamB"] != "TBD":
            items.append(row)

    def display_rank(item: Dict[str, Any]) -> tuple[int, float]:
        phase = {"live": 0, "finished": 1, "upcoming": 2}.get(item["state"], 3)
        stamp = _parse_iso(item["stateUpdatedAt"] or item["startTime"])
        return phase, (stamp.timestamp() if phase == 2 else -stamp.timestamp()) if stamp else 0

    events_since, events = _verified_events(items, previous, reference_at)
    items.sort(key=display_rank)
    items = items[:limit]
    for item in items:
        item["pm"] = _pm_context(dependencies, [item["teamA"], item["teamB"]])
    visible = {item["id"]: item["pm"] for item in items}
    previous_event_ids = {event["id"] for event in previous.get("events") or []}
    for event in events:
        if event["id"] in previous_event_ids:
            continue
        series_id = event["id"].split(":", 1)[0]
        hints = (prior_items.get(series_id, {}).get("pm", {}), visible.get(series_id, {}))
        tried = set()
        for hint in hints:
            if not (slug := hint.get("slug")) or slug in tried or deadline - time.monotonic() < 3:
                continue
            tried.add(slug)
            if market := _verified_market_context(dependencies, event, hint, timeout=3):
                event["polymarket"] = market
                break
    live_count = sum(item["state"] == "live" and item["sourceStatus"] == "ok" for item in items)
    state_failures = [state for state in state_statuses if state not in {"ok", "not-due"}]
    status = "degraded" if state_failures else "ok" if items else "empty"
    return normalize_grid_esports_payload(
        {
            "generatedAt": generated_at,
            "source": "GRID Open Access",
            "sourceUrl": getattr(settings, "grid_source_url", ""),
            "status": status,
            "sources": _source_status(True, "ok", state_statuses),
            "window": {"gte": gte, "lte": lte},
            "eventsSince": events_since,
            "events": events,
            "summary": {
                "totalSeries": total_count or len(items),
                "visibleSeries": len(items),
                "liveSeries": live_count,
                "officialSnapshots": sum(1 for item in items if item["sourceStatus"] == "ok"),
                "pmLinked": sum(1 for item in items if isinstance(item.get("pm"), dict) and item["pm"].get("status") == "matched"),
            },
            "items": items,
        },
        settings=settings,
        limit=limit,
        generated_at=generated_at,
    )


def _get_legacy_grid_esports_snapshot(
    ctx: GridEsportsContext,
    limit: int = DEFAULT_GRID_ESPORTS_LIMIT,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    settings = dependencies.settings
    ttl_seconds = max(30, int(getattr(settings, "grid_esports_ttl_seconds", 120) or 120))
    cache_key = build_grid_esports_cache_key(settings, limit=limit)
    seeded = _read_seeded_snapshot(dependencies, namespace=GRID_ESPORTS_NAMESPACE, cache_key=cache_key, ttl_seconds=ttl_seconds)
    if seeded is None and int(limit or 0) != DEFAULT_GRID_ESPORTS_LIMIT:
        seeded = _read_seeded_snapshot(
            dependencies,
            namespace=GRID_ESPORTS_NAMESPACE,
            cache_key=build_grid_esports_cache_key(settings, limit=DEFAULT_GRID_ESPORTS_LIMIT),
            ttl_seconds=ttl_seconds,
        )
    if seeded is not None:
        return normalize_grid_esports_payload(
            seeded,
            settings=settings,
            limit=limit,
            generated_at=(
                str(dependencies.utc_now_iso())
                if dependencies.utc_now_iso is not None
                else ""
            ),
        )

    return {"items": [], "generatedAt": "", "status": "warming", "cacheMode": "warming"}


def get_grid_esports_snapshot(ctx: GridEsportsContext, limit: int = DEFAULT_GRID_ESPORTS_LIMIT) -> Dict[str, Any]:
    from api.services.bookmaker_panels.snapshot_service import attach_board
    return attach_board(_dependencies(ctx).snapshot_store, _get_legacy_grid_esports_snapshot(ctx, limit), game=True)
