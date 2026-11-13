from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from api.context import resolve_optional_service_callable
from api.services.seed_recovery import age_seconds

try:
    import requests
except ImportError:  # pragma: no cover - runtime watcher validates dependency.
    requests = None


FINANCE_EXTERNAL_NAMESPACE = "runtime:finance:external-sources"
FINANCE_EXTERNAL_CACHE_KEY = "v1"
FINANCE_EXTERNAL_TTL_SECONDS = 15 * 60

ETF_FLOW_SYMBOLS: Tuple[Tuple[str, str], ...] = (
    ("IBIT", "iShares Bitcoin Trust"),
    ("FBTC", "Fidelity Wise Origin Bitcoin Fund"),
    ("GBTC", "Grayscale Bitcoin Trust"),
    ("BITB", "Bitwise Bitcoin ETF"),
    ("ARKB", "ARK 21Shares Bitcoin ETF"),
    ("HODL", "VanEck Bitcoin Trust"),
    ("BRRR", "Valkyrie Bitcoin Fund"),
    ("EZBC", "Franklin Bitcoin ETF"),
    ("BTCO", "Invesco Galaxy Bitcoin ETF"),
    ("BTCW", "WisdomTree Bitcoin Fund"),
    ("ETHA", "iShares Ethereum Trust"),
    ("FETH", "Fidelity Ethereum Fund"),
)

TRADFI_PERP_SYMBOLS: Tuple[Tuple[str, str, str], ...] = (
    ("SPY-USDT-SWAP", "SPY-PERP", "index"),
    ("XAU-USDT-SWAP", "GOLD-PERP", "commodity"),
    ("CL-USDT-SWAP", "WTI-PERP", "commodity"),
    ("IWM-USDT-SWAP", "RUSSELL-ETF-PERP", "index"),
    ("EWJ-USDT-SWAP", "JAPAN-ETF-PERP", "index"),
    ("EWY-USDT-SWAP", "KOREA-ETF-PERP", "index"),
    ("NVDA-USDT-SWAP", "NVDA-PERP", "stock"),
    ("AMD-USDT-SWAP", "AMD-PERP", "stock"),
    ("AAPL-USDT-SWAP", "AAPL-PERP", "stock"),
    ("MSFT-USDT-SWAP", "MSFT-PERP", "stock"),
    ("AMZN-USDT-SWAP", "AMZN-PERP", "stock"),
    ("GOOGL-USDT-SWAP", "GOOGL-PERP", "stock"),
    ("META-USDT-SWAP", "META-PERP", "stock"),
    ("TSLA-USDT-SWAP", "TSLA-PERP", "stock"),
    ("COIN-USDT-SWAP", "COIN-PERP", "stock"),
    ("MSTR-USDT-SWAP", "MSTR-PERP", "stock"),
    ("HOOD-USDT-SWAP", "HOOD-PERP", "stock"),
    ("SPACEX-USDT-SWAP", "SPACEX-PERP", "private"),
)

TRADFI_REFERENCE_SYMBOLS: Tuple[Tuple[str, str, str], ...] = (
    ("ES=F", "S&P500-PERP", "index"),
    ("NQ=F", "NASDAQ-PERP", "index"),
    ("YM=F", "DOW-PERP", "index"),
    ("RTY=F", "RUSSELL-PERP", "index"),
    ("GC=F", "GOLD-PERP", "commodity"),
    ("CL=F", "WTI-PERP", "commodity"),
)

COT_MARKETS: Tuple[Tuple[str, str, str], ...] = (
    ("ES", "E-MINI S&P 500", "Equity index"),
    ("NQ", "NASDAQ-100", "Equity index"),
    ("BTC", "BITCOIN", "Crypto"),
    ("CL", "CRUDE OIL", "Energy"),
    ("GC", "GOLD", "Metals"),
)

STABLECOIN_SYMBOLS: Tuple[str, ...] = ("USDT", "USDC", "USDS", "DAI", "PYUSD", "FDUSD", "TUSD")


@dataclass(frozen=True)
class FinanceExternalSourceDependencies:
    settings: Any
    http_json_get: Callable[..., Any] | None
    http_json_post: Callable[..., Any] | None
    get_yahoo_market_snapshot: Callable[..., Any] | None
    get_cached_json: Callable[..., Any] | None
    snapshot_store: Any
    begin_source: Callable[..., Any] | None = None
    map_yahoo: Callable[..., Any] | None = None

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> FinanceExternalSourceDependencies:
        return cls(
            settings=context.get("SETTINGS"),
            http_json_get=resolve_optional_service_callable(
                context,
                "http_json_get",
            ),
            http_json_post=resolve_optional_service_callable(
                context,
                "http_json_post",
            ),
            get_yahoo_market_snapshot=resolve_optional_service_callable(
                context,
                "get_yahoo_market_snapshot",
            ),
            get_cached_json=resolve_optional_service_callable(
                context,
                "get_cached_json",
            ),
            snapshot_store=context.get("SNAPSHOT_STORE"),
            begin_source=resolve_optional_service_callable(context, "begin_source"),
            map_yahoo=context.get("map_yahoo"),
        )


