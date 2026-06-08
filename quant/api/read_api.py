"""Read helpers for future /quant API endpoints."""

from __future__ import annotations

import re
from typing import Any


MATCHUP_RE = re.compile(r"\s+(?:vs\.?|v\.?)\s+", re.IGNORECASE)
NON_EVENT_TITLE_PREFIXES = {"spread", "total", "moneyline", "winner", "will"}


def _clean_label(value: str | None) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text.removesuffix("?").strip()


def _title_event_prefix(title: str | None) -> str | None:
    text = _clean_label(title)
    if ":" not in text:
        return None
    prefix = _clean_label(text.split(":", 1)[0])
    if not prefix:
        return None
    first_word = prefix.split(" ", 1)[0].lower()
    if first_word in NON_EVENT_TITLE_PREFIXES:
        return None
    return prefix


def _label_from_title_suffix(title: str | None) -> str | None:
    text = _clean_label(title)
    if ":" not in text:
        return None
    suffix = _clean_label(text.split(":", 1)[1])
    return suffix or None


def infer_outcome_label(market_title: str | None, token_side: str | None, *, event_scope: bool = False) -> str:
    """Return a display label for a token/outcome without changing stored prices."""

    side = str(token_side or "").upper()
    title = _clean_label(market_title)
    if event_scope:
        suffix = _label_from_title_suffix(title)
        if suffix:
            return suffix
    parts = [part.strip() for part in MATCHUP_RE.split(title, maxsplit=1) if part.strip()]
    if len(parts) == 2:
        return parts[0] if side == "YES" else parts[1]
    suffix = _label_from_title_suffix(title)
    if suffix:
        return suffix if side == "YES" else f"Not {suffix}"
    if title and side == "YES" and not title.lower().startswith("will "):
        return title
    return "Yes" if side == "YES" else "No"


