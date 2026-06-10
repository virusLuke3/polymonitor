# Polymarket Backtesting Accuracy

This backtester is designed to be deterministic and no-lookahead. A strategy
signal is evaluated on historical price rows, then execution is simulated from
the latest persisted CLOB depth snapshot available at or before the simulated
execution block/timestamp.

## Execution Model

- `execution_price_mode=DEPTH` uses `quant.clob_orderbook_snapshots`.
- BUY YES consumes ask levels; SELL YES consumes bid levels.
- Snapshot lookup never uses a future book.
- `latency_seconds` shifts the execution timestamp forward before book lookup.
- `max_book_staleness_seconds` marks old books as stale.
- `reject_on_stale_book=true` rejects fills from stale books.
- `allow_partial_fill=false` rejects orders that cannot fully fill.
- `min_fill_size` and `min_fill_pct` reject dust or insufficient fills.
- Buy fills are capped by the configured position cash budget.
- Exit fills are capped by the open position size.
- Fees and slippage are applied after depth consumption.

`execution_price_mode=LEGACY` is retained for comparison with older runs. It
uses close price plus bps costs and volume caps, and should not be treated as a
historical order-book replay.

## Reproducibility

Each run stores:

- run id and selected framework
- full strategy parameter snapshot
- price row checksum/data version
- execution snapshot summary/version
- gap and jump report
- trade-level fill status, filled size, snapshot id, staleness, and average fill

The run can be reproduced as long as the exact price rows and CLOB snapshots
remain in the database.

## Current Accuracy Boundary

This is suitable for internal research and liquidity-aware backtests when
historical CLOB snapshots exist across the tested range. It is not equivalent to
a complete live exchange simulator unless snapshots are sampled frequently
enough for the strategy horizon.

Known remaining limits:

- queue position is not simulated
- maker/taker order lifecycle and cancellation are not simulated
- network latency is modeled as a fixed parameter
- historical CLOB accuracy depends on snapshot sampling coverage
- market resolution/settlement is not a full accounting engine yet

For money-sensitive use, prefer `DEPTH`, keep stale rejection enabled, inspect
gap reports, and reject runs with low snapshot coverage.
