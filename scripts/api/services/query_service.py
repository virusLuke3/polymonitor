from __future__ import annotations

import json
from typing import Any, Dict, List

from api.services import clickhouse_orderfilled_service


def fetch_dashboard_market_status(ctx: dict, now_iso: str) -> List[Dict[str, Any]]:
    return ctx["query_all"](
        """
        SELECT status AS name, COUNT(*) AS value
        FROM (
            SELECT
                CASE
                    WHEN COALESCE(mss.has_settle, FALSE) = TRUE OR COALESCE(mss.settlement_code, 0) IN (1, 2, 3) THEN 'Settled'
                    WHEN COALESCE(mss.has_propose, FALSE) = TRUE THEN 'Proposed'
                    WHEN m.end_date IS NOT NULL AND m.end_date < ? THEN 'Closed'
                    ELSE 'Active'
                END AS status
            FROM markets m
            LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
        ) status_rows
        GROUP BY status
        ORDER BY value DESC
        """,
        (now_iso,),
    )


def fetch_recent_trade_window_bounds(ctx: dict, window_size: int) -> Dict[str, Any]:
    if ctx["table_exists"]("market_trade_daily_stats"):
        summary_days = 30 if window_size >= 50000 else 7
        summary_row = ctx["query_one"](
            """
            SELECT
                COALESCE(SUM(day_rows.trade_count), 0) AS trade_count,
                MIN(CONCAT(day_rows.trade_date, 'T00:00:00Z')) AS earliest_timestamp,
                MAX(day_rows.last_trade_at) AS latest_timestamp
            FROM (
                SELECT
                    trade_date,
                    SUM(trade_count) AS trade_count,
                    MAX(last_trade_at) AS last_trade_at
                FROM market_trade_daily_stats
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT ?
            ) day_rows
            """,
            (summary_days,),
        )
        if summary_row and (summary_row.get("latest_timestamp") is not None or int(summary_row.get("trade_count") or 0) > 0):
            summary_row["source"] = f"market_trade_daily_stats:{summary_days}d"
            return summary_row

    trade_source = ctx["get_existing_trade_read_source"]()
    if trade_source is None:
        return {"trade_count": 0, "earliest_timestamp": None, "latest_timestamp": None, "source": "none"}
    payload = ctx["query_one"](
        f"""
        SELECT
            COUNT(*) AS trade_count,
            MIN(timestamp) AS earliest_timestamp,
            MAX(timestamp) AS latest_timestamp
        FROM (
            SELECT timestamp
            FROM {trade_source}
            ORDER BY timestamp DESC
            LIMIT ?
        ) recent_trades
        """,
        (window_size,),
    )
    payload["source"] = ctx["_identifier_name"](trade_source)
    return payload


def fetch_dashboard_trade_volume(ctx: dict, window_size: int) -> List[Dict[str, Any]]:
    summary_threshold = ctx["utc_date_days_ago"](30)
    summary_rows = ctx["query_all"](
        """
        SELECT trade_date AS day, SUM(trade_count) AS trade_count
        FROM market_trade_daily_stats
        WHERE trade_date >= ?
        GROUP BY trade_date
        ORDER BY trade_date ASC
        """,
        (summary_threshold,),
    )
    if summary_rows:
        return summary_rows
    trade_source = ctx["get_existing_trade_read_source"]()
    if trade_source is None:
        return []
    return ctx["query_all"](
        f"""
        SELECT day, COUNT(*) AS trade_count
        FROM (
            SELECT substr(timestamp, 1, 10) AS day
            FROM {trade_source}
            ORDER BY timestamp DESC
            LIMIT ?
        ) recent_trades
        GROUP BY day
        ORDER BY day ASC
        """,
        (window_size,),
    )


