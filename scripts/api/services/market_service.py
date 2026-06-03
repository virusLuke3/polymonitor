from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional
from urllib.parse import unquote

from api.services import clickhouse_orderfilled_service
from api.services import market_group_service
from market.market_identity import MarketIdentity, oracle_event_lookup_clause, oracle_event_lookup_terms

ACTIVE_MARKETS_SNAPSHOT_NAMESPACE = "snapshot:markets_active_v12"
DEFAULT_ACTIVE_MARKET_MAX_AGE_HOURS = int(os.environ.get("POLYDATA_ACTIVE_MARKET_MAX_AGE_HOURS", "336"))
DEFAULT_ACTIVE_MARKET_LOB_PREFETCH_LIMIT = int(os.environ.get("POLYDATA_ACTIVE_MARKET_LOB_PREFETCH_LIMIT", "60"))
DEFAULT_ACTIVE_MARKET_EXCLUSION_SQL = """
    LOWER(COALESCE(CAST(m.tags AS TEXT), '')) NOT LIKE '%%hide-from-new%%'
    AND LOWER(COALESCE(CAST(m.tags AS TEXT), '')) NOT LIKE '%%recurring%%'
    AND LOWER(COALESCE(CAST(m.tags AS TEXT), '')) NOT LIKE '%%onchain-registry%%'
    AND LOWER(COALESCE(CAST(m.slug AS TEXT), '')) NOT LIKE '%%updown-5m%%'
    AND LOWER(COALESCE(CAST(m.slug AS TEXT), '')) NOT LIKE '%%updown-15m%%'
    AND LOWER(COALESCE(CAST(m.title AS TEXT), '')) NOT LIKE '%% up or down - %%'
"""

def _default_active_market_activity_sql(stats_alias: str) -> str:
    return f"""
    (
        COALESCE({stats_alias}.trade_count_24h, 0) > 0
        OR COALESCE({stats_alias}.volume_24h, 0) > 0
        OR {stats_alias}.last_trade_at IS NOT NULL
        OR {stats_alias}.latest_trade_at IS NOT NULL
    )
    """

def _default_active_market_price_sql(stats_alias: str) -> str:
    return f"""
    (
        {stats_alias}.latest_price IS NULL
        OR (CAST({stats_alias}.latest_price AS DECIMAL(18, 10)) >= 0.10 AND CAST({stats_alias}.latest_price AS DECIMAL(18, 10)) <= 0.90)
    )
    """

def _default_active_market_recent_trade_sql(stats_alias: str) -> str:
    return f"COALESCE({stats_alias}.last_trade_at, {stats_alias}.latest_trade_at) >= ?"


def _default_active_market_created_recent_sql() -> str:
    return "m.created_at IS NULL OR m.created_at >= ?"


def _iso_hours_before(now_iso: str, hours: int) -> str:
    text = str(now_iso or "").replace("Z", "+00:00")
    try:
        now = datetime.fromisoformat(text)
    except ValueError:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

PRICE_TARGET_RE = re.compile(r"\b(?:hit|reach)\s+\$+\s*([0-9][0-9,]*(?:\.\d+)?)\s*([kmb])?\b", re.IGNORECASE)
PAIR_RE = re.compile(r"\b([A-Z0-9]{2,12}/[A-Z0-9]{2,12})\b")
YAHOO_QUOTE_RE = re.compile(r"finance\.yahoo\.com/quote/([^/?\"' )]+)", re.IGNORECASE)

NAME_TO_YAHOO_SYMBOL = {
    "bitcoin": "BTC-USD",
    "btc": "BTC-USD",
    "ethereum": "ETH-USD",
    "eth": "ETH-USD",
    "solana": "SOL-USD",
    "sol": "SOL-USD",
    "xrp": "XRP-USD",
    "dogecoin": "DOGE-USD",
    "doge": "DOGE-USD",
    "s&p 500": "^GSPC",
    "spx": "^GSPC",
    "nasdaq 100": "^NDX",
    "ndx": "^NDX",
    "gold": "GC=F",
    "silver": "SI=F",
    "oil": "CL=F",
}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def markets_runtime_prices_enabled() -> bool:
    return _env_flag("POLYDATA_MARKETS_RUNTIME_PRICES", False)


def markets_latest_snapshot_fallback_enabled() -> bool:
    return _env_flag("POLYDATA_MARKETS_LATEST_SNAPSHOT_FALLBACK", True)


def _trim_active_markets_payload(ctx: dict, payload: Any, page_size: int) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        return None
    source_page_size = len(items)
    pagination = payload.get("pagination")
    if isinstance(pagination, dict):
        try:
            source_page_size = int(pagination.get("pageSize") or source_page_size)
        except (TypeError, ValueError):
            source_page_size = len(items)
    if len(items) < page_size and source_page_size < page_size:
        return None
    trimmed_items = items[:page_size]
    return {
        **payload,
        "items": trimmed_items,
        "pagination": {
            "page": 1,
            "pageSize": page_size,
            "total": len(trimmed_items),
            "totalPages": 1,
            "hasMore": len(items) > page_size,
        },
    }


def _normalized_gamma_active_keys(ctx: dict) -> tuple[set[str], set[str]]:
    get_filter = ctx.get("get_gamma_active_market_filter")
    if not callable(get_filter):
        return set(), set()
    payload = get_filter() or {}
    condition_ids = {
        str(value or "").strip().lower()
        for value in (payload.get("conditionIds") or [])
        if str(value or "").strip()
    }
    slugs = {
        str(value or "").strip().lower()
        for value in (payload.get("slugs") or [])
        if str(value or "").strip()
    }
    return condition_ids, slugs


