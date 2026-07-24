#!/usr/bin/env python3
"""Durable tracking for raw OrderFilled tokens missing market registry coverage.

The goal is simple: if chain OrderFilled arrives before the local token registry
can resolve that token to a real market, record it durably so the gap is
auditable and can be repaired later. This prevents silent leakage into
downstream replay/build steps.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from db import get_backend
from trade.orderfilled_raw import normalize_block_time, normalize_hex


ORDERFILLED_REGISTRY_GAP_TABLE = "orderfilled_registry_gaps"


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def ensure_orderfilled_registry_gap_schema(conn) -> None:
    backend = get_backend()
    if backend == "mysql":
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {ORDERFILLED_REGISTRY_GAP_TABLE} (
                token_id VARCHAR(128) NOT NULL PRIMARY KEY,
                status VARCHAR(32) NOT NULL DEFAULT 'open',
                first_seen_block BIGINT,
                last_seen_block BIGINT,
                first_seen_at VARCHAR(40),
                last_seen_at VARCHAR(40),
                first_tx_hash CHAR(66),
                last_tx_hash CHAR(66),
                first_log_index BIGINT,
                last_log_index BIGINT,
                seen_count BIGINT NOT NULL DEFAULT 0,
                sample_market_id BIGINT,
                resolved_market_id BIGINT,
                resolved_condition_id VARCHAR(255),
                resolution_source VARCHAR(64),
                note TEXT,
                resolved_at VARCHAR(40),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
            """
        )
        return

    if backend in {"postgres", "postgresql"}:
        conn.execute("CREATE SCHEMA IF NOT EXISTS ops")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS ops.{ORDERFILLED_REGISTRY_GAP_TABLE} (
                token_id TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'open',
                first_seen_block BIGINT,
                last_seen_block BIGINT,
                first_seen_at TIMESTAMPTZ,
                last_seen_at TIMESTAMPTZ,
                first_tx_hash TEXT,
                last_tx_hash TEXT,
                first_log_index BIGINT,
                last_log_index BIGINT,
                seen_count BIGINT NOT NULL DEFAULT 0,
                sample_market_id BIGINT,
                resolved_market_id BIGINT,
                resolved_condition_id TEXT,
                resolution_source TEXT,
                note TEXT,
                resolved_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{ORDERFILLED_REGISTRY_GAP_TABLE}_status
            ON ops.{ORDERFILLED_REGISTRY_GAP_TABLE}(status, last_seen_block)
            """
        )
        return

    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {ORDERFILLED_REGISTRY_GAP_TABLE} (
            token_id TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'open',
            first_seen_block INTEGER,
            last_seen_block INTEGER,
            first_seen_at TEXT,
            last_seen_at TEXT,
            first_tx_hash TEXT,
            last_tx_hash TEXT,
            first_log_index INTEGER,
            last_log_index INTEGER,
            seen_count INTEGER NOT NULL DEFAULT 0,
            sample_market_id INTEGER,
            resolved_market_id INTEGER,
            resolved_condition_id TEXT,
            resolution_source TEXT,
            note TEXT,
            resolved_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        f"CREATE INDEX IF NOT EXISTS idx_{ORDERFILLED_REGISTRY_GAP_TABLE}_status ON {ORDERFILLED_REGISTRY_GAP_TABLE}(status, last_seen_block)"
    )


def upsert_orderfilled_registry_gap(
    conn,
    *,
    token_id: Any,
    block_number: Any = None,
    observed_at: Any = None,
    tx_hash: Any = None,
    log_index: Any = None,
    sample_market_id: Any = None,
    note: str = "",
) -> None:
    ensure_orderfilled_registry_gap_schema(conn)
    token_text = _text(token_id)
    if not token_text:
        return

    block_number_int = int(block_number or 0) if block_number not in (None, "") else None
    observed_text = normalize_block_time(observed_at) or _utc_now_text()
    tx_hash_text = normalize_hex(tx_hash, prefix=True) if tx_hash else ""
    log_index_int = int(log_index or 0) if log_index not in (None, "") else None
    sample_market_int = int(sample_market_id) if sample_market_id not in (None, "") else None
    note_text = _text(note)

    backend = get_backend()
    if backend == "mysql":
        conn.execute(
            f"""
            INSERT INTO {ORDERFILLED_REGISTRY_GAP_TABLE} (
                token_id, status, first_seen_block, last_seen_block, first_seen_at, last_seen_at,
                first_tx_hash, last_tx_hash, first_log_index, last_log_index,
                seen_count, sample_market_id, note, resolved_market_id,
                resolved_condition_id, resolution_source, resolved_at
            ) VALUES (%s, 'open', %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, NULL, NULL, NULL, NULL)
            ON DUPLICATE KEY UPDATE
                status = 'open',
                last_seen_block = VALUES(last_seen_block),
                last_seen_at = VALUES(last_seen_at),
                last_tx_hash = VALUES(last_tx_hash),
                last_log_index = VALUES(last_log_index),
                seen_count = COALESCE(seen_count, 0) + 1,
                sample_market_id = COALESCE(sample_market_id, VALUES(sample_market_id)),
                note = CASE
                    WHEN COALESCE(VALUES(note), '') <> '' THEN VALUES(note)
                    ELSE note
                END,
                resolved_market_id = NULL,
                resolved_condition_id = NULL,
                resolution_source = NULL,
                resolved_at = NULL
            """,
            (
                token_text,
                block_number_int,
                block_number_int,
                observed_text,
                observed_text,
                tx_hash_text,
                tx_hash_text,
                log_index_int,
                log_index_int,
                sample_market_int,
                note_text,
            ),
        )
        conn.commit()
        return

    if backend in {"postgres", "postgresql"}:
        conn.execute(
            f"""
            INSERT INTO {ORDERFILLED_REGISTRY_GAP_TABLE} (
                token_id, status, first_seen_block, last_seen_block, first_seen_at, last_seen_at,
                first_tx_hash, last_tx_hash, first_log_index, last_log_index,
                seen_count, sample_market_id, note, resolved_market_id,
                resolved_condition_id, resolution_source, resolved_at, updated_at
            ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, NULL, NULL, NULL, now())
            ON CONFLICT (token_id) DO UPDATE SET
                status = 'open',
                last_seen_block = EXCLUDED.last_seen_block,
                last_seen_at = EXCLUDED.last_seen_at,
                last_tx_hash = EXCLUDED.last_tx_hash,
                last_log_index = EXCLUDED.last_log_index,
                seen_count = COALESCE(orderfilled_registry_gaps.seen_count, 0) + 1,
                sample_market_id = COALESCE(orderfilled_registry_gaps.sample_market_id, EXCLUDED.sample_market_id),
                note = CASE
                    WHEN COALESCE(EXCLUDED.note, '') <> '' THEN EXCLUDED.note
                    ELSE orderfilled_registry_gaps.note
                END,
                resolved_market_id = NULL,
                resolved_condition_id = NULL,
                resolution_source = NULL,
                resolved_at = NULL,
                updated_at = now()
            """,
            (
                token_text,
                block_number_int,
                block_number_int,
                observed_text or None,
                observed_text or None,
                tx_hash_text or None,
                tx_hash_text or None,
                log_index_int,
                log_index_int,
                sample_market_int,
                note_text or None,
            ),
        )
        conn.commit()
        return

    conn.execute(
        f"""
        INSERT INTO {ORDERFILLED_REGISTRY_GAP_TABLE} (
            token_id, status, first_seen_block, last_seen_block, first_seen_at, last_seen_at,
            first_tx_hash, last_tx_hash, first_log_index, last_log_index,
            seen_count, sample_market_id, note, resolved_market_id,
            resolved_condition_id, resolution_source, resolved_at, updated_at
        ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP)
        ON CONFLICT(token_id) DO UPDATE SET
            status = 'open',
            last_seen_block = excluded.last_seen_block,
            last_seen_at = excluded.last_seen_at,
            last_tx_hash = excluded.last_tx_hash,
            last_log_index = excluded.last_log_index,
            seen_count = COALESCE(seen_count, 0) + 1,
            sample_market_id = COALESCE(sample_market_id, excluded.sample_market_id),
            note = CASE
                WHEN COALESCE(excluded.note, '') <> '' THEN excluded.note
                ELSE note
            END,
            resolved_market_id = NULL,
            resolved_condition_id = NULL,
            resolution_source = NULL,
            resolved_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            token_text,
            block_number_int,
            block_number_int,
            observed_text,
            observed_text,
            tx_hash_text,
            tx_hash_text,
            log_index_int,
            log_index_int,
            sample_market_int,
            note_text,
        ),
    )
    conn.commit()


