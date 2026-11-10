# Macro panel data and refresh contract

Scope: CPI Release Command, CPI Components, Goods/Tariff, Labor/Services,
Fed/Growth and Geo/Sanctions. These retain the explicit registry, panel directories,
Preact and shared runtime. No new polling owner lives in a renderer.

## Acquisition and serving

- FRED driver collectors produce `panel-v3` snapshots with unit, frequency,
  adjustment, statistical period, movement window and original acquisition time.
- Numerical FRED reads share `api/clients/fred_csv.py` across the macro driver,
  food basket, CPI registry and Finance sentiment collectors. They reuse each
  owner's injected Session and the explicit routes in the project `.env`.
  The configured series CSV is requested without adding a dynamic date query;
  the existing four-year lookback is applied locally after validating the named
  series column, finite values and observation dates. Explicit query parameters
  in the configured template remain intact. No new collector or cache is added.
  Each series has at most two transport attempts, a 90-second total deadline and
  a 2 MiB body limit; an existing owner deadline can shorten that budget. Body
  failures retry through the shared transport, without nesting route attempts.
  Statistical date, successful acquisition time and unknown publication time
  remain separate. Existing Redis/SQLite snapshot identities and schedules stay
  owned by the respective collectors; API reads do not execute this reader.
  Finance sentiment preserves each FRED series in `sourceDetails`: the original
  date in `sourceObservedAt`, actual read completion in `sourceFetchedAt`, a null
  `sourcePublishedAt` when unknown, the latest value and the observation count.
  Its CNN/AAII failures remain explicit source errors, including an available
  HTTP status; neither an access denial nor a schema mismatch is a healthy empty
  survey. CNN uses the same owner HTTP adapter and retains a supplied source
  timestamp. Missing survey dates stay unknown.
- The macro registry collector produces complete `panel-v2` snapshots, including
  CPI actual series, previous values and period-matched model nowcasts.
- Registry API requests only read Redis or SQLite. A cache miss returns warming;
  API reads never fetch FRED or rebuild CPI events. SQLite recovery keeps original
  clocks. A failed individual source retains its previous observation with a
  failure label; it does not become a successful new source observation.
- Calendar and energy watch loops use the existing `collection_delay` policy:
  healthy rounds retain their one-hour/six-hour start-to-start cadence; partial,
  preserved or failed rounds retry after 5, 10, 20, then at most 30 minutes,
  subtracting collection elapsed time and resting at least 30 seconds. A stored
  partial payload is still a failed collection round for scheduling. Success
  resets backoff. This reuses each source owner, transport limits and original
  snapshot clocks; a retry is not evidence that a failed source recovered.
- The three macro/food collectors confirm the authoritative SQLite publication
  before mirroring to Redis or advancing a successful seed receipt. A rejected
  SQLite write is a publication failure. Redis is an optional mirror; an outage
  does not block startup, durable reads or successful SQLite publication. The
  collectors read SQLite first, and a first failed attempt leaves lastSuccessAt
  unknown. Retained observations keep their original clocks and are marked stale.
- Default registry composition and its frontend checks are every 30 minutes;
  FRED driver, energy and food acquisition is every 6 hours. Their seven source
  panels check the existing saved seed every 5 minutes while visible, so a new
  collector publication does not wait another six hours for a browser read.
  Manual Refresh checks the saved seed;
  it does not make a visitor run external collection.
- Each selected macro panel has an independent 45-second request deadline, runtime
  retry/cancellation, validation, and a bounded public browser cache. Registry
  freshness is 45 minutes, allowing the normal 30-minute composition cycle;
  source health separately checks the underlying collector interval. The six-hour
  source family uses 9-hour freshness (1.5 collector cycles), with at most 18-hour
  retention from the original acquisition clock. It must not inherit the registry's
  45-minute freshness. Registry recovery retention is also 18 hours; Geo retention
  is 24 hours. Individual source failures and row expiry remain independent.
  Geo uses its 5-minute source cycle and
  a 10-minute freshness budget. Historical conflict dates are never called live.
