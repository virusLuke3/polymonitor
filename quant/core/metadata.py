"""Market/token metadata loader for quant price builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class MarketTokenMetadata:
    market_id: int
    gamma_market_id: str | None
    market_slug: str | None
    condition_id: str | None
    question_id: str | None
    market_title: str | None
    token_id: str
    token_id_hex: str | None
    token_side: str
    outcome_index: int | None
    active: bool
    closed: bool
    archived: bool
    deprecated: bool
    duplicate_group_key: str | None
    end_date: Any
    created_at: Any


def _row_to_metadata(row: dict[str, Any]) -> MarketTokenMetadata:
    token_id = str(row["token_id"])
    return MarketTokenMetadata(
        market_id=int(row["market_id"]),
        gamma_market_id=row.get("gamma_market_id"),
        market_slug=row.get("market_slug"),
        condition_id=row.get("condition_id"),
        question_id=row.get("question_id"),
        market_title=row.get("market_title"),
        token_id=token_id,
        token_id_hex=derive_clickhouse_token_id_hex(token_id),
        token_side=str(row.get("token_side") or "").upper(),
        outcome_index=row.get("outcome_index"),
        active=bool(row.get("active", True)),
        closed=bool(row.get("closed", False)),
        archived=bool(row.get("archived", False)),
        deprecated=bool(row.get("deprecated", False)),
        duplicate_group_key=row.get("duplicate_group_key"),
        end_date=row.get("end_date"),
        created_at=row.get("created_at"),
    )


def derive_clickhouse_token_id_hex(token_id: str | None) -> str | None:
    """Convert a CLOB decimal token id to ClickHouse's normalized hex token id."""

    text = str(token_id or "").strip().lower()
    if not text:
        return None
    if text.startswith("0x"):
        text = text[2:]
    if len(text) == 64 and all(ch in "0123456789abcdef" for ch in text):
        return text
    if not text.isdigit():
        return None
    try:
        return format(int(text), "064x")
    except ValueError:
        return None


def fetch_market_token_metadata(
    conn: Any,
    *,
    limit: int | None = None,
    market_slug: str | None = None,
    since_ts: int | None = None,
) -> list[MarketTokenMetadata]:
    params: list[Any] = []
    filters = ["mt.token_id IS NOT NULL", "mt.token_id <> ''"]
    if market_slug:
        filters.append("m.slug = %s")
        params.append(market_slug)
    if since_ts is not None:
        filters.append(
            """
            (
                m.created_at >= to_timestamp(%s)
                OR m.end_date >= to_timestamp(%s)
            )
            """
        )
        params.extend([int(since_ts), int(since_ts)])
    limit_sql = ""
    if limit is not None:
        limit_sql = "LIMIT %s"
        params.append(int(limit))
    sql = f"""
        SELECT
            m.id AS market_id,
            m.gamma_market_id,
            m.slug AS market_slug,
            m.condition_id,
            m.question_id,
            COALESCE(m.title, m.slug) AS market_title,
            mt.token_id,
            UPPER(COALESCE(mt.outcome, CASE WHEN mt.outcome_index = 0 THEN 'YES' WHEN mt.outcome_index = 1 THEN 'NO' ELSE 'UNKNOWN' END)) AS token_side,
            mt.outcome_index,
            COALESCE(mt.active, TRUE) AS active,
            COALESCE(mss.is_trading_closed, FALSE) AS closed,
            (
                m.slug ILIKE 'arch-%%'
                OR m.slug ILIKE '%%-arch-%%'
                OR m.title ILIKE 'ARCH:%%'
                OR m.title ILIKE '[ARCH]%%'
            ) AS archived,
            (
                m.slug ILIKE '%%deprecated%%'
                OR m.title ILIKE '%%deprecated%%'
            ) AS deprecated,
            lower(COALESCE(NULLIF(m.condition_id, ''), NULLIF(m.question_id, ''), NULLIF(m.slug, ''))) AS duplicate_group_key,
            COALESCE(mt.end_date, m.end_date) AS end_date,
            m.created_at AS created_at
        FROM core.market_tokens mt
        JOIN core.markets m ON m.id = mt.market_id
        LEFT JOIN core.market_status_snapshot mss ON mss.market_id = m.id
        WHERE {" AND ".join(filters)}
        ORDER BY m.id ASC, mt.outcome_index ASC, mt.token_id ASC
        {limit_sql}
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [_row_to_metadata(dict(row)) for row in cur.fetchall()]


def upsert_market_token_metadata(conn: Any, rows: Iterable[MarketTokenMetadata]) -> int:
    values = [
        (
            row.market_id,
            row.gamma_market_id,
            row.market_slug,
            row.condition_id,
            row.question_id,
            row.market_title,
            row.token_id,
            row.token_id_hex,
            row.token_side,
            row.outcome_index,
            row.active,
            row.closed,
            row.archived,
            row.deprecated,
            row.duplicate_group_key,
            row.end_date,
            row.created_at,
        )
        for row in rows
    ]
    if not values:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO quant.market_token_metadata (
                market_id, gamma_market_id, market_slug, condition_id, question_id,
                market_title, token_id, token_id_hex, token_side, outcome_index, active, closed,
                archived, deprecated, duplicate_group_key, end_date, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (token_id) DO UPDATE SET
                market_id = EXCLUDED.market_id,
                gamma_market_id = EXCLUDED.gamma_market_id,
                market_slug = EXCLUDED.market_slug,
                condition_id = EXCLUDED.condition_id,
                question_id = EXCLUDED.question_id,
                market_title = EXCLUDED.market_title,
                token_id_hex = EXCLUDED.token_id_hex,
                token_side = EXCLUDED.token_side,
                outcome_index = EXCLUDED.outcome_index,
                active = EXCLUDED.active,
                closed = EXCLUDED.closed,
                archived = EXCLUDED.archived,
                deprecated = EXCLUDED.deprecated,
                duplicate_group_key = EXCLUDED.duplicate_group_key,
                end_date = EXCLUDED.end_date,
                created_at = EXCLUDED.created_at,
                updated_at = now()
            """,
            values,
        )
        return cur.rowcount or len(values)


def refresh_market_token_metadata(conn: Any, *, limit: int | None = None, market_slug: str | None = None, since_ts: int | None = None) -> int:
    return upsert_market_token_metadata(conn, fetch_market_token_metadata(conn, limit=limit, market_slug=market_slug, since_ts=since_ts))
