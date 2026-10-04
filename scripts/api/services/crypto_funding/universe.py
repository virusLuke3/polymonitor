from __future__ import annotations

import re
import time
from functools import lru_cache
from typing import Callable

from .contracts import MAX_LIMIT, timestamp

# A broad contextual watchlist supplements, rather than substitutes for, active
# Polymarket asset discovery. Trading eligibility is always venue-authoritative.
ASSET_NAMES = {
    "BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "XRP": "XRP", "HYPE": "Hyperliquid",
    "DOGE": "Dogecoin", "BNB": "BNB", "SUI": "Sui", "ADA": "Cardano", "AVAX": "Avalanche",
    "LINK": "Chainlink", "ZEC": "Zcash", "TAO": "Bittensor", "LTC": "Litecoin", "BCH": "Bitcoin Cash",
    "AAVE": "Aave", "UNI": "Uniswap", "PEPE": "Pepe", "SHIB": "Shiba Inu", "BONK": "Bonk",
    "TRUMP": "Official Trump", "PUMP": "Pump.fun", "WLFI": "World Liberty Financial", "WIF": "dogwifhat",
    "NEAR": "Near", "APT": "Aptos", "DOT": "Polkadot", "ARB": "Arbitrum", "OP": "Optimism",
    "SEI": "Sei", "TIA": "Celestia", "ENA": "Ethena", "TON": "Toncoin", "TRX": "Tron", "ETC": "Ethereum Classic",
    "FET": "Fetch.ai", "RENDER": "Render", "INJ": "Injective", "JUP": "Jupiter", "ONDO": "Ondo",
    "POL": "Polygon", "ATOM": "Cosmos", "XLM": "Stellar", "HBAR": "Hedera", "ALGO": "Algorand",
    "ICP": "Internet Computer", "FIL": "Filecoin", "CRV": "Curve", "LDO": "Lido", "DYDX": "dYdX",
    "EIGEN": "EigenLayer", "PYTH": "Pyth", "S": "Sonic", "GRT": "The Graph", "JTO": "Jito",
    "WLD": "Worldcoin", "STX": "Stacks", "IMX": "Immutable", "SAND": "The Sandbox", "GALA": "Gala",
    "APE": "ApeCoin", "MKR": "Maker", "PENDLE": "Pendle", "ENS": "Ethereum Name Service", "ETHFI": "Ether.fi",
    "TRB": "Tellor", "RUNE": "THORChain", "VIRTUAL": "Virtuals", "FLOKI": "Floki", "MORPHO": "Morpho",
    "ZEN": "Horizen", "DASH": "Dash", "XMR": "Monero", "BGB": "Bitget Token", "OKB": "OKB",
    "ASTER": "Aster", "BERA": "Berachain", "IP": "Story", "KAS": "Kaspa", "RAY": "Raydium", "ZK": "ZKsync",
}
CORE_ORDER = list(ASSET_NAMES)
UNIVERSE_SECONDS = 900


def underlying(base: str) -> str:
    base = str(base or "").upper()
    # These multiplier contracts have provider-declared bases; do not strip
    # arbitrary numbers from unrelated tokens (e.g. 1INCH).
    for prefix in ("1000000", "10000", "1000"):
        if base.startswith(prefix) and base[len(prefix):] in {"PEPE", "SHIB", "BONK", "FLOKI", "XEC", "SATS", "RATS", "CAT"}:
            return base[len(prefix):]
    return base


@lru_cache(maxsize=1)
def _name_matcher():
    names = {name.lower(): asset for asset, name in ASSET_NAMES.items() if name != asset}
    expression = r"(?<![a-z0-9])(" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")(?![a-z0-9])"
    return re.compile(expression, re.I), names


def event_assets(event: dict, eligible_assets: set[str]) -> set[str]:
    # Never lower-case the entire venue symbol catalogue into ordinary words.
    # A single compiled name matcher also avoids millions of regex compilations
    # on a large Gamma scan. Longer names consume Bitcoin Cash before Bitcoin.
    title = str(event.get("title") or "")
    matcher, names = _name_matcher()
    ambiguous_names = {"near", "render", "maker", "curve", "stellar", "immutable", "sonic", "story"}
    found = set()
    for match in matcher.finditer(title):
        name = match.group(0).lower()
        if name in ambiguous_names and not re.search(r"^(?:what price will |will |can )?" + re.escape(name)
                + r"\s+(?:price|hit|reach|be|above|below|up|outperform)", title, re.I):
            continue
        found.add(names[name])
    generic = {"THE", "ONE", "ALL", "TOKEN", "COIN", "HIGH", "CAP", "NET", "OPEN", "MOVE", "GAS", "ACT", "FUN", "BASED", "ARC", "AI", "FDV", "USD", "US", "UK", "EU", "USA", "CEO", "ETF", "SEC", "NEW"}
    for match in re.finditer(r"(?<![A-Za-z0-9])\$?([A-Z][A-Z0-9]{0,23})(?![A-Za-z0-9])", title):
        symbol = match.group(1)
        explicit = match.group(0).startswith("$")
        if (symbol in ASSET_NAMES or symbol in eligible_assets) and (explicit or (len(symbol) >= 2 and symbol not in generic)):
            found.add(symbol)
    return found


