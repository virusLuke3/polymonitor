"""Official filings and regulatory documents: one scheduled owner, read-only views."""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

NAMESPACE = "snapshot:official-disclosures"
SOURCES = "source:official-disclosures"
WATCHLIST = {
    "AAPL": "0000320193", "MSFT": "0000789019", "NVDA": "0001045810",
    "AMZN": "0001018724", "GOOGL": "0001652044", "META": "0001326801",
    "TSLA": "0001318605", "AVGO": "0001730168",
}
FORMS = {"10-K", "10-Q", "8-K", "10-K/A", "10-Q/A", "8-K/A"}


def iso(timestamp):
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def filings(raw, cik, symbol):
    if str(raw.get("cik", "")).zfill(10) != cik:
        raise ValueError("SEC CIK mismatch")
    recent = raw.get("filings", {}).get("recent")
    if not isinstance(recent, dict) or not isinstance(recent.get("accessionNumber"), list):
        raise ValueError("SEC filings schema invalid")
    result = []
    for i, accession in enumerate(recent["accessionNumber"]):
        def field(name):
            values = recent.get(name, [])
            return values[i] if i < len(values) else None
        if field("form") not in FORMS:
            continue
        doc = field("primaryDocument")
        if not doc or not field("filingDate") or not isinstance(accession, str):
            continue
        result.append({"id": accession, "symbol": symbol, "cik": cik,
                       "company": raw.get("name", symbol), "form": field("form"),
                       "publishedAt": field("acceptanceDateTime") or field("filingDate"),
                       "filed": field("filingDate"), "period": field("reportDate"),
                       "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{quote(doc, safe='')}",
                       "amendment": field("form").endswith("/A")})
    return sorted(result, key=lambda row: row["publishedAt"], reverse=True)[:24]


