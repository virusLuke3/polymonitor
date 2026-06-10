"""Fixed-template quant backtest engine.

This first production pass intentionally keeps the strategy small: one long
position template, two price sources, and durable run/result tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from typing import Any

from .frameworks import normalize_backtest_engine, run_framework_backtest
from ..prices.build_targets import target_reason, upsert_price_build_targets_for_market


SUPPORTED_PRICE_SOURCES = {"frontend", "orderfilled_block_close"}


@dataclass(frozen=True)
class BacktestParameters:
    entry_threshold: Decimal = Decimal("0.58")
    exit_threshold: Decimal = Decimal("0.44")
    stop_loss: Decimal = Decimal("0.075")
    take_profit: Decimal = Decimal("0.16")
    max_holding_bars: int = 96
    initial_capital: Decimal = Decimal("100000")
    position_size: Decimal = Decimal("100")
    fee_bps: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    liquidity_cap_pct: Decimal = Decimal("100")


@dataclass(frozen=True)
class PricePoint:
    x_value: int
    price: Decimal
    volume: Decimal


@dataclass
class OpenPosition:
    trade_index: int
    entry_index: int
    entry_x: int
    entry_price: Decimal
    size: Decimal


def decimal_or_default(value: Any, default: Decimal) -> Decimal:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def int_or_default(value: Any, default: int) -> int:
    try:
        parsed = int(str(value))
    except Exception:
        return default
    return parsed if parsed > 0 else default


def normalize_price_source(value: Any) -> str:
    text = str(value or "frontend").strip().lower()
    aliases = {
        "orderfilled": "orderfilled_block_close",
        "block_close": "orderfilled_block_close",
        "orderfilled_block_close": "orderfilled_block_close",
        "frontend_price_history": "frontend",
        "frontend-price-history": "frontend",
        "frontend": "frontend",
    }
    source = aliases.get(text, text)
    if source not in SUPPORTED_PRICE_SOURCES:
        raise ValueError(f"unsupported price_source: {value!r}")
    return source


def parse_parameters(payload: dict[str, Any]) -> BacktestParameters:
    return BacktestParameters(
        entry_threshold=decimal_or_default(payload.get("entry_threshold", payload.get("entryThreshold")), Decimal("0.58")),
        exit_threshold=decimal_or_default(payload.get("exit_threshold", payload.get("exitThreshold")), Decimal("0.44")),
        stop_loss=decimal_or_default(payload.get("stop_loss", payload.get("stopLoss")), Decimal("0.075")),
        take_profit=decimal_or_default(payload.get("take_profit", payload.get("takeProfit")), Decimal("0.16")),
        max_holding_bars=int_or_default(payload.get("max_holding_bars", payload.get("maxHoldingBars")), 96),
        initial_capital=decimal_or_default(payload.get("initial_capital", payload.get("initialCapital")), Decimal("100000")),
        position_size=decimal_or_default(payload.get("position_size", payload.get("positionSize")), Decimal("100")),
        fee_bps=decimal_or_default(payload.get("fee_bps", payload.get("feeBps")), Decimal("0")),
        slippage_bps=decimal_or_default(payload.get("slippage_bps", payload.get("slippageBps")), Decimal("0")),
        liquidity_cap_pct=decimal_or_default(payload.get("liquidity_cap_pct", payload.get("liquidityCapPct")), Decimal("100")),
    )


def _decimal_text(value: Decimal) -> str:
    return format(Decimal(str(value)).normalize(), "f")


def backtest_parameter_snapshot(
    *,
    market_slug: str,
    token_side: str,
    token_id: str | None,
    outcome_label: str | None,
    price_source: str,
    backtest_engine: str,
    from_ts: int | None,
    to_ts: int | None,
    from_block: int | None,
    to_block: int | None,
    params: BacktestParameters,
    execution_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    snapshot = {
        "strategy": "fixed_threshold_v1",
        "market_slug": market_slug,
        "token_side": token_side,
        "token_id": token_id,
        "outcome_label": outcome_label,
        "price_source": price_source,
        "backtest_engine": backtest_engine,
        "from_ts": from_ts,
        "to_ts": to_ts,
        "from_block": from_block,
        "to_block": to_block,
        "parameters": {
            "entry_threshold": _decimal_text(params.entry_threshold),
            "exit_threshold": _decimal_text(params.exit_threshold),
            "stop_loss": _decimal_text(params.stop_loss),
            "take_profit": _decimal_text(params.take_profit),
            "max_holding_bars": int(params.max_holding_bars),
            "initial_capital": _decimal_text(params.initial_capital),
            "position_size": _decimal_text(params.position_size),
            "fee_bps": _decimal_text(params.fee_bps),
            "slippage_bps": _decimal_text(params.slippage_bps),
            "liquidity_cap_pct": _decimal_text(params.liquidity_cap_pct),
        },
    }
    if execution_context:
        snapshot["execution_context"] = execution_context
    return snapshot


def backtest_parameter_fingerprint(snapshot: dict[str, Any]) -> str:
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _json_safe_scalar(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_text(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _sanitize_json_value(value: Any, *, depth: int = 0, max_items: int = 24) -> Any:
    if depth > 4:
        return _json_safe_scalar(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, inner in list(value.items())[:max_items]:
            if not isinstance(key, str):
                key = str(key)
            result[key[:80]] = _sanitize_json_value(inner, depth=depth + 1, max_items=max_items)
        return result
    if isinstance(value, list):
        return [_sanitize_json_value(item, depth=depth + 1, max_items=max_items) for item in value[:max_items]]
    return _json_safe_scalar(value)


def _execution_context_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("execution_context", payload.get("executionContext"))
    if not isinstance(raw, dict):
        raw = {}
    context = _sanitize_json_value(raw)
    if not isinstance(context, dict):
        context = {}
    context.setdefault("model", "fixed_threshold_v1")
    context.setdefault("fill_model", "close_price_with_bps_and_volume_cap")
    return context


def create_and_execute_backtest(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    run_id = create_backtest_run(conn, payload)
    try:
        execute_backtest_run(conn, run_id)
    except Exception as exc:
        mark_run_failed(conn, run_id, str(exc))
    return get_backtest_run_for_update_free(conn, run_id)


def list_queued_backtest_run_ids(conn: Any, *, limit: int = 10) -> list[int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT run_id
            FROM quant.quant_backtest_runs
            WHERE status = 'queued'
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (int(limit),),
        )
        return [int(row["run_id"]) for row in cur.fetchall()]


def claim_backtest_run(conn: Any, run_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quant.quant_backtest_runs
            SET status = 'running',
                started_at = CASE WHEN started_at IS NULL THEN now() ELSE started_at END,
                error = NULL
            WHERE run_id = %s
              AND status = 'queued'
            RETURNING run_id
            """,
            (int(run_id),),
        )
        return cur.fetchone() is not None


