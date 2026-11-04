"""Bounded FRASER transport for the existing three BLS content sources."""
from __future__ import annotations

import re
import hashlib
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from api.services.bls_release_archive import archive_root, extract_text, parse_release, read_latest, save_document
from .http import fetch, SourceHTTPError
from .normalize import canonical_url

DOMAIN_LOCK = threading.Lock()


def _checked_fetch(session, url, source, state, deadline):
    body, meta = fetch(session, url, source, state, deadline=deadline)
    if meta["http_status"] not in {200, 304}:
        raise SourceHTTPError(meta)
    return body, meta


def latest_item(body, source):
    soup = BeautifulSoup(body, "html.parser")
    candidates = []
    for anchor in soup.select('a.list-item[data-type="item"]'):
        url = canonical_url(urljoin(source["feed_url"], anchor.get("href", "")), source)
        match = re.search(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})", anchor.get_text(" ", strip=True), re.I)
        if url and match:
            period = datetime.strptime(f"{match[1]} {match[2]}", "%B %Y")
            candidates.append((period, int(anchor.get("data-id", "0")), url))
    if not candidates:
        raise ValueError("fraser-release-directory-empty")
    return max(candidates)[2]


def collect(session, snapshot_store, source, *, deadline, probe=False):
    if not DOMAIN_LOCK.acquire(timeout=max(0, deadline - time.monotonic())):
        raise TimeoutError("fraser-domain-budget-exhausted")
    try:
        # Per-source policy: unrelated feeds retain their configured egress.
        session.trust_env = False
        session.proxies.clear()
        directory, directory_meta = _checked_fetch(session, source["feed_url"], source, {}, deadline)
        item_url = latest_item(directory, source)
        body, _ = _checked_fetch(session, item_url, source, {}, deadline)
        soup = BeautifulSoup(body, "html.parser")
        node = soup.find("meta", attrs={"name": "citation_pdf_url"})
        pdf_url = canonical_url(node.get("content", "") if node else "", source)
        if not pdf_url or not pdf_url.endswith(".pdf"):
            raise ValueError("fraser-pdf-link-missing")
        kind = source["release_kind"]
        old = read_latest(snapshot_store, kind)
        cached = old if old.get("archiveUrl") == item_url and old.get("pdfUrl") == pdf_url else {}
        if cached:
            path = archive_root(snapshot_store) / kind / cached["pdfFile"]
            if (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != cached.get("sha256")
                    or not (path.parent / cached["textFile"]).is_file()):
                cached = {}
        pdf, meta = _checked_fetch(session, pdf_url, source, cached.get("pdfHttp", {}), deadline)
        if meta["http_status"] == 304 and cached:
            record = cached
        else:
            text = extract_text(pdf, timeout=deadline - time.monotonic())
            record = {**parse_release(text, kind), "archiveUrl": item_url, "pdfUrl": pdf_url,
                      "distributor": "FRASER, Federal Reserve Bank of St. Louis", "publisher": "BLS",
                      "receivedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "pdfHttp": meta}
            if not probe:
                record = save_document(snapshot_store, kind, pdf, text, record)
        item = {"external_id": record["releaseNumber"],
                "event_id": f"bls:{kind}:{record['referencePeriod']}",
                "title": record["title"], "url": record["archiveUrl"], "summary": record["summary"],
                "published_at": record["published_at"], "reference_period": record["referencePeriod"],
                "source_kind": source["source_kind"], "topics": source["topics"], "language": "en",
                "excerpt_origin": "official-release", "distributor": record["distributor"],
                "pdf_url": record["pdfUrl"], "archive_sha256": record.get("sha256"),
                "archive_received_at": record["receivedAt"], "release_number": record["releaseNumber"]}
        return [item], {**directory_meta, "transport": "fraser-pdf", "proxy_mode": "direct",
                        "latest_release": record["published_at"], "latest_reference_period": record["referencePeriod"],
                        "archive_sha256": record.get("sha256"), "pdf_http_status": meta["http_status"]}
    finally:
        DOMAIN_LOCK.release()
