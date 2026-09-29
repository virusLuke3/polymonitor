"""Explicit service bindings and HTTP-specific adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.runtime import ServiceRuntime

from db.trade_v2 import TRADE_V2_CORE_TABLE, sql_identifier

from api import cache as api_cache
from api import db as api_db
from api.clients import market_data_client
from api.serialization import iso_days_before
from api.services.natural_hazards.service import NaturalHazardDependencies

from api.services import (
    address_service,
    bootstrap_service,
    clickhouse_orderfilled_service,
    commodity_equity_transmission_service,
    cpi_release_calendar_service,
    energy_gasoline_shock_service,
    f1_runtime_service,
    food_retail_basket_service,
    geo_sanctions_shock_service,
    global_weather_map_service,
    jin10_runtime_service,
    macro_cpi_panels_service,
    macro_cpi_registry_service,
    market_service,
    natural_hazards,
    new_market_signal_service,
    polybeats_service,
    polymarket_macro_map_service,
    query_service,
    runtime_service,
    signal_service,
    system_service,
    weather_news_service,
)

try:
    import redis
except ImportError:
    redis = None
try:
    import requests
except ImportError:
    requests = None
try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None
try:
    import xlrd
except ImportError:
    xlrd = None
from db import dict_from_row
from db.trade_v2 import LEGACY_TRADES_TABLE

from api.serialization import (
    COMMODITY_SYMBOLS,
    CRYPTO_COINGECKO_IDS,
    CRYPTO_SYMBOLS,
    _safe_decimal,
    _safe_float,
    build_market_status_case,
    format_trade_address,
    format_trade_decimal,
    get_trade_market_projection_sql,
    normalize_address,
    normalize_market,
    normalize_oracle_event,
    normalize_trade,
    parse_iso_datetime,
    parse_json_list,
    utc_date_days_ago,
    utc_now_iso,
)
from api.services import (
    auth_service,
    breaking_event_radar_service,
    briefing_service,
    content_service,
    crypto_funding_service,
    defi_token_watch_service,
    finance_panels_service,
    finance_watch_panels_service,
    finance_external_sources_service,
    global_transport_shipping_service,
    grid_esports_service,
    live_video_source_service,
    lob_service,
    market_group_service,
    market_quality_service,
    market_workspace_cache_service,
    orderfilled_outcome_proof_service,
    product_service,
    sports_odds_service,
    tech_panels_service,
    web_push_service,
    workspace_layout_service,
    world_cup_match_ops_service,
    worldcup_dashboard_service,
    worldcup_intel_service,
)


def bind_services(runtime: ServiceRuntime) -> None:
    runtime.cache = api_cache.CacheState(
        runtime.resources,
        runtime.app,
        runtime.SNAPSHOT_STORE,
        redis_url=runtime.SETTINGS.redis_url,
        redis_prefix=runtime.SETTINGS.redis_prefix,
        redis_module=redis,
    )
    get_runtime_lob_by_token_payload = lambda token_id, no_token_id="", market_title="", market_id=None: (
        lob_service.get_runtime_lob_by_token_payload(
            token_id, no_token_id=no_token_id, market_title=market_title, market_id=market_id
        )
    )
    _identifier_name = lambda identifier: api_db.identifier_name(identifier)
    build_system_health_payload = lambda: system_service.build_system_health_payload(runtime.system_health)
    enrich_market_rows_with_runtime_prices = lambda rows, max_updates=18, force_refresh=False: (
        market_service.enrich_market_rows_with_runtime_prices(
            runtime.market_context, rows, max_updates=max_updates, force_refresh=force_refresh
        )
    )
    fetch_dashboard_market_status = lambda now_iso: query_service.fetch_dashboard_market_status(
        runtime.dashboard_status, now_iso
    )
    fetch_dashboard_recent_markets = lambda now_iso, window_size: query_service.fetch_dashboard_recent_markets(
        runtime.dashboard_recent_markets, now_iso, window_size
    )
    fetch_dashboard_trade_volume = lambda window_size: query_service.fetch_dashboard_trade_volume(
        runtime.dashboard_trade_volume, window_size
    )
    fetch_recent_trade_window_bounds = lambda window_size: query_service.fetch_recent_trade_window_bounds(
        runtime.recent_trade_window, window_size
    )
    fetch_trade_count_estimate = lambda: query_service.fetch_trade_count_estimate(runtime.trade_count_estimate)
    get_active_markets_snapshot = lambda page_size=40, include_runtime_prices=False, include_change_24h=False: (
        market_service.get_active_markets_snapshot(
            runtime.market_context,
            page_size=page_size,
            include_runtime_prices=include_runtime_prices,
            include_change_24h=include_change_24h,
        )
    )
    get_alpha_signal_snapshot = lambda limit=8: signal_service.get_alpha_signal_snapshot(
        runtime.signal_context, limit=limit
    )
    get_bootstrap_payload_cached = lambda: bootstrap_service.get_bootstrap_payload_cached(runtime.bootstrap_cache)
    get_cached_json = lambda namespace, cache_key: api_cache.get_cached_json(runtime.cache, namespace, cache_key)
    get_cached_runtime_payload = lambda namespace, cache_key: api_cache.get_cached_runtime_payload(
        runtime.cache, namespace, cache_key
    )
    get_crypto_funding_watch_snapshot = lambda limit=16: crypto_funding_service.get_crypto_funding_watch_snapshot(
        runtime.crypto_funding, limit=limit
    )
    get_finance_market_atlas_snapshot = lambda limit=16: finance_panels_service.get_finance_market_atlas_snapshot(
        runtime.finance_panels_context, limit=limit
    )
    get_equity_event_command_snapshot = lambda limit=12: finance_panels_service.get_equity_event_command_snapshot(
        runtime.finance_panels_context, limit=limit
    )
    get_onchain_tradfi_perp_radar_snapshot = lambda limit=12: (
        finance_panels_service.get_onchain_tradfi_perp_radar_snapshot(runtime.finance_panels_context, limit=limit)
    )
    get_finance_liquidity_regime_snapshot = lambda limit=12: (
        finance_panels_service.get_finance_liquidity_regime_snapshot(runtime.finance_panels_context, limit=limit)
    )
    get_existing_trade_read_source = lambda: api_db.get_existing_trade_read_source(runtime.api_db_context)
    get_gamma_active_market_filter = lambda: market_data_client.get_gamma_active_market_filter(
        runtime.market_data_client_context
    )
    get_latest_content_snapshot = lambda limit=8: query_service.get_latest_content_snapshot(
        runtime.query_context, limit=limit
    )
    get_market_by_id = lambda market_id: market_service.get_market_by_id(runtime.market_context, market_id)
    get_market_chart_payload = lambda market_id, range_name="1d", interval="5m": (
        market_service.get_market_chart_payload(
            runtime.market_context, market_id, range_name=range_name, interval=interval
        )
    )
    get_market_clob_price_series = lambda market, range_name="1d", interval="5m": (
        market_data_client.get_market_clob_price_series(
            runtime.market_data_client_context, market, range_name=range_name, interval=interval
        )
    )
    get_market_clob_price_snapshot = lambda market: market_data_client.get_market_clob_price_snapshot(
        runtime.market_data_client_context, market
    )
    get_market_group_snapshot = lambda items, kind: runtime_service.get_market_group_snapshot(
        runtime.runtime_context, items, kind=kind
    )
    get_market_groups_payload = lambda query="", page=1, page_size=80, sort="active": (
        market_group_service.get_market_groups_payload(
            runtime.market_group_context, query=query, page=page, page_size=page_size, sort=sort
        )
    )
    get_polymarket_macro_map_snapshot = lambda limit=12: polymarket_macro_map_service.get_polymarket_macro_map_snapshot(
        runtime.polymarket_macro_map, limit=limit
    )
    get_market_group_chart_payload = lambda event_id, range_name="1d": (
        market_group_service.get_market_group_chart_payload(
            runtime.market_group_context, event_id, range_name=range_name
        )
    )
    get_jin10_panel_snapshot = lambda limit=24: jin10_runtime_service.get_jin10_panel_snapshot(
        runtime.jin10_runtime, limit=limit
    )
    get_oracle_events_by_market_id = lambda market_id: market_service.get_oracle_events_by_market_id(
        runtime.market_context, market_id
    )
    get_recent_oracle_events = lambda limit=24: query_service.get_recent_oracle_events(
        runtime.query_recent_oracle, limit=limit
    )
    get_recent_oracle_snapshot = lambda limit=24: market_service.get_recent_oracle_snapshot(
        runtime.recent_oracle, limit=limit
    )
    get_recent_trades = lambda limit=24: query_service.get_recent_trades(runtime.query_context, limit=limit)
    get_recent_trades_snapshot = lambda limit=24: market_service.get_recent_trades_snapshot(
        runtime.market_context, limit=limit
    )
    get_redis_client = lambda: api_cache.get_redis_client(runtime.cache)
    get_related_content_by_market_id = lambda market_id, limit=8: query_service.get_related_content_by_market_id(
        runtime.query_context, market_id, limit=limit
    )
    get_runtime_lob_payload = lambda market_id: lob_service.get_runtime_lob_payload(runtime.lob, market_id)
    get_snapshot_payload = lambda namespace, cache_key, builder, *, ttl_seconds: api_cache.get_snapshot_payload(
        runtime.cache, namespace, cache_key, builder, ttl_seconds=ttl_seconds
    )
    get_suspicious_trades_snapshot = lambda limit=12: signal_service.get_suspicious_trades_snapshot(
        runtime.signal_context, limit=limit
    )
    get_trades_by_market_id = lambda market_id, limit=100, offset=0, before=None: (
        market_service.get_trades_by_market_id(
            runtime.market_context, market_id, limit=limit, offset=offset, before=before
        )
    )
    get_whale_trades_snapshot = lambda limit=14: signal_service.get_whale_trades_snapshot(
        runtime.signal_context, limit=limit
    )
    get_worldcup_dashboard_snapshot = lambda: worldcup_dashboard_service.get_worldcup_dashboard_snapshot(
        runtime.worldcup_dashboard_context
    )
    get_yahoo_market_snapshot = lambda symbol, interval="30m", range_name="5d", ttl_seconds=None: (
        market_data_client.get_yahoo_market_snapshot(
            runtime.market_data_client_context,
            symbol,
            interval=interval,
            range_name=range_name,
            ttl_seconds=ttl_seconds,
        )
    )
    http_json_get = lambda url, params=None, timeout=12, headers=None: market_data_client.http_json_get(
        runtime.market_data_client_context, url, params=params, timeout=timeout, headers=headers
    )
    query_all = lambda sql, params=None: api_db.query_all(runtime.api_db_context, sql, params)
    query_one = lambda sql, params=None: api_db.query_one(runtime.api_db_context, sql, params)
    search_markets = lambda query, limit=10: market_service.search_markets(runtime.market_context, query, limit=limit)
    table_exists = lambda table_name: api_db.table_exists(runtime.api_db_context, table_name)
    get_backend = lambda: runtime.SETTINGS.database.backend
    get_orderfilled_outcome_mutation_proof = lambda **kwargs: (
        orderfilled_outcome_proof_service.get_orderfilled_outcome_mutation_proof(
            query_context={"app": runtime.app, "_resources": runtime.resources}, **kwargs
        )
    )
    runtime.address_context = {
        "_resources": runtime.resources,
        "app": runtime.app,
        "get_backend": get_backend,
        "get_cached_json": get_cached_json,
        "set_cached_json": runtime.set_cached_json,
        "ADDRESS_CACHE_TTL_SECONDS": runtime.SETTINGS.address_cache_ttl_seconds,
        "get_markets_payload_cached": runtime.get_markets_payload_cached,
        "normalize_address": normalize_address,
        "normalize_trade": normalize_trade,
        "query_all": query_all,
        "query_one": query_one,
        "utc_date_days_ago": utc_date_days_ago,
    }
    runtime.api_db_context = {
        "_resources": runtime.resources,
        "DB_PATH": runtime.SETTINGS.db_path,
        "LEGACY_TRADES_TABLE": LEGACY_TRADES_TABLE,
        "TRADE_READ_SOURCE": runtime.TRADE_READ_SOURCE,
        "TRADE_V2_CORE_TABLE": TRADE_V2_CORE_TABLE,
        "app": runtime.app,
        "dict_from_row": dict_from_row,
        "get_backend": get_backend,
        "get_connection": runtime._api_connection_factory,
        "query_all": query_all,
        "query_one": query_one,
        "sql_identifier": sql_identifier,
        "table_exists": table_exists,
    }
    runtime.content_context = {
        "_resources": runtime.resources,
        "get_latest_content_snapshot": get_latest_content_snapshot,
        "get_related_content_by_market_id": get_related_content_by_market_id,
        "get_snapshot_payload": get_snapshot_payload,
        "query_one": query_one,
        "table_exists": table_exists,
    }
    runtime.finance_panels_context = {
        "_resources": runtime.resources,
        "app": runtime.app,
        "get_crypto_funding_watch_snapshot": get_crypto_funding_watch_snapshot,
        "get_market_groups_payload": get_market_groups_payload,
        "get_snapshot_payload": get_snapshot_payload,
        "get_yahoo_market_snapshot": get_yahoo_market_snapshot,
        "utc_now_iso": utc_now_iso,
    }
    runtime.global_transport_shipping_context = {
        "_resources": runtime.resources,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "app": runtime.app,
        "get_cached_json": get_cached_json,
        "http_form_post": runtime.http_form_post,
        "http_json_get": http_json_get,
        "http_text_get": runtime.http_text_get,
        "search_markets": search_markets,
        "set_cached_json": runtime.set_cached_json,
        "utc_now_iso": utc_now_iso,
    }
    runtime.live_video_source_context = {
        "_resources": runtime.resources,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "get_cached_json": get_cached_json,
        "http_json_get": http_json_get,
        "http_text_get": runtime.http_text_get,
        "requests": requests,
        "set_cached_json": runtime.set_cached_json,
        "utc_now_iso": utc_now_iso,
    }
    runtime.macro_cpi_panels_context = {
        "_resources": runtime.resources,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "app": runtime.app,
        "get_cached_json": get_cached_json,
        "http_json_get": http_json_get,
        "http_text_get": runtime.http_text_get,
        "set_cached_json": runtime.set_cached_json,
        "utc_now_iso": utc_now_iso,
    }
    runtime.macro_cpi_registry_context = {
        "_resources": runtime.resources,
        "BeautifulSoup": BeautifulSoup,
        "CRYPTO_COINGECKO_IDS": CRYPTO_COINGECKO_IDS,
        "FINANCE_RUNTIME_TTL_SECONDS": runtime.SETTINGS.finance_runtime_ttl_seconds,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "SPORTS_RUNTIME_TTL_SECONDS": runtime.SETTINGS.sports_runtime_ttl_seconds,
        "_safe_float": _safe_float,
        "app": runtime.app,
        "get_cached_json": get_cached_json,
        "get_snapshot_payload": get_snapshot_payload,
        "get_yahoo_market_snapshot": get_yahoo_market_snapshot,
        "http_json_get": http_json_get,
        "http_text_get": runtime.http_text_get,
        "requests": requests,
        "set_cached_json": runtime.set_cached_json,
        "utc_now_iso": utc_now_iso,
    }
    runtime.market_data_client_context = {
        "_resources": runtime.resources,
        "CLOB_API_BASE": runtime.SETTINGS.clob_api_base,
        "CLOB_TIMEOUT_SECONDS": runtime.SETTINGS.clob_timeout_seconds,
        "FINANCE_RUNTIME_TTL_SECONDS": runtime.SETTINGS.finance_runtime_ttl_seconds,
        "SETTINGS": runtime.SETTINGS,
        "_safe_float": _safe_float,
        "app": runtime.app,
        "format_trade_decimal": format_trade_decimal,
        "get_cached_runtime_payload": get_cached_runtime_payload,
        "get_clob_session": runtime.get_clob_session,
        "requests": requests,
        "set_cached_runtime_payload": runtime.set_cached_runtime_payload,
    }
    runtime.market_group_context = {
        "_resources": runtime.resources,
        "SETTINGS": runtime.SETTINGS,
        "app": runtime.app,
        "get_backend": get_backend,
        "get_cached_runtime_payload": get_cached_runtime_payload,
        "get_market_clob_price_series": get_market_clob_price_series,
        "get_orderfilled_outcome_mutation_proof": get_orderfilled_outcome_mutation_proof,
        "get_snapshot_payload": get_snapshot_payload,
        "http_json_get": http_json_get,
        "normalize_trade": normalize_trade,
        "query_all": query_all,
        "set_cached_runtime_payload": runtime.set_cached_runtime_payload,
        "table_exists": table_exists,
        "utc_now_iso": utc_now_iso,
    }
    runtime.market_context = {
        "_resources": runtime.resources,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "app": runtime.app,
        "build_market_status_case": build_market_status_case,
        "format_trade_decimal": format_trade_decimal,
        "get_backend": get_backend,
        "get_cached_json": get_cached_json,
        "get_cached_runtime_payload": get_cached_runtime_payload,
        "get_gamma_active_market_filter": get_gamma_active_market_filter,
        "get_market_clob_price_series": get_market_clob_price_series,
        "get_market_clob_price_snapshot": get_market_clob_price_snapshot,
        "get_markets_payload_cached": runtime.get_markets_payload_cached,
        "get_orderfilled_outcome_mutation_proof": get_orderfilled_outcome_mutation_proof,
        "get_recent_oracle_events": get_recent_oracle_events,
        "get_recent_trades": get_recent_trades,
        "get_runtime_lob_by_token_payload": get_runtime_lob_by_token_payload,
        "get_snapshot_payload": get_snapshot_payload,
        "get_yahoo_market_snapshot": get_yahoo_market_snapshot,
        "http_json_get": http_json_get,
        "normalize_market": normalize_market,
        "normalize_oracle_event": normalize_oracle_event,
        "normalize_trade": normalize_trade,
        "parse_iso_datetime": parse_iso_datetime,
        "parse_json_list": parse_json_list,
        "query_all": query_all,
        "query_one": query_one,
        "set_cached_json": runtime.set_cached_json,
        "set_cached_runtime_payload": runtime.set_cached_runtime_payload,
        "table_exists": table_exists,
        "utc_now_iso": utc_now_iso,
    }
    runtime.natural_hazards_context = {
        "_resources": runtime.resources,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "app": runtime.app,
        "http_bytes_get": runtime.http_bytes_get,
        "http_json_get": http_json_get,
        "http_text_get": runtime.http_text_get,
    }
    runtime.new_market_signal_context = {
        "_resources": runtime.resources,
        "REDIS_PREFIX": runtime.SETTINGS.redis_prefix,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "app": runtime.app,
        "get_cached_json": get_cached_json,
        "get_redis_client": get_redis_client,
        "set_cached_json": runtime.set_cached_json,
        "utc_now_iso": utc_now_iso,
    }
    runtime.polybeats_context = {
        "_resources": runtime.resources,
        "SIGNAL_RUNTIME_TTL_SECONDS": runtime.SETTINGS.signal_runtime_ttl_seconds,
        "_safe_decimal": _safe_decimal,
        "app": runtime.app,
        "format_trade_decimal": format_trade_decimal,
        "get_backend": get_backend,
        "get_orderfilled_outcome_mutation_proof": get_orderfilled_outcome_mutation_proof,
        "get_recent_trades": get_recent_trades,
        "get_related_content_by_market_id": get_related_content_by_market_id,
        "get_snapshot_payload": get_snapshot_payload,
        "normalize_address": normalize_address,
        "parse_iso_datetime": parse_iso_datetime,
        "query_all": query_all,
        "table_exists": table_exists,
        "utc_now_iso": utc_now_iso,
    }
    runtime.query_context = {
        "_resources": runtime.resources,
        "CONTENT_RUNTIME_PROVIDER": runtime.CONTENT_RUNTIME_PROVIDER,
        "DB_PATH": runtime.SETTINGS.db_path,
        "TRADE_V2_CORE_TABLE": TRADE_V2_CORE_TABLE,
        "_identifier_name": _identifier_name,
        "app": runtime.app,
        "build_market_status_case": build_market_status_case,
        "get_backend": get_backend,
        "get_connection": runtime._api_connection_factory,
        "get_existing_trade_read_source": get_existing_trade_read_source,
        "get_market_by_id": get_market_by_id,
        "get_orderfilled_outcome_mutation_proof": get_orderfilled_outcome_mutation_proof,
        "get_snapshot_payload": get_snapshot_payload,
        "get_trade_market_projection_sql": get_trade_market_projection_sql,
        "normalize_oracle_event": normalize_oracle_event,
        "normalize_trade": normalize_trade,
        "parse_json_list": parse_json_list,
        "query_all": query_all,
        "query_one": query_one,
        "table_exists": table_exists,
        "utc_date_days_ago": utc_date_days_ago,
    }
    runtime.runtime_context = {
        "_resources": runtime.resources,
        "BeautifulSoup": BeautifulSoup,
        "CRYPTO_COINGECKO_IDS": CRYPTO_COINGECKO_IDS,
        "FINANCE_RUNTIME_TTL_SECONDS": runtime.SETTINGS.finance_runtime_ttl_seconds,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "SPORTS_RUNTIME_TTL_SECONDS": runtime.SETTINGS.sports_runtime_ttl_seconds,
        "_safe_float": _safe_float,
        "app": runtime.app,
        "get_cached_json": get_cached_json,
        "get_snapshot_payload": get_snapshot_payload,
        "get_yahoo_market_snapshot": get_yahoo_market_snapshot,
        "http_json_get": http_json_get,
        "requests": requests,
        "set_cached_json": runtime.set_cached_json,
        "utc_now_iso": utc_now_iso,
    }
    runtime.signal_context = {
        "_resources": runtime.resources,
        "SIGNAL_RUNTIME_TTL_SECONDS": runtime.SETTINGS.signal_runtime_ttl_seconds,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "_safe_decimal": _safe_decimal,
        "app": runtime.app,
        "format_trade_address": format_trade_address,
        "format_trade_decimal": format_trade_decimal,
        "get_active_markets_snapshot": get_active_markets_snapshot,
        "get_backend": get_backend,
        "get_cached_json": get_cached_json,
        "get_cached_runtime_payload": get_cached_runtime_payload,
        "get_orderfilled_outcome_mutation_proof": get_orderfilled_outcome_mutation_proof,
        "get_recent_oracle_events": get_recent_oracle_events,
        "get_recent_trades": get_recent_trades,
        "iso_days_before": iso_days_before,
        "normalize_trade": normalize_trade,
        "parse_iso_datetime": parse_iso_datetime,
        "query_all": query_all,
        "set_cached_runtime_payload": runtime.set_cached_runtime_payload,
        "utc_date_days_ago": utc_date_days_ago,
        "utc_now_iso": utc_now_iso,
    }
    runtime.system_context = {
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "_resources": runtime.resources,
        "app": runtime.app,
        "describe_db_target": runtime.SETTINGS.database.describe,
        "get_cached_json": get_cached_json,
        "get_lob_runtime_status": lob_service.get_lob_runtime_status,
        "get_redis_client": get_redis_client,
        "query_all": query_all,
        "query_one": query_one,
        "set_cached_json": runtime.set_cached_json,
        "table_exists": table_exists,
        "utc_now_iso": utc_now_iso,
    }
    runtime.world_cup_match_ops_context = {
        "_resources": runtime.resources,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "app": runtime.app,
        "get_cached_json": get_cached_json,
        "get_worldcup_dashboard_snapshot": get_worldcup_dashboard_snapshot,
        "set_cached_json": runtime.set_cached_json,
        "utc_now_iso": utc_now_iso,
    }
    runtime.worldcup_dashboard_context = {
        "_resources": runtime.resources,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "get_cached_json": get_cached_json,
    }
    runtime.worldcup_intel_context = {
        "_resources": runtime.resources,
        "BeautifulSoup": BeautifulSoup,
        "SETTINGS": runtime.SETTINGS,
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "get_cached_json": get_cached_json,
        "http_json_get": http_json_get,
        "http_text_get": runtime.http_text_get,
        "requests": requests,
        "set_cached_json": runtime.set_cached_json,
    }
    runtime.bootstrap_cache = bootstrap_service.BootstrapCacheDependencies(
        resources=runtime.resources,
        builder=bootstrap_service.BootstrapCoreDependencies(
            application=runtime.app,
            commodity_symbols=COMMODITY_SYMBOLS,
            finance_runtime_ttl_seconds=int(runtime.SETTINGS.finance_runtime_ttl_seconds),
            query_all=query_all,
            query_one=query_one,
            utc_now_iso=utc_now_iso,
            utc_date_days_ago=utc_date_days_ago,
            parse_json_list=parse_json_list,
            get_gamma_active_market_filter=get_gamma_active_market_filter,
            enrich_market_rows_with_runtime_prices=enrich_market_rows_with_runtime_prices,
            get_bootstrap_component_cached=runtime.get_bootstrap_component_cached,
            get_market_groups_payload=get_market_groups_payload,
            get_market_by_id=get_market_by_id,
            normalize_market=normalize_market,
            get_trades_by_market_id=get_trades_by_market_id,
            get_oracle_events_by_market_id=get_oracle_events_by_market_id,
            table_exists=table_exists,
            get_related_content_by_market_id=get_related_content_by_market_id,
            get_recent_trades_snapshot=get_recent_trades_snapshot,
            get_recent_oracle_snapshot=get_recent_oracle_snapshot,
            get_latest_content_snapshot=get_latest_content_snapshot,
            get_market_group_snapshot=get_market_group_snapshot,
            build_system_health_payload=build_system_health_payload,
        ),
        application=runtime.app,
        snapshot_store=runtime.SNAPSHOT_STORE,
        cache=runtime._bootstrap_cache,
        cache_lock=runtime._bootstrap_cache_lock,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        cache_ttl_seconds=int(runtime.SETTINGS.bootstrap_cache_ttl_seconds),
        component_ttl_seconds=int(runtime.SETTINGS.bootstrap_component_ttl_seconds),
    )
    runtime.dashboard_cache = bootstrap_service.DashboardCacheDependencies(
        resources=runtime.resources,
        builder=bootstrap_service.DashboardBuildDependencies(
            fetch_market_status=fetch_dashboard_market_status,
            fetch_trade_volume=fetch_dashboard_trade_volume,
            fetch_recent_markets=fetch_dashboard_recent_markets,
            fetch_trade_window_bounds=fetch_recent_trade_window_bounds,
            fetch_trade_count_estimate=fetch_trade_count_estimate,
            query_one=query_one,
            iso_days_before=iso_days_before,
            utc_now_iso=utc_now_iso,
            recent_trade_window=int(runtime.SETTINGS.recent_trade_window),
            cache_ttl_seconds=int(runtime.SETTINGS.dashboard_cache_ttl_seconds),
        ),
        application=runtime.app,
        snapshot_store=runtime.SNAPSHOT_STORE,
        cache=runtime._dashboard_cache,
        cache_lock=runtime._dashboard_cache_lock,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        utc_now_iso=utc_now_iso,
        recent_trade_window=int(runtime.SETTINGS.recent_trade_window),
        cache_ttl_seconds=int(runtime.SETTINGS.dashboard_cache_ttl_seconds),
    )
    runtime.bootstrap_prewarm = bootstrap_service.BootstrapPrewarmDependencies(
        resources=runtime.resources,
        bootstrap=bootstrap_service.BootstrapCoreDependencies(
            application=runtime.app,
            commodity_symbols=COMMODITY_SYMBOLS,
            finance_runtime_ttl_seconds=int(runtime.SETTINGS.finance_runtime_ttl_seconds),
            query_all=query_all,
            query_one=query_one,
            utc_now_iso=utc_now_iso,
            utc_date_days_ago=utc_date_days_ago,
            parse_json_list=parse_json_list,
            get_gamma_active_market_filter=get_gamma_active_market_filter,
            enrich_market_rows_with_runtime_prices=enrich_market_rows_with_runtime_prices,
            get_bootstrap_component_cached=runtime.get_bootstrap_component_cached,
            get_market_groups_payload=get_market_groups_payload,
            get_market_by_id=get_market_by_id,
            normalize_market=normalize_market,
            get_trades_by_market_id=get_trades_by_market_id,
            get_oracle_events_by_market_id=get_oracle_events_by_market_id,
            table_exists=table_exists,
            get_related_content_by_market_id=get_related_content_by_market_id,
            get_recent_trades_snapshot=get_recent_trades_snapshot,
            get_recent_oracle_snapshot=get_recent_oracle_snapshot,
            get_latest_content_snapshot=get_latest_content_snapshot,
            get_market_group_snapshot=get_market_group_snapshot,
            build_system_health_payload=build_system_health_payload,
        ),
        application=runtime.app,
        commodity_symbols=COMMODITY_SYMBOLS,
        finance_runtime_ttl_seconds=int(runtime.SETTINGS.finance_runtime_ttl_seconds),
        signal_runtime_ttl_seconds=int(runtime.SETTINGS.signal_runtime_ttl_seconds),
        snapshot_prewarm_enabled=bool(runtime.SETTINGS.snapshot_prewarm_enabled),
        get_market_groups_payload=get_market_groups_payload,
        get_market_group_chart_payload=get_market_group_chart_payload,
        get_market_group_snapshot=get_market_group_snapshot,
        get_bootstrap_component_cached=runtime.get_bootstrap_component_cached,
        get_active_markets_snapshot=get_active_markets_snapshot,
        get_recent_oracle_snapshot=get_recent_oracle_snapshot,
        get_recent_trades_snapshot=get_recent_trades_snapshot,
        get_finance_market_atlas_snapshot=get_finance_market_atlas_snapshot,
        get_equity_event_command_snapshot=get_equity_event_command_snapshot,
        get_onchain_tradfi_perp_radar_snapshot=get_onchain_tradfi_perp_radar_snapshot,
        get_finance_liquidity_regime_snapshot=get_finance_liquidity_regime_snapshot,
        get_whale_trades_snapshot=get_whale_trades_snapshot,
        get_suspicious_trades_snapshot=get_suspicious_trades_snapshot,
        get_alpha_signal_snapshot=get_alpha_signal_snapshot,
        get_jin10_panel_snapshot=get_jin10_panel_snapshot,
        get_bootstrap_payload_cached=get_bootstrap_payload_cached,
    )
    runtime.breaking_event_radar = breaking_event_radar_service.BreakingEventRadarDependencies(
        resources=runtime.resources,
        utc_now_iso=utc_now_iso,
        settings=runtime.SETTINGS,
        http_json_get=http_json_get,
        search_markets=search_markets,
        get_cached_json=get_cached_json,
        snapshot_store=runtime.SNAPSHOT_STORE,
        set_cached_json=runtime.set_cached_json,
        application=runtime.app,
    )
    runtime.latest_content = content_service.LatestContentDependencies.from_context(runtime.content_context)
    runtime.related_content = content_service.RelatedContentDependencies.from_context(runtime.content_context)
    runtime.cpi_release_calendar = cpi_release_calendar_service.CpiReleaseCalendarDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        http_text_get=runtime.http_text_get,
        beautiful_soup=BeautifulSoup,
        get_polymarket_macro_map_snapshot=get_polymarket_macro_map_snapshot,
        utc_now_iso=utc_now_iso,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
    )
    runtime.crypto_funding = crypto_funding_service.CryptoFundingDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        http_json_get=http_json_get,
        utc_now_iso=utc_now_iso,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        get_snapshot_payload=get_snapshot_payload,
    )
    runtime.defi_token_watch = defi_token_watch_service.DefiTokenWatchDependencies(
        settings=runtime.SETTINGS,
        http_json_get=http_json_get,
        utc_now_iso=utc_now_iso,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        get_snapshot_payload=get_snapshot_payload,
    )
    runtime.energy_gasoline_shock = energy_gasoline_shock_service.EnergyGasolineShockDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        http_bytes_get=runtime.http_bytes_get,
        xlrd=xlrd,
        utc_now_iso=utc_now_iso,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
    )
    runtime.f1_runtime = f1_runtime_service.F1RuntimeDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        requests_lib=requests,
        utc_now_iso=utc_now_iso,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        snapshot_store=runtime.SNAPSHOT_STORE,
        sports_runtime_ttl_seconds=runtime.SETTINGS.sports_runtime_ttl_seconds,
    )
    runtime.finance_watch = finance_watch_panels_service.FinanceWatchDependencies(
        settings=runtime.SETTINGS,
        http_json_get=http_json_get,
        http_text_get=runtime.http_text_get,
        get_yahoo_market_snapshot=get_yahoo_market_snapshot,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        get_snapshot_payload=get_snapshot_payload,
        get_crypto_funding_watch_snapshot=get_crypto_funding_watch_snapshot,
        crypto_funding=crypto_funding_service.CryptoFundingDependencies(
            settings=runtime.SETTINGS,
            application=runtime.app,
            http_json_get=http_json_get,
            utc_now_iso=utc_now_iso,
            snapshot_store=runtime.SNAPSHOT_STORE,
            get_cached_json=get_cached_json,
            set_cached_json=runtime.set_cached_json,
            get_snapshot_payload=get_snapshot_payload,
        ),
        external_sources=finance_external_sources_service.FinanceExternalSourceDependencies(
            settings=runtime.SETTINGS,
            http_json_get=http_json_get,
            http_json_post=None,
            get_yahoo_market_snapshot=get_yahoo_market_snapshot,
            get_cached_json=get_cached_json,
            snapshot_store=runtime.SNAPSHOT_STORE,
        ),
    )
    runtime.food_retail_basket = food_retail_basket_service.FoodRetailBasketDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        http_text_get=runtime.http_text_get,
        utc_now_iso=utc_now_iso,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
    )
    runtime.geo_sanctions_shock = geo_sanctions_shock_service.GeoSanctionsShockDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        utc_now_iso=utc_now_iso,
        requests_lib=requests,
        http_json_get=http_json_get,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_acled_auth_state=None,
        store_acled_auth_state=None,
    )
    runtime.global_transport_shipping = (
        global_transport_shipping_service.GlobalTransportShippingDependencies.from_context(
            runtime.global_transport_shipping_context
        )
    )
    runtime.global_weather_map = global_weather_map_service.GlobalWeatherMapDependencies(
        resources=runtime.resources,
        settings=runtime.SETTINGS,
        application=runtime.app,
        http_json_get=http_json_get,
        utc_now_iso=utc_now_iso,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        lob_reader=get_runtime_lob_by_token_payload,
        get_connection=runtime._api_connection_factory,
        database_path=runtime.SETTINGS.db_path,
        runtime_state=runtime.resources.weather_state,
    )
    runtime.grid_esports = grid_esports_service.GridEsportsDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        requests_lib=requests,
        http_json_post=None,
        search_markets=search_markets,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        get_snapshot_payload=get_snapshot_payload,
        snapshot_store=runtime.SNAPSHOT_STORE,
        utc_now_iso=utc_now_iso,
    )
    runtime.jin10_runtime = jin10_runtime_service.Jin10RuntimeDependencies(
        settings=runtime.SETTINGS,
        requests_lib=requests,
        utc_now_iso=utc_now_iso,
        snapshot_store=runtime.SNAPSHOT_STORE,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        signal_runtime_ttl_seconds=runtime.SETTINGS.signal_runtime_ttl_seconds,
    )
    runtime.live_video_source = live_video_source_service.LiveVideoSourceDependencies.from_context(
        runtime.live_video_source_context
    )
    runtime.lob = lob_service.LobDependencies(get_market_by_id)
    runtime.market_quality = market_quality_service.MarketQualityDependencies(
        resources=runtime.resources,
        application=runtime.app,
        query_one=query_one,
        query_all=query_all,
        table_exists=table_exists,
        get_snapshot_payload=get_snapshot_payload,
        get_recent_oracle_snapshot=get_recent_oracle_snapshot,
        utc_now_iso=utc_now_iso,
    )
    runtime.recent_oracle = market_service.RecentOracleDependencies.from_context(runtime.market_context)
    runtime.market_workspace_cache = market_workspace_cache_service.MarketWorkspaceCacheDependencies(
        resources=runtime.resources,
        cache=runtime.cache,
        application=runtime.app,
        snapshot_store=runtime.SNAPSHOT_STORE,
        utc_now_iso=utc_now_iso,
        build_detail=lambda market_id: market_service.get_market_detail_payload(runtime.market_context, market_id),
        build_chart=get_market_chart_payload,
        build_flow=get_trades_by_market_id,
        build_lob=get_runtime_lob_payload,
        get_market_by_id=get_market_by_id,
        detail_ttl=runtime.SETTINGS.workspace_detail_ttl_seconds,
        chart_ttl=runtime.SETTINGS.workspace_chart_ttl_seconds,
        flow_ttl=runtime.SETTINGS.workspace_flow_ttl_seconds,
    )
    runtime.natural_hazard = NaturalHazardDependencies.from_context(runtime.natural_hazards_context)
    runtime.polymarket_macro_map = polymarket_macro_map_service.PolymarketMacroMapDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        http_json_get=http_json_get,
        utc_now_iso=utc_now_iso,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        snapshot_store=runtime.SNAPSHOT_STORE,
    )
    runtime.dashboard_recent_markets = query_service.DashboardRecentMarketsDependencies.from_context(
        runtime.query_context
    )
    runtime.dashboard_status = query_service.DashboardStatusDependencies.from_context(runtime.query_context)
    runtime.dashboard_trade_volume = query_service.DashboardTradeVolumeDependencies.from_context(runtime.query_context)
    runtime.query_recent_oracle = query_service.RecentOracleDependencies.from_context(runtime.query_context)
    runtime.recent_trade_window = query_service.RecentTradeWindowDependencies.from_context(runtime.query_context)
    runtime.trade_count_estimate = query_service.TradeCountEstimateDependencies.from_context(runtime.query_context)
    runtime.sports_odds = sports_odds_service.SportsOddsDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        search_markets=search_markets,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        snapshot_store=runtime.SNAPSHOT_STORE,
        utc_now_iso=utc_now_iso,
        http_json_get=http_json_get,
        get_http_quota=None,
    )
    runtime.seed_health = system_service.SeedHealthDependencies.from_context(runtime.system_context)
    runtime.system_health = system_service.SystemHealthDependencies.from_context(runtime.system_context)
    runtime.tech_panels = tech_panels_service.TechPanelsDependencies(
        settings=runtime.SETTINGS,
        application=runtime.app,
        http_text_get=runtime.http_text_get,
        http_text_post=None,
        http_json_get=http_json_get,
        get_yahoo_market_snapshot=get_yahoo_market_snapshot,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        get_snapshot_payload=get_snapshot_payload,
        snapshot_store=runtime.SNAPSHOT_STORE,
    )
    runtime.weather_news = weather_news_service.WeatherNewsDependencies(
        resources=runtime.resources,
        settings=runtime.SETTINGS,
        application=runtime.app,
        http_text_get=runtime.http_text_get,
        utc_now_iso=utc_now_iso,
        get_cached_json=get_cached_json,
        set_cached_json=runtime.set_cached_json,
        snapshot_store=runtime.SNAPSHOT_STORE,
    )
    runtime.agent_snapshot_context = {
        "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
        "app": runtime.app,
        "get_active_markets_snapshot": get_active_markets_snapshot,
        "get_cached_json": get_cached_json,
        "get_market_by_id": get_market_by_id,
        "get_market_groups_payload": get_market_groups_payload,
        "get_recent_oracle_snapshot": get_recent_oracle_snapshot,
        "get_recent_trades_snapshot": get_recent_trades_snapshot,
        "get_trades_by_market_id": get_trades_by_market_id,
        "set_cached_json": runtime.set_cached_json,
    }
    runtime.agent_snapshot_context["get_trades_by_market_id"] = lambda market_id, limit=100, offset=0: (
        market_workspace_cache_service.get_market_flow_rows(
            runtime.market_workspace_cache, market_id, limit=limit, offset=offset
        )
    )


from api.routes import analytics as analytics_routes
from api.routes import content as content_routes
from api.routes import bootstrap as bootstrap_routes
from api.routes import runtime_sports as runtime_sports_routes
from api.routes import auth as auth_routes
from api.routes import market_groups as market_groups_routes
from api.runtime_panels import types as runtime_panel_types
from api.routes import runtime_panels as runtime_panels_routes
from api.routes import product as product_routes
from api.routes import mcp as mcp_routes
from api.routes import data_quality as data_quality_routes
from api.routes import agent_snapshots as agent_snapshots_routes
from api.routes import system as system_routes
from api.routes import agent as agent_routes
from api.routes import markets as markets_routes
from api.routes import lob as lob_routes
from api.routes import schema as schema_routes


def build_blueprints(runtime: ServiceRuntime):

    return (
        analytics_routes.create_analytics_blueprint(
            analytics_routes.AnalyticsRouteDependencies(
                get_top_addresses_cached=lambda days=None, limit=50: address_service.get_top_addresses_cached(
                    runtime.address_context, days, limit
                ),
                get_active_addresses_cached=lambda days=30: address_service.get_active_addresses_cached(
                    runtime.address_context, days
                ),
                normalize_address=normalize_address,
                get_address_summary_cached=lambda address, days=30: address_service.get_address_summary_cached(
                    runtime.address_context, address, days
                ),
                get_address_trades_payload=lambda address, **kwargs: address_service.get_address_trades_payload(
                    runtime.address_context, address, **kwargs
                ),
            )
        ),
        content_routes.create_content_blueprint(
            content_routes.ContentRouteDependencies(
                get_market_by_id=lambda market_id: market_service.get_market_by_id(runtime.market_context, market_id),
                get_related_content_payload=lambda market_id, limit=8: content_service.get_related_content_payload(
                    runtime.related_content, market_id, limit=limit
                ),
                get_latest_content_payload=lambda limit=8: content_service.get_latest_content_payload(
                    runtime.latest_content, limit=limit
                ),
                get_runtime_content_latest=lambda limit=8: {
                    "items": runtime.CONTENT_RUNTIME_PROVIDER.get_latest_items(limit=limit),
                    "sourceMode": "runtime-rss",
                },
            )
        ),
        bootstrap_routes.create_bootstrap_blueprint(
            bootstrap_routes.BootstrapRouteDependencies(
                get_dashboard_payload_cached=runtime.get_dashboard_payload_cached,
                get_bootstrap_payload_cached=lambda: bootstrap_service.get_bootstrap_payload_cached(
                    runtime.bootstrap_cache
                ),
                search_markets=lambda query, limit=10: market_service.search_markets(
                    runtime.market_context, query, limit=limit
                ),
            )
        ),
        runtime_sports_routes.create_runtime_sports_blueprint(
            runtime_sports_routes.RuntimeSportsRouteDependencies(
                get_nba_scoreboard_snapshot=lambda limit=10: runtime_service.get_nba_scoreboard_snapshot(
                    runtime.runtime_context, limit=limit
                ),
                get_nba_intel_snapshot=lambda limit=12: runtime_service.get_nba_intel_snapshot(
                    runtime.runtime_context, limit=limit
                ),
                get_nba_matchup_predictor_snapshot=lambda limit=8: runtime_service.get_nba_matchup_predictor_snapshot(
                    runtime.runtime_context, limit=limit
                ),
                get_worldcup_intel_snapshot=lambda limit=96: worldcup_intel_service.get_worldcup_intel_snapshot(
                    runtime.worldcup_intel_context, limit=limit
                ),
                get_worldcup_dashboard_snapshot=lambda: worldcup_dashboard_service.get_worldcup_dashboard_snapshot(
                    runtime.worldcup_dashboard_context
                ),
                get_worldcup_core_snapshot=lambda: worldcup_dashboard_service.get_worldcup_core_snapshot(
                    runtime.worldcup_dashboard_context
                ),
                get_worldcup_live_snapshot=lambda: worldcup_dashboard_service.get_worldcup_live_snapshot(
                    runtime.worldcup_dashboard_context
                ),
                get_worldcup_panel_snapshot=lambda panel_id: worldcup_dashboard_service.get_worldcup_panel_snapshot(
                    runtime.worldcup_dashboard_context, panel_id
                ),
            )
        ),
        auth_routes.create_auth_blueprint(
            auth_routes.AuthRouteDependencies(
                auth_enabled=auth_service.auth_enabled,
                authenticate_request=auth_service.authenticate_request,
                change_password=auth_service.change_password,
                create_api_key=auth_service.create_api_key,
                list_api_keys=auth_service.list_api_keys,
                list_audit_log=auth_service.list_audit_log,
                login=auth_service.login,
                logout=auth_service.logout,
                request_metadata=auth_service.request_metadata,
                revoke_api_key=auth_service.revoke_api_key,
                session_cookie_name=auth_service.session_cookie_name,
                session_snapshot=auth_service.session_snapshot,
                session_ttl_seconds=auth_service.session_ttl_seconds,
                cookie_secure=auth_service.cookie_secure,
                allowed_scopes=tuple(tuple(sorted(auth_service.ALLOWED_SCOPES))),
            )
        ),
        market_groups_routes.create_market_groups_blueprint(
            market_groups_routes.MarketGroupRouteDependencies(
                get_market_groups_payload=lambda query="", page=1, page_size=80, sort="active": (
                    market_group_service.get_market_groups_payload(
                        runtime.market_group_context, query=query, page=page, page_size=page_size, sort=sort
                    )
                ),
                get_market_group_detail_payload=lambda event_id: market_group_service.get_market_group_detail_payload(
                    runtime.market_group_context, event_id
                ),
                get_market_group_chart_payload=lambda event_id, range_name="1d": (
                    market_group_service.get_market_group_chart_payload(
                        runtime.market_group_context, event_id, range_name=range_name
                    )
                ),
            )
        ),
        runtime_panels_routes.create_runtime_panels_blueprint(
            runtime_panels_routes.RuntimePanelRouteDependencies(
                panel_context=runtime_panel_types.RuntimePanelContext(
                    get_alpha_signal_snapshot=lambda limit=8: signal_service.get_alpha_signal_snapshot(
                        runtime.signal_context, limit=limit
                    ),
                    get_polybeats_snapshot=lambda limit=8: polybeats_service.get_polybeats_snapshot(
                        runtime.polybeats_context, limit=limit
                    ),
                    get_whale_trades_snapshot=lambda limit=14: signal_service.get_whale_trades_snapshot(
                        runtime.signal_context, limit=limit
                    ),
                    get_suspicious_trades_snapshot=lambda limit=12: signal_service.get_suspicious_trades_snapshot(
                        runtime.signal_context, limit=limit
                    ),
                    get_world_cup_match_ops_snapshot=lambda limit=12: (
                        world_cup_match_ops_service.get_world_cup_match_ops_snapshot(
                            runtime.world_cup_match_ops_context, limit=limit
                        )
                    ),
                    get_new_market_signals_snapshot=lambda limit=12: (
                        new_market_signal_service.get_new_market_signals_snapshot(
                            runtime.new_market_signal_context, limit=limit
                        )
                    ),
                    commodity_symbols=COMMODITY_SYMBOLS,
                    crypto_symbols=CRYPTO_SYMBOLS,
                    get_market_group_snapshot=lambda items, kind: runtime_service.get_market_group_snapshot(
                        runtime.runtime_context, items, kind=kind
                    ),
                    get_breaking_event_radar_snapshot=lambda limit=12: (
                        breaking_event_radar_service.get_breaking_event_radar_snapshot(
                            runtime.breaking_event_radar, limit=limit
                        )
                    ),
                    get_market_tv_wire_snapshot=lambda limit=24, category=None: (
                        live_video_source_service.get_market_tv_wire_snapshot(
                            runtime.live_video_source, limit=limit, category=category
                        )
                    ),
                    get_market_youtube_channels_snapshot=lambda limit=12, category=None: (
                        live_video_source_service.get_market_youtube_channels_snapshot(
                            runtime.live_video_source, limit=limit, category=category
                        )
                    ),
                    get_global_weather_map_snapshot=lambda limit=34: (
                        global_weather_map_service.get_global_weather_map_snapshot(
                            runtime.global_weather_map, limit=limit
                        )
                    ),
                    get_weather_news_snapshot=lambda limit=24: weather_news_service.get_weather_news_snapshot(
                        runtime.weather_news, limit=limit
                    ),
                    finance=runtime_panel_types.FinanceRuntimePanelDependencies(
                        watch_panel_snapshot=lambda panel_id, limit=10: (
                            finance_watch_panels_service.get_finance_watch_panel_snapshot(
                                runtime.finance_watch, panel_id, limit=limit
                            )
                        ),
                        crypto_funding_watch_snapshot=lambda limit=16: (
                            crypto_funding_service.get_crypto_funding_watch_snapshot(
                                runtime.crypto_funding, limit=limit
                            )
                        ),
                        defi_token_watch_snapshot=lambda limit=10: (
                            defi_token_watch_service.get_defi_token_watch_snapshot(
                                runtime.defi_token_watch, limit=limit
                            )
                        ),
                        market_atlas_snapshot=lambda limit=16: finance_panels_service.get_finance_market_atlas_snapshot(
                            runtime.finance_panels_context, limit=limit
                        ),
                        equity_event_command_snapshot=lambda limit=12: (
                            finance_panels_service.get_equity_event_command_snapshot(
                                runtime.finance_panels_context, limit=limit
                            )
                        ),
                        commodity_equity_transmission_snapshot=lambda limit=8: (
                            commodity_equity_transmission_service.get_commodity_equity_transmission_snapshot(
                                commodity_equity_transmission_service.CommodityEquityTransmissionDependencies(
                                    get_market_group_snapshot=lambda items, kind: (
                                        runtime_service.get_market_group_snapshot(
                                            runtime.runtime_context, items, kind=kind
                                        )
                                    ),
                                    commodity_symbols=COMMODITY_SYMBOLS,
                                    search_markets=lambda query, limit=10: market_service.search_markets(
                                        runtime.market_context, query, limit=limit
                                    ),
                                    application=runtime.app,
                                    utc_now_iso=utc_now_iso,
                                ),
                                limit=limit,
                            )
                        ),
                        onchain_tradfi_perp_radar_snapshot=lambda limit=12: (
                            finance_panels_service.get_onchain_tradfi_perp_radar_snapshot(
                                runtime.finance_panels_context, limit=limit
                            )
                        ),
                        liquidity_regime_snapshot=lambda limit=12: (
                            finance_panels_service.get_finance_liquidity_regime_snapshot(
                                runtime.finance_panels_context, limit=limit
                            )
                        ),
                    ),
                    macro=runtime_panel_types.MacroRuntimePanelDependencies(
                        cpi_components_pressure_registry_snapshot=lambda limit=36: (
                            macro_cpi_registry_service.get_cpi_components_pressure_registry_snapshot(
                                runtime.macro_cpi_registry_context, limit=limit
                            )
                        ),
                        cpi_release_calendar_snapshot=lambda limit=8: (
                            cpi_release_calendar_service.get_cpi_release_calendar_snapshot(
                                runtime.cpi_release_calendar, limit=limit
                            )
                        ),
                        cpi_release_command_center_snapshot=lambda limit=36: (
                            macro_cpi_registry_service.get_cpi_release_command_center_snapshot(
                                runtime.macro_cpi_registry_context, limit=limit
                            )
                        ),
                        energy_gasoline_shock_snapshot=lambda limit=6: (
                            energy_gasoline_shock_service.get_energy_gasoline_shock_snapshot(
                                runtime.energy_gasoline_shock, limit=limit
                            )
                        ),
                        fed_rates_polymarket_gap_snapshot=lambda limit=8: (
                            macro_cpi_panels_service.get_fed_rates_polymarket_gap_snapshot(
                                runtime.macro_cpi_panels_context, limit=limit
                            )
                        ),
                        fed_reaction_growth_risk_board_snapshot=lambda limit=36: (
                            macro_cpi_registry_service.get_fed_reaction_growth_risk_board_snapshot(
                                runtime.macro_cpi_registry_context, limit=limit
                            )
                        ),
                        food_retail_basket_snapshot=lambda limit=8: (
                            food_retail_basket_service.get_food_retail_basket_snapshot(
                                runtime.food_retail_basket, limit=limit
                            )
                        ),
                        goods_tariff_supply_watch_snapshot=lambda limit=36: (
                            macro_cpi_registry_service.get_goods_tariff_supply_watch_snapshot(
                                runtime.macro_cpi_registry_context, limit=limit
                            )
                        ),
                        growth_demand_recession_tracker_snapshot=lambda limit=8: (
                            macro_cpi_panels_service.get_growth_demand_recession_tracker_snapshot(
                                runtime.macro_cpi_panels_context, limit=limit
                            )
                        ),
                        inflation_nowcast_snapshot=lambda: runtime_service.get_inflation_nowcast_snapshot(
                            runtime.runtime_context
                        ),
                        jin10_panel_snapshot=lambda limit=24: jin10_runtime_service.get_jin10_panel_snapshot(
                            runtime.jin10_runtime, limit=limit
                        ),
                        labor_services_inflation_monitor_snapshot=lambda limit=36: (
                            macro_cpi_registry_service.get_labor_services_inflation_monitor_snapshot(
                                runtime.macro_cpi_registry_context, limit=limit
                            )
                        ),
                        labor_wage_services_pressure_snapshot=lambda limit=8: (
                            macro_cpi_panels_service.get_labor_wage_services_pressure_snapshot(
                                runtime.macro_cpi_panels_context, limit=limit
                            )
                        ),
                        polymarket_macro_map_snapshot=lambda limit=12: (
                            polymarket_macro_map_service.get_polymarket_macro_map_snapshot(
                                runtime.polymarket_macro_map, limit=limit
                            )
                        ),
                        shelter_rent_oer_pressure_snapshot=lambda limit=8: (
                            macro_cpi_panels_service.get_shelter_rent_oer_pressure_snapshot(
                                runtime.macro_cpi_panels_context, limit=limit
                            )
                        ),
                        supply_tariff_import_watch_snapshot=lambda limit=8: (
                            macro_cpi_panels_service.get_supply_tariff_import_watch_snapshot(
                                runtime.macro_cpi_panels_context, limit=limit
                            )
                        ),
                    ),
                    sports=runtime_panel_types.SportsRuntimePanelDependencies(
                        nba_matchup_predictor_snapshot=lambda limit=8: (
                            runtime_service.get_nba_matchup_predictor_snapshot(runtime.runtime_context, limit=limit)
                        ),
                        grid_esports_snapshot=lambda limit=10: grid_esports_service.get_grid_esports_snapshot(
                            runtime.grid_esports, limit=limit
                        ),
                        f1_panel_snapshot=lambda limit=10: f1_runtime_service.get_f1_panel_snapshot(
                            runtime.f1_runtime, limit=limit
                        ),
                        nba_intel_snapshot=lambda limit=12: runtime_service.get_nba_intel_snapshot(
                            runtime.runtime_context, limit=limit
                        ),
                        nba_scoreboard_snapshot=lambda limit=10: runtime_service.get_nba_scoreboard_snapshot(
                            runtime.runtime_context, limit=limit
                        ),
                        sports_odds_snapshot=lambda limit=8: sports_odds_service.get_sports_odds_snapshot(
                            runtime.sports_odds, limit=limit
                        ),
                    ),
                    technology=runtime_panel_types.TechnologyRuntimePanelDependencies(
                        panel_snapshot=lambda panel_id, limit=10: tech_panels_service.get_tech_panel_snapshot(
                            runtime.tech_panels, panel_id, limit=limit
                        )
                    ),
                    world=runtime_panel_types.WorldRuntimePanelDependencies(
                        geo_sanctions_shock_snapshot=lambda limit=geo_sanctions_shock_service.DEFAULT_ITEM_LIMIT: (
                            geo_sanctions_shock_service.get_geo_sanctions_shock_snapshot(
                                runtime.geo_sanctions_shock, limit=limit
                            )
                        ),
                        global_transport_shipping_snapshot=lambda limit=14: (
                            global_transport_shipping_service.get_global_transport_shipping_snapshot(
                                runtime.global_transport_shipping, limit=limit
                            )
                        ),
                        natural_hazards_snapshot=lambda limit=natural_hazards.DEFAULT_EVENT_LIMIT: (
                            natural_hazards.get_natural_hazards_snapshot(
                                runtime.natural_hazard, limit=limit, allow_provider_fetch=False
                            )
                        ),
                    ),
                ),
                utc_now_iso=utc_now_iso,
                natural_hazard_map_snapshot=lambda source, limit=natural_hazards.DEFAULT_EVENT_LIMIT, zoom=2.0, bbox=None: (
                    natural_hazards.get_natural_hazard_map_snapshot(
                        runtime.natural_hazards_context, source=source, limit=limit, zoom=zoom, bbox=bbox
                    )
                ),
                natural_hazard_event_detail=lambda event_id: natural_hazards.get_natural_hazard_event_detail(
                    runtime.natural_hazards_context, event_id=event_id
                ),
                natural_hazard_related_markets=runtime.get_natural_hazard_related_markets,
                aviation_viewport_snapshot=lambda bbox, zoom, limit=180: (
                    global_transport_shipping_service.get_aviation_viewport_snapshot(
                        runtime.global_transport_shipping_context, bbox=bbox, zoom=zoom, limit=limit
                    )
                ),
            )
        ),
        product_routes.create_product_blueprint(
            product_routes.ProductRouteDependencies(
                authenticate=auth_service.authenticate_user_request,
                request_metadata=auth_service.request_metadata,
                get_watchlist=product_service.get_watchlist,
                add_market=product_service.add_watchlist_market,
                remove_market=product_service.remove_watchlist_market,
                create_rule=product_service.create_alert_rule,
                delete_rule=product_service.delete_alert_rule,
                get_alerts=product_service.get_alert_events,
                mark_alert_read=product_service.mark_alert_read,
                mark_all_read=product_service.mark_all_alerts_read,
                get_preferences=product_service.get_notification_preferences,
                update_preferences=product_service.update_notification_preferences,
                get_web_push=web_push_service.get_status,
                subscribe_web_push=web_push_service.upsert_subscription,
                unsubscribe_web_push=web_push_service.revoke_subscription,
            )
        ),
        mcp_routes.create_mcp_blueprint(
            mcp_routes.McpRouteDependencies(
                authenticate=auth_service.authenticate_request,
                search_markets=lambda query, limit=10: market_service.search_markets(
                    runtime.market_context, query, limit=limit
                ),
                get_market_workspace=lambda market_id: market_workspace_cache_service.get_market_workspace_payload(
                    runtime.market_workspace_cache, market_id
                ),
                get_market_oracle=lambda market_id: market_service.get_market_oracle_payload(
                    runtime.market_context, market_id
                ),
                get_market_data_quality=lambda: market_quality_service.get_market_data_quality_payload(
                    runtime.market_quality
                ),
                get_public_briefing=briefing_service.get_public_briefing,
                allowed_origins=frozenset(
                    (str(value) for value in tuple(sorted(runtime.ALLOWED_ORIGINS)) if str(value))
                ),
            )
        ),
        data_quality_routes.create_data_quality_blueprint(
            data_quality_routes.DataQualityRouteDependencies(
                get_market_data_quality_payload=lambda: market_quality_service.get_market_data_quality_payload(
                    runtime.market_quality
                )
            )
        ),
        agent_snapshots_routes.create_agent_snapshot_blueprint(
            agent_snapshots_routes.AgentSnapshotRouteDependencies(
                source={
                    "app": runtime.app,
                    "SNAPSHOT_STORE": runtime.SNAPSHOT_STORE,
                    "get_cached_json": lambda namespace, cache_key: api_cache.get_cached_json(
                        runtime.cache, namespace, cache_key
                    ),
                },
                snapshot_store=runtime.SNAPSHOT_STORE,
            )
        ),
        system_routes.create_system_blueprint(
            system_routes.SystemRouteDependencies(
                authenticate_request=auth_service.authenticate_request,
                build_system_health_payload=lambda: system_service.build_system_health_payload(runtime.system_health),
                build_seed_health_payload=lambda: system_service.build_seed_health_payload(runtime.seed_health),
                describe_db_target=runtime.SETTINGS.database.describe,
                get_redis_client=lambda: api_cache.get_redis_client(runtime.cache),
            )
        ),
        agent_routes.create_agent_blueprint(
            agent_routes.AgentRouteDependencies(
                resources=runtime.resources,
                application=runtime.app,
                get_cached_json=lambda namespace, cache_key: api_cache.get_cached_json(
                    runtime.cache, namespace, cache_key
                ),
                set_cached_json=runtime.set_cached_json,
                get_redis_client=lambda: api_cache.get_redis_client(runtime.cache),
            )
        ),
        markets_routes.create_markets_blueprint(
            markets_routes.MarketRouteDependencies(
                sanitize_payload=lambda payload, **kw: (
                    markets_routes.outcome_semantics_service.sanitize_public_market_payload(
                        {
                            "query_all": lambda sql, params=None: api_db.query_all(runtime.api_db_context, sql, params),
                            "get_backend": lambda: runtime.SETTINGS.database.backend,
                        },
                        payload,
                        **kw,
                    )
                ),
                get_markets_payload=lambda status="active", query="", page=1, page_size=20: (
                    market_service.get_markets_payload(
                        runtime.market_context, status=status, query=query, page=page, page_size=page_size
                    )
                ),
                get_market_by_id=lambda market_id: market_service.get_market_by_id(runtime.market_context, market_id),
                get_market_by_slug=lambda slug: market_service.get_market_by_slug(runtime.market_context, slug),
                normalize_market=normalize_market,
                get_trades_by_market_id=lambda market_id, limit=100, offset=0, before=None: (
                    market_workspace_cache_service.get_market_flow_rows(
                        runtime.market_workspace_cache, market_id, limit=limit, offset=offset, before=before
                    )
                ),
                get_recent_trades_snapshot=lambda limit=24: market_service.get_recent_trades_snapshot(
                    runtime.market_context, limit=limit
                ),
                get_market_oracle_payload=lambda market_id: market_service.get_market_oracle_payload(
                    runtime.market_context, market_id
                ),
                get_recent_oracle_snapshot=lambda limit=24: market_service.get_recent_oracle_snapshot(
                    runtime.recent_oracle, limit=limit
                ),
                get_market_detail_payload=lambda market_id: market_workspace_cache_service.get_market_detail_payload(
                    runtime.market_workspace_cache, market_id
                ),
                get_market_chart_payload=lambda market_id, range_name="1d", interval="5m": (
                    market_workspace_cache_service.get_market_chart_payload(
                        runtime.market_workspace_cache, market_id, range_name=range_name, interval=interval
                    )
                ),
                get_market_workspace_payload=lambda market_id: (
                    market_workspace_cache_service.get_market_workspace_payload(
                        runtime.market_workspace_cache, market_id
                    )
                ),
                get_market_focus_tile_payload=lambda market_id: (
                    market_workspace_cache_service.get_market_focus_tile_payload(
                        runtime.market_workspace_cache, market_id
                    )
                ),
            )
        ),
        lob_routes.create_lob_blueprint(
            lob_routes.LobRouteDependencies(
                lambda market_id: market_workspace_cache_service.get_market_orderbook_payload(
                    runtime.market_workspace_cache, market_id
                ),
                lambda token_id, no_token_id="", market_title="", market_id=None: (
                    lob_service.get_runtime_lob_by_token_payload(
                        token_id, no_token_id=no_token_id, market_title=market_title, market_id=market_id
                    )
                ),
            )
        ),
        schema_routes.create_schema_blueprint(),
    )
