"""Direct-access Fed calendars, bound to BLS reference periods from the archive."""
from __future__ import annotations

from data_sources import source_value

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .bls_release_archive import MONTH, TITLES, read_latest

NYFED_URL = source_value('POLYMONITOR_URL_WWW_NEWYORKFED_ORG_RESEARCH_CALENDARS_NATIONALECON_CAL_6C6183')
FRED_URL = source_value('POLYMONITOR_URL_FRED_STLOUISFED_ORG_RELEASES_CALENDAR_1285C6')
RELEASE_IDS = {"cpi": 10, "nfp": 50, "ppi": 46}
SOURCE_KEYS = {"cpi": "fredCpi", "nfp": "fredEmployment", "ppi": "fredPpi"}
UTC = timezone.utc
EASTERN = ZoneInfo("America/New_York")


def event(kind, local, provider, url):
    stamp = local.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {"id": f"{kind}-{stamp[:10]}", "kind": kind, "title": TITLES[kind],
            "releaseAt": stamp, "releaseTimeEt": local.astimezone(EASTERN).strftime("%I:%M %p"),
            "referencePeriod": None, "source": provider, "sourceUrl": url,
            "referencePeriodStatus": "unknown", "scheduleStatus": "verified",
            "marketRelevance": "Scheduled U.S. statistical release"}


def parse_fred(html, kind, year):
    url = FRED_URL.format(rid=RELEASE_IDS[kind], year=year)
    rows = []
    date = None
    for row in BeautifulSoup(html, "html.parser").select("table.table-standard-theme tr"):
        match = re.search(MONTH + r"\s+\d{1,2},\s+20\d{2}", row.get_text(" ", strip=True), re.I)
        if match:
            date = match[0]
        if not row.select_one(f'a[href="/release?rid={RELEASE_IDS[kind]}"]'):
            continue
        clock = re.search(r"\d{1,2}:\d{2}\s*[ap]m", row.get_text(" ", strip=True), re.I)
        if date and clock:
            local = datetime.strptime(date + " " + clock[0].upper(), "%B %d, %Y %I:%M %p")
            if local.year != year:
                raise ValueError("fred-calendar-wrong-year")
            rows.append(event(kind, local.replace(tzinfo=ZoneInfo("America/Chicago")), "FRED release calendar", url))
    if not rows:
        raise ValueError("fred-calendar-no-valid-releases")
    return rows


def parse_nyfed(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    links = {"cpi.toc.htm": "cpi", "empsit.toc.htm": "nfp", "ppi.toc.htm": "ppi", "ppi/": "ppi"}
    for table in soup.select("table.research-table-1col"):
        heading = table.find_previous(string=lambda value: value and re.fullmatch(MONTH + r"\s+20\d{2}", value.strip(), re.I))
        if not heading:
            continue
        month = datetime.strptime(heading.strip(), "%B %Y")
        for anchor in table.select("a[href]"):
            kind = next((kind for suffix, kind in links.items() if anchor["href"].lower().endswith("/" + suffix)), None)
            if kind is None:
                continue
            cell = anchor.find_parent("td")
            day = re.match(r"\s*(\d{1,2})\b", cell.get_text(" ", strip=True))
            siblings = []
            for sibling in anchor.next_siblings:
                if getattr(sibling, "name", None) == "a":
                    break
                siblings.append(sibling.get_text(" ") if hasattr(sibling, "get_text") else str(sibling))
            clock = re.search(r"\((\d{2}):(\d{2})\)", " ".join(siblings))
            if day and clock:
                local = month.replace(day=int(day[1]), hour=int(clock[1]), minute=int(clock[2]), tzinfo=EASTERN)
                rows.append(event(kind, local, "Federal Reserve Bank of New York", NYFED_URL))
    if not rows:
        raise ValueError("nyfed-calendar-no-valid-releases")
    return rows


def bind_period(row, record):
    evidence = None
    if row["releaseAt"] == record.get("published_at"):
        evidence = record
    elif row["releaseAt"] == record.get("next_release", {}).get("releaseAt"):
        evidence = record["next_release"]
    if evidence:
        row.update(referencePeriod=evidence["referencePeriod"], referencePeriodStatus="original-release",
                   referencePeriodSourceUrl=record["pdfUrl"])
    return row


def source_error(exc):
    status = getattr(getattr(exc, "response", None), "status_code", None)
    # Transport exception strings can contain private proxy credentials.
    return f"HTTP {status}" if status else type(exc).__name__


def build(http_get, snapshot_store, now, previous=None, checked_at=None):
    def verified_rows(rows):
        stamp = checked_at() if checked_at else now.isoformat().replace("+00:00", "Z")
        return [{**row, "verifiedAt": stamp} for row in rows]

    states, errors, candidates = {}, {}, {}
    ny_rows = []
    try:
        ny_rows = verified_rows(parse_nyfed(http_get(NYFED_URL, timeout=45)))
        states["nyFed"] = "ok"
    except Exception as exc:
        states["nyFed"] = "error"
        errors["nyFed"] = source_error(exc)
    years = [now.year] + ([now.year + 1] if now.month == 12 else [])
    conflicts = []
    for kind, rid in RELEASE_IDS.items():
        key = SOURCE_KEYS[kind]
        fred_rows = []
        for year in years:
            try:
                fred_rows += verified_rows(parse_fred(http_get(FRED_URL.format(rid=rid, year=year), timeout=45), kind, year))
            except Exception as exc:
                errors[key] = source_error(exc)
        states[key] = "error" if key in errors else "ok"
        ny_kind = [row for row in ny_rows if row["kind"] == kind]
        rows = {row["releaseAt"]: row for row in fred_rows}
        for row in ny_kind:
            same_month = [other for other in fred_rows if other["releaseAt"][:7] == row["releaseAt"][:7]]
            if same_month and any(other["releaseAt"] != row["releaseAt"] for other in same_month):
                conflicts.append({"kind": kind, "candidates": same_month + [row]})
                for other in same_month:
                    rows.pop(other["releaseAt"], None)
                states[key] = "conflict"
            elif row["releaseAt"] in rows:
                rows[row["releaseAt"]]["corroboratedBy"] = NYFED_URL
            else:
                rows[row["releaseAt"]] = row
        record = read_latest(snapshot_store, kind)
        for row in rows.values():
            candidates[row["id"]] = bind_period(row, record)
        states[kind + "Schedule"] = "conflict" if any(c["kind"] == kind for c in conflicts) else ("ok" if rows else "error")
        if states[key] == "error":
            # A fresh monthly fallback must not erase the rest of a previously
            # verified annual calendar. Fresh months replace their old dates.
            fresh_months = {row["releaseAt"][:7] for row in rows.values()}
            for old in (previous or {}).get("items", []):
                verified = old.get("verifiedAt")
                if (old.get("kind") != kind or not verified or not old.get("releaseAt")
                        or old.get("id") in candidates or old["releaseAt"][:7] in fresh_months):
                    continue
                try:
                    age = now - datetime.fromisoformat(verified.replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    continue
                if timedelta(0) <= age <= timedelta(days=7):
                    candidates[old["id"]] = {**old, "scheduleStatus": "retained", "retained": True}
    return list(candidates.values()), states, errors, conflicts
