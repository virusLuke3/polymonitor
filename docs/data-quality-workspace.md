# Oracle Lifecycle and Data Quality Workspace

`/data-quality` is PolyMonitor's read-only audit surface for prediction-market identity,
market lifecycle coverage, Oracle observations and synchronization freshness. It reports
what the platform has actually collected and keeps known gaps visible; it does not repair,
restart or mutate a collector.

## API contract

`GET /data-quality/markets` returns `prediction-market-data-quality.v1`. The response is
cached for five minutes and contains:

- a weighted readiness score and an overall `ok`, `degraded` or `critical` state
- seven declared coverage and freshness dimensions
- market lifecycle counts from discovery through final resolution
- Oracle request, propose, dispute and settle event counts
- recent Oracle observations with local-market binding metadata
- active gap records and representative markets awaiting Oracle resolution
- market, trade and Oracle synchronization watermarks
- explicit identity, ordering and market-bridge semantics

The score is an operational signal, not a claim of dataset completeness. Its weights are:

| Dimension | Weight |
| --- | ---: |
| Canonical market identity | 20% |
| Normalized token registry | 15% |
| Serving price coverage | 15% |
| Oracle event binding | 20% |
| Closed-market finality | 15% |
| Oracle index freshness | 10% |
| OrderFilled serving freshness | 5% |

Lifecycle counts use different source universes and are not a conversion funnel. A missing
redemption count is explicitly marked `not-collected` instead of being represented as zero.

## Oracle semantics

- Durable event identity is `tx_hash + log_index`.
- Canonical event order is `block_number + log_index`.
- Local binding uses market, condition, question and token identifiers.
- Request, proposal, dispute and settlement are separate observations.
- An unbound event remains valid on-chain evidence even when it cannot yet be joined to a
  canonical local market.
- A closed market is not presented as final unless a final settlement snapshot is available.

The Market Dossier uses the same four-stage Oracle rail and shows `logIndex` beside each
transaction hash so an observation can be audited back to its exact log.

## Failure and freshness behavior

- The browser refreshes every 60 seconds.
- A failed refresh preserves the last good audit and displays the error.
- Oracle observations older than seven days are critical.
- OrderFilled serving observations older than one day are critical.
- Query failures produce empty or missing evidence that lowers the contract state; they are
  logged server-side and never converted into a healthy result.
- The page never starts or restarts the Oracle indexer. Host-level service state remains a
  deployment and Operations concern.

## Scope boundary

This workspace reads existing market registry, token registry, serving market, Oracle event,
market status and synchronization tables. It does not modify LOB runtime, Quant,
PolySignal/PolyBeats, PnL/position/address pipelines, non-trade/CTF/ERC20/Data API trades,
World Cup, Kaggle or test code.
