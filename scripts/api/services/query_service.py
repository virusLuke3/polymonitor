from __future__ import annotations

from api.context import RuntimeResources, runtime_resources

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, cast

from api.context import resolve_service_callable
from api.services import clickhouse_orderfilled_service


@dataclass(frozen=True)
class DashboardStatusDependencies:
    query_all: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> DashboardStatusDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            query_all=resolve_service_callable(context, "query_all"),
        )


@dataclass(frozen=True)
class RecentTradeWindowDependencies:
    query_one: Callable[..., Any]
    table_exists: Callable[..., Any]
    get_existing_trade_read_source: Callable[..., Any]
    identifier_name: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> RecentTradeWindowDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            query_one=resolve_service_callable(context, "query_one"),
            table_exists=resolve_service_callable(context, "table_exists"),
            get_existing_trade_read_source=resolve_service_callable(
                context,
                "get_existing_trade_read_source",
            ),
            identifier_name=resolve_service_callable(context, "_identifier_name"),
        )


@dataclass(frozen=True)
class DashboardTradeVolumeDependencies:
    query_all: Callable[..., Any]
    get_existing_trade_read_source: Callable[..., Any]
    utc_date_days_ago: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> DashboardTradeVolumeDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            query_all=resolve_service_callable(context, "query_all"),
            get_existing_trade_read_source=resolve_service_callable(
                context,
                "get_existing_trade_read_source",
            ),
            utc_date_days_ago=resolve_service_callable(
                context,
                "utc_date_days_ago",
            ),
        )


@dataclass(frozen=True)
class DashboardRecentMarketsDependencies:
    query_all: Callable[..., Any]
    get_existing_trade_read_source: Callable[..., Any]
    utc_date_days_ago: Callable[..., Any]
    build_market_status_case: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> DashboardRecentMarketsDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            query_all=resolve_service_callable(context, "query_all"),
            get_existing_trade_read_source=resolve_service_callable(
                context,
                "get_existing_trade_read_source",
            ),
            utc_date_days_ago=resolve_service_callable(
                context,
                "utc_date_days_ago",
            ),
            build_market_status_case=resolve_service_callable(
                context,
                "build_market_status_case",
            ),
        )


@dataclass(frozen=True)
class TradeCountEstimateDependencies:
    query_one: Callable[..., Any]
    get_existing_trade_read_source: Callable[..., Any]
    identifier_name: Callable[..., Any]
    get_backend: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> TradeCountEstimateDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            query_one=resolve_service_callable(context, "query_one"),
            get_existing_trade_read_source=resolve_service_callable(
                context,
                "get_existing_trade_read_source",
            ),
            identifier_name=resolve_service_callable(context, "_identifier_name"),
            get_backend=resolve_service_callable(context, "get_backend"),
        )


@dataclass(frozen=True)
class RecentOracleDependencies:
    query_all: Callable[..., Any]
    normalize_oracle_event: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> RecentOracleDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            query_all=resolve_service_callable(context, "query_all"),
            normalize_oracle_event=resolve_service_callable(
                context,
                "normalize_oracle_event",
            ),
        )


@dataclass(frozen=True)
class ContentStorageDependencies:
    resources: RuntimeResources
    application: Any
    database_path: str
    get_backend: Callable[..., Any]
    table_exists: Callable[..., Any]
    get_connection: Callable[..., Any]
    query_all: Callable[..., Any]
    query_one: Callable[..., Any]

    @classmethod
    def from_context(
        cls,
        context: Mapping[str, Any],
    ) -> ContentStorageDependencies:
        if isinstance(context, cls):
            return context
        return cls(
            resources=runtime_resources(context),
            application=context.get("app"),
            database_path=cast(
                str,
                context.get("DB_PATH"),
            ),
            get_backend=resolve_service_callable(context, "get_backend"),
            table_exists=resolve_service_callable(context, "table_exists"),
            get_connection=resolve_service_callable(context, "get_connection"),
            query_all=resolve_service_callable(context, "query_all"),
            query_one=resolve_service_callable(context, "query_one"),
        )


