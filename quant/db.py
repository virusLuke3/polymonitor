"""Database and ClickHouse connection helpers for quant price builders."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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


@dataclass(frozen=True)
class PostgresSettings:
    host: str = os.environ.get("POLYDATA_POSTGRES_HOST", os.environ.get("POLYMARKET_POSTGRES_HOST", "127.0.0.1"))
    port: int = env_int("POLYDATA_POSTGRES_PORT", env_int("POLYMARKET_POSTGRES_PORT", 45432))
    user: str = os.environ.get("POLYDATA_POSTGRES_USER", os.environ.get("POLYMARKET_POSTGRES_USER", "poly_user"))
    password: str = os.environ.get(
        "POLYDATA_POSTGRES_PASSWORD",
        os.environ.get(
            "POLYMARKET_POSTGRES_PASSWORD",
            os.environ.get("POLYMARKET_POSTGRESQL_PASSWORD", os.environ.get("POLYMARKET_PostgreSQL_PASSWORD", "")),
        ),
    )
    database: str = os.environ.get("POLYDATA_POSTGRES_DATABASE", os.environ.get("POLYMARKET_POSTGRES_DATABASE", "poly_data_core"))
    search_path: str = os.environ.get("POLYDATA_POSTGRES_SEARCH_PATH", "quant,core,oracle,ops,public")
    connect_timeout_seconds: int = env_int("POLYDATA_QUANT_POSTGRES_CONNECT_TIMEOUT_SECONDS", 10)


@dataclass(frozen=True)
class ClickHouseSettings:
    http_url: str = os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL", "").strip()
    container: str = os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_CONTAINER", "polydata_clickhouse_orderfilled")
    database: str = os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_DATABASE", "poly_orderfilled")
    user: str = os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_USER", "poly_user")
    password: str = os.environ.get("CLICKHOUSE_PASSWORD", "PolyUserPass_007!")
    orderfilled_table: str = os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_READ_TABLE", "orderfilled_fact")
    timeout_seconds: float = env_float("POLYDATA_QUANT_CLICKHOUSE_TIMEOUT_SECONDS", 120.0)


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
