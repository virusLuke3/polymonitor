from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, cast

from api.context import RuntimeResources, runtime_resources, resolve_service_callable
from api.runtime_panels import get_default_panel_ids


SNAPSHOT_PREWARM_INTERVAL_SECONDS = 15


def _service_callable(
    context: Mapping[str, Any],
    name: str,
) -> Callable[..., Any]:
    return resolve_service_callable(context, name)


@dataclass(frozen=True)
class DashboardBuildDependencies:
    fetch_market_status: Callable[..., Any]
    fetch_trade_volume: Callable[..., Any]
    fetch_recent_markets: Callable[..., Any]
    fetch_trade_window_bounds: Callable[..., Any]
    fetch_trade_count_estimate: Callable[..., Any]
    query_one: Callable[..., Any]
    iso_days_before: Callable[..., Any]
    utc_now_iso: Callable[..., Any]
    recent_trade_window: int
    cache_ttl_seconds: int

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> DashboardBuildDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            fetch_market_status=_service_callable(
                context,
                "fetch_dashboard_market_status",
            ),
            fetch_trade_volume=_service_callable(
                context,
                "fetch_dashboard_trade_volume",
            ),
            fetch_recent_markets=_service_callable(
                context,
                "fetch_dashboard_recent_markets",
            ),
            fetch_trade_window_bounds=_service_callable(
                context,
                "fetch_recent_trade_window_bounds",
            ),
            fetch_trade_count_estimate=_service_callable(
                context,
                "fetch_trade_count_estimate",
            ),
            query_one=_service_callable(context, "query_one"),
            iso_days_before=_service_callable(context, "iso_days_before"),
            utc_now_iso=_service_callable(context, "utc_now_iso"),
            recent_trade_window=int(
                context.get("RECENT_TRADE_WINDOW", 0)
            ),
            cache_ttl_seconds=int(
                context.get("DASHBOARD_CACHE_TTL_SECONDS", 0)
            ),
        )


@dataclass(frozen=True)
class DashboardCacheDependencies:
    resources: RuntimeResources
    builder: DashboardBuildDependencies
    application: Any
    snapshot_store: Any
    cache: dict[str, Any]
    cache_lock: Any
    get_cached_json: Callable[..., Any]
    set_cached_json: Callable[..., Any]
    utc_now_iso: Callable[..., Any]
    recent_trade_window: int
    cache_ttl_seconds: int

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> DashboardCacheDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            resources=runtime_resources(context),
            builder=DashboardBuildDependencies.from_context(context),
            application=context.get("app"),
            snapshot_store=context.get("SNAPSHOT_STORE"),
            cache=cast(
                dict[str, Any],
                context.get("_dashboard_cache", {}),
            ),
            cache_lock=context.get("_dashboard_cache_lock"),
            get_cached_json=_service_callable(context, "get_cached_json"),
            set_cached_json=_service_callable(context, "set_cached_json"),
            utc_now_iso=_service_callable(context, "utc_now_iso"),
            recent_trade_window=int(
                context.get("RECENT_TRADE_WINDOW", 0)
            ),
            cache_ttl_seconds=int(
                context.get("DASHBOARD_CACHE_TTL_SECONDS", 0)
            ),
        )


