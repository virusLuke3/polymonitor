from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit


from api.clients.source_transport import SourceSession, read_with_retry, source_session
from api.context import runtime_resources


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _thread_session(ctx, requests_lib: Any):
    resources = runtime_resources(ctx)
    with resources.http_lock:
        if resources.stopped.is_set():
            raise RuntimeError("service runtime is closed")
        session = getattr(resources.http_local, "session", None)
        if session is None:
            session = source_session(requests_lib)
            resources.http_local.session = session
            resources.http_sessions.append(session)
        return session


def http_json_get(
    ctx: dict,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 12,
    headers: Optional[Dict[str, str]] = None,
    max_response_bytes: int | None = None,
    retry_attempts: int = 1,
    retry_deadline: float | None = None,
) -> Any:
    requests_lib = ctx.get("requests")
    if requests_lib is None:
        return None
    owner_deadline = ctx.get("external_source_deadline")
    if owner_deadline is not None:
        remaining = owner_deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("external panel collection deadline exhausted")
        timeout = min(timeout, remaining)
        retry_deadline = min(retry_deadline, owner_deadline) if retry_deadline is not None else owner_deadline
    request_headers = headers or {"Accept": "application/json"}
    trust_env_proxy = _truthy_env("POLYDATA_API_HTTP_TRUST_ENV_PROXY", default=False)
    proxy_url = os.environ.get("POLYDATA_API_HTTP_PROXY_URL", "").strip()
    if urlsplit(url).hostname in {"localhost", "127.0.0.1", "::1"}:
        proxy_url = ""
    proxy_options = {"proxies": {"http": proxy_url, "https": proxy_url}} if proxy_url else {}
    response_options = {"stream": True} if max_response_bytes is not None else {}
    if hasattr(requests_lib, "Session"):
        # A provider worker often performs many calls to the same host (for
        # example NWS affected-zone geometry).  Reuse a connection pool within
        # that worker thread while never sharing a Session across threads.
        session = _thread_session(ctx, requests_lib)
        session.trust_env = trust_env_proxy
        if retry_attempts > 1:
            return read_with_retry(session, url, lambda response: _read_json_response(response, max_response_bytes, retry_deadline),
                                   attempts=retry_attempts, deadline=retry_deadline, params=params, timeout=timeout, headers=request_headers,
                                   **proxy_options, **response_options)
        deadline_options = {"source_deadline": retry_deadline} if isinstance(session, SourceSession) and retry_deadline is not None else {}
        response = session.get(url, params=params, timeout=timeout, headers=request_headers, **proxy_options, **response_options, **deadline_options)
        value = _read_json_response(response, max_response_bytes, retry_deadline)
        route = response.headers.get("X-Polymonitor-Source-Route") if isinstance(session, SourceSession) else None
        if route is not None:
            session._route_succeeded(f"{urlsplit(url).hostname}:{route}")
        return value
    if hasattr(requests_lib, "trust_env"):
        requests_lib.trust_env = trust_env_proxy
    deadline_options = {"source_deadline": retry_deadline} if isinstance(requests_lib, SourceSession) and retry_deadline is not None else {}
    response = requests_lib.get(url, params=params, timeout=timeout, headers=request_headers, **proxy_options, **response_options, **deadline_options)
    return _read_json_response(response, max_response_bytes, retry_deadline)


def _read_json_response(response, max_response_bytes, deadline=None):
    if max_response_bytes is not None:
        try:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("source body collection budget exhausted")
                if len(body) + len(chunk) > max_response_bytes:
                    raise ValueError("SOURCE_RESPONSE_TOO_LARGE")
                body.extend(chunk)
            return json.loads(body) if body else None
        finally:
            response.close()
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()
