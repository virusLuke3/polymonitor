from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any, Callable, Dict, List, Optional
from zoneinfo import ZoneInfo

from api.context import resolve_optional_service_callable, resolve_service_callable
from api.services import bls_calendar


CPI_CALENDAR_SNAPSHOT_NAMESPACE = "snapshot:macro:cpi-release-calendar"
CPI_CALENDAR_CACHE_KEY = "panel-v1"
DEFAULT_ITEM_LIMIT = 8
EASTERN_TZ = ZoneInfo("America/New_York")

MONTHS: Dict[str, int] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


@dataclass(frozen=True)
class CpiReleaseCalendarDependencies:
    settings: Any
    application: Any
    http_text_get: Callable[..., str]
    beautiful_soup: Any
    get_polymarket_macro_map_snapshot: Callable[..., Any] | None
    utc_now_iso: Callable[..., Any] | None
    snapshot_store: Any
    get_cached_json: Callable[..., Any] | None
    set_cached_json: Callable[..., Any] | None

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> CpiReleaseCalendarDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            settings=context.get("SETTINGS"),
            application=context.get("app"),
            http_text_get=resolve_service_callable(
                context,
                "http_text_get",
            ),
            beautiful_soup=context.get("BeautifulSoup"),
            get_polymarket_macro_map_snapshot=resolve_optional_service_callable(
                context,
                "get_polymarket_macro_map_snapshot",
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
        )


CpiReleaseCalendarContext = (
    Mapping[str, Any] | CpiReleaseCalendarDependencies
)


def _dependencies(
    context: CpiReleaseCalendarContext,
) -> CpiReleaseCalendarDependencies:
    if isinstance(context, CpiReleaseCalendarDependencies):
        return context
    return CpiReleaseCalendarDependencies.from_context(context)


def _utc_now_iso(
    dependencies: CpiReleaseCalendarDependencies,
) -> str:
    if dependencies.utc_now_iso is not None:
        return str(dependencies.utc_now_iso())
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_iso_ts(value: Any) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _html_to_lines(
    dependencies: CpiReleaseCalendarDependencies,
    html: str,
) -> List[str]:
    soup_factory = dependencies.beautiful_soup
    if soup_factory is not None:
        soup = soup_factory(html, "html.parser")
        text = soup.get_text("\n", strip=True)
    else:
        text = re.sub(r"<[^>]+>", "\n", html)
    return [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]


def _month_number(raw: str) -> int:
    key = str(raw or "").strip().strip(".").lower()
    return MONTHS.get(key, 0)


def _parse_et_datetime(month_token: str, day: str, year: str, time_text: str) -> Optional[str]:
    month = _month_number(month_token)
    if not month:
        return None
    time_match = re.match(r"^(\d{1,2}):(\d{2})\s*([AP]M)$", str(time_text or "").strip(), re.I)
    if not time_match:
        return None
    hour = int(time_match.group(1))
    minute = int(time_match.group(2))
    if time_match.group(3).upper() == "PM" and hour != 12:
        hour += 12
    if time_match.group(3).upper() == "AM" and hour == 12:
        hour = 0
    local_dt = datetime(int(year), month, int(day), hour, minute, tzinfo=EASTERN_TZ)
    return local_dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_date_without_year(raw: str, base_year: int) -> Optional[tuple[int, int, int]]:
    match = re.match(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})$", raw)
    if not match:
        return None
    return base_year, _month_number(match.group(1)), int(match.group(2))


