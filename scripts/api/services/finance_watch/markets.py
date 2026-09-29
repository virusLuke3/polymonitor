from __future__ import annotations

import math
from typing import Any, Dict, List

from api.services import crypto_funding_service
from api.services.finance_watch.common import (
    FinanceWatchContext,
    _dependencies,
    _fetch_yahoo_snapshot,
    _format_pct,
    _format_price,
    _http_json_get,
    _payload,
    _safe_float,
    _setting,
    _tone,
)

GLOBAL_INDEX_SYMBOLS = (
    ("S&P 500", "^GSPC", "US"),
    ("NASDAQ", "^IXIC", "US"),
    ("DOW", "^DJI", "US"),
    ("RUSSELL", "^RUT", "US"),
    ("SHANGHAI", "000001.SS", "CN"),
    ("HANG SENG", "^HSI", "HK"),
    ("NIKKEI", "^N225", "JP"),
    ("NIFTY", "^NSEI", "IN"),
    ("EURO STOXX", "^STOXX50E", "EU"),
    ("FTSE", "^FTSE", "UK"),
    ("DAX", "^GDAXI", "DE"),
    ("CAC", "^FCHI", "FR"),
)


CRYPTO_PERP_ORDER = (
    "BTC",
    "ETH",
    "SOL",
    "BNB",
    "XRP",
    "DOGE",
    "ADA",
    "AVAX",
    "LINK",
    "TRX",
    "DOT",
    "BCH",
    "SUI",
    "NEAR",
    "APT",
)


RELIABLE_DEFI_PROJECTS = {
    "aave-v3": 120,
    "aave": 118,
    "pendle": 116,
    "uniswap-v3": 114,
    "uniswap-v4": 112,
    "uniswap": 110,
    "curve-dex": 108,
    "curve": 108,
    "compound-v3": 106,
    "compound": 104,
    "morpho-blue": 102,
    "morpho": 100,
    "makerdao": 98,
    "sky-lending": 96,
    "ether.fi": 94,
    "lido": 92,
}


TRADFI_PERP_CLASS_PRIORITY = {"INDEX": 4, "COMMODITY": 3, "STOCK": 2, "PRIVATE": 1}


TRADFI_PERP_DISPLAY_PRIORITY = {
    "SPY-PERP": 100,
    "S&P500-PERP": 98,
    "RUSSELL-PERP": 96,
    "RUSSELL-ETF-PERP": 95,
    "DOW-PERP": 94,
    "NASDAQ-PERP": 92,
    "GOLD-PERP": 90,
    "WTI-PERP": 88,
}


def build_defi_yields_payload(
    ctx: FinanceWatchContext,
    limit: int,
) -> Dict[str, Any]:
    raw = _http_json_get(ctx, _setting(ctx, "finance_defillama_yields_url"), timeout=16)
    pools = raw.get("data") if isinstance(raw, dict) else []
    rows: List[Dict[str, Any]] = []
    for pool in pools or []:
        if not isinstance(pool, dict):
            continue
        tvl = _safe_float(pool.get("tvlUsd"))
        apy = _safe_float(pool.get("apy"))
        project = str(pool.get("project") or "Protocol")
        project_key = project.lower().strip()
        protocol_score = RELIABLE_DEFI_PROJECTS.get(project_key, 0)
        if tvl is None or apy is None or tvl < 5_000_000 or apy <= 0 or apy > 60:
            continue
        if protocol_score <= 0 and tvl < 50_000_000:
            continue
        symbol = str(pool.get("symbol") or pool.get("underlyingTokens") or "").upper()
        stable_bonus = 18 if pool.get("stablecoin") else 0
        moderate_apy_bonus = max(0.0, 30.0 - abs(float(apy) - 8.0))
        risk_penalty = 45 if apy > 30 else 18 if apy > 18 else 0
        reliability = protocol_score + stable_bonus + math.log10(max(tvl, 1.0)) * 8 + moderate_apy_bonus - risk_penalty
        tags = ["TVL"]
        if pool.get("stablecoin"):
            tags.append("STABLE")
        if project_key in RELIABLE_DEFI_PROJECTS:
            tags.append(project.split("-")[0].upper()[:8])
        if apy >= 25:
            tags.append("RISK")
        rows.append(
            {
                "id": str(pool.get("pool") or f"{project}:{symbol}"),
                "label": project.title(),
                "symbol": symbol[:18],
                "metric": apy,
                "metricLabel": f"{apy:.2f}%",
                "metricUnit": "APY",
                "secondary": tvl,
                "secondaryLabel": _format_usd(tvl),
                "change": _safe_float(pool.get("apyPct30D") or pool.get("apyPct7D")),
                "tags": tags[:4],
                "tone": "up" if apy < 18 else "watch",
                "reliabilityScore": reliability,
            }
        )
    rows.sort(key=lambda item: (_safe_float(item.get("reliabilityScore")) or 0.0, _safe_float(item.get("secondary")) or 0.0), reverse=True)
    return _payload("defi-yield-monitor", title="DEFI YIELDS", items=rows[:limit], summary={"topLabel": rows[0]["label"] if rows else None, "rankBy": "protocol reliability + TVL"}, sources={"defillamaYields": "ok" if rows else "empty"})


