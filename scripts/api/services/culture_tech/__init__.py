"""Twelve independent views over shared public evidence, acquired off the API path."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from api.services.panel_evidence_store import (SourceSpec, collect_one, collect_sources,
    fetch_bytes, payload, public_url, read_source)
from data_sources import source_value
from . import parsers


SPECS = {
    "arena": SourceSpec("culture-tech:arena", "Arena published leaderboard · CC BY 4.0", "POLYMONITOR_ARENA_ROWS_URL", parsers.arena, cadence=21600, stale_after=86400),
    "music": SourceSpec("culture-tech:apple-music", "Apple Music US most played", "POLYMONITOR_APPLE_MUSIC_CHART_URL", parsers.music, cadence=21600, stale_after=86400),
    "space": SourceSpec("culture-tech:launch-library", "The Space Devs · Launch Library 2", "POLYMONITOR_SPACE_LAUNCHES_URL", parsers.launches, cadence=3600, stale_after=10800),
    "research": SourceSpec("culture-tech:crossref", "Crossref DOI metadata", "POLYMONITOR_RESEARCH_WORKS_URL", parsers.research, cadence=21600, stale_after=86400),
    "steam": SourceSpec("culture-tech:steam", "Steam release listings", "POLYMONITOR_STEAM_FEATURED_URL", parsers.steam, cadence=3600, stale_after=10800),
    "auction": SourceSpec("culture-tech:christies", "Christie's official calendar", "POLYMONITOR_AUCTION_CALENDAR_URL", parsers.auctions, cadence=21600, stale_after=86400),
    "reality": SourceSpec("culture-tech:tvmaze", "TVmaze schedule · CC BY-SA", "POLYMONITOR_REALITY_SCHEDULE_URL", parsers.reality, cadence=21600, stale_after=86400),
    "speeches": SourceSpec("culture-tech:fed-speeches", "Federal Reserve published speeches", "POLYMONITOR_MENTIONS_SPEECHES_URL", parsers.speeches, cadence=3600, stale_after=10800),
    "social": SourceSpec("culture-tech:bluesky", "Bluesky public profile activity", "POLYMONITOR_SOCIAL_PROFILE_FEED_URL", parsers.social, cadence=3600, stale_after=10800, retain_for=86400),
    "box-office": SourceSpec("culture-tech:bfi", "British Film Institute weekly box office", "POLYMONITOR_BOX_OFFICE_INDEX_URL", parsers.box_office, cadence=21600, stale_after=86400, retain_for=14*86400),
    "awards": SourceSpec("culture-tech:golden-globes", "Golden Globes official announcements", "POLYMONITOR_CULTURE_AWARDS_FEED_URL", parsers.speeches, cadence=21600, stale_after=86400),
}
PANELS = {
    "ai-leaderboard-watch": "arena", "art-auction-watch": "auction", "culture-box-office": "box-office",
    "culture-awards-race": "awards", "culture-music-charts": "music", "product-release-watch": "steam",
    "public-figure-events": "speeches", "reality-show-progress": "reality", "research-evidence-watch": "research",
    "social-window-monitor": "social", "space-mission-watch": "space", "mentions-evidence": "speeches",
}


def acquire_box_office(deadline):
    raw = fetch_bytes(source_value("POLYMONITOR_BOX_OFFICE_INDEX_URL"), deadline=deadline, max_bytes=2*1024**2)
    soup = BeautifulSoup(raw, "html.parser")
    origin = urlsplit(source_value("POLYMONITOR_BOX_OFFICE_DOWNLOAD_ORIGIN"))
    links = [(a.get("href"), a.get_text(" ", strip=True)) for a in soup.find_all("a", href=True)
        if "Weekend box office report:" in a.get_text() and "OpenDocument" in a.get_text()]
    if not links or not origin.hostname:
        raise ValueError("BFI latest document or configured download origin missing")
    url, title = links[0]
    if not public_url(url) or urlsplit(url).hostname != origin.hostname:
        raise ValueError("Unreviewed box office download host")
    body = fetch_bytes(url, deadline=deadline, max_bytes=2*1024**2)
    data = parsers.box_office(body)
    data.update(documentUrl=url, documentTitle=title)
    return body, data


def speech_spec(row):
    return SourceSpec("culture-tech:speech:" + hashlib.sha256(row["url"].encode()).hexdigest()[:20],
        "Federal Reserve official written remarks", "POLYMONITOR_MENTIONS_SPEECHES_URL",
        lambda raw: {"paragraphs": parsers.transcript(raw)}, cadence=86400, stale_after=172800, retain_for=7*86400)


def acquire_research(deadline):
    url = urlsplit(source_value("POLYMONITOR_RESEARCH_WORKS_URL"))
    params = dict(parse_qsl(url.query))
    filters = [f for f in params.get("filter", "").split(",") if f and not f.startswith("until-pub-date:")]
    filters.append("until-pub-date:" + datetime.now(timezone.utc).date().isoformat())
    params.update(filter=",".join(filters), rows="50")
    raw = fetch_bytes(urlunsplit(url._replace(query=urlencode(params))), deadline=deadline)
    return raw, parsers.research(raw)


def collect(store, *, force=False):
    results = collect_sources(store, [s for k, s in SPECS.items() if k not in {"box-office", "research"}], force=force, budget=330)
    end = time.monotonic() + 90
    result = collect_one(store, SPECS["research"], acquire=lambda: acquire_research(end), force=force, deadline=end)
    results["research"] = result.get("error") or "stored-or-not-due"
    end = time.monotonic() + 120
    result = collect_one(store, SPECS["box-office"], acquire=lambda: acquire_box_office(end), force=force, deadline=end)
    results["box-office"] = result.get("error") or "stored-or-not-due"
    speeches, _ = read_source(store, SPECS["speeches"])
    end = time.monotonic() + 120
    for row in speeches.get("items", [])[:3]:
        if time.monotonic() + 45 > end:
            break
        url = row.get("url")
        if not url or urlsplit(url).hostname != urlsplit(source_value("POLYMONITOR_MENTIONS_SPEECHES_URL")).hostname:
            continue
        spec = speech_spec(row)
        def acquire(url=url, spec=spec):
            raw = fetch_bytes(url, deadline=end, max_bytes=2*1024**2)
            return raw, spec.parse(raw)
        result = collect_one(store, spec, acquire=acquire, force=force, deadline=end)
        results[spec.key] = result.get("error") or "stored-or-not-due"
    return results


def get_snapshot(store, panel_id, *, limit=100):
    if panel_id not in PANELS:
        raise KeyError(panel_id)
    data, source = read_source(store, SPECS[PANELS[panel_id]])
    sources = [source]
    fields = {**data, "items": data.get("items", [])[:max(1, min(100, limit))]}
    if panel_id == "mentions-evidence":
        rows = []
        for item in data.get("items", [])[:3]:
            if not item.get("url"):
                continue
            document, meta = read_source(store, speech_spec(item))
            sources.append(meta)
            rows.append({**item, "paragraphs": document.get("paragraphs", []), "documentAvailable": bool(document),
                "transcriptScope": "Official published written remarks; spoken delivery and audio timestamps unverified"})
        fields.update(items=rows, coverage="Federal Reserve official written remarks · up to three recent documents. Exact whole-word matches in acquired paragraphs; not an audio transcript or settlement count.")
    elif panel_id == "public-figure-events":
        fields["coverage"] = "Federal Reserve officials · publication of official remarks. Other public figures, private events and celebrity claims are not covered."
    elif panel_id == "culture-awards-race":
        fields["coverage"] = "Golden Globes official announcements. Publication status only; nominations, winners and rules require the linked award document, not headline inference."
        fields["items"] = [{**r, "speaker": None, "kind": "Official award announcement"} for r in fields["items"]]
    return payload(panel_id, sources, **fields)
