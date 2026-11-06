#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Centralized configuration for the polyData API service."""

from __future__ import annotations

from data_sources import source_value

import os
import math
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from db import DEFAULT_DB_PATH
from db.db import DatabaseSettings
from data_sources import env_str


PROJECT_ROOT = Path(__file__).resolve().parents[2]


from runtime.environment import load_environment


def _get_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    text = value.strip()
    return text or default


def _get_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _get_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _get_csv(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.environ.get(name)
    if raw is None:
        return default
    values = tuple(part.strip() for part in str(raw).split(",") if part.strip())
    return values or default


def _get_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
        return value if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ClickHouseSettings:
    enabled: bool = True
    http_url: str = ""
    container: str = "polydata_clickhouse_orderfilled"
    database: str = "poly_orderfilled"
    user: str = "poly_user"
    password: str = field(default="", repr=False)
    table: str = "orderfilled_fact"
    concurrency: int = 1
    alpha_edge_fee_probability: float = 0.01
    whale_min_notional: float = 1000.0
    whale_elevated_notional: float = 2500.0
    whale_critical_notional: float = 10000.0
    whale_market_share_threshold: float = 0.1
    whale_relative_min_notional: float = 500.0
    signal_min_price: float = 0.02
    signal_max_price: float = 0.98
    alpha_volume_window_minutes: int = 15
    alpha_market_baseline_minutes: int = 60
    alpha_min_flow_notional: float = 1000.0
    alpha_min_single_trade_notional: float = 2500.0
    alpha_relative_min_flow_notional: float = 500.0
    alpha_market_share_threshold: float = 0.12
    alpha_min_net_strength: float = 0.55
    whale_volume_window_minutes: int = 60
    max_threads: int = 2
    max_memory_bytes: int = 536870912
    max_bytes_to_read: int = 536870912
    max_execution_seconds: int = 6

    def __post_init__(self):
        for value in (self.database, self.table):
            if not value or not all(c.isalnum() or c == "_" for c in value):
                raise ValueError("Unsafe ClickHouse identifier")

    @classmethod
    def from_environment(cls):
        return cls(
            enabled=_get_bool("POLYDATA_ORDERFILLED_CLICKHOUSE_READ_ENABLED", True),
            http_url=_get_str("POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL", ""),
            container=_get_str("POLYDATA_ORDERFILLED_CLICKHOUSE_CONTAINER", cls.container),
            database=_get_str("POLYDATA_ORDERFILLED_CLICKHOUSE_DATABASE", cls.database),
            user=_get_str("POLYDATA_ORDERFILLED_CLICKHOUSE_USER", cls.user),
            password=_get_str("POLYDATA_ORDERFILLED_CLICKHOUSE_PASSWORD", _get_str("CLICKHOUSE_PASSWORD", "")),
            table=_get_str("POLYDATA_ORDERFILLED_CLICKHOUSE_READ_TABLE", cls.table),
            concurrency=max(1, min(_get_int("POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_CONCURRENCY", 1), 4)),
            alpha_edge_fee_probability=max(0.0, min(_get_float("POLYDATA_ALPHA_EDGE_FEE_PROBABILITY", 0.01), 0.25)),
            whale_min_notional=max(0.0, min(_get_float("POLYDATA_WHALE_MIN_NOTIONAL", 1000.0), 1000000000.0)),
            whale_elevated_notional=max(0.0, min(_get_float("POLYDATA_WHALE_ELEVATED_NOTIONAL", 2500.0), 1000000000.0)),
            whale_critical_notional=max(
                0.0, min(_get_float("POLYDATA_WHALE_CRITICAL_NOTIONAL", 10000.0), 1000000000.0)
            ),
            whale_market_share_threshold=max(0.0, min(_get_float("POLYDATA_WHALE_MARKET_SHARE_THRESHOLD", 0.1), 1.0)),
            whale_relative_min_notional=max(
                0.0, min(_get_float("POLYDATA_WHALE_RELATIVE_MIN_NOTIONAL", 500.0), 1000000000.0)
            ),
            signal_min_price=max(0.0, min(_get_float("POLYDATA_SIGNAL_MIN_PRICE", 0.02), 0.49)),
            signal_max_price=max(0.51, min(_get_float("POLYDATA_SIGNAL_MAX_PRICE", 0.98), 1.0)),
            alpha_volume_window_minutes=max(5, min(_get_int("POLYDATA_ALPHA_VOLUME_WINDOW_MINUTES", 15), 360)),
            alpha_market_baseline_minutes=max(15, min(_get_int("POLYDATA_ALPHA_MARKET_BASELINE_MINUTES", 60), 1440)),
            alpha_min_flow_notional=max(0.0, min(_get_float("POLYDATA_ALPHA_MIN_FLOW_NOTIONAL", 1000.0), 1000000000.0)),
            alpha_min_single_trade_notional=max(
                0.0, min(_get_float("POLYDATA_ALPHA_MIN_SINGLE_TRADE_NOTIONAL", 2500.0), 1000000000.0)
            ),
            alpha_relative_min_flow_notional=max(
                0.0, min(_get_float("POLYDATA_ALPHA_RELATIVE_MIN_FLOW_NOTIONAL", 500.0), 1000000000.0)
            ),
            alpha_market_share_threshold=max(0.0, min(_get_float("POLYDATA_ALPHA_MARKET_SHARE_THRESHOLD", 0.12), 1.0)),
            alpha_min_net_strength=max(0.0, min(_get_float("POLYDATA_ALPHA_MIN_NET_STRENGTH", 0.55), 1.0)),
            whale_volume_window_minutes=max(5, min(_get_int("POLYDATA_WHALE_VOLUME_WINDOW_MINUTES", 60), 1440)),
            max_threads=max(1, min(_get_int("POLYDATA_ORDERFILLED_CLICKHOUSE_MAX_THREADS", 2), 8)),
            max_memory_bytes=max(
                67108864, min(_get_int("POLYDATA_ORDERFILLED_CLICKHOUSE_MAX_MEMORY_BYTES", 536870912), 4294967296)
            ),
            max_bytes_to_read=max(
                67108864, min(_get_int("POLYDATA_ORDERFILLED_CLICKHOUSE_MAX_BYTES_TO_READ", 536870912), 8589934592)
            ),
            max_execution_seconds=max(1, min(_get_int("POLYDATA_ORDERFILLED_CLICKHOUSE_MAX_EXECUTION_SECONDS", 6), 30)),
        )


@dataclass(frozen=True)
class MarketSelectionSettings:
    max_age_hours: int = 336
    activity_hours: int = 72
    lob_prefetch_limit: int = 0
    min_price: Decimal = Decimal("0.05")
    max_price: Decimal = Decimal("0.95")


@dataclass(frozen=True)
class ApiSettings:
    market_selection: MarketSelectionSettings
    database: DatabaseSettings
    deploy_role: str
    host: str
    port: int
    allowed_origins: tuple[str, ...]
    db_path: str
    dashboard_cache_ttl_seconds: int
    markets_cache_ttl_seconds: int
    recent_trade_window: int
    address_cache_ttl_seconds: int
    redis_url: str
    redis_prefix: str
    snapshot_sqlite_path: str
    snapshot_prewarm_enabled: bool
    gamma_api_base: str
    polymarket_macro_map_source_url: str
    polymarket_macro_map_ttl_seconds: int
    polymarket_macro_map_search_terms: tuple[str, ...]
    finance_runtime_ttl_seconds: int
    finance_defillama_yields_url: str
    finance_alternative_fng_url: str
    finance_google_news_rss_url: str
    finance_yahoo_chart_url_template: str
    finance_fred_csv_url_template: str
    fred_csv_lookback_years: int
    finance_barchart_quote_url_template: str
    finance_cnn_fng_url: str
    finance_cnn_fng_referer_url: str
    finance_aaii_sentiment_url: str
    finance_broker_research_feed_urls: tuple[str, ...]
    finance_broker_research_news_fallback: bool
    finance_broker_research_edison_url: str
    finance_broker_research_zacks_url: str
    finance_broker_research_water_tower_url: str
    finance_broker_research_eastmoney_url: str
    finance_broker_research_choice_url: str
    finance_hyperliquid_info_url: str
    finance_okx_market_ticker_url: str
    finance_defillama_stablecoins_url: str
    finance_cftc_legacy_cot_url: str
    tech_runtime_ttl_seconds: int
    tech_google_news_rss_url: str
    tech_app_store_top_free_url: str
    sports_runtime_ttl_seconds: int
    signal_runtime_ttl_seconds: int
    signal_refresh_interval_seconds: int
    grid_open_access_base_url: str
    grid_central_data_graphql_url: str
    grid_series_state_graphql_url: str
    grid_api_key: str
    grid_source_url: str
    grid_esports_ttl_seconds: int
    grid_esports_lookback_days: int
    grid_esports_lookahead_days: int
    grid_esports_pm_search_enabled: bool
    the_odds_api_base_url: str
    the_odds_api_key: str
    the_odds_source_url: str
    worldcup_odds_markets: str
    worldcup_core_seed_ttl_seconds: int
    worldcup_live_seed_ttl_seconds: int
    the_rundown_api_key: str
    api_football_api_key: str
    betfair_app_key: str
    matchbook_api_username: str
    sports_odds_ttl_seconds: int
    sports_odds_sport_key: str
    sports_odds_regions: str
    sports_odds_markets: str
    sports_odds_pm_search_enabled: bool
    crypto_funding_watch_api_url: str
    crypto_funding_watch_bybit_api_url: str
    crypto_funding_watch_api_key: str
    crypto_funding_watch_bybit_api_key: str
    crypto_funding_watch_source_url: str
    crypto_funding_watch_ttl_seconds: int
    crypto_funding_watch_symbols: tuple[str, ...]
    defi_token_watch_ids: tuple[str, ...]
    defi_token_watch_ttl_seconds: int
    yahoo_chart_base_url: str
    coingecko_base_url: str
    espn_nba_base_url: str
    espn_core_nba_base_url: str
    nba_lineups_base_url: str
    nba_official_base_url: str
    cleveland_fed_nowcast_url: str
    cpi_calendar_bls_cpi_url: str
    cpi_calendar_bls_employment_url: str
    cpi_calendar_bea_schedule_url: str
    cpi_calendar_fomc_url: str
    cpi_calendar_source_url: str
    cpi_calendar_ttl_seconds: int
    energy_shock_wti_xls_url: str
    energy_shock_gasoline_xls_url: str
    energy_shock_diesel_xls_url: str
    energy_shock_source_url: str
    energy_shock_ttl_seconds: int
    food_basket_fred_csv_url_template: str
    food_basket_source_url: str
    food_basket_ttl_seconds: int
    macro_cpi_panel_ttl_seconds: int
    macro_cpi_registry_ttl_seconds: int
    geo_shock_ofac_sdn_url: str
    geo_shock_ofac_consolidated_url: str
    geo_shock_federal_register_api_url: str
    geo_shock_conflict_api_url: str
    geo_shock_gdelt_doc_api_url: str
    geo_shock_ucdp_api_url: str
    geo_shock_ucdp_access_token: str
    geo_shock_acled_token_url: str
    geo_shock_acled_api_url: str
    geo_shock_acled_email: str
    geo_shock_acled_password: str
    geo_shock_source_url: str
    geo_shock_ttl_seconds: int
    natural_hazards_usgs_url: str
    natural_hazards_eonet_url: str
    natural_hazards_gdacs_url: str
    natural_hazards_nws_url: str
    natural_hazards_firms_base_url: str
    natural_hazards_firms_source: str
    open_meteo_api_url: str
    aviationweather_metar_api_url: str
    google_news_rss_url: str
    weather_source_url: str
    global_weather_map_ttl_seconds: int
    global_weather_market_days: int
    weather_news_ttl_seconds: int
    weather_news_limit: int
    weather_news_fetch_workers: int
    f1_panel_path: str
    f1_bwenews_rss_url: str
    f1_bwenews_source_url: str
    jin10_flash_api_url: str
    jin10_flash_detail_base_url: str
    jin10_live_url: str
    jin10_flash_channel: str
    jin10_flash_app_id: str
    jin10_flash_version: str
    clickhouse: ClickHouseSettings = field(default_factory=ClickHouseSettings.from_environment)
    shutdown_timeout_seconds: float = field(
        default_factory=lambda: max(0.1, min(_get_float("POLYDATA_SHUTDOWN_TIMEOUT_SECONDS", 20), 25))
    )
    snapshot_refresh_workers: int = field(
        default_factory=lambda: max(1, min(_get_int("POLYDATA_SNAPSHOT_REFRESH_WORKERS", 2), 8))
    )


def load_api_settings() -> ApiSettings:
    load_environment()
    snapshot_default = str((PROJECT_ROOT / "data" / "panel_snapshots.sqlite3").resolve())
    deploy_role = _get_str("POLYDATA_DEPLOY_ROLE", "local-data").strip().lower()
    snapshot_prewarm_default = deploy_role in {"gcp-api", "remote-api", "production-api"}
    signal_interval = max(120, _get_int("POLYDATA_SIGNAL_WATCH_INTERVAL_SECONDS", 120))
    return ApiSettings(
        market_selection=MarketSelectionSettings(
            max_age_hours=_get_int("POLYDATA_ACTIVE_MARKET_MAX_AGE_HOURS", 336),
            activity_hours=_get_int("POLYDATA_ACTIVE_MARKET_ACTIVITY_HOURS", 72),
            lob_prefetch_limit=_get_int("POLYDATA_ACTIVE_MARKET_LOB_PREFETCH_LIMIT", 0),
            min_price=Decimal(_get_str("POLYDATA_ACTIVE_MARKET_MIN_PRICE", "0.05")),
            max_price=Decimal(_get_str("POLYDATA_ACTIVE_MARKET_MAX_PRICE", "0.95")),
        ),
        database=DatabaseSettings.from_environment(),
        deploy_role=deploy_role,
        host=_get_str("POLYDATA_API_HOST", "127.0.0.1"),
        port=_get_int("POLYDATA_API_PORT", 18500),
        allowed_origins=_get_csv("POLYDATA_ALLOWED_ORIGINS", ()),
        db_path=_get_str("POLYMARKET_DB", DEFAULT_DB_PATH),
        dashboard_cache_ttl_seconds=_get_int("POLYDATA_DASHBOARD_CACHE_TTL_SECONDS", 300),
        markets_cache_ttl_seconds=_get_int("POLYDATA_MARKETS_CACHE_TTL_SECONDS", 60),
        recent_trade_window=_get_int("POLYDATA_DASHBOARD_TRADE_WINDOW", 250000),
        address_cache_ttl_seconds=_get_int("POLYDATA_ADDRESS_CACHE_TTL_SECONDS", 120),
        redis_url=_get_str("POLYDATA_REDIS_URL", ""),
        redis_prefix=_get_str("POLYDATA_REDIS_PREFIX", "polydata:"),
        snapshot_sqlite_path=_get_str("POLYDATA_SNAPSHOT_SQLITE_PATH", snapshot_default),
        snapshot_prewarm_enabled=_get_bool("POLYDATA_SNAPSHOT_PREWARM", snapshot_prewarm_default),
        gamma_api_base=_get_str("POLYDATA_GAMMA_API_BASE", ("")),
        polymarket_macro_map_source_url=_get_str(
            "POLYDATA_MACRO_MARKET_MAP_SOURCE_URL",
            env_str("POLYDATA_GAMMA_API_BASE"),
        ),
        polymarket_macro_map_ttl_seconds=_get_int("POLYDATA_MACRO_MARKET_MAP_TTL_SECONDS", 180),
        polymarket_macro_map_search_terms=_get_csv("POLYDATA_MACRO_MARKET_MAP_SEARCH_TERMS", ()),
        finance_runtime_ttl_seconds=_get_int("POLYDATA_FINANCE_RUNTIME_TTL_SECONDS", 300),
        finance_defillama_yields_url=source_value('POLYDATA_FINANCE_DEFILLAMA_YIELDS_URL'),
        finance_alternative_fng_url=source_value('POLYDATA_FINANCE_ALTERNATIVE_FNG_URL'),
        finance_google_news_rss_url=_get_str(
            "POLYDATA_FINANCE_GOOGLE_NEWS_RSS_URL",
            env_str("POLYDATA_GOOGLE_NEWS_RSS_URL") or source_value('POLYDATA_GOOGLE_NEWS_RSS_URL'),
        ),
        finance_yahoo_chart_url_template=source_value('POLYDATA_FINANCE_YAHOO_CHART_URL_TEMPLATE'),
        finance_fred_csv_url_template=source_value('POLYDATA_FINANCE_FRED_CSV_URL_TEMPLATE'),
        fred_csv_lookback_years=max(1, _get_int("POLYDATA_FRED_CSV_LOOKBACK_YEARS", 4)),
        finance_barchart_quote_url_template=source_value('POLYDATA_FINANCE_BARCHART_QUOTE_URL_TEMPLATE'),
        finance_cnn_fng_url=source_value('POLYDATA_FINANCE_CNN_FNG_URL'),
        finance_cnn_fng_referer_url=source_value('POLYDATA_FINANCE_CNN_FNG_REFERER_URL'),
        finance_aaii_sentiment_url=source_value('POLYDATA_FINANCE_AAII_SENTIMENT_URL'),
        finance_broker_research_feed_urls=_get_csv("POLYDATA_FINANCE_BROKER_RESEARCH_FEED_URLS", ()),
        finance_broker_research_news_fallback=_get_bool("POLYDATA_FINANCE_BROKER_RESEARCH_NEWS_FALLBACK", False),
        finance_broker_research_edison_url=source_value('POLYDATA_FINANCE_BROKER_RESEARCH_EDISON_URL'),
        finance_broker_research_zacks_url=source_value('POLYDATA_FINANCE_BROKER_RESEARCH_ZACKS_URL'),
        finance_broker_research_water_tower_url=source_value('POLYDATA_FINANCE_BROKER_RESEARCH_WATER_TOWER_URL'),
        finance_broker_research_eastmoney_url=_get_str("POLYDATA_FINANCE_BROKER_RESEARCH_EASTMONEY_URL", ("")),
        finance_broker_research_choice_url=_get_str("POLYDATA_FINANCE_BROKER_RESEARCH_CHOICE_URL", ("")),
        finance_hyperliquid_info_url=source_value('POLYDATA_FINANCE_HYPERLIQUID_INFO_URL'),
        finance_okx_market_ticker_url=source_value('POLYDATA_FINANCE_OKX_MARKET_TICKER_URL'),
        finance_defillama_stablecoins_url=source_value('POLYDATA_FINANCE_DEFILLAMA_STABLECOINS_URL'),
        finance_cftc_legacy_cot_url=source_value('POLYDATA_FINANCE_CFTC_LEGACY_COT_URL'),
        tech_runtime_ttl_seconds=_get_int("POLYDATA_TECH_RUNTIME_TTL_SECONDS", 600),
        tech_google_news_rss_url=_get_str(
            "POLYDATA_TECH_GOOGLE_NEWS_RSS_URL",
            env_str("POLYDATA_GOOGLE_NEWS_RSS_URL")
            or env_str("POLYDATA_FINANCE_GOOGLE_NEWS_RSS_URL")
            or source_value('POLYDATA_GOOGLE_NEWS_RSS_URL'),
        ),
        tech_app_store_top_free_url=source_value('POLYDATA_TECH_APP_STORE_TOP_FREE_URL'),
        sports_runtime_ttl_seconds=_get_int("POLYDATA_SPORTS_RUNTIME_TTL_SECONDS", 60),
        signal_refresh_interval_seconds=signal_interval,
        signal_runtime_ttl_seconds=max(signal_interval + 60, _get_int("POLYDATA_SIGNAL_RUNTIME_TTL_SECONDS", 2 * signal_interval + 60)),
        grid_open_access_base_url=source_value('POLYDATA_GRID_OPEN_ACCESS_BASE_URL'),
        grid_central_data_graphql_url=source_value('POLYDATA_GRID_CENTRAL_DATA_GRAPHQL_URL'),
        grid_series_state_graphql_url=source_value('POLYDATA_GRID_SERIES_STATE_GRAPHQL_URL'),
        grid_api_key=_get_str("POLYDATA_GRID_API_KEY", _get_str("grid_api_key", _get_str("GRID_API_KEY", ""))),
        grid_source_url=source_value('POLYDATA_GRID_SOURCE_URL'),
        grid_esports_ttl_seconds=_get_int("POLYDATA_GRID_ESPORTS_TTL_SECONDS", 120),
        grid_esports_lookback_days=_get_int("POLYDATA_GRID_ESPORTS_LOOKBACK_DAYS", 2),
        grid_esports_lookahead_days=_get_int("POLYDATA_GRID_ESPORTS_LOOKAHEAD_DAYS", 14),
        grid_esports_pm_search_enabled=_get_bool("POLYDATA_GRID_ESPORTS_PM_SEARCH_ENABLED", False),
        the_odds_api_base_url=source_value('POLYDATA_THE_ODDS_API_BASE_URL'),
        the_odds_api_key=_get_str(
            "POLYDATA_THE_ODDS_API_KEY2",
            _get_str(
                "the_odds_api_key2",
                _get_str(
                    "odds_api_key2",
                    _get_str(
                        "THE_ODDS_API_KEY2",
                        _get_str(
                            "POLYDATA_THE_ODDS_API_KEY",
                            _get_str("the_odds_api_key", _get_str("odds_api_key", _get_str("THE_ODDS_API_KEY", ""))),
                        ),
                    ),
                ),
            ),
        ),
        the_odds_source_url=source_value('POLYDATA_THE_ODDS_SOURCE_URL'),
        worldcup_odds_markets=_get_str("POLYDATA_WORLDCUP_ODDS_MARKETS", "h2h,spreads,totals"),
        worldcup_core_seed_ttl_seconds=_get_int("POLYDATA_WORLDCUP_CORE_SEED_TTL_SECONDS", 86400),
        worldcup_live_seed_ttl_seconds=_get_int("POLYDATA_WORLDCUP_LIVE_SEED_TTL_SECONDS", 300),
        the_rundown_api_key=_get_str(
            "POLYDATA_THERUNDOWN_API_KEY", _get_str("THERUNDOWN_API_KEY", _get_str("the_rundown_api_key", ""))
        ),
        api_football_api_key=_get_str(
            "POLYDATA_API_FOOTBALL_KEY", _get_str("API_FOOTBALL_KEY", _get_str("api_football_key", ""))
        ),
        betfair_app_key=_get_str(
            "POLYDATA_BETFAIR_APP_KEY", _get_str("BETFAIR_APP_KEY", _get_str("betfair_app_key", ""))
        ),
        matchbook_api_username=_get_str(
            "POLYDATA_MATCHBOOK_USERNAME", _get_str("MATCHBOOK_USERNAME", _get_str("matchbook_username", ""))
        ),
        sports_odds_ttl_seconds=_get_int("POLYDATA_SPORTS_ODDS_TTL_SECONDS", 180),
        sports_odds_sport_key=_get_str("POLYDATA_SPORTS_ODDS_SPORT_KEY", "upcoming"),
        sports_odds_regions=_get_str("POLYDATA_SPORTS_ODDS_REGIONS", "us"),
        sports_odds_markets=_get_str("POLYDATA_SPORTS_ODDS_MARKETS", "h2h"),
        sports_odds_pm_search_enabled=_get_bool("POLYDATA_SPORTS_ODDS_PM_SEARCH_ENABLED", False),
        crypto_funding_watch_api_url=_get_str("POLYDATA_CRYPTO_FUNDING_WATCH_API_URL", ("")),
        crypto_funding_watch_bybit_api_url=_get_str("POLYDATA_CRYPTO_FUNDING_WATCH_BYBIT_API_URL", ("")),
        crypto_funding_watch_api_key=_get_str("POLYDATA_CRYPTO_FUNDING_WATCH_API_KEY", ""),
        crypto_funding_watch_bybit_api_key=_get_str("POLYDATA_CRYPTO_FUNDING_WATCH_BYBIT_API_KEY", ""),
        crypto_funding_watch_source_url=_get_str("POLYDATA_CRYPTO_FUNDING_WATCH_SOURCE_URL", ("")),
        crypto_funding_watch_ttl_seconds=_get_int("POLYDATA_CRYPTO_FUNDING_WATCH_TTL_SECONDS", 15),
        crypto_funding_watch_symbols=_get_csv(
            "POLYDATA_CRYPTO_FUNDING_WATCH_SYMBOLS",
            (
                "BTCUSDT",
                "ETHUSDT",
                "SOLUSDT",
                "BNBUSDT",
                "XRPUSDT",
                "DOGEUSDT",
                "ADAUSDT",
                "AVAXUSDT",
                "LINKUSDT",
                "LTCUSDT",
                "DOTUSDT",
                "TRXUSDT",
                "BCHUSDT",
                "SUIUSDT",
                "TONUSDT",
                "NEARUSDT",
                "APTUSDT",
                "ETCUSDT",
            ),
        ),
        defi_token_watch_ids=_get_csv(
            "POLYDATA_DEFI_TOKEN_WATCH_IDS",
            (
                "uniswap",
                "pendle",
                "maker",
                "aave",
                "lido-dao",
                "ethena",
                "curve-dao-token",
                "compound-governance-token",
                "synthetix-network-token",
                "rocket-pool",
            ),
        ),
        defi_token_watch_ttl_seconds=_get_int("POLYDATA_DEFI_TOKEN_WATCH_TTL_SECONDS", 120),
        yahoo_chart_base_url=source_value('POLYDATA_YAHOO_CHART_BASE_URL'),
        coingecko_base_url=_get_str("POLYDATA_COINGECKO_BASE_URL", ("")),
        espn_nba_base_url=_get_str("POLYDATA_ESPN_NBA_BASE_URL", ("")),
        espn_core_nba_base_url=_get_str("POLYDATA_ESPN_CORE_NBA_BASE_URL", ("")),
        nba_lineups_base_url=_get_str("POLYDATA_NBA_LINEUPS_BASE_URL", ("")),
        nba_official_base_url=_get_str("POLYDATA_NBA_OFFICIAL_BASE_URL", ("")),
        cleveland_fed_nowcast_url=_get_str("POLYDATA_CLEVELAND_FED_NOWCAST_URL", ("")),
        cpi_calendar_bls_cpi_url=source_value('POLYDATA_CPI_CALENDAR_BLS_CPI_URL'),
        cpi_calendar_bls_employment_url=source_value('POLYDATA_CPI_CALENDAR_BLS_EMPLOYMENT_URL'),
        cpi_calendar_bea_schedule_url=source_value('POLYDATA_CPI_CALENDAR_BEA_SCHEDULE_URL'),
        cpi_calendar_fomc_url=source_value('POLYDATA_CPI_CALENDAR_FOMC_URL'),
        cpi_calendar_source_url=source_value('POLYDATA_CPI_CALENDAR_SOURCE_URL'),
        cpi_calendar_ttl_seconds=_get_int("POLYDATA_CPI_CALENDAR_TTL_SECONDS", 3600),
        energy_shock_wti_xls_url=source_value('POLYDATA_ENERGY_SHOCK_WTI_XLS_URL'),
        energy_shock_gasoline_xls_url=source_value('POLYDATA_ENERGY_SHOCK_GASOLINE_XLS_URL'),
        energy_shock_diesel_xls_url=source_value('POLYDATA_ENERGY_SHOCK_DIESEL_XLS_URL'),
        energy_shock_source_url=source_value('POLYDATA_ENERGY_SHOCK_SOURCE_URL'),
        energy_shock_ttl_seconds=_get_int("POLYDATA_ENERGY_SHOCK_TTL_SECONDS", 21600),
        food_basket_fred_csv_url_template=source_value('POLYDATA_FOOD_BASKET_FRED_CSV_URL_TEMPLATE'),
        food_basket_source_url=source_value('POLYDATA_FOOD_BASKET_SOURCE_URL'),
        food_basket_ttl_seconds=_get_int("POLYDATA_FOOD_BASKET_TTL_SECONDS", 21600),
        macro_cpi_panel_ttl_seconds=_get_int("POLYDATA_MACRO_CPI_PANEL_TTL_SECONDS", 21600),
        macro_cpi_registry_ttl_seconds=_get_int("POLYDATA_MACRO_CPI_REGISTRY_TTL_SECONDS", 21600),
        geo_shock_ofac_sdn_url=source_value('POLYDATA_GEO_SHOCK_OFAC_SDN_URL'),
        geo_shock_ofac_consolidated_url=source_value('POLYDATA_GEO_SHOCK_OFAC_CONSOLIDATED_URL'),
        geo_shock_federal_register_api_url=source_value('POLYDATA_GEO_SHOCK_FEDERAL_REGISTER_API_URL'),
        geo_shock_conflict_api_url=_get_str("POLYDATA_GEO_SHOCK_CONFLICT_API_URL", ("")),
        geo_shock_gdelt_doc_api_url=source_value('POLYDATA_GEO_SHOCK_GDELT_DOC_API_URL'),
        geo_shock_ucdp_api_url=_get_str(
            "POLYDATA_GEO_SHOCK_UCDP_API_URL",
            _get_str(
                "UCDP_API_URL",
                (env_str("POLYDATA_GEO_SHOCK_UCDP_API_URL") or env_str("UCDP_API_URL"))
                or source_value('POLYMONITOR_URL_UCDPAPI_PCR_UU_SE_API_GEDEVENTS_25_1_46DFB9'),
            ),
        ),
        geo_shock_ucdp_access_token=_get_str(
            "POLYDATA_GEO_SHOCK_UCDP_ACCESS_TOKEN",
            _get_str(
                "UCDP_API_TOKEN",
                _get_str(
                    "UCDP_API_Token",
                    _get_str(
                        "UCDP_ACCESS_TOKEN",
                        _get_str(
                            "UC_DP_KEY",
                            (
                                env_str("POLYDATA_GEO_SHOCK_UCDP_ACCESS_TOKEN")
                                or env_str("UCDP_API_TOKEN")
                                or env_str("UCDP_API_Token")
                                or env_str("UCDP_ACCESS_TOKEN")
                                or env_str("UC_DP_KEY")
                            ),
                        ),
                    ),
                ),
            ),
        ),
        geo_shock_acled_token_url=source_value('POLYDATA_GEO_SHOCK_ACLED_TOKEN_URL'),
        geo_shock_acled_api_url=source_value('POLYDATA_GEO_SHOCK_ACLED_API_URL'),
        geo_shock_acled_email=_get_str(
            "POLYDATA_GEO_SHOCK_ACLED_EMAIL",
            _get_str("ACLED_USERNAME", (env_str("POLYDATA_GEO_SHOCK_ACLED_EMAIL") or env_str("ACLED_USERNAME"))),
        ),
        geo_shock_acled_password=_get_str(
            "POLYDATA_GEO_SHOCK_ACLED_PASSWORD",
            _get_str("ACLED_PASSWORD", (env_str("POLYDATA_GEO_SHOCK_ACLED_PASSWORD") or env_str("ACLED_PASSWORD"))),
        ),
        geo_shock_source_url=source_value('POLYDATA_GEO_SHOCK_SOURCE_URL'),
        geo_shock_ttl_seconds=_get_int("POLYDATA_GEO_SHOCK_TTL_SECONDS", 900),
        natural_hazards_usgs_url=source_value('POLYDATA_NATURAL_HAZARDS_USGS_URL'),
        natural_hazards_eonet_url=source_value('POLYDATA_NATURAL_HAZARDS_EONET_URL'),
        natural_hazards_gdacs_url=source_value('POLYDATA_NATURAL_HAZARDS_GDACS_URL'),
        natural_hazards_nws_url=source_value('POLYDATA_NATURAL_HAZARDS_NWS_URL'),
        natural_hazards_firms_base_url=source_value('POLYDATA_NATURAL_HAZARDS_FIRMS_BASE_URL'),
        natural_hazards_firms_source=_get_str(
            "POLYDATA_NATURAL_HAZARDS_FIRMS_SOURCE",
            "VIIRS_NOAA20_NRT",
        ),
        open_meteo_api_url=source_value('POLYDATA_OPEN_METEO_API_URL'),
        aviationweather_metar_api_url=source_value('POLYDATA_AVIATIONWEATHER_METAR_API_URL'),
        google_news_rss_url=source_value('POLYDATA_GOOGLE_NEWS_RSS_URL'),
        weather_source_url=source_value('POLYDATA_WEATHER_SOURCE_URL'),
        global_weather_map_ttl_seconds=_get_int("POLYDATA_GLOBAL_WEATHER_MAP_TTL_SECONDS", 7200),
        global_weather_market_days=_get_int("POLYDATA_GLOBAL_WEATHER_MARKET_DAYS", 4),
        weather_news_ttl_seconds=_get_int("POLYDATA_WEATHER_NEWS_TTL_SECONDS", 300),
        weather_news_limit=_get_int("POLYDATA_WEATHER_NEWS_LIMIT", 40),
        weather_news_fetch_workers=_get_int("POLYDATA_WEATHER_NEWS_FETCH_WORKERS", 4),
        f1_panel_path=_get_str(
            "POLYDATA_F1_PANEL_PATH",
            str((PROJECT_ROOT / "data" / "runtime" / "f1" / "panel.json").resolve()),
        ),
        f1_bwenews_rss_url=_get_str("POLYDATA_F1_BWENEWS_RSS_URL", ("")),
        f1_bwenews_source_url=_get_str("POLYDATA_F1_BWENEWS_SOURCE_URL", ("")),
        jin10_flash_api_url=_get_str("POLYDATA_JIN10_FLASH_API_URL", ("")),
        jin10_flash_detail_base_url=_get_str("POLYDATA_JIN10_FLASH_DETAIL_BASE_URL", ("")),
        jin10_live_url=_get_str("POLYDATA_JIN10_LIVE_URL", ("")),
        jin10_flash_channel=_get_str("POLYDATA_JIN10_FLASH_CHANNEL", "-8200"),
        jin10_flash_app_id=_get_str("POLYDATA_JIN10_APP_ID", "SO1EJGmNgCtmpcPF"),
        jin10_flash_version=_get_str("POLYDATA_JIN10_VERSION", "1.0.0"),
    )
