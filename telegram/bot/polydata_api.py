from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Optional

import requests


WORLDCUP_QUERY_ALIASES = {
    "墨西哥": "Mexico",
    "南非": "South Africa",
    "韩国": "South Korea",
    "捷克": "Czech Republic",
    "美国": "USA",
    "加拿大": "Canada",
    "巴西": "Brazil",
    "摩洛哥": "Morocco",
    "德国": "Germany",
    "荷兰": "Netherlands",
    "日本": "Japan",
    "英格兰": "England",
    "法国": "France",
    "西班牙": "Spain",
    "葡萄牙": "Portugal",
}


def _unique_urls(values: Iterable[str]) -> tuple[str, ...]:
    urls: list[str] = []
    seen: set[str] = set()
    for value in values:
        url = str(value or "").strip().rstrip("/")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return tuple(urls)


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(value or ""))


def _expand_worldcup_query(query: str) -> str:
    expanded = str(query or "").strip()
    for alias, value in WORLDCUP_QUERY_ALIASES.items():
        expanded = expanded.replace(alias, value)
    return " ".join(expanded.split())


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


class PolyDataBotApi:
    def __init__(self, *, base_url: str, timeout_seconds: int = 12, base_urls: Optional[Iterable[str]] = None) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.base_urls = _unique_urls((self.base_url, *(base_urls or ())))
        self.timeout_seconds = max(1, int(timeout_seconds or 12))
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"Accept": "application/json", "User-Agent": "polydata-telegram-bot/1.0"})
        self.worldcup_local_market_search_enabled = _env_bool("POLYDATA_TELEGRAM_WORLDCUP_LOCAL_MARKET_SEARCH", False)

    def get_json(self, path: str, *, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not self.base_urls:
            raise RuntimeError("POLYDATA_TELEGRAM_BOT_POLYDATA_API_BASE is required")
        last_error: Optional[Exception] = None
        for base_url in self.base_urls:
            try:
                response = self.session.get(f"{base_url}{path}", params=params or {}, timeout=self.timeout_seconds)
                if response.status_code == 404:
                    return {"error": "not_found", "_status": 404}
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {"items": payload if isinstance(payload, list) else []}
            except requests.RequestException as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise RuntimeError("No polyData API base URLs configured")

    def search_markets(self, query: str, *, limit: int = 5) -> Dict[str, Any]:
        cleaned = str(query or "").strip()
        if cleaned.isdigit():
            return self.get_json(f"/markets/{int(cleaned)}/detail")
        if cleaned and "/" not in cleaned and " " not in cleaned and len(cleaned) > 10 and not cleaned.startswith("0x"):
            slug_payload = self.get_json(f"/markets/{cleaned}")
            if not slug_payload.get("error"):
                return {"items": [slug_payload]}
        return self.get_json("/markets", params={"q": cleaned, "pageSize": limit})

    def gamma_search_markets(self, query: str, *, limit: int = 8) -> Dict[str, Any]:
        base_url = str(os.environ.get("POLYDATA_GAMMA_API_BASE") or "https://gamma-api.polymarket.com").rstrip("/")
        rows: list[Dict[str, Any]] = []
        seen: set[str] = set()
        for path in ("/markets", "/events"):
            try:
                response = self.session.get(f"{base_url}{path}", params={"q": query, "limit": limit}, timeout=self.timeout_seconds)
                response.raise_for_status()
                payload = response.json()
            except requests.RequestException:
                continue
            items = payload if isinstance(payload, list) else payload.get("data") if isinstance(payload, dict) else []
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                nested_markets = item.get("markets") if isinstance(item.get("markets"), list) else []
                candidates = nested_markets if nested_markets else [item]
                for candidate in candidates:
                    if not isinstance(candidate, dict):
                        continue
                    title = str(candidate.get("question") or candidate.get("title") or item.get("title") or "").strip()
                    slug = str(candidate.get("slug") or item.get("slug") or "").strip()
                    key = slug or title
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        **candidate,
                        "title": title,
                        "marketTitle": title,
                        "slug": slug,
                        "eventTitle": item.get("title"),
                        "source": "gamma",
                    })
                    if len(rows) >= limit:
                        return {"items": rows}
        return {"items": rows}

    def worldcup_market_search(self, query: str, *, limit: int = 8) -> Dict[str, Any]:
        variants = []
        cleaned = str(query or "").strip()
        if cleaned:
            expanded = _expand_worldcup_query(cleaned)
            for base in (expanded, cleaned):
                if base and base not in variants:
                    variants.extend([base, f"world cup {base}", f"fifa world cup {base}", f"{base} winner"])
        rows: list[Dict[str, Any]] = []
        seen: set[str] = set()
        for variant in variants:
            payloads: list[Dict[str, Any]] = []
            if self.worldcup_local_market_search_enabled and not _contains_cjk(variant):
                try:
                    payloads.append(self.search_markets(variant, limit=limit))
                except requests.RequestException:
                    pass
            try:
                payloads.append(self.gamma_search_markets(variant, limit=limit))
            except requests.RequestException:
                pass
            for payload in payloads:
                for item in payload.get("items") if isinstance(payload.get("items"), list) else []:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("slug") or item.get("id") or item.get("title") or item.get("marketTitle") or "")
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    rows.append(item)
                    if len(rows) >= limit:
                        return {"items": rows}
        return {"items": rows}

    def alpha_signals(self, *, limit: int = 5) -> Dict[str, Any]:
        return self.get_json("/runtime/signals/alpha", params={"limit": limit})

    def crypto_markets(self) -> Dict[str, Any]:
        return self.get_json("/runtime/markets/crypto")

    def wallet_summary(self, address: str, *, days: int = 30) -> Dict[str, Any]:
        return self.get_json(f"/analytics/addresses/{address}", params={"days": days})

    def wallet_trades(self, address: str, *, limit: int = 5) -> Dict[str, Any]:
        return self.get_json(f"/analytics/addresses/{address}/trades", params={"limit": limit})

    def pnl(self, address: str) -> Dict[str, Any]:
        return self.get_json(f"/bot/pnl/{address}")

    def worldcup_dashboard(self) -> Dict[str, Any]:
        return self.get_json("/runtime/worldcup/dashboard")

    def worldcup_intel(self, *, limit: int = 24) -> Dict[str, Any]:
        return self.get_json("/runtime/sports/worldcup-intel", params={"limit": limit})
