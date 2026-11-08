"""Bounded public source adapters; only called by the seed worker."""
from __future__ import annotations

from data_sources import source_value

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation
import re
import time

from .contracts import ASSETS, basis, depth, iso, number, option_bands, points, trade_sample
from .cadence import source_error
from .cadence import SourceCadence

DERIBIT_BASE = source_value('POLYMONITOR_URL_WWW_DERIBIT_COM_API_V2_PUBLIC_99D260')


def bybit(get, base, endpoint, **params):
    value = get(base + "/v5/market/" + endpoint, params=params)
    if not isinstance(value, dict) or not isinstance(value.get("result"), dict):
        raise ValueError("BYBIT_RESPONSE_INVALID")
    if value.get("retCode") != 0:
        raise ValueError("BYBIT_RET_CODE_" + str(value.get("retCode")))
    return value


def venue_asset(get, base, asset, now, cadence=None, *, include_history=True, history_only=False):
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
                identity = (base, asset, key)
                value = cadence.read(identity, now, interval_ms, fetch)
                state = cadence.state(identity)
                result.setdefault("sourceStates", {})[key] = state
                if state["error"]:
                    result["errors"][key] = state["error"]
                return value
            return fetch()
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result["errors"][key] = source_error(exc)
            if cadence is not None and interval_ms:
                result.setdefault("sourceStates", {})[key] = cadence.state((base, asset, key))
            return None

    for category in (() if history_only else ("spot", "linear")):
        value = read(category, "tickers", category=category)
        if value and value["result"].get("list"):
            raw = next((r for r in value["result"]["list"] if r.get("symbol") == symbol), {})
            result[category] = {"price": number(raw.get("lastPrice")), "bid": number(raw.get("bid1Price")),
                "ask": number(raw.get("ask1Price")), "sourceResponseAt": iso(value.get("time")),
                "mark": number(raw.get("markPrice")), "index": number(raw.get("indexPrice")),
                "oi": number(raw.get("openInterest")), "oiValue": number(raw.get("openInterestValue")),
                "fundingPercent": (number(raw.get("fundingRate")) * 100) if number(raw.get("fundingRate")) is not None else None}
    spot, perp = result.get("spot", {}), result.get("linear", {})
    clocks = [datetime.fromisoformat(q["sourceResponseAt"]).timestamp() * 1000
              for q in (spot, perp) if q.get("sourceResponseAt")]
    aligned = len(clocks) == 2 and abs(clocks[0] - clocks[1]) <= 5000 and all(now - 90000 <= t <= now + 60000 for t in clocks)
    result["basisBps"] = basis(perp.get("mark"), spot.get("price")) if aligned else None
    result["basisClockSkewMs"] = abs(clocks[0] - clocks[1]) if len(clocks) == 2 else None
    result["premiumBps"] = basis(perp.get("mark"), perp.get("index"))
    result["basisMethod"] = "Bybit mark / Bybit spot last; separate REST responses"
    value = None if history_only else read("flow", "recent-trade", category="spot", limit=60)
    if value:
        result["flow"] = trade_sample(value["result"].get("list", []), limit=60)
        result["flow"]["receivedAt"] = iso(time.time() * 1000)
    value = None if history_only else read("depth", "orderbook", category="spot", limit=50)
    if value:
        result["depth"] = depth(value["result"])
    if include_history:
        for category in ("spot", "linear"):
            bars = read(category + "Bars", "kline", category=category, interval="1", limit=180)
            if bars:
                result[category + "History"] = [{"t": int(r[0]) + 60000, "v": float(r[4])}
                    for r in reversed(bars["result"].get("list", []))
                    if isinstance(r, list) and len(r) >= 5 and number(r[0]) is not None
                    and number(r[0]) + 60000 <= now and (number(r[4]) or 0) > 0]
        value = read("oiHistory", "open-interest", category="linear", intervalTime="5min", limit=100)
        if value:
            result["oiHistory"] = points(value["result"].get("list", []), "timestamp", "openInterest")
        value = read("fundingHistory", "funding/history", category="linear", limit=100)
        if value:
            result["fundingHistory"] = [{"t": p["t"], "v": p["v"] * 100}
                for p in points(value["result"].get("list", []), "fundingRateTimestamp", "fundingRate")]
    result["status"] = "partial" if result["errors"] else "ok"
    return result


