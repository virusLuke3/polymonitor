from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 3
DEFAULT_LIMIT = 80
MAX_LIMIT = 120
FRESH_SECONDS = 90
RETAIN_SECONDS = 900
CATALOG_SECONDS = 600
CATALOG_RETAIN_SECONDS = 1800


def number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.timestamp() if result.tzinfo is not None else None
    except (ValueError, TypeError, OverflowError):
        return None


def millis_iso(value: Any) -> str | None:
    millis = number(value)
    if millis is None or millis <= 0:
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def current(value: Any, now: str, max_age: int = FRESH_SECONDS) -> bool:
    observed, clock = timestamp(value), timestamp(now)
    return observed is not None and clock is not None and -30 <= clock - observed <= max_age


def funding_direction(rate: float) -> str:
    return "positive" if rate > 0 else "negative" if rate < 0 else "flat"


def normalize_quote(raw: dict, instrument: dict, *, exchange: str, response_at: str | None, fetched_at: str) -> dict | None:
    """Only a qualified USDT perpetual can supply an actionable funding quote.

    Provider response clocks are preserved separately from a quote's native time.
    An absent interval is unknown, never an assumed eight-hour settlement.
    """
    if instrument.get("eligible") is not True:
        return None
    rate = number(raw.get("lastFundingRate") if exchange == "Binance" else raw.get("fundingRate"))
    if rate is None or abs(rate) > 1:
        return None
    symbol = str(raw.get("symbol") or "")
    if symbol != instrument.get("symbol"):
        return None
    quote_at = millis_iso(raw.get("time")) if exchange == "Binance" else None
    clock = quote_at if exchange == "Binance" else response_at
    if not current(clock, fetched_at):
        return None
    period = number(raw.get("fundingIntervalHour")) if exchange == "Bybit" else None
    period = period if period is not None and 0 < period <= 24 else number(instrument.get("intervalHours"))
    period = period if period is not None and 0 < period <= 24 else None
    percent = rate * 100
    normalized = percent * 8 / period if period else None
    next_at = millis_iso(raw.get("nextFundingTime"))
    if next_at and timestamp(next_at) < timestamp(fetched_at) - 60:
        return None
    return {
        "id": f"{exchange.lower()}:{symbol}", "exchange": exchange,
        "symbol": symbol, "pair": symbol, "asset": instrument["asset"],
        "contractType": "perpetual", "contractStatus": instrument["status"],
        "settleCoin": "USDT", "eligible": True,
        "eligibilityCheckedAt": instrument["checkedAt"],
        "fundingRate": rate, "fundingRatePercent": percent,
        "fundingRatePercent8h": normalized, "fundingIntervalHours": period,
        "annualizedPercent": percent * 24 / period * 365 if period else None,
        "rateKind": "latest-rate", "direction": funding_direction(rate),
        "quoteObservedAt": quote_at, "sourceResponseAt": response_at,
        "timeBasis": "quote-time" if quote_at else "provider-response",
        "updatedAt": clock, "fetchedAt": fetched_at, "acquisitionState": "ok",
        "nextFundingTime": next_at,
        "markPrice": number(raw.get("markPrice")), "indexPrice": number(raw.get("indexPrice")),
        "sourceUrl": ("https://www.binance.com/en/futures/funding-history" if exchange == "Binance"
                      else "https://www.bybit.com/en/announcement-info/fund-rate/"),
    }


def group_assets(quotes: list[dict], *, markets: dict[str, dict], order: list[str], now: str) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    for quote in quotes:
        grouped.setdefault(quote["asset"], []).append(quote)
    rows = []
    for asset, values in grouped.items():
        fresh = [q for q in values if q.get("acquisitionState") == "ok" and current(q.get("updatedAt"), now)]
        comparable = [q for q in fresh if number(q.get("fundingRatePercent8h")) is not None]
        rates = [q["fundingRatePercent8h"] for q in comparable]
        strongest = max(comparable, key=lambda q: abs(q["fundingRatePercent8h"]), default=None)
        positive, negative = any(r > 0 for r in rates), any(r < 0 for r in rates)
        relation = markets.get(asset, {})
        rows.append({
            "id": asset, "asset": asset, "symbol": asset, "quotes": values,
            "venues": len({q["exchange"] for q in values}), "freshVenues": len(fresh),
            "bias": "mixed" if positive and negative else "longs-pay" if positive else "shorts-pay" if negative else "flat" if rates else "unknown",
            "consensusFundingPercent8h": sum(rates) / len(rates) if rates else None,
            "strongestFundingPercent8h": strongest["fundingRatePercent8h"] if strongest else None,
            "strongestVenue": strongest["exchange"] if strongest else None,
            "spreadPercent8h": max(rates) - min(rates) if len(rates) >= 2 else None,
            "maxAbsFundingPercent": max((abs(q["fundingRatePercent"]) for q in fresh), default=None),
            "calculationBasis": "simple-mean-of-fresh-rates-normalized-to-8h",
            "status": "stale" if not fresh else "degraded" if len(fresh) != len(values) or len(comparable) != len(fresh) else "ok",
            "marketCount": relation.get("marketCount", 0), "priceMarketCount": relation.get("priceMarketCount", 0),
            "relatedMarkets": relation.get("relatedMarkets", []),
        })
    priority = {asset: index for index, asset in enumerate(order)}
    rows.sort(key=lambda row: (0 if row["priceMarketCount"] else 1 if row["marketCount"] else 2,
                               priority.get(row["asset"], 999), row["asset"]))
    return rows
