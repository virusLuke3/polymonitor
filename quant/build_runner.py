"""Batch runner primitives for quant price builds.

The runner can be used for one-shot historical jobs or as a daemon on the local
collector. It builds the two production price sources independently from the
backtest API:

* frontend: time-based Polymarket prices-history rows.
* orderfilled_block_close: block-number based trade close rows.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .block_close_algorithm import orderfilled_block_close_sql
from .block_close_backfill import backfill_block_close_prices
from .db import ClickHouseClient, PostgresSettings, postgres_connection
from .eligibility import fetch_orderfilled_trade_stats, refresh_eligibility
from .frontend_backfill import insert_frontend_points, backfill_frontend_prices
from .frontend_client import FrontendPriceClient
from .metadata import refresh_market_token_metadata
from .schema import create_schema


SEPTEMBER_2025_TS = 1756684800
FRONTEND_SOURCE = "frontend"
BLOCK_CLOSE_SOURCE = "orderfilled_block_close"


def utc_now_ts() -> int:
    return int(datetime.now(tz=timezone.utc).timestamp())


def ts_to_utc(timestamp: int) -> datetime:
    return datetime.fromtimestamp(int(timestamp), tz=timezone.utc)


def maybe_datetime_to_ts(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    try:
        return int(value)
    except Exception:
        return None


def start_run(conn: Any, *, source: str, mode: str, meta: dict[str, Any]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO quant.market_price_build_runs (source, mode, status, meta)
            VALUES (%s, %s, 'running', %s::jsonb)
            RETURNING run_id
            """,
            (source, mode, json.dumps(meta, sort_keys=True)),
        )
        row = cur.fetchone()
        return int(row["run_id"])


