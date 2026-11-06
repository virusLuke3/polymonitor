"""Read-only projections. Never contact a provider or advance a success clock."""
from __future__ import annotations

from data_sources import source_value

import json
import os
import time
from datetime import datetime
from .catalog import catalog
from .store import SOURCE_NS, iso, source

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
        sources.append(meta)
        return data

    payload = {}
    if panel_id == "politics-election":
        polls = read("decision-labs")
        results = read("nc-results-20261103")
        payload = {"polls": polls.get("items", [])[:limit], "pollCount": polls.get("availableCount", 0),
                   "attribution": polls.get("attribution"), "results": results.get("items", []),
                   "basis": results.get("basis"), "defaultPhase": "counting" if results.get("items") else "polls",
                   "certifications": [], "mappingStatus": "unverified"}
    elif panel_id == "politics-early-vote":
        payload = read("nc-early-20261103")
    elif panel_id == "politics-nomination":
        payload = {**read("nc-primary-20260303"), "delegates": None, "threshold": None,
                   "scope": "US-NC · 2026-03-03 · federal primaries"}
    elif panel_id in ("politics-seats", "politics-government"):
        payload = read("house-roster")
    elif panel_id == "politics-campaign-finance":
        key = next(k for k in specs if k.startswith("fec-"))
        data = read(key)
        payload = {**data, "items": data.get("items", [])[:limit], "cycle": key[4:], "independentExpenditures": [],
                   "coverage": "top-receipts-candidates", "filingRevisionsAvailable": False}
    elif panel_id == "politics-executive":
        from api.services.official_disclosures_service import SOURCES, source_meta
        state = store.get_stale(SOURCES, "federal-register:presidential") or {}
        meta = source_meta(state, time.time())
        sources.append({**meta, "id": "federal-register:presidential", "url": source_value('POLYMONITOR_URL_WWW_FEDERALREGISTER_GOV_PRESIDENTIAL_DOCUMENTS_F56EA4')})
        payload = {**state.get("data", {}), "items": state.get("data", {}).get("items", [])[:limit]}
    elif panel_id == "politics-appointments":
        payload = {**read("presidential-nominations"), "confirmations": [], "hearings": []}
    else:
        key = next(k for k in specs if k.startswith("bills-"))
        feed = read(key)
        index = store.get_stale(SOURCE_NS, "bill-index") or {}
        details = []
        for identity in index.get("ids", [])[-100:]:
            data, meta = source(store, "bill:" + identity, source_value('POLYMONITOR_URL_WWW_GOVINFO_GOV_BULKDATA_BILLSTATUS_643E59'))
            if data:
                details.append({**data, "source": meta})
        details.sort(key=lambda r: r.get("updatedAt") or "", reverse=True)
        if panel_id == "politics-funding":
            details = [r for r in details if any(w in (r.get("title") or "").lower() for w in ("appropriat", "continuing resolution", "funding"))]
        payload = {"items": details[:min(40, limit)], "feed": feed.get("items", [])[:limit],
                   "targetCount": index.get("targetCount", 0), "acquiredCount": len(index.get("ids", [])),
                   "deadline": None, "fundingCoverage": [], "coverage": "recent-publications-and-watchlist"}
        if panel_id == "politics-funding":
            payload["law"] = read("funding-law-119-103")
    attempts = [s["lastAttemptAt"] for s in sources if s.get("lastAttemptAt")]
    result = {**payload, "panelId": panel_id, "schemaVersion": 1,
              "generatedAt": max(attempts) if attempts else iso(0), "sources": sources,
              "credentials": {"ap": bool(os.getenv("POLYMONITOR_AP_ELECTIONS_API_KEY")),
                              "congress": bool(os.getenv("POLYMONITOR_CONGRESS_API_KEY")),
                              "fec": bool(os.getenv("POLYMONITOR_FEC_API_KEY"))}}
    if len(json.dumps(result, ensure_ascii=False).encode()) > 512 * 1024:
        raise ValueError("Politics read exceeds payload budget")
    return result
