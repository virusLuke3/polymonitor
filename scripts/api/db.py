from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def query_all(ctx: dict, sql: str, params: Optional[Iterable[Any]] = None) -> List[Dict[str, Any]]:
    conn = ctx["get_connection"](ctx["DB_PATH"])
    bound_params = ()
    try:
        bound_params = tuple(params or ())
        cursor = conn.cursor()
        cursor.execute(sql, bound_params)
        return [ctx["dict_from_row"](row) for row in cursor.fetchall()]
    except Exception:
        ctx["app"].logger.exception("SQL query_all failed sql=%s params=%s", " ".join(sql.split()), bound_params)
        raise
    finally:
        conn.close()


def query_one(ctx: dict, sql: str, params: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    conn = ctx["get_connection"](ctx["DB_PATH"])
    bound_params = ()
    try:
        bound_params = tuple(params or ())
        cursor = conn.cursor()
        cursor.execute(sql, bound_params)
        return ctx["dict_from_row"](cursor.fetchone())
    except Exception:
        ctx["app"].logger.exception("SQL query_one failed sql=%s params=%s", " ".join(sql.split()), bound_params)
        raise
    finally:
        conn.close()


def table_exists(ctx: dict, table_name: str) -> bool:
    conn = ctx["get_connection"](ctx["DB_PATH"])
    try:
        cursor = conn.cursor()
        if ctx["get_backend"]() == "sqlite":
            cursor.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1", (table_name,))
            return cursor.fetchone() is not None
        if ctx["get_backend"]() in {"postgres", "postgresql"}:
            if "." in table_name:
                schema, name = table_name.split(".", 1)
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = ? AND table_name = ?
                    LIMIT 1
                    """,
                    (schema, name),
                )
            else:
                cursor.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema IN ('core', 'oracle', 'ops', 'public')
                      AND table_name = ?
                    LIMIT 1
                    """,
                    (table_name,),
                )
            return cursor.fetchone() is not None
        cursor.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = %s
            LIMIT 1
            """,
            (table_name,),
        )
        return cursor.fetchone() is not None
    except Exception:
        ctx["app"].logger.exception("SQL table_exists failed table=%s", table_name)
        raise
    finally:
        conn.close()


def identifier_name(identifier: str) -> str:
    return str(identifier or "").strip().strip("`")


def get_existing_trade_read_source(ctx: dict) -> Optional[str]:
    for candidate in (ctx["TRADE_V2_CORE_TABLE"], ctx["TRADE_READ_SOURCE"], ctx["LEGACY_TRADES_TABLE"]):
        table_name = identifier_name(candidate)
        if table_name and table_exists(ctx, table_name):
            return ctx["sql_identifier"](table_name)
    return None
