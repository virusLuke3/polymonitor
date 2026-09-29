from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlencode

from api.context import resolve_optional_service_callable

try:
    import requests
except ImportError:  # pragma: no cover - watcher validates dependency.
    requests = None

from api.services import crypto_funding_service, finance_external_sources_service

FINANCE_WATCH_CACHE_KEY = "v1"


@dataclass(frozen=True)
class FinanceWatchDependencies:
    settings: Any
    http_json_get: Callable[..., Any] | None
    http_text_get: Callable[..., Any] | None
    get_yahoo_market_snapshot: Callable[..., Any] | None
    snapshot_store: Any
    get_cached_json: Callable[..., Any] | None
    set_cached_json: Callable[..., Any] | None
    get_snapshot_payload: Callable[..., Any] | None
    get_crypto_funding_watch_snapshot: Callable[..., Any] | None
    crypto_funding: crypto_funding_service.CryptoFundingDependencies
    external_sources: finance_external_sources_service.FinanceExternalSourceDependencies

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> FinanceWatchDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            settings=context.get("SETTINGS"),
            http_json_get=resolve_optional_service_callable(
                context,
                "http_json_get",
            ),
            http_text_get=resolve_optional_service_callable(
                context,
                "http_text_get",
            ),
            get_yahoo_market_snapshot=resolve_optional_service_callable(
                context,
                "get_yahoo_market_snapshot",
            ),
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
            get_crypto_funding_watch_snapshot=(
                resolve_optional_service_callable(
                    context,
                    "get_crypto_funding_watch_snapshot",
                )
            ),
            crypto_funding=(
                crypto_funding_service.CryptoFundingDependencies.from_context(
                    context,
                )
            ),
            external_sources=(
                finance_external_sources_service.FinanceExternalSourceDependencies.from_context(
                    context,
                )
            ),
        )


FinanceWatchContext = Mapping[str, Any] | FinanceWatchDependencies


def _dependencies(
    context: FinanceWatchContext,
) -> FinanceWatchDependencies:
    if isinstance(context, FinanceWatchDependencies):
        return context
    return FinanceWatchDependencies.from_context(context)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def finance_watch_namespace(panel_id: str) -> str:
    return f"runtime:finance:{panel_id}"


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compact_source(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:34] if text else "source"


def _strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _setting(ctx: FinanceWatchContext, name: str) -> str:
    dependencies = _dependencies(ctx)
    value = getattr(dependencies.settings, name, "") if dependencies.settings is not None else ""
    return str(value or "").strip()


def _tone(value: Any, *, inverted: bool = False) -> str:
    number = _safe_float(value)
    if number is None:
        return "neutral"
    if inverted:
        number = -number
    if number > 0:
        return "up"
    if number < 0:
        return "down"
    return "neutral"


def _http_json_get(
    ctx: FinanceWatchContext,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    timeout: int = 12,
) -> Any:
    dependencies = _dependencies(ctx)
    if dependencies.http_json_get is not None:
        try:
            return dependencies.http_json_get(
                url,
                params=params,
                timeout=timeout,
                headers={
                    "User-Agent": "polydata-finance-watch/1.0",
                    "Accept": "application/json",
                },
            )
        except Exception:
            pass
    if requests is None:
        raise RuntimeError("requests package is required")
    session = requests.Session()
    session.trust_env = True
    try:
        response = session.get(url, params=params, timeout=timeout, headers={"User-Agent": "polydata-finance-watch/1.0", "Accept": "application/json"})
        response.raise_for_status()
        return response.json() if response.content else None
    finally:
        session.close()


def _http_text_get(
    ctx: FinanceWatchContext,
    url: str,
    *,
    timeout: int = 12,
    headers: Optional[Dict[str, str]] = None,
) -> str:
    dependencies = _dependencies(ctx)
    request_headers = {"User-Agent": "polydata-finance-watch/1.0", "Accept": "application/rss+xml,application/xml,text/xml"}
    if headers:
        request_headers.update(headers)
    if dependencies.http_text_get is not None:
        try:
            return dependencies.http_text_get(
                url,
                timeout=timeout,
                headers=request_headers,
            )
        except Exception:
            pass
    if requests is None:
        raise RuntimeError("requests package is required")
    session = requests.Session()
    session.trust_env = True
    try:
        response = session.get(url, timeout=timeout, headers=request_headers)
        response.raise_for_status()
        return response.text
    finally:
        session.close()


