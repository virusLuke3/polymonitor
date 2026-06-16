from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote


PANEL_ID = "breaking-event-radar"
BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE = "snapshot:evidence:breaking-event-radar"
BREAKING_EVENT_RADAR_CACHE_KEY = "panel-v1"
DEFAULT_LIMIT = 12
DEFAULT_TTL_SECONDS = 300
GDELT_DOC_API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
WIKIMEDIA_PAGEVIEWS_BASE_URL = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org/all-access/user"

_LIVE_REFRESH_LOCK = threading.Lock()
_LIVE_REFRESHING: set[str] = set()

DEFAULT_TOPIC_SEEDS: List[Dict[str, Any]] = [
    {
        "id": "iran-geopolitics",
        "topic": "geopolitics",
        "entity": "Iran",
        "country": "Iran",
        "query": '(Iran OR Tehran) (missile OR nuclear OR sanctions OR attack OR conflict)',
        "wikiTitles": ["Iran", "Iran_nuclear_deal_framework"],
    },
    {
        "id": "us-politics",
        "topic": "politics",
        "entity": "US Politics",
        "country": "United States",
        "query": '("United States" OR Washington) (election OR senate OR congress OR president OR campaign)',
        "wikiTitles": ["Politics_of_the_United_States", "2026_United_States_elections"],
    },
    {
        "id": "geopolitical-risk",
        "topic": "geopolitics",
        "entity": "Geopolitical Risk",
        "country": "Global",
        "query": '(war OR ceasefire OR invasion OR sanctions OR military) (risk OR crisis OR talks OR strike)',
        "wikiTitles": ["Geopolitics", "International_sanctions"],
    },
    {
        "id": "world-cup",
        "topic": "world-cup",
        "entity": "World Cup 2026",
        "country": "Global",
        "query": '("World Cup 2026" OR "FIFA World Cup") (schedule OR team OR venue OR injury OR weather)',
        "wikiTitles": ["2026_FIFA_World_Cup", "FIFA_World_Cup"],
    },
    {
        "id": "crypto-policy",
        "topic": "crypto",
        "entity": "Crypto Policy",
        "country": "Global",
        "query": '(bitcoin OR crypto OR stablecoin OR ethereum) (ETF OR regulation OR SEC OR treasury)',
        "wikiTitles": ["Cryptocurrency", "Bitcoin"],
    },
    {
        "id": "extreme-weather",
        "topic": "weather",
        "entity": "Extreme Weather",
        "country": "Global",
        "query": '(hurricane OR flood OR wildfire OR heatwave OR storm) (warning OR damage OR forecast OR emergency)',
        "wikiTitles": ["Extreme_weather", "Tropical_cyclone"],
    },
]