def options(get, asset, now):
    base = DERIBIT_BASE
    instrument_payload = get(base + "get_instruments", params={"currency": asset, "kind": "option", "expired": "false"})
    quote_payload = get(base + "get_book_summary_by_currency", params={"currency": asset, "kind": "option"})
    if "error" in instrument_payload or "error" in quote_payload:
        raise ValueError("DERIBIT_RESPONSE_INVALID")
    instruments = {i["instrument_name"]: i for i in instrument_payload["result"] if i.get("is_active")}
    observed = number(quote_payload.get("usOut"))
    bands = option_bands(quote_payload["result"], instruments, now)
    if not instruments or not bands:
        raise ValueError("DERIBIT_NO_VALID_OPTION_BANDS")
    return {"asset": asset, "source": "Deribit", "observedAt": iso(observed / 1000) if observed else iso(now),
            "clockBasis": "source-response" if observed else "received",
            "method": "call-spread / strike-width; discount factor assumed 1; band-averaged risk-neutral proxy",
            "pmExpiryMatched": False, "expiries": bands}


def _reference_point_valid(point, asset, now):
    try:
        value = Decimal(str(point.get("value")))
        exact = int(point.get("full_accuracy_value"))
        observed, published, received = (point.get(k) for k in ("event_at_ms", "published_at_ms", "received_at_ms"))
        return (value.is_finite() and value > 0 and value == Decimal(exact).scaleb(-18)
                and point.get("feed_id") == f"rtds:crypto_prices_twap_sixty:{asset.lower()}/usd"
                and point.get("price_kind") == "twap" and point.get("window_seconds") == 60
                and point.get("quote_currency") == "USD"
                and all(type(t) is int for t in (observed, published, received))
                and 0 < observed <= published <= received <= now + 1000)
    except (TypeError, ValueError, InvalidOperation):
        return False


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
        start = now // 300000 * 300000
        valid = valid and market.get("starts_at_ms") == start and market.get("ends_at_ms") == start + 300000
        valid = valid and market.get("slug") == f"{asset.lower()}-updown-5m-{start // 1000}"
        valid = valid and bool(re.fullmatch(r"0x[0-9a-fA-F]{64}", str(market.get("condition_id", "")))) and bool(market.get("rule_version"))
        rule_root = source_value('POLYMONITOR_URL_DATA_CHAIN_LINK_C3DCEB').rstrip('/')
        valid = valid and market.get("rule_url") == f"{rule_root}/streams/{asset.lower()}-usd-twap-60s-streams"
        outcomes = market.get("outcomes") or {}
        valid = valid and set(outcomes) == {"UP", "DOWN"} and len(set(outcomes.values())) == 2
        valid = valid and all(str(t).isdigit() and 0 < int(t) < 2**256 for t in outcomes.values())
        valid = valid and market.get("price_kind") == "twap" and market.get("window_seconds") == 60 and market.get("comparator") == ">="
        anchor = market.get("anchor") or {}
        if (anchor.get("condition_id") != market.get("condition_id") or anchor.get("event_at_ms") != start
                or not _reference_point_valid(anchor, asset, now)):
            market = {**market, "anchor": None}
        market_out = {k: market.get(k) for k in ("asset", "market_id", "condition_id", "slug", "outcomes", "starts_at_ms", "ends_at_ms",
            "rule_version", "rule_url", "price_kind", "window_seconds", "comparator", "anchor", "opening_alignment")} if valid else None
        prices = [p for p in item.get("prices", []) if _reference_point_valid(p, asset, now)]
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
            "status": "ok" if latest and not item.get("read_error") and 0 <= now - latest["event_at_ms"] < 15000 else "stale" if latest else "unavailable",
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


def stablecoins(get, now, cadence=None):
    result = []
    for symbol in ("USDC", "USDT"):
        for source, pair in (("Coinbase", symbol + "-USD"), ("Kraken", symbol + "USD")):
            identity = ("stablecoin", symbol, source)
            def fetch():
                if source == "Coinbase":
                    raw = get(source_value('POLYMONITOR_URL_API_COINBASE_COM_V2_PRICES_771506') + pair + "/spot")
                    value = number(raw["data"]["amount"])
                else:
                    raw = get(source_value('POLYMONITOR_URL_API_KRAKEN_COM_0_PUBLIC_TICKER_C10C94'), params={"pair": pair})
                    if raw.get("error"):
                        raise ValueError("KRAKEN_PAIR_UNAVAILABLE")
                    ticker = next(iter(raw.get("result", {}).values()), None)
                    if not isinstance(ticker, dict):
                        raise ValueError("KRAKEN_EMPTY_TICKER")
                    value = number(ticker["c"][0])
                if not value or value <= 0:
                    raise ValueError("INVALID_STABLECOIN_PRICE")
                return {"asset": symbol, "source": source, "price": value, "deviationBps": basis(value, 1),
                    "receivedAt": iso(time.time() * 1000), "clockBasis": "received; quote-native time unavailable", "status": "ok"}
            try:
                row = cadence.read(identity, now, 60_000, fetch, retain_ms=300_000) if cadence else fetch()
                if cadence:
                    state = cadence.state(identity)
                    row.update(status=state["status"], sourceState=state, error=state["error"])
                result.append(row)
            except (OSError, ValueError, TypeError, KeyError, StopIteration) as exc:
                result.append({"asset": symbol, "source": source, "price": None, "deviationBps": None,
                               "status": "unavailable", "error": source_error(exc)})
    return result