def _news_url(ctx: FinanceWatchContext, query: str) -> str:
    # URL is supplied through POLYDATA_FINANCE_GOOGLE_NEWS_RSS_URL.
    return f"{_setting(ctx, 'finance_google_news_rss_url')}?{urlencode({'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})}"


def _fetch_yahoo_snapshot(
    ctx: FinanceWatchContext,
    symbol: str,
    *,
    interval: str = "30m",
    range_name: str = "5d",
) -> Optional[Dict[str, Any]]:
    dependencies = _dependencies(ctx)
    try:
        if dependencies.get_yahoo_market_snapshot is None:
            raise RuntimeError("get_yahoo_market_snapshot helper missing")
        quote = dependencies.get_yahoo_market_snapshot(
            symbol,
            interval=interval,
            range_name=range_name,
            ttl_seconds=300,
        )
    except Exception:
        quote = None
    if isinstance(quote, dict) and quote.get("price") is not None:
        return quote
    payload = _http_json_get(
        ctx,
        _setting(ctx, "finance_yahoo_chart_url_template").format(symbol=symbol),
        params={"range": range_name, "interval": "1d" if range_name != "1d" else "5m"},
        timeout=12,
    )
    result = (payload.get("chart") or {}).get("result") if isinstance(payload, dict) else []
    chart = result[0] if isinstance(result, list) and result else {}
    quote_rows = (chart.get("indicators") or {}).get("quote") or []
    quote_data = quote_rows[0] if quote_rows and isinstance(quote_rows[0], dict) else {}
    timestamps = chart.get("timestamp") or []
    closes = [value for value in (quote_data.get("close") or []) if value is not None]
    volumes = [value for value in (quote_data.get("volume") or []) if value is not None]
    if not closes:
        return None
    price = _safe_float(closes[-1])
    previous = _safe_float(closes[-2]) if len(closes) >= 2 else None
    points = []
    start = max(0, len(closes) - 260)
    for offset, value in enumerate(closes[start:]):
        index = start + offset
        timestamp = timestamps[index] if index < len(timestamps) else None
        points.append({"timestamp": timestamp, "value": value})
    return {
        "price": price,
        "changePercent": ((price - previous) / previous * 100) if price is not None and previous not in (None, 0) else None,
        "volume24h": _safe_float(volumes[-1]) if volumes else None,
        "points": points,
    }


def _payload(panel_id: str, *, title: str, items: List[Dict[str, Any]], summary: Optional[Dict[str, Any]] = None, sources: Optional[Dict[str, Any]] = None, status: Optional[str] = None, generated_at: Optional[str] = None) -> Dict[str, Any]:
    return {
        "generatedAt": generated_at or utc_now_iso(),
        "status": status or ("ok" if items else "empty"),
        "cacheMode": "live-build",
        "panelId": panel_id,
        "title": title,
        "sources": sources or {},
        "summary": {"count": len(items), **(summary or {})},
        "items": items,
    }


def _format_price(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    if number is None:
        return "--"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    if abs(number) < 1:
        return f"{number:.4f}".rstrip("0").rstrip(".")
    return f"{number:,.{digits}f}".rstrip("0").rstrip(".")


def _format_pct(value: Any) -> str:
    number = _safe_float(value)
    if number is None:
        return "--"
    return f"{number:+.2f}%"


def _short_time(value: Any) -> str:
    if not value:
        return "--"
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "--"
    delta = timestamp - datetime.now(timezone.utc)
    hours = int(delta.total_seconds() // 3600)
    if hours > 0:
        return f"{hours}h reset"
    minutes = int(delta.total_seconds() // 60)
    return f"{max(0, minutes)}m reset"