def _parse_bea_schedule(
    ctx: CpiReleaseCalendarContext,
    *,
    url: str,
) -> tuple[List[Dict[str, Any]], str]:
    dependencies = _dependencies(ctx)
    html = dependencies.http_text_get(
        url,
        timeout=45,
        headers={
            "Accept": "text/html",
            "User-Agent": "polydata-cpi-calendar/1.0",
        },
    )
    lines = _html_to_lines(dependencies, str(html or ""))
    now = datetime.fromtimestamp(
        _parse_iso_ts(_utc_now_iso(dependencies))
        or datetime.now(timezone.utc).timestamp(),
        timezone.utc,
    )
    items: List[Dict[str, Any]] = []
    for idx, line in enumerate(lines):
        date_parts = _parse_date_without_year(line, now.year)
        if not date_parts:
            continue
        time_text = lines[idx + 1] if idx + 1 < len(lines) else ""
        if not re.match(r"^\d{1,2}:\d{2}\s+[AP]M$", time_text, re.I):
            continue
        title = ""
        for candidate in lines[idx + 2 : idx + 9]:
            if "Personal Income and Outlays" in candidate:
                title = candidate
                break
        if not title:
            continue
        year, month, day = date_parts
        release_at = _parse_et_datetime(datetime(year, month, day).strftime("%B"), str(day), str(year), time_text)
        reference = title.split(",", 1)[1].strip() if "," in title else None
        items.append(
            {
                "id": f"pce-{year}-{month:02d}-{day:02d}",
                "kind": "pce",
                "title": "Personal Income and Outlays / PCE",
                "referencePeriod": reference,
                "releaseAt": release_at,
                "releaseTimeEt": time_text.upper(),
                "source": "BEA Release Schedule",
                "sourceUrl": url,
                "marketRelevance": "PCE / Core PCE / Fed",
            }
        )
    if not items:
        raise ValueError("bea-calendar-no-valid-releases")
    return items, "ok"


def _parse_fomc_schedule(
    ctx: CpiReleaseCalendarContext,
    *,
    url: str,
) -> tuple[List[Dict[str, Any]], str]:
    dependencies = _dependencies(ctx)
    html = dependencies.http_text_get(
        url,
        timeout=45,
        headers={
            "Accept": "text/html",
            "User-Agent": "polydata-cpi-calendar/1.0",
        },
    )
    lines = _html_to_lines(dependencies, str(html or ""))
    items: List[Dict[str, Any]] = []
    now_year = datetime.fromtimestamp(
        _parse_iso_ts(_utc_now_iso(dependencies))
        or datetime.now(timezone.utc).timestamp(),
        timezone.utc,
    ).year
    current_year: Optional[int] = None
    current_month: Optional[str] = None
    for line in lines:
        year_match = re.match(r"^(\d{4}) FOMC Meetings$", line)
        if year_match:
            current_year = int(year_match.group(1))
            current_month = None
            continue
        if current_year is None:
            continue
        if re.match(r"^\d{4} FOMC Meetings$", line):
            break
        if _month_number(line):
            current_month = line
            continue
        date_match = re.match(r"^(\d{1,2})(?:-(\d{1,2}))?\*?$", line)
        if not date_match or not current_month or current_year < now_year or current_year > now_year + 1:
            continue
        end_day = int(date_match.group(2) or date_match.group(1))
        start_day = int(date_match.group(1))
        month = _month_number(current_month)
        release_at = datetime(current_year, month, end_day, 14, 0, tzinfo=EASTERN_TZ).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        range_label = f"{current_month} {start_day}-{end_day}" if start_day != end_day else f"{current_month} {end_day}"
        items.append(
            {
                "id": f"fomc-{current_year}-{month:02d}-{start_day:02d}",
                "kind": "fomc",
                "title": "FOMC decision",
                "referencePeriod": f"{range_label}, {current_year}",
                "releaseAt": release_at,
                "releaseTimeEt": "02:00 PM",
                "source": "Federal Reserve FOMC Calendar",
                "sourceUrl": url,
                "marketRelevance": "Fed decision / rates",
            }
        )
    if not items:
        raise ValueError("fomc-calendar-no-valid-meetings")
    return items, "ok"


def _baseline_from_macro_map(
    dependencies: CpiReleaseCalendarDependencies,
) -> Dict[str, Any]:
    if dependencies.get_polymarket_macro_map_snapshot is None:
        return {"status": "unavailable", "label": "No Polymarket map snapshot"}
    try:
        payload = dependencies.get_polymarket_macro_map_snapshot(limit=20)
    except Exception:
        return {"status": "error", "label": "Polymarket map unavailable"}
    candidates: List[Dict[str, Any]] = []
    for item in payload.get("items") or []:
        if not isinstance(item, dict) or "cpi" not in (item.get("categoryIds") or []):
            continue
        for outcome in item.get("topOutcomes") or []:
            if isinstance(outcome, dict) and outcome.get("yesPrice") is not None:
                candidates.append({"item": item, "outcome": outcome})
    if not candidates:
        return {"status": "empty", "label": "No active CPI bucket market"}
    winner = max(candidates, key=lambda row: float(row["outcome"].get("yesPrice") or 0))
    outcome = winner["outcome"]
    item = winner["item"]
    return {
        "status": "market-implied",
        "label": outcome.get("label") or "Top CPI outcome",
        "probability": outcome.get("yesPrice"),
        "marketTitle": item.get("title"),
        "marketSlug": item.get("slug"),
        "source": "Polymarket Macro Market Map",
    }


