from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Tuple

from weather.cities import load_weather_cities
from weather.temperature_bins import parse_temperature_bin
from weather.weather_codes import describe_weather_code


GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE = "snapshot:weather:global-map"
GLOBAL_WEATHER_MAP_CACHE_KEY = "panel-v1"
DEFAULT_ITEM_LIMIT = 60

WEATHER_MARKET_TERMS = (
    "temperature",
    "highest temperature",
    "lowest temperature",
    "high temperature",
    "low temperature",
    "precipitation",
    "rain",
    "snow",
    "weather",
    "climate",
    "tornado",
    "hurricane",
    "volcano",
    "pandemic",
)
WEATHER_FAMILY_PRIORITY = {
    "highest_temperature": 0,
    "lowest_temperature": 1,
    "precipitation": 2,
    "hurricane": 3,
    "tornado": 4,
    "volcano": 5,
    "pandemic": 6,
    "global_climate": 7,
    "weather_binary": 8,
}
HURRICANE_SPORTS_FALSE_POSITIVE_TERMS = (
    "carolina hurricanes",
    "hurricanes vs",
    "vs hurricanes",
    "hurricanes win",
    "will hurricanes win",
    "nhl",
    "playoffs",
    "stanley cup",
    "eastern conference",
    "super rugby",
)
GAMMA_QUERY_TIMEOUT_SECONDS = 6
GAMMA_QUERIES_PER_CITY = 2
GAMMA_QUERY_PAUSE_SECONDS = 0.03
WEATHER_CLOB_BOOK_CACHE_NAMESPACE = "weather-clob-book"
WEATHER_CLOB_BOOK_TTL_SECONDS = 10

_LIVE_REFRESH_LOCK = threading.Lock()
_LIVE_REFRESHING: set[str] = set()
_WEATHER_CLOB_BOOK_CACHE_LOCK = threading.Lock()
_WEATHER_CLOB_BOOK_CACHE: Dict[str, Dict[str, Any]] = {}


def _utc_now_iso(ctx: dict) -> str:
    now = ctx.get("utc_now_iso")
    return now() if callable(now) else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _float(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


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
            return [part.strip() for part in text.split(",") if part.strip()]
    return [value]


def _c_to_unit(value: Any, unit: str) -> Optional[float]:
    number = _float(value)
    if number is None:
        return None
    return round((number * 9 / 5) + 32, 1) if str(unit).upper() == "F" else round(number, 1)


def _parse_ts(value: Any) -> float:
    if not value:
        return 0.0
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _date_labels(ctx: dict, days: int) -> List[Dict[str, str]]:
    now = datetime.fromisoformat(_utc_now_iso(ctx).replace("Z", "+00:00"))
    labels: List[Dict[str, str]] = []
    for offset in range(max(1, int(days or 4))):
        day = now + timedelta(days=offset)
        labels.append({"iso": day.date().isoformat(), "month": day.strftime("%B").lower(), "monthShort": day.strftime("%b").lower(), "day": str(day.day), "year": str(day.year)})
    return labels


def _normalize_text(*parts: Any) -> str:
    return " ".join(str(part or "").lower() for part in parts)


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "as_dict"):
        return row.as_dict()
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    return {}


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "t", "yes", "y", "closed", "resolved"}


def _slugify(value: Any) -> str:
    text = str(value or "").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-+", "-", text)


def _matches_alias(text: str, city: Dict[str, Any]) -> bool:
    aliases = [city.get("city"), *list(city.get("polymarket_aliases") or [])]
    for alias in aliases:
        normalized = str(alias or "").strip().lower()
        if normalized and re.search(r"(?<![a-z0-9])" + re.escape(normalized).replace(r"\ ", r"\s+") + r"(?![a-z0-9])", text):
            return True
    return False


def _matches_weather_market(text: str) -> bool:
    return any(term in text for term in WEATHER_MARKET_TERMS)


def _matches_high_temperature_market(text: str) -> bool:
    return "highest-temperature-in-" in text or "highest temperature" in text or "high temperature" in text


def _market_family(text: str) -> str:
    normalized = str(text or "").lower()
    if "hurricane" in normalized and any(term in normalized for term in HURRICANE_SPORTS_FALSE_POSITIVE_TERMS):
        return "other"
    if "highest-temperature" in normalized or "highest temperature" in normalized or "high temperature" in normalized:
        return "highest_temperature"
    if "lowest-temperature" in normalized or "lowest temperature" in normalized or "low temperature" in normalized:
        return "lowest_temperature"
    if "precipitation" in normalized or re.search(r"\b(rain|rainfall|snowfall)\b", normalized):
        return "precipitation"
    if "hurricane" in normalized:
        return "hurricane"
    if "tornado" in normalized:
        return "tornado"
    if "volcano" in normalized or "volcanic" in normalized:
        return "volcano"
    if "pandemic" in normalized or "outbreak" in normalized or "epidemic" in normalized:
        return "pandemic"
    if "climate" in normalized or "global warming" in normalized or "global temperature" in normalized:
        return "global_climate"
    if _matches_weather_market(normalized):
        return "weather_binary"
    return "other"


def _family_label(family: str) -> str:
    return {
        "highest_temperature": "High temperature",
        "lowest_temperature": "Low temperature",
        "precipitation": "Precipitation",
        "hurricane": "Hurricane",
        "tornado": "Tornado",
        "volcano": "Volcano",
        "pandemic": "Pandemic",
        "global_climate": "Global climate",
        "weather_binary": "Weather",
    }.get(family, str(family or "Weather").replace("_", " ").title())


def _extract_month_label(text: str) -> Optional[str]:
    match = re.search(r"\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b(?:\s+\d{4})?", text, re.I)
    return match.group(0).strip() if match else None


_PRECIP_RANGE_RE = re.compile(r"(?:between\s+)?(\d+(?:\.\d+)?)\s*(?:-|to|–)\s*(\d+(?:\.\d+)?)\s*(mm|millimeters?|inches?|inch|in\.?|\"|')?", re.I)
_PRECIP_SINGLE_RE = re.compile(r"(?:less than|under|below|more than|over|at least|or more|or less)?\s*(\d+(?:\.\d+)?)\s*(mm|millimeters?|inches?|inch|in\.?|\"|')", re.I)


def _normalize_precip_unit(unit: Any, fallback: str = "mm") -> str:
    text = str(unit or fallback or "mm").lower()
    if text in {'"', "'", "in", "in.", "inch", "inches"}:
        return "in"
    return "mm"


def _parse_precipitation_bin(label: Any) -> Optional[Dict[str, Any]]:
    text = str(label or "").strip()
    if not text:
        return None
    lowered = text.lower()
    range_match = _PRECIP_RANGE_RE.search(text)
    if range_match:
        low = _float(range_match.group(1))
        high = _float(range_match.group(2))
        unit = _normalize_precip_unit(range_match.group(3))
        if low is None or high is None:
            return None
        return {
            "label": text,
            "bucketType": "range",
            "minValue": low,
            "maxValue": high,
            "unit": unit,
            "sortKey": low,
            "metricType": "precipitation",
        }
    match = _PRECIP_SINGLE_RE.search(text)
    if not match:
        return None
    value = _float(match.group(1))
    unit = _normalize_precip_unit(match.group(2))
    if value is None:
        return None
    if re.search(r"\b(less than|under|below|or less)\b", lowered):
        bucket_type = "below"
        min_value = None
        max_value = value
    elif re.search(r"\b(more than|over|at least|or more|\+)\b", lowered):
        bucket_type = "above"
        min_value = value
        max_value = None
    else:
        bucket_type = "threshold"
        min_value = value
        max_value = value
    return {
        "label": text,
        "bucketType": bucket_type,
        "minValue": min_value,
        "maxValue": max_value,
        "unit": unit,
        "sortKey": value,
        "metricType": "precipitation",
    }