def _filter_candidate_rows_to_gamma_active(ctx: dict, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    condition_ids, slugs = _normalized_gamma_active_keys(ctx)
    if not condition_ids and not slugs:
        return rows
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        condition_id = str(row.get("condition_id") or "").strip().lower()
        slug = str(row.get("slug") or "").strip().lower()
        if condition_id and condition_id in condition_ids:
            filtered.append(row)
            continue
        if slug and slug in slugs:
            filtered.append(row)
    return filtered


def _prefer_gamma_active_candidate_rows(ctx: dict, rows: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    """Prefer Gamma-confirmed markets, then fill from DB-active rows like PolyWorld."""
    gamma_rows = _filter_candidate_rows_to_gamma_active(ctx, rows)
    if len(gamma_rows) >= target_count:
        return gamma_rows
    if not gamma_rows:
        return rows

    seen_ids = {int(row["id"]) for row in gamma_rows if row.get("id") is not None}
    fallback_rows = [row for row in rows if row.get("id") is None or int(row["id"]) not in seen_ids]
    return [*gamma_rows, *fallback_rows]


def _blend_recent_candidate_rows(volume_rows: List[Dict[str, Any]], recent_rows: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    if not recent_rows:
        return volume_rows
    target_count = max(1, int(target_count))
    recent_count = max(target_count, min(len(recent_rows), target_count * 2))

    blended: List[Dict[str, Any]] = []
    seen_ids: set[int] = set()

    def append_rows(rows: List[Dict[str, Any]], limit: Optional[int] = None) -> None:
        added = 0
        for row in rows:
            market_id = row.get("id")
            if market_id is not None:
                numeric_id = int(market_id)
                if numeric_id in seen_ids:
                    continue
                seen_ids.add(numeric_id)
            blended.append(row)
            added += 1
            if limit is not None and added >= limit:
                break

    append_rows(recent_rows, recent_count)
    append_rows(volume_rows)
    append_rows(recent_rows)
    return blended


def _decimal_from_any(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _price_value_from_point(point: Dict[str, Any]) -> Any:
    if not isinstance(point, dict):
        return None
    return point.get("yesPrice") if point.get("yesPrice") not in (None, "") else point.get("price")


def _chart_point_stats(points: List[Dict[str, Any]]) -> tuple[int, int]:
    values: set[str] = set()
    for point in points or []:
        value = _price_value_from_point(point)
        if value not in (None, ""):
            values.add(str(value))
    return len(points or []), len(values)


def _chart_history_status(range_name: str, interval: str, points: List[Dict[str, Any]]) -> str:
    if not points:
        return "missing"
    if range_name == "snapshot" or interval == "snapshot" or len(points) <= 2:
        return "snapshot"
    _, distinct_count = _chart_point_stats(points)
    if distinct_count <= 1:
        return "flat"
    if len(points) < 8:
        return "short"
    return "ok"


def _workspace_identity(market_id: int, market: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "localMarketId": market_id,
        "marketId": market_id,
        "gammaMarketId": market.get("gamma_market_id"),
        "eventId": market.get("event_id"),
        "eventSlug": market.get("event_slug"),
        "slug": market.get("slug"),
        "conditionId": market.get("condition_id"),
        "questionId": market.get("question_id"),
        "oracle": market.get("oracle"),
        "yesTokenId": market.get("yes_token_id"),
        "noTokenId": market.get("no_token_id"),
    }


def _workspace_selected_outcome(
    group: Optional[Dict[str, Any]],
    market_id: int,
    market: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(group, dict):
        return None
    market = market or {}
    gamma_market_id = str(market.get("gamma_market_id") or "").strip()
    condition_id = str(market.get("condition_id") or "").strip().lower()
    yes_token_id = str(market.get("yes_token_id") or "").strip()
    outcomes = list(group.get("outcomes") or []) + list(group.get("topOutcomes") or [])
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        for key in ("marketId", "localMarketId"):
            if outcome.get(key) is None:
                continue
            try:
                if int(outcome.get(key) or 0) == int(market_id):
                    return outcome
            except (TypeError, ValueError):
                continue
        if gamma_market_id and str(outcome.get("gammaMarketId") or "").strip() == gamma_market_id:
            return outcome
        if condition_id and str(outcome.get("conditionId") or "").strip().lower() == condition_id:
            return outcome
        if yes_token_id and str(outcome.get("yesTokenId") or "").strip() == yes_token_id:
            return outcome
    return None


def _workspace_health(
    *,
    market_id: int,
    identity: Dict[str, Any],
    price: Optional[Dict[str, Any]],
    chart: Optional[Dict[str, Any]],
    oracle_payload: Optional[Dict[str, Any]],
    diagnostics: Optional[Dict[str, Any]],
    group: Optional[Dict[str, Any]],
    selected_outcome: Optional[Dict[str, Any]],
    serving_source: Optional[str],
) -> Dict[str, Any]:
    chart_status = str((chart or {}).get("historyStatus") or (diagnostics or {}).get("chartStatus") or "missing")
    timeline = (oracle_payload or {}).get("timeline") or []
    if not isinstance(timeline, list):
        timeline = []
    has_identity = bool(identity.get("conditionId") or identity.get("questionId") or identity.get("oracle"))
    oracle_market_id = (oracle_payload or {}).get("localMarketId") or (oracle_payload or {}).get("marketId")
    try:
        oracle_matches = oracle_market_id in (None, "") or int(oracle_market_id or 0) == int(market_id)
    except (TypeError, ValueError):
        oracle_matches = str(oracle_market_id or "") == str(market_id)
    if not oracle_matches:
        oracle_status = "mismatch"
    elif timeline:
        oracle_status = "bound"
    elif has_identity:
        oracle_status = "open-no-events"
    else:
        oracle_status = "unbound"
    price_status = "ok" if price and (price.get("latestYesPrice") not in (None, "") or price.get("latestPrice") not in (None, "")) else "missing"
    if chart_status == "missing" and price_status == "ok":
        chart_status = "snapshot" if (chart or {}).get("points") else "missing-local-history"
    if group and selected_outcome is None:
        group_status = "outcome-missing"
    elif group:
        group_status = "ok"
    else:
        group_status = "single-market"
    serving_status = "ok" if serving_source == "postgres" else "fallback"
    issues = list((diagnostics or {}).get("issues") or [])
    if oracle_status == "mismatch":
        issues.append("oracle-market-id-mismatch")
    if group_status == "outcome-missing":
        issues.append("group-selected-outcome-missing")
    return {
        "marketId": market_id,
        "priceStatus": price_status,
        "chartStatus": chart_status,
        "oracleStatus": oracle_status,
        "lobStatus": "not-loaded",
        "servingStatus": serving_status,
        "groupStatus": group_status,
        "issues": issues,
        "level": "critical" if any("mismatch" in issue for issue in issues) else ("warn" if issues else "ok"),
    }


def _workspace_diagnostics(
    market_id: int,
    market: Dict[str, Any],
    price: Dict[str, Any],
    chart: Dict[str, Any],
    oracle_payload: Dict[str, Any],
    trades: List[Dict[str, Any]],
) -> Dict[str, Any]:
    points = chart.get("points") if isinstance(chart, dict) else []
    if not isinstance(points, list):
        points = []
    chart_status = str(chart.get("historyStatus") or _chart_history_status(str(chart.get("range") or ""), str(chart.get("interval") or ""), points))
    oracle_timeline = oracle_payload.get("timeline") if isinstance(oracle_payload, dict) else []
    if not isinstance(oracle_timeline, list):
        oracle_timeline = []
    token_ids = [value for value in (market.get("yes_token_id"), market.get("no_token_id")) if value]
    issues: List[str] = []
    if not market.get("gamma_market_id"):
        issues.append("missing-gamma-market-id")
    if not market.get("condition_id"):
        issues.append("missing-condition-id")
    if not token_ids:
        issues.append("missing-clob-token-ids")
    if chart_status in {"missing", "snapshot", "flat"}:
        issues.append(f"chart-{chart_status}")
    if not price or price.get("latestPrice") in (None, ""):
        issues.append("missing-latest-price")
    completion_status = str(oracle_payload.get("completionStatus") or "UNKNOWN")
    if completion_status not in {"OPEN", "UNKNOWN"} and not oracle_timeline:
        issues.append("missing-oracle-timeline")
    volume = _decimal_from_any(price.get("volume24h") if isinstance(price, dict) else None)
    trade_count = int((price or {}).get("tradeCount24h") or 0)
    if not trades and ((volume is not None and volume > 0) or trade_count > 0):
        issues.append("serving-volume-without-local-trades")

    critical_issues = {"missing-condition-id", "missing-clob-token-ids"}
    if any(issue in critical_issues for issue in issues):
        level = "critical"
    elif issues:
        level = "warn"
    else:
        level = "ok"
    return {
        "marketId": market_id,
        "identityStatus": "ok" if market.get("condition_id") and token_ids else "partial",
        "chartStatus": chart_status,
        "oracleStatus": completion_status,
        "oracleEventCount": len(oracle_timeline),
        "tradeCount": len(trades),
        "hasPrice": bool(price and price.get("latestPrice") not in (None, "")),
        "hasLobTokens": bool(token_ids),
        "issues": issues,
        "level": level,
    }


def _is_tradeable_probability(value: Any) -> bool:
    price = _decimal_from_any(value)
    if price is None:
        return True
    return Decimal("0.01") < price < Decimal("0.99")


def _has_recent_trade_window(row: Dict[str, Any]) -> bool:
    trade_count = int(row.get("trade_count_24h") or 0)
    volume_24h = _decimal_from_any(row.get("volume_24h"))
    return trade_count > 0 or (volume_24h is not None and volume_24h > 0)


def _filter_tradeable_market_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for row in rows:
        if not _has_recent_trade_window(row):
            continue
        if not _is_tradeable_probability(row.get("latest_price")):
            continue
        filtered.append(row)
    return filtered


def _prefer_tradeable_market_rows(rows: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    """Prefer liquid/recent markets, then fill from active rows instead of collapsing the panel."""
    tradeable_rows = _filter_tradeable_market_rows(rows)
    if len(tradeable_rows) >= target_count:
        return tradeable_rows
    if not tradeable_rows:
        return rows

    seen_ids = {int(row["id"]) for row in tradeable_rows if row.get("id") is not None}
    fallback_rows = [row for row in rows if row.get("id") is None or int(row["id"]) not in seen_ids]
    return [*tradeable_rows, *fallback_rows]


def _balanced_probability_score(value: Any) -> float:
    price = _decimal_from_any(value)
    if price is None:
        return 0.0
    distance = abs(float(price) - 0.5)
    return max(0.0, 1.0 - distance / 0.5)


def _market_family_key(row: Dict[str, Any]) -> str:
    question_id = str(row.get("question_id") or "").strip().lower()
    if question_id:
        return f"question:{question_id}"
    title = re.sub(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b|\b\d+(?:\.\d+)?\b", " ", str(row.get("title") or "").lower())
    words = re.findall(r"[a-z][a-z0-9]+", title)
    prefix = " ".join(words[:5]) if words else str(row.get("slug") or row.get("condition_id") or row.get("id"))
    category = str(row.get("category") or "").strip().lower()
    return f"{category}:{prefix}"


def _rank_default_market_rows(rows: List[Dict[str, Any]], now_value: Any = None) -> List[Dict[str, Any]]:
    def parse_time(value: Any) -> Optional[datetime]:
        if not value:
            return None
        text = str(value).replace(" ", "T")
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    now = parse_time(now_value) or datetime.now(timezone.utc)

    def score(row: Dict[str, Any]) -> float:
        created = parse_time(row.get("created_at"))
        last_trade = parse_time(row.get("last_trade_at") or row.get("latest_trade_at"))
        age_hours = (now - created).total_seconds() / 3600 if created else 9999
        trade_age_hours = (now - last_trade).total_seconds() / 3600 if last_trade else 9999
        recency = max(0.0, 1.0 - min(age_hours, 24 * 14) / (24 * 14))
        trade_recency = max(0.0, 1.0 - min(trade_age_hours, 24 * 3) / (24 * 3))
        volume = min(1.0, float(_decimal_from_any(row.get("volume_24h")) or 0) / 50000.0)
        trades = min(1.0, int(row.get("trade_count_24h") or 0) / 250.0)
        balance = _balanced_probability_score(row.get("latest_price"))
        return recency * 35 + trade_recency * 25 + balance * 25 + volume * 10 + trades * 5

    return sorted(rows, key=score, reverse=True)


def _diversify_market_rows(rows: List[Dict[str, Any]], page_size: int, now_value: Any = None) -> List[Dict[str, Any]]:
    selected: List[Dict[str, Any]] = []
    seen_families: set[str] = set()
    for row in rows:
        family = _market_family_key(row)
        if family in seen_families:
            continue
        selected.append(row)
        seen_families.add(family)
        if len(selected) >= page_size:
            return selected
    seen_ids = {int(row["id"]) for row in selected if row.get("id") is not None}
    ranked = _rank_default_market_rows(rows, now_value)
    for row in ranked:
        market_id = row.get("id")
        if market_id is not None and int(market_id) in seen_ids:
            continue
        selected.append(row)
        if len(selected) >= page_size:
            break
    return selected


def _coalesce_native_market_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    passthrough: List[Dict[str, Any]] = []
    for row in rows:
        question_id = str(row.get("question_id") or "").strip().lower()
        if not question_id:
            passthrough.append(row)
            continue
        grouped.setdefault(question_id, []).append(row)

    coalesced: List[Dict[str, Any]] = []
    for group_rows in grouped.values():
        if len(group_rows) == 1:
            coalesced.append(group_rows[0])
            continue
        ranked = _rank_default_market_rows(group_rows)
        representative = dict(ranked[0])
        representative["native_outcome_count"] = len(group_rows)
        representative["volume_24h"] = sum((_decimal_from_any(row.get("volume_24h")) or Decimal("0")) for row in group_rows)
        representative["trade_count_24h"] = sum(int(row.get("trade_count_24h") or 0) for row in group_rows)
        coalesced.append(representative)
    return [*coalesced, *passthrough]


def _book_side_has_levels(side: Any) -> bool:
    return isinstance(side, dict) and bool(side.get("bids") or side.get("asks"))


def _lob_payload_has_levels(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return _book_side_has_levels(payload.get("yes")) or _book_side_has_levels(payload.get("no"))


def _prefer_lob_ready_market_rows(ctx: dict, rows: List[Dict[str, Any]], target_count: int) -> List[Dict[str, Any]]:
    if not _env_flag("POLYDATA_ACTIVE_MARKET_PREFER_LOB_READY", True):
        return rows
    manager = ctx.get("LOB_RUNTIME_MANAGER")
    if manager is None or not hasattr(manager, "get_market_snapshot"):
        return rows
    max_checks = min(len(rows), max(0, DEFAULT_ACTIVE_MARKET_LOB_PREFETCH_LIMIT), max(target_count * 3, target_count))
    if max_checks <= 0:
        return rows

    ready: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    for row in rows[:max_checks]:
        market_id = row.get("id")
        yes_token_id = str(row.get("yes_token_id") or "").strip()
        no_token_id = str(row.get("no_token_id") or "").strip()
        if market_id is None or not yes_token_id or not no_token_id:
            deferred.append(row)
            continue
        try:
            payload = manager.get_market_snapshot(
                market_id=int(market_id),
                yes_token_id=yes_token_id,
                no_token_id=no_token_id,
                market_title=str(row.get("title") or ""),
            )
        except Exception:
            deferred.append(row)
            continue
        if _lob_payload_has_levels(payload):
            ready.append(row)
        else:
            deferred.append(row)
    if not ready:
        return rows
    return [*ready, *deferred, *rows[max_checks:]]


def _parse_numeric_target(value: str, suffix: str | None = None) -> Optional[float]:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        numeric = float(text)
    except (TypeError, ValueError):
        return None
    normalized_suffix = str(suffix or "").strip().lower()
    if normalized_suffix == "k":
        numeric *= 1_000
    elif normalized_suffix == "m":
        numeric *= 1_000_000
    elif normalized_suffix == "b":
        numeric *= 1_000_000_000
    return numeric


def _resolve_yahoo_symbol(title: str, description: str) -> Optional[str]:
    yahoo_match = YAHOO_QUOTE_RE.search(description)
    if yahoo_match:
        return unquote(yahoo_match.group(1))

    pair_match = PAIR_RE.search(description)
    if pair_match:
        base, quote = pair_match.group(1).split("/", 1)
        base = base.strip().upper()
        quote = quote.strip().upper()
        if quote in {"USDT", "USD"}:
            return f"{base}-USD"

    haystack = f"{title} {description}".lower()
    for label, symbol in NAME_TO_YAHOO_SYMBOL.items():
        if label in haystack:
            return symbol
    return None


def _extract_market_chart_context(ctx: dict, market: Optional[Dict[str, Any]], range_name: str) -> Optional[Dict[str, Any]]:
    if not market:
        return None

    title = str(market.get("title") or "").strip()
    description = str(market.get("description") or "").strip()
    if not title and not description:
        return None

    title_match = PRICE_TARGET_RE.search(title)
    desc_match = PRICE_TARGET_RE.search(description)
    target_match = title_match or desc_match
    target_price = None
    if target_match:
        target_price = _parse_numeric_target(target_match.group(1), target_match.group(2))

    pair_match = PAIR_RE.search(description)
    pair_label = pair_match.group(1) if pair_match else None
    yahoo_symbol = _resolve_yahoo_symbol(title, description)
    is_up_down = "up or down" in title.lower() or "close price is greater than or equal to the open price" in description.lower()
    is_price_target = target_price is not None and (
        "price specified in the title" in description.lower()
        or "hit" in title.lower()
        or "reach" in title.lower()
    )

    if not yahoo_symbol or not (is_up_down or is_price_target):
        return None

    source_label = "Yahoo Finance" if "finance.yahoo.com/quote/" in description.lower() else "Underlying"
    if "binance" in description.lower():
        source_label = "Underlying proxy"

    yahoo_interval = "5m" if range_name in {"1h", "1d"} else "30m"
    yahoo_range = "1d" if range_name == "1h" else "5d"
    snapshot = ctx["get_yahoo_market_snapshot"](yahoo_symbol, interval=yahoo_interval, range_name=yahoo_range)
    if not snapshot or not snapshot.get("points"):
        return None

    return {
        "kind": "underlying-price",
        "sourceSymbol": yahoo_symbol,
        "sourceLabel": source_label,
        "pairLabel": pair_label,
        "targetPrice": target_price,
        "targetLabel": "Target" if is_price_target else "Price to beat",
        "referenceRule": "close >= open" if is_up_down else "hit threshold",
        "currentUnderlyingPrice": snapshot.get("price"),
        "underlyingChangePercent": snapshot.get("changePercent"),
        "points": snapshot.get("points") or [],
    }


def search_markets(ctx: dict, query: str, limit: int = 10) -> Dict[str, Any]:
    cleaned = str(query or "").strip()
    if not cleaned:
        return {"items": []}
    pattern = f"%{cleaned}%"
    rows = ctx["query_all"](
        """
        SELECT id, gamma_market_id, slug, title, condition_id, question_id
        FROM markets
        WHERE title LIKE ? OR slug LIKE ? OR condition_id LIKE ? OR question_id LIKE ?
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (pattern, pattern, pattern, pattern, limit),
    )
    return {
        "items": [
            {
                "id": row.get("id"),
                "localMarketId": row.get("id"),
                "slug": row.get("slug"),
                "title": row.get("title"),
                "conditionId": row.get("condition_id"),
                "questionId": row.get("question_id"),
                "gammaMarketId": row.get("gamma_market_id"),
            }
            for row in rows
        ]
    }


def get_market_by_slug(ctx: dict, slug: str) -> Optional[dict]:
    now_iso = ctx["utc_now_iso"]()
    status_case = ctx["build_market_status_case"](now_iso)
    market = ctx["query_one"](
        f"""
        SELECT
            m.*,
            {status_case} AS status,
            COALESCE(mss_detail.settlement_code, 0) AS settlement_code,
            COALESCE(mss_detail.settlement_outcome, 'UNKNOWN') AS settlement_outcome,
            mss_detail.settlement_source,
            mss_detail.settlement_raw,
            mss_detail.settlement_event_id,
            mss_detail.settlement_event_time,
            mss_detail.settlement_transaction,
            COALESCE(mss_detail.is_trading_closed, FALSE) AS is_trading_closed,
            COALESCE(mss_detail.is_resolved, FALSE) AS is_resolved,
            COALESCE(mss_detail.is_final, FALSE) AS is_final,
            COALESCE(mss_detail.completion_status, 'OPEN') AS completion_status,
            mss_detail.completion_source,
            mss_detail.completion_time,
            COALESCE(mss_detail.gamma_closed, FALSE) AS gamma_closed,
            mss_detail.gamma_closed_time,
            mlp.latest_yes_price,
            mlp.latest_no_price,
            mlp.latest_price
        FROM markets m
        LEFT JOIN market_status_snapshot mss_detail ON mss_detail.market_id = m.id
        LEFT JOIN market_latest_prices mlp ON mlp.market_id = m.id
        WHERE m.slug = ? COLLATE NOCASE
        LIMIT 1
        """,
        (now_iso, slug),
    )
    return market or None


def get_market_by_id(ctx: dict, market_id: int) -> Optional[dict]:
    now_iso = ctx["utc_now_iso"]()
    status_case = ctx["build_market_status_case"](now_iso)
    market = ctx["query_one"](
        f"""
        SELECT
            m.*,
            {status_case} AS status,
            COALESCE(mss_detail.settlement_code, 0) AS settlement_code,
            COALESCE(mss_detail.settlement_outcome, 'UNKNOWN') AS settlement_outcome,
            mss_detail.settlement_source,
            mss_detail.settlement_raw,
            mss_detail.settlement_event_id,
            mss_detail.settlement_event_time,
            mss_detail.settlement_transaction,
            COALESCE(mss_detail.is_trading_closed, FALSE) AS is_trading_closed,
            COALESCE(mss_detail.is_resolved, FALSE) AS is_resolved,
            COALESCE(mss_detail.is_final, FALSE) AS is_final,
            COALESCE(mss_detail.completion_status, 'OPEN') AS completion_status,
            mss_detail.completion_source,
            mss_detail.completion_time,
            COALESCE(mss_detail.gamma_closed, FALSE) AS gamma_closed,
            mss_detail.gamma_closed_time,
            mlp.latest_yes_price,
            mlp.latest_no_price,
            mlp.latest_price
        FROM markets m
        LEFT JOIN market_status_snapshot mss_detail ON mss_detail.market_id = m.id
        LEFT JOIN market_latest_prices mlp ON mlp.market_id = m.id
        WHERE m.id = ?
        LIMIT 1
        """,
        (now_iso, market_id),
    )
    return market or None


def get_trades_by_market_id(ctx: dict, market_id: int, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
    clickhouse_rows = clickhouse_orderfilled_service.get_market_trades(ctx, market_id, limit=limit, offset=offset)
    if clickhouse_rows is not None:
        return clickhouse_rows
    if clickhouse_orderfilled_service.clickhouse_orderfilled_enabled():
        return []
    trade_source = ctx["get_existing_trade_read_source"]()
    if trade_source is None:
        return []
    if ctx["_identifier_name"](trade_source) == ctx["TRADE_V2_CORE_TABLE"]:
        rows = ctx["query_all"](
            f"""
            SELECT
                {ctx['get_trade_market_projection_sql']('t')}
            FROM {trade_source} t
            WHERE t.market_id = ?
            ORDER BY t.block_time DESC, t.block_number DESC, t.log_index DESC
            LIMIT ? OFFSET ?
            """,
            (market_id, limit, offset),
        )
    else:
        rows = ctx["query_all"](
            f"""
            SELECT
                tx_hash, log_index, market_id, maker, taker, price, size, side, outcome,
                token_id, timestamp, block_number, order_hash, maker_asset_id, taker_asset_id,
                maker_amount, taker_amount, fee, contract
            FROM {trade_source}
            WHERE market_id = ?
            ORDER BY timestamp DESC, block_number DESC, log_index DESC
            LIMIT ? OFFSET ?
            """,
            (market_id, limit, offset),
        )
    return [ctx["normalize_trade"](row) for row in rows]


def get_recent_trades_snapshot(ctx: dict, limit: int = 24) -> List[Dict[str, Any]]:
    cache_key = json.dumps({"limit": limit}, sort_keys=True, ensure_ascii=True)
    return ctx["get_snapshot_payload"](
        "snapshot:trades_recent",
        cache_key,
        lambda: ctx["get_recent_trades"](limit=limit),
        ttl_seconds=15,
    )


def get_oracle_events_by_market_id(ctx: dict, market_id: int, market: Optional[dict] = None) -> List[Dict[str, Any]]:
    market = market if market is not None else get_market_by_id(ctx, market_id)
    identity = MarketIdentity.from_row(market) if market else None
    backend_getter = ctx.get("get_backend")
    backend = str(backend_getter() if callable(backend_getter) else "").strip().lower()
    if backend in {"postgres", "postgresql"} and identity:
        terms = oracle_event_lookup_terms(identity)
        union_sql = "\nUNION ALL\n".join(
            f"SELECT oe.* FROM oracle_events oe WHERE oe.{column_name} = ?"
            for column_name, _value in terms
        )
        rows = ctx["query_all"](
            f"""
            WITH matched_events AS (
                {union_sql}
            ),
            dedup_events AS (
                SELECT DISTINCT ON (id) *
                FROM matched_events
                ORDER BY id
            )
            SELECT
                oe.id, oe.tx_hash, oe.block_number, oe.event_time, oe.event_status, oe.external_market_id,
                COALESCE(oe.market_id, m.id) AS market_id, COALESCE(m.title, oe.market_title) AS market_title,
                oe.matched_by, COALESCE(NULLIF(oe.question_id, ''), m.question_id) AS question_id,
                COALESCE(NULLIF(oe.condition_id, ''), m.condition_id) AS condition_id,
                oe.proposed_price, oe.settled_price, oe.payout, oe.requester, oe.proposer, oe.disputer,
                oe.proposal_transaction, oe.settlement_transaction, oe.source_adapter, oe.source_oracle,
                m.slug AS market_slug, m.category AS market_category,
                COALESCE(mss.completion_status, 'OPEN') AS completion_status,
                COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
                COALESCE(mss.is_resolved, FALSE) AS is_resolved,
                COALESCE(mss.is_final, FALSE) AS is_final,
                COALESCE(mss.settlement_code, 0) AS snapshot_settlement_code,
                COALESCE(mss.settlement_outcome, 'UNKNOWN') AS snapshot_settlement_outcome,
                mss.settlement_source AS snapshot_settlement_source
            FROM dedup_events oe
            LEFT JOIN markets m ON m.id = COALESCE(oe.market_id, ?)
            LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
            ORDER BY oe.block_number ASC NULLS LAST, oe.id ASC
            """,
            (*[value for _column_name, value in terms], market_id),
        )
        return [ctx["normalize_oracle_event"](row) for row in rows]

    if market:
        where_sql, where_params = oracle_event_lookup_clause(identity or MarketIdentity.from_row(market), "oe")
    else:
        where_sql, where_params = "oe.market_id = ?", (market_id,)
    rows = ctx["query_all"](
        f"""
        SELECT
            oe.id, oe.tx_hash, oe.block_number, oe.event_time, oe.event_status, oe.external_market_id,
            COALESCE(oe.market_id, m.id) AS market_id, COALESCE(m.title, oe.market_title) AS market_title,
            oe.matched_by, COALESCE(NULLIF(oe.question_id, ''), m.question_id) AS question_id,
            COALESCE(NULLIF(oe.condition_id, ''), m.condition_id) AS condition_id,
            oe.proposed_price, oe.settled_price, oe.payout, oe.requester, oe.proposer, oe.disputer,
            oe.proposal_transaction, oe.settlement_transaction, oe.source_adapter, oe.source_oracle,
            m.slug AS market_slug, m.category AS market_category,
            COALESCE(mss.completion_status, 'OPEN') AS completion_status,
            COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
            COALESCE(mss.is_resolved, FALSE) AS is_resolved,
            COALESCE(mss.is_final, FALSE) AS is_final,
            COALESCE(mss.settlement_code, 0) AS snapshot_settlement_code,
            COALESCE(mss.settlement_outcome, 'UNKNOWN') AS snapshot_settlement_outcome,
            mss.settlement_source AS snapshot_settlement_source
        FROM oracle_events oe
        LEFT JOIN markets m ON m.id = COALESCE(oe.market_id, ?)
        LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
        WHERE {where_sql}
        ORDER BY oe.block_number ASC, oe.id ASC
        """,
        (market_id, *where_params),
    )
    return [ctx["normalize_oracle_event"](row) for row in rows]


def get_recent_oracle_snapshot(ctx: dict, limit: int = 24) -> List[Dict[str, Any]]:
    cache_key = json.dumps({"limit": limit}, sort_keys=True, ensure_ascii=True)
    return ctx["get_snapshot_payload"](
        "snapshot:oracle_recent",
        cache_key,
        lambda: ctx["get_recent_oracle_events"](limit=limit),
        ttl_seconds=30,
    )


def _json_payload(value: Any, expected_type: type) -> Optional[Any]:
    if isinstance(value, expected_type):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        return parsed if isinstance(parsed, expected_type) else None
    return None


def _get_market_workspace_serving_row(ctx: dict, market_id: int) -> Optional[Dict[str, Any]]:
    if not ctx["table_exists"]("market_workspace_serving"):
        return None
    return ctx["query_one"](
        """
        SELECT market_id, detail_payload, price_payload, oracle_summary, content_summary, updated_at
        FROM market_workspace_serving
        WHERE market_id = ?
        LIMIT 1
        """,
        (market_id,),
    )


def _get_market_workspace_detail_payload(ctx: dict, market_id: int) -> Optional[Dict[str, Any]]:
    row = _get_market_workspace_serving_row(ctx, market_id)
    if not row:
        return None
    payload = _json_payload(row.get("detail_payload"), dict)
    if not payload:
        return None
    payload.setdefault("servingSource", "postgres")
    payload.setdefault("servingUpdatedAt", row.get("updated_at"))
    return payload


def _get_market_workspace_price_payload(ctx: dict, market_id: int) -> Optional[Dict[str, Any]]:
    row = _get_market_workspace_serving_row(ctx, market_id)
    if not row:
        return None
    payload = _json_payload(row.get("price_payload"), dict)
    if not payload:
        return None
    payload.setdefault("marketId", market_id)
    payload.setdefault("localMarketId", market_id)
    payload.setdefault("servingSource", "postgres")
    payload.setdefault("servingUpdatedAt", row.get("updated_at"))
    return payload


def _get_market_chart_serving_payload(ctx: dict, market_id: int, range_name: str, interval: str) -> Optional[Dict[str, Any]]:
    if not ctx["table_exists"]("market_chart_serving"):
        return None
    normalized_range = str(range_name or "1d").strip().lower()
    normalized_interval = str(interval or "5m").strip().lower()
    row = ctx["query_one"](
        """
        SELECT market_id, range_name, interval_name, kind, history_status, point_count, points, updated_at
        FROM market_chart_serving
        WHERE market_id = ? AND range_name = ?
        ORDER BY CASE WHEN interval_name = ? THEN 0 ELSE 1 END, updated_at DESC
        LIMIT 1
        """,
        (market_id, normalized_range, normalized_interval),
    )
    if not row:
        return None
    points = _json_payload(row.get("points"), list) or []
    history_status = str(row.get("history_status") or ("ok" if points else "missing"))
    return {
        "marketId": market_id,
        "localMarketId": market_id,
        "range": row.get("range_name") or normalized_range,
        "interval": row.get("interval_name") or normalized_interval,
        "kind": row.get("kind") or "probability",
        "historyStatus": history_status,
        "points": points,
        "servingSource": "postgres",
        "servingUpdatedAt": row.get("updated_at"),
    }


def _is_usable_market_chart_serving(payload: Optional[Dict[str, Any]]) -> bool:
    if not payload:
        return False
    status = str(payload.get("historyStatus") or "").strip().lower()
    if status == "ok":
        return True
    points = payload.get("points")
    if not isinstance(points, list) or len(points) <= 2:
        return False
    _, distinct_count = _chart_point_stats(points)
    return distinct_count > 1 and status not in {"missing", "snapshot", "flat"}


def _last_chart_price(chart: Optional[Dict[str, Any]]) -> tuple[Optional[Any], Optional[Any], Optional[Any]]:
    if not isinstance(chart, dict):
        return None, None, None
    points = chart.get("points")
    if not isinstance(points, list) or not points:
        return None, None, None
    last = points[-1]
    if not isinstance(last, dict):
        return None, None, None
    return last.get("yesPrice"), last.get("noPrice"), last.get("timestamp")


def _merge_chart_latest_price(price: Dict[str, Any], chart: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    latest_yes, latest_no, updated_at = _last_chart_price(chart)
    if latest_yes in (None, ""):
        return price
    merged = dict(price or {})
    merged["latestPrice"] = latest_yes
    merged["latestYesPrice"] = latest_yes
    if latest_no not in (None, ""):
        merged["latestNoPrice"] = latest_no
    if updated_at:
        merged["updatedAt"] = updated_at
    merged["priceSource"] = "chart-history"
    return merged


def get_market_price_summary(
    ctx: dict,
    market_id: int,
    market: Optional[dict] = None,
    *,
    include_runtime_price: bool = False,
    include_recent_stats: bool = False,
) -> Dict[str, Any]:
    if not include_runtime_price and not include_recent_stats:
        serving_payload = _get_market_workspace_price_payload(ctx, market_id)
        if serving_payload is not None:
            return serving_payload
    if market is None and not include_runtime_price and not include_recent_stats:
        cache_key = json.dumps({"marketId": int(market_id), "v": 3}, sort_keys=True, ensure_ascii=True)
        return ctx["get_snapshot_payload"](
            "snapshot:market_price_summary",
            cache_key,
            lambda: get_market_price_summary(
                ctx,
                market_id,
                market=get_market_by_id(ctx, market_id),
                include_runtime_price=False,
                include_recent_stats=False,
            ),
            ttl_seconds=90,
        )
    market = market if market is not None else get_market_by_id(ctx, market_id)
    summary_row = ctx["query_one"](
        """
        SELECT
            COALESCE(mlp.market_id, mls.market_id) AS market_id,
            COALESCE(mlp.latest_price, mls.latest_price) AS latest_price,
            COALESCE(mlp.latest_yes_price, mls.latest_price) AS latest_yes_price,
            mlp.latest_no_price,
            COALESCE(mlp.latest_trade_at, mls.latest_trade_at, mls.last_trade_at) AS latest_trade_at,
            mls.price_24h_ago AS serving_price_24h_ago,
            mls.trade_count_24h AS serving_trade_count_24h,
            mls.volume_24h AS serving_volume_24h
        FROM (SELECT ? AS market_id) requested
        LEFT JOIN market_latest_prices mlp ON mlp.market_id = requested.market_id
        LEFT JOIN market_list_serving mls ON mls.market_id = requested.market_id
        LIMIT 1
        """,
        (market_id,),
    ) or {}
    latest_price = summary_row.get("latest_yes_price") or summary_row.get("latest_price")
    latest_yes_price = summary_row.get("latest_yes_price")
    latest_no_price = summary_row.get("latest_no_price")
    updated_at = summary_row.get("latest_trade_at")
    clob_snapshot = ctx["get_market_clob_price_snapshot"](market) if include_runtime_price else None
    if clob_snapshot:
        latest_price = clob_snapshot.get("latestYesPrice") or clob_snapshot.get("latestPrice") or latest_price
        latest_yes_price = clob_snapshot.get("latestYesPrice") or latest_yes_price
        latest_no_price = clob_snapshot.get("latestNoPrice") or latest_no_price
        updated_at = clob_snapshot.get("updatedAt") or updated_at

    recent_stats = {
        "price_24h_ago": summary_row.get("serving_price_24h_ago"),
        "price_1h_ago": None,
        "trade_count_24h": summary_row.get("serving_trade_count_24h") or 0,
        "volume_24h": summary_row.get("serving_volume_24h") or 0,
    }
    trade_source = ctx["get_existing_trade_read_source"]() if include_recent_stats else None
    if trade_source is None:
        pass
    elif ctx["_identifier_name"](trade_source) == ctx["TRADE_V2_CORE_TABLE"]:
        recent_stats = ctx["query_one"](
            f"""
            SELECT
                MAX(CASE WHEN block_time >= ? THEN price END) AS price_24h_ago,
                MAX(CASE WHEN block_time >= ? THEN price END) AS price_1h_ago,
                SUM(CASE WHEN block_time >= ? THEN 1 ELSE 0 END) AS trade_count_24h,
                COALESCE(SUM(CASE WHEN block_time >= ? THEN size * price END), 0) AS volume_24h
            FROM {trade_source}
            WHERE market_id = ?
            """,
            (
                ctx["iso_days_before"](updated_at, 1) if updated_at else ctx["utc_date_days_ago"](1),
                (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                ctx["iso_days_before"](updated_at, 1) if updated_at else ctx["utc_date_days_ago"](1),
                ctx["iso_days_before"](updated_at, 1) if updated_at else ctx["utc_date_days_ago"](1),
                market_id,
            ),
        )
    else:
        recent_stats = ctx["query_one"](
            f"""
            SELECT
                MAX(CASE WHEN timestamp >= ? THEN price END) AS price_24h_ago,
                MAX(CASE WHEN timestamp >= ? THEN price END) AS price_1h_ago,
                COUNT(*) AS trade_count_24h,
                COALESCE(SUM(CASE WHEN timestamp >= ? THEN size * price END), 0) AS volume_24h
            FROM {trade_source}
            WHERE market_id = ?
            """,
            (
                ctx["iso_days_before"](updated_at, 1) if updated_at else ctx["utc_date_days_ago"](1),
                (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                ctx["iso_days_before"](updated_at, 1) if updated_at else ctx["utc_date_days_ago"](1),
                market_id,
            ),
        )

    def _change(current: Any, past: Any) -> Optional[str]:
        if current in (None, "") or past in (None, ""):
            return None
        try:
            delta = Decimal(str(current)) - Decimal(str(past))
        except (InvalidOperation, ValueError, TypeError):
            return None
        return format(delta, "f")

    return {
        "marketId": market_id,
        "localMarketId": market_id,
        "latestPrice": ctx["format_trade_decimal"](latest_yes_price or latest_price),
        "latestYesPrice": ctx["format_trade_decimal"](latest_yes_price),
        "latestNoPrice": ctx["format_trade_decimal"](latest_no_price),
        "change1h": clob_snapshot.get("change1h") if clob_snapshot else _change(latest_price, recent_stats.get("price_1h_ago")),
        "change24h": clob_snapshot.get("change24h") if clob_snapshot else _change(latest_price, recent_stats.get("price_24h_ago")),
        "volume24h": ctx["format_trade_decimal"](recent_stats.get("volume_24h")),
        "tradeCount24h": int(recent_stats.get("trade_count_24h") or 0),
        "updatedAt": updated_at,
    }


def get_market_chart_payload(
    ctx: dict,
    market_id: int,
    range_name: str = "1d",
    interval: str = "5m",
    market: Optional[dict] = None,
    price: Optional[Dict[str, Any]] = None,
    include_runtime_series: bool = True,
) -> Dict[str, Any]:
    serving_payload = _get_market_chart_serving_payload(ctx, market_id, range_name, interval)
    if _is_usable_market_chart_serving(serving_payload):
        return serving_payload
    if market is None and price is None:
        cache_key = json.dumps(
            {
                "marketId": int(market_id),
                "range": str(range_name or "1d").strip().lower(),
                "interval": str(interval or "5m").strip().lower(),
                "includeRuntimeSeries": bool(include_runtime_series),
                "v": 7,
            },
            sort_keys=True,
            ensure_ascii=True,
        )
        return ctx["get_snapshot_payload"](
            "snapshot:market_chart",
            cache_key,
            lambda: get_market_chart_payload(
                ctx,
                market_id,
                range_name=range_name,
                interval=interval,
                market=get_market_by_id(ctx, market_id),
                price=None,
                include_runtime_series=include_runtime_series,
            ),
            ttl_seconds=180,
        )
    market = market if market is not None else get_market_by_id(ctx, market_id)
    chart_context = _extract_market_chart_context(ctx, market, range_name) if include_runtime_series else None
    if chart_context:
        return {
            "marketId": market_id,
            "localMarketId": market_id,
            "range": range_name,
            "interval": interval,
            "kind": chart_context.get("kind"),
            "sourceSymbol": chart_context.get("sourceSymbol"),
            "sourceLabel": chart_context.get("sourceLabel"),
            "pairLabel": chart_context.get("pairLabel"),
            "currentUnderlyingPrice": chart_context.get("currentUnderlyingPrice"),
            "underlyingChangePercent": chart_context.get("underlyingChangePercent"),
            "targetPrice": chart_context.get("targetPrice"),
            "targetLabel": chart_context.get("targetLabel"),
            "referenceRule": chart_context.get("referenceRule"),
            "points": chart_context.get("points"),
        }
    price = price if price is not None else get_market_price_summary(ctx, market_id, market=market)
    latest = price.get("latestYesPrice") or price.get("latestPrice")
    latest_decimal = _decimal_from_any(latest)
    recent_volume = _decimal_from_any(price.get("volume24h")) or Decimal("0")
    recent_trades = int(price.get("tradeCount24h") or 0)
    points: List[Dict[str, Any]] = []
    if recent_volume > 0 or recent_trades > 0:
        limit = 400
        if range_name == "7d":
            limit = 700
        clickhouse_points = clickhouse_orderfilled_service.get_price_series(ctx, market_id, limit=limit)
        points = clickhouse_points if clickhouse_points is not None else ctx["get_trade_derived_market_price_series"](market_id, limit=limit)
    if not points:
        limit = 700 if range_name == "7d" else 400
        clickhouse_points = clickhouse_orderfilled_service.get_price_series(ctx, market_id, limit=limit)
        if clickhouse_points:
            points = clickhouse_points
    if include_runtime_series:
        point_count, distinct_count = _chart_point_stats(points)
        needs_clob_series = (
            not points
            or point_count <= 2
            or distinct_count <= 1
        )
        if needs_clob_series:
            clob_points = ctx["get_market_clob_price_series"](market, range_name=range_name, interval=interval)
            clob_count, clob_distinct_count = _chart_point_stats(clob_points)
            if clob_count > point_count and (clob_distinct_count > distinct_count or distinct_count <= 1):
                points = clob_points
    effective_range = range_name
    effective_interval = interval
    if not points and latest not in (None, ""):
        timestamp = price.get("updatedAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        points = [
            {"timestamp": timestamp, "yesPrice": latest, "noPrice": price.get("latestNoPrice")},
            {"timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "yesPrice": latest, "noPrice": price.get("latestNoPrice")},
        ]
        effective_range = "snapshot"
        effective_interval = "snapshot"
    history_status = _chart_history_status(effective_range, effective_interval, points)
    return {
        "marketId": market_id,
        "localMarketId": market_id,
        "range": effective_range,
        "interval": effective_interval,
        "kind": "probability",
        "historyStatus": history_status,
        "points": points,
    }


def get_market_oracle_payload(ctx: dict, market_id: int, market: Optional[dict] = None) -> Dict[str, Any]:
    market = market if market is not None else get_market_by_id(ctx, market_id)
    if not market:
        return {"error": "Market not found", "marketId": market_id, "_status": 404}
    cache_key = json.dumps({"marketId": int(market_id), "v": 2}, sort_keys=True, ensure_ascii=True)

    def build_payload() -> Dict[str, Any]:
        return {
            "marketId": market_id,
            "localMarketId": market_id,
            "gammaMarketId": market.get("gamma_market_id"),
            "questionId": market.get("question_id"),
            "conditionId": market.get("condition_id"),
            "oracle": market.get("oracle"),
            "currentStatus": market.get("status"),
            "completionStatus": market.get("completion_status"),
            "isTradingClosed": _truthy_flag(market.get("is_trading_closed")),
            "isResolved": _truthy_flag(market.get("is_resolved")),
            "isFinal": _truthy_flag(market.get("is_final")),
            "settlementOutcome": market.get("settlement_outcome"),
            "settlementSource": market.get("settlement_source"),
            "timeline": get_oracle_events_by_market_id(ctx, market_id, market=market),
        }

    return ctx["get_snapshot_payload"](
        "snapshot:market_oracle_payload",
        cache_key,
        build_payload,
        ttl_seconds=60,
    )


def enrich_market_rows_with_runtime_prices(
    ctx: dict,
    rows: List[Dict[str, Any]],
    *,
    max_updates: int = 18,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    enriched_rows: List[Dict[str, Any]] = [dict(row) for row in rows]
    candidates: List[tuple[int, Dict[str, Any]]] = []
    for index, normalized in enumerate(enriched_rows):
        latest_trade_at = ctx["parse_iso_datetime"](normalized.get("last_trade_at") or normalized.get("latest_trade_at"))
        is_stale = latest_trade_at is None or (now - latest_trade_at) > timedelta(hours=6)
        needs_runtime_price = force_refresh or normalized.get("latest_price") in (None, "") or is_stale
        if needs_runtime_price and len(candidates) < max_updates:
            candidates.append((index, normalized))
    if not candidates:
        return enriched_rows
    max_workers = min(6, len(candidates))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(ctx["get_market_clob_price_snapshot"], candidate): index for index, candidate in candidates}
        for future in as_completed(future_map):
            index = future_map[future]
            try:
                snapshot = future.result()
            except Exception:
                ctx["app"].logger.exception("runtime market price enrichment failed index=%s", index)
                continue
            runtime_price = snapshot.get("latestPrice") if snapshot else None
            if runtime_price not in (None, ""):
                enriched_rows[index]["latest_price"] = runtime_price
    return enriched_rows


def enrich_market_rows_with_24h_change(ctx: dict, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    market_ids = [int(row["id"]) for row in rows if row.get("id") is not None]
    if not market_ids:
        return rows
    trade_source = ctx["get_existing_trade_read_source"]()
    if trade_source is None:
        return rows

    placeholders = ", ".join("?" for _ in market_ids)
    threshold = ctx["utc_date_days_ago"](1)
    if ctx["_identifier_name"](trade_source) == ctx["TRADE_V2_CORE_TABLE"]:
        time_column = "block_time"
        order_columns = "block_time DESC, block_number DESC, log_index DESC"
        yes_price_expr = "CASE WHEN outcome_code = 2 THEN 1 - price ELSE price END"
    else:
        time_column = "timestamp"
        order_columns = "timestamp DESC, block_number DESC, log_index DESC"
        yes_price_expr = "CASE WHEN UPPER(COALESCE(outcome, '')) = 'NO' THEN 1 - price ELSE price END"

    price_rows = ctx["query_all"](
        f"""
        SELECT market_id, price
        FROM (
            SELECT
                market_id,
                {yes_price_expr} AS price,
                ROW_NUMBER() OVER (
                    PARTITION BY market_id
                    ORDER BY {order_columns}
                ) AS row_num
            FROM {trade_source}
            WHERE market_id IN ({placeholders}) AND {time_column} <= ?
        ) ranked_prices
        WHERE row_num = 1
        """,
        (*market_ids, threshold),
    )
    price_map = {int(row["market_id"]): row.get("price") for row in price_rows if row.get("market_id") is not None}
    enriched_rows: List[Dict[str, Any]] = []
    for row in rows:
        normalized = dict(row)
        market_id = normalized.get("id")
        if market_id is not None:
            normalized["price_24h_ago"] = price_map.get(int(market_id))
        enriched_rows.append(normalized)
    return enriched_rows


def _market_outcome_count(ctx: dict, row: Dict[str, Any]) -> int:
    native_count = int(row.get("native_outcome_count") or 0)
    if native_count > 1:
        return native_count
    token_ids = ctx["parse_json_list"](row.get("clob_token_ids"))
    if token_ids:
        return len(token_ids)
    yes_token = row.get("yes_token_id")
    no_token = row.get("no_token_id")
    return int(bool(yes_token)) + int(bool(no_token))


def _market_change(ctx: dict, current: Any, past: Any) -> Any:
    if current in (None, "") or past in (None, ""):
        return None
    try:
        delta = Decimal(str(current)) - Decimal(str(past))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return ctx["format_trade_decimal"](delta)


def _int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _truthy_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"", "0", "false", "none", "null"}


def _settlement_code(row: Dict[str, Any]) -> int:
    return _int_value(row.get("settlement_code"), 0)


def _settlement_payload(row: Dict[str, Any], *, include_raw: bool = False) -> Dict[str, Any]:
    payload = {
        "settlementCode": _settlement_code(row),
        "settlementOutcome": row.get("settlement_outcome") or "UNKNOWN",
        "settlementSource": row.get("settlement_source"),
        "settlementEventId": row.get("settlement_event_id"),
        "settlementEventTime": row.get("settlement_event_time"),
        "settlementTransaction": row.get("settlement_transaction"),
        "completionStatus": row.get("completion_status") or "OPEN",
        "completionSource": row.get("completion_source"),
        "completionTime": row.get("completion_time"),
        "isTradingClosed": _truthy_flag(row.get("is_trading_closed")),
        "isResolved": _truthy_flag(row.get("is_resolved")),
        "isFinal": _truthy_flag(row.get("is_final")),
        "gammaClosed": _truthy_flag(row.get("gamma_closed")),
        "gammaClosedTime": row.get("gamma_closed_time"),
    }
    if include_raw:
        payload["settlementRaw"] = row.get("settlement_raw")
    return payload


def _market_status_from_snapshot(row: Dict[str, Any], now_iso: str) -> str:
    completion_status = str(row.get("completion_status") or "").strip().upper()
    if completion_status in {"SETTLED", "CANCELLED", "UNKNOWN"} and _truthy_flag(row.get("is_final")):
        return "Settled"
    if completion_status == "DISPUTED":
        return "Disputed"
    if completion_status == "PROPOSED":
        return "Proposed"
    if _truthy_flag(row.get("is_trading_closed")):
        return "Closed"
    if _settlement_code(row) in {1, 2, 3} or _truthy_flag(row.get("has_settle")):
        return "Settled"
    if _truthy_flag(row.get("has_propose")):
        return "Proposed"
    end_date = row.get("end_date")
    if end_date not in (None, "") and str(end_date) < now_iso:
        return "Closed"
    return "Active"


def _is_postgres_ctx(ctx: dict) -> bool:
    backend_getter = ctx.get("get_backend")
    backend = str(backend_getter() if callable(backend_getter) else "").strip().lower()
    return backend in {"postgres", "postgresql"}


def _market_list_item(ctx: dict, row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": row.get("id"),
        "localMarketId": row.get("id"),
        "gammaMarketId": row.get("gamma_market_id"),
        "slug": row.get("slug"),
        "title": row.get("title"),
        "conditionId": row.get("condition_id"),
        "questionId": row.get("question_id"),
        "endDate": row.get("end_date"),
        "createdAt": row.get("created_at"),
        "latestPrice": row.get("latest_price"),
        "status": row.get("status"),
        "category": row.get("category") or "Uncategorized",
        "tags": ctx["parse_json_list"](row.get("tags")),
        "outcomeCount": _market_outcome_count(ctx, row),
        "volume24h": ctx["format_trade_decimal"](row.get("volume_24h")),
        "tradeCount24h": int(row.get("trade_count_24h") or 0),
        "change24h": row.get("change_24h") or _market_change(ctx, row.get("latest_price"), row.get("price_24h_ago")),
        "lastTradeAt": row.get("last_trade_at") or row.get("latest_trade_at"),
        **_settlement_payload(row),
    }


def _merge_clickhouse_stats(ctx: dict, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    market_ids = [int(row["id"]) for row in rows if row.get("id") is not None]
    stats = clickhouse_orderfilled_service.get_market_stats(ctx, market_ids, hours=24)
    if not stats:
        return rows
    merged_rows: List[Dict[str, Any]] = []
    for row in rows:
        market_id = row.get("id")
        if market_id is None or int(market_id) not in stats:
            merged_rows.append(row)
            continue
        stat = stats[int(market_id)]
        merged = dict(row)
        for key in ("trade_count_24h", "volume_24h", "latest_price", "last_trade_at", "latest_trade_at"):
            value = stat.get(key)
            if value not in (None, ""):
                merged[key] = value
        merged_rows.append(merged)
    return merged_rows


def _clickhouse_active_market_candidate_rows(ctx: dict, now_iso: str, limit: int) -> List[Dict[str, Any]]:
    activity_rows = clickhouse_orderfilled_service.get_recent_market_activity(
        ctx,
        limit=max(int(limit) * 20, 1000),
        hours=24,
    )
    if not activity_rows:
        return []
    stats_by_market_id = {
        int(row["market_id"]): row
        for row in activity_rows
        if row.get("market_id") is not None
    }
    market_ids = list(stats_by_market_id.keys())
    if not market_ids:
        return []
    placeholders = ", ".join("?" for _ in market_ids)
    created_cutoff = _iso_hours_before(now_iso, DEFAULT_ACTIVE_MARKET_MAX_AGE_HOURS)
    detail_rows = ctx["query_all"](
        f"""
        SELECT
            m.id,
            m.slug,
            m.condition_id,
            m.end_date,
            m.created_at,
            CASE WHEN COALESCE(mss.has_settle, FALSE) THEN 1 ELSE 0 END AS has_settle,
            CASE WHEN COALESCE(mss.has_propose, FALSE) THEN 1 ELSE 0 END AS has_propose,
            COALESCE(mss.settlement_code, 0) AS settlement_code,
            COALESCE(mss.settlement_outcome, 'UNKNOWN') AS settlement_outcome,
            mss.settlement_source,
            mss.settlement_event_id,
            mss.settlement_event_time,
            mss.settlement_transaction,
            COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
            COALESCE(mss.is_resolved, FALSE) AS is_resolved,
            COALESCE(mss.is_final, FALSE) AS is_final,
            COALESCE(mss.completion_status, 'OPEN') AS completion_status,
            mss.completion_source,
            mss.completion_time,
            COALESCE(mss.gamma_closed, FALSE) AS gamma_closed,
            mss.gamma_closed_time,
            0 AS trade_count_24h,
            0 AS volume_24h,
            NULL AS latest_price,
            NULL AS last_trade_at,
            NULL AS latest_trade_at,
            NULL AS price_24h_ago
        FROM markets m
        LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
        WHERE m.id IN ({placeholders})
          AND COALESCE(mss.has_settle, FALSE) = FALSE
          AND COALESCE(mss.has_propose, FALSE) = FALSE
          AND COALESCE(mss.is_trading_closed, FALSE) = FALSE
          AND COALESCE(mss.settlement_code, 0) = 0
          AND (m.end_date IS NULL OR m.end_date >= ?)
          AND ({_default_active_market_created_recent_sql()})
          AND {DEFAULT_ACTIVE_MARKET_EXCLUSION_SQL}
        """,
        (*market_ids, now_iso, created_cutoff),
    )
    detail_by_id = {int(row["id"]): row for row in detail_rows if row.get("id") is not None}
    candidates: List[Dict[str, Any]] = []
    for market_id in market_ids:
        row = detail_by_id.get(market_id)
        if not row:
            continue
        merged = dict(row)
        stats = stats_by_market_id.get(market_id, {})
        merged.update(
            {
                "trade_count_24h": stats.get("trade_count_24h") or 0,
                "volume_24h": stats.get("volume_24h") or 0,
                "latest_price": stats.get("latest_price"),
                "last_trade_at": stats.get("last_trade_at"),
                "latest_trade_at": stats.get("latest_trade_at"),
            }
        )
        candidates.append(merged)
        if len(candidates) >= limit:
            break
    return candidates


def _active_market_candidate_select_sql(stats_alias: str) -> str:
    return f"""
            SELECT
                m.id,
                m.slug,
                m.condition_id,
                m.end_date,
                m.created_at,
                CASE WHEN COALESCE(mss.has_settle, FALSE) THEN 1 ELSE 0 END AS has_settle,
                CASE WHEN COALESCE(mss.has_propose, FALSE) THEN 1 ELSE 0 END AS has_propose,
                COALESCE(mss.settlement_code, 0) AS settlement_code,
                COALESCE(mss.settlement_outcome, 'UNKNOWN') AS settlement_outcome,
                mss.settlement_source,
                mss.settlement_event_id,
                mss.settlement_event_time,
                mss.settlement_transaction,
                COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
                COALESCE(mss.is_resolved, FALSE) AS is_resolved,
                COALESCE(mss.is_final, FALSE) AS is_final,
                COALESCE(mss.completion_status, 'OPEN') AS completion_status,
                mss.completion_source,
                mss.completion_time,
                COALESCE(mss.gamma_closed, FALSE) AS gamma_closed,
                mss.gamma_closed_time,
                {stats_alias}.trade_count_24h,
                {stats_alias}.volume_24h,
                {stats_alias}.latest_price,
                {stats_alias}.last_trade_at,
                {stats_alias}.latest_trade_at,
                {stats_alias}.price_24h_ago
            FROM markets m
            LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
            LEFT JOIN market_list_serving {stats_alias} ON {stats_alias}.market_id = m.id
            WHERE COALESCE(mss.has_settle, FALSE) = FALSE
              AND COALESCE(mss.has_propose, FALSE) = FALSE
              AND COALESCE(mss.is_trading_closed, FALSE) = FALSE
              AND COALESCE(mss.settlement_code, 0) = 0
              AND (m.end_date IS NULL OR m.end_date >= ?)
              AND ({_default_active_market_created_recent_sql()})
              AND {DEFAULT_ACTIVE_MARKET_EXCLUSION_SQL}
              AND {_default_active_market_activity_sql(stats_alias)}
              AND {_default_active_market_price_sql(stats_alias)}
              AND {_default_active_market_recent_trade_sql(stats_alias)}
        """


def _market_list_serving_has_rows(ctx: dict, min_rows: int = 1) -> bool:
    table_exists = ctx.get("table_exists")
    if not callable(table_exists):
        return True
    if not table_exists("market_list_serving"):
        return False
    min_rows = max(1, int(min_rows))
    row = ctx["query_one"](
        "SELECT COUNT(*) AS c FROM market_list_serving WHERE volume_24h > 0 OR latest_price IS NOT NULL"
    )
    return bool(row and int(row.get("c") or 0) >= min_rows)


def _fallback_active_market_candidate_rows(ctx: dict, now_iso: str, limit: int) -> List[Dict[str, Any]]:
    created_cutoff = _iso_hours_before(now_iso, DEFAULT_ACTIVE_MARKET_MAX_AGE_HOURS)
    if _is_postgres_ctx(ctx):
        prelimit = max(int(limit) * 30, 5000)
        return ctx["query_all"](
            f"""
            WITH recent_markets AS MATERIALIZED (
                SELECT
                    m.id,
                    m.slug,
                    m.condition_id,
                    m.end_date,
                    m.created_at
                FROM markets m
                WHERE (m.end_date IS NULL OR m.end_date >= ?)
                  AND (m.created_at IS NULL OR m.created_at >= ?)
                  AND {DEFAULT_ACTIVE_MARKET_EXCLUSION_SQL}
                ORDER BY m.created_at DESC NULLS LAST, m.id DESC
                LIMIT ?
            )
            SELECT
                m.id,
                m.slug,
                m.condition_id,
                m.end_date,
                m.created_at,
                0 AS has_settle,
                0 AS has_propose,
                COALESCE(mss.settlement_code, 0) AS settlement_code,
                COALESCE(mss.settlement_outcome, 'UNKNOWN') AS settlement_outcome,
                mss.settlement_source,
                mss.settlement_event_id,
                mss.settlement_event_time,
                mss.settlement_transaction,
                COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
                COALESCE(mss.is_resolved, FALSE) AS is_resolved,
                COALESCE(mss.is_final, FALSE) AS is_final,
                COALESCE(mss.completion_status, 'OPEN') AS completion_status,
                mss.completion_source,
                mss.completion_time,
                COALESCE(mss.gamma_closed, FALSE) AS gamma_closed,
                mss.gamma_closed_time,
                0 AS trade_count_24h,
                0 AS volume_24h,
                NULL AS latest_price,
                NULL AS last_trade_at,
                NULL AS latest_trade_at,
                NULL AS price_24h_ago
            FROM recent_markets m
            JOIN market_status_snapshot mss ON mss.market_id = m.id
            WHERE mss.has_settle = FALSE
              AND mss.has_propose = FALSE
              AND mss.is_trading_closed = FALSE
              AND mss.settlement_code = 0
            ORDER BY m.created_at DESC NULLS LAST, m.id DESC
            LIMIT ?
            """,
            (now_iso, created_cutoff, prelimit, limit),
        )
    return ctx["query_all"](
        f"""
            SELECT
                m.id,
                m.slug,
                m.condition_id,
                m.end_date,
                m.created_at,
                CASE WHEN COALESCE(mss.has_settle, FALSE) THEN 1 ELSE 0 END AS has_settle,
                CASE WHEN COALESCE(mss.has_propose, FALSE) THEN 1 ELSE 0 END AS has_propose,
                COALESCE(mss.settlement_code, 0) AS settlement_code,
                COALESCE(mss.settlement_outcome, 'UNKNOWN') AS settlement_outcome,
                mss.settlement_source,
                mss.settlement_event_id,
                mss.settlement_event_time,
                mss.settlement_transaction,
                COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
                COALESCE(mss.is_resolved, FALSE) AS is_resolved,
                COALESCE(mss.is_final, FALSE) AS is_final,
                COALESCE(mss.completion_status, 'OPEN') AS completion_status,
                mss.completion_source,
                mss.completion_time,
                COALESCE(mss.gamma_closed, FALSE) AS gamma_closed,
                mss.gamma_closed_time,
                0 AS trade_count_24h,
                0 AS volume_24h,
                NULL AS latest_price,
                NULL AS last_trade_at,
                NULL AS latest_trade_at,
                NULL AS price_24h_ago
            FROM markets m
            LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
            WHERE COALESCE(mss.has_settle, FALSE) = FALSE
              AND COALESCE(mss.has_propose, FALSE) = FALSE
              AND COALESCE(mss.is_trading_closed, FALSE) = FALSE
              AND COALESCE(mss.settlement_code, 0) = 0
              AND (m.end_date IS NULL OR m.end_date >= ?)
              AND (m.created_at IS NULL OR m.created_at >= ?)
              AND {DEFAULT_ACTIVE_MARKET_EXCLUSION_SQL}
            ORDER BY m.created_at DESC NULLS LAST, m.id DESC
            LIMIT ?
        """,
        (now_iso, created_cutoff, limit),
    )


def _get_market_detail_rows_by_ids(ctx: dict, market_ids: List[int]) -> Dict[int, Dict[str, Any]]:
    if not market_ids:
        return {}
    placeholders = ", ".join("?" for _ in market_ids)
    rows = ctx["query_all"](
        f"""
            SELECT
                m.id,
                m.gamma_market_id,
                m.slug,
                m.title,
                m.condition_id,
            m.question_id,
            m.yes_token_id,
            m.no_token_id,
            m.category,
            m.tags,
            m.clob_token_ids,
            m.end_date,
            m.created_at,
            COALESCE(mss.settlement_code, 0) AS settlement_code,
            COALESCE(mss.settlement_outcome, 'UNKNOWN') AS settlement_outcome,
            mss.settlement_source,
            mss.settlement_event_id,
            mss.settlement_event_time,
            mss.settlement_transaction,
            mss.settlement_raw,
            COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
            COALESCE(mss.is_resolved, FALSE) AS is_resolved,
            COALESCE(mss.is_final, FALSE) AS is_final,
            COALESCE(mss.completion_status, 'OPEN') AS completion_status,
            mss.completion_source,
            mss.completion_time,
            COALESCE(mss.gamma_closed, FALSE) AS gamma_closed,
            mss.gamma_closed_time,
            COALESCE(mlp.latest_yes_price, mls.latest_price) AS latest_price,
            COALESCE(mls.latest_trade_at, mlp.latest_trade_at) AS latest_trade_at,
            mls.price_24h_ago
        FROM markets m
        LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
        LEFT JOIN market_list_serving mls ON mls.market_id = m.id
        LEFT JOIN market_latest_prices mlp ON mlp.market_id = m.id
        WHERE m.id IN ({placeholders})
        """,
        market_ids,
    )
    return {
        int(row["id"]): row
        for row in rows
        if row.get("id") is not None
    }


def get_markets_payload(
    ctx: dict,
    *,
    status: str = "active",
    query: str = "",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    now_iso = ctx["utc_now_iso"]()
    status = str(status or "active").strip().lower()
    query = str(query or "").strip()
    page = max(1, int(page))
    page_size = min(500, max(1, int(page_size)))
    offset = (page - 1) * page_size

    filters: List[str] = []
    params: List[Any] = []
    recent_trade_cutoff = _iso_hours_before(now_iso, 24 * 7)
    created_cutoff = _iso_hours_before(now_iso, DEFAULT_ACTIVE_MARKET_MAX_AGE_HOURS)
    serving_has_rows = _market_list_serving_has_rows(ctx, min_rows=max(page_size * 10, 1000))
    if status == "active":
        filters.append("(COALESCE(mss.is_trading_closed, FALSE) = FALSE AND COALESCE(mss.has_settle, FALSE) = FALSE AND COALESCE(mss.has_propose, FALSE) = FALSE AND COALESCE(mss.settlement_code, 0) = 0 AND (m.end_date IS NULL OR m.end_date >= ?))")
        params.append(now_iso)
        if not query:
            filters.append(f"({_default_active_market_created_recent_sql()})")
            params.append(created_cutoff)
        if not query and serving_has_rows:
            filters.append(f"({DEFAULT_ACTIVE_MARKET_EXCLUSION_SQL})")
            filters.append(_default_active_market_activity_sql("mls"))
            filters.append(_default_active_market_price_sql("mls"))
            filters.append(_default_active_market_recent_trade_sql("mls"))
            params.append(recent_trade_cutoff)
    elif status == "closed":
        filters.append("(COALESCE(mss.is_trading_closed, FALSE) = TRUE OR COALESCE(mss.has_settle, FALSE) = TRUE OR COALESCE(mss.settlement_code, 0) IN (1, 2, 3) OR (COALESCE(mss.has_settle, FALSE) = FALSE AND COALESCE(mss.has_propose, FALSE) = FALSE AND COALESCE(mss.settlement_code, 0) = 0 AND m.end_date IS NOT NULL AND m.end_date < ?))")
        params.append(now_iso)
    if query:
        pattern = f"%{query}%"
        filters.append("(m.title LIKE ? OR m.slug LIKE ? OR m.condition_id LIKE ? OR m.question_id LIKE ?)")
        params.extend([pattern, pattern, pattern, pattern])

    where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
    cache_key = json.dumps({"status": status, "query": query, "page": page, "pageSize": page_size, "v": 2}, sort_keys=True, ensure_ascii=True)

    if status == "active" and not query and page == 1:
        return get_active_markets_snapshot(ctx, page_size=page_size, include_runtime_prices=markets_runtime_prices_enabled())

    def build_payload() -> Dict[str, Any]:
        recent_14d_iso = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat().replace("+00:00", "Z")
        recent_30d_iso = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
        raw_limit = min(5000, max((offset + page_size + 1) * 6, 180))
        clickhouse_candidate_rows = (
            _clickhouse_active_market_candidate_rows(ctx, now_iso, raw_limit)
            if status == "active" and not query
            else []
        )
        if clickhouse_candidate_rows:
            candidate_rows = clickhouse_candidate_rows
        elif status == "active" and not query and not serving_has_rows:
            candidate_rows = _fallback_active_market_candidate_rows(ctx, now_iso, raw_limit)
        else:
            candidate_rows = ctx["query_all"](
                f"""
                SELECT
                    m.id,
                    m.slug,
                    m.condition_id,
                    m.end_date,
                    m.created_at,
                    CASE WHEN COALESCE(mss.has_settle, FALSE) THEN 1 ELSE 0 END AS has_settle,
                    CASE WHEN COALESCE(mss.has_propose, FALSE) THEN 1 ELSE 0 END AS has_propose,
                    COALESCE(mss.settlement_code, 0) AS settlement_code,
                    COALESCE(mss.settlement_outcome, 'UNKNOWN') AS settlement_outcome,
                    mss.settlement_source,
                    mss.settlement_event_id,
                    mss.settlement_event_time,
                    mss.settlement_transaction,
                    COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
                    COALESCE(mss.is_resolved, FALSE) AS is_resolved,
                    COALESCE(mss.is_final, FALSE) AS is_final,
                    COALESCE(mss.completion_status, 'OPEN') AS completion_status,
                    mss.completion_source,
                    mss.completion_time,
                    COALESCE(mss.gamma_closed, FALSE) AS gamma_closed,
                    mss.gamma_closed_time,
                    mls.trade_count_24h,
                    mls.volume_24h,
                    mls.latest_price,
                    mls.last_trade_at,
                    mls.latest_trade_at,
                    mls.price_24h_ago
                FROM markets m
                LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
                LEFT JOIN market_list_serving mls ON mls.market_id = m.id
                {where_clause}
                ORDER BY
                    CASE
                        WHEN m.created_at >= ? THEN 0
                        WHEN m.created_at >= ? THEN 1
                        ELSE 2
                    END ASC,
                    m.created_at DESC,
                    COALESCE(mls.trade_count_24h, 0) DESC,
                    COALESCE(mls.volume_24h, 0) DESC,
                    mls.last_trade_at DESC
                LIMIT ?
                """,
                [*params, recent_14d_iso, recent_30d_iso, raw_limit],
            )
        if status == "active" and serving_has_rows and not clickhouse_candidate_rows:
            candidate_rows = _prefer_gamma_active_candidate_rows(ctx, candidate_rows, offset + page_size + 1)
        working_candidates = candidate_rows[offset: offset + max(page_size * 3, page_size + 1)]
        if not working_candidates and candidate_rows:
            working_candidates = candidate_rows[: max(page_size * 3, page_size + 1)]
        visible_market_ids = [int(row["id"]) for row in working_candidates if row.get("id") is not None]
        detail_rows = _get_market_detail_rows_by_ids(ctx, visible_market_ids)
        visible_rows: List[Dict[str, Any]] = []
        for candidate in working_candidates:
            market_id = candidate.get("id")
            if market_id is None:
                continue
            detail_row = detail_rows.get(int(market_id))
            if not detail_row:
                continue
            normalized = dict(detail_row)
            normalized.update(
                {
                    "trade_count_24h": candidate.get("trade_count_24h"),
                    "volume_24h": candidate.get("volume_24h"),
                    "last_trade_at": candidate.get("last_trade_at") or candidate.get("latest_trade_at"),
                    "price_24h_ago": candidate.get("price_24h_ago"),
                    "has_settle": candidate.get("has_settle"),
                    "has_propose": candidate.get("has_propose"),
                    "settlement_code": candidate.get("settlement_code"),
                    "settlement_outcome": candidate.get("settlement_outcome"),
                    "settlement_source": candidate.get("settlement_source"),
                    "settlement_event_id": candidate.get("settlement_event_id"),
                    "settlement_event_time": candidate.get("settlement_event_time"),
                    "settlement_transaction": candidate.get("settlement_transaction"),
                    "is_trading_closed": candidate.get("is_trading_closed"),
                    "is_resolved": candidate.get("is_resolved"),
                    "is_final": candidate.get("is_final"),
                    "completion_status": candidate.get("completion_status"),
                    "completion_source": candidate.get("completion_source"),
                    "completion_time": candidate.get("completion_time"),
                    "gamma_closed": candidate.get("gamma_closed"),
                    "gamma_closed_time": candidate.get("gamma_closed_time"),
                }
            )
            normalized["status"] = _market_status_from_snapshot(normalized, now_iso)
            visible_rows.append(normalized)
        max_runtime_updates = min(page_size, 40 if page_size >= 80 else (24 if page_size >= 40 else 16))
        visible_rows = enrich_market_rows_with_runtime_prices(
            ctx,
            visible_rows,
            max_updates=max_runtime_updates,
        )
        if status == "active":
            visible_rows = _merge_clickhouse_stats(ctx, visible_rows)
        if status == "active":
            visible_rows = _prefer_tradeable_market_rows(visible_rows, page_size + 1)
            if not query:
                visible_rows = _coalesce_native_market_rows(visible_rows)
                visible_rows = _diversify_market_rows(visible_rows, page_size + 1, now_iso)
        has_more = len(visible_rows) > page_size
        visible_rows = visible_rows[:page_size]
        return {
            "items": [_market_list_item(ctx, row) for row in visible_rows],
            "pagination": {
                "page": page,
                "pageSize": page_size,
                "total": offset + len(visible_rows) + (1 if has_more else 0),
                "totalPages": page + (1 if has_more else 0),
                "hasMore": has_more,
            },
        }

    return ctx["get_markets_payload_cached"](cache_key, build_payload)


def build_active_markets_payload(
    ctx: dict,
    page_size: int = 40,
    *,
    include_runtime_prices: bool = False,
    include_change_24h: bool = False,
) -> Dict[str, Any]:
    now_iso = ctx["utc_now_iso"]()
    created_cutoff = _iso_hours_before(now_iso, DEFAULT_ACTIVE_MARKET_MAX_AGE_HOURS)
    raw_limit = max(page_size * 3, 180)
    clickhouse_candidate_rows = _clickhouse_active_market_candidate_rows(ctx, now_iso, raw_limit)
    if clickhouse_candidate_rows:
        candidate_rows = clickhouse_candidate_rows
    elif _market_list_serving_has_rows(ctx, min_rows=max(page_size * 10, 1000)):
        volume_candidate_rows = ctx["query_all"](
            f"""
            {_active_market_candidate_select_sql("stats_24h")}
            ORDER BY COALESCE(stats_24h.volume_24h, 0) DESC, COALESCE(stats_24h.trade_count_24h, 0) DESC, stats_24h.last_trade_at DESC, m.created_at DESC
            LIMIT ?
            """,
            (now_iso, created_cutoff, _iso_hours_before(now_iso, 24 * 7), raw_limit),
        )
        recent_candidate_rows = ctx["query_all"](
            f"""
            {_active_market_candidate_select_sql("stats_24h")}
            ORDER BY m.created_at DESC, COALESCE(stats_24h.volume_24h, 0) DESC, COALESCE(stats_24h.trade_count_24h, 0) DESC
            LIMIT ?
            """,
            (now_iso, created_cutoff, _iso_hours_before(now_iso, 24 * 7), min(raw_limit, max(page_size * 2, 80))),
        )
        candidate_rows = _blend_recent_candidate_rows(volume_candidate_rows, recent_candidate_rows, page_size)
    else:
        candidate_rows = _fallback_active_market_candidate_rows(ctx, now_iso, raw_limit)
    candidate_stats_map = {
        int(row["id"]): {
            "trade_count_24h": row.get("trade_count_24h"),
            "volume_24h": row.get("volume_24h"),
            "last_trade_at": row.get("last_trade_at") or row.get("latest_trade_at"),
            "price_24h_ago": row.get("price_24h_ago"),
            "has_settle": row.get("has_settle"),
            "has_propose": row.get("has_propose"),
            "settlement_code": row.get("settlement_code"),
            "settlement_outcome": row.get("settlement_outcome"),
            "settlement_source": row.get("settlement_source"),
            "settlement_event_id": row.get("settlement_event_id"),
            "settlement_event_time": row.get("settlement_event_time"),
            "settlement_transaction": row.get("settlement_transaction"),
            "is_trading_closed": row.get("is_trading_closed"),
            "is_resolved": row.get("is_resolved"),
            "is_final": row.get("is_final"),
            "completion_status": row.get("completion_status"),
            "completion_source": row.get("completion_source"),
            "completion_time": row.get("completion_time"),
            "gamma_closed": row.get("gamma_closed"),
            "gamma_closed_time": row.get("gamma_closed_time"),
        }
        for row in candidate_rows
        if row.get("id") is not None
    }
    ordered_market_ids: List[int] = []
    for row in candidate_rows:
        market_id = row.get("id")
        if market_id is None:
            continue
        ordered_market_ids.append(int(market_id))
        if len(ordered_market_ids) >= max(page_size * 3, page_size):
            break
    detail_rows = _get_market_detail_rows_by_ids(ctx, ordered_market_ids)
    rows: List[Dict[str, Any]] = []
    for market_id in ordered_market_ids:
        detail_row = detail_rows.get(market_id)
        if not detail_row:
            continue
        normalized = dict(detail_row)
        normalized.update(candidate_stats_map.get(market_id, {}))
        normalized["status"] = _market_status_from_snapshot(normalized, now_iso)
        rows.append(normalized)
    if include_runtime_prices:
        rows = enrich_market_rows_with_runtime_prices(
            ctx,
            rows,
            max_updates=min(page_size, 24),
            force_refresh=False,
        )
    if include_change_24h:
        rows = enrich_market_rows_with_24h_change(ctx, rows)
    rows = _merge_clickhouse_stats(ctx, rows)
    rows = _coalesce_native_market_rows(rows)
    rows = _prefer_lob_ready_market_rows(ctx, rows, page_size)
    rows = _diversify_market_rows(rows, page_size, now_iso)
    rows = rows[:page_size]
    return {
        "items": [_market_list_item(ctx, row) for row in rows],
        "pagination": {"page": 1, "pageSize": page_size, "total": len(rows), "totalPages": 1, "hasMore": False},
    }


def get_active_markets_snapshot(ctx: dict, page_size: int = 40, *, include_runtime_prices: bool = False) -> Dict[str, Any]:
    cache_key = json.dumps(
        {
            "page": 1,
            "pageSize": page_size,
            "status": "active",
            "includeRuntimePrices": include_runtime_prices,
            "includeChange24h": include_runtime_prices,
            "maxAgeHours": DEFAULT_ACTIVE_MARKET_MAX_AGE_HOURS,
            "v": 16,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    exact_payload = ctx["SNAPSHOT_STORE"].get(ACTIVE_MARKETS_SNAPSHOT_NAMESPACE, cache_key)
    if exact_payload is not None:
        ctx["set_cached_json"](ACTIVE_MARKETS_SNAPSHOT_NAMESPACE, cache_key, exact_payload, 60)
        return exact_payload

    if markets_latest_snapshot_fallback_enabled():
        latest_payload = ctx["SNAPSHOT_STORE"].get_latest_stale(ACTIVE_MARKETS_SNAPSHOT_NAMESPACE, exclude_cache_key=cache_key)
        fallback_payload = _trim_active_markets_payload(ctx, latest_payload, page_size)
        if fallback_payload is not None:
            ctx["app"].logger.info(
                "markets-active latest-snapshot-fallback page_size=%s include_runtime_prices=%s",
                page_size,
                include_runtime_prices,
            )
            ctx["SNAPSHOT_STORE"].set(ACTIVE_MARKETS_SNAPSHOT_NAMESPACE, cache_key, fallback_payload, 60)
            ctx["set_cached_json"](ACTIVE_MARKETS_SNAPSHOT_NAMESPACE, cache_key, fallback_payload, 60)
            return fallback_payload

    return ctx["get_snapshot_payload"](
        ACTIVE_MARKETS_SNAPSHOT_NAMESPACE,
        cache_key,
        lambda: build_active_markets_payload(
            ctx,
            page_size=page_size,
            include_runtime_prices=include_runtime_prices,
            include_change_24h=include_runtime_prices,
        ),
        ttl_seconds=60,
    )


def get_market_detail_payload(ctx: dict, market_id: int) -> Dict[str, Any]:
    serving_payload = _get_market_workspace_detail_payload(ctx, market_id)
    if serving_payload is not None:
        return serving_payload
    market = get_market_by_id(ctx, market_id)
    if not market:
        return {"error": "Market not found", "marketId": market_id, "_status": 404}
    cache_key = json.dumps({"marketId": int(market_id), "v": 11}, sort_keys=True, ensure_ascii=True)

    def build_payload() -> Dict[str, Any]:
        price = get_market_price_summary(
            ctx,
            market_id,
            market=market,
            include_runtime_price=False,
            include_recent_stats=False,
        )
        latest = price.get("latestYesPrice") or price.get("latestPrice")
        snapshot_time = price.get("updatedAt") or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        chart_points = (
            [
                {"timestamp": snapshot_time, "yesPrice": latest, "noPrice": price.get("latestNoPrice")},
                {"timestamp": snapshot_time, "yesPrice": latest, "noPrice": price.get("latestNoPrice")},
            ]
            if latest not in (None, "")
            else []
        )
        chart = {
            "marketId": market_id,
            "localMarketId": market_id,
            "range": "snapshot" if chart_points else "missing",
            "interval": "snapshot" if chart_points else "missing",
            "kind": "probability",
            "historyStatus": "snapshot" if chart_points else "missing",
            "points": chart_points,
        }
        oracle_payload = get_market_oracle_payload(ctx, market_id, market=market)
        oracle_events = oracle_payload.get("timeline", [])
        trades = get_trades_by_market_id(ctx, market_id, limit=24, offset=0)
        normalized_market = ctx["normalize_market"](market)
        identity = _workspace_identity(market_id, market)
        diagnostics = _workspace_diagnostics(
            market_id,
            market,
            price,
            chart,
            oracle_payload,
            trades,
        )
        return {
            "market": normalized_market,
            "localMarketId": market_id,
            "gammaMarketId": market.get("gamma_market_id"),
            "identity": identity,
            "diagnostics": diagnostics,
            "price": price,
            "chart": chart,
            "priceSeries": chart.get("points", []),
            "trades": trades,
            "oracle": oracle_payload,
            "oracleEvents": oracle_events,
            "content": None,
        }

    return ctx["get_snapshot_payload"](
        "snapshot:market_detail_bundle",
        cache_key,
        build_payload,
        ttl_seconds=90,
    )


def get_market_workspace_payload(ctx: dict, market_id: int) -> Dict[str, Any]:
    market = get_market_by_id(ctx, market_id)
    if not market:
        return {"error": "Market not found", "marketId": market_id, "_status": 404}

    detail_payload = get_market_detail_payload(ctx, market_id)
    if detail_payload.get("_status") == 404:
        return detail_payload

    identity = dict(detail_payload.get("identity") or _workspace_identity(market_id, market))
    identity.setdefault("eventId", market.get("event_id"))
    identity.setdefault("eventSlug", market.get("event_slug"))

    group = None
    event_id = str(market.get("event_id") or identity.get("eventId") or "").strip()
    if event_id:
        try:
            group = market_group_service.get_market_group_detail_payload(ctx, event_id)
        except Exception:
            ctx["app"].logger.exception("market workspace group load failed market_id=%s event_id=%s", market_id, event_id)
            group = None
    selected_outcome = _workspace_selected_outcome(group, market_id, market)
    if selected_outcome and selected_outcome.get("outcomeKey"):
        identity["selectedOutcomeKey"] = selected_outcome.get("outcomeKey")

    price = detail_payload.get("price") or get_market_price_summary(ctx, market_id, market=market)
    if not (price or {}).get("latestYesPrice") and not (price or {}).get("latestPrice"):
        price = get_market_price_summary(ctx, market_id, market=market)

    detail_chart = detail_payload.get("chart") if isinstance(detail_payload.get("chart"), dict) else None
    detail_chart_points = detail_chart.get("points") if isinstance(detail_chart, dict) else []
    chart = detail_chart if isinstance(detail_chart_points, list) and _is_usable_market_chart_serving(detail_chart) else None
    if chart is None:
        chart = get_market_chart_payload(
            ctx,
            market_id,
            range_name="1d",
            interval="5m",
            market=market,
            price=price,
            include_runtime_series=True,
        )
    price = _merge_chart_latest_price(price, chart)
    oracle_payload = detail_payload.get("oracle") or get_market_oracle_payload(ctx, market_id, market=market)
    trades = detail_payload.get("trades") if isinstance(detail_payload.get("trades"), list) else []
    if not trades:
        trades = get_trades_by_market_id(ctx, market_id, limit=24, offset=0)
    diagnostics = dict(detail_payload.get("diagnostics") or {})
    if diagnostics:
        diagnostics["workspaceContract"] = "v1"
    health = _workspace_health(
        market_id=market_id,
        identity=identity,
        price=price,
        chart=chart,
        oracle_payload=oracle_payload,
        diagnostics=diagnostics,
        group=group,
        selected_outcome=selected_outcome,
        serving_source=detail_payload.get("servingSource"),
    )
    return {
        "market": detail_payload.get("market") or ctx["normalize_market"](market),
        "identity": identity,
        "diagnostics": diagnostics,
        "health": health,
        "group": group,
        "selectedOutcome": selected_outcome,
        "price": price,
        "chart": chart,
        "trades": trades,
        "oracle": oracle_payload,
        "content": detail_payload.get("content"),
        "lob": None,
        "servingSource": detail_payload.get("servingSource") or "fallback",
        "servingUpdatedAt": detail_payload.get("servingUpdatedAt"),
        "generatedAt": ctx["utc_now_iso"](),
    }
