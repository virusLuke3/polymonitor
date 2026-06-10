from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from quant.backtest.backtest_engine import BacktestParameters, PricePoint, build_data_quality_report, data_quality_metrics, simulate_strategy
from quant.backtest.frameworks import normalize_backtest_engine, run_framework_backtest
from quant.backtest.frameworks import _nautilus_python_bin


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_normalize_backtest_engine_aliases():
    assert normalize_backtest_engine(None) == "builtin"
    assert normalize_backtest_engine("fixed-threshold-v1") == "builtin"
    assert normalize_backtest_engine("bt") == "backtrader"
    assert normalize_backtest_engine("nautilus") == "nautilus_trader"


def test_normalize_backtest_engine_rejects_unknown():
    with pytest.raises(ValueError):
        normalize_backtest_engine("zipline")


def test_builtin_framework_runs_and_annotates_result():
    points = [
        PricePoint(x_value=1, price=Decimal("0.60"), volume=Decimal("10")),
        PricePoint(x_value=2, price=Decimal("0.70"), volume=Decimal("10")),
        PricePoint(x_value=3, price=Decimal("0.50"), volume=Decimal("10")),
    ]
    run = {
        "market_slug": "demo-market",
        "token_side": "YES",
        "price_source": "orderfilled_block_close",
    }
    params = BacktestParameters(
        entry_threshold=Decimal("0.58"),
        exit_threshold=Decimal("0.55"),
        stop_loss=Decimal("0.50"),
        take_profit=Decimal("0.50"),
        max_holding_bars=10,
        initial_capital=Decimal("1000"),
        position_size=Decimal("100"),
        execution_price_mode="LEGACY",
    )

    result = run_framework_backtest(
        "builtin",
        points,
        run,
        params,
        builtin_simulator=simulate_strategy,
        metrics_builder=lambda trades, equity, price_points, parameters: [],
    )

    assert result["trades"][0]["exit_reason"] == "exit_threshold"
    assert result["events"][0]["event_type"] == "framework"
    engine_metric = next(row for row in result["metrics"] if row["metric_key"] == "backtest_engine")
    assert engine_metric["formatted_value"] == "builtin"


def test_builtin_framework_applies_execution_costs_and_liquidity_cap():
    points = [
        PricePoint(x_value=1, price=Decimal("0.60"), volume=Decimal("40")),
        PricePoint(x_value=2, price=Decimal("0.70"), volume=Decimal("40")),
        PricePoint(x_value=3, price=Decimal("0.50"), volume=Decimal("40")),
    ]
    run = {
        "market_slug": "demo-market",
        "token_side": "YES",
        "price_source": "orderfilled_block_close",
    }
    params = BacktestParameters(
        entry_threshold=Decimal("0.58"),
        exit_threshold=Decimal("0.55"),
        stop_loss=Decimal("0.50"),
        take_profit=Decimal("0.50"),
        max_holding_bars=10,
        initial_capital=Decimal("1000"),
        position_size=Decimal("100"),
        fee_bps=Decimal("10"),
        slippage_bps=Decimal("20"),
        liquidity_cap_pct=Decimal("50"),
        execution_price_mode="LEGACY",
    )

    result = run_framework_backtest(
        "builtin",
        points,
        run,
        params,
        builtin_simulator=simulate_strategy,
        metrics_builder=lambda trades, equity, price_points, parameters: [],
    )

    trade = result["trades"][0]
    assert trade["size"] == Decimal("33.3333333333")
    assert trade["entry_price"] > Decimal("0.60")
    assert trade["exit_price"] < Decimal("0.50")
    assert trade["execution_cost"] > Decimal("0")
    assert trade["requested_notional"] == Decimal("100")
    assert trade["filled_notional"] == Decimal("20.0000000000")
    assert trade["fill_pct"] == Decimal("20.0000000000")
    assert trade["pnl"] < Decimal("-2")


