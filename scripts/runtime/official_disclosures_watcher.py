"""Scheduled source acquisition. No browser or API-triggered network work."""
from __future__ import annotations

from data_sources import source_value

import os
import json
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

from api.clients.source_transport import read_response_bytes, read_with_retry, source_session
from api.services.official_disclosures_service import WATCHLIST, collect_source, facts, filings, policies, presidential_documents, publish
from runtime.snapshot_store import SnapshotStore


class Transport:
    def __init__(self, session, *, deadline, user_agent):
        self.session, self.deadline, self.user_agent = session, deadline, user_agent

    def fetch(self, url, *, deadline=None):
        is_sec = urlsplit(url).hostname == "data.sec.gov"
        if is_sec and not self.user_agent:
            raise ValueError("SEC contact User-Agent is not configured")
        request_deadline = min(self.deadline, deadline if deadline is not None else time.monotonic() + 100)
        proxy = os.environ.get("POLYMONITOR_DISCLOSURES_SEC_PROXY_URL", "") if is_sec else ""
        def read(response):
            if 300 <= response.status_code < 400:
                raise ValueError("Disclosure endpoint redirected; source URL requires review")
            return json.loads(read_response_bytes(response, 24 * 1024**2, deadline=request_deadline))
        return read_with_retry(self.session, url, read, attempts=2, deadline=request_deadline,
                               timeout=45, stream=True, allow_redirects=False,
                               proxies={"http": proxy, "https": proxy},
                               headers={"User-Agent": self.user_agent if is_sec else "Polymonitor",
                                        "Accept": "application/json"})


def run():
    store = SnapshotStore(os.environ["POLYDATA_SNAPSHOT_SQLITE_PATH"])
    session = source_session()
    session.trust_env = False
    deadline = time.monotonic() + 1100
    transport = Transport(session, deadline=deadline, user_agent=os.environ.get("POLYMONITOR_SEC_USER_AGENT", ""))
    fetch = transport.fetch
    try:
        with store.fetch_lock("owner:official-disclosures", "seed", timeout=1):
            since = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
            params = {"per_page": 100, "order": "newest", "conditions[publication_date][gte]": since,
                      "fields[]": ["document_number", "title", "type", "publication_date", "html_url", "pdf_url", "agencies", "effective_on", "comments_close_on"]}
            url = source_value('POLYMONITOR_URL_WWW_FEDERALREGISTER_GOV_API_V1_DOCUMENTS_JSON_C2538A') + urlencode(params, doseq=True)
            collect_source(store, "federal-register", url, policies, fetch, 1800)
            presidential_since = (datetime.now(timezone.utc) - timedelta(days=90)).date().isoformat()
            presidential_params = {"per_page": 100, "order": "newest", "conditions[type][]": "PRESDOCU",
                "conditions[publication_date][gte]": presidential_since,
                "fields[]": ["document_number", "title", "type", "publication_date", "html_url", "pdf_url", "agencies",
                    "effective_on", "signing_date", "subtype", "executive_order_number", "proclamation_number",
                    "raw_text_url", "correction_of", "executive_order_notes"]}
            presidential_url = source_value('POLYMONITOR_URL_WWW_FEDERALREGISTER_GOV_API_V1_DOCUMENTS_JSON_C2538A') + urlencode(presidential_params, doseq=True)
            def presidential_fetch(first_url):
                # Pagination shares one source budget; FR cannot consume five SEC slots.
                source_deadline = min(deadline, time.monotonic() + 100)
                first = fetch(first_url, deadline=source_deadline)
                rows, next_url = first["results"], first.get("next_page_url")
                for _ in range(4):
                    if not next_url:
                        break
                    if urlsplit(next_url).hostname != "www.federalregister.gov":
                        raise ValueError("Unexpected Federal Register continuation host")
                    page = fetch(next_url, deadline=source_deadline)
                    rows.extend(page["results"])
                    next_url = page.get("next_page_url")
                return {**first, "results": rows, "next_page_url": next_url}
            collect_source(store, "federal-register:presidential", presidential_url,
                           presidential_documents, presidential_fetch, 1800)
            publish(store)
            for symbol, cik in WATCHLIST.items():
                for kind, cadence, url, parse in [
                    ("submissions", 1800, f"{source_value('POLYMONITOR_URL_DATA_SEC_GOV_SUBMISSIONS_CIK_0584E3')}{cik}.json", lambda raw: filings(raw, cik, symbol)),
                    ("facts", 21600, f"{source_value('POLYMONITOR_URL_DATA_SEC_GOV_API_XBRL_COMPANYFACTS_CIK_2BF4F6')}{cik}.json", lambda raw: facts(raw, cik)),
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