def _market_payload(rows: list[dict[str, Any]], *, market_slug: str, source: str, scope: str, x_axis: str) -> dict[str, Any]:
    first = next((row for row in rows if row.get("market_slug") == market_slug), rows[0] if rows else {})
    return {
        "market_id": first.get("market_id"),
        "market_slug": first.get("market_slug") or market_slug,
        "market_title": first.get("market_title"),
        "condition_id": first.get("condition_id"),
        "end_date": first.get("end_date"),
        "source": source,
        "scope": scope,
        "x_axis": x_axis,
    }


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
        with conn.cursor() as cur:
            cur.execute(
                """
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
                        max(md.end_date) AS end_date,
                        CASE
                            WHEN lower(p.market_slug) = %s THEN 0
                            WHEN lower(p.market_slug) LIKE %s THEN 1
                            WHEN lower(p.market_slug) LIKE %s THEN 2
                            WHEN lower(p.market_slug) LIKE %s THEN 3
                            WHEN lower(max(md.market_title)) = %s THEN 4
                            WHEN lower(max(md.market_title)) LIKE %s THEN 5
                            ELSE 9
                        END AS search_rank
                    FROM quant.market_price_build_market_progress p
                    LEFT JOIN quant.market_token_metadata md
                        ON md.market_id = p.market_id AND md.token_side = COALESCE(%s, 'YES')
                    WHERE p.market_slug IS NOT NULL
                      AND (COALESCE(p.block_rows_written, 0) > 0 OR COALESCE(p.frontend_rows_written, 0) > 0)
                      AND (lower(p.market_slug) LIKE %s OR lower(md.market_title) LIKE %s)
                    GROUP BY
                        p.market_id, p.market_slug, md.token_side, p.block_rows_written,
                        p.first_orderfilled_block, p.max_block_complete, p.last_orderfilled_block,
                        p.frontend_rows_written, p.min_frontend_complete_ts, p.max_frontend_complete_ts,
                        p.updated_at
                )
                SELECT *
                FROM titled
                ORDER BY search_rank ASC,
                         (block_rows + frontend_rows) DESC,
                         market_slug ASC
                LIMIT %s
                """,
                [
                    search_text,
                    slug_prefix_text,
                    prefix_text,
                    slug_token_text,
                    search_text,
                    prefix_text,
                    token_side.upper() if token_side else None,
                    text,
                    text,
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


def _fetch_market_tokens(conn: Any, *, market_slug: str, scope: str, max_outcomes: int) -> tuple[list[dict[str, Any]], str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                market_id, market_slug, market_title, condition_id, end_date,
                token_id, token_side, outcome_index
            FROM quant.market_token_metadata
            WHERE market_slug = %s
            ORDER BY market_id, outcome_index NULLS LAST, token_side, token_id
            """,
            (market_slug,),
        )
        base_rows = [dict(row) for row in cur.fetchall()]
        if not base_rows:
            return [], "market"
        event_prefix = _title_event_prefix(base_rows[0].get("market_title"))
        effective_scope = "event" if scope == "event" or (scope == "auto" and event_prefix) else "market"
        if effective_scope != "event" or not event_prefix:
            return base_rows[: int(max_outcomes)], "market"
        cur.execute(
            """
            WITH markets AS (
                SELECT DISTINCT market_id, market_slug, market_title, condition_id, end_date
                FROM quant.market_token_metadata
                WHERE market_title ILIKE %s
                ORDER BY market_title ASC, market_id ASC
                LIMIT %s
            )
            SELECT
                m.market_id, m.market_slug, m.market_title, m.condition_id, m.end_date,
                md.token_id, md.token_side, md.outcome_index
            FROM markets m
            JOIN quant.market_token_metadata md
                ON md.market_id = m.market_id AND md.token_side = 'YES'
            ORDER BY m.market_title ASC, md.outcome_index NULLS LAST, md.token_id
            """,
            (f"{event_prefix}:%", int(max_outcomes)),
        )
        return [dict(row) for row in cur.fetchall()], "event"


def _complement_side(token_side: str | None) -> str:
    return "NO" if str(token_side or "").upper() == "YES" else "YES"


def get_market_price_series(
    conn: Any,
    *,
    market_slug: str,
    price_source: str,
    scope: str = "auto",
    token_side: str | None = None,
    from_ts: int | None = None,
    to_ts: int | None = None,
    from_block: int | None = None,
    to_block: int | None = None,
    limit: int = 2500,
    max_outcomes: int = 24,
) -> dict[str, Any]:
    """Return semantic market/event series grouped by outcome token.

    Raw price tables stay token-granular. This read model packages those token
    rows into user-facing outcomes, so sports matchups and selection markets can
    render multiple lines without forcing the backtest engine to guess meaning.
    """

    source = "orderfilled_block_close" if price_source == "orderfilled_block_close" else "frontend"
    requested_scope = scope if scope in {"auto", "market", "event"} else "auto"
    tokens, effective_scope = _fetch_market_tokens(
        conn,
        market_slug=market_slug,
        scope=requested_scope,
        max_outcomes=max_outcomes,
    )
    if token_side and effective_scope == "market":
        wanted = token_side.upper()
        tokens = [token for token in tokens if str(token.get("token_side") or "").upper() == wanted]

    outcomes: list[dict[str, Any]] = []
    market_ids = sorted({int(token["market_id"]) for token in tokens if token.get("market_id") is not None})
    tokens_by_market_side: dict[tuple[int, str], dict[str, Any]] = {}
    with conn.cursor() as cur:
        if market_ids:
            cur.execute(
                """
                SELECT
                    market_id, market_slug, market_title, condition_id, end_date,
                    token_id, token_side, outcome_index
                FROM quant.market_token_metadata
                WHERE market_id = ANY(%s::bigint[])
                """,
                (market_ids,),
            )
            for row in cur.fetchall():
                item = dict(row)
                tokens_by_market_side[(int(item["market_id"]), str(item.get("token_side") or "").upper())] = item

        points_cache: dict[str, list[dict[str, Any]]] = {}

        def fetch_points(token_id: str | None) -> list[dict[str, Any]]:
            if not token_id:
                return []
            cache_key = str(token_id)
            if cache_key in points_cache:
                return points_cache[cache_key]
            params: list[Any] = [cache_key]
            if source == "frontend":
                filters = ["token_id = %s"]
                if from_ts is not None:
                    filters.append("timestamp >= %s")
                    params.append(int(from_ts))
                if to_ts is not None:
                    filters.append("timestamp <= %s")
                    params.append(int(to_ts))
                params.append(int(limit))
                cur.execute(
                    f"""
                    WITH limited AS (
                        SELECT
                            token_id, market_id, market_slug, token_side,
                            ts_minute, timestamp, price, 0::numeric AS volume
                        FROM quant.market_token_frontend_price_1m
                        WHERE {" AND ".join(filters)}
                        ORDER BY ts_minute DESC
                        LIMIT %s
                    )
                    SELECT *
                    FROM limited
                    ORDER BY ts_minute ASC
                    """,
                    params,
                )
                rows = [
                    {
                        "x": row["timestamp"],
                        "timestamp": row["timestamp"],
                        "price": row["price"],
                        "volume": row["volume"],
                    }
                    for row in cur.fetchall()
                ]
            else:
                filters = ["token_id = %s"]
                if from_block is not None:
                    filters.append("block_number >= %s")
                    params.append(int(from_block))
                if to_block is not None:
                    filters.append("block_number <= %s")
                    params.append(int(to_block))
                params.append(int(limit))
                cur.execute(
                    f"""
                    WITH limited AS (
                        SELECT
                            token_id, market_id, market_slug, token_side, block_number,
                            close_price, yes_probability_close, vwap_price, yes_probability_vwap,
                            volume, trade_count
                        FROM quant.market_token_block_close
                        WHERE {" AND ".join(filters)}
                        ORDER BY block_number DESC
                        LIMIT %s
                    )
                    SELECT *
                    FROM limited
                    ORDER BY block_number ASC
                    """,
                    params,
                )
                rows = [
                    {
                        "x": row["block_number"],
                        "block_number": row["block_number"],
                        "price": row["close_price"],
                        "yes_probability_close": row["yes_probability_close"],
                        "vwap_price": row["vwap_price"],
                        "yes_probability_vwap": row["yes_probability_vwap"],
                        "volume": row["volume"],
                        "trade_count": row["trade_count"],
                    }
                    for row in cur.fetchall()
                ]
            points_cache[cache_key] = rows
            return rows

        for token in tokens:
            points = fetch_points(str(token.get("token_id") or ""))
            complement_token = tokens_by_market_side.get(
                (int(token["market_id"]), _complement_side(str(token.get("token_side") or "")))
            )
            complement_points = fetch_points(str(complement_token.get("token_id") or "")) if complement_token else []
            label = infer_outcome_label(
                token.get("market_title"),
                token.get("token_side"),
                event_scope=effective_scope == "event",
            )
            outcomes.append(
                {
                    "market_id": token.get("market_id"),
                    "market_slug": token.get("market_slug"),
                    "market_title": token.get("market_title"),
                    "condition_id": token.get("condition_id"),
                    "end_date": token.get("end_date"),
                    "token_id": token.get("token_id"),
                    "token_side": token.get("token_side"),
                    "outcome_index": token.get("outcome_index"),
                    "outcome_label": label,
                    "buy_yes_token_id": token.get("token_id"),
                    "buy_yes_token_side": token.get("token_side"),
                    "buy_yes_label": f"{label} Yes",
                    "buy_yes_price": points[-1]["price"] if points else None,
                    "buy_no_token_id": complement_token.get("token_id") if complement_token else None,
                    "buy_no_token_side": complement_token.get("token_side") if complement_token else None,
                    "buy_no_label": f"{label} No",
                    "buy_no_price": complement_points[-1]["price"] if complement_points else None,
                    "rows": len(points),
                    "first_x": points[0]["x"] if points else None,
                    "last_x": points[-1]["x"] if points else None,
                    "latest_price": points[-1]["price"] if points else None,
                    "points": points,
                    "complement_rows": len(complement_points),
                    "complement_first_x": complement_points[0]["x"] if complement_points else None,
                    "complement_last_x": complement_points[-1]["x"] if complement_points else None,
                    "complement_latest_price": complement_points[-1]["price"] if complement_points else None,
                    "complement_points": complement_points,
                }
            )

    return {
        "market": _market_payload(
            tokens,
            market_slug=market_slug,
            source=source,
            scope=effective_scope,
            x_axis="block_number" if source == "orderfilled_block_close" else "timestamp",
        ),
        "outcomes": outcomes,
        "count": len(outcomes),
    }


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
