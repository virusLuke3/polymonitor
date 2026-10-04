from __future__ import annotations

import time
from urllib.parse import urlsplit
from typing import Callable

from .contracts import CATALOG_RETAIN_SECONDS, CATALOG_SECONDS, current, millis_iso, normalize_quote, number
from .universe import underlying

SOURCE_BUDGET_SECONDS = 8


def origin(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("invalid-venue-url")
    return f"{parts.scheme}://{parts.netloc}"


def bybit_rows(payload: object) -> tuple[list[dict], str, str | None]:
    if not isinstance(payload, dict) or payload.get("retCode") != 0:
        raise ValueError("bybit-business-error")
    result = payload.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("list"), list):
        raise ValueError("invalid-bybit-schema")
    return [row for row in result["list"] if isinstance(row, dict)], str(result.get("nextPageCursor") or ""), millis_iso(payload.get("time"))


def fetch_catalog(exchange: str, request: Callable, *, base: str, now: str) -> dict:
    instruments: dict[str, dict] = {}
    if exchange == "Binance":
        info = request(f"{base}/fapi/v1/exchangeInfo")
        if not isinstance(info, dict) or not isinstance(info.get("symbols"), list):
            raise ValueError("invalid-binance-instruments")
        funding = request(f"{base}/fapi/v1/fundingInfo")
        if not isinstance(funding, list):
            raise ValueError("invalid-binance-funding-info")
        periods = {str(row.get("symbol")): number(row.get("fundingIntervalHours")) for row in funding if isinstance(row, dict)}
        for raw in info["symbols"]:
            if not isinstance(raw, dict):
                continue
            symbol = str(raw.get("symbol") or "")
            if raw.get("quoteAsset") != "USDT" or raw.get("marginAsset") != "USDT":
                continue
            asset = underlying(raw.get("baseAsset"))
            if not symbol or not asset:
                continue
            instruments[symbol] = {"symbol": symbol, "asset": asset, "status": raw.get("status"),
                "eligible": raw.get("status") == "TRADING" and raw.get("contractType") == "PERPETUAL",
                "intervalHours": periods.get(symbol), "checkedAt": now}
    else:
        cursor = ""
        for _ in range(4):
            params = {"category": "linear", "limit": 1000}
            if cursor:
                params["cursor"] = cursor
            rows, next_cursor, _ = bybit_rows(request(f"{base}/v5/market/instruments-info", params=params))
            for raw in rows:
                symbol = str(raw.get("symbol") or "")
                asset = underlying(raw.get("baseCoin"))
                if raw.get("settleCoin") != "USDT" or raw.get("quoteCoin") != "USDT" or not symbol or not asset:
                    continue
                period = number(raw.get("fundingInterval"))
                instruments[symbol] = {"symbol": symbol, "asset": asset, "status": raw.get("status"),
                    "eligible": raw.get("status") == "Trading" and raw.get("contractType") == "LinearPerpetual",
                    "intervalHours": period / 60 if period else None, "checkedAt": now}
            if not next_cursor:
                break
            if next_cursor == cursor:
                raise ValueError("bybit-pagination-repeated")
            cursor = next_cursor
        else:
            raise ValueError("bybit-catalog-scan-limit")
    if not instruments:
        raise ValueError("empty-venue-catalog")
    return {"checkedAt": now, "instruments": instruments, "status": "ok"}


def collect_venue(exchange: str, *, url: str, get: Callable, now: str, cached_catalog: dict | None, save_catalog: Callable, clock: Callable | None = None) -> dict:
    """Each venue has its own budget, clocks, eligibility and failure state."""
    deadline = time.monotonic() + SOURCE_BUDGET_SECONDS
    def request(endpoint: str, params: dict | None = None):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("venue-request-deadline")
        return get(endpoint, params=params, timeout=min(5, left), headers={"Accept": "application/json", "User-Agent": "polymonitor-funding/3"})

    result = {"status": "error", "catalogStatus": "unavailable", "catalog": {}, "quotes": [],
              "attemptedAt": now, "fetchedAt": None, "responseAt": None, "errorCode": None}
    if not url:
        result["errorCode"] = "missing-venue-url"
        return result
    catalog = cached_catalog or {}
    try:
        if not current(catalog.get("checkedAt"), now, CATALOG_SECONDS):
            catalog = fetch_catalog(exchange, request, base=origin(url), now=now)
            checked = clock() if clock else now
            catalog = {**catalog, "checkedAt": checked, "instruments": {
                symbol: {**instrument, "checkedAt": checked} for symbol, instrument in catalog["instruments"].items()}}
            save_catalog(catalog)
        result["catalogStatus"] = "ok"
    except Exception as exc:
        if current(catalog.get("checkedAt"), now, CATALOG_RETAIN_SECONDS):
            result["catalogStatus"] = "retained"
        else:
            result["errorCode"] = type(exc).__name__
            return result
    result["catalog"] = catalog
    try:
        payload = request(url, {"category": "linear"} if exchange == "Bybit" else None)
        if exchange == "Bybit":
            rows, _, response_at = bybit_rows(payload)
        else:
            if not isinstance(payload, list):
                raise ValueError("invalid-binance-ticker-schema")
            rows, response_at = [row for row in payload if isinstance(row, dict)], None
        result["responseAt"] = response_at
        fetched_at = clock() if clock else now
        for raw in rows:
            instrument = catalog.get("instruments", {}).get(str(raw.get("symbol") or ""))
            if instrument is None:
                continue
            quote = normalize_quote(raw, instrument, exchange=exchange, response_at=response_at, fetched_at=fetched_at)
            if quote is not None:
                result["quotes"].append(quote)
        result["status"] = "ok" if result["quotes"] else "empty"
        result["fetchedAt"] = fetched_at
    except Exception as exc:
        result["errorCode"] = type(exc).__name__
    return result
