from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple


GRID_ESPORTS_NAMESPACE = "snapshot:esports:esports-intel"
DEFAULT_GRID_ESPORTS_LIMIT = 10
DEFAULT_GRID_PM_SEARCH_LIMIT = 12

ALL_SERIES_QUERY = """
query EsportsIntelSeries($gte: String!, $lte: String!) {
  allSeries(
    filter: { startTimeScheduled: { gte: $gte, lte: $lte } }
    orderBy: StartTimeScheduled
  ) {
    totalCount
    edges {
      node {
        id
        startTimeScheduled
        teams { baseInfo { id name logoUrl } }
        tournament { id name }
        title { id nameShortened }
      }
    }
  }
}
"""

SERIES_STATE_QUERY = """
query EsportsIntelSeriesState($id: ID!) {
  seriesState(id: $id) {
    startedAt
    started
    finished
    teams {
      won
      score
      kills
      deaths
      players { kills deaths }
    }
  }
}
"""


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
    return {
        "gridCentralData": central_status if has_key else "missing-key",
        "gridSeriesState": "ok" if any(status == "ok" for status in states) else ("empty" if states else "not-queried"),
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


def _post_graphql(ctx: dict, url: str, query: str, variables: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
    poster = ctx.get("http_json_post")
    if callable(poster):
        payload = poster(url, {"query": query, "variables": variables}, timeout=timeout, headers=_graphql_headers(ctx["SETTINGS"]))
        if isinstance(payload, dict):
            return payload
        raise RuntimeError("GRID GraphQL returned non-object payload")

    requests = ctx.get("requests")
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
            headers=_graphql_headers(ctx["SETTINGS"]),
        )
        response.raise_for_status()
        payload = response.json()
    finally:
        if close_client:
            client.close()
    if not isinstance(payload, dict):
        raise RuntimeError("GRID GraphQL returned non-object payload")
    return payload


def _raise_graphql_errors(payload: Dict[str, Any]) -> None:
    errors = payload.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        message = str(first.get("message") or "GRID GraphQL error")
        raise RuntimeError(message)


def _extract_series_nodes(payload: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
    all_series = (payload.get("data") or {}).get("allSeries") if isinstance(payload.get("data"), dict) else None
    if not isinstance(all_series, dict):
        return [], 0
    total_count = _safe_int(all_series.get("totalCount")) or 0
    nodes: List[Dict[str, Any]] = []
    for edge in all_series.get("edges") or []:
        node = edge.get("node") if isinstance(edge, dict) else None
        if isinstance(node, dict):
            nodes.append(node)
    return nodes, total_count


def _team_names(node: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for team in node.get("teams") or []:
        if not isinstance(team, dict):
            continue
        base_info = team.get("baseInfo") if isinstance(team.get("baseInfo"), dict) else {}
        name = str(base_info.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _state_team_metrics(state: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    rows: List[Dict[str, Any]] = []
    for team in state.get("teams") or []:
        if not isinstance(team, dict):
            continue
        players = [player for player in (team.get("players") or []) if isinstance(player, dict)]
        player_kills = sum(_safe_int(player.get("kills")) or 0 for player in players)
        player_deaths = sum(_safe_int(player.get("deaths")) or 0 for player in players)
        rows.append(
            {
                "won": bool(team.get("won")),
                "score": _safe_int(team.get("score")) or 0,
                "kills": _safe_int(team.get("kills")) if _safe_int(team.get("kills")) is not None else player_kills,
                "deaths": _safe_int(team.get("deaths")) if _safe_int(team.get("deaths")) is not None else player_deaths,
            }
        )
    return rows


def _momentum_score(metrics: List[Dict[str, Any]]) -> int:
    if len(metrics) < 2:
        return 50
    left = (_safe_int(metrics[0].get("kills")) or 0) - (_safe_int(metrics[0].get("deaths")) or 0) + (_safe_int(metrics[0].get("score")) or 0) * 3
    right = (_safe_int(metrics[1].get("kills")) or 0) - (_safe_int(metrics[1].get("deaths")) or 0) + (_safe_int(metrics[1].get("score")) or 0) * 3
    diff = left - right
    return max(1, min(99, 50 + diff * 4))


def _score_label(metrics: List[Dict[str, Any]]) -> str:
    if len(metrics) < 2:
        return "--"
    return f"{metrics[0].get('score', 0)}-{metrics[1].get('score', 0)}"


def _context_tags(status: str, metrics: List[Dict[str, Any]], state: Optional[Dict[str, Any]]) -> List[str]:
    tags = [status.upper()]
    if isinstance(state, dict) and state.get("startedAt"):
        tags.append("STATE")
    if len(metrics) >= 2:
        kill_diff = (_safe_int(metrics[0].get("kills")) or 0) - (_safe_int(metrics[1].get("kills")) or 0)
        if kill_diff > 8:
            tags.append("A KILL EDGE")
        elif kill_diff < -8:
            tags.append("B KILL EDGE")
        elif abs(kill_diff) > 0:
            tags.append("KILLS EVEN")
    return tags[:4]


def _series_state(ctx: dict, series_id: str) -> Tuple[Optional[Dict[str, Any]], str]:
    settings = ctx["SETTINGS"]
    url = str(getattr(settings, "grid_series_state_graphql_url", "") or "").strip()
    if not url:
        return None, "missing-url"
    try:
        payload = _post_graphql(ctx, url, SERIES_STATE_QUERY, {"id": series_id}, timeout=12)
        _raise_graphql_errors(payload)
        state = (payload.get("data") or {}).get("seriesState") if isinstance(payload.get("data"), dict) else None
        return state if isinstance(state, dict) else None, "ok" if isinstance(state, dict) else "empty"
    except Exception:
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.exception("GRID series state fetch failed series_id=%s", series_id)
        return None, "error"


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


def _pm_context(ctx: dict, team_names: List[str]) -> Dict[str, Any]:
    settings = ctx.get("SETTINGS")
    if not bool(getattr(settings, "grid_esports_pm_search_enabled", False)):
        return {"status": "not-matched", "probability": None, "delta": None, "signal": "PM SEARCH OFF", "matchQuality": "none"}
    search = ctx.get("search_markets")
    if not callable(search) or len(team_names) < 2:
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
        "title": market.get("title"),
        "probability": price,
        "delta": None,
        "signal": "PM LINKED" if price is not None else "PM MATCH",
        "matchQuality": "medium",
    }


def _normalize_series(node: Dict[str, Any], state: Optional[Dict[str, Any]], *, ctx: dict) -> Dict[str, Any]:
    team_names = _team_names(node)
    title = node.get("title") if isinstance(node.get("title"), dict) else {}
    tournament = node.get("tournament") if isinstance(node.get("tournament"), dict) else {}
    metrics = _state_team_metrics(state)
    status = _status_from_state(state, node.get("startTimeScheduled"))
    momentum = _momentum_score(metrics)
    game_title = str(title.get("nameShortened") or title.get("name") or "ESPORTS").upper()
    team_a = team_names[0] if len(team_names) >= 1 else "TBD"
    team_b = team_names[1] if len(team_names) >= 2 else "TBD"
    return {
        "id": str(node.get("id") or ""),
        "gameTitle": game_title,
        "tournament": str(tournament.get("name") or "GRID Series"),
        "series": f"{team_a} vs {team_b}",
        "teamA": team_a,
        "teamB": team_b,
        "format": "BO?",
        "startTime": node.get("startTimeScheduled"),
        "startedAt": state.get("startedAt") if isinstance(state, dict) else None,
        "state": status,
        "score": _score_label(metrics),
        "currentMap": "series",
        "liveContext": "Official state snapshot" if state else "Series metadata only",
        "momentum": momentum,
        "contextTags": _context_tags(status, metrics, state),
        "teamMetrics": metrics,
        "pm": _pm_context(ctx, team_names),
    }


def _window(settings: Any, now_iso: str | None = None) -> Tuple[str, str]:
    now = _parse_iso(now_iso) or _utc_now()
    lookback = max(0, int(getattr(settings, "grid_esports_lookback_days", 2) or 2))
    lookahead = max(1, int(getattr(settings, "grid_esports_lookahead_days", 14) or 14))
    return _iso(now - timedelta(days=lookback)), _iso(now + timedelta(days=lookahead))


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
    return json.dumps({"limit": int(limit), "source": fingerprint, "version": 1}, sort_keys=True, ensure_ascii=True)


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
        "sourceUrl": str(payload.get("sourceUrl") or getattr(settings, "grid_source_url", "") or "https://grid.gg/open-access/"),
        "status": str(payload.get("status") or ("ok" if items else "empty")),
        "cacheMode": str(payload.get("cacheMode") or ""),
        "sources": payload.get("sources") if isinstance(payload.get("sources"), dict) else {},
        "window": payload.get("window") if isinstance(payload.get("window"), dict) else {},
        "summary": summary,
        "items": items,
    }


def _with_cache_mode(payload: Dict[str, Any], cache_mode: str) -> Dict[str, Any]:
    return {**payload, "cacheMode": str(payload.get("cacheMode") or cache_mode)}


def _read_seeded_snapshot(ctx: dict, *, namespace: str, cache_key: str, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    reader = ctx.get("get_cached_json")
    if callable(reader):
        redis_payload = reader(namespace, cache_key)
        if isinstance(redis_payload, dict):
            store = ctx.get("SNAPSHOT_STORE")
            if store is not None:
                store.set(namespace, cache_key, redis_payload, ttl_seconds)
            return _with_cache_mode(redis_payload, "redis-seed")
    store = ctx.get("SNAPSHOT_STORE")
    if store is None:
        return None
    sqlite_payload = store.get(namespace, cache_key)
    if isinstance(sqlite_payload, dict):
        setter = ctx.get("set_cached_json")
        if callable(setter):
            setter(namespace, cache_key, sqlite_payload, ttl_seconds)
        return _with_cache_mode(sqlite_payload, "sqlite-seed")
    stale_payload = store.get_stale(namespace, cache_key)
    if isinstance(stale_payload, dict):
        setter = ctx.get("set_cached_json")
        if callable(setter):
            setter(namespace, cache_key, stale_payload, min(15, ttl_seconds))
        return _with_cache_mode(stale_payload, "stale-seed")
    return None


def _store_seed_fallback(ctx: dict, *, namespace: str, cache_key: str, payload: Dict[str, Any], ttl_seconds: int) -> Dict[str, Any]:
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        store.set(namespace, cache_key, payload, ttl_seconds)
    setter = ctx.get("set_cached_json")
    if callable(setter):
        setter(namespace, cache_key, payload, ttl_seconds)
    return payload


def fetch_live_grid_esports_payload(ctx: dict, limit: int = DEFAULT_GRID_ESPORTS_LIMIT) -> Dict[str, Any]:
    settings = ctx["SETTINGS"]
    generated_at = ctx.get("utc_now_iso", lambda: _iso(_utc_now()))()
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

    payload = _post_graphql(ctx, central_url, ALL_SERIES_QUERY, {"gte": gte, "lte": lte}, timeout=20)
    _raise_graphql_errors(payload)
    nodes, total_count = _extract_series_nodes(payload)
    selected = nodes[: max(1, int(limit or DEFAULT_GRID_ESPORTS_LIMIT))]
    state_statuses: List[str] = []
    items: List[Dict[str, Any]] = []
    for node in selected:
        series_id = str(node.get("id") or "").strip()
        state, state_status = _series_state(ctx, series_id) if series_id else (None, "missing-id")
        state_statuses.append(state_status)
        items.append(_normalize_series(node, state, ctx=ctx))

    live_count = sum(1 for item in items if item.get("state") == "live")
    status = "ok" if items and all(status == "ok" for status in state_statuses) else "degraded" if items else "empty"
    return normalize_grid_esports_payload(
        {
            "generatedAt": generated_at,
            "source": "GRID Open Access",
            "sourceUrl": getattr(settings, "grid_source_url", ""),
            "status": status,
            "sources": _source_status(True, "ok", state_statuses),
            "window": {"gte": gte, "lte": lte},
            "summary": {
                "totalSeries": total_count or len(items),
                "visibleSeries": len(items),
                "liveSeries": live_count,
                "officialSnapshots": sum(1 for item in items if item.get("teamMetrics")),
                "pmLinked": sum(1 for item in items if isinstance(item.get("pm"), dict) and item["pm"].get("status") == "matched"),
            },
            "items": items,
        },
        settings=settings,
        limit=limit,
        generated_at=generated_at,
    )


def _degraded_error_payload(ctx: dict, *, limit: int, error: Exception) -> Dict[str, Any]:
    settings = ctx["SETTINGS"]
    generated_at = ctx.get("utc_now_iso", lambda: _iso(_utc_now()))()
    message = str(error).strip()
    return normalize_grid_esports_payload(
        {
            "generatedAt": generated_at,
            "source": "GRID Open Access",
            "sourceUrl": getattr(settings, "grid_source_url", ""),
            "status": "degraded",
            "sources": {
                "gridCentralData": "error",
                "gridSeriesState": "not-queried",
                "polymarket": "optional-local-match",
            },
            "error": message[:240],
            "items": [],
        },
        settings=settings,
        limit=limit,
        generated_at=generated_at,
    )


def _safe_live_grid_esports_payload(ctx: dict, *, limit: int) -> Dict[str, Any]:
    try:
        return fetch_live_grid_esports_payload(ctx, limit=limit)
    except Exception as exc:
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.exception("GRID esports live fallback failed")
        return _degraded_error_payload(ctx, limit=limit, error=exc)


def get_grid_esports_snapshot(ctx: dict, limit: int = DEFAULT_GRID_ESPORTS_LIMIT) -> Dict[str, Any]:
    settings = ctx["SETTINGS"]
    ttl_seconds = max(30, int(getattr(settings, "grid_esports_ttl_seconds", 120) or 120))
    cache_key = build_grid_esports_cache_key(settings, limit=limit)
    seeded = _read_seeded_snapshot(ctx, namespace=GRID_ESPORTS_NAMESPACE, cache_key=cache_key, ttl_seconds=ttl_seconds)
    if seeded is None and int(limit or 0) != DEFAULT_GRID_ESPORTS_LIMIT:
        seeded = _read_seeded_snapshot(
            ctx,
            namespace=GRID_ESPORTS_NAMESPACE,
            cache_key=build_grid_esports_cache_key(settings, limit=DEFAULT_GRID_ESPORTS_LIMIT),
            ttl_seconds=ttl_seconds,
        )
    if seeded is not None:
        return normalize_grid_esports_payload(seeded, settings=settings, limit=limit, generated_at=ctx.get("utc_now_iso", lambda: "")())

    def _builder() -> Dict[str, Any]:
        return _safe_live_grid_esports_payload(ctx, limit=limit)

    if ctx.get("SNAPSHOT_STORE") is None and callable(ctx.get("get_snapshot_payload")):
        return ctx["get_snapshot_payload"](GRID_ESPORTS_NAMESPACE, cache_key, _builder, ttl_seconds=ttl_seconds)

    payload = _with_cache_mode(_safe_live_grid_esports_payload(ctx, limit=limit), "live-build")
    if payload.get("items"):
        return _store_seed_fallback(ctx, namespace=GRID_ESPORTS_NAMESPACE, cache_key=cache_key, payload=payload, ttl_seconds=ttl_seconds)
    return payload