def build_crypto_perps_payload(
    ctx: FinanceWatchContext,
    limit: int,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    requested_limit = max(limit, len(CRYPTO_PERP_ORDER), 24)
    if dependencies.get_crypto_funding_watch_snapshot is not None:
        base = dependencies.get_crypto_funding_watch_snapshot(
            limit=requested_limit,
        )
    else:
        base = crypto_funding_service.get_crypto_funding_watch_snapshot(
            dependencies.crypto_funding,
            limit=requested_limit,
        )
    asset_map = {str(asset.get("asset") or asset.get("symbol") or "").upper(): asset for asset in (base.get("assets") or []) if isinstance(asset, dict)}
    ordered_assets = [asset_map[symbol] for symbol in CRYPTO_PERP_ORDER if symbol in asset_map]
    extras = [asset for symbol, asset in asset_map.items() if symbol not in CRYPTO_PERP_ORDER]
    rows: List[Dict[str, Any]] = []
    for asset in (ordered_assets + extras)[:limit]:
        if not isinstance(asset, dict):
            continue
        funding = _safe_float(asset.get("consensusFundingPercent") if asset.get("consensusFundingPercent") is not None else asset.get("maxAbsFundingPercent"))
        bias = str(asset.get("bias") or "mixed")
        signed = funding
        if funding is not None and bias == "shorts-pay":
            signed = -abs(funding)
        elif funding is not None:
            signed = abs(funding)
        quotes = [quote for quote in (asset.get("quotes") or []) if isinstance(quote, dict)]
        mark = next((_safe_float(quote.get("markPrice")) for quote in quotes if _safe_float(quote.get("markPrice")) is not None), None)
        exchange = str(quotes[0].get("exchange") or "PERP") if quotes else "PERP"
        rows.append(
            {
                "id": str(asset.get("symbol") or asset.get("asset")),
                "label": str(asset.get("asset") or asset.get("symbol") or "Perp"),
                "symbol": str(asset.get("symbol") or "").upper(),
                "metric": signed,
                "metricLabel": f"{signed:+.4f}%" if signed is not None else "--",
                "metricUnit": "FUND",
                "secondary": mark,
                "secondaryLabel": _format_price(mark),
                "tags": [exchange.upper()[:8], _bias_tag(bias)],
                "tone": "down" if signed and signed < 0 else ("up" if signed and signed > 0 else "neutral"),
            }
        )
    return _payload("crypto-perp-funding", title="CRYPTO PERPS", items=rows, summary={"venues": len(base.get("venues") or [])}, sources=base.get("sources") if isinstance(base.get("sources"), dict) else {"funding": base.get("status") or "ok"})


def build_tradfi_perps_payload(
    ctx: FinanceWatchContext,
    limit: int,
    external: Dict[str, Any],
) -> Dict[str, Any]:
    source = external.get("tradfiPerps") if isinstance(external.get("tradfiPerps"), dict) else {}
    rows: List[Dict[str, Any]] = []
    for item in source.get("items") or []:
        if not isinstance(item, dict):
            continue
        mark = _safe_float(item.get("markPx"))
        oracle = _safe_float(item.get("oraclePx"))
        basis_bps = _safe_float(item.get("basisBps"))
        change = _safe_float(item.get("changePercent") if item.get("changePercent") is not None else item.get("funding"))
        if basis_bps is None and mark is not None and oracle not in (None, 0):
            basis_bps = ((mark - float(oracle)) / float(oracle)) * 10000
        asset_class = str(item.get("assetClass") or "perp").upper()
        venue = str(item.get("venue") or item.get("source") or "PERP").upper()
        rows.append(
            {
                "id": str(item.get("symbol") or item.get("display")),
                "label": str(item.get("display") or f"{item.get('symbol')}-PERP"),
                "symbol": asset_class,
                "metric": mark,
                "metricLabel": _format_price(mark),
                "metricUnit": "MARK",
                "secondary": basis_bps,
                "secondaryLabel": f"{basis_bps:+.0f} bps" if basis_bps is not None and abs(basis_bps) > 0 else (_format_usd(item.get("dayNotional")) if item.get("dayNotional") is not None else "--"),
                "change": change,
                "changeLabel": _format_pct(change),
                "tags": [venue[:8], asset_class],
                "tone": _tone(change if change is not None else basis_bps),
            }
        )
    rows.sort(
        key=lambda item: (
            TRADFI_PERP_DISPLAY_PRIORITY.get(str(item.get("label") or "").upper(), 0),
            TRADFI_PERP_CLASS_PRIORITY.get(str(item.get("symbol") or "").upper(), 0),
            abs(_safe_float(item.get("change")) or _safe_float(item.get("secondary")) or 0.0),
        ),
        reverse=True,
    )
    return _payload("tradfi-perp-radar", title="TRADFI PERPS", items=rows[:limit], sources={"financeExternal": source.get("status") or "seed"})


def build_global_indices_payload(
    ctx: FinanceWatchContext,
    limit: int,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for label, symbol, region in GLOBAL_INDEX_SYMBOLS[:limit]:
        snapshot = _fetch_yahoo_snapshot(ctx, symbol, interval="30m", range_name="5d")
        if not isinstance(snapshot, dict):
            continue
        change = _safe_float(snapshot.get("changePercent"))
        rows.append(
            {
                "id": symbol,
                "label": label,
                "symbol": region,
                "metric": snapshot.get("price"),
                "metricLabel": _format_price(snapshot.get("price")),
                "metricUnit": "IDX",
                "change": change,
                "changeLabel": f"{change:+.2f}%" if change is not None else "--",
                "points": snapshot.get("points") or [],
                "tags": [region],
                "tone": _tone(change),
            }
        )
    avg = sum(_safe_float(row.get("change")) or 0.0 for row in rows) / len(rows) if rows else None
    return _payload("global-index-monitor", title="GLOBAL INDICES", items=rows, summary={"riskTone": "RISK ON" if avg and avg > 0 else "RISK OFF" if avg and avg < 0 else "MIXED", "avgChange": avg}, sources={"yahoo": "ok" if rows else "empty"})


def build_crypto_etf_payload(
    ctx: FinanceWatchContext,
    limit: int,
    external: Dict[str, Any],
) -> Dict[str, Any]:
    source = external.get("etfFlow") if isinstance(external.get("etfFlow"), dict) else {}
    rows = []
    for item in source.get("items") or []:
        if not isinstance(item, dict):
            continue
        flow = _safe_float(item.get("flowProxyUsd"))
        change = _safe_float(item.get("changePercent"))
        symbol = str(item.get("symbol") or "ETF")
        issuer = str(item.get("issuer") or ("BTC ETF" if symbol not in {"ETHA", "FETH"} else "ETH ETF"))
        rows.append(
            {
                "id": symbol,
                "label": symbol,
                "symbol": _short_etf_issuer(issuer),
                "issuer": issuer,
                "metric": flow,
                "metricLabel": _format_usd(flow),
                "metricUnit": "FLOW",
                "secondary": item.get("volume"),
                "secondaryLabel": _format_volume(item.get("volume")),
                "change": change,
                "changeLabel": _format_pct(change),
                "tags": ["INFLOW" if flow and flow > 0 else "OUTFLOW" if flow and flow < 0 else "PROXY"],
                "tone": _tone(flow),
            }
        )
    total_volume = sum(_safe_float(row.get("secondary")) or 0.0 for row in rows)
    inflows = sum(1 for row in rows if (_safe_float(row.get("metric")) or 0.0) > 0)
    outflows = sum(1 for row in rows if (_safe_float(row.get("metric")) or 0.0) < 0)
    return _payload("crypto-etf-flow", title="CRYPTO ETF", items=rows[:limit], summary={"netFlowProxyUsd": source.get("netFlowProxyUsd"), "totalVolume": total_volume, "inflowCount": inflows, "outflowCount": outflows}, sources={"financeExternal": source.get("status") or "seed"})


def build_stablecoin_payload(
    ctx: FinanceWatchContext,
    limit: int,
    external: Dict[str, Any],
) -> Dict[str, Any]:
    source = external.get("stablecoin") if isinstance(external.get("stablecoin"), dict) else {}
    rows = []
    for item in source.get("items") or []:
        if not isinstance(item, dict):
            continue
        deviation = _safe_float(item.get("deviationBps"))
        change = _safe_float(item.get("change7dPct"))
        rows.append(
            {
                "id": str(item.get("symbol") or item.get("name")),
                "label": str(item.get("symbol") or "Stablecoin"),
                "symbol": str(item.get("name") or "SUPPLY")[:18],
                "metric": item.get("price"),
                "metricLabel": f"{_format_price(item.get('price'), digits=4)}  SUPPLY {_format_usd(item.get('supplyUsd'))}",
                "metricUnit": "PEG",
                "secondary": item.get("supplyUsd"),
                "secondaryLabel": None,
                "change": change,
                "changeLabel": _format_pct(change),
                "tags": ["WATCH"] if abs(deviation or 0.0) >= 20 else [],
                "tone": "down" if abs(deviation or 0.0) >= 20 else _tone(change),
            }
        )
    return _payload("stablecoin-monitor", title="STABLECOINS", items=rows[:limit], summary={"totalSupplyUsd": source.get("totalSupplyUsd"), "supplyChange7dPct": source.get("supplyChange7dPct"), "stressedCount": source.get("stressedCount")}, sources={"financeExternal": source.get("status") or "seed"})


def _format_usd(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "--"
    sign = "-" if number < 0 else ""
    number = abs(number)
    for suffix, divisor in (("T", 1_000_000_000_000), ("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if number >= divisor:
            return f"{sign}${number / divisor:.1f}{suffix}"
    return f"{sign}${number:.0f}"


def _format_volume(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "--"
    sign = "-" if number < 0 else ""
    number = abs(number)
    for suffix, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if number >= divisor:
            return f"{sign}{number / divisor:.1f}{suffix}"
    return f"{sign}{number:.0f}"


def _bias_tag(value: str) -> str:
    if value == "longs-pay":
        return "LONGS PAY"
    if value == "shorts-pay":
        return "SHORTS PAY"
    return "MIXED"


def _short_etf_issuer(value: Any) -> str:
    issuer = str(value or "").strip()
    lowered = issuer.lower()
    if "ishares" in lowered:
        return "BlackRock"
    if "fidelity" in lowered:
        return "Fidelity"
    if "grayscale" in lowered:
        return "Grayscale"
    if "bitwise" in lowered:
        return "Bitwise"
    if "ark" in lowered or "21shares" in lowered:
        return "ARK/21Shares"
    if "vaneck" in lowered:
        return "VanEck"
    if "franklin" in lowered:
        return "Franklin"
    if "invesco" in lowered:
        return "Invesco"
    if "valkyrie" in lowered:
        return "Valkyrie"
    if "wisdomtree" in lowered:
        return "WisdomTree"
    return issuer or "ETF"
