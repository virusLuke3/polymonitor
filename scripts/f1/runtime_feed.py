#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Runtime BWENews feed builder used by the API and optional CLI helpers."""

from __future__ import annotations

import os
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from data_sources import env_str
from api.clients.source_transport import read_response_bytes, read_with_retry, source_session


DEFAULT_PANEL_PATH = (Path(__file__).resolve().parents[2] / "data" / "runtime" / "f1" / "panel.json").resolve()


def default_news_feeds() -> List[Dict[str, str]]:
    if not env_str("POLYDATA_F1_BWENEWS_RSS_URL"):
        return []
    return [
        {
            "source": "BWENews",
            "url": env_str("POLYDATA_F1_BWENEWS_RSS_URL"),
            "source_url": env_str("POLYDATA_F1_BWENEWS_SOURCE_URL"),
        },
    ]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    import json

    target = ensure_parent(path)
    tmp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(target)


def _requests_get(requests_lib, url: str, *, params: Optional[Dict[str, Any]] = None, timeout: int = 45, headers: Optional[Dict[str, str]] = None):
    if hasattr(requests_lib, "Session"):
        session = source_session(requests_lib)
        session.trust_env = False
        proxy_url = os.environ.get("POLYDATA_API_HTTP_PROXY_URL", "").strip()
        if proxy_url:
            session.proxies.update({"http": proxy_url, "https": proxy_url})
        try:
            return _requests_get(session, url, params=params, timeout=timeout, headers=headers)
        finally:
            session.close()
    if hasattr(requests_lib, "request"):
        deadline = time.monotonic() + 90
        return read_with_retry(
            requests_lib, url,
            lambda response: read_response_bytes(response, 2_500_000, deadline=deadline),
            attempts=2, deadline=deadline, timeout=timeout, stream=True,
            params=params, headers=headers or {},
        )
    # Injected readers use the same parser without opening a second client.
    response = requests_lib.get(url, params=params, timeout=timeout, headers=headers or {})
    response.raise_for_status()
    return response.text


