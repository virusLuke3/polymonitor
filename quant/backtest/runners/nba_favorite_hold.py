"""CLI for the NBA pregame favorite hold-to-settlement strategy."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from decimal import Decimal
import json
import sys

from .nba_pregame_hold import run_nba_pregame_favorite_hold


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=2000)
    parser.add_argument("--min-probability", default="0.60")
    parser.add_argument("--max-probability", default="0.80")
    parser.add_argument("--snapshot-hours-before-start", default="1")
    parser.add_argument("--signal-lookback-hours", default="24")
    parser.add_argument("--window-start-hours", default="4")
    parser.add_argument("--window-end-hours", default="0")
    parser.add_argument("--initial-capital", default="1000")
    parser.add_argument("--stake", default="10")
    parser.add_argument("--liquidity-cap-pct", default="100")
    parser.add_argument("--no-bankroll", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--csv", default="")
    args = parser.parse_args(argv)
    report = run_nba_pregame_favorite_hold(
        limit=args.limit,
        min_probability=Decimal(str(args.min_probability)),
        max_probability=Decimal(str(args.max_probability)),
        snapshot_hours_before_start=Decimal(str(args.snapshot_hours_before_start)),
        signal_lookback_hours=Decimal(str(args.signal_lookback_hours)),
        window_start_hours=Decimal(str(args.window_start_hours)),
        window_end_hours=Decimal(str(args.window_end_hours)),
        initial_capital=Decimal(str(args.initial_capital)),
        stake=Decimal(str(args.stake)),
        liquidity_cap_pct=Decimal(str(args.liquidity_cap_pct)),
        enforce_bankroll=not args.no_bankroll,
    )
    if args.csv and report.trade_rows:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(asdict(report.trade_rows[0]).keys()))
            writer.writeheader()
            for row in report.trade_rows:
                writer.writerow(asdict(row))
    payload = asdict(report)
    payload["trade_rows"] = [asdict(row) for row in report.trade_rows]
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(
            f"{report.run_id}: markets={report.market_count} raw_markets={report.raw_market_count} "
            f"signals={report.signal_count} fills={report.trades} no_fills={report.no_fills} "
            f"skipped_cash={report.skipped_insufficient_cash} wins={report.wins} losses={report.losses} pnl={report.total_pnl} "
            f"ending_capital={report.ending_capital} roi_on_cost={report.total_roi_on_cost}"
        )
        for row in report.trade_rows:
            print(
                f"{row.market_slug} | {row.title} | buy={row.buy_outcome_label} "
                f"prob={row.signal_probability} status={row.order_status} cost={row.buy_cost} "
                f"settle={row.settlement_outcome} pnl={row.pnl}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