def finish_run(conn: Any, *, run_id: int, status: str, rows_written: int, markets_complete: int, error_count: int = 0, last_error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quant.market_price_build_runs
            SET status = %s,
                finished_at = now(),
                rows_written = %s,
                markets_complete = %s,
                error_count = %s,
                last_error = %s
            WHERE run_id = %s
            """,
            (status, rows_written, markets_complete, error_count, last_error, run_id),
        )


def shard_sql(alias: str, *, shard_count: int) -> str:
    if int(shard_count) <= 1:
        return "TRUE"
    return f"mod(abs(hashtext({alias}.token_id)), %s) = %s"


def shard_params(*, shard_count: int, shard_index: int) -> tuple[int, int] | tuple:
    if int(shard_count) <= 1:
        return ()
    return (int(shard_count), int(shard_index))


def fetch_frontend_build_candidates(
    conn: Any,
    *,
    since_ts: int,
    limit: int,
    min_orderfilled_trades: int,
    include_active_without_trades: bool,
    targets_only: bool,
    shard_index: int = 0,
    shard_count: int = 1,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                m.token_id, m.market_id, m.market_slug, m.token_side,
                m.active, m.closed, m.end_date, m.created_at,
                e.eligible, e.orderfilled_trade_count,
                t.priority AS target_priority, t.reason AS target_reason,
                t.requested_from_ts, t.requested_to_ts,
                s.last_complete_ts, s.attempt_count, s.last_error
            FROM quant.market_token_metadata m
            LEFT JOIN quant.market_price_eligibility e ON e.token_id = m.token_id
            LEFT JOIN quant.market_price_build_targets t
                ON t.source = %s AND t.token_id = m.token_id AND t.status = 'active'
            LEFT JOIN quant.market_price_build_market_state s
                ON s.source = %s AND s.token_id = m.token_id
            WHERE
                COALESCE(e.is_archived, m.archived, FALSE) = FALSE
                AND COALESCE(e.is_deprecated, m.deprecated, FALSE) = FALSE
                AND COALESCE(e.is_duplicate_market, FALSE) = FALSE
                AND {shard_sql("m", shard_count=shard_count)}
                AND (
                    m.created_at >= to_timestamp(%s)
                    OR m.end_date >= to_timestamp(%s)
                )
                AND (
                    t.token_id IS NOT NULL
                    OR (
                        %s = FALSE
                        AND COALESCE(e.eligible, FALSE) = TRUE
                        AND COALESCE(e.orderfilled_trade_count, 0) >= %s
                    )
                    OR (
                        %s = TRUE
                        AND %s = FALSE
                        AND m.active = TRUE
                        AND m.closed = FALSE
                    )
                )
                AND (
                    t.requested_to_ts IS NULL
                    OR s.last_complete_ts IS NULL
                    OR s.last_complete_ts < t.requested_to_ts
                )
            ORDER BY
                CASE WHEN t.token_id IS NOT NULL THEN 0 ELSE 1 END,
                t.priority DESC NULLS LAST,
                s.last_complete_ts ASC NULLS FIRST,
                m.active DESC,
                e.orderfilled_trade_count DESC NULLS LAST,
                m.market_id ASC,
                m.outcome_index ASC,
                m.token_id ASC
            LIMIT %s
            """,
            (
                FRONTEND_SOURCE,
                FRONTEND_SOURCE,
                *shard_params(shard_count=shard_count, shard_index=shard_index),
                int(since_ts),
                int(since_ts),
                bool(targets_only),
                int(min_orderfilled_trades),
                bool(include_active_without_trades),
                bool(targets_only),
                int(limit),
            ),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_block_close_build_candidates(
    conn: Any,
    *,
    since_ts: int,
    limit: int,
    min_orderfilled_trades: int,
    shard_index: int = 0,
    shard_count: int = 1,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                m.token_id, m.token_id_hex, m.market_id, m.market_slug, m.token_side,
                m.active, m.closed, m.end_date, m.created_at,
                e.first_orderfilled_block, e.last_orderfilled_block, e.orderfilled_trade_count,
                t.priority AS target_priority, t.reason AS target_reason,
                t.requested_from_block, t.requested_to_block,
                s.last_complete_block, s.attempt_count, s.last_error
            FROM quant.market_token_metadata m
            JOIN quant.market_price_eligibility e ON e.token_id = m.token_id
            LEFT JOIN quant.market_price_build_targets t
                ON t.source = %s AND t.token_id = m.token_id AND t.status = 'active'
            LEFT JOIN quant.market_price_build_market_state s
                ON s.source = %s AND s.token_id = m.token_id
            WHERE
                e.eligible = TRUE
                AND (
                    t.token_id IS NOT NULL
                    OR e.orderfilled_trade_count >= %s
                )
                AND m.token_id_hex IS NOT NULL
                AND e.first_orderfilled_block IS NOT NULL
                AND e.last_orderfilled_block IS NOT NULL
                AND {shard_sql("m", shard_count=shard_count)}
                AND (
                    m.created_at >= to_timestamp(%s)
                    OR m.end_date >= to_timestamp(%s)
                )
                AND (
                    (
                        t.token_id IS NOT NULL
                        AND t.requested_to_block IS NOT NULL
                        AND (
                            s.last_complete_block IS NULL
                            OR s.last_complete_block < t.requested_to_block
                        )
                    )
                    OR (
                        (t.token_id IS NULL OR t.requested_to_block IS NULL)
                        AND (
                            s.last_complete_block IS NULL
                            OR s.last_complete_block < e.last_orderfilled_block
                        )
                    )
                )
            ORDER BY
                CASE WHEN t.token_id IS NOT NULL THEN 0 ELSE 1 END,
                t.priority DESC NULLS LAST,
                s.last_complete_block ASC NULLS FIRST,
                m.active DESC,
                e.orderfilled_trade_count DESC NULLS LAST,
                m.market_id ASC,
                m.outcome_index ASC,
                m.token_id ASC
            LIMIT %s
            """,
            (
                BLOCK_CLOSE_SOURCE,
                BLOCK_CLOSE_SOURCE,
                int(min_orderfilled_trades),
                *shard_params(shard_count=shard_count, shard_index=shard_index),
                int(since_ts),
                int(since_ts),
                int(limit),
            ),
        )
        return [dict(row) for row in cur.fetchall()]


def fetch_eligibility_refresh_candidates(
    conn: Any,
    *,
    since_ts: int,
    limit: int,
    shard_index: int = 0,
    shard_count: int = 1,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                m.token_id, m.token_id_hex, m.market_id, m.market_slug, m.token_side,
                m.archived, m.deprecated, m.duplicate_group_key,
                row_number() OVER (
                    PARTITION BY m.duplicate_group_key, m.token_side
                    ORDER BY m.created_at NULLS LAST, m.market_id ASC
                ) AS duplicate_rank
            FROM quant.market_token_metadata m
            LEFT JOIN quant.market_price_eligibility e ON e.token_id = m.token_id
            WHERE
                m.token_id_hex IS NOT NULL
                AND {shard_sql("m", shard_count=shard_count)}
                AND (
                    m.created_at >= to_timestamp(%s)
                    OR m.end_date >= to_timestamp(%s)
                )
            ORDER BY e.checked_at ASC NULLS FIRST, m.market_id ASC, m.token_id ASC
            LIMIT %s
            """,
            (
                *shard_params(shard_count=shard_count, shard_index=shard_index),
                int(since_ts),
                int(since_ts),
                int(limit),
            ),
        )
        return [dict(row) for row in cur.fetchall()]


def refresh_since_eligibility(
    conn: Any,
    ch: ClickHouseClient,
    *,
    since_ts: int,
    batch_size: int = 1000,
    shard_index: int = 0,
    shard_count: int = 1,
) -> int:
    rows = fetch_eligibility_refresh_candidates(conn, since_ts=since_ts, limit=batch_size, shard_index=shard_index, shard_count=shard_count)
    if not rows:
        return 0
    stats = fetch_orderfilled_trade_stats(ch, [str(row["token_id_hex"]) for row in rows if row.get("token_id_hex")])
    upserts = []
    for row in rows:
        token_id = str(row["token_id"])
        token_id_hex = str(row.get("token_id_hex") or "").lower()
        token_stats = stats.get(token_id_hex)
        trade_count = token_stats.trade_count if token_stats else 0
        archived = bool(row.get("archived"))
        deprecated = bool(row.get("deprecated"))
        duplicate = int(row.get("duplicate_rank") or 1) > 1
        eligible = bool(trade_count > 0 and not archived and not deprecated and not duplicate)
        reasons = []
        if trade_count <= 0:
            reasons.append("no_orderfilled_trades")
        if archived:
            reasons.append("archived")
        if deprecated:
            reasons.append("deprecated")
        if duplicate:
            reasons.append("duplicate_market")
        upserts.append(
            (
                token_id,
                int(row["market_id"]),
                row.get("market_slug"),
                row.get("token_side"),
                eligible,
                trade_count > 0,
                archived,
                deprecated,
                duplicate,
                ",".join(reasons) if reasons else None,
                trade_count,
                token_stats.first_block if token_stats else None,
                token_stats.last_block if token_stats else None,
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO quant.market_price_eligibility (
                token_id, market_id, market_slug, token_side, eligible,
                has_orderfilled_trades, is_archived, is_deprecated, is_duplicate_market,
                skip_reason, orderfilled_trade_count, first_orderfilled_block, last_orderfilled_block,
                checked_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                market_slug = EXCLUDED.market_slug,
                token_side = EXCLUDED.token_side,
                eligible = EXCLUDED.eligible,
                has_orderfilled_trades = EXCLUDED.has_orderfilled_trades,
                is_archived = EXCLUDED.is_archived,
                is_deprecated = EXCLUDED.is_deprecated,
                is_duplicate_market = EXCLUDED.is_duplicate_market,
                skip_reason = EXCLUDED.skip_reason,
                orderfilled_trade_count = EXCLUDED.orderfilled_trade_count,
                first_orderfilled_block = EXCLUDED.first_orderfilled_block,
                last_orderfilled_block = EXCLUDED.last_orderfilled_block,
                checked_at = now()
            """,
            upserts,
        )
    return len(upserts)

def update_frontend_state(
    conn: Any,
    *,
    token: dict[str, Any],
    status: str,
    last_complete_ts: int | None,
    rows_written: int,
    last_error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO quant.market_price_build_market_state (
                source, token_id, market_id, market_slug, token_side,
                status, last_complete_ts, attempt_count, last_error, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, to_timestamp(%s), 1, %s, now())
            ON CONFLICT (source, token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                market_slug = EXCLUDED.market_slug,
                token_side = EXCLUDED.token_side,
                status = EXCLUDED.status,
                last_complete_ts = GREATEST(
                    COALESCE(quant.market_price_build_market_state.last_complete_ts, to_timestamp(0)),
                    EXCLUDED.last_complete_ts
                ),
                attempt_count = quant.market_price_build_market_state.attempt_count + 1,
                last_error = EXCLUDED.last_error,
                updated_at = now()
            """,
            (
                FRONTEND_SOURCE,
                token["token_id"],
                token["market_id"],
                token.get("market_slug"),
                token["token_side"],
                status,
                int(last_complete_ts or SEPTEMBER_2025_TS),
                last_error[:4000] if last_error else None,
            ),
        )


def update_block_state(
    conn: Any,
    *,
    token: dict[str, Any],
    status: str,
    last_complete_block: int | None,
    last_error: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO quant.market_price_build_market_state (
                source, token_id, market_id, market_slug, token_side,
                status, last_complete_block, attempt_count, last_error, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, 1, %s, now())
            ON CONFLICT (source, token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                market_slug = EXCLUDED.market_slug,
                token_side = EXCLUDED.token_side,
                status = EXCLUDED.status,
                last_complete_block = GREATEST(
                    COALESCE(quant.market_price_build_market_state.last_complete_block, 0),
                    EXCLUDED.last_complete_block
                ),
                attempt_count = quant.market_price_build_market_state.attempt_count + 1,
                last_error = EXCLUDED.last_error,
                updated_at = now()
            """,
            (
                BLOCK_CLOSE_SOURCE,
                token["token_id"],
                token["market_id"],
                token.get("market_slug"),
                token["token_side"],
                status,
                int(last_complete_block or token.get("first_orderfilled_block") or 0),
                last_error[:4000] if last_error else None,
            ),
        )


def insert_single_token_block_close_rows(conn: Any, token: dict[str, Any], rows: list[dict[str, Any]]) -> int:
    values = []
    for row in rows:
        close_price = _decimal_or_none(row.get("close_price"))
        vwap_price = _decimal_or_none(row.get("vwap_price"))
        close_raw_price = _decimal_or_none(row.get("close_raw_price"))
        close_maker_amount = _decimal_or_none(row.get("close_maker_amount"))
        close_taker_amount = _decimal_or_none(row.get("close_taker_amount"))
        values.append(
            (
                str(token["token_id"]),
                int(token["market_id"]),
                token.get("market_slug"),
                token["token_side"],
                int(row["block_number"]),
                close_price,
                _yes_probability(str(token["token_side"]), close_price),
                vwap_price,
                _yes_probability(str(token["token_side"]), vwap_price),
                close_raw_price,
                row.get("close_price_source") or "unknown",
                row.get("close_tx_hash"),
                int(row["close_log_index"]) if row.get("close_log_index") is not None else None,
                close_maker_amount,
                close_taker_amount,
                int(row.get("clean_trade_count") or 0),
                int(row.get("raw_trade_count") or 0),
                int(row.get("internal_filtered_count") or 0),
                int(row.get("invalid_size_count") or 0),
                int(row.get("invalid_price_count") or 0),
                int(row.get("amount_ratio_count") or 0),
                int(row.get("raw_price_fallback_count") or 0),
                int(row.get("extreme_trade_count") or 0),
                json.dumps(_anomaly_flags(row), sort_keys=True),
                _decimal_or_none(row.get("volume")) or Decimal("0"),
            )
        )
    if not values:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO quant.market_token_block_close (
                token_id, market_id, market_slug, token_side, block_number,
                close_price, yes_probability_close, vwap_price, yes_probability_vwap,
                close_raw_price, close_price_source, close_tx_hash, close_log_index,
                close_maker_amount, close_taker_amount, trade_count, raw_trade_count,
                internal_filtered_count, invalid_size_count, invalid_price_count,
                amount_ratio_count, raw_price_fallback_count, extreme_trade_count,
                anomaly_flags, volume
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (token_id, block_number) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                market_slug = EXCLUDED.market_slug,
                token_side = EXCLUDED.token_side,
                close_price = EXCLUDED.close_price,
                yes_probability_close = EXCLUDED.yes_probability_close,
                vwap_price = EXCLUDED.vwap_price,
                yes_probability_vwap = EXCLUDED.yes_probability_vwap,
                close_raw_price = EXCLUDED.close_raw_price,
                close_price_source = EXCLUDED.close_price_source,
                close_tx_hash = EXCLUDED.close_tx_hash,
                close_log_index = EXCLUDED.close_log_index,
                close_maker_amount = EXCLUDED.close_maker_amount,
                close_taker_amount = EXCLUDED.close_taker_amount,
                trade_count = EXCLUDED.trade_count,
                raw_trade_count = EXCLUDED.raw_trade_count,
                internal_filtered_count = EXCLUDED.internal_filtered_count,
                invalid_size_count = EXCLUDED.invalid_size_count,
                invalid_price_count = EXCLUDED.invalid_price_count,
                amount_ratio_count = EXCLUDED.amount_ratio_count,
                raw_price_fallback_count = EXCLUDED.raw_price_fallback_count,
                extreme_trade_count = EXCLUDED.extreme_trade_count,
                anomaly_flags = EXCLUDED.anomaly_flags,
                volume = EXCLUDED.volume,
                source = 'clean_orderfilled_fact',
                built_at = now()
            """,
            values,
        )
    return len(values)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.upper() in {"NULL", "\\N", "NONE", "NAN"}:
        return None
    return Decimal(text)


def _yes_probability(token_side: str | None, token_price: Decimal | None) -> Decimal | None:
    if token_price is None:
        return None
    side = str(token_side or "").upper()
    if side == "YES":
        return token_price
    if side == "NO":
        return Decimal("1") - token_price
    return None


def _anomaly_flags(row: dict[str, Any]) -> list[str]:
    flags: list[str] = []
    if int(row.get("internal_filtered_count") or 0) > 0:
        flags.append("internal_counterparty_filtered")
    if int(row.get("invalid_size_count") or 0) > 0:
        flags.append("invalid_size_filtered")
    if int(row.get("invalid_price_count") or 0) > 0:
        flags.append("invalid_price_filtered")
    if int(row.get("extreme_trade_count") or 0) > 0:
        flags.append("extreme_price_trade_present")
    if int(row.get("raw_price_fallback_count") or 0) > 0:
        flags.append("raw_price_fallback_used")
    return flags


def run_frontend_incremental(
    conn: Any,
    client: FrontendPriceClient,
    *,
    since_ts: int,
    end_ts: int,
    token_limit: int,
    window_seconds: int,
    overlap_seconds: int,
    fidelity_minutes: int,
    min_orderfilled_trades: int,
    include_active_without_trades: bool,
    targets_only: bool,
    shard_index: int,
    shard_count: int,
) -> dict[str, int]:
    tokens = fetch_frontend_build_candidates(
        conn,
        since_ts=since_ts,
        limit=token_limit,
        min_orderfilled_trades=min_orderfilled_trades,
        include_active_without_trades=include_active_without_trades,
        targets_only=targets_only,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    rows_written = 0
    failures = 0
    touched = 0
    for token in tokens:
        last_ts = maybe_datetime_to_ts(token.get("last_complete_ts"))
        requested_from_ts = maybe_datetime_to_ts(token.get("requested_from_ts"))
        requested_to_ts = maybe_datetime_to_ts(token.get("requested_to_ts"))
        anchor_ts = last_ts or requested_from_ts or since_ts
        if requested_from_ts and (last_ts is None or last_ts < requested_from_ts):
            anchor_ts = requested_from_ts
        start_ts = max(int(since_ts), int(anchor_ts - overlap_seconds))
        token_end_ts = min(int(end_ts), start_ts + int(window_seconds) - 1)
        if requested_to_ts:
            token_end_ts = min(token_end_ts, requested_to_ts)
        end_date_ts = maybe_datetime_to_ts(token.get("end_date"))
        if end_date_ts and bool(token.get("closed")):
            token_end_ts = min(token_end_ts, end_date_ts + 86400)
        if token_end_ts <= start_ts:
            continue
        touched += 1
        try:
            points, token_failures = client.fetch_segmented_prices_history(
                str(token["token_id"]),
                start_ts=start_ts,
                end_ts=token_end_ts,
                fidelity_minutes=fidelity_minutes,
            )
            written = insert_frontend_points(
                conn,
                market_id=int(token["market_id"]),
                market_slug=token.get("market_slug"),
                token_id=str(token["token_id"]),
                token_side=str(token["token_side"]),
                points=points,
                fidelity_minutes=fidelity_minutes,
            )
            rows_written += written
            failures += len(token_failures)
            update_frontend_state(
                conn,
                token=token,
                status="error" if token_failures else "complete",
                last_complete_ts=token_end_ts,
                rows_written=written,
                last_error="; ".join(f.error for f in token_failures) if token_failures else None,
            )
            print(
                json.dumps(
                    {
                        "source": FRONTEND_SOURCE,
                        "token_id": token["token_id"],
                        "market_slug": token.get("market_slug"),
                        "start_ts": start_ts,
                        "end_ts": token_end_ts,
                        "rows_written": written,
                        "failures": len(token_failures),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            update_frontend_state(conn, token=token, status="error", last_complete_ts=last_ts or since_ts, rows_written=0, last_error=repr(exc))
    return {"tokens": touched, "rows_written": rows_written, "failures": failures}


def run_block_close_incremental(
    conn: Any,
    ch: ClickHouseClient,
    *,
    since_ts: int,
    token_limit: int,
    block_window: int,
    block_overlap: int,
    min_orderfilled_trades: int,
    shard_index: int,
    shard_count: int,
) -> dict[str, int]:
    tokens = fetch_block_close_build_candidates(
        conn,
        since_ts=since_ts,
        limit=token_limit,
        min_orderfilled_trades=min_orderfilled_trades,
        shard_index=shard_index,
        shard_count=shard_count,
    )
    rows_written = 0
    failures = 0
    touched = 0
    table = ch.settings.orderfilled_table
    for token in tokens:
        first_block = int(token.get("first_orderfilled_block") or 0)
        last_block = int(token.get("last_orderfilled_block") or 0)
        last_complete = int(token.get("last_complete_block") or 0)
        requested_from_block = int(token.get("requested_from_block") or 0)
        requested_to_block = int(token.get("requested_to_block") or 0)
        if first_block <= 0 or last_block <= 0:
            continue
        anchor_block = last_complete or requested_from_block or first_block
        if requested_from_block and (not last_complete or last_complete < requested_from_block):
            anchor_block = requested_from_block
        start_block = max(first_block, anchor_block - int(block_overlap) + 1 if last_complete else anchor_block)
        to_block = min(last_block, start_block + int(block_window) - 1)
        if requested_to_block:
            to_block = min(to_block, requested_to_block)
        if to_block < start_block:
            continue
        touched += 1
        try:
            sql = orderfilled_block_close_sql(
                table=table,
                from_block=start_block,
                to_block=to_block,
                token_ids=[str(token["token_id_hex"]).lower()],
            )
            rows = ch.query_json_rows(sql)
            written = insert_single_token_block_close_rows(conn, token, rows)
            rows_written += written
            update_block_state(conn, token=token, status="complete", last_complete_block=to_block)
            print(
                json.dumps(
                    {
                        "source": BLOCK_CLOSE_SOURCE,
                        "token_id": token["token_id"],
                        "market_slug": token.get("market_slug"),
                        "from_block": start_block,
                        "to_block": to_block,
                        "rows_written": written,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            update_block_state(conn, token=token, status="error", last_complete_block=last_complete or first_block, last_error=repr(exc))
    return {"tokens": touched, "rows_written": rows_written, "failures": failures}


def run_daemon(args: argparse.Namespace) -> None:
    metadata_next = 0.0
    eligibility_next = 0.0
    while True:
        cycle_started = time.time()
        with postgres_connection(PostgresSettings()) as conn:
            create_schema(conn)
            if not args.skip_maintenance and cycle_started >= metadata_next:
                count = refresh_market_token_metadata(conn, since_ts=args.since_ts)
                metadata_next = cycle_started + args.metadata_interval_seconds
                print(json.dumps({"event": "metadata_refreshed", "count": count}, sort_keys=True), flush=True)
            if not args.skip_maintenance and cycle_started >= eligibility_next:
                count = refresh_since_eligibility(
                    conn,
                    ClickHouseClient(),
                    since_ts=args.since_ts,
                    shard_index=args.shard_index,
                    shard_count=args.shard_count,
                )
                eligibility_next = cycle_started + args.eligibility_interval_seconds
                print(json.dumps({"event": "eligibility_refreshed", "count": count}, sort_keys=True), flush=True)

            if args.source_mode in {"both", FRONTEND_SOURCE}:
                end_ts = utc_now_ts() - int(args.frontend_lag_seconds)
                frontend_run_id = start_run(
                    conn,
                    source=FRONTEND_SOURCE,
                    mode="daemon",
                    meta={
                        "since_ts": args.since_ts,
                        "end_ts": end_ts,
                        "token_limit": args.frontend_token_limit,
                        "min_orderfilled_trades": args.frontend_min_orderfilled_trades,
                        "include_active_without_trades": args.frontend_include_active_without_trades,
                        "targets_only": args.frontend_targets_only,
                        "shard_index": args.shard_index,
                        "shard_count": args.shard_count,
                    },
                )
                frontend_result = run_frontend_incremental(
                    conn,
                    FrontendPriceClient(),
                    since_ts=args.since_ts,
                    end_ts=end_ts,
                    token_limit=args.frontend_token_limit,
                    window_seconds=args.frontend_window_seconds,
                    overlap_seconds=args.frontend_overlap_seconds,
                    fidelity_minutes=args.fidelity_minutes,
                    min_orderfilled_trades=args.frontend_min_orderfilled_trades,
                    include_active_without_trades=args.frontend_include_active_without_trades,
                    targets_only=args.frontend_targets_only,
                    shard_index=args.shard_index,
                    shard_count=args.shard_count,
                )
                finish_run(
                    conn,
                    run_id=frontend_run_id,
                    status="complete" if frontend_result["failures"] == 0 else "error",
                    rows_written=frontend_result["rows_written"],
                    markets_complete=frontend_result["tokens"],
                    error_count=frontend_result["failures"],
                )

            if args.source_mode in {"both", BLOCK_CLOSE_SOURCE}:
                block_run_id = start_run(
                    conn,
                    source=BLOCK_CLOSE_SOURCE,
                    mode="daemon",
                    meta={
                        "since_ts": args.since_ts,
                        "token_limit": args.block_token_limit,
                        "block_window": args.block_window,
                        "min_orderfilled_trades": args.block_min_orderfilled_trades,
                        "shard_index": args.shard_index,
                        "shard_count": args.shard_count,
                    },
                )
                block_result = run_block_close_incremental(
                    conn,
                    ClickHouseClient(),
                    since_ts=args.since_ts,
                    token_limit=args.block_token_limit,
                    block_window=args.block_window,
                    block_overlap=args.block_overlap,
                    min_orderfilled_trades=args.block_min_orderfilled_trades,
                    shard_index=args.shard_index,
                    shard_count=args.shard_count,
                )
                finish_run(
                    conn,
                    run_id=block_run_id,
                    status="complete" if block_result["failures"] == 0 else "error",
                    rows_written=block_result["rows_written"],
                    markets_complete=block_result["tokens"],
                    error_count=block_result["failures"],
                )

        elapsed = time.time() - cycle_started
        sleep_seconds = max(0.0, float(args.sleep_seconds) - elapsed)
        if sleep_seconds:
            time.sleep(sleep_seconds)


def run_once(args: argparse.Namespace) -> dict[str, Any]:
    with postgres_connection(PostgresSettings()) as conn:
        create_schema(conn)
        if args.refresh_metadata:
            refresh_market_token_metadata(conn)
        if args.refresh_eligibility:
            refresh_eligibility(conn, ClickHouseClient())

        meta = vars(args).copy()
        run_id = start_run(conn, source=args.source, mode="once", meta=meta)
        try:
            if args.source == "frontend":
                result = backfill_frontend_prices(
                    conn,
                    FrontendPriceClient(),
                    start_ts=args.start_ts,
                    end_ts=args.end_ts,
                    fidelity_minutes=args.fidelity_minutes,
                    limit=args.limit,
                )
            elif args.source == "orderfilled_block_close":
                result = backfill_block_close_prices(
                    conn,
                    ClickHouseClient(),
                    from_block=args.from_block,
                    to_block=args.to_block,
                    limit=args.limit,
                )
            else:
                raise ValueError(f"unsupported source: {args.source}")
            finish_run(
                conn,
                run_id=run_id,
                status="complete",
                rows_written=int(result.get("rows_written") or 0),
                markets_complete=int(result.get("tokens") or 0),
                error_count=int(result.get("failures") or 0),
            )
            result["run_id"] = run_id
            return result
        except Exception as exc:
            finish_run(conn, run_id=run_id, status="error", rows_written=0, markets_complete=0, error_count=1, last_error=repr(exc))
            conn.commit()
            raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a one-shot quant price build.")
    parser.add_argument("--source", choices=("frontend", "orderfilled_block_close"), default="frontend")
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--refresh-eligibility", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--start-ts", type=int)
    parser.add_argument("--end-ts", type=int)
    parser.add_argument("--fidelity-minutes", type=int, default=1)
    parser.add_argument("--from-block", type=int)
    parser.add_argument("--to-block", type=int)
    parser.add_argument("--daemon", action="store_true")
    parser.add_argument("--source-mode", choices=("both", "frontend", "orderfilled_block_close", "maintenance"), default="both")
    parser.add_argument("--since-ts", type=int, default=SEPTEMBER_2025_TS)
    parser.add_argument("--token-limit", type=int, default=20)
    parser.add_argument("--frontend-token-limit", type=int)
    parser.add_argument("--block-token-limit", type=int)
    parser.add_argument("--sleep-seconds", type=float, default=30.0)
    parser.add_argument("--skip-maintenance", action="store_true")
    parser.add_argument("--metadata-interval-seconds", type=float, default=3600.0)
    parser.add_argument("--eligibility-interval-seconds", type=float, default=900.0)
    parser.add_argument("--frontend-min-orderfilled-trades", type=int, default=1000)
    parser.add_argument("--frontend-include-active-without-trades", action="store_true")
    parser.add_argument("--frontend-targets-only", action="store_true")
    parser.add_argument("--frontend-window-seconds", type=int, default=7 * 86400)
    parser.add_argument("--frontend-overlap-seconds", type=int, default=6 * 3600)
    parser.add_argument("--frontend-lag-seconds", type=int, default=120)
    parser.add_argument("--block-min-orderfilled-trades", type=int, default=1)
    parser.add_argument("--block-window", type=int, default=50000)
    parser.add_argument("--block-overlap", type=int, default=2000)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.frontend_token_limit = args.frontend_token_limit or args.token_limit
    args.block_token_limit = args.block_token_limit or args.token_limit
    args.shard_count = max(1, int(args.shard_count))
    args.shard_index = max(0, min(int(args.shard_index), args.shard_count - 1))
    if args.daemon:
        run_daemon(args)
        return
    if args.source == "frontend" and (args.start_ts is None or args.end_ts is None):
        raise SystemExit("--start-ts and --end-ts are required for frontend")
    if args.source == "orderfilled_block_close" and (args.from_block is None or args.to_block is None):
        raise SystemExit("--from-block and --to-block are required for orderfilled_block_close")
    print(run_once(args))


if __name__ == "__main__":
    main()