def _utc_now_iso(ctx: dict | None = None) -> str:
    if ctx:
        getter = ctx.get("utc_now_iso")
        if callable(getter):
            return getter()
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    candidates = [
        text.replace("Z", "+00:00"),
        text[:4] + "-" + text[4:6] + "-" + text[6:8] + "T" + text[8:10] + ":" + text[10:12] + ":" + text[12:14] + "+00:00"
        if re.fullmatch(r"\d{14}", text)
        else "",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _timestamp(value: Any) -> float:
    parsed = _parse_iso(value)
    return parsed.timestamp() if parsed else 0.0


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(part or "").strip().lower() for part in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _load_topic_seeds() -> List[Dict[str, Any]]:
    raw = os.environ.get("POLYDATA_BREAKING_EVENT_TOPICS_JSON", "").strip()
    if raw:
        try:
            decoded = json.loads(raw)
            if isinstance(decoded, list):
                rows = [row for row in decoded if isinstance(row, dict) and row.get("query")]
                if rows:
                    return rows
        except Exception:
            pass
    return DEFAULT_TOPIC_SEEDS


def _gdelt_url(ctx: dict) -> str:
    settings = ctx.get("SETTINGS")
    return str(
        os.environ.get("POLYDATA_BREAKING_EVENT_GDELT_DOC_API_URL")
        or getattr(settings, "breaking_event_gdelt_doc_api_url", "")
        or GDELT_DOC_API_URL
    ).strip()


def _wikimedia_base_url(ctx: dict) -> str:
    settings = ctx.get("SETTINGS")
    return str(
        os.environ.get("POLYDATA_BREAKING_EVENT_WIKIMEDIA_PAGEVIEWS_BASE_URL")
        or getattr(settings, "breaking_event_wikimedia_pageviews_base_url", "")
        or WIKIMEDIA_PAGEVIEWS_BASE_URL
    ).rstrip("/")


def _fetch_gdelt_articles(ctx: dict, seed: Dict[str, Any], *, max_records: int) -> List[Dict[str, Any]]:
    getter = ctx.get("http_json_get")
    if not callable(getter):
        raise RuntimeError("http_json_get helper missing")
    payload = getter(
        _gdelt_url(ctx),
        params={
            "query": str(seed.get("query") or ""),
            "mode": "artlist",
            "format": "json",
            "maxrecords": max(1, min(max_records, 50)),
            "sort": "hybridrel",
        },
        timeout=12,
        headers={"Accept": "application/json", "User-Agent": "polydata-breaking-event-radar/1.0"},
    )
    articles = payload.get("articles") if isinstance(payload, dict) else []
    return [row for row in articles if isinstance(row, dict)]


def _fetch_pageviews(ctx: dict, title: str, *, days: int = 7) -> Dict[str, Any]:
    getter = ctx.get("http_json_get")
    if not callable(getter):
        raise RuntimeError("http_json_get helper missing")
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=max(2, days))
    encoded_title = quote(str(title or "").replace(" ", "_"), safe="")
    url = f"{_wikimedia_base_url(ctx)}/{encoded_title}/daily/{start:%Y%m%d}/{end:%Y%m%d}"
    timeout = max(2, min(int(os.environ.get("POLYDATA_BREAKING_EVENT_WIKIMEDIA_TIMEOUT_SECONDS", "4") or 4), 12))
    payload = getter(url, timeout=timeout, headers={"Accept": "application/json", "User-Agent": "polydata-breaking-event-radar/1.0"})
    items = payload.get("items") if isinstance(payload, dict) else []
    views = [int(row.get("views") or 0) for row in items if isinstance(row, dict)]
    latest = views[-1] if views else 0
    baseline = sum(views[:-1]) / max(1, len(views[:-1])) if len(views) > 1 else 0
    delta = latest - baseline
    pct = (delta / baseline * 100) if baseline else (100.0 if latest else 0.0)
    return {"title": title, "latestViews": latest, "baselineViews": round(baseline, 2), "deltaViews": round(delta, 2), "deltaPct": round(pct, 2)}


def _article_title(article: Dict[str, Any]) -> str:
    return str(article.get("title") or article.get("seendate") or "Breaking source").strip()


def _article_time(article: Dict[str, Any]) -> str:
    parsed = _parse_iso(article.get("seendate") or article.get("datetime") or article.get("date"))
    return parsed.isoformat().replace("+00:00", "Z") if parsed else ""


