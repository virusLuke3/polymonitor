from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Callable, Dict

from api.context import resolve_optional_service_callable, resolve_service_callable
from .crypto_funding import contracts, providers, universe

CRYPTO_FUNDING_NAMESPACE = "snapshot:crypto:funding-watch"
DEFAULT_CRYPTO_FUNDING_LIMIT = contracts.DEFAULT_LIMIT
CATALOG_NAMESPACE = "snapshot:crypto:funding-catalog"
UNIVERSE_NAMESPACE = "snapshot:crypto:funding-universe"

@dataclass(frozen=True)
class CryptoFundingDependencies:
    settings: Any
    application: Any
    http_json_get: Callable[..., Any]
    utc_now_iso: Callable[..., Any]
    snapshot_store: Any
    get_cached_json: Callable[..., Any] | None
    set_cached_json: Callable[..., Any] | None
    get_snapshot_payload: Callable[..., Any] | None
    executor: Any = None
    market_executor: Any = None
    market_jobs: Any = None

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> CryptoFundingDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            settings=context.get("SETTINGS"),
            application=context.get("app"),
            http_json_get=resolve_service_callable(context, "http_json_get"),
            utc_now_iso=resolve_service_callable(context, "utc_now_iso"),
            snapshot_store=context.get("SNAPSHOT_STORE"),
            get_cached_json=resolve_optional_service_callable(
                context,
                "get_cached_json",
            ),
            set_cached_json=resolve_optional_service_callable(
                context,
                "set_cached_json",
            ),
            get_snapshot_payload=resolve_optional_service_callable(
                context,
                "get_snapshot_payload",
            ),
            executor=context.get("funding_executor"),
            market_executor=context.get("funding_market_executor"),
            market_jobs=context.get("funding_market_jobs"),
        )

    @property
    def logger(self) -> Any:
        return getattr(self.application, "logger", None)


CryptoFundingContext = Mapping[str, Any] | CryptoFundingDependencies


def _dependencies(
    context: CryptoFundingContext,
) -> CryptoFundingDependencies:
    if isinstance(context, CryptoFundingDependencies):
        return context
    return CryptoFundingDependencies.from_context(context)



def build_crypto_funding_cache_key(settings: Any, *, limit: int = DEFAULT_CRYPTO_FUNDING_LIMIT) -> str:
    # One canonical seed; limit is presentation, not a different acquisition.
    return json.dumps({"version": contracts.SCHEMA_VERSION,
        "symbols": sorted(str(value) for value in settings.crypto_funding_watch_symbols),
        "venues": [settings.crypto_funding_watch_api_url, settings.crypto_funding_watch_bybit_api_url]}, sort_keys=True)


def _cached(dependencies: CryptoFundingDependencies, namespace: str, key: str) -> dict | None:
    try:
        value = dependencies.get_cached_json(namespace, key) if dependencies.get_cached_json else None
        if isinstance(value, dict):
            return value
    except Exception:
        pass
    if dependencies.snapshot_store is not None:
        value = dependencies.snapshot_store.get_stale(namespace, key)
        if isinstance(value, dict):
            return value
    return None


def _store(dependencies: CryptoFundingDependencies, namespace: str, key: str, value: dict, ttl: int) -> None:
    if dependencies.snapshot_store is not None:
        dependencies.snapshot_store.set(namespace, key, value, ttl)
    if dependencies.set_cached_json is not None:
        dependencies.set_cached_json(namespace, key, value, ttl)


def catalog_key(exchange: str, url: str) -> str:
    return exchange.lower() + ":" + hashlib.sha256(str(url).encode()).hexdigest()[:16]


def _market_universe(dependencies: CryptoFundingDependencies, catalogs: dict[str, dict], now: str) -> dict:
    base = str(getattr(dependencies.settings, "gamma_api_base", "") or "")
    key = hashlib.sha256(base.encode()).hexdigest()[:16]
    cached = _cached(dependencies, UNIVERSE_NAMESPACE, key) or {}
    if contracts.current(cached.get("observedAt"), now, universe.UNIVERSE_SECONDS):
        return cached
    if cached.get("status") != "ok" and contracts.current(cached.get("attemptedAt"), now, 120):
        return cached
    if dependencies.market_executor is not None:
        pending = dependencies.market_jobs.get(key)
        if pending is None or pending.done():
            dependencies.market_jobs[key] = dependencies.market_executor.submit(
                _refresh_market_universe, dependencies, catalogs, now, key, base, cached)
        retained = contracts.current(cached.get("observedAt"), now, universe.UNIVERSE_SECONDS * 2)
        return {**cached, "status": "stale" if retained else "warming", "assets": cached.get("assets", {}) if retained else {}}
    return _refresh_market_universe(dependencies, catalogs, now, key, base, cached)


