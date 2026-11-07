"""Weather-only catalog and official quote snapshots; API reads never acquire books."""
from __future__ import annotations

import copy
import math
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from data_sources import source_value

NAMESPACE = "snapshot:weather:markets"
STATE = "state:weather:markets"
CATALOG_KEY = "catalog-v1"
BOOKS_KEY = "books-v1"
RETAIN_SECONDS = 7200
LEASE_SECONDS = 90


def setting(name, default, minimum=1, maximum=86400):
    return max(minimum, min(maximum, int(source_value(name) or default)))


def iso(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, timezone.utc).isoformat().replace("+00:00", "Z")


def timestamp(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.timestamp() if parsed.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def publish(store, key, value, ttl=7200):
    if store.set(NAMESPACE, key, value, ttl) is False:
        raise RuntimeError("weather market snapshot publication rejected")


def read_catalog(store, now=None):
    now = time.time() if now is None else now
    value = store.get_stale(NAMESPACE, CATALOG_KEY) if store else None
    if not isinstance(value, dict):
        return {"status": "warming", "items": []}
    value = copy.deepcopy(value)
    success = timestamp(value.get("generatedAt"))
    limit = setting("POLYMONITOR_WEATHER_CATALOG_MAX_AGE_SECONDS", 900)
    if success is None or not 0 <= now - success < limit:
        return {**value, "status": "stale", "items": []}
    for city in value.get("items", []):
        today = datetime.fromtimestamp(now, ZoneInfo(city.get("timezone") or "UTC")).date().isoformat()
        groups = [group for group in city.get("markets", [])
                  if (not group.get("marketDate") or group["marketDate"] >= today)
                  and group.get("eventStatus") != "inactive"]
        city["markets"] = groups
        # A removed primary date must never keep its old token set.
        city["bins"] = []
        city["topBin"] = None
        if groups:
            city.update(groups[0])
        else:
            for key in ("eventSlug", "eventTitle", "eventStatus", "marketDate", "marketUrl"):
                city[key] = None
        city["todayDate"] = today
    return value


def catalog_tokens(catalog):
    return {str(row["yesTokenId"]): city["cityId"] for city in catalog.get("items", [])
            for group in city.get("markets", []) for row in group.get("bins", [])
            if row.get("yesTokenId") and row.get("marketStatus") != "inactive"}


def validate_book(raw, token, now, fresh_seconds):
    if not isinstance(raw, dict) or raw.get("asset_id") != token:
        raise ValueError("book identity mismatch")
    event = float(raw["timestamp"]) / 1000
    if not math.isfinite(event) or event <= 0 or event > now + 1:
        raise ValueError("invalid book source time")
    levels = {}
    for side in ("bids", "asks"):
        rows = raw.get(side)
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError("invalid book levels")
        prices = []
        for row in rows:
            price, size = float(row["price"]), float(row["size"])
            if not math.isfinite(price) or not 0 <= price <= 1 or not math.isfinite(size) or size <= 0:
                raise ValueError("invalid price or size")
            prices.append((price, size))
        levels[side] = [{"price": price, "size": size} for price, size in prices]
    bid = max((row["price"] for row in levels["bids"]), default=None)
    ask = min((row["price"] for row in levels["asks"]), default=None)
    if bid is not None and ask is not None and bid > ask:
        raise ValueError("crossed book")
    return {"tokenId": token, "bookStatus": "available", "source": "official-clob-rest",
            "upstreamReady": True, "continuity": False, "eventAt": iso(event), "observedAt": iso(now),
            "staleAfter": iso(now + fresh_seconds), "bestBid": bid, "bestAsk": ask,
            "bids": levels["bids"], "asks": levels["asks"], "hash": raw.get("hash"),
            "market": raw.get("market")}


def visible_book(book, token, now=None):
    now = time.time() if now is None else now
    empty = {"tokenId": token, "bookStatus": "unavailable", "bids": [], "asks": []}
    if not isinstance(book, dict) or book.get("tokenId") != token:
        return empty
    observed, event, deadline = (timestamp(book.get(k)) for k in ("observedAt", "eventAt", "staleAfter"))
    if observed is None or event is None or observed > now + 1 or event > now + 1:
        return empty
    if deadline and now < deadline and book.get("bookStatus") == "available":
        return book
    if 0 <= now - event < RETAIN_SECONDS:
        return {**book, "bookStatus": "stale", "upstreamReady": False}
    return {**empty, "bookStatus": "stale", "eventAt": book.get("eventAt"), "observedAt": book.get("observedAt")}


def quote_bin(row, books, now=None):
    book = visible_book(books.get(str(row.get("yesTokenId"))), str(row.get("yesTokenId")), now)
    bid, ask = book.get("bestBid"), book.get("bestAsk")
    current = book.get("bookStatus") == "available"
    has_price = bid is not None or ask is not None
    status = "snapshot" if current and has_price else "no-book" if current else "retained" if has_price else book["bookStatus"]
    return {**row, "bestBidYes": bid, "bestAskYes": ask,
            "midPriceYes": (bid + ask) / 2 if bid is not None and ask is not None else None,
            "bookStatus": status, "priceSource": "clob-snapshot" if current else "previous-book" if has_price else None,
            "quoteUpdatedAt": book.get("eventAt"), "quoteObservedAt": book.get("observedAt"),
            "quoteStaleAfter": book.get("staleAfter") if current else iso(timestamp(book["eventAt"]) + RETAIN_SECONDS) if has_price else None}


def read_books(store, tokens, now=None):
    """Only a bounded demand lease is written; no network or market DB read."""
    now = time.time() if now is None else now
    if not 1 <= len(tokens) <= 24 or any(not t.isdecimal() or len(t) > 100 for t in tokens):
        raise ValueError("Expected 1 to 24 numeric weather token ids")
    catalog = read_catalog(store, now)
    allowed = catalog_tokens(catalog)
    by_city = {}
    for token in tokens:
        if token in allowed:
            by_city.setdefault(allowed[token], []).append(token)
    for city, requested in by_city.items():
        key = "demand:" + city
        with store.fetch_lock(STATE, key, timeout=.2):
            old = store.get(STATE, key) or {}
            demands = {t: expiry for t, expiry in old.get("tokens", {}).items() if t in allowed and expiry > now}
            for token in requested:
                demands[token] = now + LEASE_SECONDS
            if store.set(STATE, key, {"tokens": demands}, LEASE_SECONDS, max_entries=70) is False:
                raise RuntimeError("weather demand publication rejected")
    saved = store.get_stale(NAMESPACE, BOOKS_KEY) or {}
    books = saved.get("books", {})
    return {"catalogAt": catalog.get("generatedAt"), "catalogStatus": catalog.get("status"),
            "lastAttemptAt": saved.get("lastAttemptAt"), "lastSuccessAt": saved.get("lastSuccessAt"),
            "books": {token: {"source": "official-clob-rest", "yes": visible_book(books.get(token), token, now) if token in allowed else
                               {"tokenId": token, "bookStatus": "inactive", "bids": [], "asks": []}}
                      for token in tokens}}


def overlay_weather(payload, store, now=None):
    """Pure join; forecast generation and source clocks remain untouched."""
    if store is None or not store.get_stale(NAMESPACE, CATALOG_KEY):
        return payload
    now = time.time() if now is None else now
    catalog = read_catalog(store, now)
    by_city = {c["cityId"]: c for c in catalog.get("items", [])}
    books = (store.get_stale(NAMESPACE, BOOKS_KEY) or {}).get("books", {})
    fields = ("eventSlug", "eventTitle", "eventStatus", "marketSource", "marketDate", "marketFamily",
              "marketFamilyLabel", "metricType", "marketUrl", "marketFetchedAt", "marketFamilies")
    items = []
    from .global_weather_map_service import _align_city_forecast, build_summary
    for old in payload.get("items", []):
        city = by_city.get(old["cityId"], {})
        groups = []
        for group in city.get("markets", []):
            bins = [quote_bin(row, books, now) for row in group.get("bins", [])]
            top = max(bins, key=lambda b: b.get("midPriceYes") if b.get("midPriceYes") is not None else -1, default=None)
            groups.append({**group, "bins": bins, "topBin": top,
                           "quoteCoverage": f"{sum(b['bookStatus'] == 'snapshot' for b in bins)}/{len(bins)}"})
        primary = groups[0] if groups else {}
        item = {**old, **{key: None for key in fields}, **{key: city.get(key) for key in fields}, **primary,
                "markets": groups, "bins": primary.get("bins", []), "topBin": primary.get("topBin"),
                "marketFetchedAt": catalog.get("generatedAt"), "catalogStatus": catalog.get("status"),
                "sourceStates": {**old.get("sourceStates", {}), "polymarket": catalog.get("status")}}
        items.append(_align_city_forecast(item))
    primary_bins = [row for city in items for row in city.get("bins", [])]
    acquired = sum(row.get("bookStatus") in {"snapshot", "no-book"} for row in primary_bins)
    quoted = sum(row.get("bookStatus") == "snapshot" for row in primary_bins)
    book_state = ("empty" if not primary_bins else
                  "ok" if acquired == len(primary_bins) and quoted else
                  "no-book" if acquired == len(primary_bins) else
                  "partial" if acquired else "unavailable")
    sources = {**payload.get("sources", {}), "marketDatabase": catalog.get("status"), "clob": book_state}
    status = payload.get("status")
    if status == "ok" and catalog.get("status") != "ok":
        status = "degraded"
    return {**payload, "status": status, "sources": sources, "items": items,
            "marketCatalogAt": catalog.get("generatedAt"), "marketCatalogStatus": catalog.get("status"),
            "summary": {**payload.get("summary", {}), **build_summary(items)}}