- These checks reuse the existing shared Runtime, SQLite/Redis identities and
  browser keys. Seven visible source panels add at most seven saved-snapshot
  reads per five minutes, sharing the normal admission, single-flight, deadline
  and retry budgets; they never run FRED/EIA acquisition. Acceptance requires a
  scheduled owner write with new source fetch clocks, followed by an automatic
  public API response and rendered content in the already-open browser.

## BLS replacement for daily monitoring and release archives

The calendar/archive path retains its explicit transport policy for New York Fed
and FRED release calendars and original BLS release PDFs distributed by FRASER.
FRED calendar HTTP reads reuse `api.clients.fred_csv.read_fred_text` (the text
transport, followed by the existing HTML calendar parser): the same working
request identity as other FRED owners, 2 MiB body cap, two complete 40-second
attempts within 90 seconds, explicit configured routes, no inherited proxies.
The calendars keep their original source URLs, release times and reference
period validation; transport recovery must not invent or shift a release.
The existing four FRED CPI numerical series use the shared CSV reader and
configured source routes described above, without changing main Clash. This is a daily
monitoring/archive contract, not a release-instant trading feed. Cleveland Fed
nowcasts, BEA, FOMC and Polymarket data keep their existing owners.

- The existing `cpi_release_calendar_watcher` owns calendar acquisition every
  hour. The `snapshot:macro:cpi-release-calendar / panel-v1` SQLite/Redis identity
  and existing Calendar/Command consumers remain. NY Fed times use
  `America/New_York`, FRED times use `America/Chicago`; conflicting times are
  explicit, and reference months require original release evidence. An absent
  reference month must not be inferred by subtracting a month from release time.
  Calendar HTML uses the shared source Session and explicit project host routes,
  with environment-proxy inheritance disabled. Non-FRED calendar requests have
  at most two attempts, a 45-second attempt timeout, a 90-second total read
  deadline and a 2.5 MB body cap; FRED uses the shared limits above. December
  adds the three next-year FRED calendars within those limits. HTTP/body failures
  use shared retry and Retry-After handling; no route attempts are nested.
  Known calendar pages with no valid releases are schema errors, including
  BEA and FOMC, and each failure appears in `sourceErrors`. An event's
  `verifiedAt` is the successful source read/parse completion; retained events
  preserve that time. A composition consisting only of retained events also
  preserves `generatedAt`, while `projectedAt` records the composition attempt.
  If FRED fails while NY Fed's monthly calendar succeeds, other months of the
  previous annual calendar can remain for seven days with `retained` status and
  their original verification time. A freshly verified month replaces old dates
  for that month; retention never overrides a new date or a detected conflict.
  `freshCount` and `retainedCount` count the full stored event set separately;
  `failedSources` lists failed/conflicting providers independently of display
  filtering and the availability of a successful monthly fallback.
- The existing `inflation_nowcast_watcher` keeps its 30-minute cycle and
  `snapshot:macro:inflation-nowcast / latest` identity. It uses the same source
  Session policy, at most two attempts, 45-second attempt timeout, 90-second
  total deadline and 2.5 MB HTML cap. All three named Cleveland tables must
  contain valid period/measure columns and rows. Missing tables, challenge HTML,
  malformed periods and nonfinite values are errors that preserve the prior
  snapshot and its successful clock. Publisher-declared blank measure cells
  remain blank; they mean that measure has already been released. All monthly
  rows remain available for exact CPI-period matching. `Updated` stays the
  publisher's raw date label; `generatedAt` records successful acquisition after
  parsing and must not be substituted for the model's publication time.
- The existing content worker owns the three BLS source IDs, with FRASER
  directory/PDF transport every six hours. It retains BLS as publisher and
  records FRASER as distributor. Source state/conditional requests and bounded
  retries survive restarts. No browser request acquires these sources.
