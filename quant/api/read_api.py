"""Read helpers for future /quant API endpoints."""

from __future__ import annotations

from typing import Any


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
