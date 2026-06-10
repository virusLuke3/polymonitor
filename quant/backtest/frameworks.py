"""Backtest framework adapters for quant price rows.

The production tables use one result shape regardless of the execution engine.
This module keeps framework-specific imports and bar conversion out of the
database runner so queued jobs can switch engines per run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any, Callable


SUPPORTED_BACKTEST_ENGINES = {"builtin", "backtrader", "nautilus_trader"}


@dataclass
class AdapterPosition:
    trade_index: int
    entry_index: int
    entry_x: int
    entry_price: Decimal
    size: Decimal


def normalize_backtest_engine(value: Any) -> str:
    text = str(value or "builtin").strip().lower().replace("-", "_")
    aliases = {
        "": "builtin",
        "internal": "builtin",
        "fixed_threshold": "builtin",
        "fixed_threshold_v1": "builtin",
        "native": "builtin",
        "bt": "backtrader",
        "back_trader": "backtrader",
        "mementum_backtrader": "backtrader",
        "nautilus": "nautilus_trader",
        "nautilus_trader": "nautilus_trader",
        "nautech_nautilus_trader": "nautilus_trader",
    }
    engine = aliases.get(text, text)
    if engine not in SUPPORTED_BACKTEST_ENGINES:
        raise ValueError(f"unsupported backtest_engine: {value!r}")
    return engine


def run_framework_backtest(
    engine: str,
    points: list[Any],
    run: dict[str, Any],
    params: Any,
    *,
    builtin_simulator: Callable[[list[Any], dict[str, Any], Any], dict[str, Any]],
    metrics_builder: Callable[[list[dict[str, Any]], list[dict[str, Any]], list[Any], Any], list[dict[str, Any]]],
) -> dict[str, Any]:
    """Execute a normalized quant backtest with the requested framework."""

    engine = normalize_backtest_engine(engine)
    if engine == "builtin":
        result = builtin_simulator(points, run, params)
    elif engine == "backtrader":
        result = _run_backtrader(points, run, params, metrics_builder)
    elif engine == "nautilus_trader":
        result = _run_nautilus_trader(points, run, params, metrics_builder)
    else:  # pragma: no cover - guarded by normalize_backtest_engine
        raise ValueError(f"unsupported backtest_engine: {engine!r}")
    _annotate_result(result, engine)
    return result


def _run_backtrader(
    points: list[Any],
    run: dict[str, Any],
    params: Any,
    metrics_builder: Callable[[list[dict[str, Any]], list[dict[str, Any]], list[Any], Any], list[dict[str, Any]]],
) -> dict[str, Any]:
    bt = _import_external_package("backtrader", env_var="POLYDATA_BACKTRADER_PATH", repo_name="backtrader")
    try:
        import pandas as pd
    except Exception as exc:  # pragma: no cover - depends on deployment env
        raise RuntimeError("backtrader engine requires pandas to build the in-memory bar feed") from exc

    frame = pd.DataFrame(
        {
            "open": [float(point.price) for point in points],
            "high": [float(point.price) for point in points],
            "low": [float(point.price) for point in points],
            "close": [float(point.price) for point in points],
            "volume": [float(point.volume) for point in points],
        },
        index=pd.date_range("2000-01-01", periods=len(points), freq="min", tz="UTC"),
    )
    data = bt.feeds.PandasData(dataname=frame)
    x_values = [int(point.x_value) for point in points]
    x_axis = _x_axis(run)
    quant_params = params

    class QuantThresholdStrategy(bt.Strategy):  # type: ignore[misc]
        params = (
            ("x_values", x_values),
            ("x_axis", x_axis),
            ("run_row", run),
            ("quant_params", quant_params),
            ("price_points", points),
            ("metrics_builder", metrics_builder),
        )

        def __init__(self) -> None:
            self.open_position: AdapterPosition | None = None
            self.trades: list[dict[str, Any]] = []
            self.events: list[dict[str, Any]] = []
            self.equity_rows: list[dict[str, Any]] = []
            self.realized_equity = self.p.quant_params.initial_capital
            self.peak_equity = self.p.quant_params.initial_capital

        def next(self) -> None:
            index = len(self.data) - 1
            x_value = int(self.p.x_values[index])
            price = Decimal(str(self.data.close[0]))
            if self.open_position is None and price >= self.p.quant_params.entry_threshold:
                size = _size_for_liquidity(self.p.quant_params, price, Decimal(str(self.data.volume[0])))
                if size <= 0:
                    self._record_equity(index, x_value, price)
                    return
                self.open_position = AdapterPosition(
                    trade_index=len(self.trades) + 1,
                    entry_index=index,
                    entry_x=x_value,
                    entry_price=_execution_price(price, self.p.quant_params, "entry"),
                    size=size,
                )
                self.events.append(_event("open", self.p.x_axis, x_value, f"T-{self.open_position.trade_index:04d}", price, "entry threshold reached"))
            elif self.open_position is not None:
                exit_reason = _exit_reason(price, self.open_position.entry_price, index - self.open_position.entry_index, self.p.quant_params)
                if exit_reason:
                    trade = _close_trade(self.p.run_row, self.p.x_axis, self.open_position, x_value, price, index, exit_reason, self.p.quant_params)
                    self.trades.append(trade)
                    self.realized_equity += trade["pnl"]
                    self.events.append(_event("close", self.p.x_axis, x_value, trade["trade_id"], price, exit_reason))
                    self.open_position = None
            self._record_equity(index, x_value, price)

        def stop(self) -> None:
            if self.open_position is not None:
                index = len(self.p.price_points) - 1
                point = self.p.price_points[index]
                trade = _close_trade(self.p.run_row, self.p.x_axis, self.open_position, int(point.x_value), point.price, index, "end_of_data", self.p.quant_params)
                self.trades.append(trade)
                self.realized_equity += trade["pnl"]
                self.events.append(_event("close", self.p.x_axis, int(point.x_value), trade["trade_id"], point.price, "end_of_data"))
                self.open_position = None
            self.result = {
                "trades": self.trades,
                "equity": self.equity_rows,
                "metrics": self.p.metrics_builder(self.trades, self.equity_rows, self.p.price_points, self.p.quant_params),
                "events": self.events,
            }

        def _record_equity(self, index: int, x_value: int, price: Decimal) -> None:
            mark_equity = self.realized_equity
            if self.open_position is not None:
                mark_equity += (_execution_price(price, self.p.quant_params, "exit") - self.open_position.entry_price) * self.open_position.size
            self.peak_equity = max(self.peak_equity, mark_equity)
            drawdown = mark_equity - self.peak_equity
            self.equity_rows.append(
                {
                    "point_index": index + 1,
                    "x_axis": self.p.x_axis,
                    "x_value": x_value,
                    "equity": mark_equity,
                    "drawdown": drawdown,
                    "drawdown_pct": _pct(drawdown, self.peak_equity),
                    "cumulative_return": _pct(mark_equity - self.p.quant_params.initial_capital, self.p.quant_params.initial_capital),
                }
            )

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(data)
    cerebro.addstrategy(QuantThresholdStrategy)
    strategies = cerebro.run()
    if not strategies or strategies[0] is None:
        raise RuntimeError("backtrader did not return a completed strategy")
    return strategies[0].result


def _run_nautilus_trader(
    points: list[Any],
    run: dict[str, Any],
    params: Any,
    metrics_builder: Callable[[list[dict[str, Any]], list[dict[str, Any]], list[Any], Any], list[dict[str, Any]]],
) -> dict[str, Any]:
    if sys.version_info < (3, 12):
        return _run_nautilus_trader_subprocess(points, run, params)

    _import_external_package("nautilus_trader", env_var="POLYDATA_NAUTILUS_TRADER_PATH", repo_name="nautilus_trader")
    try:
        from nautilus_trader.backtest.engine import BacktestEngine
        from nautilus_trader.config import BacktestEngineConfig, LoggingConfig, StrategyConfig
        from nautilus_trader.core.datetime import dt_to_unix_nanos
        from nautilus_trader.model.currencies import USD
        from nautilus_trader.model.data import Bar, BarSpecification, BarType
        from nautilus_trader.model.enums import AccountType, BarAggregation, OmsType, PriceType
        from nautilus_trader.model.identifiers import InstrumentId, Venue
        from nautilus_trader.model.objects import Money, Quantity
        from nautilus_trader.test_kit.providers import TestInstrumentProvider
        from nautilus_trader.trading.strategy import Strategy
    except Exception as exc:  # pragma: no cover - depends on installed wheel/Python version
        raise RuntimeError(
            "nautilus_trader engine requires a working nautilus_trader install "
            "(Python 3.12+ wheels or a built source checkout)"
        ) from exc

    x_values = [int(point.x_value) for point in points]
    x_axis = _x_axis(run)
    venue = Venue("SIM")
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD", venue)
    bar_type = BarType(
        instrument_id=instrument.id,
        bar_spec=BarSpecification(step=1, aggregation=BarAggregation.MINUTE, price_type=PriceType.LAST),
    )
    base_dt = datetime(2000, 1, 1, tzinfo=timezone.utc)
    bars = []
    for index, point in enumerate(points):
        timestamp_ns = dt_to_unix_nanos(base_dt + timedelta(minutes=index))
        price = instrument.make_price(point.price)
        bars.append(
            Bar(
                bar_type=bar_type,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=Quantity.from_str(str(max(Decimal("0"), point.volume))),
                ts_event=timestamp_ns,
                ts_init=timestamp_ns,
            )
        )

    class QuantThresholdConfig(StrategyConfig, frozen=True):
        instrument_id: InstrumentId
        bar_type: BarType
        x_values: list[int]
        x_axis: str
        run_row: dict[str, Any]
        quant_params: Any
        price_points: list[Any]
        metrics_builder: Any

    class QuantThresholdStrategy(Strategy):  # type: ignore[misc]
        def __init__(self, config: QuantThresholdConfig):
            super().__init__(config)
            self.index = -1
            self.open_position: AdapterPosition | None = None
            self.trades: list[dict[str, Any]] = []
            self.events: list[dict[str, Any]] = []
            self.equity_rows: list[dict[str, Any]] = []
            self.realized_equity = config.quant_params.initial_capital
            self.peak_equity = config.quant_params.initial_capital

        def on_start(self) -> None:
            self.subscribe_bars(self.config.bar_type)

        def on_bar(self, bar: Bar) -> None:
            self.index += 1
            x_value = int(self.config.x_values[self.index])
            price = Decimal(str(bar.close))
            if self.open_position is None and price >= self.config.quant_params.entry_threshold:
                volume = Decimal(str(getattr(bar, "volume", 0) or 0))
                size = _size_for_liquidity(self.config.quant_params, price, volume)
                if size <= 0:
                    self._record_equity(x_value, price)
                    return
                self.open_position = AdapterPosition(len(self.trades) + 1, self.index, x_value, _execution_price(price, self.config.quant_params, "entry"), size)
                self.events.append(_event("open", self.config.x_axis, x_value, f"T-{self.open_position.trade_index:04d}", price, "entry threshold reached"))
            elif self.open_position is not None:
                exit_reason = _exit_reason(price, self.open_position.entry_price, self.index - self.open_position.entry_index, self.config.quant_params)
                if exit_reason:
                    trade = _close_trade(self.config.run_row, self.config.x_axis, self.open_position, x_value, price, self.index, exit_reason, self.config.quant_params)
                    self.trades.append(trade)
                    self.realized_equity += trade["pnl"]
                    self.events.append(_event("close", self.config.x_axis, x_value, trade["trade_id"], price, exit_reason))
                    self.open_position = None
            self._record_equity(x_value, price)

        def on_stop(self) -> None:
            if self.open_position is not None:
                point = self.config.price_points[-1]
                trade = _close_trade(self.config.run_row, self.config.x_axis, self.open_position, int(point.x_value), point.price, len(self.config.price_points) - 1, "end_of_data", self.config.quant_params)
                self.trades.append(trade)
                self.realized_equity += trade["pnl"]
                self.events.append(_event("close", self.config.x_axis, int(point.x_value), trade["trade_id"], point.price, "end_of_data"))
                self.open_position = None
            self.result = {
                "trades": self.trades,
                "equity": self.equity_rows,
                "metrics": self.config.metrics_builder(self.trades, self.equity_rows, self.config.price_points, self.config.quant_params),
                "events": self.events,
            }

        def _record_equity(self, x_value: int, price: Decimal) -> None:
            mark_equity = self.realized_equity
            if self.open_position is not None:
                mark_equity += (_execution_price(price, self.config.quant_params, "exit") - self.open_position.entry_price) * self.open_position.size
            self.peak_equity = max(self.peak_equity, mark_equity)
            drawdown = mark_equity - self.peak_equity
            self.equity_rows.append(
                {
                    "point_index": self.index + 1,
                    "x_axis": self.config.x_axis,
                    "x_value": x_value,
                    "equity": mark_equity,
                    "drawdown": drawdown,
                    "drawdown_pct": _pct(drawdown, self.peak_equity),
                    "cumulative_return": _pct(mark_equity - self.config.quant_params.initial_capital, self.config.quant_params.initial_capital),
                }
            )

    engine = BacktestEngine(config=BacktestEngineConfig(logging=LoggingConfig(log_level="ERROR")))
    try:
        engine.add_venue(
            venue=venue,
            oms_type=OmsType.NETTING,
            account_type=AccountType.MARGIN,
            starting_balances=[Money(params.initial_capital, USD)],
            base_currency=USD,
        )
        engine.add_instrument(instrument)
        engine.add_data(bars)
        strategy = QuantThresholdStrategy(
            QuantThresholdConfig(
                instrument_id=instrument.id,
                bar_type=bar_type,
                x_values=x_values,
                x_axis=x_axis,
                run_row=run,
                quant_params=params,
                price_points=points,
                metrics_builder=metrics_builder,
            )
        )
        engine.add_strategy(strategy)
        engine.run()
        return strategy.result
    finally:
        engine.dispose()


def _run_nautilus_trader_subprocess(points: list[Any], run: dict[str, Any], params: Any) -> dict[str, Any]:
    python_bin = _nautilus_python_bin()
    payload = {
        "points": [
            {
                "x_value": int(point.x_value),
                "price": str(point.price),
                "volume": str(point.volume),
            }
            for point in points
        ],
        "run": run,
        "params": {
            "entry_threshold": str(params.entry_threshold),
            "exit_threshold": str(params.exit_threshold),
            "stop_loss": str(params.stop_loss),
            "take_profit": str(params.take_profit),
            "max_holding_bars": int(params.max_holding_bars),
            "initial_capital": str(params.initial_capital),
            "position_size": str(params.position_size),
            "fee_bps": str(getattr(params, "fee_bps", "0")),
            "slippage_bps": str(getattr(params, "slippage_bps", "0")),
            "liquidity_cap_pct": str(getattr(params, "liquidity_cap_pct", "100")),
        },
    }
    project_root = Path(__file__).resolve().parents[2]
    worker = Path(__file__).resolve().parent / "nautilus_worker.py"
    with tempfile.TemporaryDirectory(prefix="quant-nautilus-") as tmpdir:
        input_path = Path(tmpdir) / "input.json"
        output_path = Path(tmpdir) / "output.json"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        completed = subprocess.run(
            [str(python_bin), str(worker), str(input_path), str(output_path)],
            cwd=str(project_root),
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            error = (completed.stderr or completed.stdout or "nautilus worker failed").strip()
            raise RuntimeError(error[:4000])
        if not output_path.exists():
            raise RuntimeError("nautilus worker did not write an output file")
        return _decode_result(json.loads(output_path.read_text(encoding="utf-8")))


def _nautilus_python_bin() -> Path:
    configured = os.environ.get("POLYDATA_NAUTILUS_PYTHON")
    candidates = [
        Path(configured).expanduser() if configured else None,
        Path.home() / ".conda/envs/polymonitor-nautilus312/bin/python",
        Path("/opt/anaconda3/envs/polymonitor-nautilus312/bin/python"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate.resolve()
    raise RuntimeError(
        "nautilus_trader requires a Python 3.12 runtime. Set POLYDATA_NAUTILUS_PYTHON "
        "to the conda env python path."
    )


_DECIMAL_RESULT_KEYS = {
    "price",
    "equity",
    "drawdown",
    "drawdown_pct",
    "cumulative_return",
    "value",
    "entry_price",
    "exit_price",
    "size",
    "notional",
    "pnl",
    "pnl_pct",
}


def _decode_result(value: Any, key: str | None = None) -> Any:
    if isinstance(value, list):
        return [_decode_result(item, key) for item in value]
    if isinstance(value, dict):
        return {item_key: _decode_result(item_value, item_key) for item_key, item_value in value.items()}
    if key in _DECIMAL_RESULT_KEYS and value is not None:
        return Decimal(str(value))
    return value


def _import_external_package(package_name: str, *, env_var: str, repo_name: str) -> Any:
    vendor_path = _vendor_package_parent(package_name)
    if vendor_path and str(vendor_path) not in sys.path:
        sys.path.insert(0, str(vendor_path))
    try:
        return importlib.import_module(package_name)
    except Exception as first_exc:
        repo_path = _external_repo_path(env_var, repo_name)
        if repo_path and str(repo_path) not in sys.path:
            sys.path.insert(0, str(repo_path))
        try:
            return importlib.import_module(package_name)
        except Exception as second_exc:
            raise RuntimeError(
                f"{package_name} is not importable. Install it in this Python environment "
                f"or set {env_var} to the cloned repository path."
            ) from second_exc if repo_path else first_exc


def _vendor_package_parent(package_name: str) -> Path | None:
    vendor_parent = Path(__file__).resolve().parent / "vendor"
    package_dir = vendor_parent / package_name
    if (package_dir / "__init__.py").exists():
        return vendor_parent
    return None


def _external_repo_path(env_var: str, repo_name: str) -> Path | None:
    configured = os.environ.get(env_var)
    if configured:
        path = Path(configured).expanduser().resolve()
        return path if path.exists() else None
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / repo_name
        if candidate.exists():
            return candidate
        sibling = parent.parent / repo_name
        if sibling.exists():
            return sibling
    return None


def _annotate_result(result: dict[str, Any], engine: str) -> None:
    events = result.setdefault("events", [])
    events.insert(0, _event("framework", "engine", 0, None, Decimal("0"), f"backtest engine: {engine}"))
    metrics = result.setdefault("metrics", [])
    metrics.append(
        {
            "metric_key": "backtest_engine",
            "metric_name": "Backtest Engine",
            "metric_group": "system",
            "value": Decimal("0"),
            "formatted_value": engine,
            "delta": "framework",
            "status": "neutral",
            "tooltip": "Execution framework selected for this run",
            "sort_order": 10_000,
        }
    )


def _x_axis(run: dict[str, Any]) -> str:
    return "timestamp" if run["price_source"] == "frontend" else "block_number"


def _exit_reason(price: Decimal, entry_price: Decimal, holding_bars: int, params: Any) -> str | None:
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
    position: AdapterPosition,
    exit_x: int,
    exit_price: Decimal,
    point_index: int,
    exit_reason: str,
    params: Any,
) -> dict[str, Any]:
    fill_exit_price = _execution_price(exit_price, params, "exit")
    notional = position.entry_price * position.size
    exit_notional = fill_exit_price * position.size
    fee_cost = (notional + exit_notional) * _bps_fraction(getattr(params, "fee_bps", Decimal("0")))
    slippage_cost = ((position.entry_price - _execution_price(position.entry_price, params, "raw_entry")) * position.size).copy_abs()
    slippage_cost += ((exit_price - fill_exit_price) * position.size).copy_abs()
    execution_cost = fee_cost + slippage_cost
    pnl = (fill_exit_price - position.entry_price) * position.size - fee_cost
    return {
        "trade_id": f"T-{position.trade_index:04d}",
        "market_slug": run["market_slug"],
        "token_side": run["token_side"],
        "side": "LONG",
        "x_axis": x_axis,
        "entry_x": position.entry_x,
        "exit_x": exit_x,
        "entry_price": position.entry_price,
        "exit_price": fill_exit_price,
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


def _event(event_type: str, x_axis: str, x_value: int, trade_id: str | None, price: Decimal, message: str) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "x_axis": x_axis,
        "x_value": x_value,
        "trade_id": trade_id,
        "price": price,
        "message": message,
        "meta": {},
    }


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if not denominator:
        return Decimal("0")
    return (numerator / denominator * Decimal("100")).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _bps_fraction(value: Any) -> Decimal:
    return max(Decimal("0"), Decimal(str(value or "0"))) / Decimal("10000")


def _execution_price(price: Decimal, params: Any, side: str) -> Decimal:
    fraction = _bps_fraction(getattr(params, "slippage_bps", Decimal("0")))
    if side == "raw_entry":
        if fraction <= 0:
            return price
        return (price / (Decimal("1") + fraction)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
    if side == "entry":
        return min(Decimal("0.9999999999"), price * (Decimal("1") + fraction)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
    return max(Decimal("0"), price * (Decimal("1") - fraction)).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


def _size_for_liquidity(params: Any, price: Decimal, volume: Decimal) -> Decimal:
    if price <= 0:
        return Decimal("0")
    cap_pct = max(Decimal("0"), Decimal(str(getattr(params, "liquidity_cap_pct", "100"))))
    if cap_pct <= 0:
        return Decimal("0")
    target_notional = max(Decimal("0"), Decimal(str(getattr(params, "position_size", "0"))))
    if volume <= 0:
        return (target_notional / price).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
    capped_notional = min(target_notional, volume * cap_pct / Decimal("100"))
    return (capped_notional / price).quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)
