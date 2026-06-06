"""Postgres schema for quant price production tables."""

from __future__ import annotations

from typing import Any


CREATE_SCHEMA_SQL = "CREATE SCHEMA IF NOT EXISTS quant"


CREATE_TABLE_SQL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS quant.market_token_metadata (
        market_id BIGINT NOT NULL,
        gamma_market_id TEXT,
        market_slug TEXT,
        condition_id TEXT,
        question_id TEXT,
        market_title TEXT,
        token_id TEXT NOT NULL PRIMARY KEY,
        token_side TEXT NOT NULL,
        outcome_index INTEGER,
        active BOOLEAN NOT NULL DEFAULT TRUE,
        closed BOOLEAN NOT NULL DEFAULT FALSE,
        archived BOOLEAN NOT NULL DEFAULT FALSE,
        deprecated BOOLEAN NOT NULL DEFAULT FALSE,
        duplicate_group_key TEXT,
        end_date TIMESTAMPTZ,
        created_at TIMESTAMPTZ,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quant.market_price_eligibility (
        token_id TEXT PRIMARY KEY REFERENCES quant.market_token_metadata(token_id) ON DELETE CASCADE,
        market_id BIGINT NOT NULL,
        market_slug TEXT,
        token_side TEXT NOT NULL,
        eligible BOOLEAN NOT NULL DEFAULT FALSE,
        has_orderfilled_trades BOOLEAN NOT NULL DEFAULT FALSE,
        is_archived BOOLEAN NOT NULL DEFAULT FALSE,
        is_deprecated BOOLEAN NOT NULL DEFAULT FALSE,
        is_duplicate_market BOOLEAN NOT NULL DEFAULT FALSE,
        skip_reason TEXT,
        orderfilled_trade_count BIGINT NOT NULL DEFAULT 0,
        first_orderfilled_block BIGINT,
        last_orderfilled_block BIGINT,
        frontend_points BIGINT NOT NULL DEFAULT 0,
        checked_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quant.market_token_frontend_price_1m (
        token_id TEXT NOT NULL REFERENCES quant.market_token_metadata(token_id) ON DELETE CASCADE,
        market_id BIGINT NOT NULL,
        market_slug TEXT,
        token_side TEXT NOT NULL,
        ts_minute TIMESTAMPTZ NOT NULL,
        timestamp BIGINT NOT NULL,
        price NUMERIC(20, 10) NOT NULL,
        source TEXT NOT NULL DEFAULT 'prices-history',
        fidelity_minutes INTEGER NOT NULL DEFAULT 1,
        fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (token_id, ts_minute)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quant.market_token_block_close (
        token_id TEXT NOT NULL REFERENCES quant.market_token_metadata(token_id) ON DELETE CASCADE,
        market_id BIGINT NOT NULL,
        market_slug TEXT,
        token_side TEXT NOT NULL,
        block_number BIGINT NOT NULL,
        close_price NUMERIC(20, 10) NOT NULL,
        yes_probability_close NUMERIC(20, 10),
        vwap_price NUMERIC(20, 10),
        yes_probability_vwap NUMERIC(20, 10),
        close_raw_price NUMERIC(20, 10),
        close_price_source TEXT NOT NULL DEFAULT 'unknown',
        close_tx_hash TEXT,
        close_log_index INTEGER,
        close_maker_amount NUMERIC(38, 0),
        close_taker_amount NUMERIC(38, 0),
        trade_count BIGINT NOT NULL DEFAULT 0,
        raw_trade_count BIGINT NOT NULL DEFAULT 0,
        internal_filtered_count BIGINT NOT NULL DEFAULT 0,
        invalid_size_count BIGINT NOT NULL DEFAULT 0,
        invalid_price_count BIGINT NOT NULL DEFAULT 0,
        amount_ratio_count BIGINT NOT NULL DEFAULT 0,
        raw_price_fallback_count BIGINT NOT NULL DEFAULT 0,
        extreme_trade_count BIGINT NOT NULL DEFAULT 0,
        anomaly_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
        volume NUMERIC(38, 10) NOT NULL DEFAULT 0,
        source TEXT NOT NULL DEFAULT 'clean_orderfilled_fact',
        built_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (token_id, block_number)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quant.market_price_build_runs (
        run_id BIGSERIAL PRIMARY KEY,
        source TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'once',
        status TEXT NOT NULL,
        started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        finished_at TIMESTAMPTZ,
        requested_from_ts TIMESTAMPTZ,
        requested_to_ts TIMESTAMPTZ,
        requested_from_block BIGINT,
        requested_to_block BIGINT,
        markets_total BIGINT NOT NULL DEFAULT 0,
        markets_complete BIGINT NOT NULL DEFAULT 0,
        rows_written BIGINT NOT NULL DEFAULT 0,
        error_count BIGINT NOT NULL DEFAULT 0,
        last_error TEXT,
        meta JSONB NOT NULL DEFAULT '{}'::jsonb
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quant.market_price_build_market_state (
        source TEXT NOT NULL,
        token_id TEXT NOT NULL REFERENCES quant.market_token_metadata(token_id) ON DELETE CASCADE,
        market_id BIGINT NOT NULL,
        market_slug TEXT,
        token_side TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        next_from_ts TIMESTAMPTZ,
        next_to_ts TIMESTAMPTZ,
        next_from_block BIGINT,
        next_to_block BIGINT,
        last_complete_ts TIMESTAMPTZ,
        last_complete_block BIGINT,
        attempt_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        PRIMARY KEY (source, token_id)
    )
    """,
)


ALTER_TABLE_SQL: tuple[str, ...] = (
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS yes_probability_close NUMERIC(20, 10)",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS vwap_price NUMERIC(20, 10)",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS yes_probability_vwap NUMERIC(20, 10)",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS close_raw_price NUMERIC(20, 10)",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS close_price_source TEXT NOT NULL DEFAULT 'unknown'",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS close_maker_amount NUMERIC(38, 0)",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS close_taker_amount NUMERIC(38, 0)",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS raw_trade_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS internal_filtered_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS invalid_size_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS invalid_price_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS amount_ratio_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS raw_price_fallback_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS extreme_trade_count BIGINT NOT NULL DEFAULT 0",
    "ALTER TABLE quant.market_token_block_close ADD COLUMN IF NOT EXISTS anomaly_flags JSONB NOT NULL DEFAULT '[]'::jsonb",
    "ALTER TABLE quant.market_token_block_close ALTER COLUMN source SET DEFAULT 'clean_orderfilled_fact'",
)


CREATE_INDEX_SQL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_quant_metadata_slug_side ON quant.market_token_metadata (market_slug, token_side)",
    "CREATE INDEX IF NOT EXISTS idx_quant_metadata_market_side ON quant.market_token_metadata (market_id, token_side)",
    "CREATE INDEX IF NOT EXISTS idx_quant_eligibility_eligible ON quant.market_price_eligibility (eligible, market_id)",
    "CREATE INDEX IF NOT EXISTS idx_quant_frontend_slug_side_time ON quant.market_token_frontend_price_1m (market_slug, token_side, ts_minute)",
    "CREATE INDEX IF NOT EXISTS idx_quant_frontend_market_side_time ON quant.market_token_frontend_price_1m (market_id, token_side, ts_minute)",
    "CREATE INDEX IF NOT EXISTS idx_quant_block_close_slug_side_block ON quant.market_token_block_close (market_slug, token_side, block_number)",
    "CREATE INDEX IF NOT EXISTS idx_quant_block_close_market_side_block ON quant.market_token_block_close (market_id, token_side, block_number)",
    "CREATE INDEX IF NOT EXISTS idx_quant_build_state_status ON quant.market_price_build_market_state (source, status, updated_at)",
)


def create_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_SCHEMA_SQL)
        for statement in CREATE_TABLE_SQL:
            cur.execute(statement)
        for statement in ALTER_TABLE_SQL:
            cur.execute(statement)
        for statement in CREATE_INDEX_SQL:
            cur.execute(statement)