def market_relations(events: list[dict], *, eligible_assets: set[str], now: str) -> dict[str, dict]:
    result: dict[str, dict] = {}
    seen: set[str] = set()
    for event in events:
        if event.get("closed") is True or event.get("active") is False:
            continue
        tags = {str(tag.get("slug") or "").lower() for tag in event.get("tags", []) if isinstance(tag, dict)}
        for market in event.get("markets", []):
            if not isinstance(market, dict) or market.get("closed") is True or market.get("active") is False or market.get("acceptingOrders") is False:
                continue
            market_id = str(market.get("id") or "")
            # Bind the actual question, not every child of a multi-asset event.
            # Generic sibling questions must not inherit another token's name.
            question = str(market.get("question") or "")
            assets = event_assets({"title": question} if question else event, eligible_assets)
            if not assets:
                continue
            end_at = market.get("endDate") or event.get("endDate")
            end = timestamp(end_at)
            if not market_id or market_id in seen or (end is not None and end <= timestamp(now)):
                continue
            seen.add(market_id)
            price = "crypto-prices" in tags and end is not None
            slug = str(event.get("slug") or "")
            for asset in assets:
                relation = result.setdefault(asset, {"marketCount": 0, "priceMarketCount": 0, "relatedMarkets": []})
                relation["marketCount"] += 1
                relation["priceMarketCount"] += int(price)
                # Store only a few links per asset, not entire Gamma markets.
                if len(relation["relatedMarkets"]) < 3 and re.fullmatch(r"[a-zA-Z0-9_-]+", slug):
                    relation["relatedMarkets"].append({
                        "id": market_id, "eventId": str(event.get("id") or ""),
                        "title": str(market.get("question") or event.get("title") or asset)[:220],
                        "url": f"https://polymarket.com/event/{slug}", "endAt": end_at,
                        "relation": "price-asset" if price else "asset-context",
                    })
    return result


def discover_markets(get: Callable, *, base_url: str, eligible_assets: set[str], now: str, clock: Callable | None = None) -> dict:
    """Bounded active-crypto scan. It never claims full market coverage."""
    base = base_url.rstrip("/")
    if not base:
        return {"status": "unavailable", "assets": {}, "observedAt": None}
    deadline = time.monotonic() + 12
    def request(path: str, params: dict | None = None):
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError("market-universe-deadline")
        return get(f"{base}{path}", params=params, timeout=min(5, left))
    tag = request("/tags/slug/crypto")
    if not isinstance(tag, dict) or tag.get("slug") != "crypto" or not str(tag.get("id") or "").isdigit():
        raise ValueError("invalid-crypto-tag")
    events = []
    truncated = False
    for page in range(5):
        rows = request("/events", {"active": "true", "closed": "false", "tag_id": tag["id"],
                                   "order": "volume24hr", "ascending": "false", "limit": 100, "offset": page * 100})
        if not isinstance(rows, list):
            raise ValueError("invalid-crypto-events")
        events.extend(row for row in rows if isinstance(row, dict))
        if len(rows) < 100:
            break
        truncated = page == 4
    finished = clock() if clock else now
    return {"status": "ok", "observedAt": finished, "scanLimit": 500, "scannedEvents": len(events),
            "truncated": truncated, "assets": market_relations(events, eligible_assets=eligible_assets, now=finished)}


def select_assets(catalogs: dict[str, dict], market_universe: dict, configured_symbols: tuple[str, ...]) -> list[str]:
    configured = [underlying(symbol.removesuffix("USDT")) for symbol in configured_symbols if symbol.endswith("USDT")]
    markets = market_universe.get("assets") or {}
    linked = sorted(markets, key=lambda asset: (-int(markets[asset].get("priceMarketCount", 0)), -int(markets[asset].get("marketCount", 0)), asset))
    # Retain unsupported linked/core assets in selection so coverage can explain
    # why they have no funding instead of silently assigning zero.
    ordered = list(dict.fromkeys(linked + CORE_ORDER + configured))
    return ordered[:MAX_LIMIT]
