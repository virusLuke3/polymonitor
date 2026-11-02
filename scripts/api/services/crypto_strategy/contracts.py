"""Source semantics and calculations. Unknown values never become zero."""
from __future__ import annotations

import math
from datetime import datetime, timezone

ASSETS = ("BTC", "ETH", "SOL", "XRP")


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def iso(ms):
    value = number(ms)
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat() if value else None


def basis(left, right):
    a, b = number(left), number(right)
    return (a / b - 1) * 10000 if a is not None and b and a > 0 and b > 0 else None


def points(rows, time_key, value_key):
    result = {}
    for row in rows:
        t, v = number(row.get(time_key)), number(row.get(value_key))
        if t and v is not None:
            result[t] = {"t": t, "v": v}
    return sorted(result.values(), key=lambda p: p["t"])[-900:]


def trade_sample(rows, *, limit):
    """A bounded trade sample, never a claim of complete interval flow."""
    seen, trades = set(), []
    for row in rows:
        identity = row.get("execId")
        price, size, at = number(row.get("price")), number(row.get("size")), number(row.get("time"))
        if not identity or identity in seen or price is None or price <= 0 or size is None or size <= 0 or not at or row.get("side") not in {"Buy", "Sell"}:
            continue
        seen.add(identity)
        trades.append({"id": identity, "t": at, "price": price, "size": size, "side": row["side"], "notional": price * size})
    trades.sort(key=lambda r: (r["t"], r["id"]))
    buy = sum(r["notional"] for r in trades if r["side"] == "Buy")
    sell = sum(r["notional"] for r in trades if r["side"] == "Sell")
    cumulative, curve = 0.0, []
    for row in trades:
        cumulative += row["notional"] * (1 if row["side"] == "Buy" else -1)
        curve.append({"t": row["t"], "v": cumulative})
    return {"buy": buy if trades else None, "sell": sell if trades else None,
            "net": buy - sell if trades else None, "count": len(trades), "limit": limit,
            "from": trades[0]["t"] if trades else None, "to": trades[-1]["t"] if trades else None,
            "coverage": "BOUNDED_SAMPLE", "cvd": curve[-300:], "trades": trades[-20:]}


def depth(raw):
    def side(key):
        result = []
        for row in raw.get(key, [])[:50]:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            p, q = number(row[0]), number(row[1])
            if p and p > 0 and q is not None and q > 0:
                result.append([p, q])
        return result
    bids, asks = sorted(side("b"), reverse=True), sorted(side("a"))
    crossed = bool(bids and asks and bids[0][0] >= asks[0][0])
    bid = sum(p * q for p, q in bids)
    ask = sum(p * q for p, q in asks)
    return {"bids": bids[:10], "asks": asks[:10], "levels": min(len(bids), len(asks)),
            "imbalance": (bid - ask) / (bid + ask) if bids and asks and bid + ask and not crossed else None,
            "status": "invalid-crossed-book" if crossed else "ok" if bids and asks else "unavailable",
            "observedAt": iso(raw.get("cts") or raw.get("ts")), "sequence": raw.get("seq"),
            "method": "notional-depth-imbalance-snapshot"}


def option_bands(rows, instruments, now_ms):
    """Call-spread price / strike width; undiscounted, band-averaged tail proxy.

    No tail extrapolation, synthetic quotes, constant-IV curve or PM expiry match.
    Bid/ask bounds are retained; crossed and non-monotone prices are rejected.
    """
    groups = {}
    for row in rows:
        meta = instruments.get(row.get("instrument_name"), {})
        expiry, strike = number(meta.get("expiration_timestamp")), number(meta.get("strike"))
        bid, ask, underlying = number(row.get("bid_price")), number(row.get("ask_price")), number(row.get("underlying_price"))
        if meta.get("option_type") != "call" or not expiry or not now_ms < expiry <= now_ms + 7 * 86400000:
            continue
        if not strike or strike <= 0 or bid is None or ask is None or bid < 0 or ask <= 0 or bid > ask or not underlying or underlying <= 0:
            continue
        if meta.get("quote_currency") not in {"BTC", "ETH"}:
            continue
        groups.setdefault(expiry, []).append({"strike": strike, "bid": bid * underlying, "ask": ask * underlying,
            "iv": number(row.get("mark_iv")), "instrument": row["instrument_name"], "underlying": underlying})
    result = []
    for expiry, quotes in sorted(groups.items())[:3]:
        quotes.sort(key=lambda q: q["strike"])
        bands = []
        for a, b in zip(quotes, quotes[1:]):
            width = b["strike"] - a["strike"]
            if width <= 0 or abs(a["underlying"] / b["underlying"] - 1) > .002:
                continue
            low, high = (a["bid"] - b["ask"]) / width, (a["ask"] - b["bid"]) / width
            mid = (low + high) / 2
            if not 0 <= mid <= 1 or high < 0 or low > 1:
                continue
            bands.append({"strike": (a["strike"] + b["strike"]) / 2, "lowerStrike": a["strike"],
                "upperStrike": b["strike"], "probability": mid, "low": max(0, low), "high": min(1, high),
                "iv": a["iv"], "instruments": [a["instrument"], b["instrument"]]})
        if bands:
            result.append({"expiry": iso(expiry), "underlying": quotes[0]["underlying"], "bands": bands[:80]})
    return result
