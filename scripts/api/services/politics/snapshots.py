"""Read-only projections. Never contact a provider or advance a success clock."""
from __future__ import annotations

from data_sources import source_value

import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .catalog import catalog
from .store import SOURCE_NS, source

PANELS = ("politics-election", "politics-early-vote", "politics-nomination", "politics-seats",
          "politics-campaign-finance", "politics-government", "politics-executive",
          "politics-appointments", "politics-funding", "politics-legislation")


def get_snapshot(store, panel_id, *, limit=200):
    if panel_id not in PANELS:
        raise ValueError("Unknown politics panel")
    limit = max(1, min(200, limit))
    specs = {s.key: s for s in catalog()}
    sources = []

    def read(key):
        spec = specs[key]
        data, meta = source(store, key, spec.url)
        if data.get("partial"):
            meta = {**meta, "partial": True}
        sources.append(meta)
        return data

    payload = {}
    if panel_id == "politics-election":
        polls = read("decision-labs")
        results = read("nc-results-20261103")
        certification = read("nc-certification-20261103")
        certifications = []
        for row in certification.get("items", []):
            # A scheduled meeting is not evidence it happened or certified a contest.
            scheduled = datetime.fromisoformat(row["scheduledDate"] + "T" + row["scheduledTime"]).replace(tzinfo=ZoneInfo(row["timeZone"]))
            pending = scheduled >= datetime.now(timezone.utc)
            certifications.append({**row, "status": "pending" if pending else "outcome-unverified"})
        payload = {"polls": polls.get("items", [])[:limit], "pollCount": polls.get("availableCount", 0),
                   "attribution": polls.get("attribution"), "results": results.get("items", []),
                   "basis": results.get("basis"), "defaultPhase": "counting" if results.get("items") else "polls",
                   "certifications": certifications, "certificationCoverage": certification.get("coverage"),
                   "mappingStatus": "unverified"}
    elif panel_id == "politics-early-vote":
        payload = read("nc-early-20261103")
    elif panel_id == "politics-nomination":
        primary = read("nc-primary-20260303")
        delegates = read("dnc-roll-call-2024")
        payload = {**primary, "delegates": None, "threshold": None,
                   "delegateApplicability": "not-applicable-congressional-primary",
                   "delegateContests": delegates.get("items", []),
                   "scope": "US-NC · 2026-03-03 · federal primaries"}
    elif panel_id in ("politics-seats", "politics-government"):
        payload = read("house-roster")
    elif panel_id == "politics-campaign-finance":
        key = next(k for k in specs if k.startswith("fec-") and k[4:].isdigit())
        data = read(key)
        independent = read("fec-independent-" + key[4:])
        payload = {**data, "items": data.get("items", [])[:limit], "cycle": key[4:],
                   "independentExpenditures": independent.get("items", [])[:min(limit, 100)],
                   "independentExpenditureCount": independent.get("availableCount", 0),
                   "independentCoverage": independent.get("coverage"),
                   "independentRawCount": independent.get("rawCount"),
                   "independentMissingDirectionCount": independent.get("missingDirectionCount", 0),
                   "independentRawMissingDirectionCount": independent.get("rawMissingDirectionCount", 0),
                   "supersededTransactionCount": independent.get("supersededTransactionCount"),
                   "filingRevisions": independent.get("filingRevisions", [])[:min(limit, 100)],
                   "filingRevisionCount": independent.get("filingRevisionCount", 0),
                   "coverage": "top-receipts-candidates", "filingRevisionsAvailable": bool(independent)}
    elif panel_id == "politics-executive":
        from api.services.official_disclosures_service import SOURCES, source_meta
        state = store.get_stale(SOURCES, "federal-register:presidential") or {}
        meta = source_meta(state, time.time())
        sources.append({**meta, "id": "federal-register:presidential", "url": source_value('POLYMONITOR_URL_WWW_FEDERALREGISTER_GOV_PRESIDENTIAL_DOCUMENTS_F56EA4')})
        payload = {**state.get("data", {}), "items": state.get("data", {}).get("items", [])[:limit] if meta["usable"] else []}
    elif panel_id == "politics-appointments":
        announcements = read("presidential-nominations")
        confirmations = read("judicial-confirmations")
        feed = read("nomination-hearings")
        hearings = []
        for row in feed.get("items", [])[:100]:
            data, meta = source(store, "hearing:" + row["id"], row["metadataUrl"])
            sources.append(meta)
            if data:
                hearings.append({**data, "source": meta, "feedPublishedAt": row.get("publishedAt")})
        payload = {**announcements, "confirmations": confirmations.get("items", [])[:limit],
                   "confirmationCount": confirmations.get("availableCount", 0),
                   "confirmationCoverage": confirmations.get("coverage"),
                   "confirmationPublishedAt": confirmations.get("publishedAt"),
                   "hearings": hearings, "hearingTargetCount": feed.get("availableCount", 0),
                   "hearingCoverage": feed.get("coverage"), "scheduledHearingsCoverage": "unavailable",
                   "rollCallCoverage": "unavailable"}
    else:
        key = next(k for k in specs if k.startswith("bills-"))
        feed = read(key)
        index = store.get_stale(SOURCE_NS, "bill-index") or {}
        details, detail_sources = [], []
        acquired = 0
        titles = {item["id"]: item.get("title", "") for item in feed.get("items", [])}
        target_ids = set(index.get("targetIds") or [*titles, "119hr6500"])
        identities = list(dict.fromkeys([*index.get("ids", []), *index.get("targetIds", [])]))[-200:]
        for identity in identities:
            data, meta = source(store, "bill:" + identity, source_value('POLYMONITOR_URL_WWW_GOVINFO_GOV_BULKDATA_BILLSTATUS_643E59'))
            acquired += int(bool(data) and identity in target_ids)
            title = data.get("title") or titles.get(identity, "")
            if panel_id == "politics-funding" and identity != "119hr6500" and not any(
                    word in title.lower() for word in ("appropriat", "continuing resolution", "funding")):
                continue
            if identity in target_ids:
                detail_sources.append(meta)
            if data:
                details.append({**data, "source": meta})
        details.sort(key=lambda r: r.get("updatedAt") or "", reverse=True)
        sources.extend(detail_sources)
        payload = {"items": details[:min(40, limit)], "feed": feed.get("items", [])[:limit],
                   "targetCount": index.get("targetCount", 0), "acquiredCount": acquired,
                   "failedCount": sum(bool(meta.get("error")) for meta in detail_sources),
                   "pendingCount": sum(not meta.get("lastSuccessAt") for meta in detail_sources),
                   "deadline": None, "fundingCoverage": [], "coverage": "recent-publications-and-watchlist"}
        if panel_id == "politics-funding":
            payload["law"] = read("funding-law-119-103")
    attempts = [s["lastAttemptAt"] for s in sources if s.get("lastAttemptAt")]
    successes = [s["lastSuccessAt"] for s in sources if s.get("lastSuccessAt")]
    status = "ok"
    if not any(s.get("usable") for s in sources):
        status = "unavailable"
    elif any(s.get("error") or s.get("stale") or s.get("partial") or not s.get("usable") for s in sources):
        status = "degraded"
    result = {**payload, "panelId": panel_id, "schemaVersion": 1,
              "generatedAt": max(successes) if successes else None,
              "lastAttemptAt": max(attempts) if attempts else None, "status": status, "sources": sources,
              "credentials": {"ap": bool(os.getenv("POLYMONITOR_AP_ELECTIONS_API_KEY")),
                              "congress": bool(os.getenv("POLYMONITOR_CONGRESS_API_KEY")),
                              "fec": bool(os.getenv("POLYMONITOR_FEC_API_KEY"))}}
    if len(json.dumps(result, ensure_ascii=False).encode()) > 512 * 1024:
        raise ValueError("Politics read exceeds payload budget")
    return result
