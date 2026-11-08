"""Bounded FRED CSV reads with a local observation window and original dates."""
from __future__ import annotations

import csv
import io
import math
import time
from datetime import date, datetime, timezone

import requests

from api.clients.source_transport import read_response_bytes, read_with_retry

MAX_CSV_BYTES = 2 * 1024 * 1024


def read_fred_text(session, url: str, *, deadline: float | None = None, **_kwargs) -> str:
    limit = time.monotonic() + 90
    if deadline is not None:
        limit = min(limit, deadline)
    body = read_with_retry(
        session, url,
        lambda response: read_response_bytes(response, MAX_CSV_BYTES, deadline=limit),
        attempts=2, deadline=limit, timeout=40, stream=True, require_full_attempt=True,
        headers={"Accept": "text/csv", "User-Agent": requests.utils.default_user_agent()},
    )
    return body.decode("utf-8-sig")


def fetch_fred_observations(read_text, url: str, series_id: str, *, lookback_years: int = 4,
                            now: datetime | None = None) -> list[dict]:
    if not url:
        raise ValueError("FRED source not configured")
    # The configured series CSV is served reliably without an injected cosd.
    # Keep any explicitly configured URL parameters and bound the window here.
    text = read_text(url, timeout=45, headers={"Accept": "text/csv"})
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("FRED CSV exceeds response limit")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    fields = reader.fieldnames or []
    date_field = next((key for key in ("observation_date", "DATE", "date") if key in fields), None)
    if series_id not in fields or date_field is None:
        raise ValueError("FRED CSV schema mismatch")
    start = date(max(1900, (now or datetime.now(timezone.utc)).year - max(1, lookback_years)), 1, 1)
    rows = []
    for row in reader:
        observed = str(row.get(date_field) or "").strip()
        try:
            observed_date = date.fromisoformat(observed)
            value = float(row.get(series_id))
        except (ValueError, TypeError):
            continue
        if observed_date >= start and math.isfinite(value):
            rows.append({"date": observed, "value": value})
    rows.sort(key=lambda row: row["date"])
    return rows
