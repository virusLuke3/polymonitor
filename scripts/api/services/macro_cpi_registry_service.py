from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from api.services.macro_data_contract import month_key, monthly_metric, shift_month, value_label, number
from api.context import resolve_optional_service_callable
from api.services import cpi_release_calendar_service, energy_gasoline_shock_service, food_retail_basket_service, macro_cpi_panels_service, runtime_service


DEFAULT_ITEM_LIMIT = 36
MAX_ITEM_LIMIT = 60
SNAPSHOT_NAMESPACE_PREFIX = "snapshot:macro-registry:"
CACHE_KEY = "panel-v2"
FRED_CSV_LOOKBACK_YEARS = 4

CPI_EVENT_SPECS = (
    {
        "key": "headline-yoy",
        "title": "Inflation Rate YoY",
        "seriesId": "CPIAUCNS",
        "metric": "yoy",
        "nowcastKey": "CPI",
        "bucket": "yearOverYear",
    },
    {
        "key": "core-yoy",
        "title": "Core Inflation Rate YoY",
        "seriesId": "CPILFENS",
        "metric": "yoy",
        "nowcastKey": "Core CPI",
        "bucket": "yearOverYear",
    },
    {
        "key": "headline-mom",
        "title": "Inflation Rate MoM",
        "seriesId": "CPIAUCSL",
        "metric": "mom",
        "nowcastKey": "CPI",
        "bucket": "monthOverMonth",
    },
    {
        "key": "core-mom",
        "title": "Core Inflation Rate MoM",
        "seriesId": "CPILFESL",
        "metric": "mom",
        "nowcastKey": "Core CPI",
        "bucket": "monthOverMonth",
    },
)


PANEL_CONFIGS: Dict[str, Dict[str, Any]] = {
    "cpi-release-command-center": {
        "source": "BLS / BEA / Fed / Cleveland Fed / FRED",
        "signalLabel": "Release / nowcast command",
        "emptySignal": "CPI RELEASE WARMING",
    },
    "cpi-components-pressure-registry": {
        "source": "BLS / FRED / EIA",
        "signalLabel": "CPI component pressure",
        "emptySignal": "COMPONENTS WARMING",
    },
    "goods-tariff-supply-watch": {
        "source": "FRED / Federal Register / public supply proxies",
        "signalLabel": "Goods / tariff watch",
        "emptySignal": "GOODS WATCH WARMING",
    },
    "labor-services-inflation-monitor": {
        "source": "BLS / DOL / FRED",
        "signalLabel": "Labor / services inflation",
        "emptySignal": "LABOR SERVICES WARMING",
    },
    "fed-reaction-growth-risk-board": {
        "source": "Fed / Treasury / BEA / FRED",
        "signalLabel": "Fed reaction / growth risk",
        "emptySignal": "FED GROWTH WARMING",
    },
}


@dataclass(frozen=True)
class MacroCpiRegistryDependencies:
    source: Mapping[str, Any]
    utc_now_iso: Callable[..., Any] | None
    settings: Any
    http_text_get: Callable[..., Any] | None
    get_cached_json: Callable[..., Any] | None
    snapshot_store: Any

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> MacroCpiRegistryDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            source=context,
            utc_now_iso=resolve_optional_service_callable(
                context,
                "utc_now_iso",
            ),
            settings=context.get("SETTINGS"),
            http_text_get=resolve_optional_service_callable(
                context,
                "http_text_get",
            ),
            get_cached_json=resolve_optional_service_callable(
                context,
                "get_cached_json",
            ),
            snapshot_store=context.get("SNAPSHOT_STORE"),
        )


def _utc_now_iso(
    dependencies: MacroCpiRegistryDependencies,
) -> str:
    if dependencies.utc_now_iso is not None:
        return dependencies.utc_now_iso()
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _float(value: Any) -> Optional[float]:
    return number(value)


def _limit(limit: int) -> int:
    return max(1, min(int(limit or DEFAULT_ITEM_LIMIT), MAX_ITEM_LIMIT))


def _snapshot_namespace(panel_id: str) -> str:
    return f"{SNAPSHOT_NAMESPACE_PREFIX}{panel_id}"


def ttl_seconds(ctx: Mapping[str, Any]) -> int:
    dependencies = MacroCpiRegistryDependencies.from_context(ctx)
    return max(
        1800,
        int(
            getattr(
                dependencies.settings,
                "macro_cpi_registry_ttl_seconds",
                21600,
            )
            or 21600
        ),
    )


def _status_tone(value: Any) -> str:
    text = str(value or "").lower()
    if text in {"hot", "cool", "watch", "neutral"}:
        return text
    if any(term in text for term in ("hot", "rising", "hawk", "sticky", "pressure")):
        return "hot"
    if any(term in text for term in ("cool", "easing", "soft", "disinflation")):
        return "cool"
    if any(term in text for term in ("watch", "mixed", "event", "partial", "degraded", "warming")):
        return "watch"
    return "neutral"


def _signed(value: Any, *, suffix: str = "", decimals: int = 2) -> str:
    number = _float(value)
    if number is None:
        return "--"
    return f"{number:+.{decimals}f}{suffix}"


def _value_label(value: Any, unit: Any = None) -> str:
    return value_label(value, unit)


def _pct_value_label(value: Any) -> str:
    number = _float(value)
    return "--" if number is None else f"{number:.1f}%"


