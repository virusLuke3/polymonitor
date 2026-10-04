# Funding Rate panel contract

This panel supplies exchange perpetual funding context for crypto prediction
markets. A funding rate is a perpetual position's periodic cost, not a Polymarket
probability, trade signal, realized return, or settlement-price oracle.

## Ownership and isolation

- `webpage/src/panels/modules/crypto-funding-watch/` owns rendering, parsing,
  calculations, filters and its resource declaration. It has no implementation
  import from another panel.
- `useFundingFeed.ts` uses the shared `usePanelResource` scheduler, request
  cancellation, retry, visibility handling and validated public snapshot cache.
  There is no second component timer or duplicate fetch loop.
- `scripts/api/services/crypto_funding/contracts.py` owns eligibility, rate units,
  clocks and aggregation. `providers.py` owns exchange adapters. `universe.py`
  owns conservative market-question matching and bounded asset discovery.
- `crypto_funding_service.py` orchestrates these responsibilities. API serving
  reads an existing canonical seed; it never collects from external exchanges
  during a page request and never rewrites SQLite on reads.
- `scripts/runtime/crypto_funding_watcher.py` owns acquisition and persistence.
  Binance and Bybit run independently in a two-thread pool. Gamma discovery uses
  a separate one-thread pool with only one pending job.

## Source eligibility and direction

Binance instruments must be `TRADING`, `PERPETUAL`, quoted and margined in USDT.
Bybit instruments must be `Trading`, `LinearPerpetual`, quoted and settled in
USDT. Metadata pagination is followed. Closed, settling and unqualified
instruments are excluded even if their ticker still returns a rate.

One canonical contract per venue and underlying asset contributes to aggregation.
Known multiplier contracts (for example `1000PEPEUSDT`) keep their original
instrument identity while being grouped under the corresponding asset.
Unknown ticker strings are not heuristically stripped of digits.

Positive funding means longs pay; negative means shorts pay. The largest absolute
rate retains its actual sign and identifies its venue. Mixed signs are displayed
as mixed, and missing data is never displayed as a zero rate. An eligible
contract's genuine numeric zero remains valid.

The raw percentage and actual funding period are displayed for each venue.
Binance periods come from funding information; Bybit uses ticker funding hours
or instrument funding minutes. An unknown period remains unknown. For comparison:

```
rate_percent = rate_ratio * 100
rate_percent_8h = rate_percent * 8 / actual_interval_hours
simple_annualized_percent = rate_percent * 24 / actual_interval_hours * 365
```

The eight-hour value is a linear comparison, not a guaranteed eight-hour payment.
Per-asset mean and spread use fresh, comparable venues only. The overview's mean
absolute rate uses fresh venue quotes, not the maximum per asset. The 0.015%
eight-hour threshold is an explicit cost watch threshold, not an alpha claim.

## Time, state and retention

Schema version 3 preserves separate fields for source observation, provider
response, local acquisition, eligibility check, last attempt, last success and
published snapshot. Binance has a quote observation clock. Bybit's ticker API
has a response clock, which is labeled as such; no quote-native time is invented.

| Policy | Duration / behavior |
| --- | --- |
| Collector cadence | 30 seconds measured from each cycle's start |
| Visible frontend check | 15 seconds; background/hidden scheduling follows shared runtime policy |
| API request deadline | 8 seconds; resource deadline 10 seconds |
| Venue acquisition budget | 8 seconds per venue, in parallel |
| Fresh quote window | 90 seconds, with at most 30 seconds of future clock skew |
| Quote recovery retention | 15 minutes; original clock and retained label stay visible |
| Eligibility refresh | 10 minutes; verified metadata recovery bounded to 30 minutes |
| Gamma catalogue refresh | 15 minutes; recovery bounded to 30 minutes |
| Gamma discovery | At most 500 active Crypto events per scan, with a 12-second request budget |

`READY` requires accepted current quotes and successful venue qualification.
`PARTIAL` preserves usable sources while exposing missing periods, failures,
retained quotes or qualification degradation. `STALE` does not advance a saved
snapshot's clock. Retained quotes do not contribute to current means or alerts.
Beyond retention, the panel removes expired quotes and continues retrying.
Market-catalogue health is separate from exchange quote health.

HTTP success alone is insufficient: Bybit business status, numeric finiteness,
contract binding, qualification, family/schema identity and clocks are checked.
The same frontend parser validates network responses and restored public caches.

## Useful asset coverage

The contextual core watchlist supplements currently discovered crypto markets;
it includes BTC, ETH, SOL, XRP, HYPE, BNB, DOGE, ZEC, SUI, AVAX, LINK, ENA,
PUMP, ASTER, TAO, AAVE and other assets. Actual inclusion always requires a
qualified venue contract. Discovery can add explicitly named venue-listed
assets beyond the core list.

Active price-linked assets are ranked first. The panel exposes All / Price
markets filters, asset search, market links and 30-row pagination. The API's
default display limit is 80, its maximum is 120, and the panel requests 120.
Acquisition/cache identity is canonical and does not depend on display limit.

Market links bind the individual question to an explicit asset name or ticker;
an asset in a multi-asset event is not assigned to every sibling question.
Ordinary words and country abbreviations are excluded from ticker inference.
Expired or non-tradable markets are not linked. This bounded text association
does not establish token/oracle identity or exhaustive market coverage.
Unsupported assets are reported with a reason instead of fabricated funding.

## Failure recovery and verification

One failed venue does not block the other. Usable saved quotes retain their
source clock and are marked retained. No-source failures preserve the last
success clock. Market discovery failure does not delay quote collection and has
a retry cooldown. API cold start reports warming rather than blocking on venues.
Collector logs contain compact status/counts rather than full quote payloads.

Backend regression tests cover eligibility/delisting, genuine zero versus missing
rates, business errors, clocks, actual intervals, signed aggregation, source
failure/recovery/expiry, read-only seed serving, larger coverage, question binding
and an independent blocked Gamma job. Frontend tests cover parsing/calculation,
automatic publication, cache recovery, manual refresh, failures and expiry.
Browser tests exercise search, market links and venue clocks at desktop/mobile
widths. Production acceptance additionally requires the pushed release identity,
real API snapshots advancing without manual refresh, and real desktop/mobile UI
captures without API substitutions.
