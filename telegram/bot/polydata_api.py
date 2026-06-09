from __future__ import annotations

from typing import Any, Dict, Iterable, Optional

import requests


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


class PolyDataBotApi:
    def __init__(self, *, base_url: str, timeout_seconds: int = 12, base_urls: Optional[Iterable[str]] = None) -> None:
        self.base_url = str(base_url or "").rstrip("/")
        self.base_urls = _unique_urls((self.base_url, *(base_urls or ())))
        self.timeout_seconds = max(1, int(timeout_seconds or 12))
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"Accept": "application/json", "User-Agent": "polydata-telegram-bot/1.0"})

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
