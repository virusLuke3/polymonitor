"""Market selectors for optional validation DB smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from ...core.db import postgres_connection
from .data_sources import MarketCandidate


NBA_KEYWORDS = (
    "nba",
    "basketball",
    "knicks",
    "celtics",
    "lakers",
    "warriors",
    "spurs",
    "thunder",
    "mavericks",
    "nuggets",
    "bucks",
    "76ers",
    "heat",
    "suns",
)


@dataclass(frozen=True)
class ResolvedMarketCandidate:
    market_id: int
    market_slug: str
    title: str
    end_date: datetime | None
    settlement_code: int
    settlement_outcome: str


def select_nba_2024_25_markets(*, limit: int = 5) -> list[MarketCandidate]:
    pattern_filters = " OR ".join(
        [
            "lower(e.event_title) LIKE %s",
            "lower(e.event_slug) LIKE %s",
            "lower(m.question) LIKE %s",
            "lower(m.market_slug) LIKE %s",
            "lower(m.outcome_label) LIKE %s",
        ]
    )
    params: list[Any] = []
    keyword_groups: list[str] = []
    for keyword in NBA_KEYWORDS:
        keyword_groups.append(f"({pattern_filters})")
        params.extend([f"%{keyword}%"] * 5)
    params.append(limit)
    with postgres_connection(readonly=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT
                    m.market_id,
                    m.market_slug,
                    m.token_yes_id AS token_id,
                    'YES' AS token_side,
                    p.min_block_complete AS from_block,
                    p.max_block_complete AS to_block,
                    COALESCE(m.question, e.event_title, m.market_slug) AS title
                FROM quant.market_event_members m
                JOIN quant.market_event_metadata e ON e.event_slug = m.event_slug
                JOIN quant.market_price_build_market_progress p ON p.market_id = m.market_id
                WHERE ({' OR '.join(keyword_groups)})
                  AND COALESCE(e.start_date, e.created_at, m.created_at) >= TIMESTAMPTZ '2024-10-01'
                  AND COALESCE(e.start_date, e.created_at, m.created_at) < TIMESTAMPTZ '2025-07-01'
                  AND m.coverage_status = 'ready'
                  AND m.block_rows > 0
                  AND m.orderfilled_rows > 0
                  AND p.min_block_complete IS NOT NULL
                  AND p.max_block_complete IS NOT NULL
                  AND m.token_yes_id IS NOT NULL
                ORDER BY m.block_rows DESC, m.orderfilled_rows DESC, m.updated_at DESC
                LIMIT %s
                """,
                params,
            )
            return [
                MarketCandidate(
                    market_id=int(row["market_id"]),
                    market_slug=str(row["market_slug"]),
                    token_id=str(row["token_id"]) if row.get("token_id") else None,
                    token_side=str(row["token_side"]),
                    from_block=int(row["from_block"]) if row.get("from_block") is not None else None,
                    to_block=int(row["to_block"]) if row.get("to_block") is not None else None,
                    title=str(row.get("title") or ""),
                )
                for row in cur.fetchall()
            ]


def select_nba_2024_25_moneyline_markets(*, limit: int = 200) -> list[ResolvedMarketCandidate]:
    """Select resolved NBA 2024/25 moneyline markets from metadata tables only.

    This intentionally does not require `quant.market_token_block_close` coverage:
    the 2024/25 NBA moneyline data currently exists in `core.markets` plus raw
    ClickHouse OrderFilled rows, while many of those markets have not been
    materialized into `quant.market_token_block_close` yet.
    """
    with postgres_connection(readonly=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    m.id AS market_id,
                    m.slug AS market_slug,
                    m.title,
                    m.end_date,
                    s.settlement_code,
                    s.settlement_outcome
                FROM core.markets m
                JOIN core.market_status_snapshot s ON s.market_id = m.id
                WHERE lower(m.slug) ~ '^nba-[a-z]{2,4}-[a-z]{2,4}-20[0-9]{2}-[0-9]{2}-[0-9]{2}$'
                  AND COALESCE(m.end_date, m.created_at) >= TIMESTAMPTZ '2024-10-01'
                  AND COALESCE(m.end_date, m.created_at) < TIMESTAMPTZ '2025-07-01'
                  AND s.is_resolved IS TRUE
                  AND s.settlement_code IN (1, 2)
                ORDER BY m.end_date ASC, m.id ASC
                LIMIT %s
                """,
                (limit,),
            )
            return [
                ResolvedMarketCandidate(
                    market_id=int(row["market_id"]),
                    market_slug=str(row["market_slug"]),
                    title=str(row.get("title") or row["market_slug"]),
                    end_date=row.get("end_date"),
                    settlement_code=int(row["settlement_code"]),
                    settlement_outcome=str(row.get("settlement_outcome") or ""),
                )
                for row in cur.fetchall()
            ]
