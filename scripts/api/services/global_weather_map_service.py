from __future__ import annotations

from api.context import RuntimeResources, runtime_resources

import json
import re
from collections.abc import Mapping, MutableMapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus


from api.context import resolve_optional_service_callable, resolve_service_callable
from weather.cities import load_weather_cities
from weather.temperature_bins import parse_temperature_bin
from weather.weather_codes import describe_weather_code


GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE = "snapshot:weather:global-map"
GLOBAL_WEATHER_MAP_CACHE_KEY = "panel-v1"
DEFAULT_ITEM_LIMIT = 60
WTTR_URL = "https://wttr.in"

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



@dataclass(frozen=True)
class GlobalWeatherMapDependencies:
    resources: RuntimeResources
    settings: Any
    application: Any
    http_json_get: Callable[..., Any]
    utc_now_iso: Callable[..., Any] | None
    snapshot_store: Any
    get_cached_json: Callable[..., Any] | None
    set_cached_json: Callable[..., Any] | None
    lob_reader: Callable[[str], dict[str, Any]] | None
    get_connection: Callable[..., Any] | None
    database_path: Any
    runtime_state: MutableMapping[str, Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> GlobalWeatherMapDependencies:
        if isinstance(context, cls):
            return context
        resources = runtime_resources(context)
        return cls(
            resources=resources,
            settings=context.get("SETTINGS"),
            application=context.get("app"),
            http_json_get=resolve_service_callable(
                context,
                "http_json_get",
            ),
            utc_now_iso=resolve_optional_service_callable(
                context,
                "utc_now_iso",
            ),
            snapshot_store=context.get("SNAPSHOT_STORE"),
            get_cached_json=resolve_optional_service_callable(
                context,
                "get_cached_json",
            ),
            set_cached_json=resolve_optional_service_callable(
                context,
                "set_cached_json",
            ),
            lob_reader=resolve_optional_service_callable(context, "get_runtime_lob_by_token_payload"),
            get_connection=resolve_optional_service_callable(
                context,
                "get_connection",
            ),
            database_path=context.get("DB_PATH"),
            runtime_state=resources.weather_state,
        )


GlobalWeatherMapContext = Mapping[str, Any] | GlobalWeatherMapDependencies


def _dependencies(
    context: GlobalWeatherMapContext,
) -> GlobalWeatherMapDependencies:
    if isinstance(context, GlobalWeatherMapDependencies):
        return context
    return GlobalWeatherMapDependencies.from_context(context)


def _utc_now_iso(dependencies: GlobalWeatherMapDependencies) -> str:
    if dependencies.utc_now_iso is not None:
        return str(dependencies.utc_now_iso())
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _weather_context_state(
    dependencies: GlobalWeatherMapDependencies,
    key: str,
    initial: Dict[str, Any],
) -> Dict[str, Any]:
    state = dependencies.runtime_state.get(key)
    if isinstance(state, dict):
        return state
    with dependencies.resources.weather_state_lock:
        state = dependencies.runtime_state.get(key)
        if isinstance(state, dict):
            return state
        state = dict(initial)
        dependencies.runtime_state[key] = state
        return state


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


def _round_metric(value: Any, digits: int = 1) -> Optional[float]:
    number = _float(value)
    if number is None:
        return None
    return round(number, digits)


def _max_metric(values: List[Any], *, digits: int = 1) -> Optional[float]:
    present = [_float(value) for value in values]
    filtered = [value for value in present if value is not None]
    if not filtered:
        return None
    return round(max(filtered), digits)


def _sum_metric(values: List[Any], *, digits: int = 1) -> Optional[float]:
    present = [_float(value) for value in values]
    filtered = [value for value in present if value is not None]
    if not filtered:
        return None
    return round(sum(filtered), digits)


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


def _date_labels(
    ctx: GlobalWeatherMapContext,
    days: int,
) -> List[Dict[str, str]]:
    dependencies = _dependencies(ctx)
    now = datetime.fromisoformat(
        _utc_now_iso(dependencies).replace("Z", "+00:00"),
    )
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


def _weather_market_date_rank(
    ctx: GlobalWeatherMapContext,
    date_iso: str,
    date_order: Dict[str, int],
) -> Tuple[int, int]:
    dependencies = _dependencies(ctx)
    base_rank = date_order.get(date_iso, 999)
    try:
        market_date = datetime.fromisoformat(str(date_iso)).date()
        today = datetime.fromisoformat(
            _utc_now_iso(dependencies).replace("Z", "+00:00"),
        ).date()
    except Exception:
        return 3, base_rank
    delta = (market_date - today).days
    if delta > 0:
        return 0, delta
    if delta == 0:
        return 1, 0
    return 2, abs(delta)


def _date_window_bounds(
    ctx: GlobalWeatherMapContext,
    dates: List[Dict[str, str]],
) -> Tuple[str, str]:
    dependencies = _dependencies(ctx)
    now = datetime.fromisoformat(
        _utc_now_iso(dependencies).replace("Z", "+00:00"),
    )
    first = datetime.fromisoformat(dates[0]["iso"]).replace(tzinfo=timezone.utc) if dates else now
    last = datetime.fromisoformat(dates[-1]["iso"]).replace(tzinfo=timezone.utc) if dates else now
    start = min(now - timedelta(days=1), first - timedelta(hours=12))
    end = last + timedelta(days=2)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")


def _weather_market_window_bounds(
    ctx: GlobalWeatherMapContext,
    dates: List[Dict[str, str]],
) -> Tuple[str, str]:
    dependencies = _dependencies(ctx)
    start, end = _date_window_bounds(ctx, dates)
    now = datetime.fromisoformat(
        _utc_now_iso(dependencies).replace("Z", "+00:00"),
    )
    month_end = now + timedelta(days=45)
    parsed_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
    if parsed_end < month_end:
        end = month_end.isoformat().replace("+00:00", "Z")
    return start, end


def _weather_by_city(
    ctx: GlobalWeatherMapContext,
    cities: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    dependencies = _dependencies(ctx)
    if not cities:
        return {}
    base_url = str(
        getattr(dependencies.settings, "open_meteo_api_url", "")
        or ""
    ).strip()
    if not base_url:
        raise RuntimeError("open meteo api url missing")
    by_city: Dict[str, Dict[str, Any]] = {}
    failed_chunks = 0
    chunk_size = 20
    for offset in range(0, len(cities), chunk_size):
        chunk = cities[offset:offset + chunk_size]
        try:
            payload = dependencies.http_json_get(
                base_url,
                params={
                    "latitude": ",".join(str(city["lat"]) for city in chunk),
                    "longitude": ",".join(str(city["lon"]) for city in chunk),
                    "current": "temperature_2m,weather_code,precipitation,wind_speed_10m,wind_gusts_10m",
                    "hourly": "temperature_2m,precipitation,precipitation_probability,wind_speed_10m,wind_gusts_10m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max,wind_gusts_10m_max,weather_code",
                    "forecast_days": 7,
                    "timezone": "auto",
                },
                timeout=18,
                headers={"Accept": "application/json", "User-Agent": "polydata-weather-map/1.0"},
            )
        except Exception:
            failed_chunks += 1
            continue
        if isinstance(payload, dict) and payload.get("error"):
            failed_chunks += 1
            continue
        responses = payload if isinstance(payload, list) else [payload]
        for city, row in zip(chunk, responses):
            if not isinstance(row, dict):
                continue
            if row.get("error"):
                continue
            unit = str(city.get("unit") or "F").upper()
            current = row.get("current") if isinstance(row.get("current"), dict) else {}
            daily = row.get("daily") if isinstance(row.get("daily"), dict) else {}
            hourly = row.get("hourly") if isinstance(row.get("hourly"), dict) else {}
            hourly_times = hourly.get("time") if isinstance(hourly.get("time"), list) else []
            hourly_temps = hourly.get("temperature_2m") if isinstance(hourly.get("temperature_2m"), list) else []
            hourly_precip = hourly.get("precipitation") if isinstance(hourly.get("precipitation"), list) else []
            hourly_precip_prob = hourly.get("precipitation_probability") if isinstance(hourly.get("precipitation_probability"), list) else []
            hourly_wind = hourly.get("wind_speed_10m") if isinstance(hourly.get("wind_speed_10m"), list) else []
            hourly_gust = hourly.get("wind_gusts_10m") if isinstance(hourly.get("wind_gusts_10m"), list) else []
            hourly_codes = hourly.get("weather_code") if isinstance(hourly.get("weather_code"), list) else []
            daily_dates = daily.get("time") if isinstance(daily.get("time"), list) else []
            daily_highs = daily.get("temperature_2m_max") if isinstance(daily.get("temperature_2m_max"), list) else []
            daily_lows = daily.get("temperature_2m_min") if isinstance(daily.get("temperature_2m_min"), list) else []
            daily_precip_sum = daily.get("precipitation_sum") if isinstance(daily.get("precipitation_sum"), list) else []
            daily_precip_prob = daily.get("precipitation_probability_max") if isinstance(daily.get("precipitation_probability_max"), list) else []
            daily_wind = daily.get("wind_speed_10m_max") if isinstance(daily.get("wind_speed_10m_max"), list) else []
            daily_gust = daily.get("wind_gusts_10m_max") if isinstance(daily.get("wind_gusts_10m_max"), list) else []
            daily_codes = daily.get("weather_code") if isinstance(daily.get("weather_code"), list) else []
            daily_rows = [
                {
                    "date": day,
                    "high": _c_to_unit(high, unit),
                    "low": _c_to_unit(low, unit),
                    "precipitationSum": _round_metric(precip_sum),
                    "precipitationProbabilityMax": _round_metric(precip_prob, 0),
                    "windSpeedMax": _round_metric(wind_speed),
                    "windGustMax": _round_metric(wind_gust),
                    "weatherCode": _float(weather_code),
                }
                for day, high, low, precip_sum, precip_prob, wind_speed, wind_gust, weather_code in zip(
                    daily_dates[:7],
                    daily_highs[:7],
                    daily_lows[:7],
                    daily_precip_sum[:7],
                    daily_precip_prob[:7],
                    daily_wind[:7],
                    daily_gust[:7],
                    daily_codes[:7],
                )
            ]
            weather_row = {
                "condition": describe_weather_code(current.get("weather_code")),
                "weatherCode": _float(current.get("weather_code")),
                "currentTemp": _c_to_unit(current.get("temperature_2m"), unit),
                "currentWindSpeed": _round_metric(current.get("wind_speed_10m")),
                "currentWindGust": _round_metric(current.get("wind_gusts_10m")),
                "currentPrecipitation": _round_metric(current.get("precipitation")),
                "todayHigh": daily_rows[0]["high"] if daily_rows else None,
                "todayLow": daily_rows[0]["low"] if daily_rows else None,
                "todayWindSpeed": daily_rows[0].get("windSpeedMax") if daily_rows else None,
                "todayWindGust": daily_rows[0].get("windGustMax") if daily_rows else None,
                "todayPrecipitationSum": daily_rows[0].get("precipitationSum") if daily_rows else None,
                "todayPrecipitationProbability": daily_rows[0].get("precipitationProbabilityMax") if daily_rows else None,
                "forecastHigh": max([row["high"] for row in daily_rows if row.get("high") is not None], default=None),
                "forecastWindSpeedMax": max([row["windSpeedMax"] for row in daily_rows if row.get("windSpeedMax") is not None], default=None),
                "forecastWindGustMax": max([row["windGustMax"] for row in daily_rows if row.get("windGustMax") is not None], default=None),
                "forecastPrecipitationSum": max([row["precipitationSum"] for row in daily_rows if row.get("precipitationSum") is not None], default=None),
                "forecastPrecipitationProbabilityMax": max([row["precipitationProbabilityMax"] for row in daily_rows if row.get("precipitationProbabilityMax") is not None], default=None),
                "windSpeedUnit": "km/h",
                "precipitationUnit": "mm",
                "hourly": [
                    {
                        "time": time_value,
                        "temp": _c_to_unit(temp, unit),
                        "precipitation": _round_metric(precipitation),
                        "precipitationProbability": _round_metric(precipitation_probability, 0),
                        "windSpeed": _round_metric(wind_speed),
                        "windGust": _round_metric(wind_gust),
                        "weatherCode": _float(weather_code),
                    }
                    for time_value, temp, precipitation, precipitation_probability, wind_speed, wind_gust, weather_code in zip(
                        hourly_times[:24],
                        hourly_temps[:24],
                        hourly_precip[:24],
                        hourly_precip_prob[:24],
                        hourly_wind[:24],
                        hourly_gust[:24],
                        hourly_codes[:24],
                    )
                ],
                "daily": daily_rows,
                "weatherUpdatedAt": current.get("time") or row.get("generationtime_ms"),
                "updatedAt": current.get("time") or row.get("generationtime_ms"),
            }
            if _item_has_weather_signal(weather_row):
                by_city[str(city["city_id"])] = weather_row
    if not by_city and failed_chunks:
        raise RuntimeError("open meteo fetch failed for all chunks")
    return by_city


def _clean_weather_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()) or "Weather watch"


def _wttr_condition(row: Dict[str, Any], fallback: str = "Weather watch") -> str:
    desc_rows = row.get("weatherDesc") if isinstance(row, dict) else []
    if isinstance(desc_rows, list) and desc_rows and isinstance(desc_rows[0], dict):
        return _clean_weather_text(desc_rows[0].get("value") or fallback)
    return _clean_weather_text(fallback)


def _wttr_time_label(date_value: Any, time_value: Any) -> str:
    date_text = str(date_value or "").strip()
    raw_time = str(time_value or "0").strip()
    padded = raw_time.zfill(4)
    return f"{date_text}T{padded[:2]}:{padded[2:]}:00" if date_text else padded


def _wttr_city_weather(
    ctx: GlobalWeatherMapContext,
    city: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    dependencies = _dependencies(ctx)
    query = str(city.get("city") or "").split("/")[0].strip()
    if not query:
        return None
    payload = dependencies.http_json_get(
        f"{WTTR_URL}/{quote_plus(query)}",
        params={"format": "j1"},
        timeout=8,
        headers={"Accept": "application/json", "User-Agent": "polydata-weather-map/1.0"},
    )
    if not isinstance(payload, dict):
        return None
    unit = str(city.get("unit") or "F").upper()
    current_rows = payload.get("current_condition") if isinstance(payload.get("current_condition"), list) else []
    current = current_rows[0] if current_rows and isinstance(current_rows[0], dict) else {}
    weather_rows = payload.get("weather") if isinstance(payload.get("weather"), list) else []
    daily_rows: List[Dict[str, Any]] = []
    hourly_rows: List[Dict[str, Any]] = []
    for row in weather_rows[:7]:
        if not isinstance(row, dict):
            continue
        date_value = str(row.get("date") or "")
        high = row.get("maxtempF") if unit == "F" else row.get("maxtempC")
        low = row.get("mintempF") if unit == "F" else row.get("mintempC")
        row_hourly = [hourly for hourly in (row.get("hourly") or []) if isinstance(hourly, dict)]
        daily_rows.append(
            {
                "date": date_value,
                "high": _float(high),
                "low": _float(low),
                "precipitationSum": _sum_metric([hourly.get("precipMM") for hourly in row_hourly]),
                "precipitationProbabilityMax": _max_metric([hourly.get("chanceofrain") for hourly in row_hourly], digits=0),
                "windSpeedMax": _max_metric([hourly.get("windspeedKmph") for hourly in row_hourly]),
                "windGustMax": _max_metric([hourly.get("WindGustKmph") for hourly in row_hourly]),
                "weatherCode": _float((row_hourly[0] if row_hourly else {}).get("weatherCode")),
            }
        )
        for hourly in row_hourly:
            if not isinstance(hourly, dict):
                continue
            temp = hourly.get("tempF") if unit == "F" else hourly.get("tempC")
            hourly_rows.append(
                {
                    "time": _wttr_time_label(date_value, hourly.get("time")),
                    "temp": _float(temp),
                    "precipitation": _round_metric(hourly.get("precipMM")),
                    "precipitationProbability": _round_metric(hourly.get("chanceofrain"), 0),
                    "windSpeed": _round_metric(hourly.get("windspeedKmph")),
                    "windGust": _round_metric(hourly.get("WindGustKmph")),
                    "weatherCode": _float(hourly.get("weatherCode")),
                }
            )
    current_temp = current.get("temp_F") if unit == "F" else current.get("temp_C")
    return {
        "condition": _wttr_condition(current),
        "weatherCode": _float(current.get("weatherCode")),
        "currentTemp": _float(current_temp),
        "currentWindSpeed": _round_metric(current.get("windspeedKmph")),
        "currentWindGust": _round_metric(current.get("WindGustKmph")),
        "currentPrecipitation": _round_metric(current.get("precipMM")),
        "todayHigh": daily_rows[0]["high"] if daily_rows else None,
        "todayLow": daily_rows[0]["low"] if daily_rows else None,
        "todayWindSpeed": daily_rows[0].get("windSpeedMax") if daily_rows else None,
        "todayWindGust": daily_rows[0].get("windGustMax") if daily_rows else None,
        "todayPrecipitationSum": daily_rows[0].get("precipitationSum") if daily_rows else None,
        "todayPrecipitationProbability": daily_rows[0].get("precipitationProbabilityMax") if daily_rows else None,
        "forecastHigh": max([row["high"] for row in daily_rows if row.get("high") is not None], default=None),
        "forecastWindSpeedMax": max([row["windSpeedMax"] for row in daily_rows if row.get("windSpeedMax") is not None], default=None),
        "forecastWindGustMax": max([row["windGustMax"] for row in daily_rows if row.get("windGustMax") is not None], default=None),
        "forecastPrecipitationSum": max([row["precipitationSum"] for row in daily_rows if row.get("precipitationSum") is not None], default=None),
        "forecastPrecipitationProbabilityMax": max([row["precipitationProbabilityMax"] for row in daily_rows if row.get("precipitationProbabilityMax") is not None], default=None),
        "windSpeedUnit": "km/h",
        "precipitationUnit": "mm",
        "hourly": [row for row in hourly_rows[:24] if any(row.get(key) is not None for key in ("temp", "precipitation", "windSpeed", "windGust"))],
        "daily": [row for row in daily_rows if any(row.get(key) is not None for key in ("high", "low", "precipitationSum", "windSpeedMax", "windGustMax"))],
        "weatherUpdatedAt": _utc_now_iso(dependencies),
        "updatedAt": _utc_now_iso(dependencies),
        "weatherProvider": "wttr.in",
    }


def _wttr_weather_by_city(
    ctx: GlobalWeatherMapContext,
    cities: List[Dict[str, Any]],
    *,
    missing_ids: Optional[set[str]] = None,
) -> Dict[str, Dict[str, Any]]:
    targets = [city for city in cities if missing_ids is None or str(city.get("city_id") or "") in missing_ids]
    if not targets:
        return {}
    result: Dict[str, Dict[str, Any]] = {}
    max_workers = max(1, min(10, len(targets)))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="weather-wttr") as executor:
        futures = {executor.submit(_wttr_city_weather, ctx, city): city for city in targets}
        for future in as_completed(futures):
            city = futures[future]
            try:
                row = future.result()
            except Exception:
                row = None
            if row:
                result[str(city["city_id"])] = row
    return result


def _metar_by_city(
    ctx: GlobalWeatherMapContext,
    cities: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    dependencies = _dependencies(ctx)
    ids = [str(city.get("icao") or "").strip().upper() for city in cities if city.get("icao")]
    if not ids:
        return {}
    base_url = str(
        getattr(
            dependencies.settings,
            "aviationweather_metar_api_url",
            "",
        )
        or ""
    ).strip()
    payload = dependencies.http_json_get(
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


def _weather_clob_stats(
    ctx: GlobalWeatherMapContext,
) -> Dict[str, int]:
    dependencies = _dependencies(ctx)
    return _weather_context_state(
        dependencies,
        "_weather_clob_stats",
        {"attempts": 0, "errors": 0, "quoted": 0, "noBook": 0, "cacheHits": 0, "missingToken": 0},
    )


def _empty_clob_quote(status: str, token_id: Optional[str] = None) -> Dict[str, Optional[float] | Optional[str]]:
    return {
        "bestBidYes": None,
        "bestAskYes": None,
        "bookStatus": status,
        "priceSource": "clob-book",
        "yesTokenId": token_id,
    }


def _clob_book_payload(ctx: GlobalWeatherMapContext, token_id: str) -> Dict[str, Any]:
    reader = _dependencies(ctx).lob_reader
    if reader is None:
        return {"bookStatus": "unavailable", "bids": [], "asks": []}
    payload = reader(token_id)
    side = payload.get("yes") or {}
    status = side.get("bookStatus") or payload.get("bookStatus") or "unknown"
    return {"bookStatus": status, "bids": side.get("bids", []) if status == "live" else [], "asks": side.get("asks", []) if status == "live" else []}


def _clob_yes_quote(
    ctx: GlobalWeatherMapContext,
    market: Dict[str, Any],
) -> Dict[str, Optional[float] | Optional[str]]:
    dependencies = _dependencies(ctx)
    token_ids = _token_ids(market)
    if not token_ids:
        stats = _weather_clob_stats(ctx)
        stats["missingToken"] = int(stats.get("missingToken") or 0) + 1
        return _empty_clob_quote("missing-token")
    stats = _weather_clob_stats(ctx)
    stats["attempts"] = int(stats.get("attempts") or 0) + 1
    try:
        book = _clob_book_payload(ctx, token_ids[0])
    except Exception:
        stats["errors"] = int(stats.get("errors") or 0) + 1
        payload = _empty_clob_quote("error", token_ids[0])
        return payload
    bids = book.get("bids") if isinstance(book, dict) and isinstance(book.get("bids"), list) else []
    asks = book.get("asks") if isinstance(book, dict) and isinstance(book.get("asks"), list) else []
    best_bid = max((price for row in bids if isinstance(row, dict) and (price := _float(row.get("price"))) is not None), default=None)
    best_ask = min((price for row in asks if isinstance(row, dict) and (price := _float(row.get("price"))) is not None), default=None)
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
    return payload


def _apply_clob_quote_to_bin(
    ctx: GlobalWeatherMapContext,
    row: Dict[str, Any],
) -> None:
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


def _db_weather_market_rows(
    ctx: GlobalWeatherMapContext,
    dates: List[Dict[str, str]],
) -> Tuple[List[Dict[str, Any]], str]:
    dependencies = _dependencies(ctx)
    if dependencies.get_connection is None:
        return [], "empty"
    start_iso, end_iso = _weather_market_window_bounds(ctx, dates)
    conn = None
    try:
        try:
            conn = dependencies.get_connection(
                dependencies.database_path,
                readonly=True,
            )
        except TypeError:
            conn = dependencies.get_connection(dependencies.database_path)
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
                (COALESCE(m.closed, FALSE) OR COALESCE(mss.is_trading_closed, FALSE)) AS is_trading_closed,
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
                AND m.active = TRUE
                AND COALESCE(m.closed, FALSE) = FALSE
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
        logger = getattr(dependencies.application, "logger", None)
        if logger is not None:
            logger.exception("global weather map market db query failed error=%s", exc)
        return [], "error"
    finally:
        if conn is not None and hasattr(conn, "close"):
            try:
                conn.close()
            except Exception:
                pass


def _db_temperature_rows(
    ctx: GlobalWeatherMapContext,
    dates: List[Dict[str, str]],
) -> Tuple[List[Dict[str, Any]], str]:
    rows, status = _db_weather_market_rows(ctx, dates)
    filtered = [row for row in rows if _market_family(_normalize_text(row.get("title"), row.get("slug"))) == "highest_temperature"]
    return filtered, status if filtered else ("empty" if status == "ok" else status)


def _db_market_object(row: Dict[str, Any]) -> Dict[str, Any]:
    token_ids = [row.get("yes_token_id"), row.get("no_token_id")]
    return {
        "id": row.get("market_id"),
        "slug": row.get("slug"),
        "question": row.get("title"),
        "title": row.get("title"),
        "clobTokenIds": token_ids if token_ids[0] else [],
        "active": not (_truthy(row.get("is_trading_closed")) or _truthy(row.get("is_resolved")) or _truthy(row.get("gamma_closed"))),
    }


def _db_price_fallback(row: Dict[str, Any]) -> Optional[float]:
    for key in ("latest_yes_price", "latest_trade_price", "serving_latest_price"):
        price = _float(row.get(key))
        if price is not None:
            return round(price, 4)
    return None


def _normalize_temperature_db_group(
    ctx: GlobalWeatherMapContext,
    city: Dict[str, Any],
    date_iso: str,
    rows: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    dependencies = _dependencies(ctx)
    bins: List[Dict[str, Any]] = []
    for row in rows:
        market = _db_market_object(row)
        label = str(row.get("title") or row.get("slug") or "").strip()
        parsed = parse_temperature_bin(label, default_unit=str(city.get("unit") or "F"))
        if not parsed:
            continue
        fallback = _db_price_fallback(row)
        fallback_source = "db-latest" if fallback is not None else "missing"
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
    targets = (
        bins
        if str(
            dependencies.runtime_state.get("_weather_clob_scope")
            or "top"
        ).lower()
        == "all"
        else ([top] if top is not None else [])
    )
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


def _normalize_weather_db_group(
    ctx: GlobalWeatherMapContext,
    city: Optional[Dict[str, Any]],
    date_iso: str,
    family: str,
    rows: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    dependencies = _dependencies(ctx)
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
    targets = (
        bins
        if str(
            dependencies.runtime_state.get("_weather_clob_scope")
            or "top"
        ).lower()
        == "all"
        else ([top] if top is not None else [])
    )
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


def _db_markets_by_city(
    ctx: GlobalWeatherMapContext,
    cities: List[Dict[str, Any]],
    dates: List[Dict[str, str]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    dependencies = _dependencies(ctx)
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
        candidate_groups: List[Tuple[int, int, int, int, float, str, str, List[Dict[str, Any]]]] = []
        for (group_city_id, date_iso, family), group_rows in grouped.items():
            if group_city_id != city_id:
                continue
            newest = max((_parse_ts(row.get("serving_latest_trade_at") or row.get("latest_trade_at") or row.get("end_date") or row.get("created_at")) for row in group_rows), default=0.0)
            date_rank, date_distance = _weather_market_date_rank(ctx, date_iso, date_order)
            candidate_groups.append((WEATHER_FAMILY_PRIORITY.get(family, 99), date_rank, date_distance, -len(group_rows), -newest, date_iso, family, group_rows))
        candidate_groups.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
        if candidate_groups:
            selected_groups[city_id] = [(city, date_iso, family, group_rows) for _, _, _, _, _, date_iso, family, group_rows in candidate_groups[:6]]
        else:
            source_states[city_id] = "empty" if db_status == "ok" else db_status

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
    dependencies.runtime_state["_weather_family_counts"] = family_counts
    dependencies.runtime_state["_weather_unmapped_markets"] = unmapped[:80]
    return result, source_states


def _markets_by_city(
    ctx: GlobalWeatherMapContext,
    cities: List[Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    dependencies = _dependencies(ctx)
    dates = _date_labels(
        dependencies,
        int(
            getattr(
                dependencies.settings,
                "global_weather_market_days",
                4,
            )
            or 4
        ),
    )
    return _db_markets_by_city(ctx, cities, dates)


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


def _item_has_weather_signal(item: Dict[str, Any]) -> bool:
    signal_keys = (
        "currentTemp",
        "metarTemp",
        "todayHigh",
        "forecastHigh",
        "currentWindSpeed",
        "currentWindGust",
        "currentPrecipitation",
        "todayWindSpeed",
        "todayWindGust",
        "todayPrecipitationSum",
        "todayPrecipitationProbability",
        "forecastWindSpeedMax",
        "forecastWindGustMax",
        "forecastPrecipitationSum",
        "forecastPrecipitationProbabilityMax",
    )
    if any(item.get(key) is not None for key in signal_keys):
        return True
    return bool(item.get("hourly") or item.get("daily"))


def build_summary(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    mapped = [
        item for item in items
        if _item_has_weather_signal(item)
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
    "currentWindSpeed",
    "currentWindGust",
    "currentPrecipitation",
    "todayHigh",
    "todayLow",
    "todayWindSpeed",
    "todayWindGust",
    "todayPrecipitationSum",
    "todayPrecipitationProbability",
    "forecastHigh",
    "forecastWindSpeedMax",
    "forecastWindGustMax",
    "forecastPrecipitationSum",
    "forecastPrecipitationProbabilityMax",
    "windSpeedUnit",
    "precipitationUnit",
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


def build_global_weather_map_payload(
    ctx: GlobalWeatherMapContext,
    *,
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    cities = load_weather_cities(limit=max(limit or DEFAULT_ITEM_LIMIT, DEFAULT_ITEM_LIMIT))
    sources: Dict[str, str] = {}
    open_meteo_failed = False
    try:
        weather = _weather_by_city(ctx, cities)
        sources["openMeteo"] = "ok" if len(weather) >= len(cities) else ("partial" if weather else "empty")
    except Exception as exc:
        weather = {}
        open_meteo_failed = True
        sources["openMeteo"] = "error"
        logger = getattr(dependencies.application, "logger", None)
        if logger is not None:
            logger.exception("global weather map open-meteo fetch failed error=%s", exc)
    try:
        missing_weather_ids = {str(city["city_id"]) for city in cities if str(city["city_id"]) not in weather}
        wttr = _wttr_weather_by_city(ctx, cities, missing_ids=missing_weather_ids)
        if wttr:
            weather.update(wttr)
        sources["wttr"] = "ok" if wttr and not missing_weather_ids - set(wttr.keys()) else ("partial" if wttr else "empty")
    except Exception as exc:
        sources["wttr"] = "error" if open_meteo_failed else "empty"
        logger = getattr(dependencies.application, "logger", None)
        if logger is not None:
            logger.exception("global weather map wttr fallback failed error=%s", exc)
    try:
        metar = _metar_by_city(ctx, cities)
        sources["aviationWeather"] = _source_status(bool(metar))
    except Exception as exc:
        metar = {}
        sources["aviationWeather"] = "error"
        logger = getattr(dependencies.application, "logger", None)
        if logger is not None:
            logger.exception("global weather map metar fetch failed error=%s", exc)
    try:
        markets, market_source_states = _markets_by_city(ctx, cities)
        sources["marketDatabase"] = _aggregate_source(market_source_states.values())
        clob_stats = (
            dependencies.runtime_state.get("_weather_clob_stats")
            or {}
        )
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
        sources["marketDatabase"] = "error"
        sources["clob"] = "error"
        logger = getattr(dependencies.application, "logger", None)
        if logger is not None:
            logger.exception("global weather map polymarket fetch failed error=%s", exc)

    items: List[Dict[str, Any]] = []
    for city in cities:
        city_id = str(city["city_id"])
        weather_row = weather.get(city_id) or {}
        metar_row = metar.get(city_id) or {}
        market_row = markets.get(city_id) or {}
        weather_provider = str((weather_row.get("weatherProvider") or "open-meteo") if weather_row else "").lower()
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
                "openMeteo": "ok" if weather_row and weather_provider != "wttr.in" else ("error" if open_meteo_failed else "empty"),
                "wttr": "ok" if weather_provider == "wttr.in" else "empty",
                "metar": "ok" if metar_row else "empty",
                "polymarket": "ok" if market_row else market_source_states.get(city_id, "empty"),
            },
            "updatedAt": weather_row.get("updatedAt") or metar_row.get("updatedAt") or market_row.get("updatedAt") or _utc_now_iso(dependencies),
        }
        items.append(item)
    summary = build_summary(items)
    summary["marketFamilyCounts"] = (
        dependencies.runtime_state.get("_weather_family_counts")
        or summary.get("marketFamilyCounts")
        or {}
    )
    summary["unmappedMarketCount"] = len(
        dependencies.runtime_state.get("_weather_unmapped_markets")
        or []
    )
    status = "ok" if summary["mappedCount"] else "warming"
    if status == "ok" and any(value == "error" for value in sources.values()):
        status = "degraded"
    return {
        "generatedAt": _utc_now_iso(dependencies),
        "source": "Open-Meteo/wttr + AviationWeather + market-data",
        "sourceUrl": getattr(
            dependencies.settings,
            "weather_source_url",
            "https://open-meteo.com/",
        ),
        "status": status,
        "sources": sources,
        "summary": summary,
        "items": items,
        "unmappedMarkets": (
            dependencies.runtime_state.get("_weather_unmapped_markets")
            or []
        ),
    }


def _empty_payload(
    dependencies: GlobalWeatherMapDependencies,
    *,
    status: str = "warming",
) -> Dict[str, Any]:
    return {
        "generatedAt": _utc_now_iso(dependencies),
        "source": "Open-Meteo + AviationWeather + Polymarket Gamma/CLOB",
        "sourceUrl": getattr(
            dependencies.settings,
            "weather_source_url",
            "https://open-meteo.com/",
        ),
        "status": status,
        "sources": {},
        "summary": {"cityCount": 0, "mappedCount": 0, "liveMarketCount": 0, "staleCount": 0, "hottestCity": None, "marketFamilyCounts": {}, "unmappedMarketCount": 0},
        "items": [],
        "unmappedMarkets": [],
    }


def normalize_global_weather_map_payload(
    payload: Any,
    *,
    ctx: GlobalWeatherMapContext,
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    if not isinstance(payload, dict):
        return _empty_payload(dependencies, status="invalid")
    result = json.loads(json.dumps(payload, ensure_ascii=True, default=str))
    items = [item for item in (result.get("items") or []) if isinstance(item, dict)]
    result["items"] = items[: max(1, min(int(limit or DEFAULT_ITEM_LIMIT), 60))]
    result["summary"] = result.get("summary") if isinstance(result.get("summary"), dict) else build_summary(result["items"])
    result["generatedAt"] = str(
        result.get("generatedAt")
        or _utc_now_iso(dependencies)
    )
    result["status"] = str(result.get("status") or ("ok" if result["items"] else "warming"))
    result["source"] = str(result.get("source") or "Open-Meteo/wttr + AviationWeather + Polymarket Gamma/CLOB")
    result["sourceUrl"] = str(
        result.get("sourceUrl")
        or getattr(
            dependencies.settings,
            "weather_source_url",
            "https://open-meteo.com/",
        )
    )
    result["unmappedMarkets"] = [item for item in (result.get("unmappedMarkets") or []) if isinstance(item, dict)][:120]
    return result


def _with_cache_mode(payload: Dict[str, Any], cache_mode: str) -> Dict[str, Any]:
    return {**payload, "cacheMode": cache_mode}


def _read_seeded_snapshot(
    dependencies: GlobalWeatherMapDependencies,
    *,
    ttl_seconds: int,
) -> Optional[Dict[str, Any]]:
    if dependencies.get_cached_json is not None:
        payload = dependencies.get_cached_json(
            GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE,
            GLOBAL_WEATHER_MAP_CACHE_KEY,
        )
        if isinstance(payload, dict):
            return _with_cache_mode(payload, "redis-seed")
    store = dependencies.snapshot_store
    if store is None:
        return None
    payload = store.get(GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE, GLOBAL_WEATHER_MAP_CACHE_KEY)
    if isinstance(payload, dict):
        return _with_cache_mode(payload, "sqlite-seed")
    stale = store.get_stale(GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE, GLOBAL_WEATHER_MAP_CACHE_KEY)
    if isinstance(stale, dict):
        return _with_cache_mode(stale, "stale-seed")
    return None


def _store_live(
    dependencies: GlobalWeatherMapDependencies,
    payload: Dict[str, Any],
    *,
    ttl_seconds: int,
) -> None:
    if dependencies.snapshot_store is not None:
        dependencies.snapshot_store.set(
            GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE,
            GLOBAL_WEATHER_MAP_CACHE_KEY,
            payload,
            ttl_seconds,
        )
    if dependencies.set_cached_json is not None:
        dependencies.set_cached_json(
            GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE,
            GLOBAL_WEATHER_MAP_CACHE_KEY,
            payload,
            ttl_seconds,
        )


def _schedule_live_refresh(
    ctx: GlobalWeatherMapContext,
    *,
    limit: int,
    ttl_seconds: int,
    reason: str,
) -> bool:
    dependencies = _dependencies(ctx)
    refresh_key = "global_weather_map_service:" + f"{GLOBAL_WEATHER_MAP_SNAPSHOT_NAMESPACE}:{GLOBAL_WEATHER_MAP_CACHE_KEY}"
    with dependencies.resources.live_refresh_lock:
        if refresh_key in dependencies.resources.live_refreshing:
            return False
        dependencies.resources.live_refreshing.add(refresh_key)

    def refresh() -> None:
        logger = getattr(dependencies.application, "logger", None)
        previous = _read_seeded_snapshot(
            dependencies,
            ttl_seconds=ttl_seconds,
        )
        try:
            payload = _with_cache_mode(
                build_global_weather_map_payload(
                    dependencies,
                    limit=limit,
                ),
                "live-build",
            )
            payload = merge_weather_series_from_previous(payload, previous)
            if payload.get("items"):
                _store_live(
                    dependencies,
                    payload,
                    ttl_seconds=ttl_seconds,
                )
                if logger is not None and hasattr(logger, "info"):
                    logger.info("global weather map async refresh stored reason=%s items=%s", reason, len(payload.get("items") or []))
            elif logger is not None and hasattr(logger, "warning"):
                logger.warning("global weather map async refresh skipped empty payload reason=%s", reason)
        except Exception:
            if logger is not None:
                logger.exception("global weather map async refresh failed reason=%s", reason)
        finally:
            with dependencies.resources.live_refresh_lock:
                dependencies.resources.live_refreshing.discard(refresh_key)

    if not dependencies.resources.start_thread(refresh, name="global-weather-map-refresh"):
        with dependencies.resources.live_refresh_lock:
            dependencies.resources.live_refreshing.discard(refresh_key)
    return True


def get_global_weather_map_snapshot(
    ctx: GlobalWeatherMapContext,
    limit: int = DEFAULT_ITEM_LIMIT,
    *,
    allow_live_build: bool = True,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    ttl_seconds = max(
        60,
        int(
            getattr(
                dependencies.settings,
                "global_weather_map_ttl_seconds",
                300,
            )
            or 300
        ),
    )
    seeded = _read_seeded_snapshot(
        dependencies,
        ttl_seconds=ttl_seconds,
    )
    if seeded is not None:
        if allow_live_build and seeded.get("cacheMode") == "stale-seed":
            _schedule_live_refresh(
                dependencies,
                limit=limit,
                ttl_seconds=ttl_seconds,
                reason="stale-seed",
            )
        return normalize_global_weather_map_payload(
            seeded,
            ctx=dependencies,
            limit=limit,
        )
    if not allow_live_build:
        return normalize_global_weather_map_payload(
            {
                **_empty_payload(dependencies),
                "cacheMode": "seed-miss",
            },
            ctx=dependencies,
            limit=limit,
        )
    scheduled = _schedule_live_refresh(
        dependencies,
        limit=limit,
        ttl_seconds=ttl_seconds,
        reason="seed-miss",
    )
    return normalize_global_weather_map_payload(
        {
            **_empty_payload(dependencies),
            "cacheMode": (
                "seed-miss-refreshing"
                if scheduled
                else "seed-miss-refresh-inflight"
            ),
        },
        ctx=dependencies,
        limit=limit,
    )
