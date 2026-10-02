"""Alpha's token-bound flow policy. HTTP readers consume worker snapshots only.

No logical outcome_code is used: every aggregate retains one exact source token,
whose label/capability is revalidated against the existing projection ledger.
This does not grant a mutation proof to legacy tokenless aggregates.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import math
from typing import Any

from . import clickhouse_orderfilled_service as trades
from . import outcome_semantics_service as semantics

POLICY_VERSION = "token-flow-v1"


def _owned_tokens(ctx: dict, ids: list[int]) -> dict[int, set[str]]:
    if not ids:
        return {}
    try:
        owners = ctx["query_all"]("SELECT id, yes_token_id, no_token_id FROM core.markets WHERE id IN ("
                                  + ",".join("?" for _ in ids) + ")", tuple(ids))
        return {int(owner["id"]): {semantics._normalize_token_id(owner.get("yes_token_id")),
                                  semantics._normalize_token_id(owner.get("no_token_id"))} for owner in owners}
    except Exception:
        return {}


def revalidate_cached_observations(ctx: dict, payload: dict) -> dict:
    candidates = [item for item in payload.get("candidates") or [] if isinstance(item, dict)]
    owners = _owned_tokens(ctx, sorted({value for item in candidates if (value := semantics._market_id(item))}))
    valid = [item for item in candidates if item.get("qualification") == "labels-unavailable"
             and semantics._normalize_token_id(item.get("tokenId")) in owners.get(semantics._market_id(item), set())]
    result = {**payload, "candidates": valid}
    if len(valid) != len(candidates):
        coverage = {**(payload.get("coverage") or {}), "lastReadRejectedCount":
                    int((payload.get("coverage") or {}).get("lastReadRejectedCount") or 0) + len(candidates) - len(valid)}
        result.update(coverage=coverage, status="partial" if valid or payload.get("items") else "degraded",
                      error="Some cached token ownerships could not be verified")
    return result


def _observations(ctx: dict, rows: list[dict], limit: int, excluded_markets: set[int]) -> list[dict]:
    """Neutral token facts, never a label/probability/direction fallback.

    Require current canonical market ownership even for a pending candidate.
    Invalid token, conflicting ledger and unsupported labels stay excluded.
    """
    pending = [row for row in rows if row.get("outcomeSemanticsStatus") in {
        "projection_missing", "source_first_projection_missing"}]
    ids = sorted({int(row["market_id"]) for row in pending})
    if not ids:
        return []
    tokens = _owned_tokens(ctx, ids)
    result, seen = [], set(excluded_markets)
    for row in pending:
        market_id = int(row["market_id"])
        if market_id in seen or semantics._normalize_token_id(row.get("token_id")) not in tokens.get(market_id, set()):
            continue
        metrics = {target: _number(row.get(source)) for source, target in (
            ("flow_notional", "totalNotional"), ("net_flow_notional", "netFlowNotional"),
            ("net_direction_strength", "netDirectionStrength"), ("market_share", "marketShare"),
            ("unique_trader_count", "uniqueTraderCount"), ("trade_count", "tradeCount"))}
        if any(value is None or value < 0 for value in metrics.values()) or row.get("side") not in {"BUY", "SELL"}:
            continue
        seen.add(market_id)
        result.append({"id": f"candidate:{market_id}:{row['token_id']}:{row['side']}",
                       "marketId": market_id, "tokenId": row["token_id"], "marketIdentityVerified": True,
                       "marketTitle": row.get("market_title") or f"Market {market_id}",
                       "side": row["side"], "timestamp": row.get("timestamp"), "metrics": metrics,
                       "qualification": "labels-unavailable", "outcomeSemanticsValid": False,
                       "outcomeSemanticsStatus": row["outcomeSemanticsStatus"]})
        if len(result) >= limit:
            break
    return result


def _number(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _candidates(ctx: dict, limit: int) -> list[dict] | None:
    policy = trades._settings(ctx)
    window = policy.alpha_volume_window_minutes * 30
    baseline = max(window, policy.alpha_market_baseline_minutes * 30)
    table = trades._table_sql(ctx)
    cursor = trades._query_json_rows(ctx, f"SELECT ({trades._latest_fact_block_sql(ctx)}) AS watermark FORMAT JSONEachRow", timeout_seconds=2.0)
    if not cursor or _number(cursor[0].get("watermark")) is None:
        return None
    watermark = int(cursor[0]["watermark"])
    return trades._query_json_rows(ctx, f"""
        WITH {watermark} AS watermark,
        flows AS (
            SELECT market_id, token_id,
                sumIf(toFloat64(price) * toFloat64(size), side_code = 1) AS buys,
                sumIf(toFloat64(price) * toFloat64(size), side_code = 2) AS sells,
                greatest(buys, sells) AS flow,
                abs(buys - sells) AS net_flow,
                net_flow / greatest(buys + sells, 0.000001) AS strength,
                max(toFloat64(price) * toFloat64(size)) AS max_fill,
                argMax(toFloat64(price), (block_number, log_index)) AS last_price,
                uniqExact(taker) AS trader_count, count() AS trade_count,
                max(block_number) AS latest_block
            FROM {table}
            WHERE block_number >= watermark - {window}
                AND block_number <= watermark
                AND market_id != 0 AND token_id != repeat('0', 64)
                AND side_code IN (1, 2) AND size > 0
                AND price >= {policy.signal_min_price} AND price <= {policy.signal_max_price}
            GROUP BY market_id, token_id
        ), ranked_flows AS (
            SELECT *, quantileTDigest(0.95)(flow) OVER () AS threshold_p95 FROM flows
        ), baselines AS (
            SELECT market_id, sum(toFloat64(price) * toFloat64(size)) AS volume
            FROM {table}
            WHERE block_number >= watermark - {baseline} AND block_number <= watermark AND market_id != 0
            GROUP BY market_id
        ), clocks AS (
            SELECT block_number, argMax(block_time, ingested_at) AS observed_at
            FROM block_timestamps WHERE block_number >= watermark - {baseline} AND block_number <= watermark
            GROUP BY block_number
        )
        SELECT f.market_id AS market_id, concat('0x', lower(f.token_id)) AS token_id,
            if(f.buys >= f.sells, 'BUY', 'SELL') AS side,
            toString(f.last_price) AS price,
            f.flow AS flow_notional, f.net_flow AS net_flow_notional,
            f.strength AS net_direction_strength, f.max_fill AS max_trade_notional,
            f.flow / greatest(b.volume, 0.000001) AS market_share,
            f.trader_count AS unique_trader_count, f.trade_count AS trade_count,
            f.latest_block AS latest_block,
            watermark - {window} AS source_from_block, watermark AS source_through_block,
            if(c.observed_at > toDateTime('2000-01-01', 'UTC'),
                formatDateTime(c.observed_at, '%Y-%m-%dT%H:%i:%SZ', 'UTC'), NULL) AS timestamp,
            if((SELECT count() FROM clocks WHERE block_number >= watermark - 60 AND observed_at > toDateTime('2000-01-01', 'UTC')) > 0,
                formatDateTime((SELECT argMax(observed_at, block_number) FROM clocks WHERE block_number >= watermark - 60 AND observed_at > toDateTime('2000-01-01', 'UTC')), '%Y-%m-%dT%H:%i:%SZ', 'UTC'), NULL) AS source_observed_at,
            (SELECT max(block_number) FROM clocks WHERE block_number >= watermark - 60 AND observed_at > toDateTime('2000-01-01', 'UTC')) AS source_timestamp_block,
            f.threshold_p95 AS threshold_p95
        FROM ranked_flows f LEFT JOIN baselines b ON b.market_id = f.market_id
            LEFT JOIN clocks c ON c.block_number = f.latest_block
        WHERE f.strength >= {policy.alpha_min_net_strength}
            AND (f.flow >= greatest({policy.alpha_min_flow_notional}, threshold_p95)
                OR f.max_fill >= {policy.alpha_min_single_trade_notional}
                OR (f.flow >= {policy.alpha_relative_min_flow_notional}
                    AND market_share >= {policy.alpha_market_share_threshold}))
        ORDER BY f.net_flow DESC, f.latest_block DESC, f.market_id, f.token_id
        LIMIT {min(max(limit, 1), 20) * 12}
        FORMAT JSONEachRow
    """, timeout_seconds=3.5)


def _signal(row: dict, window_minutes: int) -> dict | None:
    numbers = {key: _number(row.get(key)) for key in (
        "price", "flow_notional", "net_flow_notional", "net_direction_strength",
        "market_share", "max_trade_notional", "unique_trader_count", "trade_count",
    )}
    if any(value is None for value in numbers.values()):
        return None
    price, strength, share = numbers["price"], numbers["net_direction_strength"], numbers["market_share"]
    if not (0 <= price <= 1 and 0 <= strength <= 1 and share >= 0):
        return None
    logical, side = row.get("logicalOutcome"), row.get("side")
    if logical not in {"YES", "NO"} or side not in {"BUY", "SELL"}:
        return None
    score = round(min(numbers["net_flow_notional"] / 1000 * 35, 40)
                  + min(strength * 35, 25) + min(share * 100, 15)
                  + min((1 - abs(price - .5) / .5) * 15, 10)
                  + min(numbers["unique_trader_count"], 10), 1)
    severity = "critical" if numbers["flow_notional"] >= 10000 else "elevated" if numbers["flow_notional"] >= 2500 else "watch"
    market_id = int(row["market_id"])
    return {
        "id": f"alpha:{market_id}:{row['token_id']}:{side}",
        "kind": "token-flow", "policyVersion": POLICY_VERSION,
        "marketId": market_id, "tokenId": row["token_id"],
        "marketTitle": row.get("market_title") or f"Market {market_id}",
        "title": f"{window_minutes}m net token flow", "timestamp": row.get("timestamp"),
        "sourceFromBlock": row.get("source_from_block"), "sourceThroughBlock": row.get("source_through_block"),
        "side": side, "logicalOutcome": logical, "outcome": row["sourceOutcomeLabel"],
        "sourceOutcomeLabel": row["sourceOutcomeLabel"], "price": row["price"],
        "severity": severity,
        "outcomeSemanticsValid": True, "outcomeSemanticsIdentityMode": "raw",
        "outcomeSemanticsCapabilities": row.get("outcomeSemanticsCapabilities"),
        "metrics": {
            "totalNotional": numbers["flow_notional"], "netFlowNotional": numbers["net_flow_notional"],
            "netDirectionStrength": strength, "marketShare": share,
            "uniqueTraderCount": int(numbers["unique_trader_count"]),
            "tradeCount": int(numbers["trade_count"]), "score": score,
        },
    }


def fetch_live_alpha_signal_payload(ctx: dict, limit: int = 8) -> dict:
    limit = min(max(int(limit), 1), 20)
    policy = trades._settings(ctx)
    generated_at = ctx["utc_now_iso"]()
    payload = {
        "items": [], "candidates": [], "generatedAt": generated_at, "status": "empty", "freshness": "observed",
        "policyVersion": POLICY_VERSION, "scope": "global", "sourceMode": "token-flow",
        "source": "ClickHouse OrderFilled · token-bound flow",
        "windowMinutes": policy.alpha_volume_window_minutes, "baselineMinutes": policy.alpha_market_baseline_minutes,
        "windowAnchor": "source-block-watermark", "refreshIntervalSeconds": 120,
        "sourceStates": {"clickhouseMode": trades.clickhouse_read_mode(ctx)},
        "coverage": {"candidateCount": 0, "verifiedCount": 0, "rejectedCount": 0, "rejectionReasons": {}, "truncated": False},
    }
    rows = _candidates(ctx, limit)
    if rows is None:
        payload.update(status="degraded", freshness="degraded", error="Trade source unavailable")
        payload["sourceStates"].update(clickhouse="unavailable", semantics="unknown")
        return payload
    coverage = payload["coverage"]
    coverage["candidateCount"] = len(rows)
    coverage["truncated"] = len(rows) >= min(max(limit, 1), 20) * 12
    rejected: Counter = Counter()
    # One exact token per group: no outcome_code inference or tokenless mutation claim.
    annotated = trades._attach_market_titles(ctx, semantics.annotate_raw_trade_rows(ctx, rows))
    valid = []
    for row in annotated:
        capabilities = row.get("outcomeSemanticsCapabilities") or {}
        if not row.get("outcomeSemanticsValid") or not (
            capabilities.get("supportsYesNoWording") or capabilities.get("supportsDirectionalSemantics")
        ):
            reason = row.get("outcomeSemanticsStatus") if not row.get("outcomeSemanticsValid") else "directional_semantics_unsupported"
            rejected[str(reason or "projection_missing")] += 1
        else:
            valid.append(row)
    signals = []
    for row in valid:
        signal = _signal(row, policy.alpha_volume_window_minutes)
        if signal is None:
            rejected["invalid_signal_metrics"] += 1
        else:
            signals.append(signal)
    coverage.update(verifiedCount=len(signals), rejectedCount=sum(rejected.values()), rejectionReasons=dict(rejected))
    signals.sort(key=lambda item: (-item["metrics"]["score"], -item["metrics"]["netFlowNotional"], item["id"]))
    seen = set()
    for item in signals:
        if item["marketId"] in seen:
            continue
        seen.add(item["marketId"])
        payload["items"].append(item)
        if len(payload["items"]) >= limit:
            break
    payload["status"] = "partial" if rejected else "ok" if payload["items"] else "empty"
    payload["candidates"] = _observations(ctx, annotated, limit, seen)
    if rows and not payload["items"]:
        payload.update(status="partial" if payload["candidates"] else "degraded",
                       freshness="observed" if payload["candidates"] else "degraded",
                       error="Candidate outcome labels are unavailable; token facts are not verified Alpha")
    source_times = [row.get("source_observed_at") for row in rows if row.get("source_observed_at")]
    source_time = max(source_times) if source_times else None
    payload["sourceObservedAt"] = source_time
    payload["sourceClock"] = {"blockNumber": max((int(row.get("source_timestamp_block") or 0) for row in rows), default=0),
                              "maxLagBlocks": 60}
    if rows and source_time:
        age = (datetime.fromisoformat(generated_at.replace("Z", "+00:00")) - datetime.fromisoformat(source_time.replace("Z", "+00:00"))).total_seconds()
        payload["sourceAgeSeconds"] = max(0, round(age))
        if age > 300:
            payload.update(status="stale", freshness="stale")
        elif age < -60:
            payload.update(status="partial", freshness="unknown")
    elif rows:
        # Missing block timestamps are UNKNOWN, not proof that the data expired.
        payload.update(status="partial", freshness="unknown")
    payload["sourceStates"].update(clickhouse="ok", semantics="partial" if rejected else "verified")
    return payload
