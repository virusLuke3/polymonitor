# TradFi Perp Radar

`tradfi-perp-radar` reuses the `finance-external-sources` owner and its durable
`runtime:finance:external-sources` / `v1` snapshot. The API projects that snapshot
directly; this view creates no collector, secondary snapshot, or request-time HTTP.
The existing owner runs every 900 seconds. The OKX branch shares one 180-second
deadline across six public batch reads, each with a 45-second full-attempt budget
and at most two attempts. Insufficient remaining time skips an attempt.

The batches are tickers, instruments, mark prices, USDT index tickers, open
interest, and funding (`instId=ANY`). URLs come from project environment settings.
The [official OKX contract](https://www.okx.com/docs-v5/en/) defines the units:

- `vol24h` is contracts; `volCcy24h` is underlying quantity for derivatives.
- Contract nominal quantity is contracts × `ctVal` × `ctMult`, in `ctValCcy`.
- Linear contracts' mark valuation is that quantity × current mark, in the
  instrument's quote currency. This is explicitly a valuation, not traded
  turnover. USDT is not relabeled USD. Unsupported USD turnover stays unknown.
- Mark/index basis requires the same instrument/index identity, clocks no more
  than 60 seconds apart and no more than 120 seconds old at computation.
- Funding is the actual forecast for the next settlement; its interval comes
  from the two published settlement times. A real zero is retained. Missing
  funding stays unknown. `oiUsd` is source-reported USD open interest.

Ticker, metadata, mark, index, funding, and open interest retain separate receipt
and observation clocks. Failed metric reads can retain their own last good values
for 30 minutes without advancing those clocks; stale inputs disable derived basis
and valuation. The UI exposes per-field source times and stale state.

Yahoo's six futures rows remain reference quotes. Perpetual funding, mark/index
basis and swap open interest are N/A for those reference rows. Their source quote
time is distinct from fetch time. Source coverage currently excludes unlisted
SPACEX; it is never supplied with fabricated values.

Acceptance window (2026-11-07 UTC): the bounded builder probe returned all 17
listed target swaps with mark/index/funding/basis, contract volume and USD open
interest in 18.2 seconds. The existing owner then persisted its real snapshot at
08:16:55.402793Z, with all 17 swaps complete and no metric errors. The actual local
`/runtime/finance/tradfi-perp-radar?limit=24` returned that same source timestamp,
`cacheMode=external-seed`, 17 swaps and six futures references; reference funding
remained N/A. Frontend release `7239a49f` includes the field display; its production
UI verification is tracked by the release owner. These observations are bounded
acceptance evidence, not a claim of continuous future availability.

Tests cover missing values versus zero, source clocks, alignment, contract units
and retained metric expiry. Formal owner persistence and API projection use the
same source times; request time does not renew those values.

The next normal owner write at 08:32:08 UTC retained all 17 swaps and six
references. The public API and formal SQLite snapshot matched on that clock and
all 85 displayed metric states. Production verification found that the shared
watch-snapshot sanitizer initially discarded `details`; release `da67d2d3` fixes
the bounded parse and browser-cache round trip. The real homepage then displayed
expanded contract metrics, including source units and times. Actual USD traded
turnover remains unknown, and is not replaced by mark-valued USDT volume.
