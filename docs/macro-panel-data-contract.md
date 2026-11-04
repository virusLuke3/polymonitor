# Macro panel data and refresh contract

Scope: CPI Release Command, CPI Components, Goods/Tariff, Labor/Services,
Fed/Growth and Geo/Sanctions. These retain the explicit registry, panel directories,
Preact and shared runtime. No new polling owner lives in a renderer.

## Acquisition and serving

- FRED driver collectors produce `panel-v3` snapshots with unit, frequency,
  adjustment, statistical period, movement window and original acquisition time.
- The macro registry collector produces complete `panel-v2` snapshots, including
  CPI actual series, previous values and period-matched model nowcasts.
- Registry API requests only read Redis or SQLite. A cache miss returns warming;
  API reads never fetch FRED or rebuild CPI events. SQLite recovery keeps original
  clocks. A failed individual source retains its previous observation with a
  failure label; it does not become a successful new source observation.
- Default registry composition is every 30 minutes; FRED driver, energy and food
  acquisition is every 6 hours. Frontend checks are every 30 seconds while the
  runtime owns an active visible consumer. Manual Refresh checks the saved seed;
  it does not make a visitor run external collection.
- Each selected panel has an independent 12-second request deadline, runtime
  retry/cancellation, validation, and a bounded public browser cache. Registry
  freshness is 45 minutes, allowing the normal 30-minute composition cycle;
  source health separately checks the underlying collector interval. Recovery
  cache retention is at most 24 hours. Geo uses its 5-minute source cycle and
  a 10-minute freshness budget. Historical conflict dates are never called live.

## BLS replacement for daily monitoring and release archives

The daily-monitoring path uses direct HTTPS, without inherited Clash/SOCKS
variables: New York Fed and FRED release calendars, the existing four FRED CPI
series, and original BLS release PDFs distributed by FRASER. This is a daily
monitoring/archive contract, not a release-instant trading feed. Cleveland Fed
nowcasts, BEA, FOMC and Polymarket data keep their existing owners.

- The existing `cpi_release_calendar_watcher` owns calendar acquisition every
  hour. The `snapshot:macro:cpi-release-calendar / panel-v1` SQLite/Redis identity
  and existing Calendar/Command consumers remain. NY Fed times use
  `America/New_York`, FRED times use `America/Chicago`; conflicting times are
  explicit, and reference months require original release evidence. An absent
  reference month must not be inferred by subtracting a month from release time.
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
  existing CPI watcher remains direct; FRED numerical reads use their existing
  direct/no-proxy route.
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
