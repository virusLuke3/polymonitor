"""Explicit, bounded external-source routing; never routes localhost or LOB."""
from __future__ import annotations

import email.utils
import json
import os
import threading
import time
from urllib.parse import urlsplit

import requests
from urllib3.util import Timeout

from runtime.snapshot_store import SnapshotStore
from data_sources import source_value

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


def _connection_route_failure(exc):
    # urllib3 body timeouts can be wrapped as Requests ConnectionError.
    # A closed/stalled response is local to that request, not proof of a dead exit.
    if isinstance(exc, (requests.exceptions.ReadTimeout, requests.exceptions.ChunkedEncodingError)):
        return False
    if isinstance(exc, (requests.exceptions.ConnectTimeout, requests.exceptions.ProxyError)):
        return True
    message = str(exc).lower()
    return isinstance(exc, requests.exceptions.ConnectionError) and any(
        phrase in message for phrase in ("connection refused", "failed to establish a new connection", "network is unreachable"))


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
        source_deadline = kwargs.pop("source_deadline", None)
        host = urlsplit(url).hostname or ""
        routes = self.routes.get(host)
        # This one documented POST is a public market-data read. Trading,
        # account reads and every other POST retain their original transport.
        info_url = urlsplit(source_value("POLYDATA_FINANCE_HYPERLIQUID_INFO_URL"))
        public_info_read = (bool(info_url.hostname) and host == info_url.hostname and urlsplit(url).path == info_url.path
                            and method.upper() == "POST" and kwargs.get("json") == {"type": "metaAndAssetCtxs"})
        if not routes or (method.upper() not in {"GET", "HEAD"} and not public_info_read) or host in {"localhost", "127.0.0.1", "::1"} or "polymarket" in host:
            return super().request(method, url, **kwargs)
        if not self._due(host + ":rate-limit"):
            raise requests.exceptions.RetryError(f"{host}: upstream Retry-After active")
        eligible = [(i, route) for i, route in enumerate(routes[:3]) if self._due(f"{host}:{i}")][:2]
        if not eligible:
            raise requests.exceptions.RetryError(f"{host}: source routes cooling down")
        timeout = kwargs.get("timeout") or 12
        if isinstance(timeout, Timeout):
            budget = float(timeout.total or timeout.read_timeout or timeout.connect_timeout or 12)
            connect = min(budget, float(timeout.connect_timeout or budget))
        else:
            budget = float(max(timeout) if isinstance(timeout, tuple) else timeout)
            connect = budget
        # timeout belongs to one complete attempt, not to a fraction of an
        # attempt per exit. Domain deadlines still cap the whole operation.
        deadline = time.monotonic() + budget * len(eligible)
        if source_deadline is not None:
            deadline = min(deadline, source_deadline)
        for position, (index, proxy) in enumerate(eligible):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise requests.exceptions.Timeout("source collection budget exhausted")
            allowance = min(budget, remaining)
            options = {**kwargs, "proxies": {"http": proxy or "", "https": proxy or ""},
                       "timeout": Timeout(total=allowance, connect=min(connect, allowance))}
            try:
                response = super().request(method, url, **options)
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                # A slow body/local read allowance is not evidence that the
                # exit is broken for every other collector using this host.
                if _connection_route_failure(exc):
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
            if 200 <= response.status_code < 300 and not kwargs.get("stream"):
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


def read_response_bytes(response, max_bytes, *, deadline=None, sample=False):
    """Validate and bound the body inside the retry, not after route success."""
    response.raise_for_status()
    body = bytearray()
    for chunk in response.iter_content(chunk_size=min(65536, max_bytes)):
        if deadline is not None and time.monotonic() >= deadline:
            raise requests.exceptions.Timeout("source body deadline exhausted")
        body.extend(chunk)
        if sample and len(body) >= max_bytes:
            return bytes(body[:max_bytes])
        if len(body) > max_bytes:
            raise ValueError("SOURCE_RESPONSE_TOO_LARGE")
    return bytes(body)


def read_with_retry(session, url, read_response, *, attempts=4, deadline=None,
                    require_full_attempt=False, respect_retry_after=False, **kwargs):
    """Collector-only retries, including body reads, with an intact attempt timeout.

    The normal request path keeps its original budget. Slow collectors opt in;
    they try an approved exit twice before moving once to its approved backup.
    """
    attempts = max(1, min(4, attempts))
    host = urlsplit(url).hostname or ""
    routed = isinstance(session, SourceSession) and host in session.routes
    if host in {"localhost", "127.0.0.1", "::1"} or "polymarket" in host:
        return read_response(session.get(url, **kwargs))
    if routed and not session._due(host + ":rate-limit"):
        raise requests.exceptions.RetryError(f"{host}: upstream Retry-After active")
    routes = [(i, proxy) for i, proxy in enumerate(session.routes[host][:3])
              if session._due(f"{host}:{i}")][:2] if routed else [(None, None)]
    if not routes:
        raise requests.exceptions.RetryError(f"{host}: source routes cooling down")
    request = super(SourceSession, session).request if isinstance(session, SourceSession) else session.request
    for attempt in range(attempts):
        per_route = 2 if attempts > 2 else 1
        index, proxy = routes[min(attempt // per_route, len(routes) - 1)]
        options = dict(kwargs)
        if deadline is not None:
            remaining = deadline - time.monotonic()
            requested_timeout = float(options.get("timeout", 45))
            if remaining <= 0 or (require_full_attempt and remaining < requested_timeout):
                raise requests.exceptions.Timeout("source collection budget exhausted")
            options["timeout"] = requested_timeout if require_full_attempt else min(requested_timeout, remaining)
        if routed:
            options["proxies"] = {"http": proxy or "", "https": proxy or ""}
        response = None
        try:
            response = request("GET", url, **options)
            if response.status_code == 429:
                if isinstance(session, SourceSession):
                    session._cool(host + ":rate-limit", _retry_seconds(response.headers.get("Retry-After")))
                response.raise_for_status()
            value = read_response(response)
            if routed:
                session._route_succeeded(f"{host}:{index}")
            return value
        except requests.exceptions.HTTPError as exc:
            if (respect_retry_after and exc.response is not None and exc.response.status_code == 503
                    and exc.response.headers.get('Retry-After')):
                if routed:
                    session._cool(host + ':rate-limit', _retry_seconds(exc.response.headers['Retry-After']))
                raise
            if exc.response is None or exc.response.status_code not in {500, 502, 503, 504}:
                raise
            if routed:
                session._route_failed(f"{host}:{index}")
            if attempt + 1 == attempts:
                raise
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as exc:
            if routed and _connection_route_failure(exc):
                session._route_failed(f"{host}:{index}")
            if attempt + 1 == attempts:
                raise
        finally:
            if response is not None:
                response.close()
        delay = 2 ** attempt
        if deadline is not None and time.monotonic() + delay >= deadline:
            raise requests.exceptions.Timeout("source collection budget exhausted")
        time.sleep(delay)