def _build_event_item(ctx: dict, seed: Dict[str, Any], articles: List[Dict[str, Any]], pageviews: List[Dict[str, Any]]) -> Dict[str, Any]:
    domains = sorted({str(row.get("domain") or row.get("sourceCommonName") or "").strip() for row in articles if row.get("domain") or row.get("sourceCommonName")})
    countries = sorted({str(row.get("sourcecountry") or row.get("country") or "").strip() for row in articles if row.get("sourcecountry") or row.get("country")})
    latest_article = max(articles, key=lambda row: _timestamp(row.get("seendate") or row.get("datetime") or row.get("date")), default={})
    mention_count = len(articles)
    wiki_delta = sum(float(row.get("deltaPct") or 0) for row in pageviews)
    source_diversity = len(domains)
    country_spread = len(countries)
    velocity = min(100, int(mention_count * 5 + source_diversity * 8 + country_spread * 3 + max(0.0, wiki_delta) * 0.15))
    confidence = min(0.98, 0.35 + min(mention_count, 20) * 0.02 + min(source_diversity, 8) * 0.04 + (0.08 if pageviews else 0.0))
    query = str(seed.get("entity") or seed.get("query") or "")
    markets = _match_markets(ctx, query, topic=str(seed.get("topic") or ""), limit=4)
    source_url = str(latest_article.get("url") or latest_article.get("shareurl") or GDELT_DOC_API_URL)
    return {
        "id": _stable_id(seed.get("id"), _article_title(latest_article), source_url),
        "topic": str(seed.get("topic") or "breaking"),
        "entity": str(seed.get("entity") or seed.get("id") or "Breaking Event"),
        "country": str(seed.get("country") or "Global"),
        "team": None,
        "title": _article_title(latest_article) if latest_article else str(seed.get("entity") or "Source warming"),
        "summary": str(latest_article.get("description") or latest_article.get("summary") or seed.get("query") or "")[:260],
        "eventTime": _article_time(latest_article) or _utc_now_iso(ctx),
        "source": str(latest_article.get("domain") or latest_article.get("sourceCommonName") or "GDELT"),
        "sourceUrl": source_url,
        "evidenceType": "WIRE",
        "mentionCount": mention_count,
        "mentionCount15m": mention_count,
        "mentionCount1h": mention_count,
        "mentionCount24h": mention_count,
        "velocityScore": velocity,
        "sourceDiversity": source_diversity,
        "countrySpread": country_spread,
        "tone": _safe_float(latest_article.get("tone")),
        "wikiPageviewDelta": round(wiki_delta, 2),
        "confidence": round(confidence, 2),
        "severity": "alert" if velocity >= 75 else "watch" if velocity >= 45 else "normal",
        "tags": [str(seed.get("topic") or "breaking"), "wire" if articles else "proxy"],
        "relatedPolymarketMarketIds": [market.get("marketId") for market in markets if market.get("marketId")],
        "markets": markets,
        "evidence": {
            "articles": [
                {
                    "title": _article_title(row),
                    "source": row.get("domain") or row.get("sourceCommonName"),
                    "url": row.get("url") or row.get("shareurl"),
                    "publishedAt": _article_time(row),
                }
                for row in articles[:5]
            ],
            "pageviews": pageviews,
        },
    }


