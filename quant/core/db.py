"""Database and ClickHouse connection helpers for quant price builders."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:  # pragma: no cover - exercised only in under-provisioned envs
    psycopg = None
    dict_row = None


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for candidate in (
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / ".env.local",
        PROJECT_ROOT / "scripts" / ".env",
    ):
        if candidate.exists():
            load_dotenv(candidate, override=False)


load_dotenv_files()


def env_first(*names: str, default: str = "") -> str:
    for name in names:
        raw = os.environ.get(name)
        if raw is not None and str(raw).strip() != "":
            return str(raw).strip()
    return default


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def env_int_first(*names: str, default: int) -> int:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            return default
    return default


def env_float_first(*names: str, default: float) -> float:
    for name in names:
        raw = os.environ.get(name)
        if raw is None or str(raw).strip() == "":
            continue
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            return default
    return default


@dataclass(frozen=True)
class PostgresSettings:
    host: str = field(default_factory=lambda: env_first(
        "POLYDATA_POSTGRES_HOST",
        "POLYMARKET_POSTGRES_HOST",
        "POLYMARKET_PostgreSQL_HOST",
        default="127.0.0.1",
    ))
    port: int = field(default_factory=lambda: env_int_first(
        "POLYDATA_POSTGRES_PORT",
        "POLYMARKET_POSTGRES_PORT",
        "POLYMARKET_PostgreSQL_PORT",
        default=45432,
    ))
    user: str = field(default_factory=lambda: env_first(
        "POLYDATA_POSTGRES_USER",
        "POLYMARKET_POSTGRES_USER",
        "POLYMARKET_PostgreSQL_USER",
        default="poly_user",
    ))
    password: str = field(default_factory=lambda: env_first(
        "POLYDATA_POSTGRES_PASSWORD",
        "POLYMARKET_POSTGRES_PASSWORD",
        "POLYMARKET_POSTGRESQL_PASSWORD",
        "POLYMARKET_PostgreSQL_PASSWORD",
        default="",
    ))
    database: str = field(default_factory=lambda: env_first(
        "POLYDATA_POSTGRES_DATABASE",
        "POLYMARKET_POSTGRES_DATABASE",
        "POLYMARKET_PostgreSQL_DATABASE",
        default="poly_data_core",
    ))
    search_path: str = field(default_factory=lambda: env_first(
        "POLYDATA_POSTGRES_SEARCH_PATH",
        default="quant,core,oracle,ops,public",
    ))
    connect_timeout_seconds: int = field(default_factory=lambda: env_int_first(
        "POLYDATA_QUANT_POSTGRES_CONNECT_TIMEOUT_SECONDS",
        default=10,
    ))


@dataclass(frozen=True)
class ClickHouseSettings:
    http_url: str = field(default_factory=lambda: env_first("POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL", default=""))
    container: str = field(default_factory=lambda: env_first("POLYDATA_ORDERFILLED_CLICKHOUSE_CONTAINER", default="polydata_clickhouse_orderfilled"))
    database: str = field(default_factory=lambda: env_first("POLYDATA_ORDERFILLED_CLICKHOUSE_DATABASE", default="poly_orderfilled"))
    user: str = field(default_factory=lambda: env_first("POLYDATA_ORDERFILLED_CLICKHOUSE_USER", default="poly_user"))
    password: str = field(default_factory=lambda: env_first(
        "POLYDATA_ORDERFILLED_CLICKHOUSE_PASSWORD",
        "CLICKHOUSE_PASSWORD",
        default="",
    ))
    orderfilled_table: str = field(default_factory=lambda: env_first("POLYDATA_ORDERFILLED_CLICKHOUSE_READ_TABLE", default="orderfilled_fact"))
    timeout_seconds: float = field(default_factory=lambda: env_float_first("POLYDATA_QUANT_CLICKHOUSE_TIMEOUT_SECONDS", default=120.0))


def database_settings_summary(
    postgres: PostgresSettings | None = None,
    clickhouse: ClickHouseSettings | None = None,
) -> dict[str, Any]:
    pg = postgres or PostgresSettings()
    ch = clickhouse or ClickHouseSettings()
    return {
        "postgres": {
            "host": pg.host,
            "port": pg.port,
            "user": pg.user,
            "database": pg.database,
            "search_path": pg.search_path,
            "password_configured": bool(pg.password),
        },
        "clickhouse": {
            "http_url_configured": bool(ch.http_url),
            "container": ch.container,
            "database": ch.database,
            "user": ch.user,
            "password_configured": bool(ch.password),
            "orderfilled_table": ch.orderfilled_table,
        },
    }


def safe_identifier(value: str, *, default: str | None = None) -> str:
    text = str(value or default or "").strip()
    if not text:
        raise ValueError("identifier is required")
    if not all(ch.isalnum() or ch == "_" for ch in text):
        raise ValueError(f"unsafe identifier: {value!r}")
    return text


@contextmanager
def postgres_connection(settings: PostgresSettings | None = None, *, readonly: bool = False) -> Iterator[Any]:
    if psycopg is None:
        raise RuntimeError("psycopg is not installed. Install psycopg[binary] first.")
    cfg = settings or PostgresSettings()
    conn = psycopg.connect(
        host=cfg.host,
        port=cfg.port,
        user=cfg.user,
        password=cfg.password,
        dbname=cfg.database,
        connect_timeout=cfg.connect_timeout_seconds,
        row_factory=dict_row,
        autocommit=False,
    )
    try:
        if cfg.search_path:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO " + cfg.search_path)
        with conn.cursor() as cur:
            cur.execute("SET max_parallel_workers_per_gather = 0")
            cur.execute("SET work_mem = '32MB'")
        if readonly:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
        yield conn
        if not readonly:
            conn.commit()
    except Exception:
        if not readonly:
            conn.rollback()
        raise
    finally:
        conn.close()


class ClickHouseClient:
    """Small ClickHouse reader using HTTP tunnel when available, else docker exec."""

    def __init__(self, settings: ClickHouseSettings | None = None) -> None:
        self.settings = settings or ClickHouseSettings()
        safe_identifier(self.settings.database)
        safe_identifier(self.settings.orderfilled_table)

    def query_json_rows(self, query: str, *, timeout_seconds: float | None = None) -> list[dict[str, Any]]:
        full_query = query.rstrip().removesuffix(";") + "\nFORMAT JSONEachRow"
        output = self._query_text(full_query, timeout_seconds=timeout_seconds)
        rows: list[dict[str, Any]] = []
        for line in output.splitlines():
            text = line.strip()
            if not text:
                continue
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def query_scalar(self, query: str, *, timeout_seconds: float | None = None) -> str:
        return self._query_text(query.rstrip().removesuffix(";"), timeout_seconds=timeout_seconds).strip()

    def execute(self, query: str, *, stdin: str | None = None, timeout_seconds: float | None = None) -> None:
        self._query_text(query, stdin=stdin, timeout_seconds=timeout_seconds)

    def _query_text(self, query: str, *, stdin: str | None = None, timeout_seconds: float | None = None) -> str:
        timeout = self.settings.timeout_seconds if timeout_seconds is None else timeout_seconds
        if self.settings.http_url:
            return self._query_http(query, timeout_seconds=timeout)
        if shutil.which("docker") is None:
            raise RuntimeError("docker is unavailable and POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL is not configured")
        completed = subprocess.run(
            self._docker_cmd(query),
            input=stdin,
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return completed.stdout

    def _docker_cmd(self, query: str) -> list[str]:
        return [
            "docker",
            "exec",
            "-i",
            self.settings.container,
            "clickhouse-client",
            "--user",
            self.settings.user,
            "--password",
            self.settings.password,
            "--database",
            self.settings.database,
            "--query",
            query,
        ]

    def _query_http(self, query: str, *, timeout_seconds: float) -> str:
        params = urlencode(
            {
                "database": self.settings.database,
                "user": self.settings.user,
                "password": self.settings.password,
            }
        )
        separator = "&" if "?" in self.settings.http_url else "?"
        request = Request(
            f"{self.settings.http_url}{separator}{params}",
            data=query.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "text/plain; charset=utf-8"},
        )
        with urlopen(request, timeout=timeout_seconds) as response:
            return response.read().decode("utf-8", errors="replace")


def execute_many(conn: Any, sql: str, rows: Sequence[Sequence[Any]]) -> int:
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(sql, rows)
        return cur.rowcount if cur.rowcount is not None else len(rows)
