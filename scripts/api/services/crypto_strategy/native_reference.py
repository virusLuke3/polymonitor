"""Read the existing market-data owner, independently of slow venue collection."""
import json
import os
import threading
import time
from urllib.request import Request, urlopen

from .contracts import ASSETS
from .providers import references

_lock = threading.Lock()
_cached = None
_expires = 0
_url = None


def _get(url):
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=7) as response:
        body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError("REFERENCE_RESPONSE_TOO_LARGE")
        return json.loads(body)


def current_references():
    global _cached, _expires, _url
    url = os.environ.get("POLYDATA_CRYPTO_REFERENCE_READER_URL", "")
    missing = {a: {"status": "unavailable",
                   "error": "REFERENCE_READER_UNCONFIGURED"} for a in ASSETS}
    if not url:
        return missing
    if _cached is not None and _url == url and time.monotonic() < _expires:
        return _cached
    # A shared refresh must not queue every API request behind the same read.
    if not _lock.acquire(blocking=False):
        return _cached if _url == url and _cached else missing
    try:
        try:
            # Validate freshness against response completion, not request start.
            payload = _get(url.rstrip("/") + "/crypto/reference")
            data = references(lambda *_: payload, url, int(time.time()*1000))
            _cached, _url, _expires = data, url, time.monotonic() + 1
        except (OSError, ValueError, TypeError, KeyError):
            previous = _cached if _url == url and _cached else missing
            _cached = {a: {**ref, "status": "stale" if ref.get("latest") else "unavailable",
                          "error": "REFERENCE_READ_FAILED"} for a, ref in previous.items()}
            _url, _expires = url, time.monotonic() + 3
        return _cached
    finally:
        _lock.release()