- Original PDFs, extracted text and metadata are archived under
  `bls-release-archive/` beside the configured snapshot SQLite file. Content
  hashes identify immutable versions; per-source manifests identify the latest
  validated release. This formal archive survives the news store's 90-day
  pruning. It starts with the latest available report, then preserves releases
  and revisions observed by this collector; it is not a complete historical
  backfill. Archive size grows with observed monthly releases, bounded to
  2.5 MB per downloaded document and 12 versions per item in the news projection.
- News metadata/excerpts reuse `content_items`, `content_versions`,
  `content_discoveries`, `content_source_state` and the existing related-news
  seed. The original publication time, archive first reception and successful
  check time remain separate. Old reports stay out of the seven-day news view.
- FRASER uses the existing 45-second source deadline and 90-second collector
  cycle, one concurrent request chain per FRASER domain, at most one latest
  report per topic per cycle, and bounded PDF extraction. Calendar calls have
  per-request time/size limits. Failures preserve validated data and original
  verification times; no hardcoded annual calendar is reported as verified.
  Calendar failure retention is seven days. The API carries the previous three
  days of releases separately for Command's existing post-release window, so a
  daily collection cannot lose the matching event just an hour after publication.
  The worker host requires `pdftotext` (Poppler); no browser or API PDF parsing
  is introduced. Source routing is explicit in the FRASER adapter, and the
  existing CPI calendar watcher retains its route policy; FRED numerical reads
  use the explicit project source routes.
- Acceptance covers direct transport, timezone/year rollover, reference binding,
  conflicting/failed sources, archive versions and restart reuse, original news
  dates, database writes and the real public Calendar/Command/content APIs.
  Hourly/six-hourly cadence requires configuration and scheduler tests plus real
  successful writes; a short deployment check does not establish a full cycle.

Implementation and production evidence are recorded in
[BLS source investigation](bls-source-research-2026-11-04.md).

## CPI event identity

Bind events to the official calendar reference month. Never select a forecast
just because it is the first HTML table row. Keep all nowcast monthly rows and
select the exact month; unknown/missing months leave forecast unavailable.

MoM uses SA `CPIAUCSL` and `CPILFESL`; YoY uses NSA `CPIAUCNS` and `CPILFENS`.
There is no fallback between these adjustments. Previous means the preceding
calendar month, and year-over-year comparisons require the matching month one
year earlier. Missing periods cannot be substituted with positional CSV rows.

Actual stays pending before release and requires the matching observation after
release. Rates are derived from the current FRED index vintage and rounded to one
decimal; these are not an immutable archive of the original BLS first-release
print. Market settlement rules still need verification against the named official
release. Cleveland Fed is a model estimate, not market consensus. Surprise uses
only a saved period-matched pre-release model observation; a first collection
after release cannot fabricate that history.

## Units and interpretation

- PAYEMS is thousands of persons. Display monthly employment change and retain
  the correctly scaled total as context. ICSA/CCSA are persons, not thousands.
- Rate changes use percentage points; daily yields/curve changes use basis points.
- Quarterly real GDP growth is explicitly QoQ annualized, separate from the level.
- Monthly, weekly, quarterly and prior-observation movements keep distinct labels.
- Import/export expenditure is trade context, not an import/export price index.
- Observation date is a statistical period. Collector time is acquisition time.
  Publication time remains unknown if the source does not provide it.
- Deduplicate a repeated FRED series at the same observation date. Do not rank
  mixed movement units or infer inflation from red/green row votes. CPI aggregates
  and subcomponents remain labeled observations, not independent weighted votes.
- Coverage counts leaf source checks; source service count is separate. Neither
  means all series are in the latest official publication period.

