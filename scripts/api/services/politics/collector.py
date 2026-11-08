"""Bounded acquisition with full per-attempt budgets, no browser-triggered work."""
from __future__ import annotations

from data_sources import source_value

import json
import os
import re
import time
from urllib.parse import urlsplit

from api.clients.source_transport import read_response_bytes, read_with_retry, source_session
from .catalog import catalog
from .normalizers import bill_status
from .evidence import hearing_metadata
from .store import BILL_REFRESH_SECONDS, BILL_REQUESTS_PER_ROUND, SOURCE_NS, collect


class SourceNotConfigured(ValueError):
    pass


class Transport:
    def __init__(self, *, deadline=None):
        self.session = source_session()
        self.session.trust_env = False
        self.deadline = deadline

    def remaining(self):
        return float("inf") if self.deadline is None else self.deadline - time.monotonic()

    def close(self):
        self.session.close()

    def get(self, url, *, max_bytes=8 * 1024**2):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or "{" in url:
            raise SourceNotConfigured("Missing or invalid politics source configuration")
        # Route configuration is explicit; never change the main Clash selection.
        proxy = os.environ.get("POLYMONITOR_POLITICS_PROXY_URL", "")
        deadline = min(time.monotonic() + 120, self.deadline or float("inf"))
        def fetch(target_url, *, allow_fec_redirect=False):
            def read(response):
                if 300 <= response.status_code < 400:
                    destination = response.headers.get("Location", "")
                    original, target = urlsplit(target_url), urlsplit(destination)
                    # Only this FEC GovCloud redirect is an approved source.
                    if not (allow_fec_redirect and response.status_code in (301, 302, 307, 308)
                            and bool(source_value("POLYMONITOR_URL_WWW_FEC_GOV_FILES_BULK_DOWNLOADS_AB50B3"))
                            and original.hostname == urlsplit(source_value("POLYMONITOR_URL_WWW_FEC_GOV_FILES_BULK_DOWNLOADS_AB50B3")).hostname
                            and original.path.startswith("/files/bulk-downloads/")
                            and target.scheme == "https"
                            and bool(source_value("POLYMONITOR_FEC_BULK_REDIRECT_URL"))
                            and target.hostname == urlsplit(source_value("POLYMONITOR_FEC_BULK_REDIRECT_URL")).hostname
                            and target.path == original.path.removeprefix("/files")
                            and not target.username and not target.query):
                        raise ValueError("Source redirected; review its canonical URL")
                    return destination
                return read_response_bytes(response, max_bytes, deadline=deadline)
            return read_with_retry(self.session, target_url, read, attempts=2, deadline=deadline,
                                   timeout=45, require_full_attempt=True, stream=True, allow_redirects=False,
                                   proxies={"http": proxy, "https": proxy},
                                   headers={"User-Agent": "Polymonitor/1.0", "Accept": "*/*"})
        result = fetch(url, allow_fec_redirect=True)
        return fetch(result) if isinstance(result, str) else result


def collect_owner(store, owner):
    # Leave cleanup/storage room inside the existing 1200-second service bound.
    transport = Transport(deadline=time.monotonic() + 900)
    try:
        with store.fetch_lock("owner:politics", owner, timeout=1):
            for spec in catalog():
                if spec.owner != owner:
                    continue
                if transport.remaining() < 45:
                    print(f"{spec.key}: deferred-owner-budget", flush=True)
                    continue
                def acquire():
                    raw = transport.get(spec.url, max_bytes=spec.max_bytes)
                    return raw, spec.parse(raw)
                previous_attempt = (store.get_stale(SOURCE_NS, spec.key) or {}).get("lastAttemptAt")
                state = collect(store, spec.key, acquire, spec.cadence)
                outcome = "not-due" if state.get("lastAttemptAt") == previous_attempt else state.get("error") or "stored"
                print(f"{spec.key}: {outcome}", flush=True)
            if owner == "government":
                collect_hearings(store, transport)
                collect_bills(store, transport)
    finally:
        transport.close()


def collect_hearings(store, transport):
    """At most three published hearing metadata reads per existing owner round."""
    feed = (store.get_stale(SOURCE_NS, "nomination-hearings") or {}).get("data", {})
    targets = {r["id"]: r for r in feed.get("items", [])}
    due = sorted(targets, key=lambda key: (store.get_stale(SOURCE_NS, "hearing:" + key) or {}).get("lastAttemptAt", 0))
    attempted = 0
    for identity in due:
        if getattr(transport, "remaining", lambda: float("inf"))() < 45:
            break
        previous = store.get_stale(SOURCE_NS, "hearing:" + identity) or {}
        if previous.get("nextAttemptAt", 0) > time.time():
            continue
        def acquire():
            raw = transport.get(targets[identity]["metadataUrl"])
            data = hearing_metadata(raw)
            if data["id"] != identity:
                raise ValueError("Hearing identity mismatch")
            return raw, data
        collect(store, "hearing:" + identity, acquire, 86400)
        attempted += 1
        if attempted >= 3:
            break


def collect_bills(store, transport):
    spec = next(s for s in catalog() if s.key.startswith("bills-"))
    feed = (store.get_stale(SOURCE_NS, spec.key) or {}).get("data", {})
    targets = {r["id"]: r["statusUrl"] for r in feed.get("items", [])}
    targets["119hr6500"] = source_value('POLYMONITOR_URL_WWW_GOVINFO_GOV_BULKDATA_BILLSTATUS_119_HR_BILLSTATUS_119HR6500_XML_7E532C')
    # Explicit watch targets supplement a bounded recent-publications feed.
    for identity in os.environ.get("POLYMONITOR_POLITICS_BILLS", "").split(","):
        match = re.fullmatch(r"(\d+)(hr|s|hjres|sjres|hconres|sconres|hres|sres)(\d+)", identity.strip())
        if match:
            key = match[0]
            targets[key] = f"{source_value('POLYMONITOR_URL_WWW_GOVINFO_GOV_BULKDATA_BILLSTATUS_D7E568')}{match[1]}/{match[2]}/BILLSTATUS-{key}.xml"
    index = store.get_stale(SOURCE_NS, "bill-index") or {"ids": []}
    # Rotate due targets using persisted last-attempt timestamps; max five per round.
    due = sorted(targets, key=lambda key: ((store.get_stale(SOURCE_NS, "bill:" + key) or {}).get("lastAttemptAt", 0), key != "119hr6500"))
    now = time.time()
    attempted = 0
    for identity in due:
        if transport.remaining() < 45:
            break
        previous = store.get_stale(SOURCE_NS, "bill:" + identity) or {}
        if previous.get("nextAttemptAt", 0) > now:
            continue
        def acquire():
            raw = transport.get(targets[identity])
            data = bill_status(raw)
            if data["id"] != identity:
                raise ValueError("Bill identity mismatch")
            return raw, data
        collect(store, "bill:" + identity, acquire, BILL_REFRESH_SECONDS)
        if identity not in index["ids"]:
            index["ids"].append(identity)
        attempted += 1
        if attempted >= BILL_REQUESTS_PER_ROUND:
            break
    index.update(ids=index["ids"][-200:], targetIds=list(targets)[-200:],
                 targetCount=len(targets), lastChecked=now)
    if not store.set(SOURCE_NS, "bill-index", index, 366 * 86400):
        raise RuntimeError("Bill cursor was not persisted")
