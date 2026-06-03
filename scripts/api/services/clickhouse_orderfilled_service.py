from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_CONTAINER = "polydata_clickhouse_orderfilled"
DEFAULT_DATABASE = "poly_orderfilled"
DEFAULT_USER = "poly_user"
DEFAULT_PASSWORD = "PolyUserPass_007!"
DEFAULT_TABLE = "orderfilled_fact"


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def clickhouse_orderfilled_enabled() -> bool:
    return _env_flag("POLYDATA_ORDERFILLED_CLICKHOUSE_READ_ENABLED", True)


def _identifier(value: str, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if not all(ch.isalnum() or ch == "_" for ch in text):
        raise ValueError(f"Unsafe ClickHouse identifier: {value!r}")
    return text


def _settings() -> Dict[str, str]:
    return {
        "http_url": os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_HTTP_URL", "").strip(),
        "container": os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_CONTAINER", DEFAULT_CONTAINER),
        "database": _identifier(os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_DATABASE", DEFAULT_DATABASE), DEFAULT_DATABASE),
        "user": os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_USER", DEFAULT_USER),
        "password": os.environ.get("CLICKHOUSE_PASSWORD", DEFAULT_PASSWORD),
        "table": _identifier(os.environ.get("POLYDATA_ORDERFILLED_CLICKHOUSE_READ_TABLE", DEFAULT_TABLE), DEFAULT_TABLE),
    }


def _clickhouse_cmd(query: str) -> List[str]:
    settings = _settings()
    return [
        "docker",
        "exec",
        settings["container"],
        "clickhouse-client",
        "--user",
        settings["user"],
        "--password",
        settings["password"],
        "--database",
        settings["database"],
        "--query",
        query,
    ]


def _query_json_rows_http(ctx: dict, query: str, *, timeout_seconds: float) -> Optional[List[Dict[str, Any]]]:
    settings = _settings()
    base_url = settings["http_url"]
    if not base_url:
        return None
    params = urlencode(
        {
            "database": settings["database"],
            "user": settings["user"],
            "password": settings["password"],
        }
    )
    separator = "&" if "?" in base_url else "?"
    request = Request(
        f"{base_url}{separator}{params}",
        data=query.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            output = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger = ctx.get("app").logger if ctx.get("app") is not None else None
        if logger is not None:
            logger.warning("ClickHouse HTTP OrderFilled read failed: %s", exc)
        return None
    rows: List[Dict[str, Any]] = []
    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _query_json_rows(ctx: dict, query: str, *, timeout_seconds: float = 1.8) -> Optional[List[Dict[str, Any]]]:
    if not clickhouse_orderfilled_enabled():
        return None
    if ctx.get("app") is None:
        return None
    http_rows = _query_json_rows_http(ctx, query, timeout_seconds=timeout_seconds)
    if http_rows is not None:
        return http_rows
    if shutil.which("docker") is None:
        return None
    try:
        completed = subprocess.run(
            _clickhouse_cmd(query),
            check=True,
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        logger = ctx.get("app").logger if ctx.get("app") is not None else None
        if logger is not None:
            logger.warning("ClickHouse OrderFilled read failed: %s", exc)
        return None
    rows: List[Dict[str, Any]] = []
    for line in completed.stdout.splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            rows.append(parsed)
    return rows


def _orderfilled_projection_sql() -> str:
    return """
        lower(f.tx_hash) AS tx_hash,
        f.log_index AS log_index,
        f.market_id AS market_id,
        concat('0x', lower(f.maker)) AS maker,
        concat('0x', lower(f.taker)) AS taker,
        toString(f.price) AS price,
        toString(f.size) AS size,
        multiIf(f.side_code = 1, 'BUY', f.side_code = 2, 'SELL', 'UNKNOWN') AS side,
        multiIf(f.outcome_code = 1, 'YES', f.outcome_code = 2, 'NO', 'UNKNOWN') AS outcome,
        lower(f.token_id) AS token_id,
        formatDateTime(
            if(
                bt.block_number = 0,
                max_ts_time - toIntervalSecond(greatest(toInt64(0), toInt64(max_ts_block) - toInt64(f.block_number)) * 2),
                bt.block_time
            ),
            '%Y-%m-%dT%H:%i:%SZ',
            'UTC'
        ) AS timestamp,
        f.block_number AS block_number,
        lower(f.order_hash) AS order_hash,
        multiIf(f.side_code = 1, repeat('0', 64), f.side_code = 2, lower(f.token_id), NULL) AS maker_asset_id,
        multiIf(f.side_code = 1, lower(f.token_id), f.side_code = 2, repeat('0', 64), NULL) AS taker_asset_id,
        if(f.maker_amount IS NULL, NULL, toString(f.maker_amount)) AS maker_amount,
        if(f.taker_amount IS NULL, NULL, toString(f.taker_amount)) AS taker_amount,
        if(f.fee IS NULL, NULL, toString(f.fee)) AS fee,
        f.contract AS contract
    """


def _table_sql() -> str:
    return _settings()["table"]


def get_market_trades(ctx: dict, market_id: int, *, limit: int = 100, offset: int = 0) -> Optional[List[Dict[str, Any]]]:
    limit = min(max(int(limit), 1), 500)
    offset = max(int(offset), 0)
    rows = _query_json_rows(
        ctx,
        f"""
        WITH
            (SELECT ifNull(max(block_number), 0) FROM block_timestamps) AS max_ts_block,
            (SELECT ifNull(max(block_time), now('UTC')) FROM block_timestamps) AS max_ts_time
        SELECT {_orderfilled_projection_sql()}
        FROM {_table_sql()} f
        LEFT JOIN block_timestamps bt ON bt.block_number = f.block_number
        WHERE f.market_id = {int(market_id)}
        ORDER BY f.block_number DESC, f.log_index DESC
        LIMIT {int(offset)}, {int(limit)}
        FORMAT JSONEachRow
        """,
    )
    if rows is None:
        return None
    return [ctx["normalize_trade"](row) for row in rows]


def get_recent_trades(ctx: dict, *, limit: int = 24) -> Optional[List[Dict[str, Any]]]:
    limit = min(max(int(limit), 1), 200)
    rows = _query_json_rows(
        ctx,
        f"""
        WITH
            (SELECT ifNull(max(block_number), 0) FROM {_table_sql()}) AS max_fact_block,
            (SELECT ifNull(max(block_number), 0) FROM block_timestamps) AS max_ts_block,
            (SELECT ifNull(max(block_time), now('UTC')) FROM block_timestamps) AS max_ts_time
        SELECT {_orderfilled_projection_sql()}
        FROM {_table_sql()} f
        LEFT JOIN block_timestamps bt ON bt.block_number = f.block_number
        WHERE f.market_id != 0
          AND f.block_number >= max_fact_block - 20000
        ORDER BY f.block_number DESC, f.log_index DESC
        LIMIT {int(limit)}
        FORMAT JSONEachRow
        """,
    )
    if rows is None:
        return None
    normalized = [ctx["normalize_trade"](row) for row in rows]
    market_ids = sorted({int(row["marketId"]) for row in normalized if row.get("marketId") is not None})
    title_map: Dict[int, str] = {}
    if market_ids:
        placeholders = ", ".join("?" for _ in market_ids)
        market_rows = ctx["query_all"](
            f"SELECT id, title FROM markets WHERE id IN ({placeholders})",
            market_ids,
        )
        title_map = {int(row["id"]): str(row.get("title") or "") for row in market_rows if row.get("id") is not None}
    for trade in normalized:
        market_id = trade.get("marketId")
        if market_id is not None and not trade.get("marketTitle"):
            trade["marketTitle"] = title_map.get(int(market_id))
    return normalized


def get_price_series(ctx: dict, market_id: int, *, limit: int = 400) -> Optional[List[Dict[str, Any]]]:
    limit = min(max(int(limit), 1), 1200)
    rows = _query_json_rows(
        ctx,
        f"""
        WITH
            (SELECT ifNull(max(block_number), 0) FROM block_timestamps) AS max_ts_block,
            (SELECT ifNull(max(block_time), now('UTC')) FROM block_timestamps) AS max_ts_time
        SELECT
            formatDateTime(
                if(
                    bt.block_number = 0,
                    max_ts_time - toIntervalSecond(greatest(toInt64(0), toInt64(max_ts_block) - toInt64(f.block_number)) * 2),
                    bt.block_time
                ),
                '%Y-%m-%dT%H:%i:%SZ',
                'UTC'
            ) AS timestamp,
            multiIf(f.outcome_code = 1, 'YES', f.outcome_code = 2, 'NO', 'UNKNOWN') AS outcome,
            toString(f.price) AS price,
            f.block_number AS block_number,
            f.log_index AS log_index
        FROM {_table_sql()} f
        LEFT JOIN block_timestamps bt ON bt.block_number = f.block_number
        WHERE f.market_id = {int(market_id)}
        ORDER BY f.block_number DESC, f.log_index DESC
        LIMIT {int(limit)}
        FORMAT JSONEachRow
        """,
    )
    if rows is None:
        return None
    rows.reverse()
    yes_price = None
    no_price = None
    points: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("outcome") == "YES":
            yes_price = row.get("price")
        elif row.get("outcome") == "NO":
            no_price = row.get("price")
        points.append({"timestamp": row.get("timestamp"), "yesPrice": yes_price, "noPrice": no_price})
    return points


def get_market_stats(ctx: dict, market_ids: Iterable[int], *, hours: int = 24) -> Optional[Dict[int, Dict[str, Any]]]:
    ids = sorted({int(value) for value in market_ids if value is not None})
    if not ids:
        return {}
    id_csv = ", ".join(str(value) for value in ids)
    rows = _query_json_rows(
        ctx,
        f"""
        WITH
            (SELECT ifNull(max(block_number), 0) FROM {_table_sql()}) AS max_fact_block,
            (SELECT ifNull(max(block_number), 0) FROM block_timestamps) AS max_ts_block,
            (SELECT ifNull(max(block_time), now('UTC')) FROM block_timestamps) AS max_ts_time
        SELECT
            f.market_id AS market_id,
            count() AS trade_count_24h,
            toString(sum(f.size * f.price)) AS volume_24h,
            argMax(toString(f.price), tuple(f.block_number, f.log_index)) AS latest_price,
            formatDateTime(
                max(max_ts_time - toIntervalSecond(greatest(toInt64(0), toInt64(max_ts_block) - toInt64(f.block_number)) * 2)),
                '%Y-%m-%dT%H:%i:%SZ',
                'UTC'
            ) AS latest_trade_at
        FROM {_table_sql()} f
        WHERE f.market_id IN ({id_csv})
          AND f.block_number >= max_fact_block - {max(1, int(hours)) * 1800}
        GROUP BY f.market_id
        FORMAT JSONEachRow
        """,
    )
    if rows is None:
        return None
    return {
        int(row["market_id"]): {
            "trade_count_24h": int(row.get("trade_count_24h") or 0),
            "volume_24h": row.get("volume_24h") or 0,
            "latest_price": row.get("latest_price"),
            "last_trade_at": row.get("latest_trade_at"),
            "latest_trade_at": row.get("latest_trade_at"),
        }
        for row in rows
        if row.get("market_id") is not None
    }


def get_recent_market_activity(ctx: dict, *, limit: int = 1000, hours: int = 24) -> Optional[List[Dict[str, Any]]]:
    limit = min(max(int(limit), 1), 5000)
    hours = max(1, int(hours))
    rows = _query_json_rows(
        ctx,
        f"""
        WITH
            (SELECT ifNull(max(block_number), 0) FROM {_table_sql()}) AS max_fact_block,
            (SELECT ifNull(max(block_number), 0) FROM block_timestamps) AS max_ts_block,
            (SELECT ifNull(max(block_time), now('UTC')) FROM block_timestamps) AS max_ts_time
        SELECT
            f.market_id AS market_id,
            count() AS trade_count_24h,
            toString(sum(f.size * f.price)) AS volume_24h,
            argMax(toString(f.price), tuple(f.block_number, f.log_index)) AS latest_price,
            formatDateTime(
                max(max_ts_time - toIntervalSecond(greatest(toInt64(0), toInt64(max_ts_block) - toInt64(f.block_number)) * 2)),
                '%Y-%m-%dT%H:%i:%SZ',
                'UTC'
            ) AS latest_trade_at
        FROM {_table_sql()} f
        WHERE f.market_id != 0
          AND f.block_number >= max_fact_block - {hours * 1800}
        GROUP BY f.market_id
        HAVING (trade_count_24h > 0 OR toDecimal128(volume_24h, 10) > 0)
           AND toDecimal128(latest_price, 10) >= 0.05
           AND toDecimal128(latest_price, 10) <= 0.95
        ORDER BY trade_count_24h DESC, toDecimal128(volume_24h, 10) DESC, latest_trade_at DESC
        LIMIT {limit}
        FORMAT JSONEachRow
        """,
        timeout_seconds=2.0,
    )
    if rows is None:
        return None
    return [
        {
            "market_id": int(row.get("market_id") or 0),
            "trade_count_24h": int(row.get("trade_count_24h") or 0),
            "volume_24h": row.get("volume_24h") or 0,
            "latest_price": row.get("latest_price"),
            "last_trade_at": row.get("latest_trade_at"),
            "latest_trade_at": row.get("latest_trade_at"),
        }
        for row in rows
        if int(row.get("market_id") or 0) > 0
    ]
