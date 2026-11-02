"""A single bounded token/block window, without adaptive historical scans."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from api.read_budget import take_read_token, try_permit
from api.serialization import normalize_trade
from api.services import clickhouse_orderfilled_service as ch
from api.services import outcome_semantics_service as semantics


def read_flow(reader, market_id, *, limit=50, before=None, chart_range=None):
    limit = 600 if chart_range else min(100, max(1, int(limit)))
    if before is not None:
        block, log, tx = before
        if block < 0 or log < 0 or len(tx) != 64 or any(c not in "0123456789abcdef" for c in tx):
            raise ValueError("Invalid trade cursor")

    def build():
        market = reader.record(market_id)
        tokens = [ch._uint256_clickhouse_token(market.get(key)) for key in ("yes_token_id", "no_token_id")]
        if not all(tokens) or tokens[0] == tokens[1]:
            raise TimeoutError("Market token mapping unavailable")
        permit = try_permit("panel-clickhouse", 2)
        if permit is None:
            raise TimeoutError("Panel ClickHouse budget full")
        with permit:
            if not take_read_token("panel-clickhouse", per_second=1, burst=2):
                raise TimeoutError("Panel ClickHouse rate budget full")
            settings = replace(reader.runtime.SETTINGS.clickhouse, max_threads=1, max_memory_bytes=256 * 1024**2,
                               max_bytes_to_read=16 * 1024**2, max_execution_seconds=2)
            context = {"app": reader.runtime.app, "get_backend": lambda: "postgres", "query_all": reader.semantic_query,
                       "_resources": SimpleNamespace(clickhouse=settings, clickhouse_read_timeout_seconds=None,
                                                     clickhouse_slots=threading.BoundedSemaphore(1))}
            deadline = time.monotonic() + 4.0
            calls = 0

            def read(sql):
                nonlocal calls
                calls += 1
                remaining = deadline - time.monotonic()
                # 4 MiB watermark + 56 MiB indexed facts + 4 MiB timestamps.
                # Limits are checked at granule boundaries, not physical IO.
                if calls > 3 or remaining <= 0:
                    raise TimeoutError("Panel trade request budget exhausted")
                context["_resources"].clickhouse = replace(settings, max_bytes_to_read=(56 if calls == 2 else 4) * 1024**2)
                rows = ch._query_json_rows(context, sql, timeout_seconds=min(3, remaining))
                if rows is None:
                    raise TimeoutError("Panel trade query unavailable")
                return rows

            watermarks = read("""SELECT block_number,
                formatDateTime(block_time, '%Y-%m-%dT%H:%i:%SZ', 'UTC') AS timestamp
                FROM block_timestamps ORDER BY block_number DESC LIMIT 1 FORMAT JSONEachRow""")
            if not watermarks:
                raise TimeoutError("Trade block time watermark unavailable")
            upper = int(watermarks[0]["block_number"])
            if before:
                upper = min(upper, int(before[0]))
            from api.services.market_service import RANGES
            # The block bound is a scan guard, not proof of time completeness.
            # Timestamp filtering below enforces the requested chart interval.
            seconds = RANGES[chart_range] if chart_range else 86400
            lower = max(0, upper - seconds + 1)
            token_sql = ",".join(f"'{token}'" for token in tokens)
            cursor_sql = f"AND (block_number, log_index, tx_hash) < ({before[0]}, {before[1]}, '{before[2]}')" if before else ""
            # Published primary-store contract, independent of legacy table
            # aliases or other consumers' historical fallback configuration.
            block_col = "canonical_block_number"
            table = "orderfilled_fact_primary_v1"
            token_filter = f"AND canonical_token_id IN ({token_sql})"
            rows = read(f"""SELECT {ch._orderfilled_projection_sql(include_time=False)} FROM (
                SELECT tx_hash, log_index, market_id, maker, taker, price, size, side_code, outcome_code,
                       token_id, block_number, order_hash, maker_amount, taker_amount, fee, contract
                FROM {table}
                WHERE intDiv({block_col},1000000) BETWEEN {lower // 1000000} AND {upper // 1000000}
                  AND {block_col} BETWEEN {lower} AND {upper}
                  AND token_id IN ({token_sql}) {token_filter} {cursor_sql}
                ORDER BY block_number DESC, log_index DESC, tx_hash DESC LIMIT {limit + 1}
                ) f ORDER BY block_number DESC, log_index DESC, tx_hash DESC FORMAT JSONEachRow""")
            visible = ch._attach_trade_times(read, rows[:limit])
        if chart_range:
            end = datetime.now(timezone.utc)
            start = end - timedelta(seconds=seconds)
            projected = semantics.project_token_price_series(context, [dict(row, market_id=int(market_id)) for row in visible])
            points = []
            for row in reversed(projected):
                stamp = str(row.get("timestamp") or "")
                if not row.get("priceProjectionValid") or not stamp:
                    continue
                when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                if start <= when <= end:
                    points.append({"timestamp": stamp, "yesPrice": row.get("yesPrice"), "noPrice": row.get("noPrice"),
                                   "tokenId": row.get("token_id"), "tokenPrice": row.get("tokenPrice")})
            return {"marketId": int(market_id), "range": chart_range, "interval": "trades", "kind": "probability",
                    "points": points, "historyStatus": "partial" if points else "empty", "priceSource": "stored-orderfilled",
                    "coverage": {"from": start.isoformat(), "to": end.isoformat(), "maxPoints": 600,
                                 "fromBlock": lower, "toBlock": upper, "complete": False},
                    "sourceUpdatedAt": watermarks[0]["timestamp"]}
        items = semantics.annotate_raw_trade_rows(context, [normalize_trade({**row, "market_id": int(market_id)}) for row in visible])
        last = rows[limit - 1] if len(rows) > limit else None
        return {"marketId": int(market_id), "localMarketId": int(market_id), "items": items,
                "nextCursor": f"{last['block_number']}:{last['log_index']}:{last['tx_hash']}" if last else None,
                "source": "market-data/clickhouse", "sourceUpdatedAt": watermarks[0]["timestamp"],
                "coverage": {"fromBlock": lower, "toBlock": upper, "scope": "selected-token-block-window",
                             "globalCompleteness": "NOT_PROVEN", "hasMoreInWindow": len(rows) > limit}}

    return {"marketId": int(market_id), "localMarketId": int(market_id),
            **reader.cache.get("chart" if chart_range else "flow", [int(market_id), limit, before, chart_range], build,
                               ttl=90 if chart_range else 8, max_age=300 if chart_range else 60)}


def read_chart(reader, market_id, *, range_name):
    return {"range": range_name, **read_flow(reader, market_id, chart_range=range_name)}