def _refresh_market_universe(dependencies: CryptoFundingDependencies, catalogs: dict[str, dict], now: str, key: str, base: str, cached: dict) -> dict:
    eligible = {item["asset"] for catalog in catalogs.values() for item in catalog.get("instruments", {}).values()}
    try:
        value = universe.discover_markets(dependencies.http_json_get, base_url=base, eligible_assets=eligible, now=now,
                                         clock=dependencies.utc_now_iso)
        if value["status"] == "ok":
            _store(dependencies, UNIVERSE_NAMESPACE, key, value, universe.UNIVERSE_SECONDS)
        return value
    except Exception as exc:
        # Failed discovery must not block funding. Old associations are labelled
        # and never make a current-coverage claim.
        retained = contracts.current(cached.get("observedAt"), now, universe.UNIVERSE_SECONDS * 2)
        value = {**cached, "status": "stale" if retained else "unavailable", "assets": cached.get("assets", {}) if retained else {},
                 "errorCode": type(exc).__name__, "attemptedAt": now}
        _store(dependencies, UNIVERSE_NAMESPACE, key, value, 120)
        return value


def fetch_live_crypto_funding_watch_payload(ctx: CryptoFundingContext, limit: int = DEFAULT_CRYPTO_FUNDING_LIMIT,
                                           previous: dict | None = None) -> dict:
    dependencies = _dependencies(ctx)
    now = dependencies.utc_now_iso()
    urls = {"Binance": dependencies.settings.crypto_funding_watch_api_url,
            "Bybit": dependencies.settings.crypto_funding_watch_bybit_api_url}
    pool = dependencies.executor or ThreadPoolExecutor(max_workers=2, thread_name_prefix="funding-venue")
    futures = {}
    for exchange, url in urls.items():
        key = catalog_key(exchange, url)
        cached = _cached(dependencies, CATALOG_NAMESPACE, key)
        futures[pool.submit(providers.collect_venue, exchange, url=url, get=dependencies.http_json_get, now=now,
                            clock=dependencies.utc_now_iso,
                            cached_catalog=cached, save_catalog=lambda value, key=key: _store(dependencies,
                                CATALOG_NAMESPACE, key, value, contracts.CATALOG_SECONDS))] = exchange
    done, pending = wait(futures, timeout=providers.SOURCE_BUDGET_SECONDS + 1)
    results = {}
    for future in done:
        exchange = futures[future]
        try:
            results[exchange] = future.result()
        except Exception as exc:
            results[exchange] = {"status": "error", "catalogStatus": "unavailable", "catalog": {},
                                 "quotes": [], "errorCode": type(exc).__name__}
    for future in pending:
        future.cancel()
        results[futures[future]] = {"status": "error", "catalogStatus": "unavailable", "catalog": {},
                                   "quotes": [], "errorCode": "venue-deadline"}
    if dependencies.executor is None:
        pool.shutdown(wait=False, cancel_futures=True)
    now = dependencies.utc_now_iso()
    catalogs = {name: result.get("catalog", {}) for name, result in results.items()}
    market_universe = _market_universe(dependencies, catalogs, now)
    now = dependencies.utc_now_iso()
    selected = universe.select_assets(catalogs, market_universe, dependencies.settings.crypto_funding_watch_symbols)
    selected_set = set(selected)
    previous = previous if isinstance(previous, dict) and previous.get("schemaVersion") == contracts.SCHEMA_VERSION else {}
    previous_quotes = {q["id"]: q for q in previous.get("items", []) if isinstance(q, dict) and q.get("id")}
    quotes: dict[str, dict] = {}
    expected_ids: set[str] = set()
    supported_assets: set[str] = set()
    source_details = {}
    for exchange in urls:
        result = results[exchange]
        catalog = catalogs[exchange].get("instruments", {})
        canonical: dict[str, str] = {}
        for symbol, row in catalog.items():
            if not row.get("eligible") or row["asset"] not in selected_set:
                continue
            asset = row["asset"]
            old_symbol = canonical.get(asset)
            if old_symbol is None or (symbol != asset + "USDT", len(symbol), symbol) < (old_symbol != asset + "USDT", len(old_symbol), old_symbol):
                canonical[asset] = symbol
        expected = {f"{exchange.lower()}:{symbol}" for symbol in canonical.values()}
        expected_ids.update(expected)
        supported_assets.update(row["asset"] for row in catalog.values() if row.get("eligible") and row["asset"] in selected_set)
        fresh = {q["id"]: q for q in result.get("quotes", []) if q["id"] in expected}
        quotes.update(fresh)
        retained = 0
        for quote_id, old in previous_quotes.items():
            if quote_id in quotes or old.get("exchange") != exchange or old.get("asset") not in selected_set:
                continue
            qualified = catalog.get(old.get("symbol"))
            if qualified is not None and not qualified.get("eligible"):
                continue
            if catalog and quote_id not in expected:
                continue
            if old.get("eligible") is not True or not contracts.current(old.get("updatedAt"), now, contracts.RETAIN_SECONDS):
                continue
            if not contracts.current(old.get("eligibilityCheckedAt"), now, contracts.CATALOG_RETAIN_SECONDS):
                continue
            quotes[quote_id] = {**old, "acquisitionState": "retained"}
            retained += 1
        state = result["status"]
        if state == "ok" and (expected - fresh.keys() or retained or result["catalogStatus"] != "ok"):
            state = "degraded"
        old_details = previous.get("sourceDetails", {}).get(exchange.lower(), {})
        source_details[exchange.lower()] = {"exchange": exchange, "status": state,
            "lastAttemptAt": now, "lastSuccessAt": result.get("fetchedAt") if fresh else old_details.get("lastSuccessAt"),
            "responseAt": result.get("responseAt"), "catalogStatus": result.get("catalogStatus"),
            "eligibilityCheckedAt": catalogs[exchange].get("checkedAt"),
            "expected": len(expected), "succeeded": len(fresh), "retained": retained,
            "missing": len(expected - fresh.keys() - quotes.keys()), "errorCode": result.get("errorCode")}
    fresh_quotes = [quote for quote in quotes.values() if quote.get("acquisitionState") == "ok"]
    generated = now if fresh_quotes else previous.get("generatedAt")
    assets = contracts.group_assets(list(quotes.values()), markets=market_universe.get("assets", {}), order=selected, now=now)
    missing = len(expected_ids - quotes.keys())
    retained_count = sum(q.get("acquisitionState") == "retained" for q in quotes.values())
    unknown_period = sum(q.get("fundingIntervalHours") is None for q in fresh_quotes)
    status = "ok" if fresh_quotes and not missing and not retained_count and not unknown_period and all(row["status"] == "ok" for row in source_details.values()) else "degraded" if fresh_quotes else "stale" if quotes else "unavailable"
    unavailable = []
    for asset in selected:
        if asset in supported_assets:
            continue
        known = all(result.get("catalogStatus") in {"ok", "retained"} for result in results.values())
        unavailable.append({"asset": asset, "reason": "no-trading-usdt-perpetual" if known else "eligibility-unknown",
                            "marketCount": market_universe.get("assets", {}).get(asset, {}).get("marketCount", 0)})
    return {"schemaVersion": contracts.SCHEMA_VERSION, "kind": "crypto-funding", "generatedAt": generated,
        "lastAttemptAt": now, "lastSuccessAt": now if fresh_quotes else previous.get("lastSuccessAt"),
        "status": status, "source": "binance/bybit-funding", "cacheMode": "seeded",
        "refreshIntervalSeconds": 30, "freshnessWindowSeconds": contracts.FRESH_SECONDS,
        "sources": {name: detail["status"] for name, detail in source_details.items()}, "sourceDetails": source_details,
        "venues": [name for name in urls if any(q["exchange"] == name for q in quotes.values())],
        "assets": assets, "items": list(quotes.values()),
        "coverage": {"requestedAssets": len(selected), "eligibleAssets": len(supported_assets),
                     "availableAssets": len(assets), "expectedQuotes": len(expected_ids), "succeeded": len(fresh_quotes),
                     "retained": retained_count, "missing": missing, "unknownPeriod": unknown_period,
                     "unavailableAssets": unavailable},
        "marketUniverse": {key: value for key, value in market_universe.items() if key != "assets"},
        "marketLinkedAssets": sum(row["marketCount"] > 0 for row in assets),
        "priceLinkedAssets": sum(row["priceMarketCount"] > 0 for row in assets),
        "limitations": ["Funding is perpetual cost context, not a Polymarket probability or settlement-price feed.",
                         "8h rates are linear time-normalized comparisons; future realized funding can change.",
                         "Market associations use a bounded active crypto scan, not complete market coverage."]}