def create_backtest_run(conn: Any, payload: dict[str, Any]) -> int:
    market_slug = str(payload.get("market_slug", payload.get("marketSlug", ""))).strip()
    if not market_slug:
        raise ValueError("market_slug is required")
    token_id = str(payload.get("token_id", payload.get("tokenId", ""))).strip() or None
    outcome_label = str(payload.get("outcome_label", payload.get("outcomeLabel", ""))).strip() or None
    token_side = str(payload.get("token_side", payload.get("tokenSide", "YES"))).strip().upper() or "YES"
    if token_side not in {"YES", "NO"}:
        raise ValueError("token_side must be YES or NO")
    price_source = normalize_price_source(payload.get("price_source", payload.get("priceSource", "frontend")))
    backtest_engine = normalize_backtest_engine(
        payload.get("backtest_engine", payload.get("backtestEngine", payload.get("engine", payload.get("framework", "builtin"))))
    )
    params = parse_parameters(payload)
    from_ts = _optional_int(payload.get("from_ts", payload.get("from")))
    to_ts = _optional_int(payload.get("to_ts", payload.get("to")))
    from_block = _optional_int(payload.get("from_block", payload.get("fromBlock")))
    to_block = _optional_int(payload.get("to_block", payload.get("toBlock")))
    execution_context = _execution_context_from_payload(payload)
    parameter_snapshot = backtest_parameter_snapshot(
        market_slug=market_slug,
        token_side=token_side,
        token_id=token_id,
        outcome_label=outcome_label,
        price_source=price_source,
        backtest_engine=backtest_engine,
        from_ts=from_ts,
        to_ts=to_ts,
        from_block=from_block,
        to_block=to_block,
        params=params,
        execution_context=execution_context,
    )
    parameter_fingerprint = backtest_parameter_fingerprint(parameter_snapshot)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO quant.quant_backtest_runs (
                status, market_slug, token_side, price_source, backtest_engine,
                from_ts, to_ts, from_block, to_block, meta
            )
            VALUES ('queued', %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING run_id
            """,
            (
                market_slug,
                token_side,
                price_source,
                backtest_engine,
                from_ts,
                to_ts,
                from_block,
                to_block,
                json.dumps(
                    {
                        "strategy": "fixed_threshold_v1",
                        "backtest_engine": backtest_engine,
                        "token_id": token_id,
                        "outcome_label": outcome_label,
                        "execution_context": execution_context,
                        "parameter_fingerprint": parameter_fingerprint,
                        "parameter_snapshot": parameter_snapshot,
                    }
                ),
            ),
        )
        run_id = int(cur.fetchone()["run_id"])
        cur.execute(
            """
            INSERT INTO quant.quant_backtest_parameters (
                run_id, entry_threshold, exit_threshold, stop_loss, take_profit,
                max_holding_bars, initial_capital, position_size,
                fee_bps, slippage_bps, liquidity_cap_pct
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                params.entry_threshold,
                params.exit_threshold,
                params.stop_loss,
                params.take_profit,
                params.max_holding_bars,
                params.initial_capital,
                params.position_size,
                params.fee_bps,
                params.slippage_bps,
                params.liquidity_cap_pct,
            ),
        )
    upsert_price_build_targets_for_market(
        conn,
        source=price_source,
        market_slug=market_slug,
        token_side=token_side,
        priority=2000,
        reason=target_reason("backtest_requested", {"run_id": run_id}),
        from_ts=from_ts,
        to_ts=to_ts,
        from_block=from_block,
        to_block=to_block,
    )
    return run_id


