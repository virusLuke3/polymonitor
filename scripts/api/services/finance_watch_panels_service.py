from __future__ import annotations

from typing import Any, Dict, Optional

from api.services import finance_external_sources_service, seed_recovery
from api.services.finance_watch.common import (
    FINANCE_WATCH_CACHE_KEY,
    FinanceWatchContext,
    _dependencies,
    _payload,
    finance_watch_namespace,
)
from api.services.finance_watch.common import (
    FinanceWatchDependencies as FinanceWatchDependencies,
)
from api.services.finance_watch.common import (
    _safe_float as _safe_float,
)
from api.services.finance_watch.markets import (
    build_crypto_etf_payload,
    build_crypto_perps_payload,
    build_defi_yields_payload,
    build_global_indices_payload,
    build_stablecoin_payload,
    build_tradfi_perps_payload,
)
from api.services.finance_watch.news import (
    build_news_payload,
)
from api.services.finance_watch.research import (
    build_broker_research_payload,
)
from api.services.finance_watch.sentiment import (
    build_fear_greed_payload,
)

FINANCE_WATCH_TTL_SECONDS = 10 * 60


FINANCE_WATCH_PANEL_IDS = (
    "defi-yield-monitor",
    "defi-security-watch",
    "crypto-perp-funding",
    "tradfi-perp-radar",
    "ipo-news-watch",
    "broker-research-watch",
    "global-index-monitor",
    "crypto-fear-greed",
    "crypto-etf-flow",
    "stablecoin-monitor",
    "blockchain-policy-news",
)


def _read_finance_external(
    ctx: FinanceWatchContext,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    payload = finance_external_sources_service.read_finance_external_sources(
        dependencies.external_sources,
    )
    if isinstance(payload, dict) and payload:
        return payload
    try:
        return finance_external_sources_service.build_finance_external_sources_payload(
            dependencies.external_sources,
        )
    except Exception:
        return {}


def build_finance_watch_panel_payload(
    ctx: FinanceWatchContext,
    panel_id: str,
    limit: int = 10,
    external: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    limit = max(3, min(36, int(limit or 10)))
    if panel_id == "defi-yield-monitor":
        return build_defi_yields_payload(dependencies, limit)
    if panel_id == "defi-security-watch":
        return build_news_payload(
            dependencies,
            panel_id,
            "DEFI SECURITY",
            limit,
        )
    if panel_id == "crypto-perp-funding":
        return build_crypto_perps_payload(dependencies, limit)
    if panel_id == "tradfi-perp-radar":
        return build_tradfi_perps_payload(
            dependencies,
            limit,
            external or _read_finance_external(dependencies),
        )
    if panel_id == "ipo-news-watch":
        return build_news_payload(
            dependencies,
            panel_id,
            "IPO NEWS",
            limit,
        )
    if panel_id == "broker-research-watch":
        return build_broker_research_payload(dependencies, limit)
    if panel_id == "global-index-monitor":
        return build_global_indices_payload(dependencies, limit)
    if panel_id == "crypto-fear-greed":
        return build_fear_greed_payload(dependencies, limit)
    if panel_id == "crypto-etf-flow":
        return build_crypto_etf_payload(
            dependencies,
            limit,
            external or _read_finance_external(dependencies),
        )
    if panel_id == "stablecoin-monitor":
        return build_stablecoin_payload(
            dependencies,
            limit,
            external or _read_finance_external(dependencies),
        )
    if panel_id == "blockchain-policy-news":
        return build_news_payload(
            dependencies,
            panel_id,
            "CHAIN POLICY",
            limit,
        )
    raise KeyError(f"unknown finance watch panel: {panel_id}")


def build_all_finance_watch_panel_payloads(
    ctx: FinanceWatchContext,
    limit: int = 24,
) -> Dict[str, Dict[str, Any]]:
    dependencies = _dependencies(ctx)
    external = _read_finance_external(dependencies)
    payloads: Dict[str, Dict[str, Any]] = {}
    for panel_id in FINANCE_WATCH_PANEL_IDS:
        try:
            payloads[panel_id] = build_finance_watch_panel_payload(
                dependencies,
                panel_id,
                limit=limit,
                external=external,
            )
        except Exception as exc:
            payloads[panel_id] = _payload(panel_id, title=panel_id.upper(), items=[], status="error", sources={"builder": "error"}, summary={"error": str(exc)})
    return payloads


def _trim_payload(payload: Dict[str, Any], limit: int) -> Dict[str, Any]:
    items = [item for item in (payload.get("items") or []) if isinstance(item, dict)]
    return {**payload, "items": items[: max(0, int(limit or 10))], "summary": {**(payload.get("summary") if isinstance(payload.get("summary"), dict) else {}), "count": min(len(items), max(0, int(limit or 10))), "totalCount": len(items)}}


def get_finance_watch_panel_snapshot(
    ctx: FinanceWatchContext,
    panel_id: str,
    limit: int = 10,
) -> Dict[str, Any]:
    dependencies = _dependencies(ctx)
    limit = max(3, min(36, int(limit or 10)))
    ttl_seconds = FINANCE_WATCH_TTL_SECONDS
    payload = seed_recovery.read_watch_seed(
        namespace=finance_watch_namespace(panel_id), cache_key=FINANCE_WATCH_CACHE_KEY, panel_id=panel_id,
        snapshot_store=dependencies.snapshot_store, redis_get=dependencies.get_cached_json, redis_set=dependencies.set_cached_json,
        builder=lambda: build_finance_watch_panel_payload(dependencies, panel_id, limit=max(limit, 24)), ttl_seconds=ttl_seconds,
    )
    return _trim_payload(payload, limit)