def _source_label(source: Any) -> str:
    text = str(source or "").strip()
    lowered = text.lower()
    if not text:
        return "SOURCE"
    if "cleveland" in lowered:
        return "NOWCAST"
    if "federal reserve" in lowered or lowered == "fed":
        return "FED"
    if "federal register" in lowered:
        return "FEDREG"
    if "fred" in lowered and "bls" in lowered:
        return "FRED/BLS"
    if "fred" in lowered:
        return "FRED"
    if "bls" in lowered:
        return "BLS"
    if "eia" in lowered:
        return "EIA"
    if "dol" in lowered:
        return "DOL"
    if "treasury" in lowered:
        return "UST"
    if "/" in text:
        return "/".join(part.strip()[:4].upper() for part in text.split("/")[:2] if part.strip()) or "SOURCE"
    return text.split()[0][:10].upper()


def _domain_tag(group: Any, row_type: Any, label: Any) -> str:
    text = f"{group or ''} {row_type or ''} {label or ''}".lower()
    if any(term in text for term in ("nfp", "job", "wage", "labor", "unemployment", "claim")):
        return "LABOR"
    if any(term in text for term in ("fed", "fomc", "sofr", "funds", "treasury", "rate")):
        return "FED"
    if any(term in text for term in ("oil", "wti", "gasoline", "energy", "eia")):
        return "ENERGY"
    if any(term in text for term in ("food", "retail", "egg", "meat")):
        return "FOOD"
    if any(term in text for term in ("rent", "shelter", "oer", "housing")):
        return "SHELTER"
    if any(term in text for term in ("tariff", "import", "supply", "goods", "producer")):
        return "GOODS"
    if any(term in text for term in ("cpi", "pce", "inflation", "nowcast")):
        return "CPI"
    if any(term in text for term in ("gdp", "growth", "demand", "recession")):
        return "GROWTH"
    return str(group or row_type or "MACRO").upper()[:12]


def _severity_label(tone: Any) -> str:
    normalized = _status_tone(tone)
    if normalized == "hot":
        return "ALERT"
    if normalized == "cool":
        return "COOL"
    if normalized == "watch":
        return "WATCH"
    return "INFO"


def _age_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "--"
    parsed_text = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(parsed_text)
    except ValueError:
        return text[:10]
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    diff_seconds = max(0, int((now - parsed.astimezone(timezone.utc)).total_seconds()))
    minutes = diff_seconds // 60
    hours = diff_seconds // 3600
    days = diff_seconds // 86400
    if minutes < 1:
        return "NOW"
    if minutes < 60:
        return f"{minutes}M"
    if hours < 24:
        return f"{hours}H"
    if days < 30:
        return f"{days}D"
    return parsed.date().isoformat()


