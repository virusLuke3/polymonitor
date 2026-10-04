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