def execute_backtest_run(conn: Any, run_id: int) -> None:
    run = _get_run(conn, run_id)
    params = _get_parameters(conn, run_id)
    _set_run_status(conn, run_id, "running")
    points = fetch_price_points(conn, run)
    if len(points) < 2:
        raise RuntimeError("not enough price rows for backtest")
    data_quality_report = build_data_quality_report(points, run)
    result = run_framework_backtest(
        run.get("backtest_engine") or "builtin",
        points,
        run,
        params,
        builtin_simulator=simulate_strategy,
        metrics_builder=build_metrics,
    )
    result.setdefault("metrics", [])
    result["metrics"].extend(data_quality_metrics(data_quality_report))
    replace_backtest_results(conn, run_id, result)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quant.quant_backtest_runs
            SET status = 'succeeded',
                rows_processed = %s,
                meta = meta || %s::jsonb,
                finished_at = now(),
                error = NULL
            WHERE run_id = %s
            """,
            (
                len(points),
                json.dumps({"actual_data_quality": data_quality_report}),
                run_id,
            ),
        )


def mark_run_failed(conn: Any, run_id: int, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quant.quant_backtest_runs
            SET status = 'failed', error = %s, finished_at = now()
            WHERE run_id = %s
            """,
            (error[:4000], run_id),
        )


def fetch_price_points(conn: Any, run: dict[str, Any], *, limit: int = 25000) -> list[PricePoint]:
    meta = run.get("meta") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except json.JSONDecodeError:
            meta = {}
    token_id = str(meta.get("token_id") or "").strip()
    if run["price_source"] == "frontend":
        filters: list[str]
        values: list[Any]
        if token_id:
            filters = ["token_id = %s"]
            values = [token_id]
        else:
            filters = ["market_slug = %s", "token_side = %s"]
            values = [run["market_slug"], run["token_side"]]
        if run.get("from_ts") is not None:
            filters.append("timestamp >= %s")
            values.append(run["from_ts"])
        if run.get("to_ts") is not None:
            filters.append("timestamp <= %s")
            values.append(run["to_ts"])
        values.append(limit)
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT timestamp AS x_value, price, 0::numeric AS volume
                FROM quant.market_token_frontend_price_1m
                WHERE {" AND ".join(filters)}
                ORDER BY timestamp ASC
                LIMIT %s
                """,
                values,
            )
            return [_price_point(row) for row in cur.fetchall()]

    if token_id:
        filters = ["token_id = %s"]
        values = [token_id]
    else:
        filters = ["market_slug = %s", "token_side = %s"]
        values = [run["market_slug"], run["token_side"]]
    if run.get("from_block") is not None:
        filters.append("block_number >= %s")
        values.append(run["from_block"])
    if run.get("to_block") is not None:
        filters.append("block_number <= %s")
        values.append(run["to_block"])
    values.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT block_number AS x_value, close_price AS price, volume
            FROM quant.market_token_block_close
            WHERE {" AND ".join(filters)}
            ORDER BY block_number ASC
            LIMIT %s
            """,
            values,
        )
        return [_price_point(row) for row in cur.fetchall()]


