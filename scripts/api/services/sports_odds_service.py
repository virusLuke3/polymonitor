from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional

from api.context import (
    resolve_optional_service_callable,
    resolve_optional_service_value,
    resolve_service_callable,
    resolve_service_value,
)

SPORTS_ODDS_NAMESPACE = "snapshot:sports:sports-odds"
DEFAULT_SPORTS_ODDS_LIMIT = 8


@dataclass(frozen=True)
class SportsOddsDependencies:
    settings: Any
    application: Any
    search_markets: Callable[..., Any] | None
    get_cached_json: Callable[..., Any] | None
    set_cached_json: Callable[..., Any] | None
    snapshot_store: Any
    utc_now_iso: Callable[..., Any] | None
    http_json_get: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> SportsOddsDependencies:
        return cls(
            settings=resolve_service_value(context, "SETTINGS"),
            application=resolve_optional_service_value(context, "app"),
            search_markets=resolve_optional_service_callable(
                context,
                "search_markets",
            ),
            get_cached_json=resolve_optional_service_callable(
                context,
                "get_cached_json",
            ),
            set_cached_json=resolve_optional_service_callable(
                context,
                "set_cached_json",
            ),
            snapshot_store=resolve_optional_service_value(
                context,
                "SNAPSHOT_STORE",
            ),
            utc_now_iso=resolve_optional_service_callable(
                context,
                "utc_now_iso",
            ),
            http_json_get=resolve_service_callable(
                context,
                "http_json_get",
            ),
        )


SportsOddsContext = Mapping[str, Any] | SportsOddsDependencies


def _dependencies(
    context: SportsOddsContext,
) -> SportsOddsDependencies:
    if isinstance(context, SportsOddsDependencies):
        return context
    return SportsOddsDependencies.from_context(context)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _generated_at(dependencies: SportsOddsDependencies) -> str:
    if dependencies.utc_now_iso is not None:
        return str(dependencies.utc_now_iso())
    return _utc_now_iso()


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and number > 0 else None


def _mean(values: Iterable[float]) -> Optional[float]:
    rows = [value for value in values if math.isfinite(value)]
    return sum(rows) / len(rows) if rows else None


def _stdev(values: Iterable[float]) -> Optional[float]:
    rows = [value for value in values if math.isfinite(value)]
    if len(rows) < 2:
        return 0.0 if rows else None
    avg = sum(rows) / len(rows)
    return math.sqrt(sum((value - avg) ** 2 for value in rows) / len(rows))


def _headers() -> Dict[str, str]:
    return {"Accept": "application/json", "User-Agent": "polydata-runtime/1.0"}