FinanceExternalSourceContext = (
    Mapping[str, Any] | FinanceExternalSourceDependencies
)


def _dependencies(
    context: FinanceExternalSourceContext,
) -> FinanceExternalSourceDependencies:
    if isinstance(context, FinanceExternalSourceDependencies):
        return context
    return FinanceExternalSourceDependencies.from_context(context)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _setting(
    dependencies: FinanceExternalSourceDependencies,
    name: str,
) -> str:
    value = getattr(dependencies.settings, name, "") if dependencies.settings is not None else ""
    return str(value or "").strip()


def _source_url_from_template(template: str, placeholder: str = "{symbol}") -> str:
    text = str(template or "").strip()
    if not text:
        return ""
    return text.replace(f"/{placeholder}", "").replace(placeholder, "").rstrip("?&/")


def _pct_change(current: Any, previous: Any) -> Optional[float]:
    current_float = _safe_float(current)
    previous_float = _safe_float(previous)
    if current_float is None or previous_float in (None, 0):
        return None
    return ((current_float - float(previous_float)) / float(previous_float)) * 100


def _nested_usd(row: Dict[str, Any], key: str) -> Optional[float]:
    payload = row.get(key)
    if not isinstance(payload, dict):
        return None
    return _safe_float(payload.get("peggedUSD"))


def _http_get(
    dependencies: FinanceExternalSourceDependencies,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 12,
) -> Any:
    user_agent = "Mozilla/5.0" if "finance.yahoo.com/" in url else "polydata-finance-seed/1.0"
    if dependencies.http_json_get is not None:
        return dependencies.http_json_get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        )
    if requests is None:
        raise RuntimeError("requests package is required")
    session = requests.Session()
    session.trust_env = True
    try:
        response = session.get(url, params=params, timeout=timeout, headers={"User-Agent": user_agent})
        response.raise_for_status()
        return response.json() if response.content else None
    finally:
        session.close()


def _http_post(
    dependencies: FinanceExternalSourceDependencies,
    url: str,
    *,
    json_payload: Dict[str, Any],
    timeout: int = 12,
) -> Any:
    if dependencies.http_json_post is not None:
        return dependencies.http_json_post(
            url,
            json_payload=json_payload,
            timeout=timeout,
            headers={"User-Agent": "polydata-finance-seed/1.0"},
        )
    if requests is None:
        raise RuntimeError("requests package is required")
    session = requests.Session()
    session.trust_env = True
    try:
        response = session.post(url, json=json_payload, timeout=timeout, headers={"User-Agent": "polydata-finance-seed/1.0"})
        response.raise_for_status()
        return response.json() if response.content else None
    finally:
        session.close()


def _fetch_yahoo_snapshot(
    dependencies: FinanceExternalSourceDependencies,
    symbol: str,
) -> Optional[Dict[str, Any]]:
    if dependencies.get_yahoo_market_snapshot is not None:
        quote = dependencies.get_yahoo_market_snapshot(
            symbol,
            interval="30m",
            range_name="5d",
            ttl_seconds=300,
        )
        # This client owns source timeouts and backoff. Do not bypass it with
        # another request to the same provider after a failure or empty result.
        return quote if isinstance(quote, dict) and quote.get("price") is not None else None
    payload = _http_get(
        dependencies,
        _setting(
            dependencies,
            "finance_yahoo_chart_url_template",
        ).format(symbol=symbol),
        params={"range": "5d", "interval": "1d"},
        timeout=12,
    )
    result = (payload.get("chart") or {}).get("result") if isinstance(payload, dict) else []
    chart = result[0] if isinstance(result, list) and result else {}
    quote_rows = (chart.get("indicators") or {}).get("quote") or []
    quote_data = quote_rows[0] if quote_rows and isinstance(quote_rows[0], dict) else {}
    closes = [value for value in (quote_data.get("close") or []) if value is not None]
    volumes = [value for value in (quote_data.get("volume") or []) if value is not None]
    if not closes:
        return None
    price = _safe_float(closes[-1])
    previous = _safe_float(closes[-2]) if len(closes) >= 2 else None
    return {
        "price": price,
        "changePercent": _pct_change(price, previous),
        "volume24h": _safe_float(volumes[-1]) if volumes else None,
    }


def _bounded_snapshot(payload):
    """Consumer views cannot renew failed constituent sources via a new envelope."""
    payload = dict(payload)
    now = utc_now_iso()
    for name in ("hyperliquid", "tradfiPerps", "etfFlow", "cot", "stablecoin"):
        branch = payload.get(name)
        if not isinstance(branch, dict):
            continue
        rows = []
        for row in branch.get("items", []):
            at = row.get("fetchedAt") or branch.get("fetchedAt") or payload.get("generatedAt")
            if at and age_seconds(at, now) >= 1800:
                continue
            rows.append(row)
        if len(rows) < len(branch.get("items", [])):
            payload[name] = {**branch, "items": rows, "status": "partial" if rows else "unavailable"}
            payload["status"] = "partial"
    return payload


