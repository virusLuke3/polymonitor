from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant.backtest.runners.nba_pregame_hold import _build_favorite_trades, _build_trades, _market_event_time
from quant.backtest.runners.selectors import ResolvedMarketCandidate


pytestmark = pytest.mark.backtest_validation


def test_pregame_limit_fill_uses_only_future_crossing_inside_window():
    market = _market(settlement_code=1)
    rows = [
        _row(price="0.59", block=10, log=1, hour=17, minute=10),  # outside 6h-4h window
        _row(price="0.59", block=11, log=1, hour=17, minute=31),  # signal
        _row(price="0.57", block=11, log=0, hour=17, minute=31),  # before signal crossing, must not fill
        _row(price="0.61", block=12, log=1, hour=17, minute=40),  # not crossing for BUY limit 0.59
        _row(price="0.58", block=13, log=1, hour=18, minute=0),  # valid fill
        _row(price="0.50", block=14, log=1, hour=19, minute=45),  # after window, ignored
    ]

    trades = _build_trades(
        [market],
        {market.market_id: rows},
        lower=Decimal("0.58"),
        upper=Decimal("0.62"),
        target=Decimal("0.60"),
        yes_only=False,
        window_start_hours=Decimal("6"),
        window_end_hours=Decimal("4"),
        order_size=Decimal("1"),
        liquidity_cap_pct=Decimal("100"),
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.order_status == "FILLED"
    assert trade.signal_block == 11
    assert trade.signal_log_index == 1
    assert trade.limit_price == "0.59"
    assert trade.crossing_trade_price == "0.58"
    assert trade.fill_block == 13
    assert trade.buy_price == "0.59"
    assert trade.payoff == "1"
    assert trade.pnl_per_share == "0.41"


def test_pregame_limit_order_expires_when_no_future_crossing():
    market = _market(settlement_code=2)
    rows = [
        _row(price="0.60", block=20, log=1, hour=17, minute=35),
        _row(price="0.61", block=21, log=1, hour=18, minute=0),
        _row(price="0.62", block=22, log=1, hour=19, minute=0),
    ]

    trades = _build_trades(
        [market],
        {market.market_id: rows},
        lower=Decimal("0.58"),
        upper=Decimal("0.62"),
        target=Decimal("0.60"),
        yes_only=True,
        window_start_hours=Decimal("6"),
        window_end_hours=Decimal("4"),
        order_size=Decimal("1"),
        liquidity_cap_pct=Decimal("100"),
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.order_status == "EXPIRED"
    assert trade.filled_size == "0"
    assert trade.payoff == "0"
    assert trade.pnl_per_share == "0"
    assert trade.fill_block == 0


def test_pregame_default_strategy_ignores_no_side_signals():
    market = _market(settlement_code=2)
    rows = [
        _row(price="0.60", block=30, log=1, hour=17, minute=35, outcome_code=2, token_id="token-no"),
        _row(price="0.59", block=31, log=1, hour=17, minute=45, outcome_code=2, token_id="token-no"),
        _row(price="0.60", block=32, log=1, hour=18, minute=0, outcome_code=1, token_id="token-yes"),
        _row(price="0.59", block=33, log=1, hour=18, minute=5, outcome_code=1, token_id="token-yes"),
    ]

    trades = _build_trades(
        [market],
        {market.market_id: rows},
        lower=Decimal("0.58"),
        upper=Decimal("0.62"),
        target=Decimal("0.60"),
        yes_only=True,
        window_start_hours=Decimal("6"),
        window_end_hours=Decimal("4"),
        order_size=Decimal("1"),
        liquidity_cap_pct=Decimal("100"),
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.buy_outcome_label == "YES"
    assert trade.signal_block == 32
    assert trade.fill_block == 33


def test_favorite_strategy_buys_high_probability_side_with_fixed_stake():
    market = _market(settlement_code=2)
    rows = [
        _row(price="0.38", block=40, log=1, hour=20, minute=1, outcome_code=1, token_id="token-yes"),
        _row(price="0.62", block=41, log=1, hour=20, minute=5, outcome_code=2, token_id="token-no", size="30"),
        _row(price="0.61", block=42, log=1, hour=20, minute=10, outcome_code=2, token_id="token-no", size="30"),
    ]

    trades = _build_favorite_trades(
        [market],
        {market.market_id: rows},
        min_probability=Decimal("0.60"),
        window_start_hours=Decimal("4"),
        window_end_hours=Decimal("0"),
        stake=Decimal("10"),
        liquidity_cap_pct=Decimal("100"),
    )

    assert len(trades) == 1
    trade = trades[0]
    assert trade.buy_outcome_label == "NO"
    assert trade.signal_source_outcome_code == 1
    assert trade.signal_source_price == "0.38"
    assert trade.signal_probability == "0.62"
    assert trade.order_status == "FILLED"
    assert Decimal(trade.requested_shares).quantize(Decimal("0.0001")) == Decimal("16.1290")
    assert Decimal(trade.buy_cost).quantize(Decimal("0.01")) == Decimal("10.00")
    assert Decimal(trade.settlement_value).quantize(Decimal("0.01")) == Decimal("16.13")
    assert Decimal(trade.pnl).quantize(Decimal("0.01")) == Decimal("6.13")


def test_market_event_time_uses_slug_date_when_db_end_date_is_shifted():
    shifted = ResolvedMarketCandidate(
        market_id=2,
        market_slug="nba-was-hou-2024-11-11",
        title="Wizards vs Rockets",
        end_date=datetime(2024, 11, 19, 1, 0, tzinfo=timezone.utc),
        settlement_code=1,
        settlement_outcome="YES",
    )

    assert _market_event_time(shifted) == datetime(2024, 11, 11, 1, 0, tzinfo=timezone.utc)


def _market(*, settlement_code: int) -> ResolvedMarketCandidate:
    return ResolvedMarketCandidate(
        market_id=1,
        market_slug="nba-test-2024-10-23",
        title="Test vs Test",
        end_date=datetime(2024, 10, 23, 23, 30, tzinfo=timezone.utc),
        settlement_code=settlement_code,
        settlement_outcome="YES" if settlement_code == 1 else "NO",
    )


def _row(
    *,
    price: str,
    block: int,
    log: int,
    hour: int,
    minute: int,
    outcome_code: int = 1,
    token_id: str = "token-yes",
    size: str = "5",
) -> dict[str, object]:
    return {
        "market_id": 1,
        "outcome_code": outcome_code,
        "token_id": token_id,
        "block_number": block,
        "log_index": log,
        "tx_hash": f"0x{block:04x}{log:04x}",
        "price": price,
        "size": size,
        "block_time": datetime(2024, 10, 23, hour, minute, tzinfo=timezone.utc),
    }
