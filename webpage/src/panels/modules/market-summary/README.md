# Market Summary

`index.tsx` owns the summary view; `model.ts` validates selected identity and
selects display quotes. This is an existing-data view with no new collector,
storage, historical aggregation or persistent browser cache.

## Shared data

- Market, Gamma quote and official 24-hour volume: existing `useMarketFocus`
  and catalog → `market_service.py` → market-data's PostgreSQL
  `core.markets` / `core.market_quote_current`. Detail checks every 60 seconds;
  catalog every five minutes. The source quote/observation clocks remain intact.
  API acceptance, bounded stale reuse and database budgets follow
  `scripts/api/services/market_service.py` and the existing shared runtime.
- Order book: Summary and FocusedMarketStrip both consume
  `features/market-focus/useFocusedOrderBook.ts`. Its `orderBookResource.ts`
  declaration uses the existing `PanelResourceProvider` / Runtime with the
  complete key `market-book:v1:<marketId>:<yesToken>:<noToken>`. Same-key views
  share data, requests, cancellation, retries and visibility demand.
- The existing `/runtime/lob/token/{yesToken}?noTokenId=…&marketId=…` route
  reads the market-data gateway's committed snapshot via the dedicated reader.
  Its server cache, storage identity and acquisition stay with that owner.
  Browser checks remain two seconds; HTTP timeout three seconds, runtime
  deadline 3.5 seconds, retry backoff up to 60 seconds with Retry-After.
  No additional PostgreSQL/ClickHouse reads are introduced by Summary.

## Quote semantics and failures

Both tokens and any returned market identity must match. Snapshot quotes need
`upstreamReady=true` and an observation within 30 seconds; continuous quotes
retain the existing continuity/heartbeat/deadline rules in `orderBook.ts`.
Retention is at most 30 seconds from observation/heartbeat, never response
generation. Last-event time is shown separately. A failed refresh withdraws the
current book quote; same-market Gamma values can still be shown with their source.
Closed markets do not acquire or display current execution quotes. Switching
selection cannot reuse another market's bootstrap, group, price or book.

Missing 24-hour volume/count is explicit. Neither recent 50-event flow nor the
bounded chart is a full-day count. No complement, price or zero statistic is
fabricated. Existing compact YES/NO and metric rows, typography and semantic
colors are preserved; a small source/time line explains the quote basis.

## Verification

`model.test.ts` covers missing Gamma data, identity changes, stale/unready books,
closed markets, zero values and resource validation. Browser checks in
`e2e/market-summary.spec.ts` and the focused-book lifecycle cases verify real
view sharing, independent consumers, switch cancellation, automatic updates and
hidden-page behavior. Production acceptance uses the ordinary homepage with
real APIs and desktop/mobile screenshots; local fixtures do not prove source
coverage or uptime.

### Acceptance observation — 2026-11-05

Frontend change `10a7c2a2` passed 389 unit tests (one skipped), the targeted
shared-book/lifecycle browser checks and both Summary visual sizes. Its clean
archive build was deployed and verified; the subsequent production release
`696061ed` includes the unchanged fix. The ordinary `https://polymonitor.club`
homepage was checked at 1440px and 390px using real APIs and persisted selection.
The mobile document stayed within 390px and no JavaScript page errors occurred
in the checked desktop session.

For market `550186`, a 25-second production observation captured seven successful
scheduled book responses with at most one request in flight. Both quote views
withheld the current price because every response had `upstreamReady=false`;
the last source event remained `2026-11-05T05:25:57.755Z`. Missing full-day metrics
were explicit. This verifies shared reads and unavailable-source behavior,
not recovery of this market's upstream feed or complete 24-hour coverage.
