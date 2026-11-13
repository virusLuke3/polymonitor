from __future__ import annotations
from api.services.macro_data_policy import bounded_rows, display_age, read_seeded

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from api.context import resolve_optional_service_callable, resolve_service_callable
from api.services import market_service, outcome_semantics_service


MACRO_MAP_SNAPSHOT_NAMESPACE = "snapshot:macro:polymarket-macro-map"
MACRO_MAP_CACHE_KEY = "panel-v1"
DEFAULT_ITEM_LIMIT = 12
CATALOG_MARKET_LIMIT = 100
DEFAULT_SEARCH_TERMS = (
    "cpi",
    "inflation",
    "consumer price",
    "pce",
    "fed",
    "fomc",
    "interest rate",
    "rates",
    "recession",
    "gdp",
    "unemployment",
    "payrolls",
    "jobs report",
    "oil",
    "wti",
    "brent",
    "gasoline",
    "energy",
)

MACRO_CATEGORIES = (
    {
        "id": "cpi",
        "label": "CPI / Inflation",
        "marketType": "CPI bucket / inflation prints",
        "terms": ("cpi", "inflation", "consumer price", "headline", "core cpi", "pce", "core pce"),
    },
    {
        "id": "fed",
        "label": "Fed / Rates",
        "marketType": "FOMC decision / target rate",
        "terms": ("fed", "fomc", "rate cut", "rate hike", "interest rate", "rates", "powell"),
    },
    {
        "id": "growth",
        "label": "Growth / Recession",
        "marketType": "GDP / recession / shutdown macro",
        "terms": ("recession", "gdp", "growth", "economy", "shutdown", "default"),
    },
    {
        "id": "labor",
        "label": "Labor / Jobs",
        "marketType": "NFP / unemployment / payrolls",
        "terms": ("unemployment", "payroll", "nfp", "jobs report", "jobless", "wage"),
    },
    {
        "id": "energy",
        "label": "Oil / Energy",
        "marketType": "Oil / gasoline / headline CPI driver",
        "terms": ("oil", "wti", "brent", "gasoline", "energy", "crude", "diesel"),
    },
)


@dataclass(frozen=True)
class PolymarketMacroMapDependencies:
    settings: Any
    application: Any
    http_json_get: Callable[..., Any] | None
    utc_now_iso: Callable[..., Any]
    get_cached_json: Callable[..., Any] | None
    set_cached_json: Callable[..., Any] | None
    snapshot_store: Any
    read_market_catalog: Callable[..., Any] | None = None

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> PolymarketMacroMapDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            settings=context.get("SETTINGS"),
            application=context.get("app"),
            http_json_get=resolve_optional_service_callable(
                context,
                "http_json_get",
            ),
            utc_now_iso=resolve_service_callable(
                context,
                "utc_now_iso",
            ),
            get_cached_json=resolve_optional_service_callable(
                context,
                "get_cached_json",
            ),
            set_cached_json=resolve_optional_service_callable(
                context,
                "set_cached_json",
            ),
            snapshot_store=context.get("SNAPSHOT_STORE"),
            read_market_catalog=context.get("read_market_catalog"),
        )


PolymarketMacroMapContext = (
    Mapping[str, Any] | PolymarketMacroMapDependencies
)


def _dependencies(
    context: PolymarketMacroMapContext,
) -> PolymarketMacroMapDependencies:
    return PolymarketMacroMapDependencies.from_context(context)


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, list) else [parsed]
        except Exception:
            return [item.strip() for item in text.split(",") if item.strip()]
    return [value]