def simulate_strategy(points: list[PricePoint], run: dict[str, Any], params: BacktestParameters) -> dict[str, Any]:
    x_axis = "timestamp" if run["price_source"] == "frontend" else "block_number"
    equity = params.initial_capital
    peak = params.initial_capital
    open_position: OpenPosition | None = None
    trades: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []

    for index, point in enumerate(points):
        if open_position is None and point.price >= params.entry_threshold:
            size = _size_for_liquidity(params, point.price, point.volume)
            if size <= 0:
                continue
            open_position = OpenPosition(
                trade_index=len(trades) + 1,
                entry_index=index,
                entry_x=point.x_value,
                entry_price=_execution_price(point.price, params, "entry"),
                size=size,
            )
            events.append(_event("open", x_axis, point.x_value, f"T-{open_position.trade_index:04d}", point.price, "entry threshold reached"))
        elif open_position is not None:
            exit_reason = _exit_reason(point.price, open_position.entry_price, index - open_position.entry_index, params)
            if exit_reason:
                trade = _close_trade(run, x_axis, open_position, point, index, exit_reason, params)
                trades.append(trade)
                equity += trade["pnl"]
                events.append(_event("close", x_axis, point.x_value, trade["trade_id"], point.price, exit_reason))
                open_position = None

        mark_equity = equity
        if open_position is not None:
            mark_equity += (_execution_price(point.price, params, "exit") - open_position.entry_price) * open_position.size
        peak = max(peak, mark_equity)
        drawdown = mark_equity - peak
        equity_rows.append(
            {
                "point_index": index + 1,
                "x_axis": x_axis,
                "x_value": point.x_value,
                "equity": mark_equity,
                "drawdown": drawdown,
                "drawdown_pct": _pct(drawdown, peak),
                "cumulative_return": _pct(mark_equity - params.initial_capital, params.initial_capital),
            }
        )

    if open_position is not None:
        last = points[-1]
        trade = _close_trade(run, x_axis, open_position, last, len(points) - 1, "end_of_data", params)
        trades.append(trade)
        equity += trade["pnl"]
        events.append(_event("close", x_axis, last.x_value, trade["trade_id"], last.price, "end_of_data"))

    metrics = build_metrics(trades, equity_rows, points, params)
    return {"trades": trades, "equity": equity_rows, "metrics": metrics, "events": events}