def _safe_float(value: Any) -> Optional[float]:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _match_markets(ctx: dict, query: str, *, topic: str, limit: int) -> List[Dict[str, Any]]:
    search = ctx.get("search_markets")
    if not callable(search) or not query:
        return []
    try:
        rows = search(query, limit=limit)
    except Exception:
        return []
    markets: List[Dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        market_id = row.get("id") or row.get("marketId")
        title = row.get("question") or row.get("title") or row.get("slug")
        markets.append(
            {
                "marketId": market_id,
                "slug": row.get("slug"),
                "question": title,
                "matchScore": 0.62,
                "matchReasons": [reason for reason in ("entity", "topic" if topic else "") if reason],
            }
        )
    return markets


def _summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    alert_count = len([item for item in items if item.get("severity") == "alert"])
    watch_count = len([item for item in items if item.get("severity") == "watch"])
    top = items[0] if items else {}
    return {
        "total": len(items),
        "alerts": alert_count,
        "watch": watch_count,
        "topEntity": top.get("entity"),
        "topVelocity": top.get("velocityScore"),
    }


def build_breaking_event_radar_payload(ctx: dict, *, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    max_records = max(5, min(int(os.environ.get("POLYDATA_BREAKING_EVENT_GDELT_MAX_RECORDS", "20") or 20), 50))
    wikimedia_enabled = str(os.environ.get("POLYDATA_BREAKING_EVENT_WIKIMEDIA_ENABLED", "1")).strip().lower() in {"1", "true", "yes", "on"}
    max_wiki_titles = max(0, min(int(os.environ.get("POLYDATA_BREAKING_EVENT_WIKIMEDIA_TITLES_PER_TOPIC", "1") or 1), 4))
    seeds = _load_topic_seeds()
    items: List[Dict[str, Any]] = []
    sources: Dict[str, Any] = {"gdelt": {"status": "empty", "count": 0}, "wikimedia": {"status": "empty", "count": 0}}
    errors: List[str] = []
    for seed in seeds:
        articles: List[Dict[str, Any]] = []
        pageviews: List[Dict[str, Any]] = []
        try:
            articles = _fetch_gdelt_articles(ctx, seed, max_records=max_records)
            sources["gdelt"]["count"] += len(articles)
            sources["gdelt"]["status"] = "ok" if articles else sources["gdelt"]["status"]
        except Exception as exc:
            sources["gdelt"]["status"] = "error"
            errors.append(f"gdelt:{seed.get('id')}:{exc.__class__.__name__}")
        if wikimedia_enabled and max_wiki_titles > 0:
            for title in (seed.get("wikiTitles") or [])[:max_wiki_titles]:
                try:
                    pageviews.append(_fetch_pageviews(ctx, str(title)))
                    sources["wikimedia"]["count"] += 1
                    sources["wikimedia"]["status"] = "ok"
                except Exception as exc:
                    if sources["wikimedia"]["status"] != "ok":
                        sources["wikimedia"]["status"] = "error"
                    errors.append(f"wikimedia:{title}:{exc.__class__.__name__}")
        elif not wikimedia_enabled:
            sources["wikimedia"]["status"] = "disabled"
        if articles or pageviews:
            items.append(_build_event_item(ctx, seed, articles, pageviews))
    items.sort(key=lambda row: (int(row.get("velocityScore") or 0), str(row.get("eventTime") or "")), reverse=True)
    limited = items[: max(1, min(int(limit or DEFAULT_LIMIT), 80))]
    status = "ok" if limited and not errors else "degraded" if limited else "empty" if not errors else "degraded"
    return {
        "panelId": PANEL_ID,
        "generatedAt": _utc_now_iso(ctx),
        "status": status,
        "cacheMode": "live-build",
        "freshness": "live" if status == "ok" else "degraded" if limited else "warming",
        "source": "GDELT + Wikimedia Pageviews",
        "sourceUrl": _gdelt_url(ctx),
        "sources": sources,
        "summary": _summary(limited),
        "items": limited,
        "errors": errors[:12],
    }


def _empty_payload(ctx: dict, *, status: str = "warming", cache_mode: str = "warming") -> Dict[str, Any]:
    return {
        "panelId": PANEL_ID,
        "generatedAt": _utc_now_iso(ctx),
        "status": status,
        "cacheMode": cache_mode,
        "freshness": "warming",
        "source": "GDELT + Wikimedia Pageviews",
        "sourceUrl": _gdelt_url(ctx),
        "sources": {},
        "summary": _summary([]),
        "items": [],
        "errors": [],
    }


def normalize_breaking_event_radar_payload(payload: Any, *, ctx: dict, limit: int = DEFAULT_LIMIT) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload(ctx, status="invalid", cache_mode="invalid")
    result = json.loads(json.dumps(payload, ensure_ascii=True, default=str))
    items = [item for item in result.get("items") or [] if isinstance(item, dict)]
    result["items"] = items[: max(1, min(int(limit or DEFAULT_LIMIT), 80))]
    result["panelId"] = str(result.get("panelId") or PANEL_ID)
    result["generatedAt"] = str(result.get("generatedAt") or _utc_now_iso(ctx))
    result["status"] = str(result.get("status") or ("ok" if result["items"] else "warming"))
    result["cacheMode"] = str(result.get("cacheMode") or "seeded")
    result["freshness"] = str(result.get("freshness") or ("live" if result["status"] == "ok" else "degraded"))
    result["source"] = str(result.get("source") or "GDELT + Wikimedia Pageviews")
    result["sourceUrl"] = str(result.get("sourceUrl") or _gdelt_url(ctx))
    result["sources"] = result.get("sources") if isinstance(result.get("sources"), dict) else {}
    result["summary"] = result.get("summary") if isinstance(result.get("summary"), dict) else _summary(result["items"])
    result["summary"] = {**_summary(result["items"]), **result["summary"]}
    result["errors"] = [str(error) for error in result.get("errors") or []]
    return result


def _with_cache_mode(payload: Dict[str, Any], cache_mode: str) -> Dict[str, Any]:
    freshness = "stale" if "stale" in cache_mode else "seeded"
    return {**payload, "cacheMode": cache_mode, "freshness": payload.get("freshness") or freshness}


def _read_seeded_snapshot(ctx: dict) -> Optional[Dict[str, Any]]:
    reader = ctx.get("get_cached_json")
    if callable(reader):
        payload = reader(BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE, BREAKING_EVENT_RADAR_CACHE_KEY)
        if isinstance(payload, dict):
            return _with_cache_mode(payload, "redis-seed")
    store = ctx.get("SNAPSHOT_STORE")
    if store is None:
        return None
    payload = store.get(BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE, BREAKING_EVENT_RADAR_CACHE_KEY)
    if isinstance(payload, dict):
        return _with_cache_mode(payload, "sqlite-seed")
    stale = store.get_stale(BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE, BREAKING_EVENT_RADAR_CACHE_KEY)
    if isinstance(stale, dict):
        return _with_cache_mode(stale, "stale-seed")
    return None


def _store_live(ctx: dict, payload: Dict[str, Any], *, ttl_seconds: int) -> None:
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        store.set(BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE, BREAKING_EVENT_RADAR_CACHE_KEY, payload, ttl_seconds)
    setter = ctx.get("set_cached_json")
    if callable(setter):
        setter(BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE, BREAKING_EVENT_RADAR_CACHE_KEY, payload, ttl_seconds)


def _schedule_live_refresh(ctx: dict, *, limit: int, ttl_seconds: int, reason: str) -> bool:
    refresh_key = f"{BREAKING_EVENT_RADAR_SNAPSHOT_NAMESPACE}:{BREAKING_EVENT_RADAR_CACHE_KEY}"
    with _LIVE_REFRESH_LOCK:
        if refresh_key in _LIVE_REFRESHING:
            return False
        _LIVE_REFRESHING.add(refresh_key)

    def refresh() -> None:
        logger = getattr(ctx.get("app"), "logger", None)
        try:
            payload = {**build_breaking_event_radar_payload(ctx, limit=limit), "cacheMode": "live-build"}
            if payload.get("items"):
                _store_live(ctx, payload, ttl_seconds=ttl_seconds)
            elif logger is not None and hasattr(logger, "warning"):
                logger.warning("breaking event radar refresh skipped empty payload reason=%s", reason)
        except Exception:
            if logger is not None:
                logger.exception("breaking event radar refresh failed reason=%s", reason)
        finally:
            with _LIVE_REFRESH_LOCK:
                _LIVE_REFRESHING.discard(refresh_key)

    thread = threading.Thread(target=refresh, name="breaking-event-radar-refresh", daemon=True)
    thread.start()
    return True


def get_breaking_event_radar_snapshot(ctx: dict, limit: int = DEFAULT_LIMIT, *, allow_live_build: bool = True) -> Dict[str, Any]:
    ttl_seconds = max(120, int(os.environ.get("POLYDATA_BREAKING_EVENT_RADAR_TTL_SECONDS", DEFAULT_TTL_SECONDS) or DEFAULT_TTL_SECONDS))
    seeded = _read_seeded_snapshot(ctx)
    if seeded is not None:
        if allow_live_build and seeded.get("cacheMode") == "stale-seed":
            _schedule_live_refresh(ctx, limit=limit, ttl_seconds=ttl_seconds, reason="stale-seed")
        return normalize_breaking_event_radar_payload(seeded, ctx=ctx, limit=limit)
    if not allow_live_build:
        return normalize_breaking_event_radar_payload(_empty_payload(ctx, cache_mode="seed-miss"), ctx=ctx, limit=limit)
    scheduled = _schedule_live_refresh(ctx, limit=limit, ttl_seconds=ttl_seconds, reason="seed-miss")
    mode = "seed-miss-refreshing" if scheduled else "seed-miss-refresh-inflight"
    return normalize_breaking_event_radar_payload(_empty_payload(ctx, cache_mode=mode), ctx=ctx, limit=limit)
