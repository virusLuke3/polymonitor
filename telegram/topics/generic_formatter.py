from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import replace
from typing import Any, Dict, Iterable, Mapping, Sequence

from .models import MessageCandidate, source_clock


_VOLATILE_KEY_RE = re.compile(
    r"(?:^|_)(?:generated|updated|fetched|observed|created|received|checked|attempt|success|expires?)"
    r"(?:at|time|timestamp)?$|(?:^|_)(?:age|latency|duration|elapsed)(?:seconds?|ms|minutes?)?$",
    re.IGNORECASE,
)
_SENSITIVE_KEY_RE = re.compile(
    r"(?:token|secret|password|passwd|authorization|api[_-]?key|cookie|session|chat[_-]?id|"
    r"thread[_-]?id|email|phone|private|credential|filesystem|file[_-]?path|home[_-]?dir|user[_-]?id)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(token|secret|password|passwd|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+"
)
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_LOCAL_PATH_RE = re.compile(
    r"(?:/(?:home|var|etc|opt|srv|tmp|root|Users)/[^\s,;]+)|(?:[A-Za-z]:\\[^\s,;]+)",
    re.IGNORECASE,
)
_SPACE_RE = re.compile(r"\s+")

_STATUS_KEYS = (
    "status", "health", "freshness", "sourceStatus", "sourceMode", "mode",
)
_IDENTITY_KEYS = (
    "id", "title", "headline", "name", "label", "metric", "type", "kind",
    "status", "severity", "source", "category", "symbol", "eventTitle",
    "marketTitle", "question", "asset", "entity", "locationLabel", "hazardKind",
    "metricLabel", "value", "valueLabel", "changeLabel", "rating", "state",
)
_DISPLAY_TITLE_KEYS = (
    "title", "headline", "name", "label", "metric", "eventTitle", "marketTitle",
    "question", "entity", "locationLabel", "hazardKind", "asset", "type", "kind",
)
_DISPLAY_DETAIL_KEYS = ("metricLabel", "valueLabel", "changeLabel", "status", "severity", "source", "category", "symbol")
_COLLECTION_KEYS = (
    "items", "rows", "events", "signals", "alerts", "markets", "games", "news",
    "entries", "results", "records", "incidents", "risks", "watchlist",
)
_EVENT_CLOCK_FIELDS = (
    "publishedAt", "published_at", "evidencePublishedAt", "reported_time",
    "observedAt", "timestamp", "occurredAt", "eventTime", "event_time",
    "updatedAt", "lastUpdate", "receivedAt",
)


def _safe_text(value: Any, *, limit: int = 180) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    text = _SPACE_RE.sub(" ", str(value)).strip()
    if not text:
        return ""
    text = _BEARER_RE.sub("Bearer [redacted]", text)
    text = _SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = _URL_RE.sub("[link omitted]", text)
    text = _LOCAL_PATH_RE.sub("[local path omitted]", text)
    return text[:limit]


def _actual_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    data = payload.get("data")
    if isinstance(data, Mapping) and not any(key in payload for key in ("items", "rows", "events", "signals")):
        return data
    return payload


def _title_case_panel_id(panel_id: str) -> str:
    return " ".join(part.capitalize() for part in panel_id.replace("_", "-").split("-") if part)


def _first_scalar(mapping: Mapping[str, Any], keys: Iterable[str], *, limit: int = 180) -> str:
    for key in keys:
        if _SENSITIVE_KEY_RE.search(key):
            continue
        value = _safe_text(mapping.get(key), limit=limit)
        if value:
            return value
    return ""


def _semantic_item(item: Mapping[str, Any]) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for key in _IDENTITY_KEYS:
        if _SENSITIVE_KEY_RE.search(key) or _VOLATILE_KEY_RE.search(key):
            continue
        value = _safe_text(item.get(key), limit=240)
        if value:
            result[key] = value
    return result