def normalize_crypto_funding_payload(payload: Any, *, settings: Any, limit: int = DEFAULT_CRYPTO_FUNDING_LIMIT,
                                    generated_at: str | None = None) -> dict:
    if not isinstance(payload, dict) or payload.get("schemaVersion") != contracts.SCHEMA_VERSION:
        return {"schemaVersion": contracts.SCHEMA_VERSION, "kind": "crypto-funding", "generatedAt": None,
                "status": "warming", "assets": [], "items": [], "refreshIntervalSeconds": 30}
    assets = payload.get("assets", [])[:max(1, min(contracts.MAX_LIMIT, limit))]
    ids = {q["id"] for row in assets for q in row.get("quotes", [])}
    return {**payload, "assets": assets, "items": [q for q in payload.get("items", []) if q.get("id") in ids],
            "displayedAssets": len(assets), "totalAssets": len(payload.get("assets", []))}


def get_crypto_funding_watch_snapshot(ctx: CryptoFundingContext, limit: int = DEFAULT_CRYPTO_FUNDING_LIMIT) -> dict:
    """Serving is read-only and seed-first; it never waits on external venues."""
    dependencies = _dependencies(ctx)
    key = build_crypto_funding_cache_key(dependencies.settings)
    payload = _cached(dependencies, CRYPTO_FUNDING_NAMESPACE, key)
    mode = "seed"
    if not isinstance(payload, dict) or payload.get("schemaVersion") != contracts.SCHEMA_VERSION:
        return normalize_crypto_funding_payload(None, settings=dependencies.settings, limit=limit)
    now = dependencies.utc_now_iso()
    if not contracts.current(payload.get("generatedAt"), now):
        mode = "stale-seed"
        payload = {**payload, "status": "stale"}
    return {**normalize_crypto_funding_payload(payload, settings=dependencies.settings, limit=limit), "cacheMode": mode}