def build_metrics(
    trades: list[dict[str, Any]],
    equity_rows: list[dict[str, Any]],
    points: list[PricePoint],
    params: BacktestParameters,
) -> list[dict[str, Any]]:
    net = sum((trade["pnl"] for trade in trades), Decimal("0"))
    gross_profit = sum((trade["pnl"] for trade in trades if trade["pnl"] > 0), Decimal("0"))
    gross_loss = sum((trade["pnl"] for trade in trades if trade["pnl"] < 0), Decimal("0"))
    winners = len([trade for trade in trades if trade["pnl"] > 0])
    max_drawdown = min((row["drawdown"] for row in equity_rows), default=Decimal("0"))
    avg_trade = net / Decimal(max(1, len(trades)))
    avg_holding = sum((trade["holding_bars"] for trade in trades), 0) / max(1, len(trades))
    total_return = _pct(net, params.initial_capital)
    profit_factor = gross_profit / abs(gross_loss) if gross_loss else Decimal("0")
    fill_coverage = Decimal(len(points)) / Decimal(max(1, len(points))) * Decimal("100")
    stale_ratio = Decimal("0")
    execution_cost = sum((trade.get("execution_cost", Decimal("0")) for trade in trades), Decimal("0"))
    filled_notional = sum((Decimal(str(trade.get("notional") or 0)) for trade in trades), Decimal("0"))
    requested_notional = params.position_size * Decimal(len(trades))
    liquidity_fill_rate = _pct(filled_notional, requested_notional) if requested_notional else Decimal("0")
    capped_trades = len([
        trade for trade in trades
        if Decimal(str(trade.get("notional") or 0)) < params.position_size * Decimal("0.999")
    ])
    avg_notional = filled_notional / Decimal(max(1, len(trades)))
    settlement_pnl = net if points[-1].price in (Decimal("0"), Decimal("1")) else Decimal("0")
    resolved_pnl = settlement_pnl
    unrealized_pnl = net - resolved_pnl
    rows = [
        ("net_profit", "Net Profit", "overview", net, _money(net), _percent(total_return), _status(net), "Closed realized strategy PnL"),
        ("total_return", "Total Return", "overview", total_return, _percent(total_return), "capital", _status(total_return), "Return on initial capital"),
        ("max_drawdown", "Max Drawdown", "overview", max_drawdown, _money(max_drawdown), _percent(_pct(max_drawdown, params.initial_capital)), "negative", "Largest peak-to-trough equity loss"),
        ("win_rate", "Win Rate", "overview", _ratio(winners, len(trades)) * Decimal("100"), f"{_ratio(winners, len(trades)) * Decimal('100'):.2f}%", f"{winners} / {len(trades)}", "positive" if winners else "neutral", "Percent profitable closed trades"),
        ("profit_factor", "Profit Factor", "overview", profit_factor, f"{profit_factor:.3f}", "gross P/L", "neutral", "Gross profit divided by gross loss"),
        ("total_trades", "Total Trades", "overview", Decimal(len(trades)), str(len(trades)), "closed", "neutral", "Closed strategy trades"),
        ("avg_trade", "Avg Trade", "overview", avg_trade, _money(avg_trade), _percent(_pct(avg_trade, params.initial_capital)), _status(avg_trade), "Average closed trade PnL"),
        ("avg_holding", "Avg Holding", "overview", Decimal(str(avg_holding)), f"{avg_holding:.1f} bars", "bars", "neutral", "Average bars held per trade"),
        ("resolved_pnl", "Resolved PnL", "prediction", resolved_pnl, _money(resolved_pnl), "settled", _status(resolved_pnl), "PnL from resolved markets"),
        ("unrealized_pnl", "Unrealized PnL", "prediction", unrealized_pnl, _money(unrealized_pnl), "pending", _status(unrealized_pnl), "Mark-to-market PnL for unresolved exposure"),
        ("settlement_pnl", "Settlement PnL", "prediction", settlement_pnl, _money(settlement_pnl), "resolution payoff", _status(settlement_pnl), "PnL attributable to final payoff"),
        ("slippage_cost", "Execution Cost", "prediction", -execution_cost, _money(-execution_cost), f"{params.fee_bps} fee bps / {params.slippage_bps} slip bps", "negative" if execution_cost else "neutral", "Modeled fees plus entry/exit slippage"),
        ("liquidity_fill_rate", "Liquidity Fill", "prediction", liquidity_fill_rate, f"{liquidity_fill_rate:.1f}%", f"{_money(filled_notional)} filled", "positive" if liquidity_fill_rate >= Decimal("99") else "negative" if capped_trades else "neutral", "Share of requested USDC notional actually filled after liquidity caps"),
        ("capped_trades", "Capped Trades", "prediction", Decimal(capped_trades), str(capped_trades), f"{_money(avg_notional)} avg fill", "negative" if capped_trades else "positive", "Trades whose filled notional was reduced by volume/liquidity constraints"),
        ("fill_coverage", "Fill Coverage", "prediction", fill_coverage, f"{fill_coverage:.1f}%", "price rows", "positive", "Usable fill price coverage"),
        ("stale_price_ratio", "Stale Price Ratio", "prediction", stale_ratio, f"{stale_ratio:.2f}%", "exact rows", "neutral", "Share of stale/forward-filled prices"),
    ]
    return [
        {
            "metric_key": key,
            "metric_name": name,
            "metric_group": group,
            "value": value,
            "formatted_value": formatted,
            "delta": delta,
            "status": status,
            "tooltip": tooltip,
            "sort_order": index,
        }
        for index, (key, name, group, value, formatted, delta, status, tooltip) in enumerate(rows, start=1)
    ]