def format_relative_short(anchor: Optional[datetime], now: datetime) -> str:
    if anchor is None:
        return "--"
    delta_seconds = int((anchor - now).total_seconds())
    if abs(delta_seconds) < 60:
        return "live now" if delta_seconds <= 0 else "in <1m"
    if delta_seconds > 0:
        days, remainder = divmod(delta_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes = remainder // 60
        if days > 0:
            return f"in {days}d"
        if hours > 0:
            return f"in {hours}h"
        return f"in {minutes}m"
    delta_seconds = abs(delta_seconds)
    days, remainder = divmod(delta_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    if days > 0:
        return f"{days}d ago"
    if hours > 0:
        return f"{hours}h ago"
    return f"{minutes}m ago"


def format_compact_datetime(value: Any) -> str:
    parsed = parse_iso(value)
    if parsed is None:
        return "--"
    return parsed.strftime("%a %H:%M UTC").upper()


def status_accent(status: str) -> str:
    return {
        "live": "#22c55e",
        "news": "#22c55e",
        "flash": "#22c55e",
    }.get(status, "#22c55e")


def _find_text(item: ET.Element, tag: str) -> str:
    node = item.find(tag)
    if node is None or node.text is None:
        return ""
    return node.text


def _compact_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())


def _strip_markup(value: str) -> str:
    cleaned = unescape(str(value or ""))
    for token in ("<br/>", "<br />", "<br>"):
        cleaned = cleaned.replace(token, "\n")
    return cleaned


def _normalize_bwenews_text(value: str) -> str:
    lines = []
    for raw_line in _strip_markup(value).splitlines():
        line = _compact_whitespace(raw_line)
        if not line:
            continue
        if line == "————————————":
            continue
        lines.append(line)
    return "\n".join(lines)


def _looks_like_timestamp_line(value: str) -> bool:
    parsed = parse_iso(str(value).replace(" ", "T"))
    return parsed is not None


def _split_bwenews_title_parts(title: str, description: str) -> tuple[str, Optional[str], Optional[str]]:
    normalized_title = _normalize_bwenews_text(title)
    normalized_description = _normalize_bwenews_text(description)
    lines = [line for line in normalized_title.splitlines() if line]

    headline = lines[0] if lines else _compact_whitespace(normalized_title)
    remainder: List[str] = []
    source_url = None

    for line in lines[1:]:
        lower = line.lower()
        if lower.startswith("source:"):
            source_url = line.split(":", 1)[1].strip() or None
            continue
        if _looks_like_timestamp_line(line):
            continue
        remainder.append(line)

    if normalized_description:
        remainder.append(normalized_description)

    summary = "\n".join(remainder).strip() or None
    return headline[:280], summary[:480] if summary else None, source_url


def fetch_f1_news_items(requests_lib, *, now: datetime, feed_specs: Optional[Iterable[Dict[str, str]]] = None, limit: int = 4,
                        source_states: Optional[Dict[str, str]] = None,
                        source_errors: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    states = source_states if source_states is not None else {}
    errors = source_errors if source_errors is not None else {}
    if requests_lib is None:
        states["bwenewsRss"] = "unavailable"
        errors["bwenewsRss"] = "HTTP client unavailable"
        return []
    items: List[Dict[str, Any]] = []
    feeds = list(feed_specs) if feed_specs is not None else default_news_feeds()
    if not feeds:
        states["bwenewsRss"] = "missing-config"
    for index, feed in enumerate(feeds):
        source_id = "bwenewsRss" if index == 0 else f"feed-{index + 1}"
        if not str(feed.get("url") or "").strip():
            states[source_id] = "missing-config"
            continue
        try:
            body = _requests_get(
                requests_lib,
                str(feed.get("url") or ""),
                timeout=45,
                headers={
                    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
                    "User-Agent": "polydata-f1-runtime/1.0",
                },
            )
            root = ET.fromstring(body)
            if root.tag.lower() != "rss" or root.find("channel") is None:
                raise ValueError("Expected RSS channel")
        except Exception as exc:
            states[source_id] = "error"
            code = getattr(getattr(exc, "response", None), "status_code", None)
            errors[source_id] = f"HTTP {code}" if code else type(exc).__name__
            continue
        raw_items = root.findall(".//item")[: max(limit, 8)]
        before = len(items)
        for item in raw_items:
            title_raw = _find_text(item, "title").strip()
            description_raw = _find_text(item, "description").strip()
            title, summary, embedded_source_url = _split_bwenews_title_parts(title_raw, description_raw)
            url = (_find_text(item, "link").strip() or embedded_source_url or str(feed.get("source_url") or "").strip())
            published_raw = _find_text(item, "pubDate").strip()
            published_at = None
            if published_raw:
                try:
                    published_at = parsedate_to_datetime(published_raw).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
                except Exception:
                    published_at = None
            if not title or not url:
                continue
            published_dt = parse_iso(published_at)
            items.append(
                {
                    "id": f"news-{uuid.uuid5(uuid.NAMESPACE_URL, url)}",
                    "kind": "news",
                    "status": "live",
                    "topic": "bwenews",
                    "phase": "flash",
                    "detail": format_relative_short(published_dt, now) if published_dt else None,
                    "title": title,
                    "summary": summary[:480] if summary else None,
                    "primaryMetric": str(feed.get("source") or "BWENews"),
                    "secondaryMetric": format_compact_datetime(published_at) if published_at else None,
                    "tertiaryMetric": "rss cache",
                    "quaternaryMetric": None,
                    "accentColor": status_accent("news"),
                    "url": url,
                    "source": str(feed.get("source") or "BWENews"),
                    "publishedAt": published_at,
                }
            )
        valid = len(items) - before
        states[source_id] = "ok" if valid == len(raw_items) and valid else "empty" if not raw_items else "partial" if valid else "error"
        if raw_items and not valid:
            errors[source_id] = "RSS items missing required title or link"
    items.sort(key=lambda entry: str(entry.get("publishedAt") or ""), reverse=True)
    return items[:limit]


def build_f1_panel_payload(
    *,
    requests_lib,
    year: Optional[int] = None,
    now: Optional[datetime] = None,
    limit: int = 10,
    feed_specs: Optional[Iterable[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    current_time = now or utc_now()
    feeds = list(feed_specs) if feed_specs is not None else default_news_feeds()
    sources: Dict[str, str] = {}
    errors: Dict[str, str] = {}
    cards = fetch_f1_news_items(requests_lib, now=current_time, feed_specs=feeds, limit=max(1, int(limit or 10)),
                               source_states=sources, source_errors=errors)
    failed = any(state not in {"ok", "empty"} for state in sources.values())
    source_url = str((feeds[0] if feeds else {}).get("source_url") or "")

    return {
        "generatedAt": current_time.isoformat().replace("+00:00", "Z"),
        "season": int(year or current_time.year),
        "source": "bwenews-rss",
        "sourceUrl": source_url,
        "status": ("degraded" if cards else "error") if failed else "ok" if cards else "empty",
        "sources": sources,
        "sourceErrors": errors,
        "focusMeeting": None,
        "cards": cards[: max(1, int(limit or 10))],
    }


def sync_f1_panel(path: Path | str = DEFAULT_PANEL_PATH, *, requests_lib, year: Optional[int] = None, limit: int = 10) -> Dict[str, Any]:
    payload = build_f1_panel_payload(requests_lib=requests_lib, year=year, limit=limit)
    atomic_write_json(Path(path).expanduser().resolve(), payload)
    return payload
