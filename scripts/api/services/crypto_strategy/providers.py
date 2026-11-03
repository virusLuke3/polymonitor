"""Bounded public source adapters; only called by the seed worker."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import time

from .contracts import ASSETS, basis, depth, iso, number, option_bands, points, trade_sample


def bybit(get, base, endpoint, **params):
    value = get(base + "/v5/market/" + endpoint, params=params)
    if not isinstance(value, dict) or value.get("retCode") != 0 or not isinstance(value.get("result"), dict):
        raise ValueError("BYBIT_RESPONSE_INVALID")
    return value


def venue_asset(get, base, asset, now, cadence=None):
    symbol = asset + "USDT"
    result = {"asset": asset, "venue": "Bybit", "symbol": symbol, "quoteCurrency": "USDT", "errors": {}}

    def read(key, endpoint, **params):
        def fetch():
            value = bybit(get, base, endpoint, symbol=symbol, **params)
            if endpoint == "kline":
                # Never let a cached, still-forming candle become a completed
                # candle merely because wall time crossed its closing time.
                value = {**value, "result": {**value["result"], "list": [
                    row for row in value["result"].get("list", [])
                    if isinstance(row, list) and row and number(row[0]) is not None
                    and number(row[0]) + 60_000 <= now
                ]}}
            return value
        try:
            interval_ms = {"kline": 60_000, "open-interest": 300_000, "funding/history": 900_000}.get(endpoint)
            if cadence is not None and interval_ms:
                return cadence.read((base, asset, key), now, interval_ms,
                                    fetch)
            return fetch()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result["errors"][key] = type(exc).__name__
            return None

    for category in ("spot", "linear"):
        value = read(category, "tickers", category=category)
        if value and value["result"].get("list"):
            raw = next((r for r in value["result"]["list"] if r.get("symbol") == symbol), {})
            result[category] = {"price": number(raw.get("lastPrice")), "bid": number(raw.get("bid1Price")),
                "ask": number(raw.get("ask1Price")), "sourceResponseAt": iso(value.get("time")),
                "mark": number(raw.get("markPrice")), "index": number(raw.get("indexPrice")),
                "oi": number(raw.get("openInterest")), "oiValue": number(raw.get("openInterestValue")),
                "fundingPercent": (number(raw.get("fundingRate")) * 100) if number(raw.get("fundingRate")) is not None else None}
        bars = read(category + "Bars", "kline", category=category, interval="1", limit=180)
        if bars:
            result[category + "History"] = [{"t": int(r[0]) + 60000, "v": float(r[4])}
                for r in reversed(bars["result"].get("list", []))
                if isinstance(r, list) and len(r) >= 5 and number(r[0]) is not None
                and number(r[0]) + 60000 <= now and (number(r[4]) or 0) > 0]
    spot, perp = result.get("spot", {}), result.get("linear", {})
    clocks = [datetime.fromisoformat(q["sourceResponseAt"]).timestamp() * 1000
              for q in (spot, perp) if q.get("sourceResponseAt")]
    aligned = len(clocks) == 2 and abs(clocks[0] - clocks[1]) <= 5000 and all(now - 90000 <= t <= now + 60000 for t in clocks)
    result["basisBps"] = basis(perp.get("mark"), spot.get("price")) if aligned else None
    result["basisClockSkewMs"] = abs(clocks[0] - clocks[1]) if len(clocks) == 2 else None
    result["premiumBps"] = basis(perp.get("mark"), perp.get("index"))
    result["basisMethod"] = "Bybit mark / Bybit spot last; separate REST responses"
    value = read("oiHistory", "open-interest", category="linear", intervalTime="5min", limit=100)
    if value:
        result["oiHistory"] = points(value["result"].get("list", []), "timestamp", "openInterest")
    value = read("fundingHistory", "funding/history", category="linear", limit=100)
    if value:
        result["fundingHistory"] = [{"t": p["t"], "v": p["v"] * 100}
            for p in points(value["result"].get("list", []), "fundingRateTimestamp", "fundingRate")]
    value = read("flow", "recent-trade", category="spot", limit=60)
    if value:
        result["flow"] = trade_sample(value["result"].get("list", []), limit=60)
        result["flow"]["receivedAt"] = iso(time.time() * 1000)
    value = read("depth", "orderbook", category="spot", limit=50)
    if value:
        result["depth"] = depth(value["result"])
    result["status"] = "partial" if result["errors"] else "ok"
    return result


def options(get, asset, now):
    base = "https://www.deribit.com/api/v2/public/"
    instrument_payload = get(base + "get_instruments", params={"currency": asset, "kind": "option", "expired": "false"})
    quote_payload = get(base + "get_book_summary_by_currency", params={"currency": asset, "kind": "option"})
    if "error" in instrument_payload or "error" in quote_payload:
        raise ValueError("DERIBIT_RESPONSE_INVALID")
    instruments = {i["instrument_name"]: i for i in instrument_payload["result"] if i.get("is_active")}
    observed = number(quote_payload.get("usOut"))
    return {"asset": asset, "source": "Deribit", "observedAt": iso(observed / 1000) if observed else iso(now),
            "clockBasis": "source-response" if observed else "received",
            "method": "call-spread / strike-width; discount factor assumed 1; band-averaged risk-neutral proxy",
            "pmExpiryMatched": False, "expiries": option_bands(quote_payload["result"], instruments, now)}


def references(get, url, now, lob_url=None):
    raw = get(url.rstrip("/") + "/crypto/reference")
    if raw.get("source") != "market-data" or raw.get("schemaVersion") != 1:
        raise ValueError("REFERENCE_OWNER_IDENTITY_INVALID")
    result = {}
    for asset in ASSETS:
        item = raw.get("assets", {}).get(asset, {})
        market = item.get("market") or {}
        valid = market.get("asset") == asset and (number(market.get("ends_at_ms")) or 0) > now
        valid = valid and (number(market.get("starts_at_ms")) or now + 1) <= now
        valid = valid and str(market.get("condition_id", "")).startswith("0x") and bool(market.get("rule_version"))
        valid = valid and market.get("rule_url", "").startswith("https://data.chain.link/")
        valid = valid and market.get("price_kind") == "twap" and market.get("window_seconds") == 60 and market.get("comparator") == ">="
        anchor = market.get("anchor") or {}
        if anchor.get("condition_id") != market.get("condition_id") or not (number(anchor.get("value")) or 0) > 0:
            market = {**market, "anchor": None}
        market_out = {k: market.get(k) for k in ("asset", "market_id", "condition_id", "slug", "outcomes", "starts_at_ms", "ends_at_ms",
            "rule_version", "rule_url", "price_kind", "window_seconds", "comparator", "anchor", "opening_alignment")} if valid else None
        prices = [p for p in item.get("prices", []) if p.get("price_kind") == "twap"
            and p.get("feed_id") == f"rtds:crypto_prices_twap_sixty:{asset.lower()}/usd"
            and p.get("window_seconds") == 60 and p.get("quote_currency") == "USD"
            and (number(p.get("value")) or 0) > 0
            and number(p.get("event_at_ms")) and p["event_at_ms"] <= now + 1000]
        latest = max(prices, key=lambda p: p["event_at_ms"]) if prices else {}
        latest_out = {k: latest.get(k) for k in ("value", "full_accuracy_value", "event_at_ms", "published_at_ms", "received_at_ms", "original_received_ns", "feed_id", "price_kind", "window_seconds", "precision")} if latest else {}
        quotes = {}
        if valid:
            for side, token in (market.get("outcomes") or {}).items():
                quote = (item.get("quotes") or {}).get(token) or {}
                bid, ask = number(quote.get("best_bid")), number(quote.get("best_ask"))
                received = number(quote.get("received_at_ms"))
                if quote.get("condition_id") == market["condition_id"] and quote.get("asset_id") == token and bid is not None and ask is not None and 0 <= bid <= ask <= 1 and received and now - 60000 <= received <= now + 1000:
                    quotes[side] = {"token": token, "bid": bid, "ask": ask, "observedAt": quote.get("book_observed_at"), "receivedAt": quote.get("received_at_ms"),
                        "quality": quote.get("quality"), "snapshotAt": quote.get("snapshot_at"),
                        "upstreamCompleteness": quote.get("upstream_completeness", "UNKNOWN")}
        result[asset] = {"market": market_out, "latest": latest_out, "history": points(prices, "event_at_ms", "value"),
            "spotHistory": points(item.get("binance", []), "event_at_ms", "value"), "quotes": quotes,
            "source": "market-data canonical market metadata and official TWAP archive",
            "error": item.get("read_error"), "marketError": item.get("market_error"),
            "status": "unsupported" if asset not in ("BTC", "ETH") else "ok" if latest and not item.get("read_error") and 0 <= now - latest["event_at_ms"] < 15000 else "stale" if latest else "unavailable",
            "windowModel": "UNAVAILABLE_RAW_WINDOW_OBSERVATIONS"}
    if lob_url:
        # Reuse the existing read-only market-data owner; never collect a book here.
        tokens = [token for ref in result.values() for side, token in (ref.get("market") or {}).get("outcomes", {}).items()
                  if side not in ref["quotes"] and isinstance(token, str) and token.isdecimal()]
        try:
            books = get(lob_url.rstrip("/") + "/runtime/lob/books", params={"tokens": ",".join(tokens)})["books"] if tokens else {}
            received = int(time.time() * 1000)
            for ref in result.values():
                for side, token in (ref.get("market") or {}).get("outcomes", {}).items():
                    envelope = books.get(token, {})
                    book = envelope.get("yes", {})
                    bid, ask = number(book.get("bestBid")), number(book.get("bestAsk"))
                    if envelope.get("source") != "market-data" or book.get("tokenId") != token or book.get("bookStatus") != "live" or book.get("continuity") is not True:
                        continue
                    heartbeat = datetime.fromisoformat(book["heartbeatAt"].replace("Z", "+00:00")).timestamp()*1000
                    deadline = datetime.fromisoformat(book["staleAfter"].replace("Z", "+00:00")).timestamp()*1000
                    if not 0 <= received-heartbeat <= 20000 or deadline <= received or bid is None or ask is None or not 0 <= bid <= ask <= 1:
                        continue
                    ref["quotes"][side] = {"token": token, "bid": bid, "ask": ask,
                        "observedAt": book.get("receivedAt"), "receivedAt": received, "source": "market-data native live book"}
        except (OSError, ValueError, TypeError, KeyError):
            pass  # Preserve independently available designated-source observations.
    return result


def stablecoins(get, now):
    result = []
    for symbol in ("USDC", "USDT"):
        for source, pair in (("Coinbase", symbol + "-USD"), ("Kraken", symbol + "USD")):
            try:
                if source == "Coinbase":
                    raw = get("https://api.coinbase.com/v2/prices/" + pair + "/spot")
                    value = number(raw["data"]["amount"])
                else:
                    raw = get("https://api.kraken.com/0/public/Ticker", params={"pair": pair})
                    if raw.get("error"):
                        raise ValueError("KRAKEN_PAIR_UNAVAILABLE")
                    value = number(next(iter(raw["result"].values()))["c"][0])
                if not value or value <= 0:
                    raise ValueError("INVALID_STABLECOIN_PRICE")
                result.append({"asset": symbol, "source": source, "price": value, "deviationBps": basis(value, 1),
                    "receivedAt": iso(time.time() * 1000), "clockBasis": "received; quote-native time unavailable", "status": "ok"})
            except (OSError, ValueError, TypeError, KeyError, StopIteration):
                result.append({"asset": symbol, "source": source, "price": None, "deviationBps": None, "status": "unavailable"})
    return result


def collect(get, *, bybit_base, reference_url, now, lob_url=None, cadence=None):
    jobs = {asset: lambda a=asset: venue_asset(get, bybit_base, a, now, cadence) for asset in ASSETS}
    jobs.update({"options:" + a: lambda a=a: options(get, a, now) for a in ("BTC", "ETH")})
    jobs["stablecoins"] = lambda: stablecoins(get, now)
    if cadence is not None:
        for key in ("options:BTC", "options:ETH", "stablecoins"):
            fetch = jobs[key]
            interval_ms = 60_000 if key == "stablecoins" else 300_000
            jobs[key] = lambda k=key, f=fetch, ms=interval_ms: cadence.read(k, now, ms, f)
    if reference_url:
        jobs["references"] = lambda: references(get, reference_url, now, lob_url)
    results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {key: pool.submit(call) for key, call in jobs.items()}
        for key, future in futures.items():
            try:
                results[key] = future.result()
            except (OSError, ValueError, TypeError, KeyError) as exc:
                results[key] = {"status": "unavailable", "error": type(exc).__name__}
    references_result = results.get("references", {})
    if "status" in references_result:
        references_result = {a: {"status": "unavailable"} for a in ASSETS}
    return {"schemaVersion": 1, "kind": "crypto-strategy", "generatedAt": iso(now), "collectedAt": now,
        "status": "partial", "assets": {a: results[a] for a in ASSETS},
        "references": references_result, "options": {a: results["options:" + a] for a in ("BTC", "ETH")},
        "stablecoins": results["stablecoins"] if isinstance(results["stablecoins"], list) else [],
        "inflows": {"mode": "unavailable", "reason": "LIVE_LABELED_EXCHANGE_FLOW_NOT_CONNECTED", "rows": []},
        "refreshIntervalSeconds": 30, "limitations": ["REST observation; no millisecond lead/lag claim", "Bybit spot trades are a bounded 60-trade sample; snapshot depth is not incremental OFI"]}
