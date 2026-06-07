"""Fixed-template quant backtest engine.

This first production pass intentionally keeps the strategy small: one long
position template, two price sources, and durable run/result tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
from typing import Any

from .build_targets import target_reason, upsert_price_build_targets_for_market


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
    )


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
    token_side = str(payload.get("token_side", payload.get("tokenSide", "YES"))).strip().upper() or "YES"
    if token_side not in {"YES", "NO"}:
        raise ValueError("token_side must be YES or NO")
    price_source = normalize_price_source(payload.get("price_source", payload.get("priceSource", "frontend")))
    params = parse_parameters(payload)
    from_ts = _optional_int(payload.get("from_ts", payload.get("from")))
    to_ts = _optional_int(payload.get("to_ts", payload.get("to")))
    from_block = _optional_int(payload.get("from_block", payload.get("fromBlock")))
    to_block = _optional_int(payload.get("to_block", payload.get("toBlock")))
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO quant.quant_backtest_runs (
                status, market_slug, token_side, price_source,
                from_ts, to_ts, from_block, to_block, meta
            )
            VALUES ('queued', %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING run_id
            """,
            (
                market_slug,
                token_side,
                price_source,
                from_ts,
                to_ts,
                from_block,
                to_block,
                json.dumps({"strategy": "fixed_threshold_v1"}),
            ),
        )
        run_id = int(cur.fetchone()["run_id"])
        cur.execute(
            """
            INSERT INTO quant.quant_backtest_parameters (
                run_id, entry_threshold, exit_threshold, stop_loss, take_profit,
                max_holding_bars, initial_capital, position_size
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
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
    result = simulate_strategy(points, run, params)
    replace_backtest_results(conn, run_id, result)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE quant.quant_backtest_runs
            SET status = 'succeeded',
                rows_processed = %s,
                finished_at = now(),
                error = NULL
            WHERE run_id = %s
            """,
            (len(points), run_id),
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
    if run["price_source"] == "frontend":
        filters = ["market_slug = %s", "token_side = %s"]
        values: list[Any] = [run["market_slug"], run["token_side"]]
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
            open_position = OpenPosition(
                trade_index=len(trades) + 1,
                entry_index=index,
                entry_x=point.x_value,
                entry_price=point.price,
                size=params.position_size,
            )
            events.append(_event("open", x_axis, point.x_value, f"T-{open_position.trade_index:04d}", point.price, "entry threshold reached"))
        elif open_position is not None:
            exit_reason = _exit_reason(point.price, open_position.entry_price, index - open_position.entry_index, params)
            if exit_reason:
                trade = _close_trade(run, x_axis, open_position, point, index, exit_reason)
                trades.append(trade)
                equity += trade["pnl"]
                events.append(_event("close", x_axis, point.x_value, trade["trade_id"], point.price, exit_reason))
                open_position = None

        mark_equity = equity
        if open_position is not None:
            mark_equity += (point.price - open_position.entry_price) * open_position.size
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
        trade = _close_trade(run, x_axis, open_position, last, len(points) - 1, "end_of_data")
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
    slippage_cost = abs(net) * Decimal("-0.004")
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
        ("slippage_cost", "Slippage Cost", "prediction", slippage_cost, _money(slippage_cost), "0.4% model", "negative", "Estimated execution cost placeholder"),
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
) -> dict[str, Any]:
    pnl = (point.price - position.entry_price) * position.size
    notional = position.entry_price * position.size
    return {
        "trade_id": f"T-{position.trade_index:04d}",
        "market_slug": run["market_slug"],
        "token_side": run["token_side"],
        "side": "LONG",
        "x_axis": x_axis,
        "entry_x": position.entry_x,
        "exit_x": point.x_value,
        "entry_price": position.entry_price,
        "exit_price": point.price,
        "size": position.size,
        "notional": notional,
        "pnl": pnl.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP),
        "pnl_pct": _pct(pnl, notional),
        "holding_bars": max(1, point_index - position.entry_index),
        "exit_reason": exit_reason,
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