def fetch_dashboard_recent_markets(ctx: dict, now_iso: str, window_size: int) -> List[Dict[str, Any]]:
    status_case = ctx["build_market_status_case"](now_iso)
    summary_threshold = ctx["utc_date_days_ago"](30)
    summary_rows = ctx["query_all"](
        f"""
        WITH activity AS (
            SELECT
                market_id,
                SUM(trade_count) AS trade_count,
                MAX(last_trade_at) AS last_trade_at
            FROM market_trade_daily_stats
            WHERE trade_date >= ?
            GROUP BY market_id
            ORDER BY trade_count DESC, last_trade_at DESC
            LIMIT 5
        )
        SELECT
            m.id,
            m.gamma_market_id,
            m.slug,
            m.title,
            m.end_date,
            {status_case} AS status,
            activity.trade_count,
            activity.last_trade_at,
            mlp.latest_price AS latest_price
        FROM activity
        JOIN markets m ON m.id = activity.market_id
        LEFT JOIN market_latest_prices mlp ON mlp.market_id = activity.market_id
        ORDER BY activity.trade_count DESC, activity.last_trade_at DESC
        """,
        (summary_threshold, now_iso),
    )
    if summary_rows:
        return summary_rows

    trade_source = ctx["get_existing_trade_read_source"]()
    if trade_source is None:
        return []
    return ctx["query_all"](
        f"""
        WITH recent_trades AS (
            SELECT market_id, timestamp, price, block_number, log_index
            FROM {trade_source}
            WHERE market_id IS NOT NULL
            ORDER BY timestamp DESC
            LIMIT ?
        ),
        activity AS (
            SELECT market_id, COUNT(*) AS trade_count, MAX(timestamp) AS last_trade_at
            FROM recent_trades
            GROUP BY market_id
            ORDER BY trade_count DESC, last_trade_at DESC
            LIMIT 5
        ),
        latest_price AS (
            SELECT market_id, price
            FROM (
                SELECT
                    market_id,
                    price,
                    ROW_NUMBER() OVER (
                        PARTITION BY market_id
                        ORDER BY timestamp DESC, block_number DESC, log_index DESC
                    ) AS row_num
                FROM recent_trades
            ) ranked_prices
            WHERE row_num = 1
        )
        SELECT
            m.id,
            m.gamma_market_id,
            m.slug,
            m.title,
            m.end_date,
            {status_case} AS status,
            activity.trade_count,
            activity.last_trade_at,
            latest_price.price AS latest_price
        FROM activity
        JOIN markets m ON m.id = activity.market_id
        LEFT JOIN latest_price ON latest_price.market_id = activity.market_id
        ORDER BY activity.trade_count DESC, activity.last_trade_at DESC
        """,
        (window_size, now_iso),
    )


def fetch_trade_count_estimate(ctx: dict) -> Dict[str, Any]:
    trade_source = ctx["get_existing_trade_read_source"]()
    if trade_source is None:
        return {"table_rows": 0, "auto_increment": 0}
    if ctx["get_backend"]() == "sqlite":
        return ctx["query_one"](
            f"""
            SELECT COUNT(*) AS table_rows, COALESCE(MAX(id), 0) AS auto_increment
            FROM {trade_source}
            """
        )
    return ctx["query_one"](
        f"""
        SELECT
            COALESCE(table_rows, 0) AS table_rows,
            COALESCE(auto_increment, 0) AS auto_increment
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = '{ctx["_identifier_name"](trade_source)}'
        """
    )


def get_recent_trades(ctx: dict, limit: int = 24) -> List[Dict[str, Any]]:
    clickhouse_rows = clickhouse_orderfilled_service.get_recent_trades(ctx, limit=limit)
    if clickhouse_rows is not None:
        return clickhouse_rows
    trade_source = ctx["get_existing_trade_read_source"]()
    if trade_source is None:
        return []
    if ctx["_identifier_name"](trade_source) == ctx["TRADE_V2_CORE_TABLE"]:
        rows = ctx["query_all"](
            f"""
            SELECT
                {ctx['get_trade_market_projection_sql']('t')},
                m.title AS market_title
            FROM {trade_source} t
            LEFT JOIN markets m ON m.id = t.market_id
            WHERE t.market_id IS NOT NULL
            ORDER BY t.block_number DESC, t.log_index DESC
            LIMIT ?
            """,
            (limit,),
        )
    else:
        rows = ctx["query_all"](
            f"""
            SELECT
                tx_hash, log_index, market_id, maker, taker, price, size, side, outcome,
                token_id, timestamp, block_number, order_hash, maker_asset_id, taker_asset_id,
                maker_amount, taker_amount, fee, contract,
                NULL AS market_title
            FROM {trade_source}
            WHERE market_id IS NOT NULL
            ORDER BY timestamp DESC, block_number DESC, log_index DESC
            LIMIT ?
            """,
            (limit,),
        )
    return [ctx["normalize_trade"](row) for row in rows]


