"""One persisted forecast-call budget for all Polymonitor Open-Meteo readers."""
from __future__ import annotations

import json
import math
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

NAMESPACE = "source:open-meteo"
KEY = "daily-budget"
DEFAULT_DAILY_BUDGET = 6000


def _now():
    return datetime.now(timezone.utc)


def _count(value):
    return len([part for part in str(value or "").split(",") if part.strip()])


def request_cost(params):
    variables = sum(_count(params.get(key)) for key in ("current", "hourly", "daily", "minutely_15"))
    locations = max(1, _count(params.get("latitude")), _count(params.get("longitude")))
    models = max(1, _count(params.get("models")))
    days = int(params.get("forecast_days", 7)) + int(params.get("past_days", 0))
    return math.ceil(locations * max(1, variables * models / 10 * max(1, days / 14)) * 10)


def _update(store, cost=0, *, blocked_until=0):
    if not getattr(store, "db_path", None):
        raise RuntimeError("Open-Meteo budget storage unavailable")
    # Initialize the existing schema; reserve with a strict native transaction.
    # Cache reads/writes can silently skip busy storage; quota writes must not.
    store.get(NAMESPACE, KEY)
    now = _now()
    limit = min(9000, max(1, int(os.environ.get("POLYDATA_OPEN_METEO_DAILY_BUDGET", DEFAULT_DAILY_BUDGET)))) * 10
    with closing(sqlite3.connect(store.db_path, timeout=1)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT payload_json FROM panel_snapshots WHERE namespace=? AND cache_key=?", (NAMESPACE, KEY)).fetchone()
        state = json.loads(row[0]) if row else {}
        if state.get("day") != now.date().isoformat():
            state = {"day": now.date().isoformat(), "usedTenths": 0, "blockedUntil": state.get("blockedUntil", 0)}
        if not isinstance(state.get("usedTenths"), int) or state["usedTenths"] < 0 or not math.isfinite(state.get("blockedUntil", float("nan"))) or state["blockedUntil"] < 0:
            raise RuntimeError("Open-Meteo budget state invalid")
        if cost and (state["blockedUntil"] > now.timestamp() or state["usedTenths"] + cost > limit):
            raise RuntimeError("Open-Meteo daily budget or provider cooldown active")
        state["usedTenths"] += cost
        state["blockedUntil"] = max(state["blockedUntil"], blocked_until)
        state["limitTenths"] = limit
        conn.execute("""INSERT INTO panel_snapshots(namespace,cache_key,payload_json,updated_at,expires_at)
            VALUES(?,?,?,?,?) ON CONFLICT(namespace,cache_key) DO UPDATE SET
            payload_json=excluded.payload_json,updated_at=excluded.updated_at,expires_at=excluded.expires_at""",
            (NAMESPACE, KEY, json.dumps(state), int(now.timestamp()), max(int(now.timestamp()) + 172800, int(state["blockedUntil"]) + 86400)))


def get_forecast(http_json_get, store, url, *, params, **kwargs):
    host = urlparse(url).hostname or ""
    if host != "open-meteo.com" and not host.endswith(".open-meteo.com"):
        return http_json_get(url, params=params, **kwargs)
    # Only non-ensemble forecast calls are supported by this cost calculation.
    if urlparse(url).path.rstrip("/") != "/v1/forecast" or "ensemble" in str(params.get("models", "")):
        raise ValueError("Unsupported Open-Meteo budget endpoint")
    _update(store, request_cost(params))
    try:
        return http_json_get(url, params=params, **kwargs)
    except Exception as exc:
        response = getattr(exc, "response", None)
        if getattr(response, "status_code", None) == 429:
            now = _now()
            try:
                daily = "daily" in str(response.json().get("reason", "")).lower()
            except (ValueError, AttributeError):
                daily = False
            reset = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), timezone.utc).timestamp()
            retry = (getattr(response, "headers", {}) or {}).get("Retry-After")
            until = reset if daily else now.timestamp() + 3600
            if retry:
                try:
                    until = max(until, now.timestamp() + max(1, float(retry)))
                except ValueError:
                    try:
                        until = max(until, parsedate_to_datetime(retry).timestamp())
                    except (TypeError, ValueError):
                        pass
            _update(store, blocked_until=until)
        raise
