"""Calendar-bound macro calculations; never compare incompatible movement units."""
from __future__ import annotations

import calendar
import math
from datetime import date, datetime
from typing import Any

QUARTERLY = {"GDPC1", "IMPGS", "EXPGS", "USSTHPI"}
WEEKLY = {"ICSA", "CCSA"}
DAILY = {"DFF", "SOFR", "DGS2", "DGS3MO", "DGS5", "DGS10", "DGS30", "T10Y2Y", "DFEDTARU", "DFEDTARL"}
NSA = {"PPIACO", "CSUSHPINSA", "CPIAUCNS", "CPILFENS", "IR", "IQ"}


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def month_key(value: Any) -> str | None:
    text = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y-%m", "%B %Y", "%b %Y", "%B, %Y"):
        try:
            return datetime.strptime(text[:10] if fmt == "%Y-%m-%d" else text, fmt).strftime("%Y-%m")
        except ValueError:
            pass
    return None


def shift_month(period: str, offset: int) -> str:
    year, month = map(int, period.split("-"))
    index = year * 12 + month - 1 + offset
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def monthly_metric(observations: list[dict], period: str | None, metric: str) -> float | None:
    if not period:
        return None
    values = {month_key(row.get("date")): number(row.get("value")) for row in observations}
    current, previous = values.get(period), values.get(shift_month(period, -12 if metric == "yoy" else -1))
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1) * 100


def series_contract(spec: dict) -> dict:
    series = spec["seriesId"]
    frequency = "quarterly" if series in QUARTERLY else "weekly" if series in WEEKLY else "daily" if series in DAILY else "monthly"
    adjustment = "NSA" if series in NSA or series.startswith("CUUR") else "not applicable" if frequency == "daily" else "SA"
    if series == "USSTHPI":
        adjustment = "NSA"
    unit = "persons" if series in WEEKLY else spec.get("unit")
    return {"frequency": frequency, "adjustment": adjustment, "unit": unit,
            "contextOnly": series in {"IMPGS", "EXPGS", "CSUSHPINSA", "USSTHPI"},
            "levelBasis": "annual rate" if series in {"GDPC1", "IMPGS", "EXPGS", "PCE", "PCEC96", "DSPIC96", "HOUST", "PERMIT"} else None}


def value_label(value: Any, unit: str | None) -> str:
    value = number(value)
    if value is None:
        return "--"
    if unit == "k":
        return f"{value / 1000:,.3f}M" if abs(value) >= 1000 else f"{value:,.1f}K"
    if unit == "persons":
        return f"{value:,.0f} persons"
    if unit in {"bil", "mil"}:
        return f"${value:,.1f}{'B' if unit == 'bil' else 'M'}"
    if unit and unit.startswith("$"):
        return f"${value:,.2f}{unit[1:]}"
    return f"{value:,.2f}{'%' if unit == '%' else ' pp' if unit == 'pp' else ' index' if unit == 'idx' else ' hours' if unit == 'hrs' else ''}"


def describe_series(spec: dict, observations: list[dict], fetched_at: str) -> dict:
    contract = series_contract(spec)
    latest, previous = observations[-1], observations[-2]
    frequency, unit = contract["frequency"], contract["unit"]
    period = month_key(latest["date"])
    previous_period = month_key(previous["date"])
    adjacent = frequency not in {"monthly", "quarterly"} or previous_period == shift_month(period, -3 if frequency == "quarterly" else -1)
    delta = latest["value"] - previous["value"] if adjacent else None
    pct = (latest["value"] / previous["value"] - 1) * 100 if adjacent and previous["value"] else None
    window = {"monthly": "MoM", "quarterly": "QoQ", "weekly": "WoW", "daily": "vs prior observation"}[frequency]
    change, change_unit = delta, unit or "units"
    headline, headline_unit = latest["value"], unit
    label = spec["label"]
    if spec["seriesId"] == "GDPC1":
        change = ((latest["value"] / previous["value"]) ** 4 - 1) * 100 if pct is not None and previous["value"] > 0 else None
        headline, headline_unit = change, "%"
        label = "Real GDP growth (QoQ annualized)"
        change_unit, window = "%", "QoQ annualized"
    elif spec["seriesId"] == "PAYEMS":
        headline = delta
        label = "Nonfarm payrolls monthly change"
        change_unit = "K persons"
    elif unit in {"%", "pp"}:
        change_unit = "bp" if frequency == "daily" else "pp"
        change = delta * 100 if delta is not None and change_unit == "bp" else delta
    elif spec.get("metric") == "pct":
        change, change_unit = pct, "%"
    elif unit == "k":
        change_unit = "K persons"
    if frequency == "quarterly":
        year, month = map(int, period.split("-"))
        period_label = f"{year} Q{(month - 1) // 3 + 1}"
    elif frequency == "monthly":
        year, month = map(int, period.split("-"))
        period_label = f"{calendar.month_name[month]} {year}"
    else:
        period_label = latest["date"]
    return {**contract, "label": label, "valueLabel": value_label(headline, headline_unit),
            "changeValue": round(change, 3) if change is not None else None,
            "changeUnit": change_unit, "changeWindow": window,
            "changeLabel": f"{change:+.2f} {change_unit} {window}" if change is not None else "Change unavailable (missing period)",
            "periodLabel": period_label, "fetchedAt": fetched_at, "publishedAt": None,
            "levelLabel": value_label(latest["value"], unit), "yoyPct": monthly_metric(observations, period, "yoy") if frequency == "monthly" else None,
            "change": round(delta, 3) if delta is not None else None,
            "changePct": round(pct, 3) if pct is not None else None}