@dataclass(frozen=True)
class BootstrapPrewarmDependencies:
    resources: RuntimeResources
    application: Any
    commodity_symbols: Sequence[Any]
    finance_runtime_ttl_seconds: int
    signal_runtime_ttl_seconds: int
    snapshot_prewarm_enabled: bool
    get_market_group_snapshot: Callable[..., Any]
    get_finance_market_atlas_snapshot: Callable[..., Any]
    get_equity_event_command_snapshot: Callable[..., Any]
    get_onchain_tradfi_perp_radar_snapshot: Callable[..., Any]
    get_finance_liquidity_regime_snapshot: Callable[..., Any]
    get_whale_trades_snapshot: Callable[..., Any]
    get_suspicious_trades_snapshot: Callable[..., Any]
    get_alpha_signal_snapshot: Callable[..., Any]
    get_jin10_panel_snapshot: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> BootstrapPrewarmDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            resources=runtime_resources(context),
            application=context.get("app"),
            commodity_symbols=cast(
                Sequence[Any],
                context.get("COMMODITY_SYMBOLS", ()),
            ),
            finance_runtime_ttl_seconds=int(
                context.get("FINANCE_RUNTIME_TTL_SECONDS", 0)
            ),
            signal_runtime_ttl_seconds=int(
                context.get("SIGNAL_RUNTIME_TTL_SECONDS", 0)
            ),
            snapshot_prewarm_enabled=bool(
                context.get("SNAPSHOT_PREWARM_ENABLED", False)
            ),
            get_market_group_snapshot=_service_callable(
                context,
                "get_market_group_snapshot",
            ),
            get_finance_market_atlas_snapshot=_service_callable(
                context,
                "get_finance_market_atlas_snapshot",
            ),
            get_equity_event_command_snapshot=_service_callable(
                context,
                "get_equity_event_command_snapshot",
            ),
            get_onchain_tradfi_perp_radar_snapshot=_service_callable(
                context,
                "get_onchain_tradfi_perp_radar_snapshot",
            ),
            get_finance_liquidity_regime_snapshot=_service_callable(
                context,
                "get_finance_liquidity_regime_snapshot",
            ),
            get_whale_trades_snapshot=_service_callable(
                context,
                "get_whale_trades_snapshot",
            ),
            get_suspicious_trades_snapshot=_service_callable(
                context,
                "get_suspicious_trades_snapshot",
            ),
            get_alpha_signal_snapshot=_service_callable(
                context,
                "get_alpha_signal_snapshot",
            ),
            get_jin10_panel_snapshot=_service_callable(
                context,
                "get_jin10_panel_snapshot",
            ),
        )


