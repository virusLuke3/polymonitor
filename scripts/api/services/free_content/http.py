from __future__ import annotations
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit
import requests


class SourceHTTPError(RuntimeError):
    def __init__(self, meta):
        self.meta = meta
        super().__init__(f"HTTP {meta['http_status']}")


MAX_BYTES = 2_500_000
USER_AGENT = "Polymonitor/1.0 (+https://www.polymonitor.club/)"


def validate_url(url, hosts):
    p = urlsplit(url)
    if p.scheme != "https" or p.hostname not in hosts or p.username or p.password or p.port not in {None, 443}:
        raise ValueError("unapproved-host")
    for result in socket.getaddrinfo(p.hostname, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(result[4][0]).is_global:
            raise ValueError("non-public-host-address")


def fetch(session, url, source, state=None, *, deadline=None):
    deadline = deadline if deadline is not None else time.monotonic() + 45
    def remaining():
        budget = deadline - time.monotonic()
        if budget <= 0:
            raise TimeoutError("source-budget-exhausted")
        return budget
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/atom+xml, application/geo+json, application/json, text/html, application/xml",
    }
    state = state or {}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    for _ in range(4):
        remaining()
        validate_url(url, source["allowed_hosts"])
        budget = remaining()
        with session.get(url, headers=headers, timeout=(min(6, budget), min(18, budget)), allow_redirects=False, stream=True) as r:
            remaining()
            if r.status_code in {301, 302, 303, 307, 308}:
                url = urljoin(url, r.headers.get("Location", ""))
                continue
            meta = {
                "http_status": r.status_code,
                "final_url": url,
                "etag": r.headers.get("ETag"),
                "last_modified": r.headers.get("Last-Modified"),
                "retry_after": r.headers.get("Retry-After"),
                "cache_control": r.headers.get("Cache-Control"),
            }
            if r.status_code == 304:
                return b"", meta
            if r.status_code == 429:
                return b"", meta
            if r.status_code >= 400:
                raise SourceHTTPError(meta)
            chunks = []
            size = 0
            for chunk in r.iter_content(65536):
                remaining()
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("response-too-large")
                chunks.append(chunk)
            return b"".join(chunks), meta
    raise ValueError("redirect-limit")