def build_data_quality_report(points: list[PricePoint], run: dict[str, Any]) -> dict[str, Any]:
    x_values = [int(point.x_value) for point in points]
    prices = [point.price for point in points]
    deltas = [x_values[index] - x_values[index - 1] for index in range(1, len(x_values)) if x_values[index] > x_values[index - 1]]
    sorted_deltas = sorted(deltas)
    median_delta = sorted_deltas[len(sorted_deltas) // 2] if sorted_deltas else 0
    gap_threshold = int(median_delta * 4) if median_delta else 0
    gaps = [
        {"from_x": x_values[index - 1], "to_x": x_values[index], "span": x_values[index] - x_values[index - 1]}
        for index in range(1, len(x_values))
        if gap_threshold and x_values[index] - x_values[index - 1] > gap_threshold
    ]
    jumps = [
        {
            "x": x_values[index],
            "from_price": _decimal_text(prices[index - 1]),
            "to_price": _decimal_text(prices[index]),
            "delta": _decimal_text((prices[index] - prices[index - 1]).copy_abs()),
        }
        for index in range(1, len(prices))
        if (prices[index] - prices[index - 1]).copy_abs() > Decimal("0.18")
    ]
    requested_from = run.get("from_block") if run.get("price_source") == "orderfilled_block_close" else run.get("from_ts")
    requested_to = run.get("to_block") if run.get("price_source") == "orderfilled_block_close" else run.get("to_ts")
    first_x = x_values[0] if x_values else None
    last_x = x_values[-1] if x_values else None
    requested_span = int(requested_to - requested_from) if requested_from is not None and requested_to is not None and requested_to > requested_from else None
    observed_span = int(last_x - first_x) if first_x is not None and last_x is not None and last_x >= first_x else None
    span_coverage = Decimal(str(observed_span or 0)) / Decimal(str(requested_span)) if requested_span else Decimal("1")
    status = "ready"
    caveats: list[str] = []
    if gaps:
        status = "review"
        caveats.append(f"{len(gaps)} large x-axis gaps")
    if jumps:
        status = "review"
        caveats.append(f"{len(jumps)} price jumps over 18 percentage points")
    if len(points) < 50:
        status = "review"
        caveats.append("fewer than 50 rows")
    if span_coverage < Decimal("0.75"):
        status = "review"
        caveats.append("observed span covers less than 75% of requested range")
    return {
        "status": status,
        "price_source": run.get("price_source"),
        "x_axis": "block_number" if run.get("price_source") == "orderfilled_block_close" else "timestamp",
        "rows": len(points),
        "first_x": first_x,
        "last_x": last_x,
        "median_delta": median_delta,
        "gap_count": len(gaps),
        "gap_threshold": gap_threshold,
        "largest_gaps": gaps[:8],
        "jump_count": len(jumps),
        "largest_jumps": jumps[:8],
        "requested_from": requested_from,
        "requested_to": requested_to,
        "observed_span": observed_span,
        "requested_span": requested_span,
        "span_coverage_pct": _decimal_text((span_coverage * Decimal("100")).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)),
        "caveats": caveats,
    }


def data_quality_metrics(report: dict[str, Any]) -> list[dict[str, Any]]:
    status = "positive" if report.get("status") == "ready" else "negative"
    return [
        {
            "metric_key": "data_quality_status",
            "metric_name": "Data Quality",
            "metric_group": "prediction",
            "value": Decimal("1") if report.get("status") == "ready" else Decimal("0"),
            "formatted_value": str(report.get("status") or "unknown"),
            "delta": f"{report.get('rows', 0)} rows",
            "status": status,
            "tooltip": "; ".join(report.get("caveats") or []) or "No large gaps or jumps detected in the executed price rows",
            "sort_order": 90,
        },
        {
            "metric_key": "gap_count",
            "metric_name": "Gap Count",
            "metric_group": "prediction",
            "value": Decimal(int(report.get("gap_count") or 0)),
            "formatted_value": str(report.get("gap_count") or 0),
            "delta": f"threshold {report.get('gap_threshold') or 0}",
            "status": "negative" if report.get("gap_count") else "positive",
            "tooltip": "Large x-axis gaps detected in the rows used by this backtest",
            "sort_order": 91,
        },
        {
            "metric_key": "jump_count",
            "metric_name": "Jump Count",
            "metric_group": "prediction",
            "value": Decimal(int(report.get("jump_count") or 0)),
            "formatted_value": str(report.get("jump_count") or 0),
            "delta": ">18 pct points",
            "status": "negative" if report.get("jump_count") else "positive",
            "tooltip": "Large adjacent price jumps detected in the rows used by this backtest",
            "sort_order": 92,
        },
        {
            "metric_key": "span_coverage",
            "metric_name": "Span Coverage",
            "metric_group": "prediction",
            "value": Decimal(str(report.get("span_coverage_pct") or "0")),
            "formatted_value": f"{report.get('span_coverage_pct') or '0'}%",
            "delta": f"{report.get('first_x') or '-'} -> {report.get('last_x') or '-'}",
            "status": "positive" if Decimal(str(report.get("span_coverage_pct") or "0")) >= Decimal("75") else "negative",
            "tooltip": "Observed row span compared with the requested backtest range",
            "sort_order": 93,
        },
    ]


