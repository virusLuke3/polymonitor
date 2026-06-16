"""NBA 2024/25 pregame 60/40 hold-to-settlement validation runner."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import sys
import time
from typing import Any

from ...core.db import ClickHouseClient
from .base import MemorySampler, Timer
from .execution_replay import OrderIntent, ReplayTradeEvent, replay_limit_order, sequence_key
from .selectors import ResolvedMarketCandidate, select_nba_2024_25_moneyline_markets


@dataclass(frozen=True)
class NbaPregameHoldTrade:
    market_id: int
    market_slug: str
    title: str
    end_date: str | None
    buy_outcome_code: int
    buy_outcome_label: str
    settlement_code: int
    settlement_outcome: str
    window_start: str
    window_end: str
    signal_price: str
    limit_price: str
    buy_price: str
    crossing_trade_price: str
    order_status: str
    filled_size: str
    payoff: str
    pnl_per_share: str
    roi: str
    signal_block: int
    signal_log_index: int
    fill_block: int
    fill_log_index: int
    token_id: str
    raw_rows_for_outcome: int


@dataclass(frozen=True)
class NbaPregameHoldReport:
    run_id: str
    market_count: int
    raw_market_count: int
    signal_count: int
    trades: int
    no_fills: int
    skipped_without_60_40: int
    wins: int
    losses: int
    win_rate: str
    total_cost: str
    total_payoff: str
    total_pnl: str
    total_roi: str
    db_query_sec: float
    engine_sec: float
    total_runtime_sec: float
    peak_memory_mb: float
    trade_rows: list[NbaPregameHoldTrade]


@dataclass(frozen=True)
class NbaFavoriteHoldTrade:
    market_id: int
    market_slug: str
    title: str
    end_date: str | None
    buy_outcome_code: int
    buy_outcome_label: str
    settlement_code: int
    settlement_outcome: str
    window_start: str
    window_end: str
    signal_time: str
    signal_source_outcome_code: int
    signal_source_price: str
    signal_probability: str
    limit_price: str
    stake: str
    requested_shares: str
    filled_size: str
    buy_cost: str
    crossing_trade_price: str
    order_status: str
    payoff_per_share: str
    settlement_value: str
    pnl: str
    roi: str
    signal_block: int
    signal_log_index: int
    fill_block: int
    fill_log_index: int
    token_id: str
    raw_rows_for_outcome: int


@dataclass(frozen=True)
class NbaFavoriteHoldReport:
    run_id: str
    initial_capital: str
    stake: str
    min_probability: str
    max_probability: str
    snapshot_hours_before_start: str
    enforce_bankroll: bool
    market_count: int
    raw_market_count: int
    signal_count: int
    trades: int
    no_fills: int
    skipped_without_signal: int
    skipped_insufficient_cash: int
    wins: int
    losses: int
    win_rate: str
    total_staked: str
    total_cost: str
    total_payoff: str
    total_pnl: str
    ending_capital: str
    total_roi_on_cost: str
    total_return_on_initial_capital: str
    avg_pnl: str
    profit_factor: str
    max_drawdown: str
    max_realized_pnl_drawdown: str
    max_concurrent_cost: str
    max_concurrent_positions: int
    db_query_sec: float
    engine_sec: float
    total_runtime_sec: float
    peak_memory_mb: float
    trade_rows: list[NbaFavoriteHoldTrade]


def run_nba_pregame_hold(
    *,
    limit: int = 200,
    lower: Decimal = Decimal("0.58"),
    upper: Decimal = Decimal("0.62"),
    target: Decimal = Decimal("0.60"),
    yes_only: bool = True,
    window_start_hours: Decimal = Decimal("6"),
    window_end_hours: Decimal = Decimal("4"),
    order_size: Decimal = Decimal("1"),
    liquidity_cap_pct: Decimal = Decimal("100"),
) -> NbaPregameHoldReport:
    timer = Timer()
    start = time.perf_counter()
    memory = MemorySampler.peak_mb()
    with timer.track("db_query"):
        markets = select_nba_2024_25_moneyline_markets(limit=limit)
        raw_rows = _load_window_orderfilled_rows(
            markets,
            window_start_hours=window_start_hours,
            window_end_hours=window_end_hours,
        )
    with timer.track("engine"):
        by_market: dict[int, list[dict[str, Any]]] = {}
        for row in raw_rows:
            by_market.setdefault(int(row["market_id"]), []).append(row)
        trades = _build_trades(
            markets,
            by_market,
            lower=lower,
            upper=upper,
            target=target,
            yes_only=yes_only,
            window_start_hours=window_start_hours,
            window_end_hours=window_end_hours,
            order_size=order_size,
            liquidity_cap_pct=liquidity_cap_pct,
        )
    filled_trades = [trade for trade in trades if trade.order_status in {"FILLED", "PARTIAL_FILLED"}]
    wins = sum(1 for trade in filled_trades if Decimal(trade.payoff) > 0)
    total_cost = sum((Decimal(trade.buy_price) * Decimal(trade.filled_size) for trade in filled_trades), Decimal("0"))
    total_payoff = sum((Decimal(trade.payoff) * Decimal(trade.filled_size) for trade in filled_trades), Decimal("0"))
    total_pnl = total_payoff - total_cost
    total_roi = total_pnl / total_cost if total_cost else Decimal("0")
    raw_market_count = len({int(row["market_id"]) for row in raw_rows})
    no_fills = sum(1 for trade in trades if trade.order_status not in {"FILLED", "PARTIAL_FILLED"})
    return NbaPregameHoldReport(
        run_id="nba_pregame_60_40_hold_yes_only" if yes_only else "nba_pregame_60_40_hold",
        market_count=len(markets),
        raw_market_count=raw_market_count,
        signal_count=len(trades),
        trades=len(filled_trades),
        no_fills=no_fills,
        skipped_without_60_40=len(markets) - len(trades),
        wins=wins,
        losses=len(filled_trades) - wins,
        win_rate=_decimal_text(Decimal(wins) / Decimal(len(filled_trades)) if filled_trades else Decimal("0")),
        total_cost=_decimal_text(total_cost),
        total_payoff=_decimal_text(total_payoff),
        total_pnl=_decimal_text(total_pnl),
        total_roi=_decimal_text(total_roi),
        db_query_sec=round(timer.elapsed.get("db_query", 0.0), 6),
        engine_sec=round(timer.elapsed.get("engine", 0.0), 6),
        total_runtime_sec=round(time.perf_counter() - start, 6),
        peak_memory_mb=memory,
        trade_rows=trades,
    )


def run_nba_pregame_favorite_hold(
    *,
    limit: int = 2000,
    min_probability: Decimal = Decimal("0.60"),
    max_probability: Decimal = Decimal("0.80"),
    snapshot_hours_before_start: Decimal | None = Decimal("1"),
    signal_lookback_hours: Decimal = Decimal("24"),
    window_start_hours: Decimal = Decimal("4"),
    window_end_hours: Decimal = Decimal("0"),
    initial_capital: Decimal = Decimal("1000"),
    stake: Decimal = Decimal("10"),
    liquidity_cap_pct: Decimal = Decimal("100"),
    enforce_bankroll: bool = True,
) -> NbaFavoriteHoldReport:
    timer = Timer()
    start = time.perf_counter()
    memory = MemorySampler.peak_mb()
    with timer.track("db_query"):
        markets = select_nba_2024_25_moneyline_markets(limit=limit)
        load_start_hours = window_start_hours
        if snapshot_hours_before_start is not None:
            load_start_hours = max(window_start_hours, snapshot_hours_before_start + signal_lookback_hours)
        raw_rows = _load_window_orderfilled_rows(
            markets,
            window_start_hours=load_start_hours,
            window_end_hours=window_end_hours,
        )
    with timer.track("engine"):
        by_market: dict[int, list[dict[str, Any]]] = {}
        for row in raw_rows:
            by_market.setdefault(int(row["market_id"]), []).append(row)
        trade_rows = _build_favorite_trades(
            markets,
            by_market,
            min_probability=min_probability,
            max_probability=max_probability,
            snapshot_hours_before_start=snapshot_hours_before_start,
            signal_lookback_hours=signal_lookback_hours,
            window_start_hours=window_start_hours,
            window_end_hours=window_end_hours,
            stake=stake,
            liquidity_cap_pct=liquidity_cap_pct,
        )
        if enforce_bankroll:
            trade_rows = _apply_bankroll_constraints(trade_rows, initial_capital)
    filled_trades = [row for row in trade_rows if Decimal(row.filled_size) > 0]
    wins = sum(1 for row in filled_trades if Decimal(row.pnl) > 0)
    losses = sum(1 for row in filled_trades if Decimal(row.pnl) < 0)
    pnls = [Decimal(row.pnl) for row in filled_trades]
    positive_pnl = sum((pnl for pnl in pnls if pnl > 0), Decimal("0"))
    negative_pnl = sum((pnl for pnl in pnls if pnl < 0), Decimal("0"))
    total_staked = stake * Decimal(len(filled_trades))
    total_cost = sum((Decimal(row.buy_cost) for row in filled_trades), Decimal("0"))
    total_payoff = sum((Decimal(row.settlement_value) for row in filled_trades), Decimal("0"))
    total_pnl = sum(pnls, Decimal("0"))
    ending_capital = initial_capital + total_pnl
    raw_market_count = len({int(row["market_id"]) for row in raw_rows})
    no_fills = sum(1 for row in trade_rows if Decimal(row.filled_size) <= 0)
    skipped_insufficient_cash = sum(1 for row in trade_rows if row.order_status == "SKIPPED_INSUFFICIENT_CASH")
    realized_pnl_drawdown = _max_drawdown(pnls)
    max_concurrent_cost, max_concurrent_positions = _max_concurrent_exposure(filled_trades)
    return NbaFavoriteHoldReport(
        run_id="nba_pregame_favorite_snapshot_hold",
        initial_capital=_decimal_text(initial_capital),
        stake=_decimal_text(stake),
        min_probability=_decimal_text(min_probability),
        max_probability=_decimal_text(max_probability),
        snapshot_hours_before_start=_decimal_text(snapshot_hours_before_start) if snapshot_hours_before_start is not None else "",
        enforce_bankroll=enforce_bankroll,
        market_count=len(markets),
        raw_market_count=raw_market_count,
        signal_count=len(trade_rows),
        trades=len(filled_trades),
        no_fills=no_fills,
        skipped_without_signal=len(markets) - len(trade_rows),
        skipped_insufficient_cash=skipped_insufficient_cash,
        wins=wins,
        losses=losses,
        win_rate=_decimal_text(Decimal(wins) / Decimal(len(filled_trades)) if filled_trades else Decimal("0")),
        total_staked=_decimal_text(total_staked),
        total_cost=_decimal_text(total_cost),
        total_payoff=_decimal_text(total_payoff),
        total_pnl=_decimal_text(total_pnl),
        ending_capital=_decimal_text(ending_capital),
        total_roi_on_cost=_decimal_text(total_pnl / total_cost if total_cost else Decimal("0")),
        total_return_on_initial_capital=_decimal_text(total_pnl / initial_capital if initial_capital else Decimal("0")),
        avg_pnl=_decimal_text(total_pnl / Decimal(len(filled_trades)) if filled_trades else Decimal("0")),
        profit_factor=_decimal_text(positive_pnl / abs(negative_pnl) if negative_pnl else Decimal("0")),
        max_drawdown=_decimal_text(realized_pnl_drawdown),
        max_realized_pnl_drawdown=_decimal_text(realized_pnl_drawdown),
        max_concurrent_cost=_decimal_text(max_concurrent_cost),
        max_concurrent_positions=max_concurrent_positions,
        db_query_sec=round(timer.elapsed.get("db_query", 0.0), 6),
        engine_sec=round(timer.elapsed.get("engine", 0.0), 6),
        total_runtime_sec=round(time.perf_counter() - start, 6),
        peak_memory_mb=memory,
        trade_rows=trade_rows,
    )


def _load_window_orderfilled_rows(
    markets: list[ResolvedMarketCandidate],
    *,
    window_start_hours: Decimal,
    window_end_hours: Decimal,
) -> list[dict[str, Any]]:
    if not markets:
        return []
    dated_markets = [market for market in markets if market.end_date is not None]
    if not dated_markets:
        return []
    ids = ",".join(str(market.market_id) for market in markets)
    starts = [
        _market_event_time(market) - timedelta(hours=float(window_start_hours))
        for market in dated_markets
        if market.end_date is not None
    ]
    ends = [
        _market_event_time(market) - timedelta(hours=float(window_end_hours))
        for market in dated_markets
        if market.end_date is not None
    ]
    global_start = min(starts).strftime("%Y-%m-%d %H:%M:%S")
    global_end = max(ends).strftime("%Y-%m-%d %H:%M:%S")
    client = ClickHouseClient()
    return client.query_json_rows(
        f"""
        SELECT
            f.market_id,
            f.outcome_code,
            f.token_id,
            f.block_number,
            f.log_index,
            lower(f.tx_hash) AS tx_hash,
            f.price,
            f.size,
            bt.block_time
        FROM orderfilled_fact f
        INNER JOIN block_timestamps bt ON bt.block_number = f.block_number
        WHERE f.market_id IN ({ids})
          AND bt.block_time >= toDateTime('{global_start}', 'UTC')
          AND bt.block_time <= toDateTime('{global_end}', 'UTC')
        ORDER BY f.market_id ASC, f.outcome_code ASC, f.block_number ASC, f.log_index ASC, f.tx_hash ASC
        """
    )


def _build_trades(
    markets: list[ResolvedMarketCandidate],
    by_market: dict[int, list[dict[str, Any]]],
    *,
    lower: Decimal,
    upper: Decimal,
    target: Decimal,
    yes_only: bool,
    window_start_hours: Decimal,
    window_end_hours: Decimal,
    order_size: Decimal,
    liquidity_cap_pct: Decimal,
) -> list[NbaPregameHoldTrade]:
    trades: list[NbaPregameHoldTrade] = []
    for market in markets:
        if market.end_date is None:
            continue
        event_time = _market_event_time(market)
        window_start = event_time - timedelta(hours=float(window_start_hours))
        window_end = event_time - timedelta(hours=float(window_end_hours))
        market_rows = [
            row for row in by_market.get(market.market_id, [])
            if window_start <= _row_block_time(row, event_time) <= window_end
        ]
        raw_rows_by_outcome = _count_by_outcome(market_rows)
        signals: list[tuple[tuple[int, int, str], Decimal, dict[str, Any]]] = []
        for row in market_rows:
            outcome_code = int(row["outcome_code"])
            if yes_only and outcome_code != 1:
                continue
            price = Decimal(str(row["price"]))
            if lower <= price <= upper:
                signals.append((
                    (int(row["block_number"]), int(row["log_index"]), str(row["tx_hash"])),
                    abs(price - target),
                    row,
                ))
        if not signals:
            continue
        _, _, row = sorted(signals, key=lambda item: (item[0], item[1]))[0]
        limit_price = Decimal(str(row["price"]))
        buy_code = int(row["outcome_code"])
        signal_sequence = sequence_key(int(row["block_number"]), 0, int(row["log_index"]), str(row["tx_hash"]))
        replay_events = [
            ReplayTradeEvent(
                market_id=market.market_id,
                token_id=str(event["token_id"]),
                block_number=int(event["block_number"]),
                log_index=int(event["log_index"]),
                tx_hash=str(event["tx_hash"]),
                trade_price=Decimal(str(event["price"])),
                size=Decimal(str(event["size"])),
            )
            for event in market_rows
            if int(event["outcome_code"]) == buy_code and str(event["token_id"]) == str(row["token_id"])
        ]
        fill = replay_limit_order(
            OrderIntent(
                side="BUY_YES",
                limit_price=limit_price,
                size=order_size,
                time_in_force="GTD",
                submit_sequence=signal_sequence,
                expire_sequence=_last_sequence(replay_events) or signal_sequence,
                liquidity_cap_pct=liquidity_cap_pct,
                order_id=f"NBA-{market.market_id}-{buy_code}",
            ),
            replay_events,
        )
        payoff = Decimal("1") if buy_code == market.settlement_code else Decimal("0")
        buy_price = fill.avg_fill_price if fill.filled_size > 0 else limit_price
        pnl = (payoff - buy_price) if fill.filled_size > 0 else Decimal("0")
        roi = pnl / buy_price if buy_price and fill.filled_size > 0 else Decimal("0")
        crossing = fill.candidate_events[0] if fill.candidate_events else None
        trades.append(
            NbaPregameHoldTrade(
                market_id=market.market_id,
                market_slug=market.market_slug,
                title=market.title,
                end_date=event_time.isoformat(),
                buy_outcome_code=buy_code,
                buy_outcome_label="YES" if buy_code == 1 else "NO",
                settlement_code=market.settlement_code,
                settlement_outcome=market.settlement_outcome,
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                signal_price=_decimal_text(limit_price),
                limit_price=_decimal_text(limit_price),
                buy_price=_decimal_text(buy_price),
                crossing_trade_price=_decimal_text(crossing.trade_price) if crossing else "",
                order_status=fill.status,
                filled_size=_decimal_text(fill.filled_size),
                payoff=_decimal_text(payoff),
                pnl_per_share=_decimal_text(pnl),
                roi=_decimal_text(roi),
                signal_block=int(row["block_number"]),
                signal_log_index=int(row["log_index"]),
                fill_block=int(crossing.block_number) if crossing else 0,
                fill_log_index=int(crossing.log_index) if crossing else 0,
                token_id=str(row["token_id"]),
                raw_rows_for_outcome=raw_rows_by_outcome.get(buy_code, 0),
            )
        )
    return trades


def _build_favorite_trades(
    markets: list[ResolvedMarketCandidate],
    by_market: dict[int, list[dict[str, Any]]],
    *,
    min_probability: Decimal,
    max_probability: Decimal = Decimal("1"),
    snapshot_hours_before_start: Decimal | None = None,
    signal_lookback_hours: Decimal = Decimal("24"),
    window_start_hours: Decimal,
    window_end_hours: Decimal,
    stake: Decimal,
    liquidity_cap_pct: Decimal,
) -> list[NbaFavoriteHoldTrade]:
    trades: list[NbaFavoriteHoldTrade] = []
    for market in markets:
        if market.end_date is None:
            continue
        event_time = _market_event_time(market)
        signal_lookback_start = (
            event_time - timedelta(hours=float(snapshot_hours_before_start + signal_lookback_hours))
            if snapshot_hours_before_start is not None
            else event_time - timedelta(hours=float(window_start_hours))
        )
        window_start = event_time - timedelta(hours=float(window_start_hours))
        window_end = event_time - timedelta(hours=float(window_end_hours))
        market_rows = sorted(
            [
                row for row in by_market.get(market.market_id, [])
                if signal_lookback_start <= _row_block_time(row, event_time) <= window_end
            ],
            key=lambda row: (int(row["block_number"]), int(row["log_index"]), str(row["tx_hash"])),
        )
        if not market_rows:
            continue
        token_by_outcome = _token_by_outcome(market_rows)
        raw_rows_by_outcome = _count_by_outcome(market_rows)
        if snapshot_hours_before_start is not None:
            signal_time = event_time - timedelta(hours=float(snapshot_hours_before_start))
            signal = _favorite_signal_at_snapshot(
                market_rows,
                token_by_outcome,
                min_probability,
                max_probability,
                signal_time,
                event_time,
            )
        else:
            signal_time = window_start
            signal = _first_favorite_signal(market_rows, token_by_outcome, min_probability, max_probability)
        if signal is None:
            continue
        signal_row, buy_code, probability, token_id = signal
        signal_sequence = sequence_key(int(signal_row["block_number"]), 0, int(signal_row["log_index"]), str(signal_row["tx_hash"]))
        replay_events = [
            ReplayTradeEvent(
                market_id=market.market_id,
                token_id=str(row["token_id"]),
                block_number=int(row["block_number"]),
                log_index=int(row["log_index"]),
                tx_hash=str(row["tx_hash"]),
                trade_price=Decimal(str(row["price"])),
                size=Decimal(str(row["size"])),
            )
            for row in market_rows
            if int(row["outcome_code"]) == buy_code and str(row["token_id"]) == token_id
            and _row_block_time(row, event_time) >= signal_time
            and _row_block_time(row, event_time) <= window_end
        ]
        requested_shares = (stake / probability) if probability > 0 else Decimal("0")
        fill = replay_limit_order(
            OrderIntent(
                side="BUY_YES",
                limit_price=probability,
                size=requested_shares,
                time_in_force="GTD",
                submit_sequence=signal_sequence,
                expire_sequence=_last_sequence(replay_events) or signal_sequence,
                liquidity_cap_pct=liquidity_cap_pct,
                order_id=f"NBA-FAV-{market.market_id}-{buy_code}",
            ),
            replay_events,
        )
        crossing = fill.candidate_events[0] if fill.candidate_events else None
        payoff_per_share = Decimal("1") if buy_code == market.settlement_code else Decimal("0")
        buy_cost = (fill.filled_size * probability)
        settlement_value = fill.filled_size * payoff_per_share
        pnl = settlement_value - buy_cost
        trades.append(
            NbaFavoriteHoldTrade(
                market_id=market.market_id,
                market_slug=market.market_slug,
                title=market.title,
                end_date=event_time.isoformat(),
                buy_outcome_code=buy_code,
                buy_outcome_label="YES" if buy_code == 1 else "NO",
                settlement_code=market.settlement_code,
                settlement_outcome=market.settlement_outcome,
                window_start=window_start.isoformat(),
                window_end=window_end.isoformat(),
                signal_time=signal_time.isoformat(),
                signal_source_outcome_code=int(signal_row["outcome_code"]),
                signal_source_price=_decimal_text(Decimal(str(signal_row["price"]))),
                signal_probability=_decimal_text(probability),
                limit_price=_decimal_text(probability),
                stake=_decimal_text(stake),
                requested_shares=_decimal_text(requested_shares),
                filled_size=_decimal_text(fill.filled_size),
                buy_cost=_decimal_text(buy_cost),
                crossing_trade_price=_decimal_text(crossing.trade_price) if crossing else "",
                order_status=fill.status,
                payoff_per_share=_decimal_text(payoff_per_share),
                settlement_value=_decimal_text(settlement_value),
                pnl=_decimal_text(pnl),
                roi=_decimal_text(pnl / buy_cost if buy_cost else Decimal("0")),
                signal_block=int(signal_row["block_number"]),
                signal_log_index=int(signal_row["log_index"]),
                fill_block=int(crossing.block_number) if crossing else 0,
                fill_log_index=int(crossing.log_index) if crossing else 0,
                token_id=token_id,
                raw_rows_for_outcome=raw_rows_by_outcome.get(buy_code, 0),
            )
        )
    return trades


def _first_favorite_signal(
    rows: list[dict[str, Any]],
    token_by_outcome: dict[int, str],
    min_probability: Decimal,
    max_probability: Decimal,
) -> tuple[dict[str, Any], int, Decimal, str] | None:
    for row in rows:
        favorite = _favorite_from_row(row, token_by_outcome)
        if favorite is None:
            continue
        buy_code, probability, token_id = favorite
        if min_probability <= probability <= max_probability:
            return row, buy_code, probability, token_id
    return None


def _favorite_signal_at_snapshot(
    rows: list[dict[str, Any]],
    token_by_outcome: dict[int, str],
    min_probability: Decimal,
    max_probability: Decimal,
    signal_time: datetime,
    event_time: datetime,
) -> tuple[dict[str, Any], int, Decimal, str] | None:
    candidates = [row for row in rows if _row_block_time(row, event_time) <= signal_time]
    for row in reversed(candidates):
        favorite = _favorite_from_row(row, token_by_outcome)
        if favorite is None:
            continue
        buy_code, probability, token_id = favorite
        if min_probability <= probability <= max_probability:
            return row, buy_code, probability, token_id
        return None
    return None


def _favorite_from_row(
    row: dict[str, Any],
    token_by_outcome: dict[int, str],
) -> tuple[int, Decimal, str] | None:
    source_code = int(row["outcome_code"])
    source_price = Decimal(str(row["price"]))
    same_probability = source_price
    opposite_probability = Decimal("1") - source_price
    if same_probability >= opposite_probability:
        buy_code = source_code
        probability = same_probability
    else:
        buy_code = 2 if source_code == 1 else 1
        probability = opposite_probability
    token_id = token_by_outcome.get(buy_code)
    if not token_id:
        return None
    return buy_code, probability, token_id


def _apply_bankroll_constraints(
    rows: list[NbaFavoriteHoldTrade],
    initial_capital: Decimal,
) -> list[NbaFavoriteHoldTrade]:
    cash = initial_capital
    pending_settlements: list[tuple[datetime, Decimal]] = []
    constrained: list[NbaFavoriteHoldTrade] = []
    for row in sorted(rows, key=lambda item: (item.signal_time, item.signal_block, item.signal_log_index, item.market_id)):
        signal_time = datetime.fromisoformat(row.signal_time)
        matured = [item for item in pending_settlements if item[0] <= signal_time]
        if matured:
            cash += sum((value for _, value in matured), Decimal("0"))
            pending_settlements = [item for item in pending_settlements if item[0] > signal_time]
        buy_cost = Decimal(row.buy_cost)
        if Decimal(row.filled_size) > 0 and buy_cost > cash:
            constrained.append(
                replace(
                    row,
                    order_status="SKIPPED_INSUFFICIENT_CASH",
                    filled_size="0",
                    buy_cost="0",
                    settlement_value="0",
                    pnl="0",
                    roi="0",
                )
            )
            continue
        if buy_cost > 0:
            cash -= buy_cost
            pending_settlements.append((datetime.fromisoformat(row.end_date), Decimal(row.settlement_value)))
        constrained.append(row)
    return constrained


def _max_concurrent_exposure(rows: list[NbaFavoriteHoldTrade]) -> tuple[Decimal, int]:
    events: list[tuple[datetime, int, Decimal, int]] = []
    for row in rows:
        cost = Decimal(row.buy_cost)
        if cost <= 0 or Decimal(row.filled_size) <= 0:
            continue
        start = datetime.fromisoformat(row.signal_time)
        end = datetime.fromisoformat(row.end_date) if row.end_date else start
        events.append((start, 1, cost, 1))
        events.append((end, 0, -cost, -1))
    active_cost = Decimal("0")
    active_positions = 0
    max_cost = Decimal("0")
    max_positions = 0
    for _, _, cost_delta, position_delta in sorted(events):
        active_cost += cost_delta
        active_positions += position_delta
        max_cost = max(max_cost, active_cost)
        max_positions = max(max_positions, active_positions)
    return max_cost, max_positions


def _token_by_outcome(rows: list[dict[str, Any]]) -> dict[int, str]:
    tokens: dict[int, str] = {}
    for row in rows:
        code = int(row["outcome_code"])
        tokens.setdefault(code, str(row["token_id"]))
    return tokens


def _last_sequence(events: list[ReplayTradeEvent]) -> tuple[int, int, int, str] | None:
    if not events:
        return None
    return max((event.event_sequence for event in events))


def _count_by_outcome(rows: list[dict[str, Any]]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for row in rows:
        code = int(row["outcome_code"])
        counts[code] = counts.get(code, 0) + 1
    return counts


def _row_block_time(row: dict[str, Any], end_date: datetime) -> datetime:
    raw = row["block_time"]
    if isinstance(raw, datetime):
        value = raw
    else:
        value = datetime.fromisoformat(str(raw).replace(" ", "T"))
    if value.tzinfo is None:
        return value.replace(tzinfo=end_date.tzinfo or timezone.utc)
    return value.astimezone(end_date.tzinfo or timezone.utc)


def _market_event_time(market: ResolvedMarketCandidate) -> datetime:
    if market.end_date is None:
        raise ValueError(f"market {market.market_slug} has no end_date")
    parts = market.market_slug.split("-")
    try:
        year, month, day = map(int, parts[-3:])
    except (TypeError, ValueError):
        return market.end_date
    slug_date = datetime(year, month, day, tzinfo=market.end_date.tzinfo or timezone.utc).date()
    if abs((market.end_date.date() - slug_date).days) <= 1:
        return market.end_date
    return datetime(
        year,
        month,
        day,
        market.end_date.hour,
        market.end_date.minute,
        market.end_date.second,
        tzinfo=market.end_date.tzinfo or timezone.utc,
    )


def _max_drawdown(pnls: list[Decimal]) -> Decimal:
    peak = Decimal("0")
    equity = Decimal("0")
    max_drawdown = Decimal("0")
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _report_dict(report: NbaPregameHoldReport) -> dict[str, Any]:
    payload = asdict(report)
    payload["trade_rows"] = [asdict(row) for row in report.trade_rows]
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--lower", default="0.58")
    parser.add_argument("--upper", default="0.62")
    parser.add_argument("--target", default="0.60")
    parser.add_argument("--yes-only", action="store_true", help="Deprecated compatibility flag; YES-only is now the default.")
    parser.add_argument("--allow-no", action="store_true", help="Also allow NO-side 60/40 signals for comparison runs.")
    parser.add_argument("--window-start-hours", default="6")
    parser.add_argument("--window-end-hours", default="4")
    parser.add_argument("--order-size", default="1")
    parser.add_argument("--liquidity-cap-pct", default="100")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--csv", default="")
    args = parser.parse_args(argv)
    report = run_nba_pregame_hold(
        limit=args.limit,
        lower=Decimal(str(args.lower)),
        upper=Decimal(str(args.upper)),
        target=Decimal(str(args.target)),
        yes_only=not args.allow_no,
        window_start_hours=Decimal(str(args.window_start_hours)),
        window_end_hours=Decimal(str(args.window_end_hours)),
        order_size=Decimal(str(args.order_size)),
        liquidity_cap_pct=Decimal(str(args.liquidity_cap_pct)),
    )
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(asdict(report.trade_rows[0]).keys()) if report.trade_rows else [])
            if report.trade_rows:
                writer.writeheader()
                for row in report.trade_rows:
                    writer.writerow(asdict(row))
    if args.json:
        print(json.dumps(_report_dict(report), ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{report.run_id}: markets={report.market_count} raw_markets={report.raw_market_count} "
            f"signals={report.signal_count} fills={report.trades} no_fills={report.no_fills} "
            f"wins={report.wins} losses={report.losses} "
            f"pnl={report.total_pnl} roi={report.total_roi}"
        )
        for row in report.trade_rows:
            print(
                f"{row.market_slug} | {row.title} | signal={row.buy_outcome_label} {row.signal_price} "
                f"status={row.order_status} buy={row.buy_price} settle={row.settlement_outcome} "
                f"payoff={row.payoff} pnl={row.pnl_per_share} roi={row.roi}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
