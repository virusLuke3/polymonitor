#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polymarket 索引器数据库模块。

PostgreSQL 用于生产数据；SQLite 用于显式本地存储和离线运行。
保留两者共享的参数化查询和行读取接口。
"""

from __future__ import annotations

import os
import re
import sqlite3
import argparse
from dataclasses import dataclass, field
from types import MappingProxyType
from collections.abc import Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import psycopg
except ImportError:
    psycopg = None

DEFAULT_SQLITE_PATH = "/data/hy/myPolyDB/polymarket_indexer.db"
DEFAULT_DB_PATH = DEFAULT_SQLITE_PATH
# Explicit CLI overrides only. Environment values are read at configuration time.
_runtime_overrides: Dict[str, Any] = {}

_NAMED_PARAM_RE = re.compile(r":([a-zA-Z_][a-zA-Z0-9_]*)")


def get_backend() -> str:
    return str(_runtime_overrides.get("backend") or os.environ.get("POLYMARKET_DB_BACKEND", "postgres")).strip().lower()


def get_sqlite_path() -> str:
    return str(
        _runtime_overrides.get("sqlite_path")
        or os.environ.get("POLYMARKET_SQLITE_PATH")
        or os.environ.get("POLYMARKET_DB")
        or DEFAULT_SQLITE_PATH
    )


def get_postgres_settings() -> Dict[str, Any]:
    defaults = {
        "host": "127.0.0.1",
        "port": 45432,
        "user": "poly_user",
        "password": "",
        "database": "poly_data_core",
        "search_path": "core,oracle,ops,public",
        "connect_timeout": 5,
        "statement_timeout_ms": 15000,
        "lock_timeout_ms": 3000,
        "idle_in_transaction_session_timeout_ms": 30000,
        "tcp_user_timeout_ms": 20000,
    }
    settings = {}
    for name, default in defaults.items():
        key = name.upper()
        aliases = [f"POLYDATA_POSTGRES_{key}", f"POLYMARKET_POSTGRES_{key}", f"POLYMARKET_PostgreSQL_{key}"]
        if name == "password":
            aliases.insert(2, "POLYMARKET_POSTGRESQL_PASSWORD")
        settings[name] = _runtime_overrides.get(
            "postgres_" + name, next((os.environ[key] for key in aliases if os.environ.get(key)), default)
        )
    settings["port"] = int(settings["port"])
    for name in defaults:
        if "timeout" in name:
            settings[name] = int(settings[name])
            if settings[name] <= 0:
                raise ValueError(f"PostgreSQL {name} must be positive")
    return settings


@dataclass(frozen=True)
class DatabaseSettings:
    backend: str
    sqlite_path: str
    connection: Mapping[str, Any] = field(repr=False)

    @classmethod
    def from_environment(cls):
        backend = get_backend()
        settings = get_postgres_settings() if backend in {"postgres", "postgresql"} else {}
        return cls(backend, get_sqlite_path(), MappingProxyType(settings))

    def connect(self, db_path=None, *, readonly=False, connect_timeout=None):
        if self.backend in {"postgres", "postgresql"}:
            return get_postgres_connection(self.connection, connect_timeout=connect_timeout)
        if self.backend == "sqlite":
            return get_sqlite_connection(db_path or self.sqlite_path, readonly=readonly)
        raise ValueError(f"Unsupported database backend: {self.backend}")

    def describe(self) -> str:
        if self.backend == "sqlite":
            return f"sqlite:{Path(self.sqlite_path).expanduser()}"
        settings = self.connection
        return f"{self.backend}:{settings['user']}@{settings['host']}:{settings['port']}/{settings['database']}"


def configure_runtime_db(
    *,
    backend=None,
    sqlite_path=None,
    postgres_host=None,
    postgres_port=None,
    postgres_user=None,
    postgres_password=None,
    postgres_database=None,
    postgres_search_path=None,
) -> None:
    _runtime_overrides.update({name: value for name, value in locals().items() if value is not None})


def add_db_cli_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--backend", choices=["sqlite", "postgres", "postgresql"], default=get_backend())
    parser.add_argument("--sqlite-path", default=get_sqlite_path())
    for name, value in get_postgres_settings().items():
        if name == "password":
            continue
        parser.add_argument(
            f"--postgres-{name.replace('_', '-')}", default=value, type=int if name == "port" else str
        )


def configure_db_from_args(args: argparse.Namespace) -> None:
    configure_runtime_db(
        backend=getattr(args, "backend", None),
        sqlite_path=getattr(args, "sqlite_path", None),
        postgres_host=getattr(args, "postgres_host", None),
        postgres_port=getattr(args, "postgres_port", None),
        postgres_user=getattr(args, "postgres_user", None),
        postgres_password=None,
        postgres_database=getattr(args, "postgres_database", None),
        postgres_search_path=getattr(args, "postgres_search_path", None),
    )


def describe_db_target() -> str:
    backend = get_backend()
    if backend == "sqlite":
        return f"sqlite:{Path(get_sqlite_path()).expanduser()}"
    if backend in {"postgres", "postgresql"}:
        settings = get_postgres_settings()
        return f"postgres:{settings['user']}@{settings['host']}:{settings['port']}/{settings['database']}"
    return f"unsupported:{backend}"


def is_postgres_backend() -> bool:
    return get_backend() in {"postgres", "postgresql"}


class DBRow:
    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        self._columns = list(columns)
        self._values = tuple(values)
        self._index = {name: idx for idx, name in enumerate(self._columns)}

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def get(self, key: str, default: Any = None) -> Any:
        return self._values[self._index[key]] if key in self._index else default

    def keys(self) -> List[str]:
        return list(self._columns)

    def as_dict(self) -> Dict[str, Any]:
        return {name: self._values[idx] for idx, name in enumerate(self._columns)}


class PostgresCursorWrapper:
    def __init__(self, connection: "PostgresConnectionWrapper", cursor) -> None:
        self._connection = connection
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def description(self):
        return self._cursor.description

    def execute(self, query: str, params: Optional[Any] = None):
        sql, bound = adapt_sql_for_postgres(query, params)
        result = self._cursor.execute(sql, bound)
        self._connection._bump_changes(self._cursor.rowcount)
        return result

    def executemany(self, query: str, seq_of_params: Iterable[Any]):
        bound_many = list(seq_of_params)
        if not bound_many:
            return 0
        sql, sample = adapt_sql_for_postgres(query, bound_many[0])
        if sample is None:
            raise RuntimeError("unexpected missing bound parameters while adapting executemany")
        bound_many = [adapt_params_for_postgres(query, item) for item in bound_many]
        result = self._cursor.executemany(sql, bound_many)
        self._connection._bump_changes(self._cursor.rowcount)
        return result

    def fetchone(self):
        row = self._cursor.fetchone()
        return wrap_db_row(self._cursor.description, row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [wrap_db_row(self._cursor.description, row) for row in rows]

    def close(self) -> None:
        self._cursor.close()


class PostgresConnectionWrapper:
    def __init__(self, pg_conn) -> None:
        self._pg_conn = pg_conn
        self.total_changes = 0
        self.row_factory = DBRow

    def _bump_changes(self, rowcount: int) -> None:
        if rowcount and rowcount > 0:
            self.total_changes += rowcount

    def cursor(self) -> PostgresCursorWrapper:
        return PostgresCursorWrapper(self, self._pg_conn.cursor())

    def execute(self, query: str, params: Optional[Any] = None):
        cur = self.cursor()
        cur.execute(query, params)
        return cur

    def executemany(self, query: str, seq_of_params: Iterable[Any]):
        cur = self.cursor()
        cur.executemany(query, seq_of_params)
        return cur

    def commit(self) -> None:
        self._pg_conn.commit()

    def rollback(self) -> None:
        self._pg_conn.rollback()

    def close(self) -> None:
        self._pg_conn.close()


def wrap_db_row(description, row):
    if row is None:
        return None
    columns = [col[0] for col in description] if description else []
    return DBRow(columns, row)


def adapt_params_for_postgres(query: str, params: Optional[Any]) -> Any:
    if params is None:
        return None
    if isinstance(params, dict):
        return params
    if isinstance(params, tuple):
        return params
    if isinstance(params, list):
        return tuple(params)
    return (params,)


def _replace_insert_or_replace_for_postgres(sql: str) -> str:
    match = re.match(
        r"INSERT\s+OR\s+REPLACE\s+INTO\s+sync_state\s*\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
    columns = [part.strip().strip('"') for part in match.group(1).split(",")]
    update_columns = [col for col in columns if col != "key"]
    updates = ", ".join(f"{col} = EXCLUDED.{col}" for col in update_columns)
    return (
        re.sub(r"INSERT\s+OR\s+REPLACE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
        + f" ON CONFLICT (key) DO UPDATE SET {updates}"
    )


def adapt_sql_for_postgres(query: str, params: Optional[Any]) -> Tuple[str, Optional[Any]]:
    sql = query.strip()
    sql = sql.replace("`", '"')
    sql = sql.replace(" COLLATE NOCASE", "")
    sql = re.sub(r"INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.IGNORECASE)
    if re.search(r"INSERT\s+OR\s+REPLACE\s+INTO", sql, flags=re.IGNORECASE):
        sql = _replace_insert_or_replace_for_postgres(sql)
    if isinstance(params, dict):
        sql = _NAMED_PARAM_RE.sub(r"%(\1)s", sql)
        return sql, params
    if params is not None:
        return sql.replace("?", "%s"), adapt_params_for_postgres(query, params)
    return sql.replace("?", "%s"), None


def get_sqlite_connection(db_path: str = DEFAULT_DB_PATH, readonly: bool = False) -> sqlite3.Connection:
    parent = Path(db_path).expanduser().resolve().parent
    parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        uri = f"file:{Path(db_path).expanduser().resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
    else:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
    conn.row_factory = sqlite3.Row
    return conn


def get_postgres_connection(
    settings: Optional[Mapping[str, Any]] = None, *, connect_timeout: int | None = None
) -> PostgresConnectionWrapper:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Please install psycopg[binary] first.")
    settings = settings if settings is not None else get_postgres_settings()
    timeout = int(settings.get("connect_timeout", 5))
    if connect_timeout is not None:
        timeout = min(timeout, connect_timeout)
    limits = {
        name: int(settings.get(name + "_ms", default))
        for name, default in (
            ("statement_timeout", 15000), ("lock_timeout", 3000),
            ("idle_in_transaction_session_timeout", 30000),
        )
    }
    tcp_timeout = int(settings.get("tcp_user_timeout_ms", 20000))
    if min(timeout, tcp_timeout, *limits.values()) <= 0:
        raise ValueError("PostgreSQL timeouts must be positive")
    raw = psycopg.connect(
        host=settings["host"],
        port=settings["port"],
        user=settings["user"],
        password=settings["password"],
        dbname=settings["database"],
        autocommit=False,
        connect_timeout=timeout,
        tcp_user_timeout=tcp_timeout,
        options=" ".join(f"-c {name}={value}" for name, value in limits.items()),
    )
    search_path = str(settings.get("search_path") or "").strip()
    if search_path:
        with raw.cursor() as cur:
            cur.execute("SET search_path TO " + search_path)
    return PostgresConnectionWrapper(raw)


def get_connection(
    db_path: Optional[str] = None,
    *,
    backend: Optional[str] = None,
    readonly: bool = False,
):
    chosen = (backend or get_backend()).strip().lower()
    if chosen == "sqlite":
        return get_sqlite_connection(db_path or get_sqlite_path(), readonly=readonly)
    if chosen in {"postgres", "postgresql"}:
        return get_postgres_connection()
    raise ValueError(f"Unsupported database backend: {chosen}")


@contextmanager
def get_db(db_path: Optional[str] = None, *, backend: Optional[str] = None, readonly: bool = False):
    conn = get_connection(db_path, backend=backend, readonly=readonly)
    try:
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        conn.close()


def get_table_columns(conn, table: str) -> List[str]:
    if isinstance(conn, sqlite3.Connection):
        cur = conn.execute(f"PRAGMA table_info({table})")
        return [row[1] for row in cur.fetchall()]
    if isinstance(conn, PostgresConnectionWrapper):
        if "." in table:
            schema, table_name = table.split(".", 1)
            params = (schema, table_name)
            schema_filter = "table_schema = %s"
        else:
            table_name = table
            params = (table_name,)
            schema_filter = "table_schema IN ('core', 'oracle', 'ops', 'public')"
        cur = conn.execute(
            f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE {schema_filter} AND table_name = %s
            ORDER BY ordinal_position
            """,
            params,
        )
        return [row[0] for row in cur.fetchall()]

    raise TypeError("Unsupported database connection")