def get_recent_oracle_events(ctx: dict, limit: int = 24) -> List[Dict[str, Any]]:
    rows = ctx["query_all"](
        """
        SELECT
            oe.id, oe.tx_hash, oe.block_number, oe.event_time, oe.event_status, oe.external_market_id,
            oe.market_id, COALESCE(m.title, oe.market_title) AS market_title, oe.matched_by,
            oe.question_id, oe.condition_id, oe.proposed_price, oe.settled_price, oe.payout,
            oe.requester, oe.proposer, oe.disputer, oe.proposal_transaction, oe.settlement_transaction,
            oe.source_adapter, oe.source_oracle, m.slug AS market_slug, m.category AS market_category,
            COALESCE(mss.completion_status, 'OPEN') AS completion_status,
            COALESCE(mss.is_trading_closed, FALSE) AS is_trading_closed,
            COALESCE(mss.is_resolved, FALSE) AS is_resolved,
            COALESCE(mss.is_final, FALSE) AS is_final,
            COALESCE(mss.settlement_code, 0) AS snapshot_settlement_code,
            COALESCE(mss.settlement_outcome, 'UNKNOWN') AS snapshot_settlement_outcome,
            mss.settlement_source AS snapshot_settlement_source
        FROM oracle_events oe
        LEFT JOIN markets m ON m.id = oe.market_id
        LEFT JOIN market_status_snapshot mss ON mss.market_id = m.id
        ORDER BY oe.block_number DESC, oe.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [ctx["normalize_oracle_event"](row) for row in rows]


def get_related_content_by_market_id(ctx: dict, market_id: int, limit: int = 8) -> Dict[str, Any]:
    market = ctx["get_market_by_id"](market_id)
    if not market:
        return {"marketId": market_id, "localMarketId": market_id, "items": []}
    if ctx["table_exists"]("content_items") and ctx["table_exists"]("content_links"):
        rows = ctx["query_all"](
            """
            SELECT
                ci.id,
                ci.content_type,
                ci.source,
                ci.title,
                ci.url,
                ci.published_at,
                ci.summary
            FROM content_links cl
            JOIN content_items ci ON ci.id = cl.content_id
            WHERE cl.market_id = ?
            ORDER BY ci.published_at DESC
            LIMIT ?
            """,
            (market_id, limit),
        )
        if rows:
            return {
                "marketId": market_id,
                "localMarketId": market_id,
                "items": [
                    {
                        "id": row.get("id"),
                        "contentType": row.get("content_type"),
                        "source": row.get("source"),
                        "title": row.get("title"),
                        "url": row.get("url"),
                        "publishedAt": row.get("published_at"),
                        "summary": row.get("summary"),
                    }
                    for row in rows
                ],
                "sourceMode": "database",
            }
    return {
        "marketId": market_id,
        "localMarketId": market_id,
        "items": ctx["CONTENT_RUNTIME_PROVIDER"].get_related_news(
            market_title=str(market.get("title") or ""),
            category=str(market.get("category") or ""),
            tags=ctx["parse_json_list"](market.get("tags")),
            limit=limit,
        ),
        "sourceMode": "runtime-rss",
    }


def get_latest_content_snapshot(ctx: dict, limit: int = 8) -> Dict[str, Any]:
    cache_key = json.dumps({"limit": limit}, sort_keys=True, ensure_ascii=True)

    def _builder() -> Dict[str, Any]:
        if ctx["table_exists"]("content_items"):
            rows = ctx["query_all"](
                """
                SELECT id, content_type, source, title, url, published_at, summary
                FROM content_items
                ORDER BY published_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return {
                "items": [
                    {
                        "id": row.get("id"),
                        "contentType": row.get("content_type"),
                        "source": row.get("source"),
                        "title": row.get("title"),
                        "url": row.get("url"),
                        "publishedAt": row.get("published_at"),
                        "summary": row.get("summary"),
                    }
                    for row in rows
                ],
                "sourceMode": "database",
            }
        return {
            "items": ctx["CONTENT_RUNTIME_PROVIDER"].get_latest_items(limit=limit),
            "sourceMode": "runtime-rss",
        }

    return ctx["get_snapshot_payload"]("snapshot:content:latest", cache_key, _builder, ttl_seconds=300)
