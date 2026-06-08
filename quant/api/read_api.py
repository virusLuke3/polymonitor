"""Read helpers for future /quant API endpoints."""

from __future__ import annotations

from typing import Any


def get_quant_price_markets(
    conn: Any,
    *,
    search: str | None = None,
    token_side: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return markets that actually have quant price rows available."""

    params: list[Any] = []
    search_text = (search or "").strip().lower()
    if search_text:
        text = f"%{search_text}%"
        prefix_text = f"{search_text}%"
        slug_prefix_text = f"{search_text}-%"
        slug_token_text = f"%-{search_text}-%"
        title_word_text = f"% {search_text} %"
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH candidates AS (
                    SELECT DISTINCT
                        md.market_id,
                        md.market_slug,
                        md.market_title,
                        md.condition_id,
                        md.end_date,
                        CASE
                            WHEN lower(md.market_slug) = %s THEN 0
                            WHEN lower(md.market_slug) LIKE %s THEN 1
                            WHEN lower(md.market_slug) LIKE %s THEN 2
                            WHEN lower(md.market_slug) LIKE %s THEN 3
                            WHEN lower(md.market_title) = %s THEN 4
                            WHEN lower(md.market_title) LIKE %s THEN 5
                            WHEN lower(md.market_title) LIKE %s THEN 6
                            ELSE 9
                        END AS search_rank
                    FROM quant.market_token_metadata md
                    WHERE md.market_slug IS NOT NULL
                      AND (lower(md.market_slug) LIKE %s OR lower(md.market_title) LIKE %s)
                    ORDER BY search_rank ASC, md.market_slug
                    LIMIT 200
                )
                SELECT
                    c.market_id,
                    c.market_slug,
                    COALESCE(%s, 'YES') AS token_side,
                    COALESCE(b.block_rows, 0) AS block_rows,
                    b.first_block,
                    b.last_block,
                    b.latest_block_price,
                    b.latest_block_at,
                    COALESCE(f.frontend_rows, 0) AS frontend_rows,
                    f.first_ts,
                    f.last_ts,
                    f.latest_frontend_price,
                    f.latest_frontend_at,
                    c.market_title,
                    c.condition_id,
                    c.end_date
                FROM candidates c
                LEFT JOIN LATERAL (
                    SELECT
                        count(*) AS block_rows,
                        min(block_number) AS first_block,
                        max(block_number) AS last_block,
                        (array_agg(COALESCE(yes_probability_close, close_price) ORDER BY block_number DESC))[1] AS latest_block_price,
                        max(built_at) AS latest_block_at
                    FROM quant.market_token_block_close b
                    WHERE b.market_slug = c.market_slug
                      AND (%s::text IS NULL OR b.token_side = %s::text)
                ) b ON TRUE
                LEFT JOIN LATERAL (
                    SELECT
                        count(*) AS frontend_rows,
                        min(timestamp) AS first_ts,
                        max(timestamp) AS last_ts,
                        (array_agg(price ORDER BY timestamp DESC))[1] AS latest_frontend_price,
                        max(fetched_at) AS latest_frontend_at
                    FROM quant.market_token_frontend_price_1m f
                    WHERE f.market_slug = c.market_slug
                      AND (%s::text IS NULL OR f.token_side = %s::text)
                ) f ON TRUE
                WHERE COALESCE(b.block_rows, 0) > 0 OR COALESCE(f.frontend_rows, 0) > 0
                ORDER BY c.search_rank ASC,
                         (COALESCE(b.block_rows, 0) + COALESCE(f.frontend_rows, 0)) DESC,
                         c.market_slug ASC
                LIMIT %s
                """,
                [
                    search_text,
                    slug_prefix_text,
                    prefix_text,
                    slug_token_text,
                    search_text,
                    prefix_text,
                    title_word_text,
                    text,
                    text,
                    token_side.upper() if token_side else None,
                    token_side.upper() if token_side else None,
                    token_side.upper() if token_side else None,
                    token_side.upper() if token_side else None,
                    token_side.upper() if token_side else None,
                    int(limit),
                ],
            )
            return [dict(row) for row in cur.fetchall()]

    filters: list[str] = []
    if search_text:
        filters.append("(lower(market_slug) LIKE %s OR lower(market_title) LIKE %s)")
        text = f"%{search_text}%"
        params.extend([text, text])
    if token_side:
        filters.append("token_side = %s")
        params.append(token_side.upper())
    where_sql = "WHERE " + " AND ".join(filters) if filters else ""
    params.append(int(limit))

    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH titled AS (
                SELECT
                    p.market_id,
                    p.market_slug,
                    COALESCE(md.token_side, 'YES') AS token_side,
                    COALESCE(p.block_rows_written, 0) AS block_rows,
                    p.first_orderfilled_block AS first_block,
                    COALESCE(p.max_block_complete, p.last_orderfilled_block) AS last_block,
                    NULL::numeric AS latest_block_price,
                    p.updated_at AS latest_block_at,
                    COALESCE(p.frontend_rows_written, 0) AS frontend_rows,
                    extract(epoch FROM p.min_frontend_complete_ts)::bigint AS first_ts,
                    extract(epoch FROM p.max_frontend_complete_ts)::bigint AS last_ts,
                    NULL::numeric AS latest_frontend_price,
                    p.updated_at AS latest_frontend_at,
                    max(md.market_title) AS market_title,
                    max(md.condition_id) AS condition_id,
                    max(md.end_date) AS end_date
                FROM quant.market_price_build_market_progress p
                LEFT JOIN quant.market_token_metadata md
                    ON md.market_id = p.market_id AND md.token_side = 'YES'
                WHERE p.market_slug IS NOT NULL
                  AND (COALESCE(p.block_rows_written, 0) > 0 OR COALESCE(p.frontend_rows_written, 0) > 0)
                GROUP BY
                    p.market_id, p.market_slug, md.token_side, p.block_rows_written,
                    p.first_orderfilled_block, p.max_block_complete, p.last_orderfilled_block,
                    p.frontend_rows_written, p.min_frontend_complete_ts, p.max_frontend_complete_ts,
                    p.updated_at
            )
            SELECT *
            FROM titled
            {where_sql}
            ORDER BY GREATEST(COALESCE(last_ts, 0), COALESCE(last_block, 0)) DESC,
                     (block_rows + frontend_rows) DESC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def get_frontend_prices(
    conn: Any,
    *,
    market_slug: str | None = None,
    token_side: str | None = None,
    token_id: str | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if market_slug:
        filters.append("market_slug = %s")
        params.append(market_slug)
    if token_side:
        filters.append("token_side = %s")
        params.append(token_side.upper())
    if token_id:
        filters.append("token_id = %s")
        params.append(token_id)
    if from_ts is not None:
        filters.append("timestamp >= %s")
        params.append(int(from_ts))
    if to_ts is not None:
        filters.append("timestamp <= %s")
        params.append(int(to_ts))
    where_sql = "WHERE " + " AND ".join(filters) if filters else ""
    params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT token_id, market_id, market_slug, token_side, ts_minute, timestamp, price
            FROM quant.market_token_frontend_price_1m
            {where_sql}
            ORDER BY ts_minute ASC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def get_block_close_prices(
    conn: Any,
    *,
    market_slug: str | None = None,
    token_side: str | None = None,
    token_id: str | None = None,
    from_block: int | None = None,
    to_block: int | None = None,
    limit: int = 10000,
) -> list[dict[str, Any]]:
    filters: list[str] = []
    params: list[Any] = []
    if market_slug:
        filters.append("market_slug = %s")
        params.append(market_slug)
    if token_side:
        filters.append("token_side = %s")
        params.append(token_side.upper())
    if token_id:
        filters.append("token_id = %s")
        params.append(token_id)
    if from_block is not None:
        filters.append("block_number >= %s")
        params.append(int(from_block))
    if to_block is not None:
        filters.append("block_number <= %s")
        params.append(int(to_block))
    where_sql = "WHERE " + " AND ".join(filters) if filters else ""
    params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                token_id, market_id, market_slug, token_side, block_number,
                close_price, yes_probability_close, vwap_price, yes_probability_vwap,
                close_raw_price, close_price_source, close_tx_hash, close_log_index,
                close_maker_amount, close_taker_amount, trade_count, raw_trade_count,
                internal_filtered_count, invalid_size_count, invalid_price_count,
                amount_ratio_count, raw_price_fallback_count, extreme_trade_count,
                anomaly_flags, volume
            FROM quant.market_token_block_close
            {where_sql}
            ORDER BY block_number ASC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def get_price_build_status(conn: Any, *, source: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    params: list[Any] = []
    where_sql = ""
    if source:
        where_sql = "WHERE source = %s"
        params.append(source)
    params.append(int(limit))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT *
            FROM quant.market_price_build_runs
            {where_sql}
            ORDER BY started_at DESC
            LIMIT %s
            """,
            params,
        )
        return [dict(row) for row in cur.fetchall()]


def get_backtest_run(conn: Any, *, run_id: int) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.*, p.entry_threshold, p.exit_threshold, p.stop_loss, p.take_profit,
                   p.max_holding_bars, p.initial_capital, p.position_size
            FROM quant.quant_backtest_runs r
            LEFT JOIN quant.quant_backtest_parameters p ON p.run_id = r.run_id
            WHERE r.run_id = %s
            """,
            (int(run_id),),
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_backtest_metrics(conn: Any, *, run_id: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM quant.quant_backtest_metrics
            WHERE run_id = %s
            ORDER BY sort_order ASC, metric_key ASC
            """,
            (int(run_id),),
        )
        return [dict(row) for row in cur.fetchall()]


def get_backtest_equity(conn: Any, *, run_id: int, limit: int = 25000) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM quant.quant_backtest_equity
            WHERE run_id = %s
            ORDER BY point_index ASC
            LIMIT %s
            """,
            (int(run_id), int(limit)),
        )
        return [dict(row) for row in cur.fetchall()]


def get_backtest_trades(conn: Any, *, run_id: int, limit: int = 10000) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM quant.quant_backtest_trades
            WHERE run_id = %s
            ORDER BY entry_x ASC, trade_id ASC
            LIMIT %s
            """,
            (int(run_id), int(limit)),
        )
        return [dict(row) for row in cur.fetchall()]