def table_exists(conn, table: str) -> bool:
    return bool(get_table_columns(conn, table))


def create_index_if_not_exists(conn, table: str, index_name: str, columns: Sequence[str], unique: bool = False) -> None:
    unique_sql = "UNIQUE " if unique else ""
    conn.execute(f"CREATE {unique_sql}INDEX IF NOT EXISTS {index_name} ON {table}({', '.join(columns)})")


def ensure_column_exists(conn, table: str, column: str, column_type: str) -> None:
    if column in get_table_columns(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def _init_postgres_schema(conn: PostgresConnectionWrapper) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS core")
    conn.execute("CREATE SCHEMA IF NOT EXISTS oracle")
    conn.execute("CREATE SCHEMA IF NOT EXISTS ops")
    conn.execute("CREATE SEQUENCE IF NOT EXISTS core.markets_id_seq")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.markets (
            id BIGINT PRIMARY KEY DEFAULT nextval('core.markets_id_seq'),
            identity_kind TEXT NOT NULL DEFAULT 'canonical_gamma'
                CHECK (identity_kind IN ('canonical_gamma', 'protocol_structural')),
            gamma_market_id TEXT,
            event_id TEXT,
            event_slug TEXT,
            event_title TEXT,
            slug TEXT NOT NULL,
            condition_id TEXT NOT NULL UNIQUE,
            question_id TEXT,
            oracle TEXT,
            yes_token_id TEXT NOT NULL,
            no_token_id TEXT NOT NULL,
            title TEXT,
            description TEXT,
            enable_neg_risk BOOLEAN NOT NULL DEFAULT FALSE,
            end_date TIMESTAMPTZ,
            raw_end_date TEXT,
            created_at TIMESTAMPTZ,
            raw_created_at TEXT,
            category TEXT,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            clob_token_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
            migrated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for col, col_type in (
        ("event_id", "TEXT"),
        ("event_slug", "TEXT"),
        ("event_title", "TEXT"),
    ):
        ensure_column_exists(conn, "core.markets", col, col_type)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.market_status_snapshot (
            market_id BIGINT PRIMARY KEY REFERENCES core.markets(id),
            has_settle BOOLEAN NOT NULL DEFAULT FALSE,
            has_propose BOOLEAN NOT NULL DEFAULT FALSE,
            has_dispute BOOLEAN NOT NULL DEFAULT FALSE,
            settlement_code SMALLINT NOT NULL DEFAULT 0 CHECK (settlement_code IN (0, 1, 2, 3)),
            settlement_outcome TEXT NOT NULL DEFAULT 'UNKNOWN',
            settlement_source TEXT,
            settlement_raw TEXT,
            settlement_event_id BIGINT,
            settlement_event_time TIMESTAMPTZ,
            settlement_transaction TEXT,
            is_trading_closed BOOLEAN NOT NULL DEFAULT FALSE,
            is_resolved BOOLEAN NOT NULL DEFAULT FALSE,
            is_final BOOLEAN NOT NULL DEFAULT FALSE,
            completion_status TEXT NOT NULL DEFAULT 'OPEN',
            completion_source TEXT,
            completion_time TIMESTAMPTZ,
            gamma_closed BOOLEAN NOT NULL DEFAULT FALSE,
            gamma_closed_time TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for col, col_type in (
        ("has_dispute", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("settlement_code", "SMALLINT NOT NULL DEFAULT 0"),
        ("settlement_outcome", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
        ("settlement_source", "TEXT"),
        ("settlement_raw", "TEXT"),
        ("settlement_event_id", "BIGINT"),
        ("settlement_event_time", "TIMESTAMPTZ"),
        ("settlement_transaction", "TEXT"),
        ("is_trading_closed", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("is_resolved", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("is_final", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("completion_status", "TEXT NOT NULL DEFAULT 'OPEN'"),
        ("completion_source", "TEXT"),
        ("completion_time", "TIMESTAMPTZ"),
        ("gamma_closed", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("gamma_closed_time", "TIMESTAMPTZ"),
    ):
        ensure_column_exists(conn, "core.market_status_snapshot", col, col_type)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.market_resolution_fast (
            market_id BIGINT PRIMARY KEY REFERENCES core.markets(id),
            settlement_code SMALLINT NOT NULL CHECK (settlement_code IN (0, 1, 2, 3)),
            condition_id TEXT,
            slug TEXT,
            closed_time TIMESTAMPTZ,
            updated_at TIMESTAMPTZ
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.market_tokens (
            id BIGINT PRIMARY KEY,
            market_id BIGINT NOT NULL REFERENCES core.markets(id),
            condition_id TEXT NOT NULL,
            token_id TEXT NOT NULL UNIQUE,
            outcome TEXT NOT NULL,
            outcome_index INTEGER NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            end_date TIMESTAMPTZ,
            raw_end_date TEXT,
            created_at TIMESTAMPTZ,
            raw_created_at TEXT,
            updated_at TIMESTAMPTZ,
            raw_updated_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ops.sync_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            last_block BIGINT,
            updated_at TIMESTAMPTZ
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.market_trade_daily_stats (
            trade_date DATE NOT NULL,
            market_id BIGINT NOT NULL REFERENCES core.markets(id),
            trade_count BIGINT NOT NULL DEFAULT 0,
            volume_notional NUMERIC(38, 18) NOT NULL DEFAULT 0,
            last_trade_at TIMESTAMPTZ,
            last_block_number BIGINT,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (trade_date, market_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.market_latest_prices (
            market_id BIGINT PRIMARY KEY REFERENCES core.markets(id),
            latest_trade_at TIMESTAMPTZ,
            latest_trade_block BIGINT,
            latest_trade_log_index BIGINT,
            latest_price NUMERIC(20, 10),
            latest_yes_trade_at TIMESTAMPTZ,
            latest_yes_trade_block BIGINT,
            latest_yes_trade_log_index BIGINT,
            latest_yes_price NUMERIC(20, 10),
            latest_no_trade_at TIMESTAMPTZ,
            latest_no_trade_block BIGINT,
            latest_no_trade_log_index BIGINT,
            latest_no_price NUMERIC(20, 10),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.market_list_serving (
            market_id BIGINT PRIMARY KEY REFERENCES core.markets(id),
            latest_price NUMERIC(20, 10),
            latest_trade_at TIMESTAMPTZ,
            price_24h_ago NUMERIC(20, 10),
            trade_count_24h BIGINT NOT NULL DEFAULT 0,
            volume_24h NUMERIC(38, 18) NOT NULL DEFAULT 0,
            last_trade_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    ensure_column_exists(conn, "core.market_list_serving", "price_24h_ago", "NUMERIC(20, 10)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.market_chart_serving (
            market_id BIGINT NOT NULL REFERENCES core.markets(id) ON DELETE CASCADE,
            range_name TEXT NOT NULL,
            interval_name TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'probability',
            history_status TEXT NOT NULL DEFAULT 'missing',
            point_count INTEGER NOT NULL DEFAULT 0,
            points JSONB NOT NULL DEFAULT '[]'::jsonb,
            source TEXT NOT NULL DEFAULT 'postgres',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (market_id, range_name, interval_name)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.market_workspace_serving (
            market_id BIGINT PRIMARY KEY REFERENCES core.markets(id) ON DELETE CASCADE,
            detail_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            price_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            oracle_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            content_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            source TEXT NOT NULL DEFAULT 'postgres',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS core.event_market_serving (
            serving_key TEXT PRIMARY KEY,
            group_id TEXT NOT NULL UNIQUE,
            event_id TEXT,
            event_slug TEXT,
            event_title TEXT,
            title TEXT NOT NULL,
            category TEXT,
            tags JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ,
            end_date TIMESTAMPTZ,
            volume_24h NUMERIC(38, 18) NOT NULL DEFAULT 0,
            gamma_volume_24h NUMERIC(38, 18),
            gamma_volume_updated_at TIMESTAMPTZ,
            gamma_volume_fetched_at TIMESTAMPTZ,
            trade_count_24h BIGINT NOT NULL DEFAULT 0,
            last_activity_at TIMESTAMPTZ,
            outcome_count INTEGER NOT NULL DEFAULT 0,
            default_market_id BIGINT REFERENCES core.markets(id) ON DELETE SET NULL,
            default_condition_id TEXT,
            default_gamma_market_id TEXT,
            default_outcome_key TEXT,
            top_outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
            outcomes JSONB NOT NULL DEFAULT '[]'::jsonb,
            completion_status TEXT NOT NULL DEFAULT 'OPEN',
            is_trading_closed BOOLEAN NOT NULL DEFAULT FALSE,
            active_rank DOUBLE PRECISION NOT NULL DEFAULT 0,
            source TEXT NOT NULL DEFAULT 'postgres',
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    for col, col_type in (
        ("gamma_volume_24h", "NUMERIC(38, 18)"),
        ("gamma_volume_updated_at", "TIMESTAMPTZ"),
        ("gamma_volume_fetched_at", "TIMESTAMPTZ"),
    ):
        ensure_column_exists(conn, "core.event_market_serving", col, col_type)
    for table, index_name, cols in (
        ("core.markets", "idx_markets_gamma_market_id", ["gamma_market_id"]),
        ("core.markets", "idx_markets_event_id", ["event_id"]),
        ("core.markets", "idx_markets_event_slug", ["event_slug"]),
        ("core.markets", "idx_markets_slug", ["slug"]),
        ("core.markets", "idx_markets_question_id", ["question_id"]),
        ("core.markets", "idx_markets_yes_token_id", ["yes_token_id"]),
        ("core.markets", "idx_markets_no_token_id", ["no_token_id"]),
        ("core.markets", "idx_markets_end_date", ["end_date"]),
        ("core.markets", "idx_markets_created_at", ["created_at"]),
        ("core.market_status_snapshot", "idx_market_status_snapshot_flags", ["has_settle", "has_propose", "market_id"]),
        (
            "core.market_status_snapshot",
            "idx_market_status_snapshot_lifecycle_flags",
            ["has_settle", "has_propose", "has_dispute", "market_id"],
        ),
        ("core.market_status_snapshot", "idx_market_status_snapshot_settlement_code", ["settlement_code"]),
        (
            "core.market_status_snapshot",
            "idx_market_status_snapshot_completion_status",
            ["completion_status", "market_id"],
        ),
        (
            "core.market_status_snapshot",
            "idx_market_status_snapshot_completion_flags",
            ["is_final", "is_resolved", "is_trading_closed", "market_id"],
        ),
        ("core.market_status_snapshot", "idx_market_status_snapshot_completion_time", ["completion_time"]),
        (
            "core.market_status_snapshot",
            "idx_market_status_snapshot_gamma_closed",
            ["gamma_closed", "gamma_closed_time"],
        ),
        ("core.market_resolution_fast", "idx_mrf_settlement_code", ["settlement_code"]),
        ("core.market_resolution_fast", "idx_mrf_condition_id", ["condition_id"]),
        ("core.market_resolution_fast", "idx_mrf_slug", ["slug"]),
        ("core.market_resolution_fast", "idx_mrf_closed_time", ["closed_time"]),
        ("core.market_trade_daily_stats", "idx_market_trade_daily_stats_market_date", ["market_id", "trade_date"]),
        ("core.market_trade_daily_stats", "idx_market_trade_daily_stats_last_trade_at", ["last_trade_at"]),
        ("core.market_latest_prices", "idx_market_latest_prices_latest_trade_at", ["latest_trade_at"]),
        (
            "core.market_list_serving",
            "idx_market_list_serving_activity",
            ["volume_24h", "trade_count_24h", "last_trade_at"],
        ),
        ("core.market_list_serving", "idx_market_list_serving_latest_trade_at", ["latest_trade_at"]),
        ("core.market_chart_serving", "idx_market_chart_serving_updated", ["updated_at"]),
        ("core.market_chart_serving", "idx_market_chart_serving_status", ["history_status", "updated_at"]),
        ("core.market_workspace_serving", "idx_market_workspace_serving_updated", ["updated_at"]),
        ("core.event_market_serving", "idx_event_market_serving_event_default", ["event_id", "default_market_id"]),
    ):
        create_index_if_not_exists(conn, table, index_name, cols)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_markets_tags_gin ON core.markets USING GIN (tags)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_markets_clob_token_ids_gin ON core.markets USING GIN (clob_token_ids)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_markets_category_lower ON core.markets (lower(category))")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_markets_created_id_desc ON core.markets (created_at DESC NULLS LAST, id DESC)"
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_status_snapshot_open_market_id
          ON core.market_status_snapshot (market_id)
          WHERE has_settle = FALSE
            AND has_propose = FALSE
            AND is_trading_closed = FALSE
            AND settlement_code = 0
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_list_serving_volume_activity_desc
          ON core.market_list_serving (volume_24h DESC, trade_count_24h DESC, last_trade_at DESC, market_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_market_list_serving_recent_trade_desc
          ON core.market_list_serving (last_trade_at DESC NULLS LAST, latest_trade_at DESC NULLS LAST, market_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_event_market_serving_active_desc
          ON core.event_market_serving (volume_24h DESC, last_activity_at DESC NULLS LAST, serving_key)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_event_market_serving_status_active_desc
          ON core.event_market_serving (completion_status, is_trading_closed, volume_24h DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_event_market_serving_rank_desc
          ON core.event_market_serving (active_rank DESC, volume_24h DESC, last_activity_at DESC NULLS LAST)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_markets_search_text_simple_gin
          ON core.markets USING GIN (
            to_tsvector(
              'simple',
              (((coalesce(title, '') || ' ') || coalesce(slug, '')) || ' ') || coalesce(category, '')
            )
          )
        """
    )
    _ensure_postgres_trade_indexes(conn)
    _ensure_postgres_oracle_indexes(conn)


def _ensure_postgres_trade_indexes(conn: PostgresConnectionWrapper) -> None:
    for table in ("core.trades_v2", "core.trades"):
        row = conn.execute("SELECT to_regclass(?)", (table,)).fetchone()
        if not row or not row[0]:
            continue
        columns = get_table_columns(conn, table)
        table_suffix = table.rsplit(".", 1)[-1]
        if "market_id" in columns and "block_time" in columns:
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table_suffix}_market_time_desc
                  ON {table} (market_id, block_time DESC NULLS LAST, block_number DESC NULLS LAST, log_index DESC NULLS LAST)
                """
            )
        if "market_id" in columns and "timestamp" in columns:
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table_suffix}_market_timestamp_desc
                  ON {table} (market_id, timestamp DESC NULLS LAST, block_number DESC NULLS LAST, log_index DESC NULLS LAST)
                """
            )


def _ensure_postgres_oracle_indexes(conn: PostgresConnectionWrapper) -> None:
    row = conn.execute("SELECT to_regclass('oracle.oracle_events')").fetchone()
    if not row or not row[0]:
        return
    for table, index_name, cols in (
        ("oracle.oracle_events", "idx_oracle_events_market_block_id", ["market_id", "block_number", "id"]),
        (
            "oracle.oracle_events",
            "idx_oracle_events_external_market_block_id",
            ["external_market_id", "block_number", "id"],
        ),
        ("oracle.oracle_events", "idx_oracle_events_question_block_id", ["question_id", "block_number", "id"]),
        ("oracle.oracle_events", "idx_oracle_events_condition_block_id", ["condition_id", "block_number", "id"]),
    ):
        create_index_if_not_exists(conn, table, index_name, cols)


def init_schema(conn=None, db_path: str = DEFAULT_DB_PATH) -> None:
    close_after = False
    if conn is None:
        conn = get_connection(db_path)
        close_after = True

    try:
        if isinstance(conn, sqlite3.Connection):
            _init_sqlite_schema(conn)
        elif isinstance(conn, PostgresConnectionWrapper):
            _init_postgres_schema(conn)
        else:
            raise TypeError("Unsupported database connection")
        conn.commit()
    finally:
        if close_after:
            conn.close()


def _init_sqlite_schema(conn: sqlite3.Connection) -> None:
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS markets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            identity_kind TEXT NOT NULL DEFAULT 'canonical_gamma'
                CHECK (identity_kind IN ('canonical_gamma', 'protocol_structural')),
            gamma_market_id TEXT,
            slug TEXT NOT NULL UNIQUE,
            condition_id TEXT NOT NULL UNIQUE,
            question_id TEXT,
            oracle TEXT,
            yes_token_id TEXT NOT NULL,
            no_token_id TEXT NOT NULL,
            title TEXT,
            description TEXT,
            enable_neg_risk INTEGER DEFAULT 0,
            end_date TEXT,
            created_at TEXT,
            category TEXT,
            tags TEXT,
            clob_token_ids TEXT
        )
        """
    )
    for col, col_type in (
        ("identity_kind", "TEXT NOT NULL DEFAULT 'canonical_gamma'"),
        ("gamma_market_id", "TEXT"),
        ("category", "TEXT"),
        ("tags", "TEXT"),
        ("clob_token_ids", "TEXT"),
    ):
        try:
            cursor.execute(f"ALTER TABLE markets ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_hash TEXT NOT NULL,
            log_index INTEGER NOT NULL,
            market_id INTEGER NOT NULL,
            maker TEXT NOT NULL,
            taker TEXT NOT NULL,
            price TEXT NOT NULL,
            size TEXT NOT NULL,
            side TEXT NOT NULL,
            outcome TEXT,
            token_id TEXT NOT NULL,
            block_number INTEGER,
            timestamp TEXT,
            order_hash TEXT,
            maker_asset_id TEXT,
            taker_asset_id TEXT,
            maker_amount INTEGER,
            taker_amount INTEGER,
            fee INTEGER,
            contract TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (market_id) REFERENCES markets(id),
            UNIQUE(tx_hash, log_index)
        )
        """
    )
    for col, col_type in (
        ("order_hash", "TEXT"),
        ("maker_asset_id", "TEXT"),
        ("taker_asset_id", "TEXT"),
        ("maker_amount", "INTEGER"),
        ("taker_amount", "INTEGER"),
        ("fee", "INTEGER"),
        ("contract", "TEXT"),
    ):
        try:
            cursor.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS block_timestamps (
            block_number INTEGER PRIMARY KEY,
            timestamp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sync_state (
            key TEXT PRIMARY KEY,
            value TEXT,
            last_block INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS market_trade_daily_stats (
            trade_date TEXT NOT NULL,
            market_id INTEGER NOT NULL,
            trade_count INTEGER NOT NULL DEFAULT 0,
            volume_notional REAL NOT NULL DEFAULT 0,
            last_trade_at TEXT,
            last_block_number INTEGER,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, market_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS market_latest_prices (
            market_id INTEGER PRIMARY KEY,
            latest_trade_at TEXT,
            latest_trade_block INTEGER,
            latest_trade_log_index INTEGER,
            latest_price REAL,
            latest_yes_trade_at TEXT,
            latest_yes_trade_block INTEGER,
            latest_yes_trade_log_index INTEGER,
            latest_yes_price REAL,
            latest_no_trade_at TEXT,
            latest_no_trade_block INTEGER,
            latest_no_trade_log_index INTEGER,
            latest_no_price REAL,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS market_status_snapshot (
            market_id INTEGER PRIMARY KEY,
            has_settle INTEGER NOT NULL DEFAULT 0,
            has_propose INTEGER NOT NULL DEFAULT 0,
            has_dispute INTEGER NOT NULL DEFAULT 0,
            settlement_code INTEGER NOT NULL DEFAULT 0,
            settlement_outcome TEXT NOT NULL DEFAULT 'UNKNOWN',
            settlement_source TEXT,
            settlement_raw TEXT,
            settlement_event_id INTEGER,
            settlement_event_time TEXT,
            settlement_transaction TEXT,
            is_trading_closed INTEGER NOT NULL DEFAULT 0,
            is_resolved INTEGER NOT NULL DEFAULT 0,
            is_final INTEGER NOT NULL DEFAULT 0,
            completion_status TEXT NOT NULL DEFAULT 'OPEN',
            completion_source TEXT,
            completion_time TEXT,
            gamma_closed INTEGER NOT NULL DEFAULT 0,
            gamma_closed_time TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for col, col_type in (
        ("has_dispute", "INTEGER NOT NULL DEFAULT 0"),
        ("settlement_code", "INTEGER NOT NULL DEFAULT 0"),
        ("settlement_outcome", "TEXT NOT NULL DEFAULT 'UNKNOWN'"),
        ("settlement_source", "TEXT"),
        ("settlement_raw", "TEXT"),
        ("settlement_event_id", "INTEGER"),
        ("settlement_event_time", "TEXT"),
        ("settlement_transaction", "TEXT"),
        ("is_trading_closed", "INTEGER NOT NULL DEFAULT 0"),
        ("is_resolved", "INTEGER NOT NULL DEFAULT 0"),
        ("is_final", "INTEGER NOT NULL DEFAULT 0"),
        ("completion_status", "TEXT NOT NULL DEFAULT 'OPEN'"),
        ("completion_source", "TEXT"),
        ("completion_time", "TEXT"),
        ("gamma_closed", "INTEGER NOT NULL DEFAULT 0"),
        ("gamma_closed_time", "TEXT"),
    ):
        try:
            cursor.execute(f"ALTER TABLE market_status_snapshot ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS market_list_serving (
            market_id INTEGER PRIMARY KEY,
            latest_price REAL,
            latest_trade_at TEXT,
            price_24h_ago REAL,
            trade_count_24h INTEGER NOT NULL DEFAULT 0,
            volume_24h REAL NOT NULL DEFAULT 0,
            last_trade_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    try:
        cursor.execute("ALTER TABLE market_list_serving ADD COLUMN price_24h_ago REAL")
    except sqlite3.OperationalError as e:
        if "duplicate column name" not in str(e).lower():
            raise
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS trade_addresses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trade_id INTEGER,
            tx_hash TEXT NOT NULL,
            log_index INTEGER NOT NULL,
            market_id INTEGER NOT NULL,
            token_id TEXT NOT NULL,
            outcome TEXT,
            address TEXT NOT NULL,
            role TEXT NOT NULL,
            side_for_address TEXT NOT NULL,
            price REAL NOT NULL,
            size REAL NOT NULL,
            notional REAL NOT NULL,
            fee_amount REAL NOT NULL DEFAULT 0,
            block_number INTEGER,
            trade_time TEXT,
            trade_date TEXT,
            contract TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(tx_hash, log_index, address)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS address_trade_daily_stats (
            trade_date TEXT NOT NULL,
            address TEXT NOT NULL,
            trade_count INTEGER NOT NULL DEFAULT 0,
            buy_count INTEGER NOT NULL DEFAULT 0,
            sell_count INTEGER NOT NULL DEFAULT 0,
            volume_notional REAL NOT NULL DEFAULT 0,
            last_trade_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (trade_date, address)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS address_trade_totals (
            address TEXT PRIMARY KEY,
            total_trade_count INTEGER NOT NULL DEFAULT 0,
            total_buy_count INTEGER NOT NULL DEFAULT 0,
            total_sell_count INTEGER NOT NULL DEFAULT 0,
            total_volume_notional REAL NOT NULL DEFAULT 0,
            first_trade_at TEXT,
            last_trade_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS address_market_stats (
            address TEXT NOT NULL,
            market_id INTEGER NOT NULL,
            trade_count INTEGER NOT NULL DEFAULT 0,
            buy_count INTEGER NOT NULL DEFAULT 0,
            sell_count INTEGER NOT NULL DEFAULT 0,
            volume_notional REAL NOT NULL DEFAULT 0,
            first_trade_at TEXT,
            last_trade_at TEXT,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (address, market_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS uma_adapter_mapping (
            ancillary_data TEXT PRIMARY KEY,
            question_id TEXT NOT NULL,
            source_adapter TEXT
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS neg_risk_request_mapping (
            request_id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL,
            market_id TEXT,
            source_operator TEXT
        )
        """
    )
    for col, col_type in (
        ("market_id", "TEXT"),
        ("source_operator", "TEXT"),
    ):
        try:
            cursor.execute(f"ALTER TABLE neg_risk_request_mapping ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS oracle_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_hash TEXT NOT NULL,
            log_index INTEGER NOT NULL,
            block_number INTEGER NOT NULL,
            event_time TEXT,
            event_status TEXT NOT NULL,
            external_market_id TEXT,
            market_id INTEGER,
            market_title TEXT,
            source_adapter TEXT,
            source_oracle TEXT,
            adapter_question_id TEXT,
            matched_by TEXT,
            question_id TEXT,
            condition_id TEXT,
            string_raw TEXT,
            p1 TEXT,
            p2 TEXT,
            proposed_price TEXT,
            settled_price TEXT,
            settlement_recipient TEXT,
            payout TEXT,
            requester TEXT,
            proposer TEXT,
            disputer TEXT,
            request_transaction TEXT,
            proposal_transaction TEXT,
            settlement_transaction TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (market_id) REFERENCES markets(id),
            UNIQUE(tx_hash, log_index)
        )
        """
    )
    for table, index_name, cols in (
        ("markets", "idx_markets_condition_id", ["condition_id"]),
        ("markets", "idx_markets_gamma_market_id", ["gamma_market_id"]),
        ("markets", "idx_markets_yes_token", ["yes_token_id"]),
        ("markets", "idx_markets_no_token", ["no_token_id"]),
        ("trades", "idx_trades_market_id", ["market_id"]),
        ("trades", "idx_trades_timestamp", ["timestamp"]),
        ("trades", "idx_trades_block", ["block_number"]),
        ("market_trade_daily_stats", "idx_market_trade_daily_stats_market_date", ["market_id", "trade_date"]),
        ("market_trade_daily_stats", "idx_market_trade_daily_stats_last_trade_at", ["last_trade_at"]),
        ("market_latest_prices", "idx_market_latest_prices_latest_trade_at", ["latest_trade_at"]),
        ("market_status_snapshot", "idx_market_status_snapshot_flags", ["has_settle", "has_propose", "market_id"]),
        (
            "market_status_snapshot",
            "idx_market_status_snapshot_lifecycle_flags",
            ["has_settle", "has_propose", "has_dispute", "market_id"],
        ),
        ("market_status_snapshot", "idx_market_status_snapshot_settlement_code", ["settlement_code"]),
        ("market_status_snapshot", "idx_market_status_snapshot_completion_status", ["completion_status", "market_id"]),
        (
            "market_status_snapshot",
            "idx_market_status_snapshot_completion_flags",
            ["is_final", "is_resolved", "is_trading_closed", "market_id"],
        ),
        ("market_status_snapshot", "idx_market_status_snapshot_completion_time", ["completion_time"]),
        ("market_status_snapshot", "idx_market_status_snapshot_gamma_closed", ["gamma_closed", "gamma_closed_time"]),
        ("market_list_serving", "idx_market_list_serving_activity", ["volume_24h", "trade_count_24h", "last_trade_at"]),
        ("market_list_serving", "idx_market_list_serving_latest_trade_at", ["latest_trade_at"]),
        ("trade_addresses", "idx_trade_addresses_address_time", ["address", "trade_time", "block_number", "log_index"]),
        ("trade_addresses", "idx_trade_addresses_address_market", ["address", "market_id"]),
        (
            "trade_addresses",
            "idx_trade_addresses_market_time",
            ["market_id", "trade_time", "block_number", "log_index"],
        ),
        ("trade_addresses", "idx_trade_addresses_trade_date_address", ["trade_date", "address"]),
        ("address_trade_daily_stats", "idx_address_trade_daily_stats_address_date", ["address", "trade_date"]),
        ("address_trade_daily_stats", "idx_address_trade_daily_stats_last_trade_at", ["last_trade_at"]),
        ("address_trade_totals", "idx_address_trade_totals_last_trade_at", ["last_trade_at"]),
        ("address_market_stats", "idx_address_market_stats_market", ["market_id"]),
        ("address_market_stats", "idx_address_market_stats_last_trade_at", ["last_trade_at"]),
        ("oracle_events", "idx_oracle_events_market_id", ["market_id"]),
        ("oracle_events", "idx_oracle_events_external_market_id", ["external_market_id"]),
        ("oracle_events", "idx_oracle_events_question_id", ["question_id"]),
        ("oracle_events", "idx_oracle_events_condition_id", ["condition_id"]),
        ("oracle_events", "idx_oracle_events_market_block_id", ["market_id", "block_number", "id"]),
        ("oracle_events", "idx_oracle_events_external_market_block_id", ["external_market_id", "block_number", "id"]),
        ("oracle_events", "idx_oracle_events_question_block_id", ["question_id", "block_number", "id"]),
        ("oracle_events", "idx_oracle_events_condition_block_id", ["condition_id", "block_number", "id"]),
        ("oracle_events", "idx_oracle_events_block", ["block_number"]),
        ("oracle_events", "idx_oracle_events_status", ["event_status"]),
        ("oracle_events", "idx_oracle_events_status_market_id", ["event_status", "market_id"]),
        ("oracle_events", "idx_oracle_events_status_event_time", ["event_status", "event_time"]),
        ("oracle_events", "idx_oracle_events_matched_by", ["matched_by"]),
        ("neg_risk_request_mapping", "idx_neg_risk_request_mapping_question_id", ["question_id"]),
        ("neg_risk_request_mapping", "idx_neg_risk_request_mapping_source_operator", ["source_operator"]),
        ("block_timestamps", "idx_block_timestamps_timestamp", ["timestamp"]),
    ):
        create_index_if_not_exists(conn, table, index_name, cols)


def dict_from_row(row) -> dict:
    if row is None:
        return {}
    if hasattr(row, "as_dict"):
        return row.as_dict()
    return dict(row)
