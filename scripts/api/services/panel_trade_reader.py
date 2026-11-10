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
        deadline = time.monotonic() + 6.0
        admission_deadline = time.monotonic() + 1.25
        permit = try_permit("panel-clickhouse", 2)
        while permit is None and time.monotonic() < admission_deadline:
            time.sleep(0.025)
            permit = try_permit("panel-clickhouse", 2)
        if permit is None:
            raise TimeoutError("Panel ClickHouse budget full")
        with permit:
            while not take_read_token("panel-clickhouse", per_second=1, burst=2):
                if time.monotonic() >= admission_deadline:
                    raise TimeoutError("Panel ClickHouse rate budget full")
                time.sleep(0.025)
            settings = replace(reader.runtime.SETTINGS.clickhouse, max_threads=1, max_memory_bytes=256 * 1024**2,
                               max_bytes_to_read=16 * 1024**2, max_execution_seconds=4)
            context = {"app": reader.runtime.app, "get_backend": lambda: "postgres", "query_all": reader.semantic_query,
                       "_resources": SimpleNamespace(clickhouse=settings, clickhouse_read_timeout_seconds=None,
                                                     clickhouse_slots=threading.BoundedSemaphore(1))}
            # Four bounded reads cross the tunnel sequentially. Network wait
            # needs its own allowance; SQL time, bytes and concurrency stay fixed.
            calls = 0

            def read(sql):
                nonlocal calls
                calls += 1
                remaining = deadline - time.monotonic()
                # 4 MiB watermark + 24 MiB keys + 32 MiB facts + 4 MiB times.
                # Limits are checked at granule boundaries, not physical IO.
                if calls > 4 or remaining <= 0:
                    raise TimeoutError("Panel trade request budget exhausted")
                context["_resources"].clickhouse = replace(settings, max_bytes_to_read=(4, 24, 32, 4)[calls - 1] * 1024**2)
                rows = ch._query_json_rows(context, sql, timeout_seconds=min(5, remaining))
                if rows is None:
                    raise TimeoutError(f"Panel trade query unavailable at read {calls}")
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
            # This panel serves recent fills, not an unbounded historical scan.
            # Older parts may reconstruct variant flags from wide raw records.
            # A wider chart axis must not multiply the source read workload.
            scan_blocks = min(seconds, 86400)
            lower = max(0, upper - scan_blocks + 1)
            token_sql = ",".join(f"'{token}'" for token in tokens)
            cursor_sql = f"AND (block_number, log_index, tx_hash) < ({before[0]}, {before[1]}, '{before[2]}')" if before else ""
            # Seek narrow event keys before reading wide variant/amount columns.
            # The preview uses only the source's verified base-fact branch.
            # fact_base_matches=1 proves the base equals every source fact;
            # variant-only history reconstruction is outside this small view.
            # Each token is the leading primary-key field. Seek its own top-N
            # before merging; the global top-N is contained in these two sets.
            # Keep that same qualification on both seeks and the value read.
            seeks = [f"""SELECT * FROM (SELECT market_id, token_id, block_number, log_index, tx_hash
                FROM orderfilled_events_v1
                PREWHERE intDiv(block_number,1000000) BETWEEN {lower // 1000000} AND {upper // 1000000}
                  AND block_number BETWEEN {lower} AND {upper} AND token_id = '{token}'
                WHERE fact_base_matches = 1 {cursor_sql}
                ORDER BY token_id DESC, block_number DESC, log_index DESC, tx_hash DESC LIMIT {limit + 1})"""
                for token in tokens]
            chosen = read(f"""SELECT market_id, token_id, block_number, log_index, tx_hash
                FROM ({' UNION ALL '.join(seeks)})
                ORDER BY block_number DESC, log_index DESC, tx_hash DESC LIMIT {limit + 1}
                FORMAT JSONEachRow""")
            rows = []
            if chosen:
                if any(str(r["token_id"]) not in tokens or len(str(r["tx_hash"])) != 64
                       or any(c not in '0123456789abcdef' for c in str(r["tx_hash"])) for r in chosen):
                    raise TimeoutError("Invalid indexed trade identity")
                identities = ",".join(f"({int(r['market_id'])},'{r['token_id']}',{int(r['block_number'])},{int(r['log_index'])},'{r['tx_hash']}')" for r in chosen)
                partitions = ",".join(str(p) for p in sorted({int(r["block_number"]) // 1000000 for r in chosen}))
                fields = ("f.tx_hash, f.log_index, f.market_id, concat('0x', f.token_id) AS token_id, "
                          "toString(f.price) AS price, f.block_number") if chart_range else ch._orderfilled_projection_sql(include_time=False)
                # Match the published fact view's UInt64 projection exactly.
                for column in ('maker_amount', 'taker_amount', 'fee'):
                    fields = fields.replace(f'toString(f.{column})', f"toString(accurateCastOrNull(f.{column},'UInt64'))")
                rows = read(f"""SELECT {fields} FROM orderfilled_events_v1 f
                    WHERE f.fact_base_matches = 1 AND intDiv(f.block_number,1000000) IN ({partitions})
                    AND f.token_id IN ({token_sql})
                    AND f.block_number BETWEEN {min(int(r['block_number']) for r in chosen)} AND {max(int(r['block_number']) for r in chosen)}
                    AND (f.market_id,f.token_id,f.block_number,f.log_index,f.tx_hash)
                        IN ({identities})
                    ORDER BY block_number DESC,log_index DESC,tx_hash DESC FORMAT JSONEachRow""")
                identity = lambda r: (int(r["block_number"]), int(r["log_index"]), str(r["tx_hash"]))
                if (len(rows) != len(chosen) or {identity(r) for r in rows} != {identity(r) for r in chosen}
                    or any(ch._uint256_clickhouse_token(r.get("token_id")) not in tokens for r in rows)):
                    raise TimeoutError("Trade facts changed during indexed read")
            visible = ch._attach_trade_times(read, rows[:limit])
        if chart_range:
            end = datetime.now(timezone.utc)
            start = end - timedelta(seconds=seconds)
            projected = semantics.project_token_price_series(context, [dict(row, market_id=int(market_id)) for row in visible])
            if any(row.get("outcomeSemanticsStatus") in {"semantics_query_failed", "semantics_database_unavailable"} for row in projected):
                raise TimeoutError("Chart outcome evidence unavailable")
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
                                 "fromBlock": lower, "toBlock": upper, "complete": False,
                                 "selection": "verified-base-facts"},
                    "sourceUpdatedAt": watermarks[0]["timestamp"]}
        items = semantics.annotate_raw_trade_rows(context, [normalize_trade({**row, "market_id": int(market_id)}) for row in visible])
        last = rows[limit - 1] if len(rows) > limit else None
        return {"marketId": int(market_id), "localMarketId": int(market_id), "items": items,
                "nextCursor": f"{last['block_number']}:{last['log_index']}:{last['tx_hash']}" if last else None,
                "source": "market-data/clickhouse", "sourceUpdatedAt": watermarks[0]["timestamp"],
                "coverage": {"fromBlock": lower, "toBlock": upper, "scope": "selected-token-block-window",
                             "selection": "verified-base-facts", "maxItems": limit,
                             "globalCompleteness": "NOT_PROVEN", "hasMoreInWindow": len(rows) > limit}}

    return {"marketId": int(market_id), "localMarketId": int(market_id),
            **reader.cache.get("chart" if chart_range else "flow", ["verified-base-v3", int(market_id), limit, before, chart_range], build,
                               ttl=90 if chart_range else 8, max_age=300 if chart_range else 60, background=False)}


def read_chart(reader, market_id, *, range_name):
    return {"range": range_name, **read_flow(reader, market_id, chart_range=range_name)}