def test_builtin_framework_rejects_entry_when_min_fill_not_met():
    points = [
        PricePoint(x_value=1, price=Decimal("0.60"), volume=Decimal("20")),
        PricePoint(x_value=2, price=Decimal("0.70"), volume=Decimal("20")),
        PricePoint(x_value=3, price=Decimal("0.50"), volume=Decimal("20")),
    ]
    run = {
        "market_slug": "demo-market",
        "token_side": "YES",
        "price_source": "orderfilled_block_close",
    }
    params = BacktestParameters(
        entry_threshold=Decimal("0.58"),
        exit_threshold=Decimal("0.55"),
        stop_loss=Decimal("0.50"),
        take_profit=Decimal("0.50"),
        max_holding_bars=10,
        initial_capital=Decimal("1000"),
        position_size=Decimal("100"),
        liquidity_cap_pct=Decimal("50"),
        max_position_notional=Decimal("80"),
        min_fill_pct=Decimal("20"),
        execution_price_mode="LEGACY",
    )

    result = run_framework_backtest(
        "builtin",
        points,
        run,
        params,
        builtin_simulator=simulate_strategy,
        metrics_builder=lambda trades, equity, price_points, parameters: [],
    )

    assert result["trades"] == []
    rejected = next(event for event in result["events"] if event["event_type"] == "fill_rejected")
    assert rejected["meta"]["requested_notional"] == Decimal("80")
    assert rejected["meta"]["fill_pct"] == Decimal("12.5000000000")


def test_builtin_framework_defaults_to_orderfilled_probability_fill():
    points = [
        PricePoint(x_value=1, price=Decimal("0.60"), volume=Decimal("40"), trade_count=4),
        PricePoint(x_value=2, price=Decimal("0.50"), volume=Decimal("20"), trade_count=2),
    ]
    run = {
        "market_slug": "demo-market",
        "token_side": "YES",
        "price_source": "orderfilled_block_close",
    }
    params = BacktestParameters(
        entry_threshold=Decimal("0.58"),
        exit_threshold=Decimal("0.55"),
        stop_loss=Decimal("0.50"),
        take_profit=Decimal("0.50"),
        max_holding_bars=10,
        initial_capital=Decimal("1000"),
        position_size=Decimal("100"),
        liquidity_cap_pct=Decimal("50"),
        min_fill_pct=Decimal("0"),
    )

    result = run_framework_backtest(
        "builtin",
        points,
        run,
        params,
        builtin_simulator=simulate_strategy,
        metrics_builder=lambda trades, equity, price_points, parameters: [],
    )

    open_event = next(event for event in result["events"] if event["event_type"] == "open")
    trade = result["trades"][0]
    assert open_event["meta"]["execution_source"] == "orderfilled_volume"
    assert open_event["meta"]["fill_probability"] == Decimal("20.0000000000")
    assert open_event["meta"]["block_volume"] == Decimal("40")
    assert open_event["meta"]["trade_count"] == 4
    assert trade["execution_source"] == "orderfilled_volume"
    assert Decimal("59.9") < trade["fill_probability"] < Decimal("60.1")
    assert trade["fill_status"] == "PARTIAL"