def facts(raw, cik):
    if str(raw.get("cik", "")).zfill(10) != cik or not isinstance(raw.get("facts"), dict):
        raise ValueError("SEC facts identity/schema invalid")
    taxonomy = raw["facts"].get("us-gaap", {})
    output = {}
    for name, unit, concepts in [
        ("eps", "USD/shares", ["EarningsPerShareDiluted"]),
        ("revenue", "USD", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"]),
    ]:
        candidates = []
        for priority, concept in enumerate(concepts):
            for value in taxonomy.get(concept, {}).get("units", {}).get(unit, []):
                if value.get("form") not in {"10-Q", "10-K", "10-Q/A", "10-K/A"}:
                    continue
                if not all(value.get(k) for k in ("start", "end", "filed", "accn")):
                    continue
                if not isinstance(value.get("val"), (int, float)) or not math.isfinite(value["val"]):
                    continue
                # Preserve actual duration: never call YTD or annual facts a quarter.
                candidates.append({"value": value["val"], "unit": unit, "start": value["start"],
                                   "end": value["end"], "filed": value["filed"], "accession": value["accn"],
                                   "form": value["form"], "concept": concept, "priority": priority})
        if candidates:
            latest_end = max(v["end"] for v in candidates)
            same_end = [v for v in candidates if v["end"] == latest_end]
            # Prefer the shortest explicitly reported duration, then the latest revision.
            selected = max(same_end, key=lambda v: (v["start"], v["filed"], -v["priority"]))
            output[name] = {k: v for k, v in selected.items() if k != "priority"}
    return output


def policies(raw):
    if not isinstance(raw.get("results"), list) or not isinstance(raw.get("count"), int):
        raise ValueError("Federal Register schema invalid")
    rows = []
    for row in raw["results"]:
        if not all(row.get(k) for k in ("document_number", "title", "publication_date", "html_url")):
            raise ValueError("Federal Register document identity missing")
        rows.append({"id": row["document_number"], "title": row["title"], "type": row.get("type", "Document"),
                     "publishedAt": row["publication_date"], "effectiveOn": row.get("effective_on"),
                     "commentsCloseOn": row.get("comments_close_on"), "url": row["html_url"],
                     "pdfUrl": row.get("pdf_url"), "agencies": [a["name"] for a in row.get("agencies", []) if a.get("name")]})
    return {"items": rows, "availableCount": raw["count"]}


def archive(store, key, raw, now):
    path = Path(store.db_path).with_name("official_disclosures.sqlite3")
    packed = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    digest = hashlib.sha256(packed).hexdigest()
    with sqlite3.connect(path, timeout=2) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS responses (source TEXT, sha256 TEXT, first_seen REAL, last_seen REAL, payload BLOB, PRIMARY KEY(source,sha256))")
        db.execute("INSERT INTO responses VALUES (?,?,?,?,?) ON CONFLICT(source,sha256) DO UPDATE SET last_seen=excluded.last_seen",
                   (key, digest, now, now, zlib.compress(packed)))
        db.execute("DELETE FROM responses WHERE last_seen < ?", (now - 90 * 86400,))
    return digest


def collect_source(store, key, url, parse, fetch, cadence, *, now=None):
    now = time.time() if now is None else now
    previous = store.get_stale(SOURCES, key) or {}
    if previous.get("nextAttemptAt", 0) > now:
        return previous
    state = {**previous, "lastAttemptAt": now}
    try:
        raw = fetch(url)
        value = parse(raw)
        digest = archive(store, key, raw, now)
        state.update(data=value, lastSuccessAt=now, nextAttemptAt=now + cadence,
                     error=None, failures=0, sha256=digest)
    except Exception as exc:
        failures = previous.get("failures", 0) + 1
        retry_after = 0
        response = getattr(exc, "response", None)
        if response is not None:
            from api.clients.source_transport import _retry_seconds
            if response.status_code == 429:
                retry_after = _retry_seconds(response.headers.get("Retry-After"))
        state.update(error=f"{type(exc).__name__}: {str(exc)[:160]}", failures=failures,
                     nextAttemptAt=now + max(retry_after, min(1800, 300 * 2 ** min(failures - 1, 3))))
    store.set(SOURCES, key, state, 90 * 86400)
    return state


def source_meta(state, now):
    age = now - state.get("lastSuccessAt", 0)
    return {"lastSuccessAt": iso(state["lastSuccessAt"]) if state.get("lastSuccessAt") else None,
            "lastAttemptAt": iso(state["lastAttemptAt"]) if state.get("lastAttemptAt") else None,
            "error": state.get("error"), "stale": age > 86400,
            "usable": age <= 7 * 86400, "sha256": state.get("sha256")}


def publish(store, now=None):
    now = time.time() if now is None else now
    companies, source_states = [], {}
    for symbol, cik in WATCHLIST.items():
        sub = store.get_stale(SOURCES, f"sec:{cik}:submissions") or {}
        fact = store.get_stale(SOURCES, f"sec:{cik}:facts") or {}
        sub_meta, fact_meta = source_meta(sub, now), source_meta(fact, now)
        source_states[symbol] = {"filings": sub_meta, "facts": fact_meta}
        companies.append({"symbol": symbol, "cik": cik,
                          "filings": sub.get("data", []) if sub_meta["usable"] else [],
                          "facts": fact.get("data", {}) if fact_meta["usable"] else {},
                          "sources": source_states[symbol]})
    fr = store.get_stale(SOURCES, "federal-register") or {}
    fr_meta = source_meta(fr, now)
    definitions = {
        "company-events": {"companies": companies, "sources": source_states},
        "policy-progress": {"items": fr.get("data", {}).get("items", []) if fr_meta["usable"] else [],
                            "availableCount": fr.get("data", {}).get("availableCount", 0), "source": fr_meta},
    }
    for panel_id, payload in definitions.items():
        store.set(NAMESPACE, panel_id, {"panelId": panel_id, "schemaVersion": 1,
                                      "generatedAt": iso(now), **payload}, 90 * 86400)


def get_snapshot(store, panel_id, *, limit=100):
    """No acquisition or success-clock mutation in a public GET."""
    if panel_id not in {"company-events", "policy-progress"}:
        raise ValueError("Unknown disclosure panel")
    payload = store.get_stale(NAMESPACE, panel_id)
    if not payload:
        return {"panelId": panel_id, "schemaVersion": 1, "status": "unavailable",
                "generatedAt": None, "companies": [], "items": []}
    # Re-evaluate at read time as timers can stop while snapshots remain.
    def refresh_meta(meta):
        at = meta.get("lastSuccessAt")
        age = time.time() - datetime.fromisoformat(at).timestamp() if at else float("inf")
        return {**meta, "stale": age > 86400, "usable": age <= 7 * 86400}
    if panel_id == "company-events":
        for company in payload["companies"]:
            company["sources"] = {k: refresh_meta(v) for k, v in company["sources"].items()}
            for field, source in (("filings", "filings"), ("facts", "facts")):
                if not company["sources"][source]["usable"]:
                    company[field] = [] if field == "filings" else {}
    else:
        payload["source"] = refresh_meta(payload["source"])
        payload["items"] = payload["items"][:limit] if payload["source"]["usable"] else []
    return {**payload, "status": "ok"}
