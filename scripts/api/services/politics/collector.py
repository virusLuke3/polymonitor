"""Bounded acquisition with full per-attempt budgets, no browser-triggered work."""
from __future__ import annotations

from data_sources import source_value

import json
import os
import re
import time
from urllib.parse import urlsplit

import requests
from api.clients.source_transport import source_session
from .catalog import catalog
from .normalizers import bill_status
from .store import SOURCE_NS, collect


class Transport:
    def __init__(self):
        self.session = source_session()
        self.session.trust_env = False

    def close(self):
        self.session.close()

    def get(self, url):
        # Route configuration is explicit; never change the main Clash selection.
        proxy = os.environ.get("POLYMONITOR_POLITICS_PROXY_URL", "")
        deadline = time.monotonic() + 120
        for attempt in range(2):
            remaining = deadline - time.monotonic()
            if remaining < 2:
                raise TimeoutError("Politics request deadline")
            try:
                def request(target):
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TimeoutError("Politics request deadline")
                    options = {"stream": True, "allow_redirects": False,
                        "timeout": (min(15, left), min(45, left)),
                        "proxies": {"http": proxy, "https": proxy},
                        "headers": {"User-Agent": "Polymonitor/1.0", "Accept": "*/*"}}
                    if hasattr(self.session, "routes"):
                        options["source_deadline"] = deadline
                    return self.session.get(target, **options)
                response = request(url)
                if response.status_code in (301, 302, 307, 308):
                    destination = response.headers.get("Location", "")
                    response.close()
                    original, target = urlsplit(url), urlsplit(destination)
                    # FEC publishes bulk files through this verified US GovCloud bucket.
                    # No arbitrary cross-host redirects, credential forwarding or private URLs.
                    if not (bool(source_value("POLYMONITOR_URL_WWW_FEC_GOV_FILES_BULK_DOWNLOADS_AB50B3")) and original.hostname == urlsplit(source_value("POLYMONITOR_URL_WWW_FEC_GOV_FILES_BULK_DOWNLOADS_AB50B3")).hostname and original.path.startswith("/files/bulk-downloads/")
                            and target.scheme == "https"
                            and bool(source_value("POLYMONITOR_FEC_BULK_REDIRECT_URL")) and target.hostname == urlsplit(source_value("POLYMONITOR_FEC_BULK_REDIRECT_URL")).hostname
                            and target.path == original.path.removeprefix("/files")
                            and not target.username and not target.query):
                        raise ValueError("Source redirected; review its canonical URL")
                    response = request(destination)
                with response:
                    response.raise_for_status()
                    if 300 <= response.status_code < 400:
                        raise ValueError("Source redirected; review its canonical URL")
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        if size > 8 * 1024**2 or time.monotonic() > deadline:
                            raise ValueError("Politics response exceeds byte/time budget")
                        chunks.append(chunk)
                    return b"".join(chunks)
            except requests.RequestException as exc:
                status = exc.response.status_code if exc.response is not None else None
                if attempt or status is not None and status not in {502, 503, 504}:
                    raise
                if deadline - time.monotonic() < 17:
                    raise
                time.sleep(2)
        raise TimeoutError("Politics acquisition exhausted")


def collect_owner(store, owner):
    transport = Transport()
    try:
        with store.fetch_lock("owner:politics", owner, timeout=1):
            for spec in catalog():
                if spec.owner != owner:
                    continue
                def acquire():
                    raw = transport.get(spec.url)
                    return raw, spec.parse(raw)
                previous_attempt = (store.get_stale(SOURCE_NS, spec.key) or {}).get("lastAttemptAt")
                state = collect(store, spec.key, acquire, spec.cadence)
                outcome = "not-due" if state.get("lastAttemptAt") == previous_attempt else state.get("error") or "stored"
                print(f"{spec.key}: {outcome}", flush=True)
            if owner == "government":
                collect_bills(store, transport)
    finally:
        transport.close()


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
        previous = store.get_stale(SOURCE_NS, "bill:" + identity) or {}
        if previous.get("nextAttemptAt", 0) > now:
            continue
        def acquire():
            raw = transport.get(targets[identity])
            data = bill_status(raw)
            if data["id"] != identity:
                raise ValueError("Bill identity mismatch")
            return raw, data
        collect(store, "bill:" + identity, acquire, 1800)
        if identity not in index["ids"]:
            index["ids"].append(identity)
        attempted += 1
        if attempted >= 5:
            break
    index.update(ids=index["ids"][-200:], targetCount=len(targets), lastChecked=now)
    if not store.set(SOURCE_NS, "bill-index", index, 366 * 86400):
        raise RuntimeError("Bill cursor was not persisted")