def collect(get, *, bybit_base, reference_url, now, lob_url=None, cadence=None, fast_only=False):
    if fast_only:
        jobs = {asset: lambda a=asset: venue_asset(get, bybit_base, a, now, cadence, include_history=False) for asset in ASSETS}
    else:
        jobs = {asset: lambda a=asset: venue_asset(get, bybit_base, a, now, cadence) for asset in ASSETS}
    jobs.update({"options:" + a: lambda a=a: options(get, a, now) for a in ("BTC", "ETH")})
    jobs["stablecoins"] = lambda: stablecoins(get, now, cadence)
    if cadence is not None:
        history_cadence = SourceCadence(cadence.entries, read_only=True) if fast_only else cadence
        for key in ("options:BTC", "options:ETH"):
            fetch = jobs[key]
            interval_ms = 60_000 if key == "stablecoins" else 300_000
            identity = (DERIBIT_BASE, key.split(":")[1], "options") if key.startswith("options:") else key
            jobs[key] = lambda k=identity, f=fetch, ms=interval_ms, c=history_cadence: c.read(k, now, ms, f)
    if reference_url:
        jobs["references"] = lambda: references(get, reference_url, now, lob_url)
    results = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {key: pool.submit(call) for key, call in jobs.items()}
        for key, future in futures.items():
            try:
                results[key] = future.result()
            except (OSError, ValueError, TypeError, KeyError) as exc:
                results[key] = {"status": "unavailable", "error": source_error(exc)}
    if fast_only and cadence is not None:
        cached = SourceCadence(cadence.entries, read_only=True)
        for asset in ASSETS:
            history = venue_asset(None, bybit_base, asset, now, cached, history_only=True)
            results[asset].update({key: value for key, value in history.items()
                                  if key.endswith("History") or key == "sourceStates"})
            results[asset].setdefault("errors", {}).update(history["errors"])
            results[asset]["status"] = "partial" if results[asset]["errors"] else "ok"
    for asset in ("BTC", "ETH"):
        key = "options:" + asset
        row = results[key]
        if cadence is not None:
            state = (history_cadence if fast_only else cadence).state((DERIBIT_BASE, asset, "options"))
            row.update(sourceState=state, status=state["status"], error=state["error"])
        # A retained quote cannot keep an already settled contract alive.
        if "expiries" in row:
            row["expiries"] = [e for e in row["expiries"]
                               if datetime.fromisoformat(e["expiry"]).timestamp() * 1000 > now]
    references_result = results.get("references", {})
    if "status" in references_result:
        references_result = {a: {"status": "unavailable"} for a in ASSETS}
    retained = any(v.get("sourceState", {}).get("retained") for k, v in results.items() if k.startswith("options:"))
    retained = retained or any(s.get("retained") for a in ASSETS for s in results[a].get("sourceStates", {}).values())
    stable_rows = results["stablecoins"] if isinstance(results["stablecoins"], list) else []
    retained = retained or any(row.get("sourceState", {}).get("retained") for row in stable_rows)
    incomplete = any(results[a].get("errors") or results[a].get("status") != "ok" for a in ASSETS)
    incomplete = incomplete or any(results["options:" + a].get("status") == "unavailable" or results["options:" + a].get("error") for a in ("BTC", "ETH"))
    incomplete = incomplete or len(stable_rows) < 4 or any(row.get("status") != "ok" for row in stable_rows)
    return {"schemaVersion": 1, "kind": "crypto-strategy", "generatedAt": iso(now), "collectedAt": now,
        "status": "stale" if retained else "partial" if incomplete else "ok", "assets": {a: results[a] for a in ASSETS},
        "references": references_result, "options": {a: results["options:" + a] for a in ("BTC", "ETH")},
        "stablecoins": results["stablecoins"] if isinstance(results["stablecoins"], list) else [],
        "inflows": {"mode": "unavailable", "reason": "LIVE_LABELED_EXCHANGE_FLOW_NOT_CONNECTED", "rows": []},
        "refreshIntervalSeconds": 30, "limitations": ["REST observation; no millisecond lead/lag claim", "Bybit spot trades are a bounded 60-trade sample; snapshot depth is not incremental OFI"]}
