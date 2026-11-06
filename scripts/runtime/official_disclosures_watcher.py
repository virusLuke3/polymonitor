"""Scheduled source acquisition. No browser or API-triggered network work."""
from __future__ import annotations

import os
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import requests
from api.clients.source_transport import source_session
from api.services.official_disclosures_service import WATCHLIST, collect_source, facts, filings, policies, presidential_documents, publish
from runtime.snapshot_store import SnapshotStore


def run():
    store = SnapshotStore(os.environ["POLYDATA_SNAPSHOT_SQLITE_PATH"])
    session = source_session()
    session.trust_env = False
    user_agent = os.environ.get("POLYMONITOR_SEC_USER_AGENT", "")
    deadline = time.monotonic() + 1100
    def fetch(url):
        is_sec = urlsplit(url).hostname == "data.sec.gov"
        if is_sec and not user_agent:
            raise ValueError("SEC contact User-Agent is not configured")
        request_deadline = min(deadline, time.monotonic() + 100)
        proxy = os.environ.get("POLYMONITOR_DISCLOSURES_SEC_PROXY_URL", "") if is_sec else ""
        request_user_agent = user_agent if is_sec else "Polymonitor https://polymonitor.club"
        for attempt in range(2):
            try:
                remaining = request_deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Disclosure acquisition deadline")
                with session.get(url, timeout=(min(15, remaining), min(45, remaining)), stream=True,
                                 allow_redirects=False,
                                 proxies={"http": proxy, "https": proxy},
                                 headers={"User-Agent": request_user_agent, "Accept": "application/json"}) as response:
                    response.raise_for_status()
                    if 300 <= response.status_code < 400:
                        raise ValueError("Disclosure endpoint redirected; source URL requires review")
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 24 * 1024 * 1024 or time.monotonic() > request_deadline:
                            raise ValueError("Disclosure response exceeds byte/time budget")
                        chunks.append(chunk)
                    return json.loads(b"".join(chunks))
            except requests.RequestException as exc:
                status = exc.response.status_code if exc.response is not None else None
                if attempt or status is not None and status not in {502, 503, 504}:
                    raise
                time.sleep(2)
    try:
        with store.fetch_lock("owner:official-disclosures", "seed", timeout=1):
            since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
            params = {"per_page": 100, "order": "newest", "conditions[publication_date][gte]": since,
                      "fields[]": ["document_number", "title", "type", "publication_date", "html_url", "pdf_url", "agencies", "effective_on", "comments_close_on"]}
            url = "https://www.federalregister.gov/api/v1/documents.json?" + urlencode(params, doseq=True)
            collect_source(store, "federal-register", url, policies, fetch, 1800)
            presidential_since = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
            presidential_params = {"per_page": 100, "order": "newest", "conditions[type][]": "PRESDOCU",
                "conditions[publication_date][gte]": presidential_since,
                "fields[]": ["document_number", "title", "type", "publication_date", "html_url", "pdf_url", "agencies",
                    "effective_on", "signing_date", "subtype", "executive_order_number", "proclamation_number",
                    "raw_text_url", "correction_of", "executive_order_notes"]}
            presidential_url = "https://www.federalregister.gov/api/v1/documents.json?" + urlencode(presidential_params, doseq=True)
            def presidential_fetch(first_url):
                first = fetch(first_url)
                rows, next_url = first["results"], first.get("next_page_url")
                for _ in range(4):
                    if not next_url:
                        break
                    if urlsplit(next_url).hostname != "www.federalregister.gov":
                        raise ValueError("Unexpected Federal Register continuation host")
                    page = fetch(next_url)
                    rows.extend(page["results"])
                    next_url = page.get("next_page_url")
                return {**first, "results": rows, "next_page_url": next_url}
            collect_source(store, "federal-register:presidential", presidential_url,
                           presidential_documents, presidential_fetch, 1800)
            publish(store)
            for symbol, cik in WATCHLIST.items():
                for kind, cadence, url, parse in [
                    ("submissions", 1800, f"https://data.sec.gov/submissions/CIK{cik}.json", lambda raw: filings(raw, cik, symbol)),
                    ("facts", 21600, f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", lambda raw: facts(raw, cik)),
                ]:
                    if time.monotonic() + 100 > deadline:
                        return
                    state = collect_source(store, f"sec:{cik}:{kind}", url, parse, fetch, cadence)
                    print(f"{symbol}/{kind}: {'failed' if state.get('error') else 'available'} lastSuccessAt={state.get('lastSuccessAt')}", flush=True)
                    publish(store)
                    time.sleep(.2)  # Below SEC aggregate request allowance.
    finally:
        session.close()


if __name__ == "__main__":
    run()