def _pm_context(
    ctx: SportsOddsContext,
    event_name: str,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    settings = dependencies.settings
    if not bool(getattr(settings, "sports_odds_pm_search_enabled", False)):
        return {"status": "not-matched", "probability": None, "delta": None, "signal": "PM SEARCH OFF", "matchQuality": "none"}
    search = dependencies.search_markets
    if search is None:
        return {"status": "not-matched", "probability": None, "delta": None, "signal": "NO PM MATCH", "matchQuality": "none"}
    try:
        matches = search(event_name, limit=3)
    except Exception:
        return {"status": "error", "probability": None, "delta": None, "signal": "PM SEARCH ERR", "matchQuality": "low"}
    rows = matches.get("items") if isinstance(matches, dict) else matches
    if not isinstance(rows, list) or not rows:
        return {"status": "not-matched", "probability": None, "delta": None, "signal": "NO PM MATCH", "matchQuality": "none"}
    market = rows[0] if isinstance(rows[0], dict) else {}
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


def _h2h_quotes(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    quotes: Dict[str, Dict[str, Any]] = {}
    for bookmaker in event.get("bookmakers") or []:
        if not isinstance(bookmaker, dict):
            continue
        bookmaker_title = str(bookmaker.get("title") or bookmaker.get("key") or "Book").strip()
        last_update = bookmaker.get("last_update")
        for market in bookmaker.get("markets") or []:
            if not isinstance(market, dict) or market.get("key") != "h2h":
                continue
            for outcome in market.get("outcomes") or []:
                if not isinstance(outcome, dict):
                    continue
                name = str(outcome.get("name") or "").strip()
                price = _safe_float(outcome.get("price"))
                if not name or price is None:
                    continue
                bucket = quotes.setdefault(name, {"name": name, "prices": [], "books": []})
                bucket["prices"].append(price)
                bucket["books"].append({"bookmaker": bookmaker_title, "price": price, "lastUpdate": last_update})
    rows: List[Dict[str, Any]] = []
    for bucket in quotes.values():
        prices = [float(price) for price in bucket["prices"]]
        implied = [1 / price for price in prices if price > 0]
        rows.append(
            {
                "name": bucket["name"],
                "bestPrice": max(prices) if prices else None,
                "consensusProbability": _mean(implied),
                "dispersion": _stdev(implied),
                "bookCount": len(prices),
                "books": sorted(bucket["books"], key=lambda item: float(item.get("price") or 0), reverse=True)[:4],
            }
        )
    rows.sort(key=lambda row: float(row.get("consensusProbability") or 0), reverse=True)
    return rows


def _normalize_event(
    ctx: SportsOddsContext,
    event: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    event_id = str(event.get("id") or "").strip()
    home = str(event.get("home_team") or "").strip()
    away = str(event.get("away_team") or "").strip()
    if not event_id or not (home or away):
        return None
    event_name = f"{away or 'Away'} @ {home or 'Home'}"
    quotes = _h2h_quotes(event)
    consensus_values = [float(row["consensusProbability"]) for row in quotes if row.get("consensusProbability") is not None]
    dispersion_values = [float(row["dispersion"]) for row in quotes if row.get("dispersion") is not None]
    consensus = _mean(consensus_values)
    dispersion = max(dispersion_values) if dispersion_values else None
    pm = _pm_context(ctx, event_name)
    delta = float(pm["probability"]) - consensus if consensus is not None and pm.get("probability") is not None else None
    signal = "WATCH" if delta is None else "PM RICH" if delta > 0.04 else "PM CHEAP" if delta < -0.04 else "IN LINE"
    bookmakers = [book for book in event.get("bookmakers") or [] if isinstance(book, dict)]
    return {
        "id": event_id,
        "sportKey": event.get("sport_key"),
        "sportTitle": event.get("sport_title") or event.get("sport_key"),
        "commenceTime": event.get("commence_time"),
        "homeTeam": home,
        "awayTeam": away,
        "event": event_name,
        "marketType": "h2h",
        "bookmakerCount": len(bookmakers),
        "bestPrice": max((float(row.get("bestPrice") or 0) for row in quotes), default=None),
        "consensusProbability": consensus,
        "dispersion": dispersion,
        "quotes": quotes[:4],
        "pm": {**pm, "delta": delta},
        "signal": signal,
        "lastUpdate": max((str(book.get("last_update") or "") for book in bookmakers), default=None),
    }


def build_sports_odds_cache_key(settings: Any, *, limit: int = DEFAULT_SPORTS_ODDS_LIMIT) -> str:
    fingerprint = hashlib.sha256(
        "|".join(
            [
                str(getattr(settings, "the_odds_api_base_url", "") or ""),
                str(getattr(settings, "sports_odds_sport_key", "") or ""),
                str(getattr(settings, "sports_odds_regions", "") or ""),
                str(getattr(settings, "sports_odds_markets", "") or ""),
            ]
        ).encode("utf-8")
    ).hexdigest()[:12]
    return json.dumps({"limit": int(limit), "source": fingerprint, "version": 1}, sort_keys=True, ensure_ascii=True)


def normalize_sports_odds_payload(payload: Any, *, settings: Any, limit: int, generated_at: str | None = None) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)][:limit]
    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    if not summary:
        summary = {
            "eventCount": len(items),
            "bookmakerCount": max((int(item.get("bookmakerCount") or 0) for item in items), default=0),
            "pmLinked": sum(1 for item in items if isinstance(item.get("pm"), dict) and item["pm"].get("status") == "matched"),
            "wideCount": sum(1 for item in items if float(item.get("dispersion") or 0) >= 0.04),
        }
    return {
        **payload,
        "generatedAt": str(payload.get("generatedAt") or generated_at or ""),
        "source": str(payload.get("source") or "The Odds API"),
        "sourceUrl": str(payload.get("sourceUrl") or getattr(settings, "the_odds_source_url", "") or "https://the-odds-api.com/"),
        "status": str(payload.get("status") or ("ok" if items else "empty")),
        "cacheMode": str(payload.get("cacheMode") or ""),
        "sources": payload.get("sources") if isinstance(payload.get("sources"), dict) else {},
        "summary": summary,
        "items": items,
    }


def _with_cache_mode(payload: Dict[str, Any], cache_mode: str) -> Dict[str, Any]:
    return {**payload, "cacheMode": str(payload.get("cacheMode") or cache_mode)}


def _read_seeded_snapshot(
    dependencies: SportsOddsDependencies,
    *,
    namespace: str,
    cache_key: str,
    ttl_seconds: int,
) -> Optional[Dict[str, Any]]:
    reader = dependencies.get_cached_json
    if reader is not None:
        redis_payload = reader(namespace, cache_key)
        if isinstance(redis_payload, dict):
            store = dependencies.snapshot_store
            if store is not None:
                store.set(namespace, cache_key, redis_payload, ttl_seconds)
            return _with_cache_mode(redis_payload, "redis-seed")
    store = dependencies.snapshot_store
    if store is None:
        return None
    sqlite_payload = store.get(namespace, cache_key)
    if isinstance(sqlite_payload, dict):
        return _with_cache_mode(sqlite_payload, "sqlite-seed")
    stale_payload = store.get_stale(namespace, cache_key)
    if isinstance(stale_payload, dict):
        return _with_cache_mode(stale_payload, "stale-seed")
    return None


def _store_seed_fallback(
    dependencies: SportsOddsDependencies,
    *,
    namespace: str,
    cache_key: str,
    payload: Dict[str, Any],
    ttl_seconds: int,
) -> Dict[str, Any]:
    store = dependencies.snapshot_store
    if store is not None:
        store.set(namespace, cache_key, payload, ttl_seconds)
    setter = dependencies.set_cached_json
    if setter is not None:
        setter(namespace, cache_key, payload, ttl_seconds)
    return payload


def fetch_live_sports_odds_payload(
    ctx: SportsOddsContext,
    limit: int = DEFAULT_SPORTS_ODDS_LIMIT,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    settings = dependencies.settings
    generated_at = _generated_at(dependencies)
    api_key = str(getattr(settings, "the_odds_api_key", "") or "").strip()
    if not api_key:
        return normalize_sports_odds_payload(
            {"generatedAt": generated_at, "status": "degraded", "sources": {"theOddsApi": "missing-key", "polymarket": "optional-local-match"}, "items": []},
            settings=settings,
            limit=limit,
            generated_at=generated_at,
        )
    url = f"{str(getattr(settings, 'the_odds_api_base_url', '') or 'https://api.the-odds-api.com').rstrip('/')}/v4/sports/{getattr(settings, 'sports_odds_sport_key', 'upcoming')}/odds/"
    params = {
        "apiKey": api_key,
        "regions": str(getattr(settings, "sports_odds_regions", "us") or "us"),
        "markets": str(getattr(settings, "sports_odds_markets", "h2h") or "h2h"),
        "oddsFormat": "decimal",
        "dateFormat": "iso",
    }
    payload = dependencies.http_json_get(url, params=params, timeout=12, headers=_headers())
    events = payload if isinstance(payload, list) else []
    items = [
        item
        for event in events
        if isinstance(event, dict)
        for item in [_normalize_event(dependencies, event)]
        if item is not None
    ]
    items.sort(
        key=lambda item: (item.get("signal") in {"PM RICH", "PM CHEAP"}, float(item.get("dispersion") or 0), int(item.get("bookmakerCount") or 0)),
        reverse=True,
    )
    return normalize_sports_odds_payload(
        {
            "generatedAt": generated_at,
            "status": "ok" if items else "empty",
            "sources": {"theOddsApi": "ok", "polymarket": "optional-local-match"},
            "items": items[:limit],
        },
        settings=settings,
        limit=limit,
        generated_at=generated_at,
    )


def _safe_live_sports_odds_payload(
    ctx: SportsOddsContext,
    *,
    limit: int,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    try:
        return fetch_live_sports_odds_payload(dependencies, limit=limit)
    except Exception as exc:
        logger = getattr(dependencies.application, "logger", None)
        if logger is not None:
            logger.exception("sports odds live fallback failed")
        settings = dependencies.settings
        generated_at = _generated_at(dependencies)
        return normalize_sports_odds_payload(
            {"generatedAt": generated_at, "status": "degraded", "sources": {"theOddsApi": "error", "polymarket": "optional-local-match"}, "error": str(exc)[:240], "items": []},
            settings=settings,
            limit=limit,
            generated_at=generated_at,
        )


def get_sports_odds_snapshot(
    ctx: SportsOddsContext,
    limit: int = DEFAULT_SPORTS_ODDS_LIMIT,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    settings = dependencies.settings
    ttl_seconds = max(30, int(getattr(settings, "sports_odds_ttl_seconds", 180) or 180))
    cache_key = build_sports_odds_cache_key(settings, limit=limit)
    seeded = _read_seeded_snapshot(dependencies, namespace=SPORTS_ODDS_NAMESPACE, cache_key=cache_key, ttl_seconds=ttl_seconds)
    if seeded is None and int(limit or 0) != DEFAULT_SPORTS_ODDS_LIMIT:
        seeded = _read_seeded_snapshot(dependencies, namespace=SPORTS_ODDS_NAMESPACE, cache_key=build_sports_odds_cache_key(settings, limit=DEFAULT_SPORTS_ODDS_LIMIT), ttl_seconds=ttl_seconds)
    if seeded is not None:
        return normalize_sports_odds_payload(
            seeded,
            settings=settings,
            limit=limit,
            generated_at=(
                str(dependencies.utc_now_iso())
                if dependencies.utc_now_iso is not None
                else ""
            ),
        )
    payload = _with_cache_mode(_safe_live_sports_odds_payload(dependencies, limit=limit), "live-build")
    if payload.get("items"):
        return _store_seed_fallback(dependencies, namespace=SPORTS_ODDS_NAMESPACE, cache_key=cache_key, payload=payload, ttl_seconds=ttl_seconds)
    return payload