def _iter_collections(payload: Mapping[str, Any]) -> Iterable[tuple[str, Sequence[Any]]]:
    seen: set[str] = set()
    for key in _COLLECTION_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            seen.add(key)
            yield key, value
    for key, value in payload.items():
        if key in seen or _SENSITIVE_KEY_RE.search(str(key)) or _VOLATILE_KEY_RE.search(str(key)):
            continue
        if isinstance(value, list) and value and all(isinstance(item, Mapping) for item in value[:5]):
            yield str(key), value


def semantic_projection(panel_id: str, payload: Mapping[str, Any]) -> Dict[str, Any]:
    actual = _actual_payload(payload)
    status: Dict[str, str] = {}
    for key in _STATUS_KEYS:
        value = _safe_text(actual.get(key), limit=80)
        if value:
            status[key] = value
    degraded = actual.get("degraded")
    if isinstance(degraded, bool):
        status["degraded"] = str(degraded).lower()

    collections: Dict[str, Dict[str, Any]] = {}
    for key, values in _iter_collections(actual):
        identities = [_semantic_item(item) for item in values if isinstance(item, Mapping)]
        identities = [identity for identity in identities if identity]
        identities.sort(key=lambda item: json.dumps(item, ensure_ascii=True, sort_keys=True))
        collections[key] = {"count": len(values), "items": identities[:50]}

    summary = actual.get("summary") if isinstance(actual.get("summary"), Mapping) else {}
    summary_status: Dict[str, str] = {}
    for key in _STATUS_KEYS:
        value = _safe_text(summary.get(key), limit=80)
        if value:
            summary_status[key] = value

    return {
        "panelId": panel_id,
        "status": status,
        "summaryStatus": summary_status,
        "collections": collections,
    }


def _semantic_hash(panel_id: str, payload: Mapping[str, Any]) -> str:
    serialized = json.dumps(semantic_projection(panel_id, payload), ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]


def _status_line(payload: Mapping[str, Any]) -> str:
    actual = _actual_payload(payload)
    values: list[str] = []
    for key in _STATUS_KEYS:
        value = _safe_text(actual.get(key), limit=60)
        if value and value.lower() not in {item.lower() for item in values}:
            values.append(value)
    degraded = actual.get("degraded")
    if degraded is True and "degraded" not in {item.lower() for item in values}:
        values.append("degraded")
    return " | ".join(values[:3]) or "snapshot available"


def _display_rows(payload: Mapping[str, Any]) -> list[str]:
    actual = _actual_payload(payload)
    rows: list[str] = []
    for _key, values in _iter_collections(actual):
        for item in values:
            if not isinstance(item, Mapping):
                continue
            title = _first_scalar(item, _DISPLAY_TITLE_KEYS, limit=130)
            if not title:
                continue
            details: list[str] = []
            for key in _DISPLAY_DETAIL_KEYS:
                detail = _safe_text(item.get(key), limit=50)
                if detail and detail.lower() not in {title.lower(), *(value.lower() for value in details)}:
                    details.append(detail)
            suffix = f" | {' | '.join(details[:2])}" if details else ""
            rows.append(f"- {title}{suffix}")
            if len(rows) >= 3:
                return rows
    return rows


def _collection_count_line(payload: Mapping[str, Any]) -> str:
    actual = _actual_payload(payload)
    parts: list[str] = []
    for key, values in _iter_collections(actual):
        parts.append(f"{key} {len(values)}")
        if len(parts) >= 4:
            break
    return " | ".join(parts)


def _priority(payload: Mapping[str, Any]) -> str:
    projection = semantic_projection("priority", payload)
    words = json.dumps(projection, ensure_ascii=True).lower()
    return "high" if any(word in words for word in ("critical", "emergency", "unhealthy", "alert")) else "normal"