def _row(
    *,
    key: str,
    row_type: str,
    group: str,
    label: str,
    value: Any = None,
    unit: Any = None,
    change: Any = None,
    change_label: str | None = None,
    date: Any = None,
    tone: str = "neutral",
    source: str = "",
    source_url: str = "",
    implication: str = "",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_tone = _status_tone(tone)
    value_label = _value_label(value, unit)
    delta_label = change_label or _signed(change)
    return {
        "key": key,
        "type": row_type,
        "group": group,
        "label": label,
        "value": value,
        "unit": unit,
        "valueLabel": value_label,
        "change": change,
        "changeLabel": delta_label,
        "date": date,
        "tone": normalized_tone,
        "source": source,
        "sourceUrl": source_url,
        "sourceLabel": _source_label(source),
        "domainTag": _domain_tag(group, row_type, label),
        "severityLabel": _severity_label(normalized_tone),
        "ageLabel": _age_label(date),
        "implication": implication,
        "metadata": metadata or {},
    }


def _sort_key(row: Dict[str, Any]) -> tuple[int, str, str]:
    tone_rank = {"hot": 0, "watch": 1, "cool": 2, "neutral": 3}.get(str(row.get("tone") or "neutral"), 4)
    if str(row.get("type") or "").lower() == "release":
        tone_rank = -1
    return (tone_rank, str(row.get("group") or ""), str(row.get("date") or "") if tone_rank == -1 else str(row.get("label") or ""))


def _rank_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique = {}
    for row in rows:
        series_id = (row.get("metadata") or {}).get("seriesId")
        identity = (series_id, row.get("date")) if series_id else row.get("key")
        existing = unique.get(identity)
        if existing is None or str((row.get("metadata") or {}).get("fetchedAt") or "") > str((existing.get("metadata") or {}).get("fetchedAt") or ""):
            unique[identity] = row
    ranked = sorted(unique.values(), key=_sort_key)
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    return ranked


def _enrich_row(row: Dict[str, Any]) -> Dict[str, Any]:
    tone = _status_tone(row.get("tone"))
    source = row.get("source")
    group = row.get("group")
    row_type = row.get("type")
    label = row.get("label")
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    unit = str(row.get("unit") or metadata.get("unit") or "").strip().lower()
    raw_change = metadata.get("rawChange")
    enriched = dict(row)
    enriched["tone"] = tone
    enriched["valueLabel"] = str(row.get("valueLabel") or _value_label(row.get("value"), row.get("unit")))
    if not row.get("changeLabel") and unit == "pp" and _float(raw_change) is not None:
        enriched["change"] = raw_change
        enriched["changeLabel"] = _signed(raw_change, suffix="pp")
    else:
        enriched["changeLabel"] = str(row.get("changeLabel") or _signed(row.get("change")))
    enriched["sourceLabel"] = str(row.get("sourceLabel") or _source_label(source))
    enriched["domainTag"] = str(row.get("domainTag") or _domain_tag(group, row_type, label))
    enriched["severityLabel"] = str(row.get("severityLabel") or _severity_label(tone))
    enriched["ageLabel"] = str(row.get("ageLabel") or _age_label(row.get("date")))
    return enriched


def _snapshot_status(payload: Dict[str, Any]) -> str:
    if payload.get("cacheMode") == "stale-seed":
        return "stale"
    return str(payload.get("status") or ("ok" if payload.get("items") else "warming"))


def _merge_sources(sources: Dict[str, str], prefix: str, payload: Dict[str, Any]) -> None:
    source_states = payload.get("sources") if isinstance(payload.get("sources"), dict) else {}
    if not source_states:
        sources[prefix] = _snapshot_status(payload)
        return
    sources.pop(prefix, None)
    for key, value in source_states.items():
        sources[f"{prefix}.{key}"] = "stale" if payload.get("cacheMode") == "stale-seed" else str(value)
    generated = _parse_datetime(payload.get("generatedAt"))
    interval = int(payload.get("expectedIntervalSeconds") or (3600 if prefix == "calendar" else 21600))
    if generated and (datetime.now(timezone.utc) - generated).total_seconds() > interval * 1.5:
        for key in source_states:
            sources[f"{prefix}.{key}"] = "stale"


def _calendar_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(payload.get("items") or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "macro").upper()
        rows.append(
            _row(
                key=f"calendar-{item.get('id') or index}",
                row_type="release",
                group=kind,
                label=str(item.get("title") or "Macro release"),
                value=item.get("releaseTimeEt") or item.get("releaseAt"),
                unit=None,
                change=item.get("hoursToEvent"),
                change_label=str(item.get("releaseTimeEt") or item.get("referencePeriod") or "--"),
                date=item.get("releaseAt"),
                tone="watch" if kind in {"FOMC", "NFP"} else "neutral",
                source=str(item.get("source") or "Official calendar"),
                source_url=str(item.get("sourceUrl") or ""),
                implication=str(item.get("marketRelevance") or "release timing"),
                metadata={
                    "id": item.get("id"),
                    "kind": str(item.get("kind") or kind).lower(),
                    "referencePeriod": item.get("referencePeriod"),
                    "releaseAt": item.get("releaseAt"),
                    "releaseTimeEt": item.get("releaseTimeEt"),
                },
            )
        )
    return rows


def _nowcast_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for bucket_name in ("monthOverMonth", "yearOverYear"):
        buckets = (payload.get("monthlyPeriods") or {}).get(bucket_name)
        if not isinstance(buckets, list):
            buckets = [payload.get(bucket_name)]
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            period = month_key(bucket.get("Month"))
            for key, value in bucket.items():
                number = _float(value)
                if number is None or key not in {"CPI", "Core CPI"}:
                    continue
                row = _row(key=f"nowcast-{bucket_name}-{period}-{key}", row_type="model", group="NOWCAST",
                           label=str(key), value=number, unit="%", change=None, change_label="Model estimate",
                           date=payload.get("generatedAt"), tone="neutral", source=str(payload.get("source") or "Cleveland Fed"),
                           source_url=str(payload.get("url") or ""), implication="Model nowcast, not market consensus",
                           metadata={"bucket": bucket_name, "nowcastKey": key, "period": period,
                                     "providerUpdated": bucket.get("Updated"), "fetchedAt": payload.get("generatedAt")})
                row["periodLabel"] = bucket.get("Month") or "Unknown period"
                rows.append(row)
    return rows


def _fred_url(
    dependencies: MacroCpiRegistryDependencies,
    series_id: str,
) -> str:
    template = getattr(
        dependencies.settings,
        "finance_fred_csv_url_template",
        getattr(
            dependencies.settings,
            "food_basket_fred_csv_url_template",
            "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}",
        ),
    )
    url = str(template).format(series_id=series_id)
    lookback_years = int(
        getattr(
            dependencies.settings,
            "fred_csv_lookback_years",
            FRED_CSV_LOOKBACK_YEARS,
        )
        or FRED_CSV_LOOKBACK_YEARS
    )
    start_date = f"{max(1900, datetime.now(timezone.utc).year - lookback_years)}-01-01"
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("cosd", start_date)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _fred_row_date(row: Dict[str, Any]) -> str:
    return str(row.get("observation_date") or row.get("DATE") or row.get("date") or "").strip()


def _series_candidates(series_id: str) -> List[str]:
    for spec in CPI_EVENT_SPECS:
        if str(spec.get("seriesId")) == series_id and spec.get("seriesCandidates"):
            return [str(item) for item in spec.get("seriesCandidates") or []]
    return [series_id]


def _fetch_cpi_series_stats(dependencies: MacroCpiRegistryDependencies) -> Dict[str, Dict[str, Any]]:
    """Collector-only: retain dates so consumers cannot rebind the latest value."""
    if dependencies.http_text_get is None:
        return {}
    stats = {}
    for series_id in sorted({str(spec["seriesId"]) for spec in CPI_EVENT_SPECS}):
        try:
            url = _fred_url(dependencies, series_id)
            text = dependencies.http_text_get(url, timeout=12, headers={"User-Agent": "polydata-cpi-release-command/2.0"})
            rows = []
            for row in csv.DictReader(io.StringIO(str(text or ""))):
                value, date = _float(row.get(series_id)), _fred_row_date(row)
                if value is not None and month_key(date):
                    rows.append({"date": date, "value": value})
            rows.sort(key=lambda row: row["date"])
            if rows:
                stats[series_id] = {"seriesId": series_id, "date": rows[-1]["date"], "observations": rows,
                                    "source": "FRED / BLS CPI", "sourceUrl": f"https://fred.stlouisfed.org/series/{series_id}",
                                    "fetchedAt": _utc_now_iso(dependencies)}
        except Exception:
            continue
    prior = (dependencies.source.get("previousRegistry") or {}).get("actualSeries", {})
    for series_id, stat in prior.items():
        if series_id not in stats:
            stats[series_id] = {**stat, "retained": True}
    return stats


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _event_hours_to_release(release_at: Any) -> Optional[float]:
    parsed = _parse_datetime(release_at)
    if parsed is None:
        return None
    return round((parsed - datetime.now(timezone.utc)).total_seconds() / 3600.0, 1)


def _release_from_rows(rows: List[Dict[str, Any]], now: datetime | None = None) -> Dict[str, Any]:
    releases = [row for row in rows if str(row.get("type") or "").lower() == "release" and str(row.get("group") or "").upper() == "CPI"]
    if not releases:
        return {}
    now = now or datetime.now(timezone.utc)
    recent = [row for row in releases if (parsed := _parse_datetime(row.get("date"))) and 0 <= (now - parsed).total_seconds() <= 3 * 86400]
    if recent:
        releases = recent
    def release_sort(row: Dict[str, Any]) -> tuple[int, datetime]:
        parsed = _parse_datetime(row.get("date")) or datetime.max.replace(tzinfo=timezone.utc)
        return (0 if parsed >= now else 1, parsed)
    row = sorted(releases, key=release_sort)[0]
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    release_at = metadata.get("releaseAt") or row.get("date")
    return {
        "id": metadata.get("id") or row.get("key"),
        "kind": "cpi",
        "title": row.get("label") or "Consumer Price Index",
        "referencePeriod": metadata.get("referencePeriod"),
        "releaseAt": release_at,
        "releaseTimeEt": metadata.get("releaseTimeEt") or row.get("changeLabel") or row.get("value"),
        "source": row.get("source"),
        "sourceUrl": row.get("sourceUrl"),
        "hoursToEvent": _event_hours_to_release(release_at),
    }


def _nowcast_lookup_from_rows(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    lookup: Dict[str, Any] = {}
    for row in rows:
        if str(row.get("type") or "").lower() != "model":
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        label = str(metadata.get("nowcastKey") or row.get("label") or "").strip().lower()
        bucket = str(metadata.get("bucket") or "").strip()
        value = _float(row.get("value"))
        if not label or value is None:
            continue
        if not bucket:
            bucket = "yearOverYear" if abs(value) >= 1.0 else "monthOverMonth"
        lookup[f"{metadata.get('period')}:{bucket}:{label}"] = {
            "value": round(value, 2),
            "label": f"{value:.2f}%",
            "source": row.get("source") or "Cleveland Fed Inflation Nowcasting",
            "sourceUrl": row.get("sourceUrl"),
            "generatedAt": row.get("date"),
        }
    return lookup


def _period_from_release(release: Dict[str, Any]) -> Optional[str]:
    text = str(release.get("referencePeriod") or "").strip()
    if text:
        return text
    parsed = _parse_datetime(release.get("releaseAt"))
    if parsed is None:
        return None
    month = parsed.month - 1
    year = parsed.year
    if month == 0:
        month = 12
        year -= 1
    return f"{year}-{month:02d}"


def _compose_cpi_release_events(
    dependencies: MacroCpiRegistryDependencies,
    rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    now = _parse_datetime(_utc_now_iso(dependencies)) or datetime.now(timezone.utc)
    release = _release_from_rows(rows, now)
    release_at = _parse_datetime(release.get("releaseAt"))
    is_released = bool(release_at and release_at <= now)
    period = _period_from_release(release)
    period_key = month_key(period)
    nowcasts = _nowcast_lookup_from_rows(rows)
    actual_series = _fetch_cpi_series_stats(dependencies)
    events: List[Dict[str, Any]] = []
    for spec in CPI_EVENT_SPECS:
        stat = actual_series.get(str(spec["seriesId"])) or {}
        metric = str(spec["metric"])
        actual = monthly_metric(stat.get("observations", []), period_key, metric) if is_released else None
        previous = monthly_metric(stat.get("observations", []), shift_month(period_key, -1), metric) if period_key else None
        actual = round(actual, 1) if actual is not None else None
        previous = round(previous, 1) if previous is not None else None
        forecast = nowcasts.get(f"{period_key}:{spec['bucket']}:{str(spec['nowcastKey']).lower()}") or {}
        previous_seed = dependencies.source.get("previousRegistry") or {}
        prior_event = next((event for event in previous_seed.get("events", []) if event.get("key") == spec["key"] and month_key(event.get("period")) == period_key), {})
        if is_released:
            frozen_at = _parse_datetime(prior_event.get("forecastAsOf"))
            forecast = {"value": prior_event.get("forecast"), "label": prior_event.get("forecastLabel"),
                        "source": prior_event.get("forecastSource"), "sourceUrl": prior_event.get("forecastSourceUrl"),
                        "generatedAt": prior_event.get("forecastAsOf")} if frozen_at and release_at and frozen_at < release_at else {}
        surprise = None
        if actual is not None and _float(forecast.get("value")) is not None:
            surprise = round(float(actual) - float(forecast["value"]), 2)
        events.append(
            {
                "key": spec["key"],
                "title": spec["title"],
                "period": period or stat.get("date"),
                "releaseAt": release.get("releaseAt"),
                "status": "released" if is_released else "scheduled",
                "unit": "%",
                "actual": actual,
                "actualLabel": _pct_value_label(actual),
                "forecast": forecast.get("value"),
                "forecastLabel": forecast.get("label") or "--",
                "forecastKind": "Nowcast (model)",
                "forecastAsOf": forecast.get("generatedAt"),
                "adjustment": "NSA" if metric == "yoy" else "SA",
                "limitation": "No period-matched pre-release nowcast" if not forecast else None,
                "previous": previous,
                "previousLabel": _pct_value_label(previous),
                "surprise": surprise,
                "surpriseLabel": _signed(surprise, suffix="pp") if surprise is not None else "--",
                "seriesId": spec["seriesId"],
                "source": stat.get("source") or "BLS / FRED",
                "sourceUrl": stat.get("sourceUrl") or "",
                "forecastSource": forecast.get("source") or "Cleveland Fed Inflation Nowcasting",
                "forecastSourceUrl": forecast.get("sourceUrl") or "",
                "asOf": stat.get("date"),
                "actualBasis": "Derived from latest FRED index vintage; not an archived first-release print",
            }
        )
    forecast_count = sum(1 for item in events if _float(item.get("forecast")) is not None)
    previous_count = sum(1 for item in events if _float(item.get("previous")) is not None)
    actual_count = sum(1 for item in events if _float(item.get("actual")) is not None)
    return {
        "release": release,
        "events": events,
        "actualSeries": actual_series,
        "eventSummary": {
            "period": period,
            "status": "released" if is_released else "scheduled",
            "eventCount": len(events),
            "actualCount": actual_count,
            "forecastCount": forecast_count,
            "previousCount": previous_count,
            "hoursToEvent": release.get("hoursToEvent"),
            "signal": "CPI RELEASE SCHEDULED" if not is_released else "CPI RELEASED",
            "sourceLabel": "BLS calendar / Cleveland Fed nowcast / FRED actuals",
        },
    }


def _energy_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        change = _float(item.get("changeWeek"))
        tone = "hot" if (change or 0) > 0 else ("cool" if (change or 0) < 0 else "neutral")
        rows.append(
            _row(
                key=f"energy-{item.get('key') or item.get('label')}",
                row_type="proxy",
                group="ENERGY",
                label=str(item.get("label") or "Energy series"),
                value=item.get("value"),
                unit=item.get("unit"),
                change=change,
                change_label=f"{_signed(change)} {item.get('unit') or 'units'} WoW",
                date=item.get("date"),
                tone=tone,
                source=str(item.get("source") or "EIA"),
                source_url=str(item.get("sourceUrl") or ""),
                implication="Commodity price proxy, not weighted CPI contribution",
                metadata={"contextOnly": True, "fetchedAt": payload.get("generatedAt"), "publishedAt": None, "frequency": "weekly", "adjustment": "Source basis"},
            )
        )
    return rows


def _food_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        mom = _float(item.get("momPct"))
        tone = "hot" if (mom or 0) >= 0.35 else ("cool" if (mom or 0) <= -0.2 else "watch")
        rows.append(
            _row(
                key=f"food-{item.get('key') or item.get('seriesId')}",
                row_type="component",
                group="FOOD",
                label=str(item.get("label") or "Food CPI component"),
                value=item.get("value"),
                unit="idx",
                change=mom,
                change_label=f"{_signed(mom, suffix='%')} MoM",
                date=item.get("date"),
                tone=tone,
                source=str(item.get("source") or "FRED / BLS CPI"),
                source_url=str(item.get("sourceUrl") or ""),
                implication="Food CPI observation, not weighted contribution",
                metadata={"seriesId": item.get("seriesId"), "fetchedAt": payload.get("generatedAt"), "publishedAt": None, "frequency": "monthly", "adjustment": "Source basis"},
            )
        )
    return rows


def _macro_driver_rows(payload: Dict[str, Any], *, default_group: str, implication: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        item_metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        change = item.get("changeValue")
        metric = item.get("changeUnit") or ""
        rows.append(
            _row(
                key=f"{default_group.lower()}-{item.get('key') or item.get('seriesId') or item.get('label')}",
                row_type="series" if item.get("seriesId") else "event",
                group=str(item.get("group") or default_group).upper(),
                label=str(item.get("label") or "Macro driver"),
                value=item.get("value"),
                unit=item.get("unit"),
                change=change,
                change_label=item.get("changeLabel") or "Change unavailable",
                date=item.get("date"),
                tone=str(item.get("tone") or "neutral"),
                source=str(item.get("source") or payload.get("source") or "Public macro source"),
                source_url=str(item.get("sourceUrl") or payload.get("sourceUrl") or ""),
                implication=implication,
                metadata={
                    **item_metadata,
                    **{key: item.get(key) for key in ("periodLabel", "frequency", "adjustment", "fetchedAt", "publishedAt", "changeUnit", "changeWindow", "contextOnly", "levelLabel", "levelBasis", "retained")},
                    "valueLabel": item.get("valueLabel"),
                    "rawChange": item.get("change"),
                    "rawChangePct": item.get("changePct"),
                    "metric": item.get("metric"),
                    "unit": item.get("unit"),
                    "seriesId": item.get("seriesId"),
                },
            )
        )
    for row in rows:
        row["valueLabel"] = (row.get("metadata") or {}).get("valueLabel") or row["valueLabel"]
        row["periodLabel"] = (row.get("metadata") or {}).get("periodLabel") or row.get("date")
    return rows


def _summarize(panel_id: str, rows: List[Dict[str, Any]], sources: Dict[str, str], config: Dict[str, Any]) -> Dict[str, Any]:
    hot = sum(1 for row in rows if row.get("tone") == "hot")
    cool = sum(1 for row in rows if row.get("tone") == "cool")
    watch = sum(1 for row in rows if row.get("tone") == "watch")
    signal = "OBSERVED MACRO DATA" if rows else str(config.get("emptySignal") or "REGISTRY WARMING")
    bias = "neutral" if rows else "unknown"
    top = None  # Units and time windows differ; no cross-unit ranking or causal vote.
    leaves = {key: value for key, value in sources.items() if not any(other.startswith(key + ".") for other in sources)}
    providers = {urlsplit(str(row.get("sourceUrl") or "")).hostname or ("FRED" if "FRED" in str(row.get("source") or "").upper() else str(row.get("sourceLabel") or "Unknown")) for row in rows}
    return {
        "panelId": panel_id,
        "signal": signal,
        "signalLabel": config.get("signalLabel"),
        "bias": bias,
        "hotCount": hot,
        "coolCount": cool,
        "watchCount": watch,
        "rowCount": len(rows),
        "coverage": sum(1 for value in leaves.values() if str(value).lower() in {"ok", "redis-seed", "sqlite-seed", "empty"}),
        "sourceCount": len(leaves),
        "providerCount": len(providers),
        "interpretation": "Directional observations, not independent evidence or weighted CPI contributions",
        "topMover": top,
        "topLabel": top.get("label") if top else None,
        "topValueLabel": top.get("valueLabel") if top else None,
        "topChangeLabel": top.get("changeLabel") if top else None,
        "sourceLabel": config.get("source"),
    }


def _payload(
    dependencies: MacroCpiRegistryDependencies,
    panel_id: str,
    rows: List[Dict[str, Any]],
    sources: Dict[str, str],
    *,
    limit: int,
) -> Dict[str, Any]:
    config = PANEL_CONFIGS[panel_id]
    previous = dependencies.source.get("previousRegistry") or {}
    present = {row.get("key") for row in rows}
    if any(state not in {"ok", "empty", "redis-seed", "sqlite-seed"} for state in sources.values()):
        rows += [{**row, "metadata": {**(row.get("metadata") or {}), "retained": True}} for row in previous.get("items", []) if row.get("key") not in present and row.get("type") != "release"]
    capped = _rank_rows(rows)[: _limit(limit)]
    cpi_release = (
        _compose_cpi_release_events(dependencies, rows)
        if panel_id == "cpi-release-command-center"
        else {}
    )
    summary = _summarize(panel_id, capped, sources, config)
    if panel_id == "cpi-release-command-center":
        summary = {**summary, **(cpi_release.get("eventSummary") or {})}
    status = "ok" if capped and all(str(value).lower() in {"ok", "empty", "redis-seed", "sqlite-seed"} for value in sources.values()) else ("degraded" if capped else "warming")
    if panel_id == "cpi-release-command-center":
        for spec in CPI_EVENT_SPECS:
            sources[f"actuals.{spec['seriesId']}"] = "ok" if spec["seriesId"] in cpi_release.get("actualSeries", {}) and not cpi_release["actualSeries"][spec["seriesId"]].get("retained") else "error"
        event_summary = cpi_release.get("eventSummary") or {}
        if event_summary.get("previousCount") != 4 or (event_summary.get("status") == "released" and event_summary.get("actualCount") != 4):
            sources["referenceValues"] = "incomplete"
        summary.update(_summarize(panel_id, capped, sources, config))
        summary.update(cpi_release.get("eventSummary") or {})
        if capped and (any(value not in {"ok", "empty", "redis-seed", "sqlite-seed"} for value in sources.values()) or summary.get("forecastCount") != 4):
            status = "degraded"
    payload = {
        "schemaVersion": 2,
        "expectedIntervalSeconds": 1800,
        "generatedAt": _utc_now_iso(dependencies),
        "panelId": panel_id,
        "source": config.get("source"),
        "sourceUrl": "",
        "status": status,
        "cacheMode": "composed-seed",
        "sources": sources,
        "summary": summary,
        "items": capped,
    }
    if panel_id == "cpi-release-command-center":
        payload.update(cpi_release)
    return payload


def _with_mode(payload: Dict[str, Any], mode: str) -> Dict[str, Any]:
    return {**payload, "cacheMode": mode}


def _read_seeded(
    dependencies: MacroCpiRegistryDependencies,
    panel_id: str,
) -> Optional[Dict[str, Any]]:
    namespace = _snapshot_namespace(panel_id)
    if dependencies.get_cached_json is not None:
        payload = dependencies.get_cached_json(namespace, CACHE_KEY)
        if isinstance(payload, dict):
            return _with_mode(payload, "redis-seed")
    store = dependencies.snapshot_store
    if store is not None:
        payload = store.get(namespace, CACHE_KEY)
        if isinstance(payload, dict):
            return _with_mode(payload, "sqlite-seed")
        stale = store.get_stale(namespace, CACHE_KEY)
        if isinstance(stale, dict):
            return _with_mode(stale, "stale-seed")
    return None


def _snapshot(fn, *args: Any, **kwargs: Any) -> Dict[str, Any]:
    try:
        payload = fn(*args, **kwargs)
    except Exception:
        return {"status": "error", "items": [], "sources": {"snapshot": "error"}}
    return payload if isinstance(payload, dict) else {"status": "invalid", "items": []}


def _inflation_nowcast_seeded_snapshot(
    dependencies: MacroCpiRegistryDependencies,
) -> Dict[str, Any]:
    payload = None
    if dependencies.get_cached_json is not None:
        payload = dependencies.get_cached_json(
            runtime_service.INFLATION_NOWCAST_NAMESPACE,
            runtime_service.INFLATION_NOWCAST_CACHE_KEY,
        )
    if not isinstance(payload, dict):
        store = dependencies.snapshot_store
        if store is not None:
            payload = store.get(runtime_service.INFLATION_NOWCAST_NAMESPACE, runtime_service.INFLATION_NOWCAST_CACHE_KEY)
            if not isinstance(payload, dict):
                payload = store.get_stale(runtime_service.INFLATION_NOWCAST_NAMESPACE, runtime_service.INFLATION_NOWCAST_CACHE_KEY)
    if isinstance(payload, dict):
        result = runtime_service.normalize_inflation_nowcast_payload(
            payload,
            ctx=dependencies.source,
            generated_at=_utc_now_iso(dependencies),
        )
        collected = _parse_datetime(payload.get("generatedAt"))
        if collected is None or (datetime.now(timezone.utc) - collected).total_seconds() > 2700:
            result["status"] = "stale"
        return result
    return runtime_service.normalize_inflation_nowcast_payload(
        {"status": "seed-miss"},
        ctx=dependencies.source,
        generated_at=_utc_now_iso(dependencies),
    )


def build_cpi_release_command_center_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = MacroCpiRegistryDependencies.from_context(ctx)
    calendar = _snapshot(
        cpi_release_calendar_service.get_cpi_release_calendar_snapshot,
        dependencies.source,
        limit=20,
        allow_live_build=False,
    )
    nowcast = _snapshot(
        _inflation_nowcast_seeded_snapshot,
        dependencies,
    )
    rows = _calendar_rows(calendar) + _nowcast_rows(nowcast)
    sources: Dict[str, str] = {"calendar": _snapshot_status(calendar), "nowcast": _snapshot_status(nowcast)}
    _merge_sources(sources, "calendar", calendar)
    return _payload(
        dependencies,
        "cpi-release-command-center",
        rows,
        sources,
        limit=limit,
    )


def build_cpi_components_pressure_registry_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = MacroCpiRegistryDependencies.from_context(ctx)
    energy = _snapshot(
        energy_gasoline_shock_service.get_energy_gasoline_shock_snapshot,
        dependencies.source,
        limit=12,
        allow_live_build=False,
    )
    food = _snapshot(
        food_retail_basket_service.get_food_retail_basket_snapshot,
        dependencies.source,
        limit=12,
        allow_live_build=False,
    )
    shelter = _snapshot(
        macro_cpi_panels_service.get_shelter_rent_oer_pressure_snapshot,
        dependencies.source,
        limit=12,
    )
    goods = _snapshot(
        macro_cpi_panels_service.get_supply_tariff_import_watch_snapshot,
        dependencies.source,
        limit=16,
    )
    rows = (
        _energy_rows(energy)
        + _food_rows(food)
        + _macro_driver_rows(shelter, default_group="SHELTER", implication="core CPI shelter stickiness")
        + [row for row in _macro_driver_rows(goods, default_group="GOODS", implication="CPI goods observation") if str((row.get("metadata") or {}).get("seriesId") or "").startswith(("CUSR", "CPI"))]
    )
    sources: Dict[str, str] = {"energy": _snapshot_status(energy), "food": _snapshot_status(food), "shelter": _snapshot_status(shelter), "goods": _snapshot_status(goods)}
    _merge_sources(sources, "energy", energy)
    _merge_sources(sources, "food", food)
    _merge_sources(sources, "shelter", shelter)
    _merge_sources(sources, "goods", goods)
    return _payload(
        dependencies,
        "cpi-components-pressure-registry",
        rows,
        sources,
        limit=limit,
    )


def build_goods_tariff_supply_watch_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = MacroCpiRegistryDependencies.from_context(ctx)
    supply = _snapshot(
        macro_cpi_panels_service.get_supply_tariff_import_watch_snapshot,
        dependencies.source,
        limit=30,
    )
    rows = _macro_driver_rows(supply, default_group="GOODS", implication="goods CPI / tariff pressure")
    sources: Dict[str, str] = {"supply": _snapshot_status(supply)}
    _merge_sources(sources, "supply", supply)
    return _payload(
        dependencies,
        "goods-tariff-supply-watch",
        rows,
        sources,
        limit=limit,
    )


def build_labor_services_inflation_monitor_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = MacroCpiRegistryDependencies.from_context(ctx)
    labor = _snapshot(
        macro_cpi_panels_service.get_labor_wage_services_pressure_snapshot,
        dependencies.source,
        limit=30,
    )
    rows = _macro_driver_rows(labor, default_group="LABOR", implication="services CPI / Fed wage pressure")
    sources: Dict[str, str] = {"labor": _snapshot_status(labor)}
    _merge_sources(sources, "labor", labor)
    return _payload(
        dependencies,
        "labor-services-inflation-monitor",
        rows,
        sources,
        limit=limit,
    )


def build_fed_reaction_growth_risk_board_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = MacroCpiRegistryDependencies.from_context(ctx)
    fed = _snapshot(
        macro_cpi_panels_service.get_fed_rates_polymarket_gap_snapshot,
        dependencies.source,
        limit=30,
    )
    growth = _snapshot(
        macro_cpi_panels_service.get_growth_demand_recession_tracker_snapshot,
        dependencies.source,
        limit=30,
    )
    calendar = _snapshot(
        cpi_release_calendar_service.get_cpi_release_calendar_snapshot,
        dependencies.source,
        limit=8,
        allow_live_build=False,
    )
    rows = (
        _macro_driver_rows(fed, default_group="FED", implication="Fed reaction path")
        + _macro_driver_rows(growth, default_group="GROWTH", implication="growth / recession risk")
        + [row for row in _calendar_rows(calendar) if str(row.get("group")).upper() == "FOMC"]
    )
    sources: Dict[str, str] = {"fed": _snapshot_status(fed), "growth": _snapshot_status(growth), "calendar": _snapshot_status(calendar)}
    _merge_sources(sources, "fed", fed)
    _merge_sources(sources, "growth", growth)
    _merge_sources(sources, "calendar", calendar)
    return _payload(
        dependencies,
        "fed-reaction-growth-risk-board",
        rows,
        sources,
        limit=limit,
    )


BUILDERS = {
    "cpi-release-command-center": build_cpi_release_command_center_snapshot,
    "cpi-components-pressure-registry": build_cpi_components_pressure_registry_snapshot,
    "goods-tariff-supply-watch": build_goods_tariff_supply_watch_snapshot,
    "labor-services-inflation-monitor": build_labor_services_inflation_monitor_snapshot,
    "fed-reaction-growth-risk-board": build_fed_reaction_growth_risk_board_snapshot,
}


MACRO_CPI_REGISTRY_PANEL_IDS = tuple(BUILDERS.keys())


def build_macro_cpi_registry_payload(
    ctx: Mapping[str, Any],
    panel_id: str,
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    builder = BUILDERS[panel_id]
    return builder(ctx, limit=limit)


def get_macro_cpi_registry_snapshot(
    ctx: Mapping[str, Any],
    panel_id: str,
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = MacroCpiRegistryDependencies.from_context(ctx)
    seeded = _read_seeded(dependencies, panel_id)
    if seeded is not None:
        return _normalize_macro_cpi_registry_payload(
            seeded,
            dependencies=dependencies,
            panel_id=panel_id,
            limit=limit,
        )
    return {"schemaVersion": 2, "panelId": panel_id, "status": "warming", "cacheMode": "seed-miss",
            "generatedAt": None, "items": [], "sources": {}, "summary": {"rowCount": 0}}


def get_cpi_release_command_center_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    return get_macro_cpi_registry_snapshot(ctx, "cpi-release-command-center", limit=limit)


def get_cpi_components_pressure_registry_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    return get_macro_cpi_registry_snapshot(ctx, "cpi-components-pressure-registry", limit=limit)


def get_goods_tariff_supply_watch_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    return get_macro_cpi_registry_snapshot(ctx, "goods-tariff-supply-watch", limit=limit)


def get_labor_services_inflation_monitor_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    return get_macro_cpi_registry_snapshot(ctx, "labor-services-inflation-monitor", limit=limit)


def get_fed_reaction_growth_risk_board_snapshot(
    ctx: Mapping[str, Any],
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    return get_macro_cpi_registry_snapshot(ctx, "fed-reaction-growth-risk-board", limit=limit)


def normalize_macro_cpi_registry_payload(
    payload: Any,
    *,
    ctx: Mapping[str, Any],
    panel_id: str,
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    return _normalize_macro_cpi_registry_payload(
        payload,
        dependencies=MacroCpiRegistryDependencies.from_context(ctx),
        panel_id=panel_id,
        limit=limit,
    )


def _normalize_macro_cpi_registry_payload(
    payload: Any,
    *,
    dependencies: MacroCpiRegistryDependencies,
    panel_id: str,
    limit: int,
) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    result = json.loads(json.dumps(payload, ensure_ascii=True, default=str))
    rows = [_enrich_row(row) for row in (result.get("items") or []) if isinstance(row, dict)]
    result["items"] = _rank_rows(rows)[: _limit(limit)]
    result["generatedAt"] = result.get("generatedAt")
    result["panelId"] = str(result.get("panelId") or panel_id)
    result["status"] = str(result.get("status") or ("ok" if rows else "warming"))
    result["cacheMode"] = str(result.get("cacheMode") or "composed-seed")
    result["source"] = str(result.get("source") or PANEL_CONFIGS.get(panel_id, {}).get("source") or "Public macro sources")
    result["sources"] = result.get("sources") if isinstance(result.get("sources"), dict) else {}
    result["summary"] = _summarize(panel_id, result["items"], result["sources"], PANEL_CONFIGS.get(panel_id, {}))
    if panel_id == "cpi-release-command-center":
        result["summary"].update(result.get("eventSummary") or {})
    return result
