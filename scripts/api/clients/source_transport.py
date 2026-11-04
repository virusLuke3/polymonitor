"""Explicit, bounded external-source routing; never routes localhost or LOB."""
from __future__ import annotations

import email.utils
import json
import os
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

import requests
from urllib3.util import Timeout

from runtime.snapshot_store import SnapshotStore

_LOCK = threading.Lock()
_COOLDOWNS: dict[str, float] = {}
_FAILURES: dict[str, tuple[int, float]] = {}
_NAMESPACE = "state:source-transport"


def _routes() -> dict:
    path = os.environ.get("POLYMONITOR_SOURCE_ROUTES_FILE", "")
    if not path:
        return {}
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise ValueError("source route configuration must be an object")
    return data


def _retry_seconds(value: str | None) -> float:
    try:
        return max(60, float(value or 60))
    except ValueError:
        try:
            return max(60, email.utils.parsedate_to_datetime(value).timestamp() - time.time())
        except (ValueError, TypeError):
            return 60


class SourceSession(requests.Session):
    def __init__(self):
        super().__init__()
        self.routes = _routes()
        path = os.environ.get("POLYDATA_SNAPSHOT_SQLITE_PATH")
        self.route_store = SnapshotStore(path) if path and self.routes else None

    def _due(self, key):
        with _LOCK:
            until = _COOLDOWNS.get(key, 0)
        if self.route_store is not None:
            stored = self.route_store.get(_NAMESPACE, key)
            if isinstance(stored, dict):
                until = max(until, stored.get("retryAt", 0))
        return until <= time.time()

    def _cool(self, key, delay):
        until = time.time() + delay
        with _LOCK:
            _COOLDOWNS[key] = until
        if self.route_store is not None:
            self.route_store.set(_NAMESPACE, key, {"retryAt": until}, max(1, int(delay + 1)))

    def _route_failed(self, key):
        # A slow request is not proof that an entire source/route is down.
        # Two consecutive failures open the circuit; a real success resets it.
        now = time.time()
        with _LOCK:
            count, at = _FAILURES.get(key, (0, 0))
            count = count + 1 if now - at < 120 else 1
            _FAILURES[key] = (count, now)
        if count >= 2:
            self._cool(key, 120)

    def _route_succeeded(self, key):
        with _LOCK:
            _FAILURES.pop(key, None)
            had_cooldown = _COOLDOWNS.pop(key, None) is not None
        if self.route_store is not None and (had_cooldown or self.route_store.get(_NAMESPACE, key)):
            self.route_store.set(_NAMESPACE, key, {"retryAt": 0}, 1)

    def request(self, method, url, **kwargs):
        host = urlsplit(url).hostname or ""
        routes = self.routes.get(host)
        # Only idempotent public reads are eligible; local and market-data are excluded.
        if not routes or method.upper() not in {"GET", "HEAD"} or host in {"localhost", "127.0.0.1", "::1"} or "polymarket" in host:
            return super().request(method, url, **kwargs)
        if not self._due(host + ":rate-limit"):
            raise requests.exceptions.RetryError(f"{host}: upstream Retry-After active")
        eligible = [(i, route) for i, route in enumerate(routes[:3]) if self._due(f"{host}:{i}")][:2]
        if not eligible:
            raise requests.exceptions.RetryError(f"{host}: source routes cooling down")
        timeout = kwargs.get("timeout") or 12
        budget = float(max(timeout) if isinstance(timeout, tuple) else timeout)
        # Tiny legacy probes should not halve an already short TLS budget.
        if budget < 8:
            eligible = eligible[:1]
        deadline = time.monotonic() + budget
        for position, (index, proxy) in enumerate(eligible):
            remaining = max(0.1, deadline - time.monotonic())
            allowance = remaining / (len(eligible) - position)
            options = {**kwargs, "proxies": {"http": proxy or "", "https": proxy or ""},
                       "timeout": Timeout(total=allowance, connect=allowance)}
            try:
                response = super().request(method, url, **options)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                self._route_failed(f"{host}:{index}")
                if position + 1 == len(eligible):
                    raise
                continue
            if response.status_code == 429:
                self._cool(host + ":rate-limit", _retry_seconds(response.headers.get("Retry-After")))
                return response
            if response.status_code in {502, 503, 504}:
                self._route_failed(f"{host}:{index}")
                if position + 1 < len(eligible):
                    response.close()
                    continue
            if 200 <= response.status_code < 300:
                self._route_succeeded(f"{host}:{index}")
            # Preserve status/response semantics: domain owners validate and publish.
            response.headers["X-Polymonitor-Source-Route"] = str(index)
            return response
        raise requests.exceptions.RetryError(f"{host}: no source route completed")


def source_session(requests_lib=requests):
    # Dependency-injected test clients retain their own constructors.
    if requests_lib is requests and os.environ.get("POLYMONITOR_SOURCE_ROUTES_FILE"):
        return SourceSession()
    return requests_lib.Session()