def read_finance_external_sources(
    ctx: FinanceExternalSourceContext,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    if dependencies.snapshot_store is not None:
        payload = dependencies.snapshot_store.get_stale(FINANCE_EXTERNAL_NAMESPACE, FINANCE_EXTERNAL_CACHE_KEY)
        if isinstance(payload, dict):
            return _bounded_snapshot(payload)
    if dependencies.get_cached_json is not None:
        try:
            payload = dependencies.get_cached_json(FINANCE_EXTERNAL_NAMESPACE, FINANCE_EXTERNAL_CACHE_KEY)
            if isinstance(payload, dict):
                return _bounded_snapshot(payload)
        except Exception:
            pass  # Optional mirror cannot suppress the durable source snapshot.
    return {}


def _source_status(items: Iterable[Any], *, degraded_if_empty: bool = True) -> str:
    count = len(list(items))
    if count:
        return "ok"
    return "degraded" if degraded_if_empty else "empty"


def _fetch_hyperliquid_perp_source(
    dependencies: FinanceExternalSourceDependencies,
) -> Dict[str, Any]:
    source_url = _setting(dependencies, "finance_hyperliquid_info_url")
    payload = _http_post(
        dependencies,
        source_url,
        json_payload={"type": "metaAndAssetCtxs"},
        timeout=15,
    )
    if not isinstance(payload, list) or len(payload) < 2:
        return {"status": "degraded", "items": [], "error": "unexpected Hyperliquid response"}
    universe = (payload[0] or {}).get("universe") or []
    asset_contexts = payload[1] or []
    # BTC/ETH are also required by the ETF demand fallback below.
    wanted = {"BTC", "ETH"} | {symbol for symbol, _name, _asset_class in TRADFI_PERP_SYMBOLS}
    rows: List[Dict[str, Any]] = []
    for meta, asset_ctx in zip(universe, asset_contexts):
        if not isinstance(meta, dict) or not isinstance(asset_ctx, dict):
            continue
        symbol = str(meta.get("name") or "").upper()
        if symbol not in wanted:
            continue
        rows.append(
            {
                "symbol": symbol,
                "display": f"{symbol}-PERP",
                "assetClass": next((asset_class for item_symbol, _name, asset_class in TRADFI_PERP_SYMBOLS if item_symbol == symbol), "crypto"),
                "markPx": _safe_float(asset_ctx.get("markPx")),
                "oraclePx": _safe_float(asset_ctx.get("oraclePx")),
                "spotPx": _safe_float(asset_ctx.get("midPx") or asset_ctx.get("markPx")),
                "basisBps": None,
                "funding": _safe_float(asset_ctx.get("funding")),
                "openInterest": _safe_float(asset_ctx.get("openInterest")),
                "dayNotional": _safe_float(asset_ctx.get("dayNtlVlm")),
                "source": "hyperliquid",
                "alerts": ["HYPER"],
            }
        )
    return {"status": _source_status(rows), "items": rows, "sourceUrl": source_url}


def fetch_okx_tradfi_perp_source(
    ctx: FinanceExternalSourceContext,
) -> Dict[str, Any]:
    return _fetch_okx_tradfi_perp_source(
        _dependencies(ctx),
    )


def _fetch_okx_tradfi_perp_source(
    dependencies: FinanceExternalSourceDependencies,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    failed = []
    unsupported = []
    source_url = _setting(dependencies, "finance_okx_market_tickers_url")
    if not source_url:
        raise ValueError("OKX batch ticker source not configured")
    payload = _http_get(dependencies, source_url, params={"instType": "SWAP"}, timeout=45)
    if not isinstance(payload, dict) or str(payload.get("code")) != "0" or not isinstance(payload.get("data"), list):
        raise ValueError("OKX batch ticker response invalid")
    tickers = {row["instId"]: row for row in payload["data"]
               if isinstance(row, dict) and row.get("instType") == "SWAP" and row.get("instId")}
    if not tickers:
        raise ValueError("OKX batch ticker catalog missing")
    ticker_fetched_at = utc_now_iso()
    # All six reads share the owner's source deadline. These are batch public
    # endpoints; funding ANY avoids one request per instrument.
    catalogs, errors, receipts = {}, {}, {}
    for name, setting, params in (
        ("instrument", "finance_okx_instruments_url", {"instType": "SWAP"}),
        ("mark", "finance_okx_mark_price_url", {"instType": "SWAP"}),
        ("index", "finance_okx_index_tickers_url", {"quoteCcy": "USDT"}),
        ("openInterest", "finance_okx_open_interest_url", {"instType": "SWAP"}),
        ("funding", "finance_okx_funding_rate_url", {"instId": "ANY"}),
    ):
        try:
            url = _setting(dependencies, setting)
            if not url:
                raise ValueError("source not configured")
            data = _http_get(dependencies, url, params=params, timeout=45)
            if not isinstance(data, dict) or str(data.get("code")) != "0" or not isinstance(data.get("data"), list):
                raise ValueError("invalid batch response")
            catalogs[name] = {r["instId"]: r for r in data["data"] if isinstance(r, dict) and r.get("instId")}
            if not catalogs[name]:
                raise ValueError("empty batch response")
            receipts[name] = utc_now_iso()
        except Exception as exc:
            catalogs[name] = {}
            errors[name] = type(exc).__name__
    fetched_at = utc_now_iso()
    for inst_id, display, asset_class in TRADFI_PERP_SYMBOLS:
        ticker = tickers.get(inst_id)
        if ticker is None:
            unsupported.append(inst_id)
            continue
        last = _safe_float(ticker.get("last"))
        open_24h = _safe_float(ticker.get("open24h"))
        change_pct = _pct_change(last, open_24h)
        if last is None or last <= 0:
            failed.append(inst_id)
            continue
        try:
            observed_at = datetime.fromtimestamp(float(ticker["ts"]) / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
        except (KeyError, TypeError, ValueError, OverflowError, OSError):
            observed_at = None
        row = {
                "symbol": inst_id,
                "display": display,
                "assetClass": asset_class,
                "lastPx": last,
                "priceType": "last",
                "instrumentType": "SWAP",
                "sourceObservedAt": observed_at,
                "fetchedAt": ticker_fetched_at,
                "markPx": None,
                "oraclePx": None,
                "spotPx": None,
                "basisBps": None,
                "funding": None,
                "openInterest": None,
                "dayNotional": None,
                "volumeBase24h": _safe_float(ticker.get("volCcy24h")),
                "volumeContracts24h": _safe_float(ticker.get("vol24h")),
                "changePercent": change_pct,
                "source": "okx-swap",
                "venue": "OKX",
                "alerts": ["OKX", "PERP"],
            }
        _okx_tradfi_metrics(row, catalogs, fetched_at, receipts)
        rows.append(row)
    # Each metric retains its own source/receipt clocks. A successful ticker
    # cannot make a failed mark, funding or metadata read fresh.
    if any(any(v != "ok" for v in r["metricStatus"].values()) for r in rows):
        previous = read_finance_external_sources(dependencies)
        old_rows = {r.get("symbol"): r for r in previous.get("tradfiPerps", {}).get("items", [])}
        for row in rows:
            _retain_okx_metrics(row, old_rows.get(row["symbol"], {}), fetched_at)
    incomplete = any(any(v != "ok" for v in r["metricStatus"].values()) for r in rows)
    return {"status": "partial" if failed or incomplete else _source_status(rows, degraded_if_empty=False),
            "metricErrors": errors,
            "failedSymbols": failed, "unsupportedSymbols": unsupported,
            "coverageScope": "returned-swap-tickers",
            "availableInstrumentCount": len(tickers), "requestedSymbolCount": len(TRADFI_PERP_SYMBOLS),
            "items": rows, "sourceUrl": source_url, "fetchedAt": fetched_at}


_OKX_METRIC_FIELDS = {
    "instrument": ("contractValue", "contractMultiplier", "contractValueCurrency", "contractType", "settleCurrency", "quoteCurrency", "indexId", "volumeBaseCurrency"),
    "mark": ("markPx",), "index": ("oraclePx",),
    "openInterest": ("openInterest", "openInterestBase", "openInterestUsd"),
    "funding": ("funding", "fundingAt", "nextFundingAt", "fundingIntervalHours", "settledFunding", "settlementState"),
}


def _okx_time(value: Any) -> Optional[str]:
    ms = _safe_float(value)
    if ms is None or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError):
        return None


def _okx_tradfi_metrics(row: Dict[str, Any], catalogs: Dict[str, Any], fetched_at: str, source_receipts: Dict[str, str]) -> None:
    inst = catalogs["instrument"].get(row["symbol"], {})
    ct_val, multiplier = _safe_float(inst.get("ctVal")), _safe_float(inst.get("ctMult"))
    index_id = str(inst.get("uly") or "")
    valid_instrument = (inst.get("instType") == "SWAP" and inst.get("ctType") in {"linear", "inverse"}
                        and ct_val is not None and ct_val > 0 and multiplier is not None and multiplier > 0
                        and bool(inst.get("ctValCcy")) and bool(inst.get("settleCcy"))
                        and index_id.endswith("-USDT"))
    clocks, receipts, states = {}, {}, {}
    for name in _OKX_METRIC_FIELDS:
        data = catalogs[name].get(index_id if name == "index" else row["symbol"], {})
        clocks[name] = _okx_time(data.get("ts")) if name != "instrument" else None
        receipts[name] = source_receipts.get(name) if data else None
        states[name] = "ok" if data and (name == "instrument" or clocks[name]) else "unavailable"
        for field in _OKX_METRIC_FIELDS[name]:
            row[field] = None
    if valid_instrument:
        row.update(contractValue=ct_val, contractMultiplier=multiplier,
                   contractValueCurrency=inst["ctValCcy"], contractType=inst["ctType"],
                   settleCurrency=inst["settleCcy"], quoteCurrency=index_id.rsplit("-", 1)[1],
                   indexId=index_id, volumeBaseCurrency=index_id.rsplit("-", 1)[0])
    else:
        states["instrument"] = "unavailable"
    for name, field, source_field in (("mark", "markPx", "markPx"), ("index", "oraclePx", "idxPx")):
        data = catalogs[name].get(index_id if name == "index" else row["symbol"], {})
        value = _safe_float(data.get(source_field))
        if value is not None and value > 0 and states[name] == "ok":
            row[field] = value
        else:
            states[name] = "unavailable"
    oi = catalogs["openInterest"].get(row["symbol"], {})
    for field, source_field in (("openInterest", "oi"), ("openInterestBase", "oiCcy"), ("openInterestUsd", "oiUsd")):
        value = _safe_float(oi.get(source_field))
        row[field] = value if value is not None and value >= 0 and states["openInterest"] == "ok" else None
    if any(row[k] is None for k in _OKX_METRIC_FIELDS["openInterest"]):
        states["openInterest"] = "unavailable"
    funding = catalogs["funding"].get(row["symbol"], {})
    rate = _safe_float(funding.get("fundingRate"))
    at, next_at = _safe_float(funding.get("fundingTime")), _safe_float(funding.get("nextFundingTime"))
    if rate is not None and at and next_at and next_at > at and states["funding"] == "ok":
        row.update(funding=rate, fundingAt=_okx_time(at), nextFundingAt=_okx_time(next_at),
                   fundingIntervalHours=(next_at - at) / 3600000,
                   settledFunding=_safe_float(funding.get("settFundingRate")), settlementState=funding.get("settState"))
    else:
        states["funding"] = "unavailable"
    for name, at in clocks.items():
        if name != "instrument" and states[name] == "ok":
            age = age_seconds(at, fetched_at)
            if not math.isfinite(age) or age < -1:
                states[name] = "unavailable"
                for field in _OKX_METRIC_FIELDS[name]:
                    row[field] = None
            elif age > 900:
                states[name] = "stale"
    row.update(metricObservedAt=clocks, metricFetchedAt=receipts, metricStatus=states)
    _okx_derived_metrics(row, fetched_at)


def _okx_derived_metrics(row: Dict[str, Any], now: str) -> None:
    clocks, states = row["metricObservedAt"], row["metricStatus"]
    row["basisBps"] = None
    row["basisStatus"] = "unavailable"
    if all(states[k] == "ok" for k in ("mark", "index", "instrument")):
        mark_age, index_age = age_seconds(clocks["mark"], now), age_seconds(clocks["index"], now)
        if max(mark_age, index_age) <= 120 and abs(mark_age - index_age) <= 60:
            row["basisBps"] = (row["markPx"] / row["oraclePx"] - 1) * 10000
            row["basisStatus"] = "ok"
        else:
            row["basisStatus"] = "unaligned"
    # Nominal units come from the live contract metadata. This is not rolling
    # traded turnover: linear quote value uses the current mark explicitly.
    row["volumeNominal24h"] = row["volumeNominalCurrency"] = None
    row["volumeMarkEquivalent24h"] = None
    contracts = row.get("volumeContracts24h")
    if states["instrument"] == "ok" and contracts is not None and contracts >= 0:
        nominal = contracts * row["contractValue"] * row["contractMultiplier"]
        row["volumeNominal24h"], row["volumeNominalCurrency"] = nominal, row["contractValueCurrency"]
        if row["contractType"] == "linear" and states["mark"] == "ok" and row["contractValueCurrency"] == row["volumeBaseCurrency"]:
            row["volumeMarkEquivalent24h"] = nominal * row["markPx"]


def _retain_okx_metrics(row: Dict[str, Any], previous: Dict[str, Any], now: str) -> None:
    for name, fields in _OKX_METRIC_FIELDS.items():
        at = previous.get("metricFetchedAt", {}).get(name)
        if row["metricStatus"][name] == "unavailable" and previous.get("metricStatus", {}).get(name) in {"ok", "stale"} and at and age_seconds(at, now) < 1800:
            for field in fields:
                row[field] = previous.get(field)
            row["metricStatus"][name] = "stale"
            row["metricObservedAt"][name] = previous.get("metricObservedAt", {}).get(name)
            row["metricFetchedAt"][name] = at
    _okx_derived_metrics(row, now)


def fetch_reference_tradfi_perp_source(
    ctx: FinanceExternalSourceContext,
) -> Dict[str, Any]:
    return _fetch_reference_tradfi_perp_source(
        _dependencies(ctx),
    )


def _fetch_reference_tradfi_perp_source(
    dependencies: FinanceExternalSourceDependencies,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    failed = []
    def fetch(spec):
        try:
            return _fetch_yahoo_snapshot(dependencies, spec[0])
        except Exception:
            return None
    mapper = dependencies.map_yahoo or map
    for (yahoo_symbol, display, asset_class), quote in zip(TRADFI_REFERENCE_SYMBOLS, mapper(fetch, TRADFI_REFERENCE_SYMBOLS)):
        if not isinstance(quote, dict):
            failed.append(yahoo_symbol)
            continue
        price = _safe_float(quote.get("price"))
        if price is None:
            continue
        rows.append(
            {
                "symbol": yahoo_symbol,
                "display": display.removesuffix("-PERP") + "-FUTURES",
                "assetClass": asset_class,
                "lastPx": price,
                "priceType": "reference",
                "instrumentType": "FUTURES_REFERENCE",
                "fetchedAt": quote.get("fetchedAt") or utc_now_iso(),
                "sourceObservedAt": quote.get("quoteAt") or quote.get("sourceObservedAt"),
                "markPx": None,
                "oraclePx": None,
                "spotPx": None,
                "basisBps": None,
                "funding": None,
                "openInterest": None,
                "dayNotional": None,
                "volume24h": _safe_float(quote.get("volume24h")),
                "changePercent": _safe_float(quote.get("changePercent")),
                "source": "yahoo-reference",
                "venue": "REFERENCE",
                "alerts": ["REF", "FUTURES"],
            }
        )
    return {
        "status": "partial" if failed else _source_status(rows),
        "failedSymbols": failed,
        "items": rows,
        "sourceUrl": _source_url_from_template(
            _setting(dependencies, "finance_yahoo_chart_url_template"),
        ),
    }


def _fetch_etf_flow_source(
    dependencies: FinanceExternalSourceDependencies,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    failed = []
    def fetch(spec):
        try:
            return _fetch_yahoo_snapshot(dependencies, spec[0])
        except Exception:
            return None
    mapper = dependencies.map_yahoo or map
    for (symbol, issuer), quote in zip(ETF_FLOW_SYMBOLS, mapper(fetch, ETF_FLOW_SYMBOLS)):
        if not isinstance(quote, dict):
            failed.append(symbol)
            continue
        change_pct = _safe_float(quote.get("changePercent"))
        volume = _safe_float(quote.get("volume24h"))
        price = _safe_float(quote.get("price"))
        flow_proxy = None
        if change_pct is not None and volume is not None and price is not None:
            flow_proxy = (change_pct / 100.0) * volume * price
        rows.append(
            {
                "symbol": symbol,
                "issuer": issuer,
                "price": price,
                "changePercent": change_pct,
                "volume": volume,
                "flowProxyUsd": flow_proxy,
                "source": "yahoo-flow-proxy",
            }
        )
    net_flow_proxy = sum(_safe_float(row.get("flowProxyUsd")) or 0.0 for row in rows)
    return {
        "status": "partial" if failed else _source_status(rows),
        "failedSymbols": failed,
        "netFlowProxyUsd": net_flow_proxy,
        "items": sorted(rows, key=lambda item: abs(_safe_float(item.get("flowProxyUsd")) or 0.0), reverse=True),
        "sourceUrl": _source_url_from_template(
            _setting(dependencies, "finance_yahoo_chart_url_template"),
        ),
    }


def _build_etf_flow_proxy_from_perps(
    dependencies: FinanceExternalSourceDependencies,
    hyperliquid_payload: Dict[str, Any],
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for item in hyperliquid_payload.get("items") or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        if symbol not in {"BTC", "ETH"}:
            continue
        funding = _safe_float(item.get("funding")) or 0.0
        day_notional = _safe_float(item.get("dayNotional")) or 0.0
        rows.append(
            {
                "symbol": f"{symbol}-ETF",
                "issuer": f"{symbol} ETF demand proxy",
                "price": item.get("markPx"),
                "changePercent": None,
                "volume": day_notional,
                "flowProxyUsd": funding * day_notional,
                "source": "hyperliquid-etf-proxy",
            }
        )
    net_flow_proxy = sum(_safe_float(row.get("flowProxyUsd")) or 0.0 for row in rows)
    return {
        "status": "proxy" if rows else "degraded",
        "netFlowProxyUsd": net_flow_proxy,
        "items": rows,
        "sourceUrl": _setting(dependencies, "finance_hyperliquid_info_url"),
        "note": "Yahoo ETF quotes unavailable; using BTC/ETH perp funding notional as an ETF demand proxy.",
    }


def fetch_cot_source(
    ctx: FinanceExternalSourceContext,
) -> Dict[str, Any]:
    return _fetch_cot_source(
        _dependencies(ctx),
    )


def _fetch_cot_source(
    dependencies: FinanceExternalSourceDependencies,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    failed = []
    source_errors = {}
    source_url = _setting(dependencies, "finance_cftc_legacy_cot_url")
    for symbol, query_term, asset_class in COT_MARKETS:
        try:
            payload = _http_get(
                dependencies,
                source_url,
                params={
                    "$limit": 1,
                    "$order": "report_date_as_yyyy_mm_dd DESC",
                    "$where": f"upper(market_and_exchange_names) like '%{query_term}%'",
                },
                timeout=15,
            )
        except Exception as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            source_errors[symbol] = {"errorType": type(exc).__name__, "httpStatus": status_code}
            failed.append(symbol)
            if status_code in {401, 403}:
                # The source rejected this reader. Do not repeat the same denial
                # for every market or turn it into an empty positioning report.
                failed.extend(item[0] for item in COT_MARKETS if item[0] not in failed and item[0] not in {row["symbol"] for row in rows})
                break
            continue
        row = payload[0] if isinstance(payload, list) and payload else {}
        if not isinstance(row, dict) or not row.get("report_date_as_yyyy_mm_dd"):
            failed.append(symbol)
            continue
        noncomm_long = _safe_float(row.get("noncomm_positions_long_all"))
        noncomm_short = _safe_float(row.get("noncomm_positions_short_all"))
        open_interest = _safe_float(row.get("open_interest_all"))
        net = None
        net_pct_oi = None
        if noncomm_long is not None and noncomm_short is not None:
            net = noncomm_long - noncomm_short
            if open_interest not in (None, 0):
                net_pct_oi = (net / float(open_interest)) * 100
        rows.append(
            {
                "symbol": symbol,
                "assetClass": asset_class,
                "market": row.get("market_and_exchange_names"),
                "reportDate": row.get("report_date_as_yyyy_mm_dd"),
                "sourceObservedAt": row.get("report_date_as_yyyy_mm_dd"),
                "fetchedAt": utc_now_iso(),
                "openInterest": open_interest,
                "nonCommercialLong": noncomm_long,
                "nonCommercialShort": noncomm_short,
                "nonCommercialNet": net,
                "netPctOpenInterest": net_pct_oi,
                "source": "cftc-cot",
            }
        )
    return {"status": ("partial" if rows else "error") if failed else _source_status(rows),
            "failedSymbols": failed, "sourceErrors": source_errors, "items": rows, "sourceUrl": source_url}


def _fetch_stablecoin_source(
    dependencies: FinanceExternalSourceDependencies,
) -> Dict[str, Any]:
    source_url = _setting(dependencies, "finance_defillama_stablecoins_url")
    payload = _http_get(
        dependencies,
        source_url,
        params={"includePrices": "true"},
        timeout=15,
    )
    assets = payload.get("peggedAssets") if isinstance(payload, dict) else []
    rows: List[Dict[str, Any]] = []
    seen_symbols = set()
    for asset in assets or []:
        if not isinstance(asset, dict):
            continue
        symbol = str(asset.get("symbol") or "").upper()
        if symbol not in STABLECOIN_SYMBOLS:
            continue
        if symbol in seen_symbols:
            continue
        seen_symbols.add(symbol)
        current = _nested_usd(asset, "circulating")
        prev_day = _nested_usd(asset, "circulatingPrevDay")
        prev_week = _nested_usd(asset, "circulatingPrevWeek")
        price = _safe_float(asset.get("price"))
        deviation_bps = None
        if price is not None:
            deviation_bps = (price - 1.0) * 10000
        rows.append(
            {
                "symbol": symbol,
                "name": asset.get("name"),
                "price": price,
                "deviationBps": deviation_bps,
                "supplyUsd": current,
                "change1dPct": _pct_change(current, prev_day),
                "change7dPct": _pct_change(current, prev_week),
                "pegMechanism": asset.get("pegMechanism"),
                "source": "defillama",
            }
        )
    rows.sort(key=lambda item: _safe_float(item.get("supplyUsd")) or 0.0, reverse=True)
    total_supply = sum(_safe_float(row.get("supplyUsd")) or 0.0 for row in rows)
    total_prev_week = None
    if rows:
        weighted = [
            (_safe_float(row.get("change7dPct")) or 0.0, _safe_float(row.get("supplyUsd")) or 0.0)
            for row in rows
        ]
        denominator = sum(weight for _change, weight in weighted)
        total_prev_week = sum(change * weight for change, weight in weighted) / denominator if denominator else None
    stressed = sum(1 for row in rows if abs(_safe_float(row.get("deviationBps")) or 0.0) >= 50)
    return {
        "status": _source_status(rows),
        "totalSupplyUsd": total_supply,
        "supplyChange7dPct": total_prev_week,
        "stressedCount": stressed,
        "items": rows,
        "sourceUrl": source_url,
    }


def build_finance_external_sources_payload(
    ctx: FinanceExternalSourceContext,
) -> Dict[str, Any]:
    return _build_finance_external_sources_payload(
        _dependencies(ctx),
    )


def _build_finance_external_sources_payload(
    dependencies: FinanceExternalSourceDependencies,
) -> Dict[str, Any]:
    sources: Dict[str, str] = {}
    errors: Dict[str, str] = {}
    previous = read_finance_external_sources(dependencies)
    observed = utc_now_iso()
    source_payloads = {}

    def capture(
        name: str,
        builder: Callable[[FinanceExternalSourceDependencies], Dict[str, Any]],
    ) -> Dict[str, Any]:
        attempted_at = utc_now_iso()
        if dependencies.begin_source is not None:
            dependencies.begin_source(name)
        try:
            payload = builder(dependencies)
        except Exception as exc:
            errors[name] = type(exc).__name__
            payload = {"status": "error", "items": [], "error": type(exc).__name__,
                       "httpStatus": getattr(getattr(exc, "response", None), "status_code", None)}
        completed_at = utc_now_iso()
        status = str(payload.get("status") or "unknown")
        old = (previous.get("sourcePayloads") or {}).get(name) or previous.get(name) or {}
        if not old and name in {"referenceTradfiPerps", "okxTradfiPerps"}:
            source = "yahoo-reference" if name == "referenceTradfiPerps" else "okx-swap"
            old = {"items": [row for row in previous.get("tradfiPerps", {}).get("items", []) if row.get("source") == source]}
        rows = [{**row, "fetchedAt": row.get("fetchedAt") or completed_at} for row in payload.get("items", [])]
        failed = set(payload.get("failedSymbols") or [])
        if status in {"error", "degraded", "unavailable"} or failed:
            seen = {row.get("symbol") or row.get("id") for row in rows}
            for row in old.get("items", []):
                identity = row.get("symbol") or row.get("id")
                at = row.get("fetchedAt") or old.get("fetchedAt") or previous.get("generatedAt")
                if identity not in seen and (not failed or identity in failed) and age_seconds(at, observed) < 1800:
                    rows.append({**row, "fetchedAt": at, "retained": True, "sourceStatus": "stale"})
        payload = {**payload, "items": rows, "lastAttemptAt": attempted_at}
        if any(row.get("retained") for row in rows):
            payload["status"] = "stale" if all(row.get("retained") for row in rows) else "partial"
        if status in {"ok", "empty", "proxy"} and not failed:
            payload["fetchedAt"] = payload.get("fetchedAt") or completed_at
        else:
            errors.setdefault(name, payload.get("error") or "incomplete source refresh")
            payload["fetchedAt"] = old.get("fetchedAt") if old.get("items") else None
        sources[name] = payload["status"]
        source_payloads[name] = payload
        return payload

    hyperliquid = capture("hyperliquid", _fetch_hyperliquid_perp_source)
    okx_tradfi = capture("okxTradfiPerps", _fetch_okx_tradfi_perp_source)
    reference_tradfi = capture(
        "referenceTradfiPerps",
        _fetch_reference_tradfi_perp_source,
    )
    tradfi_items = []
    seen_tradfi = set()
    for source in (okx_tradfi, reference_tradfi):
        for item in source.get("items") or []:
            key = str(item.get("display") or item.get("symbol") or "")
            if key and key not in seen_tradfi:
                tradfi_items.append(item)
                seen_tradfi.add(key)
    tradfi_perps = {
        "status": "ok" if all(p.get("status") == "ok" for p in (okx_tradfi, reference_tradfi)) else "partial" if tradfi_items else "unavailable",
        "items": tradfi_items,
        "sourceUrl": _setting(dependencies, "finance_okx_market_tickers_url"),
        "sources": {"okx": okx_tradfi.get("status"), "reference": reference_tradfi.get("status")},
    }
    etf_flow = capture("etfFlow", _fetch_etf_flow_source)
    if not (etf_flow.get("items") or []):
        etf_flow = _build_etf_flow_proxy_from_perps(
            dependencies,
            hyperliquid,
        )
        sources["etfFlow"] = str(etf_flow.get("status") or "proxy")
    cot = capture("cot", _fetch_cot_source)
    stablecoin = capture("stablecoin", _fetch_stablecoin_source)
    # trade.xyz does not currently expose a documented public market-data endpoint
    # in the same way Hyperliquid does; keep a seeded source state so the panel can
    # distinguish "seeded proxy" from "seed pending".
    sources["tradexyz"] = "proxy" if hyperliquid.get("items") or etf_flow.get("items") else "degraded"

    ok_count = sum(1 for status in sources.values() if status in {"ok", "proxy"})
    status = "ok" if ok_count >= 3 and not errors and tradfi_perps["status"] == "ok" else ("partial" if ok_count else "degraded")
    return {
        "generatedAt": utc_now_iso(),
        "status": status,
        "cacheMode": "seeded",
        "sources": sources,
        "errors": errors,
        "sourcePayloads": source_payloads,
        "tradfiPerps": tradfi_perps,
        "etfFlow": etf_flow,
        "cot": cot,
        "stablecoin": stablecoin,
            "summary": {
            "perpCount": len(tradfi_perps.get("items") or []),
            "etfCount": len(etf_flow.get("items") or []),
            "cotCount": len(cot.get("items") or []),
            "stablecoinCount": len(stablecoin.get("items") or []),
            "stablecoinSupplyUsd": stablecoin.get("totalSupplyUsd"),
            "etfNetFlowProxyUsd": etf_flow.get("netFlowProxyUsd"),
        },
    }