def build_dashboard_payload(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    return _build_dashboard_payload(DashboardBuildDependencies.from_context(ctx))


def _build_dashboard_payload(
    dependencies: DashboardBuildDependencies,
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat().replace("+00:00", "Z")
    last_24h = (now - timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    status_rows = dependencies.fetch_market_status(now_iso)
    active_markets = sum(int(row.get("value") or 0) for row in status_rows if row.get("name") in {"Active", "Proposed"})
    settlements_row = dependencies.query_one(
        """
        SELECT COUNT(*) AS settlements_24h
        FROM oracle_events
        WHERE event_status = 'settle' AND event_time >= ?
        """,
        (last_24h,),
    )
    trade_volume_rows = dependencies.fetch_trade_volume(
        dependencies.recent_trade_window
    )
    recent_rows = dependencies.fetch_recent_markets(
        now_iso,
        dependencies.recent_trade_window,
    )
    trade_window = dependencies.fetch_trade_window_bounds(
        dependencies.recent_trade_window
    )
    trade_count_estimate = dependencies.fetch_trade_count_estimate()
    latest_trade_ts = trade_window.get("latest_timestamp")
    earliest_trade_ts = trade_window.get("earliest_timestamp")
    coverage_7d_start = dependencies.iso_days_before(latest_trade_ts, 7)
    coverage_30d_start = dependencies.iso_days_before(latest_trade_ts, 30)
    return {
        "metrics": {
            "activeMarkets": active_markets,
            "totalTrades": int(trade_count_estimate.get("table_rows") or 0),
            "settlements24h": int(settlements_row.get("settlements_24h") or 0),
        },
        "volume7d": [{"day": str(row.get("day")) if row.get("day") is not None else None, "trade_count": int(row.get("trade_count") or 0)} for row in trade_volume_rows[-7:]],
        "volume30d": [{"day": str(row.get("day")) if row.get("day") is not None else None, "trade_count": int(row.get("trade_count") or 0)} for row in trade_volume_rows[-30:]],
        "statusShare": status_rows,
        "recentActiveMarkets": [
            {
                "id": row.get("id"),
                "localMarketId": row.get("id"),
                "gammaMarketId": row.get("gamma_market_id"),
                "slug": row.get("slug"),
                "title": row.get("title"),
                "tradeCount": int(row.get("trade_count") or 0),
                "lastTradeAt": row.get("last_trade_at"),
                "status": row.get("status"),
                "endDate": row.get("end_date"),
                "latestPrice": row.get("latest_price"),
            }
            for row in recent_rows
        ],
        "metadata": {
            "generatedAt": now_iso,
            "cacheTtlSeconds": dependencies.cache_ttl_seconds,
            "tradeWindowSize": dependencies.recent_trade_window,
            "tradeWindowEarliestTimestamp": earliest_trade_ts,
            "tradeWindowLatestTimestamp": latest_trade_ts,
            "tradeWindowSource": trade_window.get("source"),
            "tradeWindowCovers7d": bool(coverage_7d_start and earliest_trade_ts and earliest_trade_ts <= coverage_7d_start),
            "tradeWindowCovers30d": bool(coverage_30d_start and earliest_trade_ts and earliest_trade_ts <= coverage_30d_start),
            "totalTradesSource": "information_schema.table_rows",
            "totalTradesAutoIncrement": int(trade_count_estimate.get("auto_increment") or 0),
        },
    }


def _build_dashboard_fallback_payload(
    dependencies: DashboardCacheDependencies,
) -> Dict[str, Any]:
    now_iso = dependencies.utc_now_iso()
    return {
        "metrics": {"activeMarkets": 0, "totalTrades": 0, "settlements24h": 0},
        "volume7d": [],
        "volume30d": [],
        "statusShare": [],
        "recentActiveMarkets": [],
        "metadata": {
            "generatedAt": now_iso,
            "cacheTtlSeconds": dependencies.cache_ttl_seconds,
            "tradeWindowSize": dependencies.recent_trade_window,
            "tradeWindowEarliestTimestamp": None,
            "tradeWindowLatestTimestamp": None,
            "tradeWindowSource": "warming",
            "tradeWindowCovers7d": False,
            "tradeWindowCovers30d": False,
            "totalTradesSource": "warming",
            "totalTradesAutoIncrement": 0,
            "sourceMode": "fast-fallback",
            "status": "warming",
        },
    }


def _schedule_dashboard_refresh(
    dependencies: DashboardCacheDependencies,
    reason: str,
) -> None:

    with dependencies.resources.dashboard_refresh_lock:
        if dependencies.resources.dashboard_refreshing:
            return
        dependencies.resources.dashboard_refreshing = True

    def refresh() -> None:

        started_at = time.perf_counter()
        try:
            dependencies.application.logger.info(
                "dashboard-cache refresh-start reason=%s",
                reason,
            )
            payload = build_dashboard_payload(dependencies.builder)
            dependencies.snapshot_store.set(
                "snapshot:dashboard",
                "dashboard",
                payload,
                dependencies.cache_ttl_seconds,
            )
            dependencies.cache["value"] = payload
            dependencies.cache["expires_at"] = (
                time.monotonic() + dependencies.cache_ttl_seconds
            )
            dependencies.set_cached_json(
                "dashboard",
                "dashboard",
                payload,
                dependencies.cache_ttl_seconds,
            )
            dependencies.application.logger.info(
                "dashboard-cache refresh-done reason=%s duration_ms=%.2f",
                reason,
                (time.perf_counter() - started_at) * 1000,
            )
        except Exception:
            dependencies.application.logger.exception(
                "dashboard-cache refresh-failed reason=%s",
                reason,
            )
        finally:
            with dependencies.resources.dashboard_refresh_lock:
                dependencies.resources.dashboard_refreshing = False

    if not dependencies.resources.start_thread(refresh, name="dashboard-refresh"):
        with dependencies.resources.dashboard_refresh_lock:
            dependencies.resources.dashboard_refreshing = False


def get_dashboard_payload_cached(ctx: Mapping[str, Any]) -> Dict[str, Any]:
    dependencies = DashboardCacheDependencies.from_context(ctx)
    redis_cache_key = "dashboard"
    redis_payload = dependencies.get_cached_json("dashboard", redis_cache_key)
    if redis_payload is not None:
        dependencies.application.logger.info("dashboard-cache redis-hit")
        return redis_payload
    now_monotonic = time.monotonic()
    cached = dependencies.cache.get("value")
    if (
        cached is not None
        and dependencies.cache.get("expires_at", 0.0) > now_monotonic
    ):
        dependencies.application.logger.info(
            "dashboard-cache hit ttl_remaining_ms=%.2f",
            (dependencies.cache.get("expires_at", 0.0) - now_monotonic) * 1000,
        )
        return cached
    with dependencies.cache_lock:
        cached = dependencies.cache.get("value")
        if (
            cached is not None
            and dependencies.cache.get("expires_at", 0.0) > time.monotonic()
        ):
            dependencies.application.logger.info("dashboard-cache hit-after-lock")
            return cached
        dependencies.application.logger.info(
            "dashboard-cache rebuild window_size=%s ttl_seconds=%s",
            dependencies.recent_trade_window,
            dependencies.cache_ttl_seconds,
        )
        snapshot_payload = dependencies.snapshot_store.get(
            "snapshot:dashboard",
            redis_cache_key,
        )
        if snapshot_payload is not None:
            payload = snapshot_payload
        else:
            stale_payload = dependencies.snapshot_store.get_stale(
                "snapshot:dashboard",
                redis_cache_key,
            )
            if stale_payload is not None:
                dependencies.application.logger.info(
                    "dashboard-cache stale-hit scheduling_refresh=true"
                )
                _schedule_dashboard_refresh(dependencies, "stale-hit")
                payload = stale_payload
            else:
                dependencies.application.logger.info(
                    "dashboard-cache cold-miss returning_fallback=true "
                    "scheduling_refresh=true"
                )
                _schedule_dashboard_refresh(dependencies, "cold-miss")
                payload = _build_dashboard_fallback_payload(dependencies)
        dependencies.cache["value"] = payload
        dependencies.cache["expires_at"] = (
            time.monotonic() + dependencies.cache_ttl_seconds
        )
        dependencies.set_cached_json(
            "dashboard",
            redis_cache_key,
            payload,
            dependencies.cache_ttl_seconds,
        )
        return payload


def _claim_prewarm_slot(resources: RuntimeResources, task_name: str, interval_seconds: int) -> bool:
    now = time.monotonic()
    with resources.prewarm_lock:
        last_run = resources.prewarm_last_run.get(task_name, 0.0)
        if now - last_run < interval_seconds:
            return False
        resources.prewarm_last_run[task_name] = now
    return True


def _prewarm_snapshot_payloads(
    dependencies: BootstrapPrewarmDependencies,
) -> None:

    tasks = [
        (
            "commodities",
            dependencies.finance_runtime_ttl_seconds,
            lambda: dependencies.get_market_group_snapshot(
                dependencies.commodity_symbols,
                kind="commodities",
            ),
        ),
        (
            "finance:market-atlas",
            60,
            lambda: dependencies.get_finance_market_atlas_snapshot(
                limit=16,
            ),
        ),
        (
            "finance:equity-event-command",
            60,
            lambda: dependencies.get_equity_event_command_snapshot(
                limit=12,
            ),
        ),
        (
            "finance:onchain-tradfi-perp-radar",
            45,
            lambda: dependencies.get_onchain_tradfi_perp_radar_snapshot(
                limit=12,
            ),
        ),
        (
            "finance:liquidity-regime",
            45,
            lambda: dependencies.get_finance_liquidity_regime_snapshot(
                limit=12,
            ),
        ),
        (
            "whales",
            30,
            lambda: dependencies.get_whale_trades_snapshot(limit=14),
        ),
        (
            "suspicious",
            30,
            lambda: dependencies.get_suspicious_trades_snapshot(limit=12),
        ),
        (
            "alpha",
            45,
            lambda: dependencies.get_alpha_signal_snapshot(limit=8),
        ),
        (
            "jin10",
            max(15, dependencies.signal_runtime_ttl_seconds),
            lambda: dependencies.get_jin10_panel_snapshot(limit=24),
        ),
    ]
    for name, interval_seconds, builder in tasks:
        if not _claim_prewarm_slot(dependencies.resources, name, interval_seconds):
            continue
        started_at = time.perf_counter()
        try:
            builder()
            dependencies.application.logger.info(
                "snapshot-prewarm done task=%s duration_ms=%.2f",
                name,
                (time.perf_counter() - started_at) * 1000,
            )
        except Exception:
            dependencies.application.logger.exception(
                "snapshot-prewarm failed task=%s",
                name,
            )


def prewarm_critical_payloads(ctx: Mapping[str, Any]) -> None:
    _prewarm_critical_payloads(
        BootstrapPrewarmDependencies.from_context(ctx),
    )


def _prewarm_critical_payloads(
    dependencies: BootstrapPrewarmDependencies,
) -> None:
    tasks = [
        (
            "commodities",
            lambda: dependencies.get_market_group_snapshot(
                dependencies.commodity_symbols,
                kind="commodities",
            ),
        ),
        (
            "finance:market-atlas",
            lambda: dependencies.get_finance_market_atlas_snapshot(
                limit=16,
            ),
        ),
        (
            "finance:equity-event-command",
            lambda: dependencies.get_equity_event_command_snapshot(
                limit=12,
            ),
        ),
        (
            "finance:onchain-tradfi-perp-radar",
            lambda: dependencies.get_onchain_tradfi_perp_radar_snapshot(
                limit=12,
            ),
        ),
        (
            "finance:liquidity-regime",
            lambda: dependencies.get_finance_liquidity_regime_snapshot(
                limit=12,
            ),
        ),
    ]
    for name, builder in tasks:
        started_at = time.perf_counter()
        try:
            builder()
            dependencies.application.logger.info(
                "startup-prewarm done task=%s duration_ms=%.2f",
                name,
                (time.perf_counter() - started_at) * 1000,
            )
        except Exception:
            dependencies.application.logger.exception(
                "startup-prewarm failed task=%s",
                name,
            )


def start_snapshot_prewarm_thread(ctx: Mapping[str, Any]) -> None:
    dependencies = BootstrapPrewarmDependencies.from_context(ctx)
    if not dependencies.snapshot_prewarm_enabled:
        dependencies.application.logger.info("snapshot-prewarm disabled")
        return

    def _runner() -> None:
        while not dependencies.resources.stopped.is_set():
            _prewarm_snapshot_payloads(dependencies)
            dependencies.resources.stopped.wait(SNAPSHOT_PREWARM_INTERVAL_SECONDS)

    dependencies.resources.start_thread(_runner, name="polydata-snapshot-prewarm")


def build_bootstrap_payload():
    """Static workspace configuration; individual panels own their reads."""
    return {"generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "defaultWorkspace": {"name": "Market monitor", "panels": get_default_panel_ids()},
            "featuredMarket": None, "activeMarketsPreview": [], "activeMarketGroupsPreview": [],
            "globalTradesPreview": [], "globalOraclePreview": [], "latestContentPreview": [],
            "recentTradesPreview": [], "oraclePreview": [], "contentPreview": [], "pricePreview": None,
            "systemHealth": {"apiStatus": "ok"}}