def _event_risk(next_event: Optional[Dict[str, Any]], now_ts: float) -> Dict[str, Any]:
    if not next_event:
        return {"signal": "CALENDAR WARMING", "risk": "unknown", "hoursToEvent": None}
    event_ts = _parse_iso_ts(next_event.get("releaseAt"))
    hours = (event_ts - now_ts) / 3600 if event_ts and now_ts else None
    if hours is not None and hours <= 48:
        return {"signal": "EVENT RISK HIGH", "risk": "high", "hoursToEvent": round(hours, 1)}
    if hours is not None and hours <= 24 * 7:
        return {"signal": "EVENT RISK BUILDING", "risk": "medium", "hoursToEvent": round(hours, 1)}
    return {"signal": "CALENDAR WATCH", "risk": "low", "hoursToEvent": round(hours, 1) if hours is not None else None}


def _summary(events: List[Dict[str, Any]], baseline: Dict[str, Any], now_ts: float) -> Dict[str, Any]:
    upcoming = [event for event in events if _parse_iso_ts(event.get("releaseAt")) >= now_ts - 3600]
    next_event = upcoming[0] if upcoming else None
    risk = _event_risk(next_event, now_ts)
    return {
        "nextEvent": next_event,
        "nextCpi": next((event for event in upcoming if event.get("kind") == "cpi"), None),
        "nextPce": next((event for event in upcoming if event.get("kind") == "pce"), None),
        "nextNfp": next((event for event in upcoming if event.get("kind") == "nfp"), None),
        "nextFomc": next((event for event in upcoming if event.get("kind") == "fomc"), None),
        "signal": risk["signal"],
        "risk": risk["risk"],
        "hoursToEvent": risk["hoursToEvent"],
        "baselineLabel": baseline.get("label"),
        "baselineProbability": baseline.get("probability"),
        "consensusStatus": "optional-unavailable",
    }