def fetch_dashboard_market_status(
    ctx: Mapping[str, Any],
    now_iso: str,
) -> List[Dict[str, Any]]:
    dependencies = DashboardStatusDependencies.from_context(ctx)
    return dependencies.query_all(
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


def fetch_recent_trade_window_bounds(
    ctx: Mapping[str, Any],
    window_size: int,
) -> Dict[str, Any]:
    dependencies = RecentTradeWindowDependencies.from_context(ctx)
    if dependencies.table_exists("market_trade_daily_stats"):
        summary_days = 30 if window_size >= 50000 else 7
        summary_row = dependencies.query_one(
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

    trade_source = dependencies.get_existing_trade_read_source()
    if trade_source is None:
        return {"trade_count": 0, "earliest_timestamp": None, "latest_timestamp": None, "source": "none"}
    payload = dependencies.query_one(
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
    payload["source"] = dependencies.identifier_name(trade_source)
    return payload


def fetch_dashboard_trade_volume(
    ctx: Mapping[str, Any],
    window_size: int,
) -> List[Dict[str, Any]]:
    dependencies = DashboardTradeVolumeDependencies.from_context(ctx)
    summary_threshold = dependencies.utc_date_days_ago(30)
    summary_rows = dependencies.query_all(
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
    trade_source = dependencies.get_existing_trade_read_source()
    if trade_source is None:
        return []
    return dependencies.query_all(
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


def fetch_dashboard_recent_markets(
    ctx: Mapping[str, Any],
    now_iso: str,
    window_size: int,
) -> List[Dict[str, Any]]:
    dependencies = DashboardRecentMarketsDependencies.from_context(ctx)
    status_case = dependencies.build_market_status_case(now_iso)
    summary_threshold = dependencies.utc_date_days_ago(30)
    summary_rows = dependencies.query_all(
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

    trade_source = dependencies.get_existing_trade_read_source()
    if trade_source is None:
        return []
    return dependencies.query_all(
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


def fetch_trade_count_estimate(
    ctx: Mapping[str, Any],
) -> Dict[str, Any]:
    dependencies = TradeCountEstimateDependencies.from_context(ctx)
    trade_source = dependencies.get_existing_trade_read_source()
    if trade_source is None:
        return {"table_rows": 0, "auto_increment": 0}
    if dependencies.get_backend() == "sqlite":
        return dependencies.query_one(
            f"""
            SELECT COUNT(*) AS table_rows, COALESCE(MAX(id), 0) AS auto_increment
            FROM {trade_source}
            """
        )
    return dependencies.query_one(
        f"""
        SELECT
            COALESCE(table_rows, 0) AS table_rows,
            COALESCE(auto_increment, 0) AS auto_increment
        FROM information_schema.tables
        WHERE table_schema = DATABASE() AND table_name = '{dependencies.identifier_name(trade_source)}'
        """
    )


def get_recent_trades(
    ctx: Mapping[str, Any],
    limit: int = 24,
) -> List[Dict[str, Any]]:
    clickhouse_rows = clickhouse_orderfilled_service.get_recent_trades(ctx, limit=limit)
    if clickhouse_rows is not None:
        return clickhouse_rows
    raise TimeoutError("ClickHouse OrderFilled read is enabled but unavailable")


def get_recent_oracle_events(
    ctx: Mapping[str, Any],
    limit: int = 24,
) -> List[Dict[str, Any]]:
    dependencies = RecentOracleDependencies.from_context(ctx)
    rows = dependencies.query_all(
        """
        SELECT
            oe.id, oe.tx_hash, oe.log_index, oe.block_number, oe.event_time, oe.event_status, oe.external_market_id,
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
    return [dependencies.normalize_oracle_event(row) for row in rows]


def _api_readonly() -> bool:
    return str(os.environ.get("POLYDATA_API_READONLY", "")).strip().lower() in {"1", "true", "yes", "on"}


def _ensure_content_tables(
    dependencies: ContentStorageDependencies,
) -> None:
    if _api_readonly():
        return
    backend = str(dependencies.get_backend() or "").lower()
    with dependencies.resources.content_lock:
        if backend in dependencies.resources.content_tables_ensured:
            return
    conn = dependencies.get_connection(dependencies.database_path)
    try:
        if backend == "sqlite":
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_items (
                    id TEXT PRIMARY KEY,
                    content_type TEXT,
                    provider TEXT,
                    source TEXT,
                    category TEXT,
                    topic_id TEXT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT,
                    summary TEXT,
                    source_count INTEGER DEFAULT 1,
                    relevance_score INTEGER,
                    raw_payload TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_links (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_id TEXT NOT NULL,
                    market_id INTEGER NOT NULL,
                    event_slug TEXT,
                    category TEXT,
                    topic_id TEXT,
                    link_score INTEGER,
                    link_reason TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(content_id, market_id)
                )
                """
            )
            for table, column_sql in (
                ("content_items", "provider TEXT"),
                ("content_items", "category TEXT"),
                ("content_items", "topic_id TEXT"),
                ("content_items", "source_count INTEGER DEFAULT 1"),
                ("content_items", "relevance_score INTEGER"),
                ("content_items", "raw_payload TEXT"),
                ("content_links", "link_score INTEGER"),
                ("content_links", "link_reason TEXT"),
                ("content_links", "topic_id TEXT"),
            ):
                column = column_sql.split()[0]
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")
                except Exception:
                    pass
                _ = column
        else:
            conn.execute("SELECT pg_advisory_xact_lock(hashtext('polydata_content_schema'))")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_items (
                    id TEXT PRIMARY KEY,
                    content_type TEXT,
                    provider TEXT,
                    source TEXT,
                    category TEXT,
                    topic_id TEXT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    published_at TEXT,
                    summary TEXT,
                    source_count INTEGER DEFAULT 1,
                    relevance_score INTEGER,
                    raw_payload TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS content_links (
                    id BIGSERIAL PRIMARY KEY,
                    content_id TEXT NOT NULL REFERENCES content_items(id) ON DELETE CASCADE,
                    market_id BIGINT NOT NULL,
                    event_slug TEXT,
                    category TEXT,
                    topic_id TEXT,
                    link_score INTEGER,
                    link_reason TEXT,
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(content_id, market_id)
                )
                """
            )
            for table, column_sql in (
                ("content_items", "provider TEXT"),
                ("content_items", "category TEXT"),
                ("content_items", "topic_id TEXT"),
                ("content_items", "source_count INTEGER DEFAULT 1"),
                ("content_items", "relevance_score INTEGER"),
                ("content_items", "raw_payload TEXT"),
                ("content_links", "link_score INTEGER"),
                ("content_links", "link_reason TEXT"),
                ("content_links", "topic_id TEXT"),
            ):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column_sql}")
            conn.execute(
                """
                DO $$
                DECLARE constraint_name text;
                BEGIN
                    SELECT conname INTO constraint_name
                    FROM pg_constraint
                    WHERE conrelid = 'content_items'::regclass
                      AND contype = 'u'
                      AND pg_get_constraintdef(oid) = 'UNIQUE (url)';
                    IF constraint_name IS NOT NULL THEN
                        EXECUTE format('ALTER TABLE content_items DROP CONSTRAINT %I', constraint_name);
                    END IF;
                END $$;
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_content_items_published_at ON content_items (published_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_content_items_topic_time ON content_items (topic_id, published_at DESC)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_content_items_topic_url ON content_items (COALESCE(topic_id, ''), url)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_content_links_market_score ON content_links (market_id, link_score DESC, created_at DESC)")
        conn.commit()
        backend_key = str(dependencies.get_backend() or "").lower()
        with dependencies.resources.content_lock:
            dependencies.resources.content_table_exists[(backend_key, "content_items")] = True
            dependencies.resources.content_table_exists[(backend_key, "content_links")] = True
            dependencies.resources.content_tables_ensured.add(backend_key)
    except Exception:
        conn.rollback()
        dependencies.application.logger.exception(
            "content table ensure failed",
        )
    finally:
        conn.close()


def get_content_market_by_id(ctx: Mapping[str, Any], market_id: int) -> Dict[str, Any] | None:
    """Only local question metadata is needed for content, never trading/Oracle joins."""
    storage = ContentStorageDependencies.from_context(ctx)
    return storage.query_one("SELECT * FROM markets WHERE id = ?", (market_id,)) or None


def get_related_content_by_market_id(
    ctx: Mapping[str, Any],
    market_id: int,
    limit: int = 8,
    days: int = 7,
    market: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    from api.services.free_content.snapshots import read_payload
    storage = ContentStorageDependencies.from_context(ctx)
    market = market if market is not None else get_content_market_by_id(storage, market_id)
    return read_payload(storage, ctx.get("free_content_cache") if isinstance(ctx, Mapping) else None,
                        market=market, market_id=market_id, limit=limit, days=days)


def get_latest_content_snapshot(
    ctx: Mapping[str, Any],
    limit: int = 8,
    days: int = 7,
) -> Dict[str, Any]:
    from api.services.free_content.snapshots import read_payload
    storage = ContentStorageDependencies.from_context(ctx)
    return read_payload(storage, ctx.get("free_content_cache") if isinstance(ctx, Mapping) else None,
                        limit=limit, days=days)