def test_builtin_framework_uses_clob_snapshot_depth_for_entry_fill():
    points = [
        PricePoint(x_value=100, price=Decimal("0.60"), volume=Decimal("10000"), timestamp=_dt("2026-06-10T00:00:30Z")),
        PricePoint(x_value=110, price=Decimal("0.50"), volume=Decimal("10000"), timestamp=_dt("2026-06-10T00:01:30Z")),
    ]
    run = {
        "market_slug": "demo-market",
        "token_side": "YES",
        "price_source": "orderfilled_block_close",
        "_clob_snapshots": [{
            "snapshot_id": 123,
            "token_id": "token-1",
            "side": "YES",
            "block_number": 100,
            "timestamp": "2026-06-10T00:00:00Z",
            "snapshot_version": "v-entry",
            "best_bid": "0.58",
            "best_ask": "0.62",
            "spread": "0.04",
            "asks": [
                {"price": "0.62", "size": "50"},
                {"price": "0.64", "size": "200"},
            ],
            "bids": [
                {"price": "0.58", "size": "200"},
            ],
        }],
    }
    params = BacktestParameters(
        entry_threshold=Decimal("0.58"),
        exit_threshold=Decimal("0.55"),
        stop_loss=Decimal("0.50"),
        take_profit=Decimal("0.50"),
        max_holding_bars=10,
        initial_capital=Decimal("1000"),
        position_size=Decimal("100"),
        liquidity_cap_pct=Decimal("100"),
        max_book_staleness_seconds=Decimal("900"),
        execution_price_mode="DEPTH",
    )

    result = run_framework_backtest(
        "builtin",
        points,
        run,
        params,
        builtin_simulator=simulate_strategy,
        metrics_builder=lambda trades, equity, price_points, parameters: [],
    )

    trade = result["trades"][0]
    open_event = next(event for event in result["events"] if event["event_type"] == "open")
    assert trade["requested_notional"] == Decimal("100")
    assert trade["filled_notional"] == Decimal("100.0000000000")
    assert trade["entry_price"] == Decimal("0.6336633663")
    assert open_event["meta"]["execution_source"] == "clob_depth"
    assert open_event["meta"]["book_snapshot_id"] == 123
    assert open_event["meta"]["levels_consumed"] == 2


def test_data_quality_report_flags_gaps_and_jumps():
    points = [
        PricePoint(x_value=100, price=Decimal("0.40"), volume=Decimal("10")),
        PricePoint(x_value=101, price=Decimal("0.42"), volume=Decimal("10")),
        PricePoint(x_value=180, price=Decimal("0.82"), volume=Decimal("10")),
        PricePoint(x_value=181, price=Decimal("0.81"), volume=Decimal("10")),
    ]
    run = {
        "market_slug": "demo-market",
        "token_side": "YES",
        "price_source": "orderfilled_block_close",
        "from_block": 100,
        "to_block": 181,
    }

    report = build_data_quality_report(points, run)
    metrics = data_quality_metrics(report)

    assert report["status"] == "review"
    assert report["gap_count"] == 1
    assert report["jump_count"] == 1
    assert len(report["data_version"]) == 20
    assert report["version_basis"] == "x_value:price:volume:trade_count"
    assert metrics[0]["metric_key"] == "data_quality_status"
    assert metrics[0]["status"] == "negative"
    version_metric = next(metric for metric in metrics if metric["metric_key"] == "data_version")
    assert version_metric["formatted_value"] == report["data_version"]


def test_nautilus_framework_runs_through_python312_worker_when_available():
    if sys.version_info >= (3, 12):
        pytest.importorskip("nautilus_trader")
    else:
        try:
            _nautilus_python_bin()
        except RuntimeError as exc:
            pytest.skip(str(exc))

    points = [
        PricePoint(x_value=1, price=Decimal("0.60"), volume=Decimal("1")),
        PricePoint(x_value=2, price=Decimal("0.70"), volume=Decimal("1")),
        PricePoint(x_value=3, price=Decimal("0.50"), volume=Decimal("1")),
    ]
    run = {
        "market_slug": "demo-market",
        "token_side": "YES",
        "price_source": "orderfilled_block_close",
    }
    params = BacktestParameters(
        entry_threshold=Decimal("0.58"),
        exit_threshold=Decimal("0.55"),
        stop_loss=Decimal("0.50"),
        take_profit=Decimal("0.50"),
        max_holding_bars=10,
        initial_capital=Decimal("1000"),
        position_size=Decimal("100"),
        execution_price_mode="LEGACY",
    )

    result = run_framework_backtest(
        "nautilus_trader",
        points,
        run,
        params,
        builtin_simulator=simulate_strategy,
        metrics_builder=lambda trades, equity, price_points, parameters: [],
    )

    engine_metric = next(row for row in result["metrics"] if row["metric_key"] == "backtest_engine")
    assert result["trades"][0]["exit_reason"] == "exit_threshold"
    assert engine_metric["formatted_value"] == "nautilus_trader"
