"""Explicit, bounded external-source routing; never routes localhost or LOB."""
from __future__ import annotations

import email.utils
import json
import os
import threading
import time
from data_sources import source_value
from urllib.parse import urlsplit

import requests
from urllib3.util import Timeout

from runtime.snapshot_store import SnapshotStore

_LOCK = threading.Lock()
_COOLDOWNS: dict[str, float] = {}
_FAILURES: dict[str, tuple[int, float]] = {}
_NAMESPACE = "state:source-transport"


def _routes() -> dict:
    raw = source_value("POLYMONITOR_SOURCE_ROUTES_JSON")
    if not raw:
        if source_value("POLYMONITOR_SOURCE_ROUTES_FILE"):
            raise ValueError("Move source routes into POLYMONITOR_SOURCE_ROUTES_JSON in .env")
        return {}
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("Invalid POLYMONITOR_SOURCE_ROUTES_JSON") from None
    if not isinstance(data, dict):
        raise ValueError("source route configuration must be an object")
    for host, routes in data.items():
        if not isinstance(host, str) or not host or "/" in host or not isinstance(routes, list):
            raise ValueError("Invalid source route entry")
        for route in routes:
            if not isinstance(route, str) or route and urlsplit(route).scheme not in {"http", "https", "socks5", "socks5h"}:
                raise ValueError("Invalid source route protocol")
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

    def read_weather_books(self, url, tokens, *, timeout=12, source_deadline=None):
        """Explicit weather-only public POST, including bounded body retries.

        Reuse route cooldowns and their durable store without enabling any other
        Polymarket POST, account read, or internal LOB request.
        """
        if (not source_value("POLYDATA_CLOB_API_BASE")
                or url != source_value("POLYDATA_CLOB_API_BASE").rstrip("/") + "/books"
                or not 1 <= len(tokens) <= 100
                or any(not isinstance(t, str) or not t.isdecimal() or len(t) > 100 for t in tokens)):
            raise ValueError("Invalid weather book read")
        host = urlsplit(url).hostname or ""
        if not self._due(host + ":rate-limit"):
            raise requests.exceptions.RetryError("Weather books Retry-After active")
        routes = [(i, proxy) for i, proxy in enumerate(self.routes.get(host, [""])[:3])
                  if self._due(f"{host}:{i}")][:2]
        if not routes:
            raise requests.exceptions.RetryError("Weather book routes cooling down")
        deadline = min(source_deadline or float("inf"), time.monotonic() + timeout * len(routes))
        for position, (index, proxy) in enumerate(routes):
            allowance = min(timeout, deadline - time.monotonic())
            if allowance <= 0:
                raise requests.exceptions.Timeout("Weather book budget exhausted")
            try:
                with super().request("POST", url, json=[{"token_id": t} for t in tokens],
                                     timeout=Timeout(total=allowance, connect=min(6, allowance)),
                                     proxies={"http": proxy or "", "https": proxy or ""},
                                     stream=True, allow_redirects=False) as response:
                    if response.status_code == 429:
                        self._cool(host + ":rate-limit", _retry_seconds(response.headers.get("Retry-After")))
                        response.raise_for_status()
                    if response.status_code in {502, 503, 504} and position + 1 < len(routes):
                        self._route_failed(f"{host}:{index}")
                        continue
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_content(chunk_size=65536):
                        if time.monotonic() >= deadline:
                            raise requests.exceptions.Timeout("Weather book body deadline")
                        body.extend(chunk)
                        if len(body) > 2 * 1024 * 1024:
                            raise ValueError("Weather book response too large")
                    value = json.loads(body)
                self._route_succeeded(f"{host}:{index}")
                return value
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError):
                self._route_failed(f"{host}:{index}")
                if position + 1 == len(routes):
                    raise
        raise requests.exceptions.RetryError("Weather book read failed")


def source_session(requests_lib=requests):
    # Dependency-injected test clients retain their own constructors.
    if requests_lib is requests and (source_value("POLYMONITOR_SOURCE_ROUTES_JSON") or source_value("POLYMONITOR_SOURCE_ROUTES_FILE")):
        return SourceSession()
    return requests_lib.Session()