def _parse_generic_weather_bin(label: Any, family: str) -> Dict[str, Any]:
    text = str(label or "").strip() or _family_label(family)
    count_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:or more|\+|or higher|or fewer|or less)?", text, re.I)
    value = _float(count_match.group(1)) if count_match else None
    lowered = text.lower()
    bucket_type = "binary"
    min_value = None
    max_value = None
    if value is not None:
        if re.search(r"\b(or more|more than|at least|\+|or higher)\b", lowered):
            bucket_type = "above"
            min_value = value
        elif re.search(r"\b(or fewer|or less|less than|under|below)\b", lowered):
            bucket_type = "below"
            max_value = value
        else:
            bucket_type = "threshold"
            min_value = value
            max_value = value
    return {
        "label": text,
        "bucketType": bucket_type,
        "minValue": min_value,
        "maxValue": max_value,
        "unit": "events" if family in {"tornado", "hurricane", "volcano", "pandemic"} else "",
        "sortKey": value if value is not None else 0,
        "metricType": family,
    }


def _parse_weather_bin(label: Any, *, family: str, default_unit: str = "F") -> Optional[Dict[str, Any]]:
    if family in {"highest_temperature", "lowest_temperature"}:
        parsed = parse_temperature_bin(label, default_unit=default_unit)
        if parsed:
            parsed["metricType"] = family
        return parsed
    if family == "precipitation":
        return _parse_precipitation_bin(label) or _parse_generic_weather_bin(label, family)
    return _parse_generic_weather_bin(label, family)


def _matches_date(text: str, dates: List[Dict[str, str]]) -> bool:
    for item in dates:
        candidates = (
            item["iso"],
            f"{item['month']} {item['day']}",
            f"{item['monthShort']} {item['day']}",
            f"{item['month']} {item['day']} {item['year']}",
            f"{item['monthShort']} {item['day']} {item['year']}",
        )
        if any(candidate in text for candidate in candidates):
            return True
    return False


def _matched_date_iso(text: str, dates: List[Dict[str, str]]) -> Optional[str]:
    for item in dates:
        candidates = (
            item["iso"],
            f"{item['month']} {item['day']}",
            f"{item['monthShort']} {item['day']}",
            f"{item['month']} {item['day']} {item['year']}",
            f"{item['monthShort']} {item['day']} {item['year']}",
        )
        if any(candidate in text for candidate in candidates):
            return item["iso"]
    return None


def _date_window_bounds(ctx: dict, dates: List[Dict[str, str]]) -> Tuple[str, str]:
    now = datetime.fromisoformat(_utc_now_iso(ctx).replace("Z", "+00:00"))
    first = datetime.fromisoformat(dates[0]["iso"]).replace(tzinfo=timezone.utc) if dates else now
    last = datetime.fromisoformat(dates[-1]["iso"]).replace(tzinfo=timezone.utc) if dates else now
    start = min(now - timedelta(days=1), first - timedelta(hours=12))
    end = last + timedelta(days=2)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _weather_market_window_bounds(ctx: dict, dates: List[Dict[str, str]]) -> Tuple[str, str]:
    start, end = _date_window_bounds(ctx, dates)
    now = datetime.fromisoformat(_utc_now_iso(ctx).replace("Z", "+00:00"))
    month_end = now + timedelta(days=45)
    parsed_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
    if parsed_end < month_end:
        end = month_end.isoformat().replace("+00:00", "Z")
    return start, end


