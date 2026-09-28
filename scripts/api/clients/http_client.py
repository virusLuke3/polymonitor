from __future__ import annotations

import os
from typing import Any, Dict, Optional


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
            session = requests_lib.Session()
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
) -> Any:
    requests_lib = ctx.get("requests")
    if requests_lib is None:
        return None
    request_headers = headers or {"Accept": "application/json"}
    trust_env_proxy = _truthy_env("POLYDATA_API_HTTP_TRUST_ENV_PROXY", default=False)
    if hasattr(requests_lib, "Session"):
        # A provider worker often performs many calls to the same host (for
        # example NWS affected-zone geometry).  Reuse a connection pool within
        # that worker thread while never sharing a Session across threads.
        session = _thread_session(ctx, requests_lib)
        session.trust_env = trust_env_proxy
        response = session.get(url, params=params, timeout=timeout, headers=request_headers)
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()
    response = requests_lib.get(url, params=params, timeout=timeout, headers=request_headers)
    response.raise_for_status()
    if not response.content:
        return None
    return response.json()