def format_generic_snapshot(panel_id: str, payload: Mapping[str, Any], *, topic: str) -> list[MessageCandidate]:
    if not isinstance(payload, Mapping):
        return []
    projection = semantic_projection(panel_id, payload)
    has_status = bool(projection["status"] or projection["summaryStatus"])
    has_collections = bool(projection["collections"])
    if not has_status and not has_collections:
        return []

    lines = [f"Status: {_status_line(payload)}"]
    count_line = _collection_count_line(payload)
    if count_line:
        lines.append(f"Records: {count_line}")
    lines.extend(_display_rows(payload))
    lines.append("#PanelUpdate")
    text = "\n".join([f"📡 {_title_case_panel_id(panel_id)}", *lines])
    return [
        MessageCandidate(
            topic=topic,
            dedupe_key=f"generic:{panel_id}:{_semantic_hash(panel_id, payload)}",
            text=text,
            priority=_priority(payload),
            metadata={"panel": panel_id, "formatter": "generic-semantic-v1"},
            link_preview=False,
        )
    ]


def format_latest_generic_snapshot(panel_id: str, payload: Mapping[str, Any], *, topic: str) -> list[MessageCandidate]:
    actual = _actual_payload(payload)
    # These panels share a seed. Each topic message must use the panel's own evidence.
    if panel_id == "crypto-exchange-inflow":
        inflows = actual.get("inflows") or {}
        actual = {"items": inflows.get("rows") or []} if inflows.get("liveAvailable") is True else {}
    elif panel_id == "crypto-order-flow":
        rows = []
        for asset, item in (actual.get("assets") or {}).items():
            flow = item.get("flow") or {}
            if isinstance(flow.get("net"), (int, float)) and flow.get("to"):
                rows.append({"title": f"{asset} sampled trade flow", "timestamp": flow["to"],
                             "metricLabel": f'{flow["net"]:+,.0f} USD net', "source": item.get("venue")})
        actual = {"items": rows}
    elif panel_id == "crypto-oracle-reference":
        actual = {"items": [
            {"title": f"{asset} oracle reference", "timestamp": latest.get("event_at_ms"),
             "metricLabel": latest.get("value"), "source": ref.get("source")}
            for asset, ref in (actual.get("references") or {}).items()
            if ref.get("status") == "ok" and (latest := ref.get("latest")) and latest.get("value") is not None
        ]}
    elif panel_id == "options-implied-probability":
        actual = {"items": [
            {"title": f"{asset} options distribution", "observedAt": row.get("observedAt"),
             "metricLabel": f'{len(row["expiries"])} expiries', "source": row.get("source"),
             "value": row["expiries"][0].get("underlying")}
            for asset, row in (actual.get("options") or {}).items()
            if row.get("status") == "ok" and row.get("expiries")
        ]}
    elif panel_id == "company-events":
        actual = {"filings": [row for company in actual.get("companies") or [] for row in company.get("filings") or []]}
    collections = {
        key: [
            row for row in rows
            if isinstance(row, dict) and not row.get("stale")
            and str(row.get("status")) not in {"stale", "unavailable", "error"}
        ]
        for key, rows in _iter_collections(actual)
        if key not in {"sources", "errors", "categories", "providerStates", "countryRiskBreakdown",
                       "sanctionsTargetBreakdown", "targetBreakdown", "sportsContext"}
    }
    collections = {key: rows for key, rows in collections.items() if rows}
    if not collections:
        return []
    # Ignore schedule dates and fetch clocks when a row has a real event or publication time.
    now = time.time()
    timed = (
        (stamp, key, row)
        for key, rows in collections.items()
        for row in rows
        if (stamp := source_clock(row, *_EVENT_CLOCK_FIELDS)) is not None and stamp <= now
    )
    latest = max(timed, key=lambda entry: entry[0], default=None)
    projection = {key: actual[key] for key in _STATUS_KEYS if key in actual}
    if latest:
        stamp, key, row = latest
        projection[key] = [row]
        return [replace(message, observed_at=stamp) for message in format_generic_snapshot(panel_id, projection, topic=topic)]
    if any(field in row for rows in collections.values() for row in rows for field in _EVENT_CLOCK_FIELDS):
        return []
    return format_generic_snapshot(panel_id, {**projection, **collections}, topic=topic)