def _empty_payload(
    dependencies: CpiReleaseCalendarDependencies,
    *,
    status: str = "warming",
    sources: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    now_iso = _utc_now_iso(dependencies)
    return {
        "generatedAt": now_iso,
        "source": "BLS / BEA / Federal Reserve / Polymarket",
        "sourceUrl": getattr(
            dependencies.settings,
            "cpi_calendar_source_url",
            "",
        ),
        "status": status,
        "sources": sources or {},
        "summary": _summary(
            [],
            {"status": "unavailable", "label": "No baseline"},
            _parse_iso_ts(now_iso),
        ),
        "baseline": {"status": "unavailable", "label": "No Polymarket baseline"},
        "consensus": {"status": "optional-unavailable", "label": "Consensus feed not configured"},
        "items": [],
    }


def build_cpi_release_calendar_payload(
    ctx: CpiReleaseCalendarContext,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    settings = dependencies.settings
    now_iso = _utc_now_iso(dependencies)
    now = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    previous = dependencies.snapshot_store.get_stale(CPI_CALENDAR_SNAPSHOT_NAMESPACE, CPI_CALENDAR_CACHE_KEY) if dependencies.snapshot_store else {}
    events, source_states, source_errors, conflicts = bls_calendar.build(
        dependencies.http_text_get, dependencies.snapshot_store, now, previous,
        checked_at=lambda: _utc_now_iso(dependencies))

    source_jobs = (
        ("beaPce", lambda: _parse_bea_schedule(ctx, url=settings.cpi_calendar_bea_schedule_url)),
        ("fomc", lambda: _parse_fomc_schedule(ctx, url=settings.cpi_calendar_fomc_url)),
    )
    for key, builder in source_jobs:
        try:
            rows, state = builder()
            verified_at = _utc_now_iso(dependencies)
            events.extend({**row, "verifiedAt": verified_at} for row in rows)
            source_states[key] = state
        except Exception as exc:
            source_states[key] = "error"
            source_errors[key] = bls_calendar.source_error(exc)
            logger = getattr(dependencies.application, "logger", None)
            if logger is not None:
                logger.exception("cpi release calendar source failed source=%s error=%s", key, source_errors[key])

    baseline = _baseline_from_macro_map(dependencies)
    source_states["pmktBaseline"] = str(baseline.get("status") or "unknown")
    now_iso = _utc_now_iso(dependencies)
    now_ts = _parse_iso_ts(now_iso)
    unique_events = {str(event.get("id") or len(events)): event for event in events if event.get("releaseAt")}
    items = sorted(unique_events.values(), key=lambda event: _parse_iso_ts(event.get("releaseAt")))
    calendar_states = [value for key, value in source_states.items() if key != "pmktBaseline"]
    status = "ok" if items and all(value == "ok" for value in calendar_states) else ("degraded" if items else "warming")
    verified = [str(row["verifiedAt"]) for row in items if row.get("verifiedAt") and not row.get("retained")]
    return {
        "generatedAt": max(verified) if verified else (previous or {}).get("generatedAt"),
        "projectedAt": now_iso,
        "source": "FRED / New York Fed / BLS via FRASER / BEA / Federal Reserve / Polymarket",
        "sourceUrl": bls_calendar.NYFED_URL,
        "status": status,
        "sources": source_states,
        "sourceErrors": source_errors,
        "failedSources": sorted(key for key in ("nyFed", *bls_calendar.SOURCE_KEYS.values(), "beaPce", "fomc")
                                if source_states.get(key) != "ok"),
        "freshCount": len(verified),
        "retainedCount": len(items) - len(verified),
        "scheduleConflicts": conflicts,
        "summary": _summary(items, baseline, now_ts),
        "baseline": baseline,
        "consensus": {"status": "optional-unavailable", "label": "High-quality consensus is usually paid; panel uses PMKT implied baseline."},
        "items": items,
    }


def normalize_cpi_release_calendar_payload(
    payload: Any,
    *,
    ctx: CpiReleaseCalendarContext,
    limit: int = DEFAULT_ITEM_LIMIT,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    if not isinstance(payload, dict):
        return _empty_payload(
            dependencies,
            status="invalid",
            sources={"payload": "invalid"},
        )
    result = json.loads(json.dumps(payload, ensure_ascii=True, default=str))
    items = [item for item in (result.get("items") or []) if isinstance(item, dict)]
    now_iso = _utc_now_iso(dependencies)
    now_ts = _parse_iso_ts(now_iso)
    items.sort(key=lambda event: _parse_iso_ts(event.get("releaseAt")))
    visible = [item for item in items if _parse_iso_ts(item.get("releaseAt")) >= now_ts - 3600]
    if not visible:
        visible = items
    max_items = max(1, min(int(limit or DEFAULT_ITEM_LIMIT), 20))
    result["items"] = visible[:max_items]
    result["recentReleases"] = [item for item in items if now_ts - 3 * 86400 <= _parse_iso_ts(item.get("releaseAt")) < now_ts]
    result["summary"] = result.get("summary") if isinstance(result.get("summary"), dict) else _summary(items, result.get("baseline") or {}, now_ts)
    result["baseline"] = result.get("baseline") if isinstance(result.get("baseline"), dict) else {"status": "unavailable"}
    result["consensus"] = result.get("consensus") if isinstance(result.get("consensus"), dict) else {"status": "optional-unavailable"}
    result["generatedAt"] = str(result.get("generatedAt") or now_iso)
    result["source"] = str(result.get("source") or "BLS / BEA / Federal Reserve / Polymarket")
    result["sourceUrl"] = str(
        result.get("sourceUrl")
        or getattr(
            dependencies.settings,
            "cpi_calendar_source_url",
            "",
        )
    )
    result["status"] = str(result.get("status") or ("ok" if result["items"] else "warming"))
    return result


def _with_cache_mode(payload: Dict[str, Any], cache_mode: str) -> Dict[str, Any]:
    return {**payload, "cacheMode": str(cache_mode)}


def _read_seeded_snapshot(
    dependencies: CpiReleaseCalendarDependencies,
    *,
    ttl_seconds: int,
) -> Optional[Dict[str, Any]]:
    store = dependencies.snapshot_store
    if getattr(store, "backend", "sqlite") == "redis":
        from api.services.macro_data_policy import read_seeded
        return read_seeded(store, None, CPI_CALENDAR_SNAPSHOT_NAMESPACE, CPI_CALENDAR_CACHE_KEY)
    if dependencies.get_cached_json is not None:
        redis_payload = dependencies.get_cached_json(
            CPI_CALENDAR_SNAPSHOT_NAMESPACE,
            CPI_CALENDAR_CACHE_KEY,
        )
        if isinstance(redis_payload, dict):
            if dependencies.snapshot_store is not None:
                dependencies.snapshot_store.set(
                    CPI_CALENDAR_SNAPSHOT_NAMESPACE,
                    CPI_CALENDAR_CACHE_KEY,
                    redis_payload,
                    ttl_seconds,
                )
            return _with_cache_mode(redis_payload, "redis-seed")

    snapshot_store = dependencies.snapshot_store
    if snapshot_store is None:
        return None
    sqlite_payload = snapshot_store.get(CPI_CALENDAR_SNAPSHOT_NAMESPACE, CPI_CALENDAR_CACHE_KEY)
    if isinstance(sqlite_payload, dict):
        if dependencies.set_cached_json is not None:
            dependencies.set_cached_json(
                CPI_CALENDAR_SNAPSHOT_NAMESPACE,
                CPI_CALENDAR_CACHE_KEY,
                sqlite_payload,
                ttl_seconds,
            )
        return _with_cache_mode(sqlite_payload, "sqlite-seed")
    stale_payload = snapshot_store.get_stale(CPI_CALENDAR_SNAPSHOT_NAMESPACE, CPI_CALENDAR_CACHE_KEY)
    if isinstance(stale_payload, dict):
        if dependencies.set_cached_json is not None:
            dependencies.set_cached_json(
                CPI_CALENDAR_SNAPSHOT_NAMESPACE,
                CPI_CALENDAR_CACHE_KEY,
                stale_payload,
                min(60, ttl_seconds),
            )
        return _with_cache_mode(stale_payload, "stale-seed")
    return None


def _store_live_build_snapshot(
    dependencies: CpiReleaseCalendarDependencies,
    payload: Dict[str, Any],
    *,
    ttl_seconds: int,
) -> None:
    if dependencies.snapshot_store is not None:
        dependencies.snapshot_store.set(
            CPI_CALENDAR_SNAPSHOT_NAMESPACE,
            CPI_CALENDAR_CACHE_KEY,
            payload,
            ttl_seconds,
        )
    if dependencies.set_cached_json is not None:
        dependencies.set_cached_json(
            CPI_CALENDAR_SNAPSHOT_NAMESPACE,
            CPI_CALENDAR_CACHE_KEY,
            payload,
            ttl_seconds,
        )


def get_cpi_release_calendar_snapshot(
    ctx: CpiReleaseCalendarContext,
    limit: int = DEFAULT_ITEM_LIMIT,
    *,
    allow_live_build: bool = True,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    allow_live_build = allow_live_build and getattr(dependencies.snapshot_store, "backend", "sqlite") != "redis"
    ttl_seconds = max(
        300,
        int(
            getattr(
                dependencies.settings,
                "cpi_calendar_ttl_seconds",
                3600,
            )
            or 3600
        ),
    )
    seeded_payload = _read_seeded_snapshot(
        dependencies,
        ttl_seconds=ttl_seconds,
    )
    if seeded_payload is not None:
        return normalize_cpi_release_calendar_payload(
            seeded_payload,
            ctx=dependencies,
            limit=limit,
        )
    if not allow_live_build:
        return normalize_cpi_release_calendar_payload(
            {
                "status": "warming",
                "cacheMode": "seed-miss",
                "sources": {},
                "items": [],
            },
            ctx=dependencies,
            limit=limit,
        )
    payload = _with_cache_mode(build_cpi_release_calendar_payload(ctx), "live-build")
    if payload.get("items"):
        _store_live_build_snapshot(
            dependencies,
            payload,
            ttl_seconds=ttl_seconds,
        )
    return normalize_cpi_release_calendar_payload(
        payload,
        ctx=dependencies,
        limit=limit,
    )
