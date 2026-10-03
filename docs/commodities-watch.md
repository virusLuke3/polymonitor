# Commodities Watch

The global board covers 24 non-FX instruments and nine currency pairs. Non-FX
includes futures, the VIX index, and URA/LIT/COAL ETF proxies. It is macro context,
not an Alpha qualification or a trade recommendation.

## Ownership and refresh

- `scripts/api/clients/market_data_client.py` retains Yahoo quote time, fetch
  time, trading session, currency, session volume and daily previous close.
  The legacy chart-baseline change stays compatible for other consumers.
- `scripts/api/services/commodities_service.py` owns commodity coverage,
  per-symbol retention and bounded read-through recovery.
- The existing market group watcher seeds Redis and SQLite every 60 seconds,
  measured from the start of each cycle. Empty/failed acquisitions do not
  advance the successful snapshot clock; failed symbols can retain their last
  good observation for up to 15 minutes.
- The API serves seed reads immediately. Missing or >180-second snapshots
  initiate a deduplicated background recovery using the same fetcher/cache.
  This is a read-through fallback, not a second scheduled collector.
- The panel's `useCommodityFeed` declares validation, request identity,
  a bounded public browser cache and a 20-second polling policy. Shared
  `usePanelResource` owns cancellation, retries and visibility scheduling.
  No App-level commodity timer or imports from sibling panels are needed.

Visible panels refresh automatically. Hidden documents/offscreen panels pause
requests and check again when visible. Refresh forces an API revalidation,
which normally reads the latest seed; it does not fetch all symbols on every
click. API/validation failures retain the previous usable view and retry with
shared backoff. Seed freshness is 180 seconds; browser recovery retention is
15 minutes. An expired snapshot is never advertised as current.

## Display semantics

Checked time, snapshot time and each instrument's quote time are separate.
Closed-session quotes may remain unchanged. Absent quote clocks or obsolete
session evidence remain unknown; they are not replaced with the current time.
The default compact panel shows controls, clocks and quotes first; explanatory
copy and daily summaries follow the quote grid so prices are visible without
scrolling the desktop panel.
Daily moves use Yahoo `previousClose`, never the five-day chart baseline.
Missing/incompatible previous close displays a dash. Daily summary calculations
exclude retained, stale or unconfirmed quotes, and expose their denominator.
The 1.5% indicator counts daily moves, not news alerts or verified Alpha.
USD/EUR/USX retain dollars/euros/cents respectively; FX displays the pair rate,
and VIX displays index points. Session volume is not rolling 24-hour volume.

`MTF=F` was removed after production verification found a February 2025 quote.
The board explicitly displays `COAL ETF` as a coal-sector equity proxy, not a
coal futures price. Its identity is documented by the [fund issuer](https://www.rangeetfs.com/coal).
The API and watcher import the same universe from `api/commodity_symbols.py`.
Quotes older than four days are unusable even after a successful source fetch.
Standard contract weekly closures override Yahoo's rolling session windows:
see [CME gold hours](https://www.cmegroup.com/markets/metals/precious/gold.timeAndSales.html)
and [ICE TTF hours](https://www.ice.com/products/27996665/Dutch-TTF-Natural-Gas-Futures/1000).
These are conservative regular-week rules, not a complete holiday calendar;
unconfirmed trading-time evidence remains unknown rather than fabricated.

## Acceptance

Run Python commodity, Yahoo and watcher regressions; frontend model/resource
tests; and the commodity browser lifecycle test. Production verification must
observe multiple automatic checks and different seed times, preserve content
during checks, exercise Refresh and FX switching, verify cache restoration,
and capture desktop/mobile views from the actual production URL. A successful
HTTP response does not prove all provider quotes are current.