def _float_value(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _parse_timestamp(value: Any) -> float:
    if not value:
        return 0.0
    text = str(value).strip().replace("Z", "+00:00")
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _event_tags(event: Dict[str, Any]) -> List[str]:
    tags: List[str] = []
    for item in _as_list(event.get("tags")):
        if isinstance(item, dict):
            label = item.get("label") or item.get("name") or item.get("slug")
        else:
            label = item
        text = str(label or "").strip()
        if text:
            tags.append(text)
    return tags


def _normalized_text(*parts: Any) -> str:
    return " ".join(str(part or "").lower() for part in parts)


def _event_haystack(event: Dict[str, Any]) -> str:
    markets = [
        str((market or {}).get("question") or (market or {}).get("title") or "")
        for market in (event.get("markets") or [])
        if isinstance(market, dict)
    ]
    return _normalized_text(
        event.get("title"),
        event.get("slug"),
        event.get("category"),
        event.get("categorySlug"),
        " ".join(_event_tags(event)),
        " ".join(markets),
    )


def _matches_term(haystack: str, term: str) -> bool:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return False
    pattern = r"(?<![a-z0-9])" + r"\s+".join(re.escape(part) for part in normalized.split()) + r"(?![a-z0-9])"
    return re.search(pattern, haystack) is not None


def _classify_event(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    haystack = _event_haystack(event)
    hits: List[Dict[str, Any]] = []
    for category in MACRO_CATEGORIES:
        if any(_matches_term(haystack, term) for term in category["terms"]):
            hits.append({key: category[key] for key in ("id", "label", "marketType")})
    return hits


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value) if value else None


def read_macro_market_catalog(query: Callable[..., Any], *, terms: tuple[str, ...], backend: str) -> Dict[str, Any]:
    """Bounded projection of the existing owner; no HTTP or additional cache."""
    if backend.lower() not in {"postgres", "postgresql"}:
        raise RuntimeError("macro catalog requires the existing PostgreSQL owner")
    tokens = [re.findall(r"[a-z0-9]+", term.lower()) for term in terms]
    expression = " | ".join("(" + " & ".join(words) + ")" for words in tokens if words)
    if not expression:
        raise ValueError("macro catalog search terms missing")
    # Match the existing registry search index. Event titles/tags remain part
    # of classification, but are not an unbounded second discovery scan.
    rows = market_service.market_rows(query,
        "m.active IS TRUE AND m.closed IS FALSE "
        "AND (m.end_date IS NULL OR m.end_date >= now()) "
        "AND NULLIF(m.event_id, '') IS NOT NULL AND q.observed_at IS NOT NULL "
        "AND q.active AND NOT q.closed "
        "AND to_tsvector('simple', coalesce(m.title,'') || ' ' || coalesce(m.slug,'') || ' ' || coalesce(m.category,'')) "
        "@@ to_tsquery('simple', ?)", (expression,),
        limit=CATALOG_MARKET_LIMIT + 1, sort="volume", search=True)
    candidates = []
    for row in rows[:CATALOG_MARKET_LIMIT]:
        item = market_service.MarketPanelReader._item(row)
        item.update(eventId=row.get("event_id"), eventTitle=row.get("event_title"),
                    eventSlug=row.get("event_slug"),
                    sourceObservedAt=_iso(row.get("quote_observed_at")),
                    sourceUpdatedAt=_iso(row.get("quote_updated_at")))
        candidates.append(item)
    projected = outcome_semantics_service.sanitize_public_market_payload(
        {"query_all": query, "get_backend": lambda: backend}, {"items": candidates})
    items = projected.get("items", [])
    if any(row.get("outcomeSemanticsStatus") in {"semantics_query_failed", "semantics_database_unavailable"}
           for row in items):
        raise TimeoutError("macro catalog outcome evidence unavailable")
    return {"items": items, "coverage": {
        "scope": "recently-observed-macro-markets", "completeness": "NOT_PROVEN",
        "marketLimit": CATALOG_MARKET_LIMIT, "candidateCount": len(candidates),
        "truncated": len(rows) > CATALOG_MARKET_LIMIT,
        "searchFields": ["marketTitle", "marketSlug", "category"],
        "searchTerms": list(terms), "quoteMaxAgeSeconds": 7200,
        "eventMembership": "observed-matching-markets-only",
        "universeCount": None,
    }}


def _search_terms(ctx: PolymarketMacroMapContext) -> tuple[str, ...]:
    configured = getattr(_dependencies(ctx).settings, "polymarket_macro_map_search_terms", ())
    terms = tuple(str(term).strip().lower() for term in configured if str(term).strip())
    return terms or DEFAULT_SEARCH_TERMS


def _event_matches_terms(event: Dict[str, Any], terms: tuple[str, ...]) -> bool:
    haystack = _event_haystack(event)
    return any(_matches_term(haystack, term) for term in terms)


def _normalize_event(event: Dict[str, Any], categories: List[Dict[str, Any]]) -> Dict[str, Any]:
    outcomes = []
    for market in event["markets"]:
        valid = market.get("priceProjectionValid") is True
        yes_no = valid and market.get("supportsYesNoWording") is True
        source_outcomes = []
        for outcome in market.get("outcomePrices") or []:
            price = _float_value(outcome.get("price"))
            if (valid and outcome.get("tokenId") and outcome.get("sourceLabel")
                    and isinstance(outcome.get("sourceIndex"), int)
                    and price is not None and 0 <= price <= 1):
                source_outcomes.append({"tokenId": str(outcome["tokenId"]),
                    "sourceLabel": outcome["sourceLabel"], "sourceIndex": outcome["sourceIndex"],
                    "price": price})
        source_outcomes.sort(key=lambda row: row["sourceIndex"])
        primary = source_outcomes[0] if source_outcomes else {}
        outcomes.append({
            "outcomeKey": str(market["id"]), "marketId": market["id"],
            "gammaMarketId": market.get("gammaMarketId"), "label": market.get("title"),
            "title": market.get("title"), "slug": market.get("slug"),
            "conditionId": market.get("conditionId"),
            "yesPrice": _float_value(market.get("latestYesPrice")) if yes_no else None,
            "noPrice": _float_value(market.get("latestNoPrice")) if yes_no else None,
            "sourceOutcomes": source_outcomes,
            "tokenId": primary.get("tokenId"), "sourceLabel": primary.get("sourceLabel"),
            "sourceIndex": primary.get("sourceIndex"), "price": primary.get("price"),
            "priceSelection": "source-order-first" if primary else None,
            "semanticMode": market.get("semanticMode"),
            "volume24h": _float_value(market.get("volume24h")),
            "endDate": _iso(market.get("endDate")),
            "sourceObservedAt": market.get("sourceObservedAt"),
            "sourceUpdatedAt": market.get("sourceUpdatedAt"),
            "outcomeSemanticsStatus": market.get("outcomeSemanticsStatus"),
            "priceUnavailableReason": None if primary else (
                "source-outcome-binding-unavailable" if valid else market.get("outcomeSemanticsStatus") or "unverified-price"),
        })
    observed = sorted(row["sourceObservedAt"] for row in outcomes if row.get("sourceObservedAt"))
    updated = sorted(row["sourceUpdatedAt"] for row in outcomes if row.get("sourceUpdatedAt"))
    ends = sorted(row["endDate"] for row in outcomes if row.get("endDate"))
    volumes = [row["volume24h"] for row in outcomes if row["volume24h"] is not None]
    return {
        "eventId": event["id"], "slug": event.get("slug"), "title": event["title"],
        "categoryIds": [category["id"] for category in categories],
        "categoryLabels": [category["label"] for category in categories],
        "marketTypes": [category["marketType"] for category in categories],
        "endDate": ends[0] if ends else None, "endDateScope": "earliest-observed-market",
        "createdAt": None, "volume24h": None, "liquidity": None,
        "observedMarketVolume24h": sum(volumes) if volumes else None,
        "volumeScope": "observed-matching-markets-only", "eventMembershipComplete": False,
        "outcomeCount": len(outcomes), "outcomeCountScope": "observed-matching-markets-only",
        "unpricedOutcomeCount": sum(row["price"] is None for row in outcomes),
        "sourceObservedAt": observed[0] if observed else None,
        "newestSourceObservedAt": observed[-1] if observed else None,
        "sourceUpdatedAt": updated[-1] if updated else None,
        "topOutcomes": sorted(outcomes, key=lambda row: row["price"] if row["price"] is not None else -1,
                              reverse=True)[:3],
    }


def _score_item(item: Dict[str, Any], now_ts: float) -> tuple[float, float, float]:
    volume = _float_value(item.get("observedMarketVolume24h")) or 0.0
    liquidity = _float_value(item.get("liquidity")) or 0.0
    end_ts = _parse_timestamp(item.get("endDate"))
    if end_ts and now_ts:
        days_to_event = max(0.0, (end_ts - now_ts) / 86400)
        catalyst_score = max(0.0, 30.0 - min(days_to_event, 30.0))
    else:
        catalyst_score = 0.0
    category_weight = 8.0 if "cpi" in (item.get("categoryIds") or []) else 0.0
    return (category_weight + catalyst_score, volume, liquidity)


def _category_breakdown(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for category in MACRO_CATEGORIES:
        matched = [item for item in items if category["id"] in (item.get("categoryIds") or [])]
        top = max(matched, key=lambda item: _float_value(item.get("observedMarketVolume24h")) or 0.0) if matched else None
        rows.append(
            {
                "id": category["id"],
                "label": category["label"],
                "marketType": category["marketType"],
                "activeCount": len(matched),
                "topTitle": top.get("title") if top else None,
                "volume24h": sum(float(_float_value(item.get("volume24h")) or 0.0) for item in matched),
            }
        )
    return rows


def _top_catalyst(items: List[Dict[str, Any]], now_ts: float) -> Optional[Dict[str, Any]]:
    upcoming = [
        item
        for item in items
        if _parse_timestamp(item.get("endDate")) > now_ts > 0
    ]
    if not upcoming:
        return None
    item = min(upcoming, key=lambda candidate: _parse_timestamp(candidate.get("endDate")))
    return {
        "title": item.get("title"),
        "eventId": item.get("eventId"),
        "slug": item.get("slug"),
        "endDate": item.get("endDate"),
        "categoryLabels": item.get("categoryLabels") or [],
    }


def _summary(items: List[Dict[str, Any]], categories: List[Dict[str, Any]], now_ts: float) -> Dict[str, Any]:
    top_category = max(categories, key=lambda row: int(row.get("activeCount") or 0)) if categories else None
    top_label = str((top_category or {}).get("label") or "Macro")
    active_count = len(items)
    if active_count <= 0:
        signal = "NO MACRO CLUSTER"
    elif int((top_category or {}).get("activeCount") or 0) >= 4:
        signal = f"{top_label.upper()} CLUSTER ACTIVE"
    else:
        signal = "MACRO WATCHLIST LIVE"
    return {
        "activeCount": active_count,
        "activeCountScope": "observed-matching-events-only",
        "categoryCount": sum(1 for row in categories if int(row.get("activeCount") or 0) > 0),
        "topCategory": top_label,
        "signal": signal,
        "topCatalyst": _top_catalyst(items, now_ts),
    }


def _empty_payload(ctx: PolymarketMacroMapContext, *, status: str = "degraded", source_state: str = "warming") -> Dict[str, Any]:
    return {
        "generatedAt": None,
        "sourceObservedAt": None,
        "source": "market-data/postgresql",
        "sourceUrl": getattr(_dependencies(ctx).settings, "polymarket_macro_map_source_url", "") or _dependencies(ctx).settings.gamma_api_base,
        "status": status,
        "sources": {"marketCatalog": source_state},
        "summary": {
            "activeCount": 0,
            "categoryCount": 0,
            "topCategory": "Macro",
            "signal": "NO MACRO CLUSTER",
            "topCatalyst": None,
        },
        "categories": _category_breakdown([]),
        "items": [],
    }


def normalize_polymarket_macro_map_payload(payload: Any, *, ctx: PolymarketMacroMapContext, limit: int = DEFAULT_ITEM_LIMIT) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload(ctx, status="invalid", source_state="invalid")
    result = json.loads(json.dumps(payload, ensure_ascii=True, default=str))
    items = bounded_rows(result, now=_dependencies(ctx).utc_now_iso(),
        max_age=display_age(_dependencies(ctx).settings, "polymarket_macro_map_max_display_age_seconds", 7200),
        clock=lambda row: row.get("sourceObservedAt"))
    result["items"] = items[: max(1, min(int(limit or DEFAULT_ITEM_LIMIT), DEFAULT_ITEM_LIMIT))]
    if isinstance(result.get("coverage"), dict):
        result["coverage"].update(displayedEventCount=len(result["items"]),
            displayLimit=max(1, min(int(limit or DEFAULT_ITEM_LIMIT), DEFAULT_ITEM_LIMIT)),
            displayTruncated=len(items) > len(result["items"]))
    result["categories"] = [row for row in (result.get("categories") or []) if isinstance(row, dict)]
    result["summary"] = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if result["displayRetention"]["expiredItemCount"]:
        result["categories"] = _category_breakdown(items)
        result["summary"] = _summary(items, result["categories"], _parse_timestamp(_dependencies(ctx).utc_now_iso()))
    result["generatedAt"] = result.get("generatedAt") or None
    result["source"] = str(result.get("source") or "market-data/postgresql")
    result["sourceUrl"] = str(result.get("sourceUrl") or getattr(_dependencies(ctx).settings, "polymarket_macro_map_source_url", "") or _dependencies(ctx).settings.gamma_api_base)
    result["status"] = str(result.get("status") or ("ok" if result["items"] else "empty"))
    return result


def _with_cache_mode(payload: Dict[str, Any], cache_mode: str) -> Dict[str, Any]:
    return {**payload, "cacheMode": str(cache_mode)}


def _read_seeded_snapshot(ctx: PolymarketMacroMapContext) -> Optional[Dict[str, Any]]:
    dependencies = _dependencies(ctx)
    return read_seeded(dependencies.snapshot_store, dependencies.get_cached_json, MACRO_MAP_SNAPSHOT_NAMESPACE, MACRO_MAP_CACHE_KEY)


def build_polymarket_macro_map_payload(ctx: PolymarketMacroMapContext) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    if not callable(dependencies.read_market_catalog):
        raise RuntimeError("macro market catalog reader missing")
    terms = _search_terms(dependencies)
    catalog = dependencies.read_market_catalog(terms=terms)
    if not isinstance(catalog, dict) or not isinstance(catalog.get("items"), list):
        raise ValueError("macro market catalog payload invalid")
    events: Dict[str, Dict[str, Any]] = {}
    for market in catalog["items"]:
        event_id = str(market.get("eventId") or "")
        if not event_id or not market.get("eventTitle"):
            continue
        event = events.setdefault(event_id, {"id": event_id, "title": market["eventTitle"],
            "slug": market.get("eventSlug"), "tags": [], "markets": []})
        event["markets"].append(market)
        event["tags"].extend(market.get("tags") or [])
    items = []
    for event in events.values():
        categories = _classify_event(event)
        if categories and _event_matches_terms(event, terms):
            items.append(_normalize_event(event, categories))
    now_iso = dependencies.utc_now_iso()
    now_ts = _parse_timestamp(now_iso)
    items.sort(key=lambda item: _score_item(item, now_ts), reverse=True)
    categories = _category_breakdown(items)
    coverage = dict(catalog.get("coverage") or {})
    coverage.update(matchedEventCount=len(items),
        matchedMarketCount=sum(item["outcomeCount"] for item in items),
        unpricedMarketCount=sum(item["unpricedOutcomeCount"] for item in items))
    coverage["unmatchedCandidateCount"] = len(catalog["items"]) - coverage["matchedMarketCount"]
    observed = sorted(item["sourceObservedAt"] for item in items if item.get("sourceObservedAt"))
    newest = sorted(item["newestSourceObservedAt"] for item in items if item.get("newestSourceObservedAt"))
    return {
        "generatedAt": now_iso, "fetchedAt": now_iso, "source": "market-data/postgresql",
        "sourceUrl": getattr(dependencies.settings, "polymarket_macro_map_source_url", "") or None,
        "sourceObservedAt": observed[0] if observed else None,
        "newestSourceObservedAt": newest[-1] if newest else None,
        "status": ("degraded" if coverage.get("truncated") or coverage["unpricedMarketCount"] else "ok") if items else "empty",
        "sources": {"marketCatalog": "ok"}, "coverage": coverage,
        "summary": _summary(items, categories, now_ts), "categories": categories, "items": items,
    }


def get_polymarket_macro_map_snapshot(ctx: PolymarketMacroMapContext, limit: int = DEFAULT_ITEM_LIMIT) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    seeded_payload = _read_seeded_snapshot(dependencies)
    if seeded_payload is not None:
        return normalize_polymarket_macro_map_payload(
            seeded_payload,
            ctx=dependencies,
            limit=limit,
        )

    # Public GETs never discover markets or open a database collection run.
    return _with_cache_mode(_empty_payload(dependencies, status="warming", source_state="warming"), "warming")