def seed_orderfilled_registry_gap_snapshot(
    conn,
    *,
    token_id: Any,
    first_seen_block: Any = None,
    last_seen_block: Any = None,
    first_seen_at: Any = None,
    last_seen_at: Any = None,
    first_tx_hash: Any = None,
    last_tx_hash: Any = None,
    first_log_index: Any = None,
    last_log_index: Any = None,
    seen_count: Any = None,
    sample_market_id: Any = None,
    note: str = "",
    commit: bool = True,
    ensure_schema: bool = True,
) -> None:
    """Seed a historical gap snapshot without artificially incrementing counts.

    This is intended for historical backfills over already-materialized
    OrderFilled data, where we know the first/last block boundaries and an
    aggregate seen_count. Re-running the seed is idempotent: it keeps the
    earliest first_seen values, latest last_seen values, and the max seen_count.
    """

    if ensure_schema:
        ensure_orderfilled_registry_gap_schema(conn)
    token_text = _text(token_id)
    if not token_text:
        return

    first_seen_block_int = int(first_seen_block) if first_seen_block not in (None, "") else None
    last_seen_block_int = int(last_seen_block) if last_seen_block not in (None, "") else None
    first_seen_text = normalize_block_time(first_seen_at)
    last_seen_text = normalize_block_time(last_seen_at)
    first_tx_hash_text = normalize_hex(first_tx_hash, prefix=True) if first_tx_hash else ""
    last_tx_hash_text = normalize_hex(last_tx_hash, prefix=True) if last_tx_hash else ""
    first_log_index_int = int(first_log_index) if first_log_index not in (None, "") else None
    last_log_index_int = int(last_log_index) if last_log_index not in (None, "") else None
    seen_count_int = int(seen_count) if seen_count not in (None, "") else 0
    sample_market_int = int(sample_market_id) if sample_market_id not in (None, "") else None
    note_text = _text(note)

    backend = get_backend()
    if backend == "mysql":
        conn.execute(
            f"""
            INSERT INTO {ORDERFILLED_REGISTRY_GAP_TABLE} (
                token_id, status, first_seen_block, last_seen_block, first_seen_at, last_seen_at,
                first_tx_hash, last_tx_hash, first_log_index, last_log_index,
                seen_count, sample_market_id, note, resolved_market_id,
                resolved_condition_id, resolution_source, resolved_at
            ) VALUES (%s, 'open', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NULL, NULL, NULL, NULL)
            ON DUPLICATE KEY UPDATE
                status = 'open',
                first_seen_block = CASE
                    WHEN first_seen_block IS NULL THEN VALUES(first_seen_block)
                    WHEN VALUES(first_seen_block) IS NULL THEN first_seen_block
                    ELSE LEAST(first_seen_block, VALUES(first_seen_block))
                END,
                last_seen_block = CASE
                    WHEN last_seen_block IS NULL THEN VALUES(last_seen_block)
                    WHEN VALUES(last_seen_block) IS NULL THEN last_seen_block
                    ELSE GREATEST(last_seen_block, VALUES(last_seen_block))
                END,
                first_seen_at = COALESCE(first_seen_at, VALUES(first_seen_at)),
                last_seen_at = COALESCE(VALUES(last_seen_at), last_seen_at),
                first_tx_hash = COALESCE(first_tx_hash, VALUES(first_tx_hash)),
                last_tx_hash = COALESCE(VALUES(last_tx_hash), last_tx_hash),
                first_log_index = COALESCE(first_log_index, VALUES(first_log_index)),
                last_log_index = COALESCE(VALUES(last_log_index), last_log_index),
                seen_count = GREATEST(COALESCE(seen_count, 0), VALUES(seen_count)),
                sample_market_id = COALESCE(sample_market_id, VALUES(sample_market_id)),
                note = CASE
                    WHEN COALESCE(VALUES(note), '') <> '' THEN VALUES(note)
                    ELSE note
                END,
                resolved_market_id = NULL,
                resolved_condition_id = NULL,
                resolution_source = NULL,
                resolved_at = NULL
            """,
            (
                token_text,
                first_seen_block_int,
                last_seen_block_int,
                first_seen_text,
                last_seen_text,
                first_tx_hash_text or None,
                last_tx_hash_text or None,
                first_log_index_int,
                last_log_index_int,
                seen_count_int,
                sample_market_int,
                note_text or None,
            ),
        )
        if commit:
            conn.commit()
        return

    if backend in {"postgres", "postgresql"}:
        conn.execute(
            f"""
            INSERT INTO {ORDERFILLED_REGISTRY_GAP_TABLE} (
                token_id, status, first_seen_block, last_seen_block, first_seen_at, last_seen_at,
                first_tx_hash, last_tx_hash, first_log_index, last_log_index,
                seen_count, sample_market_id, note, resolved_market_id,
                resolved_condition_id, resolution_source, resolved_at, updated_at
            ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, now())
            ON CONFLICT (token_id) DO UPDATE SET
                status = 'open',
                first_seen_block = CASE
                    WHEN orderfilled_registry_gaps.first_seen_block IS NULL THEN EXCLUDED.first_seen_block
                    WHEN EXCLUDED.first_seen_block IS NULL THEN orderfilled_registry_gaps.first_seen_block
                    ELSE LEAST(orderfilled_registry_gaps.first_seen_block, EXCLUDED.first_seen_block)
                END,
                last_seen_block = CASE
                    WHEN orderfilled_registry_gaps.last_seen_block IS NULL THEN EXCLUDED.last_seen_block
                    WHEN EXCLUDED.last_seen_block IS NULL THEN orderfilled_registry_gaps.last_seen_block
                    ELSE GREATEST(orderfilled_registry_gaps.last_seen_block, EXCLUDED.last_seen_block)
                END,
                first_seen_at = COALESCE(orderfilled_registry_gaps.first_seen_at, EXCLUDED.first_seen_at),
                last_seen_at = COALESCE(EXCLUDED.last_seen_at, orderfilled_registry_gaps.last_seen_at),
                first_tx_hash = COALESCE(orderfilled_registry_gaps.first_tx_hash, EXCLUDED.first_tx_hash),
                last_tx_hash = COALESCE(EXCLUDED.last_tx_hash, orderfilled_registry_gaps.last_tx_hash),
                first_log_index = COALESCE(orderfilled_registry_gaps.first_log_index, EXCLUDED.first_log_index),
                last_log_index = COALESCE(EXCLUDED.last_log_index, orderfilled_registry_gaps.last_log_index),
                seen_count = GREATEST(COALESCE(orderfilled_registry_gaps.seen_count, 0), COALESCE(EXCLUDED.seen_count, 0)),
                sample_market_id = COALESCE(orderfilled_registry_gaps.sample_market_id, EXCLUDED.sample_market_id),
                note = CASE
                    WHEN COALESCE(EXCLUDED.note, '') <> '' THEN EXCLUDED.note
                    ELSE orderfilled_registry_gaps.note
                END,
                resolved_market_id = NULL,
                resolved_condition_id = NULL,
                resolution_source = NULL,
                resolved_at = NULL,
                updated_at = now()
            """,
            (
                token_text,
                first_seen_block_int,
                last_seen_block_int,
                first_seen_text or None,
                last_seen_text or None,
                first_tx_hash_text or None,
                last_tx_hash_text or None,
                first_log_index_int,
                last_log_index_int,
                seen_count_int,
                sample_market_int,
                note_text or None,
            ),
        )
        if commit:
            conn.commit()
        return

    conn.execute(
        f"""
        INSERT INTO {ORDERFILLED_REGISTRY_GAP_TABLE} (
            token_id, status, first_seen_block, last_seen_block, first_seen_at, last_seen_at,
            first_tx_hash, last_tx_hash, first_log_index, last_log_index,
            seen_count, sample_market_id, note, resolved_market_id,
            resolved_condition_id, resolution_source, resolved_at, updated_at
        ) VALUES (?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, CURRENT_TIMESTAMP)
        ON CONFLICT(token_id) DO UPDATE SET
            status = 'open',
            first_seen_block = CASE
                WHEN first_seen_block IS NULL THEN excluded.first_seen_block
                WHEN excluded.first_seen_block IS NULL THEN first_seen_block
                ELSE MIN(first_seen_block, excluded.first_seen_block)
            END,
            last_seen_block = CASE
                WHEN last_seen_block IS NULL THEN excluded.last_seen_block
                WHEN excluded.last_seen_block IS NULL THEN last_seen_block
                ELSE MAX(last_seen_block, excluded.last_seen_block)
            END,
            first_seen_at = COALESCE(first_seen_at, excluded.first_seen_at),
            last_seen_at = COALESCE(excluded.last_seen_at, last_seen_at),
            first_tx_hash = COALESCE(first_tx_hash, excluded.first_tx_hash),
            last_tx_hash = COALESCE(excluded.last_tx_hash, last_tx_hash),
            first_log_index = COALESCE(first_log_index, excluded.first_log_index),
            last_log_index = COALESCE(excluded.last_log_index, last_log_index),
            seen_count = MAX(COALESCE(seen_count, 0), COALESCE(excluded.seen_count, 0)),
            sample_market_id = COALESCE(sample_market_id, excluded.sample_market_id),
            note = CASE
                WHEN COALESCE(excluded.note, '') <> '' THEN excluded.note
                ELSE note
            END,
            resolved_market_id = NULL,
            resolved_condition_id = NULL,
            resolution_source = NULL,
            resolved_at = NULL,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            token_text,
            first_seen_block_int,
            last_seen_block_int,
            first_seen_text,
            last_seen_text,
            first_tx_hash_text,
            last_tx_hash_text,
            first_log_index_int,
            last_log_index_int,
            seen_count_int,
            sample_market_int,
            note_text,
        ),
    )
    if commit:
        conn.commit()


def resolve_orderfilled_registry_gap(
    conn,
    *,
    token_id: Any,
    market_id: Any,
    condition_id: Any = None,
    resolution_source: str = "market_lookup",
) -> None:
    ensure_orderfilled_registry_gap_schema(conn)
    token_text = _text(token_id)
    if not token_text:
        return
    market_int = int(market_id) if market_id not in (None, "") else None
    condition_text = _text(condition_id)
    source_text = _text(resolution_source) or "market_lookup"
    resolved_text = _utc_now_text()

    backend = get_backend()
    if backend == "mysql":
        conn.execute(
            f"""
            UPDATE {ORDERFILLED_REGISTRY_GAP_TABLE}
            SET status = 'resolved',
                resolved_market_id = %s,
                resolved_condition_id = %s,
                resolution_source = %s,
                resolved_at = %s
            WHERE token_id = %s
            """,
            (market_int, condition_text, source_text, resolved_text, token_text),
        )
        conn.commit()
        return

    conn.execute(
        f"""
        UPDATE {ORDERFILLED_REGISTRY_GAP_TABLE}
        SET status = 'resolved',
            resolved_market_id = ?,
            resolved_condition_id = ?,
            resolution_source = ?,
            resolved_at = ?,
            updated_at = { 'now()' if backend in {'postgres', 'postgresql'} else 'CURRENT_TIMESTAMP' }
        WHERE token_id = ?
        """,
        (market_int, condition_text or None, source_text, resolved_text, token_text),
    )
    conn.commit()
