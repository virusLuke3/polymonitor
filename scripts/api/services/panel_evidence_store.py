"""Shared durable acquisition mechanics; domain parsers own business semantics.

Scheduled collectors write evidence and source state. Public API reads never
fetch, renew source clocks, or interpret a failed request as an empty result.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from api.clients.source_transport import read_response_bytes, read_with_retry, source_session
from data_sources import source_value

NAMESPACE = "source:external-panels:v1"


@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str
    url_env: str
    parse: Callable[[bytes], dict]
    cadence: int = 3600
    stale_after: int = 10800
    retain_for: int = 7 * 86400
    max_bytes: int = 8 * 1024**2
    timeout: int = 45
    headers: dict | None = None


def iso(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None


def public_url(value):
    try:
        u = urlsplit(value or "")
        return value if u.scheme == "https" and u.hostname and not u.username and not u.password else ""
    except ValueError:
        return ""


def fetch_bytes(url, *, deadline=None, max_bytes=8 * 1024**2, timeout=45, headers=None):
    """Two complete attempts under one deadline and the existing env route policy."""
    if not public_url(url) or "{" in url:
        raise ValueError("Source URL is not configured")
    end = min(deadline or float("inf"), time.monotonic() + 2 * timeout + 5)
    with source_session() as session:
        session.trust_env = False
        return read_with_retry(session, url,
            lambda response: read_response_bytes(response, max_bytes, deadline=end),
            attempts=2, deadline=end, timeout=timeout, require_full_attempt=True,
            stream=True, headers={"User-Agent": "Polymonitor/1.0", "Accept": "*/*", **(headers or {})})


def archive(store, key, body, data, acquired_at):
    configured = source_value("POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH")
    path = Path(configured).expanduser() if configured else Path(store.db_path).with_name("external-panel-evidence.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    revision = hashlib.sha256(body).hexdigest()
    encoded_body = zlib.compress(body)
    encoded_data = zlib.compress(json.dumps(data, ensure_ascii=False, allow_nan=False).encode())
    with sqlite3.connect(path, timeout=2) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS evidence(source TEXT, revision TEXT, first_received REAL, last_received REAL, body BLOB, normalized BLOB, PRIMARY KEY(source,revision))")
        old = db.execute("SELECT length(normalized) FROM evidence WHERE source=? AND revision=?", (key, revision)).fetchone()
        incremental = max(0, len(encoded_data) - old[0]) if old else len(encoded_body) + len(encoded_data)
        physical = sum(p.stat().st_size for p in (path, Path(str(path)+"-wal")) if p.exists())
        if incremental and physical + incremental > 2 * 1024**3:
            raise ValueError("External evidence archive capacity requires review")
        db.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?) ON CONFLICT(source,revision) DO UPDATE SET last_received=excluded.last_received, normalized=excluded.normalized",
            (key, revision, acquired_at, acquired_at, encoded_body, encoded_data))
    return revision


def collect_one(store, spec: SourceSpec, *, acquire=None, force=False, deadline=None, now=None):
    clock = time.time if now is None else lambda: now
    started = clock()
    with store.fetch_lock(NAMESPACE, spec.key, timeout=1):
        previous = store.get_stale(NAMESPACE, spec.key) or {}
        if not force and previous.get("nextAttemptAt", 0) > started:
            return previous
        state = {**previous, "lastAttemptAt": started, "cadence": spec.cadence}
        try:
            if acquire is None:
                raw = fetch_bytes(source_value(spec.url_env), deadline=deadline,
                    max_bytes=spec.max_bytes, timeout=spec.timeout, headers=spec.headers)
                data = spec.parse(raw)
            else:
                raw, data = acquire()
            if not isinstance(raw, bytes) or len(raw) > spec.max_bytes:
                raise ValueError("Source response exceeds byte budget")
            if not isinstance(data, dict):
                raise ValueError("Invalid normalized source")
            if len(json.dumps(data, allow_nan=False).encode()) > 2 * 1024**2:
                raise ValueError("Normalized source exceeds budget")
            acquired = clock()
            revision = archive(store, spec.key, raw, data, acquired)
            state.update(data=data, revision=revision, lastSuccessAt=acquired,
                nextAttemptAt=acquired + spec.cadence, failures=0, error=None)
        except Exception as exc:
            response = getattr(exc, "response", None)
            code = response.status_code if response is not None else None
            failures = int(previous.get("failures", 0)) + 1
            delay = min(3600, 300 * 2 ** min(failures - 1, 4))
            if code == 429:
                from api.clients.source_transport import _retry_seconds
                delay = max(delay, _retry_seconds(response.headers.get("Retry-After")))
            if code in (401, 403):
                delay = max(delay, spec.cadence)
            error = f"HTTP {code}" if code else type(exc).__name__
            if not source_value(spec.url_env) and acquire is None:
                error = "not-configured"
            state.update(error=error, failures=failures, nextAttemptAt=clock() + delay)
        if not store.set(NAMESPACE, spec.key, state, ttl_seconds=max(366 * 86400, spec.retain_for)):
            raise RuntimeError("Source state was not persisted")
        return state


def collect_sources(store, specs, *, force=False, budget=300):
    deadline = time.monotonic() + budget
    result = {}
    # Oldest due source first prevents a slow early entry starving later sources.
    ordered = sorted(specs, key=lambda s: (store.get_stale(NAMESPACE, s.key) or {}).get("lastAttemptAt", 0))
    for spec in ordered:
        if deadline - time.monotonic() < spec.timeout:
            result[spec.key] = "deferred-budget"
            continue
        try:
            state = collect_one(store, spec, force=force, deadline=deadline)
        except TimeoutError:
            result[spec.key] = "deferred-lock"
            continue
        result[spec.key] = state.get("error") or "stored-or-not-due"
    return result


def read_source(store, spec: SourceSpec, *, now=None):
    now = time.time() if now is None else now
    state = store.get_stale(NAMESPACE, spec.key) or {}
    success = state.get("lastSuccessAt")
    usable = isinstance(success, (int, float)) and 0 <= now - success <= spec.retain_for and isinstance(state.get("data"), dict)
    meta = {"id": spec.key, "label": spec.label,
        "lastSuccessAt": iso(success), "lastAttemptAt": iso(state.get("lastAttemptAt")),
        "nextAttemptAt": iso(state.get("nextAttemptAt")), "revision": state.get("revision"),
        "usable": usable, "stale": success is None or now - success > spec.stale_after,
        "error": state.get("error") or ("not-configured" if not source_value(spec.url_env) else None),
        "expectedIntervalSeconds": spec.cadence, "staleAfterSeconds": spec.stale_after,
        "maxRetentionSeconds": spec.retain_for}
    # URLs are returned by parsers as reviewed evidence, never by echoing config.
    return state.get("data", {}) if usable else {}, meta


def payload(panel_id, sources, **fields):
    success = [s["lastSuccessAt"] for s in sources if s.get("usable") and s.get("lastSuccessAt")]
    status = "unavailable" if not success else "degraded" if any(not s.get("usable") or s.get("stale") or s.get("error") for s in sources) else "ok"
    result = {**fields, "panelId": panel_id, "schemaVersion": 1,
        "generatedAt": max(success) if success else None, "status": status, "sources": sources}
    if len(json.dumps(result, allow_nan=False).encode()) > 512 * 1024:
        raise ValueError("Panel projection exceeds byte budget")
    return result