def _weather_by_city(ctx: dict, cities: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    if not cities:
        return {}
    base_url = str(getattr(ctx["SETTINGS"], "open_meteo_api_url", "") or "").strip()
    if not base_url:
        raise RuntimeError("open meteo api url missing")
    by_city: Dict[str, Dict[str, Any]] = {}
    failed_chunks = 0
    chunk_size = 20
    for offset in range(0, len(cities), chunk_size):
        chunk = cities[offset:offset + chunk_size]
        try:
            payload = ctx["http_json_get"](
                base_url,
                params={
                    "latitude": ",".join(str(city["lat"]) for city in chunk),
                    "longitude": ",".join(str(city["lon"]) for city in chunk),
                    "current": "temperature_2m,weather_code",
                    "hourly": "temperature_2m",
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "forecast_days": 7,
                    "timezone": "auto",
                },
                timeout=18,
                headers={"Accept": "application/json", "User-Agent": "polydata-weather-map/1.0"},
            )
        except Exception:
            failed_chunks += 1
            continue
        responses = payload if isinstance(payload, list) else [payload]
        for city, row in zip(chunk, responses):
            if not isinstance(row, dict):
                continue
            unit = str(city.get("unit") or "F").upper()
            current = row.get("current") if isinstance(row.get("current"), dict) else {}
            daily = row.get("daily") if isinstance(row.get("daily"), dict) else {}
            hourly = row.get("hourly") if isinstance(row.get("hourly"), dict) else {}
            hourly_times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
            hourly_temps = hourly.get("temperature_2m") if isinstance(hourly.get("temperature_2m"), list) else []
            daily_dates = daily.get("time") if isinstance(daily.get("time"), list) else []
            daily_highs = daily.get("temperature_2m_max") if isinstance(daily.get("temperature_2m_max"), list) else []
            daily_lows = daily.get("temperature_2m_min") if isinstance(daily.get("temperature_2m_min"), list) else []
            daily_rows = [
                {"date": day, "high": _c_to_unit(high, unit), "low": _c_to_unit(low, unit)}
                for day, high, low in zip(daily_dates[:7], daily_highs[:7], daily_lows[:7])
            ]
            by_city[str(city["city_id"])] = {
                "condition": describe_weather_code(current.get("weather_code")),
                "currentTemp": _c_to_unit(current.get("temperature_2m"), unit),
                "todayHigh": daily_rows[0]["high"] if daily_rows else None,
                "todayLow": daily_rows[0]["low"] if daily_rows else None,
                "forecastHigh": max([row["high"] for row in daily_rows if row.get("high") is not None], default=None),
                "hourly": [{"time": time_value, "temp": _c_to_unit(temp, unit)} for time_value, temp in zip(hourly_times[:24], hourly_temps[:24])],
                "daily": daily_rows,
                "updatedAt": current.get("time") or row.get("generationtime_ms"),
            }
    if not by_city and failed_chunks:
        raise RuntimeError("open meteo fetch failed for all chunks")
    return by_city


def _metar_by_city(ctx: dict, cities: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    ids = [str(city.get("icao") or "").strip().upper() for city in cities if city.get("icao")]
    if not ids:
        return {}
    base_url = str(getattr(ctx["SETTINGS"], "aviationweather_metar_api_url", "") or "").strip()
    payload = ctx["http_json_get"](
        base_url,
        params={"ids": ",".join(ids), "format": "json", "hours": "24"},
        timeout=18,
        headers={"Accept": "application/json", "User-Agent": "polydata-weather-map/1.0"},
    )
    rows = payload if isinstance(payload, list) else ((payload or {}).get("data") or [])
    by_icao: Dict[str, Dict[str, Any]] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        icao = str(row.get("icaoId") or row.get("station_id") or row.get("id") or "").strip().upper()
        if not icao:
            continue
        by_icao[icao] = row
    result: Dict[str, Dict[str, Any]] = {}
    for city in cities:
        row = by_icao.get(str(city.get("icao") or "").upper())
        if row:
            result[str(city["city_id"])] = {"metarTemp": _c_to_unit(row.get("temp") or row.get("temp_c"), str(city.get("unit") or "F")), "updatedAt": row.get("reportTime") or row.get("obsTime")}
    return result


def _fetch_gamma_events_for_query(ctx: dict, query: str) -> Tuple[List[Dict[str, Any]], str]:
    base_url = str(ctx["SETTINGS"].gamma_api_base or "").rstrip("/")
    if not base_url:
        return [], "empty"
    try:
        payload = ctx["http_json_get"](
            f"{base_url}/events",
            params={"active": "true", "closed": "false", "limit": 80, "q": query},
            timeout=GAMMA_QUERY_TIMEOUT_SECONDS,
            headers={"Accept": "application/json", "User-Agent": "polydata-weather-map/1.0"},
        )
    except Exception as exc:
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.exception("global weather map gamma query failed query=%s error=%s", query, exc)
        return [], "error"
    rows = payload if isinstance(payload, list) else ((payload or {}).get("events") or (payload or {}).get("data") or [])
    if not isinstance(rows, list):
        return [], "empty"
    events = [event for event in rows if isinstance(event, dict)]
    return events, "ok" if events else "empty"


def _fetch_gamma_events(ctx: dict, queries: Iterable[str]) -> Tuple[List[Dict[str, Any]], str]:
    events: List[Dict[str, Any]] = []
    seen: set[str] = set()
    statuses: List[str] = []
    for query in queries:
        rows, status = _fetch_gamma_events_for_query(ctx, query)
        statuses.append(status)
        for event in rows:
            identity = str(event.get("id") or event.get("slug") or "")
            if identity and identity not in seen:
                seen.add(identity)
                events.append(event)
        if GAMMA_QUERY_PAUSE_SECONDS > 0:
            time.sleep(GAMMA_QUERY_PAUSE_SECONDS)
    if events:
        return events, "ok"
    if statuses and all(status == "error" for status in statuses):
        return [], "error"
    if any(status == "error" for status in statuses):
        return [], "partial"
    return [], "empty"


def _market_label(event_title: str, market: Dict[str, Any]) -> str:
    label = str(market.get("groupItemTitle") or market.get("group_item_title") or "").strip()
    if label:
        return label
    question = str(market.get("question") or market.get("title") or "").strip()
    if event_title and question.startswith(event_title):
        suffix = question[len(event_title) :].strip(" -:·")
        if suffix:
            return suffix
    return question or str(market.get("slug") or market.get("id") or "temperature bin")


def _market_yes_price(market: Dict[str, Any]) -> Optional[float]:
    prices = _as_list(market.get("outcomePrices") or market.get("outcome_prices"))
    return _float(prices[0]) if prices else None


def _token_ids(market: Dict[str, Any]) -> List[str]:
    candidates = (
        market.get("clobTokenIds"),
        market.get("clob_token_ids"),
        market.get("tokens"),
        market.get("outcomeTokenIds"),
        market.get("outcome_token_ids"),
    )
    for candidate in candidates:
        values = _as_list(candidate)
        token_ids: List[str] = []
        for value in values:
            if isinstance(value, dict):
                token = value.get("token_id") or value.get("tokenId") or value.get("id")
            else:
                token = value
            if token:
                token_ids.append(str(token))
        if token_ids:
            return token_ids
    return []


def _weather_clob_stats(ctx: dict) -> Dict[str, int]:
    return ctx.setdefault(
        "_weather_clob_stats",
        {"attempts": 0, "errors": 0, "quoted": 0, "noBook": 0, "cacheHits": 0, "missingToken": 0},
    )


def _cached_clob_book(ctx: dict, token_id: str) -> Optional[Dict[str, Any]]:
    cache_key = str(token_id)
    getter = ctx.get("get_cached_runtime_payload")
    if callable(getter):
        try:
            cached = getter(WEATHER_CLOB_BOOK_CACHE_NAMESPACE, cache_key)
            if isinstance(cached, dict):
                return cached
        except Exception:
            pass
    now = time.monotonic()
    with _WEATHER_CLOB_BOOK_CACHE_LOCK:
        cached = _WEATHER_CLOB_BOOK_CACHE.get(cache_key)
        if not cached:
            return None
        if float(cached.get("expires_at") or 0) <= now:
            _WEATHER_CLOB_BOOK_CACHE.pop(cache_key, None)
            return None
        payload = cached.get("payload")
        return payload if isinstance(payload, dict) else None


def _set_cached_clob_book(ctx: dict, token_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cache_key = str(token_id)
    setter = ctx.get("set_cached_runtime_payload")
    if callable(setter):
        try:
            setter(WEATHER_CLOB_BOOK_CACHE_NAMESPACE, cache_key, payload, ttl_seconds=WEATHER_CLOB_BOOK_TTL_SECONDS)
        except TypeError:
            try:
                setter(WEATHER_CLOB_BOOK_CACHE_NAMESPACE, cache_key, payload, WEATHER_CLOB_BOOK_TTL_SECONDS)
            except Exception:
                pass
        except Exception:
            pass
    with _WEATHER_CLOB_BOOK_CACHE_LOCK:
        _WEATHER_CLOB_BOOK_CACHE[cache_key] = {
            "payload": payload,
            "expires_at": time.monotonic() + WEATHER_CLOB_BOOK_TTL_SECONDS,
        }
    return payload


def _empty_clob_quote(status: str, token_id: Optional[str] = None) -> Dict[str, Optional[float] | Optional[str]]:
    return {
        "bestBidYes": None,
        "bestAskYes": None,
        "bookStatus": status,
        "priceSource": "clob-book",
        "yesTokenId": token_id,
    }


def _clob_book_payload(ctx: dict, base_url: str, token_id: str) -> Dict[str, Any]:
    session_factory = ctx.get("get_clob_session")
    if callable(session_factory):
        session = session_factory()
        if session is not None:
            response = session.get(
                f"{base_url}/book",
                params={"token_id": token_id},
                timeout=min(4, int(getattr(ctx["SETTINGS"], "clob_timeout_seconds", 8) or 8)),
                headers={"Accept": "application/json", "User-Agent": "polydata-weather-map/1.0"},
            )
            if getattr(response, "status_code", None) == 404:
                return {"bookStatus": "no-book", "bids": [], "asks": []}
            response.raise_for_status()
            data = response.json() if getattr(response, "content", True) else {}
            return data if isinstance(data, dict) else {}
    getter = ctx.get("http_json_get")
    if not callable(getter):
        return {"bookStatus": "disabled", "bids": [], "asks": []}
    data = getter(
        f"{base_url}/book",
        params={"token_id": token_id},
        timeout=min(4, int(getattr(ctx["SETTINGS"], "clob_timeout_seconds", 8) or 8)),
        headers={"Accept": "application/json", "User-Agent": "polydata-weather-map/1.0"},
    )
    return data if isinstance(data, dict) else {}


def _clob_yes_quote(ctx: dict, market: Dict[str, Any]) -> Dict[str, Optional[float] | Optional[str]]:
    token_ids = _token_ids(market)
    if not token_ids:
        stats = _weather_clob_stats(ctx)
        stats["missingToken"] = int(stats.get("missingToken") or 0) + 1
        return _empty_clob_quote("missing-token")
    base_url = str(getattr(ctx["SETTINGS"], "clob_api_base", "") or "").rstrip("/")
    if not base_url:
        return _empty_clob_quote("disabled", token_ids[0])
    stats = _weather_clob_stats(ctx)
    cached = _cached_clob_book(ctx, token_ids[0])
    if cached is not None:
        stats["cacheHits"] = int(stats.get("cacheHits") or 0) + 1
        bid = _float(cached.get("bestBidYes"))
        ask = _float(cached.get("bestAskYes"))
        if bid is not None or ask is not None:
            stats["quoted"] = int(stats.get("quoted") or 0) + 1
        elif cached.get("bookStatus") == "no-book":
            stats["noBook"] = int(stats.get("noBook") or 0) + 1
        return {
            "bestBidYes": bid,
            "bestAskYes": ask,
            "bookStatus": str(cached.get("bookStatus") or "cached"),
            "priceSource": "clob-book",
            "yesTokenId": token_ids[0],
        }
    stats["attempts"] = int(stats.get("attempts") or 0) + 1
    try:
        book = _clob_book_payload(ctx, base_url, token_ids[0])
    except Exception:
        stats["errors"] = int(stats.get("errors") or 0) + 1
        payload = _empty_clob_quote("error", token_ids[0])
        return _set_cached_clob_book(ctx, token_ids[0], payload)
    bids = book.get("bids") if isinstance(book, dict) and isinstance(book.get("bids"), list) else []
    asks = book.get("asks") if isinstance(book, dict) and isinstance(book.get("asks"), list) else []
    best_bid = max((_float(row.get("price") if isinstance(row, dict) else None) for row in bids), default=None)
    best_ask = min((_float(row.get("price") if isinstance(row, dict) else None) for row in asks), default=None)
    status = "ok" if best_bid is not None or best_ask is not None else str(book.get("bookStatus") or "no-book")
    if best_bid is not None or best_ask is not None:
        stats["quoted"] = int(stats.get("quoted") or 0) + 1
    elif status == "no-book":
        stats["noBook"] = int(stats.get("noBook") or 0) + 1
    payload = {
        "bestBidYes": best_bid,
        "bestAskYes": best_ask,
        "bookStatus": status,
        "priceSource": "clob-book",
        "yesTokenId": token_ids[0],
    }
    return _set_cached_clob_book(ctx, token_ids[0], payload)


def _apply_clob_quote_to_bin(ctx: dict, row: Dict[str, Any]) -> None:
    market = row.get("_clobMarket")
    if not isinstance(market, dict):
        return
    clob = _clob_yes_quote(ctx, market)
    bid = _float(clob.get("bestBidYes"))
    ask = _float(clob.get("bestAskYes"))
    row["bestBidYes"] = bid
    row["bestAskYes"] = ask
    row["bookStatus"] = clob.get("bookStatus")
    row["yesTokenId"] = clob.get("yesTokenId")
    if bid is not None and ask is not None:
        row["midPriceYes"] = round((bid + ask) / 2, 4)
        row["priceSource"] = "clob-book"


def _strip_internal_market(rows: List[Dict[str, Any]]) -> None:
    for row in rows:
        row.pop("_clobMarket", None)


def _normalize_temperature_event(ctx: dict, event: Dict[str, Any], city: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    event_title = str(event.get("title") or "").strip()
    markets = [market for market in (event.get("markets") or []) if isinstance(market, dict) and market.get("closed") is not True]
    bins: List[Dict[str, Any]] = []
    for market in markets:
        label = _market_label(event_title, market)
        parsed = parse_temperature_bin(label, default_unit=str(city.get("unit") or "F"))
        if not parsed:
            continue
        fallback = _market_yes_price(market)
        token_ids = _token_ids(market)
        bins.append(
            {
                **parsed,
                "bestBidYes": None,
                "bestAskYes": None,
                "midPriceYes": round(float(fallback), 4) if fallback is not None else None,
                "marketSlug": market.get("slug") or market.get("market_slug"),
                "marketStatus": "live" if market.get("active") is not False else "inactive",
                "priceSource": "gamma-outcome" if fallback is not None else "missing",
                "bookStatus": "not-queried",
                "yesTokenId": token_ids[0] if token_ids else None,
                "_clobMarket": market,
            }
        )
    if not bins:
        return None
    bins.sort(key=lambda row: float(row.get("sortKey") or 0))
    top = max([row for row in bins if row.get("midPriceYes") is not None], key=lambda row: float(row.get("midPriceYes") or 0), default=None)
    if top is not None:
        _apply_clob_quote_to_bin(ctx, top)
    quoted = len([row for row in bins if row.get("midPriceYes") is not None])
    top = max([row for row in bins if row.get("midPriceYes") is not None], key=lambda row: float(row.get("midPriceYes") or 0), default=None)
    _strip_internal_market(bins)
    slug = event.get("slug")
    return {
        "eventSlug": slug,
        "eventTitle": event_title,
        "marketSource": "gamma-api",
        "eventStatus": "live" if event.get("active") is not False and event.get("closed") is not True else "inactive",
        "marketUrl": f"https://polymarket.com/event/{slug}" if slug else None,
        "quoteCoverage": f"{quoted}/{len(bins)}",
        "topBin": top,
        "bins": bins,
        "updatedAt": event.get("updatedAt") or event.get("endDate") or event.get("createdAt"),
    }


def _db_weather_market_rows(ctx: dict, dates: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], str]:
    connector = ctx.get("get_connection")
    if not callable(connector):
        return [], "empty"
    start_iso, end_iso = _weather_market_window_bounds(ctx, dates)
    conn = None
    try:
        try:
            conn = connector(ctx.get("DB_PATH"), readonly=True)
        except TypeError:
            conn = connector(ctx.get("DB_PATH"))
        for statement in (
            "SET LOCAL max_parallel_workers_per_gather = 0",
            "SET LOCAL work_mem = '4MB'",
        ):
            try:
                conn.execute(statement)
            except Exception:
                pass
        cursor = conn.execute(
            """
            SELECT
                m.id AS market_id,
                m.gamma_market_id,
                m.slug,
                m.condition_id,
                m.yes_token_id,
                m.no_token_id,
                m.clob_token_ids,
                m.title,
                m.description,
                m.end_date,
                m.created_at,
                mlp.latest_yes_price,
                mlp.latest_price AS latest_trade_price,
                mlp.latest_trade_at,
                mls.latest_price AS serving_latest_price,
                mls.latest_trade_at AS serving_latest_trade_at,
                mss.is_trading_closed,
                mss.is_resolved,
                mss.gamma_closed
            FROM markets m
            LEFT JOIN market_latest_prices mlp ON mlp.market_id = m.id
            LEFT JOIN market_list_serving mls ON mls.market_id = m.id
            LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
            WHERE
                (
                    lower(COALESCE(m.title, '')) LIKE '%%highest temperature%%'
                    OR lower(COALESCE(m.title, '')) LIKE '%%lowest temperature%%'
                    OR lower(COALESCE(m.title, '')) LIKE '%%precipitation%%'
                    OR lower(COALESCE(m.title, '')) LIKE '%%hurricane%%'
                    OR lower(COALESCE(m.title, '')) LIKE '%%tornado%%'
                    OR lower(COALESCE(m.title, '')) LIKE '%%volcano%%'
                    OR lower(COALESCE(m.title, '')) LIKE '%%pandemic%%'
                    OR lower(COALESCE(m.title, '')) LIKE '%%climate%%'
                    OR lower(COALESCE(m.title, '')) LIKE '%%global warming%%'
                    OR lower(COALESCE(m.slug, '')) LIKE 'highest-temperature-in-%%'
                    OR lower(COALESCE(m.slug, '')) LIKE 'lowest-temperature-in-%%'
                    OR lower(COALESCE(m.slug, '')) LIKE '%%precipitation%%'
                    OR lower(COALESCE(m.slug, '')) LIKE '%%hurricane%%'
                    OR lower(COALESCE(m.slug, '')) LIKE '%%tornado%%'
                    OR lower(COALESCE(m.slug, '')) LIKE '%%volcano%%'
                    OR lower(COALESCE(m.slug, '')) LIKE '%%pandemic%%'
                    OR lower(COALESCE(m.slug, '')) LIKE '%%climate%%'
                    OR lower(COALESCE(m.category, '')) = 'weather'
                )
                AND m.end_date IS NOT NULL
                AND m.end_date >= ?
                AND m.end_date <= ?
                AND COALESCE(mss.is_trading_closed, FALSE) = FALSE
                AND COALESCE(mss.is_resolved, FALSE) = FALSE
                AND COALESCE(mss.gamma_closed, FALSE) = FALSE
            ORDER BY m.end_date ASC, m.id ASC
            LIMIT 12000
            """,
            (start_iso, end_iso),
        )
        rows = [_row_to_dict(row) for row in cursor.fetchall()]
        return rows, "ok" if rows else "empty"
    except Exception as exc:
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.exception("global weather map market db query failed error=%s", exc)
        return [], "error"
    finally:
        if conn is not None and hasattr(conn, "close"):
            try:
                conn.close()
            except Exception:
                pass


def _db_temperature_rows(ctx: dict, dates: List[Dict[str, str]]) -> Tuple[List[Dict[str, Any]], str]:
    rows, status = _db_weather_market_rows(ctx, dates)
    filtered = [row for row in rows if _market_family(_normalize_text(row.get("title"), row.get("slug"))) == "highest_temperature"]
    return filtered, status if filtered else ("empty" if status == "ok" else status)


def _db_market_object(row: Dict[str, Any]) -> Dict[str, Any]:
    token_ids = _as_list(row.get("clob_token_ids"))
    if not token_ids and row.get("yes_token_id"):
        token_ids = [row.get("yes_token_id"), row.get("no_token_id")]
    return {
        "id": row.get("market_id"),
        "slug": row.get("slug"),
        "question": row.get("title"),
        "title": row.get("title"),
        "clobTokenIds": [token for token in token_ids if token],
        "active": not (_truthy(row.get("is_trading_closed")) or _truthy(row.get("is_resolved")) or _truthy(row.get("gamma_closed"))),
    }


def _db_price_fallback(row: Dict[str, Any]) -> Optional[float]:
    for key in ("latest_yes_price", "latest_trade_price", "serving_latest_price"):
        price = _float(row.get(key))
        if price is not None:
            return round(price, 4)
    return None


def _fetch_gamma_market_by_id(ctx: dict, market_id: Any) -> Optional[Dict[str, Any]]:
    if not market_id:
        return None
    cache = ctx.setdefault("_weather_gamma_market_cache", {})
    key = str(market_id)
    if key in cache:
        return cache[key]
    base_url = str(ctx["SETTINGS"].gamma_api_base or "").rstrip("/")
    if not base_url:
        cache[key] = None
        return None
    stats = ctx.setdefault("_weather_gamma_market_stats", {"attempts": 0, "errors": 0, "priced": 0})
    stats["attempts"] = int(stats.get("attempts") or 0) + 1
    try:
        payload = ctx["http_json_get"](
            f"{base_url}/markets/{key}",
            timeout=GAMMA_QUERY_TIMEOUT_SECONDS,
            headers={"Accept": "application/json", "User-Agent": "polydata-weather-map/1.0"},
        )
    except Exception:
        stats["errors"] = int(stats.get("errors") or 0) + 1
        cache[key] = None
        return None
    market = payload if isinstance(payload, dict) else None
    if market and _market_yes_price(market) is not None:
        stats["priced"] = int(stats.get("priced") or 0) + 1
    cache[key] = market
    return market


def _gamma_price_fallback(ctx: dict, row: Dict[str, Any]) -> Tuple[Optional[float], Optional[Dict[str, Any]]]:
    market = _fetch_gamma_market_by_id(ctx, row.get("gamma_market_id"))
    price = _market_yes_price(market or {})
    return (round(price, 4) if price is not None else None), market


def _prefetch_gamma_markets(ctx: dict, rows: Iterable[Dict[str, Any]]) -> None:
    cache = ctx.setdefault("_weather_gamma_market_cache", {})
    ids: List[str] = []
    seen: set[str] = set()
    for row in rows:
        if _db_price_fallback(row) is not None:
            continue
        market_id = row.get("gamma_market_id")
        if not market_id:
            continue
        key = str(market_id)
        if key in seen or key in cache:
            continue
        seen.add(key)
        ids.append(key)
    if not ids:
        return
    max_workers = max(1, min(16, len(ids)))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="weather-gamma-market") as executor:
        futures = [executor.submit(_fetch_gamma_market_by_id, ctx, market_id) for market_id in ids]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass


def _normalize_temperature_db_group(ctx: dict, city: Dict[str, Any], date_iso: str, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    bins: List[Dict[str, Any]] = []
    for row in rows:
        market = _db_market_object(row)
        label = str(row.get("title") or row.get("slug") or "").strip()
        parsed = parse_temperature_bin(label, default_unit=str(city.get("unit") or "F"))
        if not parsed:
            continue
        fallback = _db_price_fallback(row)
        fallback_source = "db-latest" if fallback is not None else "missing"
        gamma_market = None
        if fallback is None:
            fallback, gamma_market = _gamma_price_fallback(ctx, row)
            fallback_source = "gamma-outcome" if fallback is not None else "missing"
        if gamma_market:
            market = {**market, **gamma_market}
        token_ids = _token_ids(market)
        bins.append(
            {
                **parsed,
                "bestBidYes": None,
                "bestAskYes": None,
                "midPriceYes": round(float(fallback), 4) if fallback is not None else None,
                "marketId": row.get("market_id"),
                "marketSlug": row.get("slug"),
                "marketStatus": "live" if market.get("active") else "inactive",
                "priceSource": fallback_source,
                "bookStatus": "not-queried",
                "yesTokenId": token_ids[0] if token_ids else None,
                "_clobMarket": market,
            }
        )
    if not bins:
        return None
    bins.sort(key=lambda item: float(item.get("sortKey") or 0))
    top = max([row for row in bins if row.get("midPriceYes") is not None], key=lambda row: float(row.get("midPriceYes") or 0), default=None)
    if top is None:
        forecast_high = _float(city.get("forecastHigh"))
        if forecast_high is not None:
            top = min(bins, key=lambda row: abs(float(row.get("sortKey") or 0) - forecast_high))
        elif bins:
            top = bins[0]
    targets = bins if str(ctx.get("_weather_clob_scope") or "top").lower() == "all" else ([top] if top is not None else [])
    for target in targets:
        _apply_clob_quote_to_bin(ctx, target)
    quoted = len([row for row in bins if row.get("midPriceYes") is not None])
    top = max([row for row in bins if row.get("midPriceYes") is not None], key=lambda row: float(row.get("midPriceYes") or 0), default=top)
    _strip_internal_market(bins)
    city_slug = _slugify(city.get("city"))
    date_slug = ""
    try:
        parsed_date = datetime.fromisoformat(date_iso)
        date_slug = parsed_date.strftime("on-%B-%-d-%Y").lower()
    except Exception:
        date_slug = date_iso
    event_slug = f"highest-temperature-in-{city_slug}-{date_slug}".strip("-")
    updated_at = max(
        (
            _json_safe_value(row.get("serving_latest_trade_at") or row.get("latest_trade_at") or row.get("end_date") or row.get("created_at"))
            for row in rows
        ),
        key=_parse_ts,
        default=None,
    )
    return {
        "eventSlug": event_slug,
        "eventTitle": f"Highest temperature in {city.get('city')} on {date_iso}?",
        "marketSource": "psql-db",
        "marketFamily": "highest_temperature",
        "marketFamilyLabel": _family_label("highest_temperature"),
        "metricType": "highest_temperature",
        "eventStatus": "live" if any((not _truthy(row.get("is_trading_closed")) and not _truthy(row.get("is_resolved")) and not _truthy(row.get("gamma_closed"))) for row in rows) else "inactive",
        "marketUrl": f"https://polymarket.com/event/{event_slug}",
        "quoteCoverage": f"{quoted}/{len(bins)}",
        "topBin": top,
        "bins": bins,
        "updatedAt": updated_at,
    }


def _normalize_weather_db_group(ctx: dict, city: Optional[Dict[str, Any]], date_iso: str, family: str, rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if family == "highest_temperature" and city is not None:
        return _normalize_temperature_db_group(ctx, city, date_iso, rows)
    bins: List[Dict[str, Any]] = []
    default_unit = str((city or {}).get("unit") or "F")
    for row in rows:
        market = _db_market_object(row)
        label = str(row.get("title") or row.get("slug") or "").strip()
        parsed = _parse_weather_bin(label, family=family, default_unit=default_unit)
        if not parsed:
            continue
        fallback = _db_price_fallback(row)
        fallback_source = "db-latest" if fallback is not None else "missing"
        gamma_market = None
        if fallback is None:
            fallback, gamma_market = _gamma_price_fallback(ctx, row)
            fallback_source = "gamma-outcome" if fallback is not None else "missing"
        if gamma_market:
            market = {**market, **gamma_market}
        token_ids = _token_ids(market)
        bins.append(
            {
                **parsed,
                "bestBidYes": None,
                "bestAskYes": None,
                "midPriceYes": round(float(fallback), 4) if fallback is not None else None,
                "marketId": row.get("market_id"),
                "marketSlug": row.get("slug"),
                "marketStatus": "live" if market.get("active") else "inactive",
                "priceSource": fallback_source,
                "bookStatus": "not-queried",
                "yesTokenId": token_ids[0] if token_ids else None,
                "marketFamily": family,
                "_clobMarket": market,
            }
        )
    if not bins:
        return None
    bins.sort(key=lambda item: float(item.get("sortKey") or 0))
    top = max([row for row in bins if row.get("midPriceYes") is not None], key=lambda row: float(row.get("midPriceYes") or 0), default=bins[0])
    targets = bins if str(ctx.get("_weather_clob_scope") or "top").lower() == "all" else ([top] if top is not None else [])
    for target in targets:
        _apply_clob_quote_to_bin(ctx, target)
    quoted = len([row for row in bins if row.get("midPriceYes") is not None])
    top = max([row for row in bins if row.get("midPriceYes") is not None], key=lambda row: float(row.get("midPriceYes") or 0), default=top)
    _strip_internal_market(bins)
    city_name = (city or {}).get("city") or "Global"
    updated_at = max(
        (
            _json_safe_value(row.get("serving_latest_trade_at") or row.get("latest_trade_at") or row.get("end_date") or row.get("created_at"))
            for row in rows
        ),
        key=_parse_ts,
        default=None,
    )
    event_slug = str(rows[0].get("slug") or f"{_slugify(city_name)}-{family}-{date_iso}").strip()
    titles = [str(row.get("title") or "").strip() for row in rows if row.get("title")]
    return {
        "eventSlug": event_slug,
        "eventTitle": titles[0] if len(rows) == 1 and titles else f"{_family_label(family)} in {city_name}",
        "marketSource": "psql-db",
        "marketFamily": family,
        "marketFamilyLabel": _family_label(family),
        "metricType": family,
        "eventStatus": "live" if any((not _truthy(row.get("is_trading_closed")) and not _truthy(row.get("is_resolved")) and not _truthy(row.get("gamma_closed"))) for row in rows) else "inactive",
        "marketUrl": f"https://polymarket.com/event/{event_slug}" if event_slug else None,
        "quoteCoverage": f"{quoted}/{len(bins)}",
        "topBin": top,
        "bins": bins,
        "updatedAt": updated_at,
    }


def _db_markets_by_city(ctx: dict, cities: List[Dict[str, Any]], dates: List[Dict[str, str]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    rows, db_status = _db_weather_market_rows(ctx, dates)
    if not rows:
        return {}, {str(city["city_id"]): db_status for city in cities}

    date_order = {item["iso"]: index for index, item in enumerate(dates)}
    grouped: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
    city_by_id = {str(city["city_id"]): city for city in cities}
    family_counts: Dict[str, int] = {}
    unmapped: List[Dict[str, Any]] = []
    for row in rows:
        if _truthy(row.get("is_trading_closed")) or _truthy(row.get("is_resolved")) or _truthy(row.get("gamma_closed")):
            continue
        haystack = _normalize_text(row.get("title"), row.get("description"), row.get("slug"))
        family = _market_family(haystack)
        if family == "other":
            continue
        family_counts[family] = family_counts.get(family, 0) + 1
        date_iso = _matched_date_iso(haystack, dates)
        if not date_iso:
            end_value = row.get("end_date")
            if end_value:
                try:
                    date_iso = datetime.fromisoformat(str(end_value).replace("Z", "+00:00")).date().isoformat()
                except Exception:
                    date_iso = _extract_month_label(haystack) or "rolling"
            else:
                date_iso = _extract_month_label(haystack) or "rolling"
        matched_city = False
        for city in cities:
            if _matches_alias(haystack, city):
                grouped.setdefault((str(city["city_id"]), date_iso, family), []).append(row)
                matched_city = True
                break
        if not matched_city:
            unmapped.append({
                "marketId": row.get("market_id"),
                "title": row.get("title"),
                "slug": row.get("slug"),
                "family": family,
                "endDate": _json_safe_value(row.get("end_date")),
            })

    result: Dict[str, Dict[str, Any]] = {}
    source_states: Dict[str, str] = {}
    selected_groups: Dict[str, List[Tuple[Dict[str, Any], str, str, List[Dict[str, Any]]]]] = {}
    for city_id, city in city_by_id.items():
        candidate_groups: List[Tuple[int, int, int, float, str, str, List[Dict[str, Any]]]] = []
        for (group_city_id, date_iso, family), group_rows in grouped.items():
            if group_city_id != city_id:
                continue
            newest = max((_parse_ts(row.get("serving_latest_trade_at") or row.get("latest_trade_at") or row.get("end_date") or row.get("created_at")) for row in group_rows), default=0.0)
            candidate_groups.append((WEATHER_FAMILY_PRIORITY.get(family, 99), date_order.get(date_iso, 999), -len(group_rows), -newest, date_iso, family, group_rows))
        candidate_groups.sort(key=lambda item: (item[0], item[1], item[2]))
        if candidate_groups:
            selected_groups[city_id] = [(city, date_iso, family, group_rows) for _, _, _, _, date_iso, family, group_rows in candidate_groups[:6]]
        else:
            source_states[city_id] = "empty" if db_status == "ok" else db_status

    _prefetch_gamma_markets(ctx, (row for groups in selected_groups.values() for _, _, _, group_rows in groups for row in group_rows))
    for city_id, groups in selected_groups.items():
        normalized_groups = [
            normalized
            for city, date_iso, family, group_rows in groups
            for normalized in [_normalize_weather_db_group(ctx, city, date_iso, family, group_rows)]
            if normalized
        ]
        if normalized_groups:
            primary = normalized_groups[0]
            result[city_id] = {
                **primary,
                "markets": normalized_groups,
                "marketFamilies": sorted({str(group.get("marketFamily") or "") for group in normalized_groups if group.get("marketFamily")}),
            }
            source_states[city_id] = "ok"
        else:
            source_states[city_id] = "partial"
    ctx["_weather_family_counts"] = family_counts
    ctx["_weather_unmapped_markets"] = unmapped[:80]
    return result, source_states


def _market_source_status(stats: Dict[str, Any]) -> str:
    if stats.get("match"):
        return "ok"
    query_statuses = list(stats.get("queryStatuses") or [])
    if query_statuses and all(status == "error" for status in query_statuses):
        return "error"
    if any(status == "error" for status in query_statuses):
        return "partial"
    return "empty"


def _markets_by_city(ctx: dict, cities: List[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    dates = _date_labels(ctx, int(getattr(ctx["SETTINGS"], "global_weather_market_days", 4) or 4))
    result, source_states = _db_markets_by_city(ctx, cities, dates)
    missing_cities = [city for city in cities if str(city["city_id"]) not in result]
    for city in missing_cities:
        city_id = str(city["city_id"])
        name = str(city.get("city") or "").strip()
        queries = [f"{name} temperature", f"{name} highest temperature"][:GAMMA_QUERIES_PER_CITY]
        events, query_status = _fetch_gamma_events(ctx, queries)
        stats = {"queryStatuses": [query_status], "match": False}
        matches: List[Dict[str, Any]] = []
        for event in events:
            haystack = _normalize_text(event.get("title"), event.get("slug"), " ".join(str((market or {}).get("question") or "") for market in event.get("markets") or []))
            if _matches_alias(haystack, city) and _matches_weather_market(haystack) and _matches_date(haystack, dates):
                normalized = _normalize_temperature_event(ctx, event, city)
                if normalized:
                    matches.append(normalized)
        if matches:
            matches.sort(key=lambda row: (_parse_ts(row.get("updatedAt")), len(row.get("bins") or [])), reverse=True)
            result[city_id] = matches[0]
            stats["match"] = True
        gamma_status = _market_source_status(stats)
        prior_status = source_states.get(city_id)
        if gamma_status == "ok" or prior_status in {None, "", "empty"}:
            source_states[city_id] = gamma_status
        else:
            source_states[city_id] = prior_status
    return result, source_states


def _aggregate_source(values: Iterable[str], *, empty_value: str = "empty") -> str:
    states = [str(value or "") for value in values if value]
    if not states:
        return empty_value
    if any(state == "ok" for state in states):
        return "partial" if any(state in {"error", "partial"} for state in states) else "ok"
    if any(state == "partial" for state in states):
        return "partial"
    if all(state == "error" for state in states):
        return "error"
    return empty_value


def _source_status(value: bool) -> str:
    return "ok" if value else "error"


def build_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    mapped = [
        item for item in items
        if item.get("currentTemp") is not None or item.get("metarTemp") is not None
    ]
    markets = [item for item in items if item.get("eventSlug")]
    stale = [item for item in items if "error" in set((item.get("sourceStates") or {}).values())]
    hottest = max(
        mapped,
        key=lambda row: float(
            row.get("forecastHigh")
            if row.get("forecastHigh") is not None
            else row.get("currentTemp")
            if row.get("currentTemp") is not None
            else row.get("metarTemp")
            if row.get("metarTemp") is not None
            else -999
        ),
        default=None,
    )
    family_counts: Dict[str, int] = {}
    for item in items:
        for market in item.get("markets") or ([] if not item.get("marketFamily") else [item]):
            family = str((market or {}).get("marketFamily") or "").strip()
            if family:
                family_counts[family] = family_counts.get(family, 0) + 1
    return {
        "cityCount": len(items),
        "mappedCount": len(mapped),
        "liveMarketCount": len(markets),
        "staleCount": len(stale),
        "hottestCity": hottest,
        "marketFamilyCounts": family_counts,
    }


_WEATHER_CARRY_FORWARD_FIELDS = (
    "currentTemp",
    "condition",
    "weatherCode",
    "todayHigh",
    "todayLow",
    "forecastHigh",
    "hourly",
    "daily",
    "weatherUpdatedAt",
)


def _is_missing_weather_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def merge_weather_series_from_previous(payload: Dict[str, Any], previous: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Keep usable Open-Meteo series when a fresh build only has market/METAR data."""
    if not isinstance(payload, dict) or not isinstance(previous, dict):
        return payload
    previous_items = {
        str(item.get("cityId") or ""): item
        for item in (previous.get("items") or [])
        if isinstance(item, dict) and item.get("cityId")
    }
    if not previous_items:
        return payload
    changed = False
    next_items: List[Dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        previous_item = previous_items.get(str(item.get("cityId") or ""))
        if not previous_item:
            next_items.append(item)
            continue
        next_item = dict(item)
        carried_fields: List[str] = []
        for field in _WEATHER_CARRY_FORWARD_FIELDS:
            if _is_missing_weather_value(next_item.get(field)) and not _is_missing_weather_value(previous_item.get(field)):
                next_item[field] = previous_item.get(field)
                carried_fields.append(field)
        if carried_fields:
            source_states = dict(next_item.get("sourceStates") or {})
            if source_states.get("openMeteo") == "error":
                source_states["openMeteo"] = "stale"
            next_item["sourceStates"] = source_states
            next_item["weatherCarryForward"] = True
            next_item["weatherCarryForwardFields"] = carried_fields
            changed = True
        next_items.append(next_item)
    if not changed:
        return payload
    next_payload = {**payload, "items": next_items}
    next_payload["summary"] = build_summary(next_items)
    previous_summary = previous.get("summary") if isinstance(previous.get("summary"), dict) else {}
    if isinstance(previous_summary, dict):
        next_payload["summary"]["marketFamilyCounts"] = (payload.get("summary") or {}).get("marketFamilyCounts") or previous_summary.get("marketFamilyCounts") or {}
        next_payload["summary"]["unmappedMarketCount"] = (payload.get("summary") or {}).get("unmappedMarketCount") or previous_summary.get("unmappedMarketCount") or 0
    sources = dict(next_payload.get("sources") or {})
    if sources.get("openMeteo") == "error":
        sources["openMeteo"] = "stale"
    next_payload["sources"] = sources
    if next_payload.get("status") == "warming" and next_payload["summary"].get("mappedCount"):
        next_payload["status"] = "degraded" if any(value in {"error", "partial", "stale"} for value in sources.values()) else "ok"
    return next_payload


def build_global_weather_map_payload(ctx: dict, *, limit: int = DEFAULT_ITEM_LIMIT) -> Dict[str, Any]:
    cities = load_weather_cities(limit=max(limit or DEFAULT_ITEM_LIMIT, DEFAULT_ITEM_LIMIT))
    sources: Dict[str, str] = {}
    try:
        weather = _weather_by_city(ctx, cities)
        sources["openMeteo"] = _source_status(bool(weather))
    except Exception as exc:
        weather = {}
        sources["openMeteo"] = "error"
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.exception("global weather map open-meteo fetch failed error=%s", exc)
    try:
        metar = _metar_by_city(ctx, cities)
        sources["aviationWeather"] = _source_status(bool(metar))
    except Exception as exc:
        metar = {}
        sources["aviationWeather"] = "error"
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.exception("global weather map metar fetch failed error=%s", exc)
    try:
        markets, market_source_states = _markets_by_city(ctx, cities)
        sources["gamma"] = _aggregate_source(market_source_states.values())
        clob_stats = ctx.get("_weather_clob_stats") or {}
        clob_attempts = int(clob_stats.get("attempts") or 0)
        clob_errors = int(clob_stats.get("errors") or 0)
        clob_quoted = int(clob_stats.get("quoted") or 0)
        clob_no_book = int(clob_stats.get("noBook") or 0)
        clob_cache_hits = int(clob_stats.get("cacheHits") or 0)
        if clob_attempts == 0 and clob_cache_hits == 0:
            sources["clob"] = "empty"
        elif clob_quoted > 0 and clob_errors == 0:
            sources["clob"] = "ok"
        elif clob_quoted > 0:
            sources["clob"] = "partial"
        elif clob_no_book > 0 and clob_errors == 0:
            sources["clob"] = "no-book"
        elif clob_errors > 0:
            sources["clob"] = "error"
        else:
            sources["clob"] = "empty"
    except Exception as exc:
        markets = {}
        market_source_states = {str(city["city_id"]): "error" for city in cities}
        sources["gamma"] = "error"
        sources["clob"] = "error"
        logger = getattr(ctx.get("app"), "logger", None)
        if logger is not None:
            logger.exception("global weather map polymarket fetch failed error=%s", exc)

    items: List[Dict[str, Any]] = []
    for city in cities:
        city_id = str(city["city_id"])
        weather_row = weather.get(city_id) or {}
        metar_row = metar.get(city_id) or {}
        market_row = markets.get(city_id) or {}
        item = {
            "cityId": city_id,
            "city": city.get("city"),
            "country": city.get("country"),
            "region": city.get("region"),
            "lat": city.get("lat"),
            "lon": city.get("lon"),
            "timezone": city.get("timezone"),
            "unit": city.get("unit"),
            "icao": city.get("icao"),
            "labelDx": city.get("label_dx"),
            "labelDy": city.get("label_dy"),
            **weather_row,
            **metar_row,
            **market_row,
            "markets": market_row.get("markets") or ([] if not market_row else [market_row]),
            "marketFamilies": market_row.get("marketFamilies") or ([] if not market_row.get("marketFamily") else [market_row.get("marketFamily")]),
            "sourceStates": {
                "openMeteo": "ok" if weather_row else "error",
                "metar": "ok" if metar_row else "empty",
                "polymarket": "ok" if market_row else market_source_states.get(city_id, "empty"),
            },
            "updatedAt": weather_row.get("updatedAt") or metar_row.get("updatedAt") or market_row.get("updatedAt") or _utc_now_iso(ctx),
        }
        items.append(item)
    summary = build_summary(items)
    summary["marketFamilyCounts"] = ctx.get("_weather_family_counts") or summary.get("marketFamilyCounts") or {}
    summary["unmappedMarketCount"] = len(ctx.get("_weather_unmapped_markets") or [])
    status = "ok" if summary["mappedCount"] else "warming"
    if status == "ok" and any(value == "error" for value in sources.values()):
        status = "degraded"
    return {
        "generatedAt": _utc_now_iso(ctx),
        "source": "Open-Meteo + AviationWeather + Polymarket Gamma/CLOB",
        "sourceUrl": getattr(ctx["SETTINGS"], "weather_source_url", "https://open-meteo.com/"),
        "status": status,
        "sources": sources,
        "summary": summary,
        "items": items,
        "unmappedMarkets": ctx.get("_weather_unmapped_markets") or [],
    }


def _empty_payload(ctx: dict, *, status: str = "warming") -> Dict[str, Any]:
    return {
        "generatedAt": _utc_now_iso(ctx),
        "source": "Open-Meteo + AviationWeather + Polymarket Gamma/CLOB",
        "sourceUrl": getattr(ctx["SETTINGS"], "weather_source_url", "https://open-meteo.com/"),
        "status": status,
        "sources": {},
        "summary": {"cityCount": 0, "mappedCount": 0, "liveMarketCount": 0, "staleCount": 0, "hottestCity": None, "marketFamilyCounts": {}, "unmappedMarketCount": 0},
        "items": [],
        "unmappedMarkets": [],
    }


def normalize_global_weather_map_payload(payload: Any, *, ctx: dict, limit: int = DEFAULT_ITEM_LIMIT) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty_payload(ctx, status="invalid")
    result = json.loads(json.dumps(payload, ensure_ascii=True, default=str))
    items = [item for item in (result.get("items") or []) if isinstance(item, dict)]
    result["items"] = items[: max(1, min(int(limit or DEFAULT_ITEM_LIMIT), 60))]
    result["summary"] = result.get("summary") if isinstance(result.get("summary"), dict) else build_summary(result["items"])
    result["generatedAt"] = str(result.get("generatedAt") or _utc_now_iso(ctx))
    result["status"] = str(result.get("status") or ("ok" if result["items"] else "warming"))
    result["source"] = str(result.get("source") or "Open-Meteo + AviationWeather + Polymarket Gamma/CLOB")
    result["sourceUrl"] = str(result.get("sourceUrl") or getattr(ctx["SETTINGS"], "weather_source_url", "https://open-meteo.com/"))
    result["unmappedMarkets"] = [item for item in (result.get("unmappedMarkets") or []) if isinstance(item, dict)][:120]
    return result


def _with_cache_mode(payload: Dict[str, Any], cache_mode: str) -> Dict[str, Any]:
    return {**payload, "cacheMode": cache_mode}


def _read_seeded_snapshot(ctx: dict, *, ttl_seconds: int) -> Optional[Dict[str, Any]]:
    reader = ctx.get("get_cached_json")
    if callable(reader):
        payload = reader(GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE, GLOBAL_WEATHER_MAP_CACHE_KEY)
        if isinstance(payload, dict):
            return _with_cache_mode(payload, "redis-seed")
    store = ctx.get("SNAPSHOT_STORE")
    if store is None:
        return None
    payload = store.get(GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE, GLOBAL_WEATHER_MAP_CACHE_KEY)
    if isinstance(payload, dict):
        return _with_cache_mode(payload, "sqlite-seed")
    stale = store.get_stale(GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE, GLOBAL_WEATHER_MAP_CACHE_KEY)
    if isinstance(stale, dict):
        return _with_cache_mode(stale, "stale-seed")
    return None


def _store_live(ctx: dict, payload: Dict[str, Any], *, ttl_seconds: int) -> None:
    store = ctx.get("SNAPSHOT_STORE")
    if store is not None:
        store.set(GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE, GLOBAL_WEATHER_MAP_CACHE_KEY, payload, ttl_seconds)
    setter = ctx.get("set_cached_json")
    if callable(setter):
        setter(GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE, GLOBAL_WEATHER_MAP_CACHE_KEY, payload, ttl_seconds)


def _schedule_live_refresh(ctx: dict, *, limit: int, ttl_seconds: int, reason: str) -> bool:
    refresh_key = f"{GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE}:{GLOBAL_WEATHER_MAP_CACHE_KEY}"
    with _LIVE_REFRESH_LOCK:
        if refresh_key in _LIVE_REFRESHING:
            return False
        _LIVE_REFRESHING.add(refresh_key)

    def refresh() -> None:
        logger = getattr(ctx.get("app"), "logger", None)
        previous = _read_seeded_snapshot(ctx, ttl_seconds=ttl_seconds)
        try:
            payload = _with_cache_mode(build_global_weather_map_payload(ctx, limit=limit), "live-build")
            payload = merge_weather_series_from_previous(payload, previous)
            if payload.get("items"):
                _store_live(ctx, payload, ttl_seconds=ttl_seconds)
                if logger is not None and hasattr(logger, "info"):
                    logger.info("global weather map async refresh stored reason=%s items=%s", reason, len(payload.get("items") or []))
            elif logger is not None and hasattr(logger, "warning"):
                logger.warning("global weather map async refresh skipped empty payload reason=%s", reason)
        except Exception:
            if logger is not None:
                logger.exception("global weather map async refresh failed reason=%s", reason)
        finally:
            with _LIVE_REFRESH_LOCK:
                _LIVE_REFRESHING.discard(refresh_key)

    thread = threading.Thread(target=refresh, name="global-weather-map-refresh", daemon=True)
    thread.start()
    return True


def get_global_weather_map_snapshot(ctx: dict, limit: int = DEFAULT_ITEM_LIMIT, *, allow_live_build: bool = True) -> Dict[str, Any]:
    ttl_seconds = max(60, int(getattr(ctx["SETTINGS"], "global_weather_map_ttl_seconds", 300) or 300))
    seeded = _read_seeded_snapshot(ctx, ttl_seconds=ttl_seconds)
    if seeded is not None:
        if allow_live_build and seeded.get("cacheMode") == "stale-seed":
            _schedule_live_refresh(ctx, limit=limit, ttl_seconds=ttl_seconds, reason="stale-seed")
        return normalize_global_weather_map_payload(seeded, ctx=ctx, limit=limit)
    if not allow_live_build:
        return normalize_global_weather_map_payload({**_empty_payload(ctx), "cacheMode": "seed-miss"}, ctx=ctx, limit=limit)
    scheduled = _schedule_live_refresh(ctx, limit=limit, ttl_seconds=ttl_seconds, reason="seed-miss")
    return normalize_global_weather_map_payload({**_empty_payload(ctx), "cacheMode": "seed-miss-refreshing" if scheduled else "seed-miss-refresh-inflight"}, ctx=ctx, limit=limit)
