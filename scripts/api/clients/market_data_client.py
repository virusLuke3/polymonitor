from __future__ import annotations

import json
import time
import requests
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .http_client import http_json_get
from api.serialization import parse_interval_minutes






def _price_scale_compatible(left: Optional[float], right: Optional[float]) -> bool:
    if left in (None, 0) or right in (None, 0):
        return False
    ratio = max(abs(float(left)), abs(float(right))) / max(min(abs(float(left)), abs(float(right))), 1e-12)
    return ratio <= 20


def _quote_metadata(meta: dict, current: Optional[float], safe_float: Any) -> dict:
    """Preserve provider clocks; a recent fetch is not a recent quote."""
    now = datetime.now(timezone.utc)

    def iso(value: Any) -> str | None:
        try:
            number = float(value)
            return datetime.fromtimestamp(number, timezone.utc).isoformat().replace("+00:00", "Z") if number > 0 else None
        except (TypeError, ValueError, OverflowError, OSError):
            return None

    period = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    start, end = iso(period.get("start")), iso(period.get("end"))
    state = str(meta.get("marketState") or "").upper()
    market_state = "unknown"
    if state in {"REGULAR", "OPEN"}:
        market_state = "open"
    elif state in {"CLOSED", "PRE", "PREPRE", "POST", "POSTPOST"}:
        market_state = "closed"
    elif start and end:
        start_dt, end_dt = datetime.fromisoformat(start.replace("Z", "+00:00")), datetime.fromisoformat(end.replace("Z", "+00:00"))
        # An obsolete trading window cannot prove the market is closed today.
        if start_dt <= now <= end_dt:
            market_state = "open"
        elif abs((now - end_dt).total_seconds()) <= 4 * 86400:
            market_state = "closed"
    previous = safe_float(meta.get("previousClose"))
    daily = None
    if current is not None and _price_scale_compatible(current, previous):
        daily = round((current - previous) / previous * 100, 2)
    return {
        "dailyChangePercent": daily,
        "changeBasis": "previous-close" if daily is not None else "unknown",
        "quoteAt": iso(meta.get("regularMarketTime")),
        "fetchedAt": now.isoformat().replace("+00:00", "Z"),
        "marketState": market_state,
        "exchangeTimezone": meta.get("exchangeTimezoneName"),
        "instrumentType": meta.get("instrumentType"),
        "tradingSession": {"start": start, "end": end},
        "sessionVolume": safe_float(meta.get("regularMarketVolume")),
    }


def get_yahoo_market_snapshot(
    ctx: dict,
    symbol: str,
    *,
    interval: str = "30m",
    range_name: str = "5d",
    ttl_seconds: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    cache_key = json.dumps({"symbol": symbol, "interval": interval, "range": range_name}, sort_keys=True, ensure_ascii=True)
    use_runtime_cache = ttl_seconds is None or int(ttl_seconds) > 5
    if use_runtime_cache:
        cached = ctx["get_cached_runtime_payload"]("yahoo-chart", cache_key)
        if cached is not None:
            return cached
    source_key = ctx['SETTINGS'].yahoo_chart_base_url.rstrip('/')
    state = ctx["get_cached_runtime_payload"]("yahoo-source-backoff", source_key) or {}
    if float(state.get("retryAt") or 0) > time.time():
        raise RuntimeError("Yahoo source is in bounded failure backoff")
    try:
        payload = http_json_get(
            ctx,
            f"{ctx['SETTINGS'].yahoo_chart_base_url.rstrip('/')}/{symbol}",
            params={"interval": interval, "range": range_name, "includePrePost": "false"},
            timeout=12,
            headers={"User-Agent": "polydata-runtime/1.0", "Accept": "application/json"},
        )
    except requests.RequestException as exc:
        failures = int(state.get("failures") or 0) + 1
        retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("Retry-After")
        try:
            delay = max(0, float(retry_after))
        except (TypeError, ValueError):
            try:
                delay = max(0, parsedate_to_datetime(retry_after).timestamp() - time.time())
            except (TypeError, ValueError, OverflowError):
                delay = 0
        delay = max(delay, 60 if failures >= 3 else 0)
        ctx["set_cached_runtime_payload"]("yahoo-source-backoff", source_key,
            {"failures": failures, "retryAt": time.time() + delay if delay else 0}, ttl_seconds=max(60, int(delay) + 1))
        raise
    ctx["set_cached_runtime_payload"]("yahoo-source-backoff", source_key,
        {"failures": 0, "retryAt": 0}, ttl_seconds=60)
    result = (((payload or {}).get("chart") or {}).get("result") or [None])[0]
    if not isinstance(result, dict):
        return None
    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    quotes = ((((result.get("indicators") or {}).get("quote") or [None])[0]) or {})
    closes = quotes.get("close") or []
    points = []
    first_price = None
    last_price = None
    for index, timestamp in enumerate(timestamps):
        if index >= len(closes):
            break
        close = ctx["_safe_float"](closes[index])
        if close is None:
            continue
        if first_price is None:
            first_price = close
        last_price = close
        points.append(
            {
                "timestamp": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "value": close,
            }
        )
    current = ctx["_safe_float"](meta.get("regularMarketPrice")) or last_price
    previous = ctx["_safe_float"](meta.get("chartPreviousClose")) or first_price
    if current is not None and previous is not None and not _price_scale_compatible(current, previous):
        previous = first_price if _price_scale_compatible(current, first_price) else None
    change_pct = None
    if current is not None and previous not in (None, 0):
        change_pct = ((current - float(previous)) / float(previous)) * 100
    snapshot = {
        "symbol": symbol,
        "price": current,
        "changePercent": round(change_pct, 2) if change_pct is not None else None,
        "currency": meta.get("currency"),
        "volume24h": ctx["_safe_float"](meta.get("regularMarketVolume")),
        "marketCap": ctx["_safe_float"](meta.get("marketCap")),
        "name": meta.get("symbol") or symbol,
        "points": points[-48:],
        **_quote_metadata(meta, current, ctx["_safe_float"]),
    }
    # Crypto uses an actual 24h lookback, independent of Yahoo's chart baseline.
    # The provider quote clock anchors the reference; five-minute bars imply a
    # bounded reference-time approximation, which is exposed in the payload.
    quote_at = snapshot.get("quoteAt")
    target = datetime.fromisoformat(quote_at.replace("Z", "+00:00")).timestamp() - 86400 if quote_at else None
    reference = None
    if target is not None and current is not None:
        for point in points:
            point_ts = datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00")).timestamp()
            if point_ts <= target and target - point_ts <= max(600, parse_interval_minutes(interval) * 60):
                reference = point
    reference_price = reference["value"] if reference else None
    snapshot["rollingChangePercent24h"] = round((current / reference_price - 1) * 100, 2) if reference_price is not None and reference_price > 0 and _price_scale_compatible(current, reference_price) else None
    snapshot["reference24hAt"] = reference["timestamp"] if reference else None
    cache_ttl = max(1, int(ttl_seconds if ttl_seconds is not None else ctx["FINANCE_RUNTIME_TTL_SECONDS"]))
    if use_runtime_cache:
        return ctx["set_cached_runtime_payload"]("yahoo-chart", cache_key, snapshot, ttl_seconds=cache_ttl)
    return snapshot