def replace_backtest_results(conn: Any, run_id: int, result: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM quant.quant_backtest_metrics WHERE run_id = %s", (run_id,))
        cur.execute("DELETE FROM quant.quant_backtest_equity WHERE run_id = %s", (run_id,))
        cur.execute("DELETE FROM quant.quant_backtest_trades WHERE run_id = %s", (run_id,))
        cur.execute("DELETE FROM quant.quant_backtest_events WHERE run_id = %s", (run_id,))
        cur.executemany(
            """
            INSERT INTO quant.quant_backtest_metrics (
                run_id, metric_key, metric_name, metric_group, value,
                formatted_value, delta, status, tooltip, sort_order
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    run_id,
                    row["metric_key"],
                    row["metric_name"],
                    row["metric_group"],
                    row["value"],
                    row["formatted_value"],
                    row["delta"],
                    row["status"],
                    row["tooltip"],
                    row["sort_order"],
                )
                for row in result["metrics"]
            ],
        )
        cur.executemany(
            """
            INSERT INTO quant.quant_backtest_equity (
                run_id, point_index, x_axis, x_value, equity,
                drawdown, drawdown_pct, cumulative_return
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    run_id,
                    row["point_index"],
                    row["x_axis"],
                    row["x_value"],
                    row["equity"],
                    row["drawdown"],
                    row["drawdown_pct"],
                    row["cumulative_return"],
                )
                for row in result["equity"]
            ],
        )
        cur.executemany(
            """
            INSERT INTO quant.quant_backtest_trades (
                run_id, trade_id, market_slug, token_side, side, x_axis,
                entry_x, exit_x, entry_price, exit_price, size, notional,
                pnl, pnl_pct, holding_bars, exit_reason
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (
                    run_id,
                    row["trade_id"],
                    row["market_slug"],
                    row["token_side"],
                    row["side"],
                    row["x_axis"],
                    row["entry_x"],
                    row["exit_x"],
                    row["entry_price"],
                    row["exit_price"],
                    row["size"],
                    row["notional"],
                    row["pnl"],
                    row["pnl_pct"],
                    row["holding_bars"],
                    row["exit_reason"],
                )
                for row in result["trades"]
            ],
        )
        cur.executemany(
            """
            INSERT INTO quant.quant_backtest_events (
                run_id, event_index, event_type, x_axis, x_value,
                trade_id, price, message, meta
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            [
                (
                    run_id,
                    index,
                    row["event_type"],
                    row["x_axis"],
                    row["x_value"],
                    row["trade_id"],
                    row["price"],
                    row["message"],
                    json.dumps(row["meta"]),
                )
                for index, row in enumerate(result["events"], start=1)
            ],
        )


def get_backtest_run_for_update_free(conn: Any, run_id: int) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM quant.quant_backtest_runs WHERE run_id = %s", (run_id,))
        row = cur.fetchone()
    if not row:
        raise KeyError(f"backtest run not found: {run_id}")
    return dict(row)


def _get_run(conn: Any, run_id: int) -> dict[str, Any]:
    return get_backtest_run_for_update_free(conn, run_id)


def _get_parameters(conn: Any, run_id: int) -> BacktestParameters:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM quant.quant_backtest_parameters WHERE run_id = %s", (run_id,))
        row = cur.fetchone()
    if not row:
        raise KeyError(f"backtest parameters not found: {run_id}")
    return BacktestParameters(
        entry_threshold=row["entry_threshold"],
        exit_threshold=row["exit_threshold"],
        stop_loss=row["stop_loss"],
        take_profit=row["take_profit"],
        max_holding_bars=int(row["max_holding_bars"]),
        initial_capital=row["initial_capital"],
        position_size=row["position_size"],
        fee_bps=row.get("fee_bps", Decimal("0")),
        slippage_bps=row.get("slippage_bps", Decimal("0")),
        liquidity_cap_pct=row.get("liquidity_cap_pct", Decimal("100")),
    )


def _set_run_status(conn: Any, run_id: int, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quant.quant_backtest_runs
            SET status = %s,
                started_at = CASE WHEN started_at IS NULL THEN now() ELSE started_at END
            WHERE run_id = %s
            """,
            (status, run_id),
        )


def _price_point(row: dict[str, Any]) -> PricePoint:
    return PricePoint(
        x_value=int(row["x_value"]),
        price=Decimal(str(row["price"])),
        volume=Decimal(str(row.get("volume") or 0)),
    )


def _exit_reason(price: Decimal, entry_price: Decimal, holding_bars: int, params: BacktestParameters) -> str | None:
    if price <= params.exit_threshold:
        return "exit_threshold"
    if price <= entry_price * (Decimal("1") - params.stop_loss):
        return "stop_loss"
    if price >= entry_price * (Decimal("1") + params.take_profit):
        return "take_profit"
    if holding_bars >= params.max_holding_bars:
        return "max_holding_bars"
    return None


def _close_trade(
    run: dict[str, Any],
    x_axis: str,
    position: OpenPosition,
    point: PricePoint,
    point_index: int,
    exit_reason: str,
    params: BacktestParameters,
) -> dict[str, Any]:
    exit_price = _execution_price(point.price, params, "exit")
    notional = position.entry_price * position.size
    exit_notional = exit_price * position.size
    fee_cost = (notional + exit_notional) * _bps_fraction(params.fee_bps)
    slippage_cost = ((position.entry_price - _execution_price(position.entry_price, params, "raw_entry")) * position.size).copy_abs()
    slippage_cost += ((point.price - exit_price) * position.size).copy_abs()
    execution_cost = fee_cost + slippage_cost
    pnl = (exit_price - position.entry_price) * position.size - fee_cost
    return {
        "trade_id": f"T-{position.trade_index:04d}",
        "market_slug": run["market_slug"],
        "token_side": run["token_side"],
        "side": "LONG",
        "x_axis": x_axis,
        "entry_x": position.entry_x,
        "exit_x": point.x_value,
        "entry_price": position.entry_price,
        "exit_price": exit_price,
        "size": position.size,
        "notional": notional,
        "pnl": pnl.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP),
        "pnl_pct": _pct(pnl, notional),
        "holding_bars": max(1, point_index - position.entry_index),
        "exit_reason": exit_reason,
        "fee_cost": fee_cost.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP),
        "slippage_cost": slippage_cost.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP),
        "execution_cost": execution_cost.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP),
    }


def _event(event_type: str, x_axis: str, x_value: int, trade_id: str, price: Decimal, message: str) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "x_axis": x_axis,
        "x_value": x_value,
        "trade_id": trade_id,
        "price": price,
        "message": message,
        "meta": {},
    }


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value))
    except Exception:
        return None


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if not denominator:
        return Decimal("0")
    return (numerator / denominator * Decimal("100")).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _bps_fraction(value: Decimal) -> Decimal:
    return max(Decimal("0"), Decimal(str(value))) / Decimal("10000")


def _execution_price(price: Decimal, params: BacktestParameters, side: str) -> Decimal:
    if side == "raw_entry":
        fraction = _bps_fraction(params.slippage_bps)
        if fraction <= 0:
            return price
        return (price / (Decimal("1") + fraction)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
    fraction = _bps_fraction(params.slippage_bps)
    if side == "entry":
        return min(Decimal("0.9999999999"), price * (Decimal("1") + fraction)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
    return max(Decimal("0"), price * (Decimal("1") - fraction)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _size_for_liquidity(params: BacktestParameters, price: Decimal, volume: Decimal) -> Decimal:
    if price <= 0:
        return Decimal("0")
    cap_pct = max(Decimal("0"), Decimal(str(params.liquidity_cap_pct)))
    if cap_pct <= 0:
        return Decimal("0")
    target_notional = max(Decimal("0"), Decimal(str(params.position_size)))
    if volume <= 0:
        return (target_notional / price).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
    capped_notional = min(target_notional, volume * cap_pct / Decimal("100"))
    return (capped_notional / price).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if not denominator:
        return Decimal("0")
    return Decimal(numerator) / Decimal(denominator)


def _money(value: Decimal) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):,} USDC"


def _percent(value: Decimal) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def _status(value: Decimal) -> str:
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"