Geo separates OFAC list entries and dated policy notices from UCDP historical
conflict observations. A separately bounded `sanctionsItems` sample prevents the
2,000-record conflict cap from hiding already collected policy records. Existing
conflict items and map coordinates remain unchanged. List membership is not evidence of a new sanction action;
historical death estimates are not a live escalation metric.
Policy records use their own single-column layout; macro series keep readable
period and unit labels on desktop and mobile.

## Verification

`tests/test_macro_data_contract.py` covers calendar binding, correct adjustment,
missing periods, units, annualization, seed-only API reads, pre-release forecast
freezing, deduplication and partial failure retention. Frontend macro runtime tests
cover independent refresh policies, validation and bounded cache restoration.
Production acceptance requires the exact pushed release, real public endpoints,
visible panel contents and refresh transitions on desktop and mobile.

Official definitions: [BLS seasonal adjustment](https://www.bls.gov/cpi/seasonal-adjustment/),
[Cleveland Fed model nowcasts](https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting),
[PAYEMS](https://fred.stlouisfed.org/series/PAYEMS),
[GDPC1](https://fred.stlouisfed.org/series/GDPC1),
[IMPGS](https://fred.stlouisfed.org/series/IMPGS).

## Macro market map owner and coverage

`polymarket_macro_map_watcher` projects the existing market-data PostgreSQL
catalog every 180 seconds into `snapshot:macro:polymarket-macro-map / panel-v1`.
It performs no independent Gamma acquisition. The same namespace serves the
macro-map panel and the existing macro/calendars' dependency reads. Public GETs
read the published SQLite snapshot including its retained last value. Redis is
a mirror only when SQLite is configured; a SQLite miss returns `warming` without
collection or writes. A Redis reader is supported only without a SQLite store.

The projector reuses `market_service.market_rows` and
`outcome_semantics_service.sanitize_public_market_payload`. One indexed keyword
query reads at most 101 candidates to retain 100; one batch proves the outcome
semantics. Both use the existing read-only `read_query` policy: 1-second statement
timeout, 100-ms lock timeout, 4-MB work memory, two concurrent panel reads and
the unchanged four-connection host ceiling. The watcher closes its connection
pool after each run rather than reserving a connection between runs. No new
cache, collector, source URL or database allowance is introduced.

Discovery searches registry market titles, slugs and categories using the
existing full-text index and configured macro search terms. It admits active,
unclosed, unexpired canonical markets with matching quote identity and an
observation no older than two hours. Classification also reads the stored event
title and market tags; aggregation uses the original `event_id`, never a title
or guessed ID. Search-only terms/tags cannot establish complete event membership.
`coverage` therefore records candidate/matched counts, the 100-market cap,
truncation, unmatched candidates, unpriced markets, search fields and
`completeness=NOT_PROVEN`; the market universe count remains unknown. API display
limits are recorded separately from acquisition limits.

Each outcome preserves `sourceUpdatedAt` from `quote_updated_at` and
`sourceObservedAt` from `quote_observed_at`. `generatedAt` is only the projection
completion. Event/payload observation ranges retain these original clocks;
publication and failed-attempt clocks remain in seed metadata. Only proven
Yes/No capability admits Yes/No prices, including zero. Every proven source
outcome also keeps its token ID, original source index and label, and corresponding
price. Up/Down and other source labels use this same binding; their Yes/No fields
remain null. The card shows both actual source outcomes of the selected observed
market, its market question, and the original quote clock. No source label is
translated into Yes or No. Missing binding evidence stays explicitly unpriced. Event
liquidity and total event volume remain null; `observedMarketVolume24h` and
`outcomeCount` describe only matching observed members. `endDate` is explicitly
the earliest observed member's end date. Failed refreshes preserve prior values
and clocks, with a safe error type and no false successful receipt.

Acceptance requires a formal watcher write and readback through the existing
consumer API, independent source clocks, declared truncation, preserved failure
clocks and no live collection on a cold public GET. Dated measurements are in
`market-domains-data-audit-2026-11-06.md`, not a claim of future source health.


## Whole-owner budgets and display lifetime

The existing four owners keep their original cadences: macro drivers and food
every 21,600 seconds, registry every 1,800 seconds, macro-map every 180 seconds.
One monotonic acquisition deadline is shared by every source/panel in a round.
Defaults, centrally configured through settings/project `.env`, are 900 seconds
for drivers, 720 for food, 450 for registry, and 30 for macro-map. They bound the
whole source-read phase, not a separate allowance for each source. SQLite durable
publication and metadata use the existing 750-ms busy timeout and optional Redis
2-second timeout; this bounded finalization can extend beyond the acquisition
deadline. There is no hard thread termination or new network/connection owner.
`collectionBudget` records the configured budget, elapsed acquisition time and
full-attempt policy in the actual persisted snapshot.

FRED uses at most two complete 40-second attempts within its 90-second response
budget, with the same owner deadline and existing approved route order. A body
read failure belongs to that attempt, not another nested retry layer. Insufficient
remaining time prevents a new attempt rather than shrinking its timeout. CSV and
other macro HTTP bodies are capped at 2 MiB. CSV filtering remains local and
retains the original statistical observation date. Existing per-series successful
fetch clocks suppress requests before their original cadence. Macro-map retains
the existing permit, statement, lock and response bounds and admits a query only
when the round has sufficient remaining connection/statement time.

Maximum **display** ages are independent of cache TTL and source observation date:

| Input | Acquisition clock used | Default maximum display age |
| --- | --- | --- |
| Five macro driver panels / food | Each row `fetchedAt` | 64,800 seconds (18 h) |
| Registry parent observations / calendar verification | Original metadata `fetchedAt` / `verifiedAt` | 64,800 seconds |
| Registry CPI actual/previous values | Actual-series/event `fetchedAt` | 5,400 seconds |
| Registry nowcast/forecast | Original `forecastFetchedAt` | 64,800 seconds |
| Macro-map market prices | Canonical quote `sourceObservedAt` | 7,200 seconds |

`generatedAt` remains composition time; it never extends a row's lifetime. Missing
acquisition clocks are unknown and cannot authorize indefinite display. An old
monthly observation with a recent successful acquisition remains usable. Retained
failures preserve the original clocks. The API returns `displayRetention` counts
and hides expired values; it does not delete the SQLite snapshot or raw archives.
CPI event labels/counts are recomputed after removing expired actuals, previous
values and forecasts. Food-derived registry rows keep the source row clock, not
the newer parent composition clock.

The shared frontend Runtime has an explicit optional `snapshot.revalidate` hook
on its existing one-second expiry sweep. Only the macro families and macro-map
opt in. Cache restore and offline sweeps apply the same row/event clocks; unchanged
values keep their object identity. No new timer, collector, API polling cadence,
or JSON traversal of every other panel is introduced. Registry/source cache
retention is at most 18 hours; map cache retention is at most two hours.

### Acceptance for this change

`tests/test_macro_collection_policy.py` runs the real food owner publication path
against an isolated SQLite database and reads it back through the real consumer:
valid monthly observations survive, expired display values disappear, and persisted
records/clocks remain unchanged. Transport tests prove two complete route attempts
and no fractional attempt after another panel consumed the round budget. Outcome
tests prove original Up/Down token binding, 0/1 prices and null Yes/No fields.
Runtime tests advance offline time and check partial expiry, 5,400-second actuals,
unchanged object identity and no revalidation of unrelated panels.

A bounded read-only production catalog preflight at 2026-11-07 08:00:46 UTC
returned 100 candidates / 46 observed events, truncation true, universe unknown,
and zero unpriced observed markets. The oldest quote was 07:18:55 UTC. This
particular sample contained no Up/Down markets; it does not establish production
coverage of directional outcomes. It performed no business write or service
restart and is preflight evidence only.

Production acceptance requires installing the exact owned backend changes,
letting the existing owners perform their authorized run, then comparing the
SQLite namespace/key payload and consumer API for identical source fetch/quote
clocks, source states, bounded coverage and full-attempt budget metadata. Verify
current outcome token/label/price pairs against that run's canonical evidence; if
no directional market is in scope, record that limitation. Confirm an expired
consumer projection cannot renew data by re-publication or Redis fallback. An
HTTP 200, a successful unit test, or the read-only catalog preflight is not this
formal owner-write/consumer acceptance. The separately authorized production
restarts and resulting evidence are recorded below.


### Formal owner/consumer evidence, 2026-11-07

The four existing services were individually restarted at 08:15:09–08:15:20 UTC
after verifying each deployed file against the captured before hash. No parallel
manual owner was launched; these four legacy owners do not have a shared owner
lock. Food's actual write at 08:16:04 contained all 8 source successes with original
per-series fetch clocks 08:15:18–08:16:04, using 54.528 of 720 seconds. Its consumer
returned the identical SQLite version and eight rows.

Macro-map's formal write at 08:15:22 used 0.871 of 30 seconds, with 100 candidates,
46 observed events and zero unpriced observed markets. The consumer returned
12 rows, `sqlite-seed`, `displayTruncated=true`, and the exact same version; every
returned token/label/price pair and quote clock matched the formal SQLite payload.
The universe remains unknown and acquisition remains truncated. The sample contains
no directional market, so Up/Down production coverage remains unobserved, despite
passing the canonical-shape/zero-price regression.

The macro driver's first full acquisition round ran from 08:15:13 to 08:21:38,
about 384 of 900 seconds. Of the 54 FRED input slots, PPIACO initially timed out;
its retained value kept the previous successful fetch clock. The original owner's
automatic recovery round completed at 08:22:11, with a real PPIACO acquisition at
08:22:10.431747 and the other 53 source clocks unchanged under their six-hour
cadence. All five formal driver snapshots then reported their sources `ok`.
The recovery round's 2.887-second acquisition metadata describes that cached
recomposition plus one recovered source, not 54 new network acquisitions.
Each driver's consumer matched its SQLite version and displayed row clocks;
the endpoint's 12-row cap still limits supply and labor display. Together with
food, these writes verify 62 input slots, not 62 unique FRED series or all project
macro sources.

Registry's initial post-restart run wrote five snapshots in 2.969 of 450 seconds.
After the parent acquisitions finished, the original registry service was restarted
at 08:24:07 and wrote its next five snapshots at 08:24:08–08:24:10, using 1.303 of
450 seconds. At the 08:26:59 readback, all five consumer versions matched SQLite,
and the CPI consumer explicitly reported `cacheMode=sqlite-seed`. The goods
registry kept PPIACO's actual 08:22:10.431747 fetch clock. Goods, labor and Fed/growth
registries were `ok`; CPI and components remained `degraded`.

CPI previous count remains 4; actual count is 0 for the scheduled October release,
and `calendar.cpiSchedule=error`. Its four actual-series inputs keep their successful
07:57 fetch clocks and September observation period, rather than acquiring them
again before the 1,800-second cadence or replacing the clocks with composition
time. The retained CPI schedule is explicitly marked `scheduleStatus=retained`;
optional FRED CPI/employment/PPI calendars and NY Fed calendar remain failed.
These errors do not establish a complete current annual calendar. Energy refresh
remains an independent failed source for the components registry.

A **controlled future-clock projection**, using those actual formal SQLite payloads
in read-only mode, checked display expiry without changing system time or stored
data: food +19 hours hides all 8 rows; map +3 hours hides all 46 events; CPI +2 hours
keeps the 22 still-valid parent rows but removes all four previous values. Original
`generatedAt` and the exact persisted payload bytes were unchanged in all cases.
This is expiry-path verification, not a claim that the current data was expired.
