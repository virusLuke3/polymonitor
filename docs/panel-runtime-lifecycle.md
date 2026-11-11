# Shared panel lifecycle

The panel registry, Preact and one-directory-per-panel ownership remain intact.
`usePanelRuntime` owns demand, scheduling, retries, in-flight state and cleanup.
`usePanelResource` adapts parameterized resources to that owner; it does not
start another request scheduler. `PanelRuntimeView` only exposes workspace
status and manual refresh to shared family controls.

## Common contract

- Refresh uses the configured interval since the last attempt. Source freshness
  determines READY/STALE and cache eligibility, never whether a check is due.
- Each resource has its own completion, abort signal and complete-request
  deadline (`requestTimeoutMs`, default 45 seconds). A provider which ignores
  abort cannot hold in-flight state forever. Late results cannot publish.
- A settled resource releases its lane immediately; it does not wait for an
  unrelated resource. A shared HTTP batch can only publish after its response
  arrives, and is aborted after all resource leases finish or cancel.
- Batch, single endpoint and transport fallback pass through the same
  `parseRuntimeSnapshot` path. Payload object, source status and original clock
  are checked everywhere. Domain contracts additionally verify resource
  identity, rows, numerical values, links and retention bounds.
- Transport fallback consumes the original deadline, rather than gaining a new
  deadline. Wrong resource identity is non-retryable until manual refresh or a
  parameter change; transient outages retry with bounded backoff and jitter.
- Healthy empty responses may remove previous rows. Source errors preserve
  valid previous data, with explicit error/stale status. Domain invalidations,
  such as revoked Alpha evidence, can deliberately replace old unsafe data.
- `checkedAt` is validated request completion. `generatedAt` is seed generation.
  Individual quote/publication clocks remain original; copying a seed between
  Redis, SQLite and browser storage cannot renew its lifetime.
- Every data owner declares a versioned, parameter-complete persistence policy. They are bounded
  by count, total encoded size and each resource's original source age.
- Hidden pages and offscreen views pause automatic demand. Returning catches
  up; explicit summary/map demand can keep a resource active. Unmount cancels
  only that consumer's demand. Manual refresh is an explicit override.

## Reload recovery

### Shared persistence capacity

The full 121-panel inventory, independent clocks, source acceptance and pinned
WorldMonitor comparison are recorded in [the 2026-11-10 audit](panel-cache-loading-audit-2026-11-10.md).
This dated observation does not replace per-domain live health checks.

Every resource with a non-null cache contract writes its validated envelope to
the shared IndexedDB store. Small resources also keep a bounded localStorage
copy for synchronous first paint and storage fallback; eviction from that
2,000,000-character / 96-entry copy does not delete the IndexedDB entry.
IndexedDB retains at most 256 keys / 16,000,000 encoded characters. This budget
covers the registered public owners together, rather than assuming the former
96-entry localStorage-only budget can hold the whole dashboard. Explicit
`storage: 'indexeddb'` resources skip the synchronous copy. Private and execution
resources with `cache: null` still never persist. Key/version/domain validation,
800 ms hydration admission release and 5 s storage transaction bounds apply to
both static owners and parameterized `usePanelResource` consumers.

Geo/Sanctions shares its existing map owner and 2,000-row limit; its roughly
1.1-million-character snapshot uses IndexedDB with a 2,000,000-character entry
cap. A successful network parse is not proof of persistence: acceptance also
checks the encoded size and reads the entry after localStorage eviction.

### Overnight public overview recovery

NBA, ESPN, public news, DeFi token overviews, Finance/Tech overviews and the
shared weather forecast retain their last validated display snapshot for 24 hours
from its original source time. This replaces the former 15/30-minute (weather:
six-hour) display eviction, which made an overnight visit cold even after a
successful visit. Freshness and collection/check intervals stay unchanged: an
overnight snapshot is STALE, shows its original timestamp and triggers a
background read. A retry must not cover that content or hide an existing error
behind a fresh full-panel loading overlay. The shared cache engine is reused;
this is a display policy for public context, not an execution quote lifetime.

DeFi rows expire independently at the same 24-hour display ceiling and old rows
mark the display stale even beneath a newer envelope. Weather catalog/date and
book eligibility retain their independent expiry; forecasts do not renew them.
Private/execution resources, revocable evidence, AI expiry and bookmaker quote
limits keep their own contracts. GAME/SPORTS retain their public context for
24 hours too, but restore runs their existing per-quote/per-fixture expiry;
expired odds are removed and never made eligible by the envelope age. First visits, evicted/invalid entries and data
older than the display ceiling still need a successful network read.

The default Runtime deadline includes queueing and is 45 seconds; public macro
owners use this budget too, instead of exhausting 12 seconds in the download
queue. Their network/body timeout remains separate. Weather's
multi-megabyte read has a 35-second complete-body transport limit and a
60-second total Runtime limit, replacing its conflicting 12/10-second limits.
Desktop/mobile download concurrency remains three/two; these read budgets do
not change collection frequency or create a second scheduler.

### Failure recovery adopted from WorldMonitor

Reference: WorldMonitor commit `fc1e04743e340fdfcc1de13633c4424d88fe8a18`,
[`Panel.showError`](https://github.com/koala73/worldmonitor/blob/fc1e04743e340fdfcc1de13633c4424d88fe8a18/src/components/Panel.ts#L1131),
[`CircuitBreaker.execute`](https://github.com/koala73/worldmonitor/blob/fc1e04743e340fdfcc1de13633c4424d88fe8a18/src/utils/circuit-breaker.ts#L418)
and [`RefreshScheduler`](https://github.com/koala73/worldmonitor/blob/fc1e04743e340fdfcc1de13633c4424d88fe8a18/src/app/refresh-scheduler.ts#L126).
Adopt their behavior in the existing Runtime for every resource owner and view:

- Normal polling, failure retry and maximum retained source age are independent.
  Retryable errors use 15/30/60/120/180-second delays, capped at 180 seconds plus
  up to 10% jitter, until accepted recovery or demand ends. Explicit quick
  attempts precede this sequence; exhaustion never falls back to normal polling.
- One retry timer and one in-flight request per resource. HTTP Retry-After is a
  separate lower bound. Non-retryable failures await manual retry or a new identity.
  Hiding/offscreen demand suspends retries without clearing failures.
- Visibility/connectivity recovery schedules failed demanded owners by interval,
  staggered by 100 ms for the first four gaps and 300 ms afterward. It may shorten
  client backoff, never Retry-After; at least one second separates attempts.
  Connectivity recovery also rechecks healthy demanded owners using that stagger.
- Fresh-age expiry marks data stale; only domain retention expiry removes it.
  Failure preserves data and original clocks. Accepted responses immediately
  publish to subscribers and clear errors/retries/backoff. Restored or retained
  fallback data is not successful recovery.

WorldMonitor's five-minute breaker cooldown is not another scheduler here:
Runtime already bounds requests and publishes accepted results reactively. Keep
domain hard expiry instead of unbounded stale fallback; WorldMonitor's 24-hour
persistent hydration ceiling is not a universal display-validity guarantee.

Market catalog keeps five-minute checks/freshness and retains navigation context
for fifteen minutes, visibly stale/degraded. Existing API/storage identity and
per-quote validity remain unchanged; book/flow/Oracle keep independent clocks.
A detail 404 with an empty catalog preserves selection intent until catalog
recovery. Explicit user selection/deselection cancels pending reconciliation.
WorldMonitor's external-link prediction list has no equivalent selection owner.

Acceptance covers repeated failures beyond quick attempts, resume, Retry-After,
single-flight/cancellation, immediate successful publication/error clearing,
stale catalog during pending/failed reads, valid empty/hard expiry, 404/empty/
catalog recovery and explicit selection. Production uses actual desktop/mobile
APIs and reports source failures separately.

Public persistence is an explicit resource contract, not a second collector or
scheduler. Restore validated data and its original source/check clocks before
network admission. Bootstrap loading must not cover restored content. A fresh
saved check may defer the next automatic read only until the existing browser
interval is due; stale data requests a background check while remaining visible
within its domain retention bound. Manual refresh bypasses that deferral.

Restore READY/STALE/degraded state from the payload and original age, with
`cacheMode=browser`; restoration is not a new successful request. Failed refreshes
retain the last valid value without refreshing its lifetime. Healthy empty
responses replace it; warming/errors must not overwrite a saved successful
snapshot. Expiry removes data even if another request is still pending.

The existing `resource-cache.ts` storage namespace remains the single public
browser cache. Complete keys include panel/resource ID and request limit; schema,
shape, original timestamp and capacity are validated on read and write. Storage
failure is optional and must not affect layouts or current content. Dedicated
resource consumers and workspace resources share these rules through
`usePanelRuntime`; views of a shared owner do not create separate copies.

All public resources use the IndexedDB backend of `resource-cache.ts`: database
`polymonitor-panel-snapshots-v1`, `payloads` and `metadata` stores, at most 256
entries and 16,000,000 encoded characters across all owners. Small resources
also keep a synchronous localStorage mirror, bounded to 96 entries and 2,000,000
encoded characters in total (default 256,000 per entry; the nine feeds below
retain their 128,000 cap). Eviction from this mirror does not delete the durable
copy. Weather caps an entry at 4,000,000, Geo/Sanctions, transport and market
history at 2,000,000, crypto research/history at 1,000,000. Encoded
characters are capacity units, not a promise of physical disk bytes. Writes and
oldest-entry eviction are atomic. IndexedDB restore precedes request admission;
a blocked/disabled store releases admission within 800 ms. The storage operation
may complete for up to five seconds, so a busy main thread cannot discard a valid
large snapshot merely by delaying its callbacks. A late restore may fill an empty
view while the network check remains pending, preserving that attempt/error; it
can never replace accepted network data or a different parameter identity. Both
storage backends reuse the same envelope/validator and introduce no second
scheduler. The envelope
adds the complete key and last validated `checkedAt`; old entries without that
check clock may still restore under their existing schema, but must recheck.
No layout keys are migrated or removed. `public-feed:<id>:limit:<n>:v1` identifies
the nine reviewed static feeds below; the declarations remain in each module.

| Public feed / reused owner | Browser check | Fresh / maximum retained source age |
| --- | --- | --- |
| NBA scoreboard, intel, ESPN predictor / `nba_watcher.py` | 60 seconds | 3 minutes / 24 hours |
| Esports / `grid_esports_watcher.py` | 2 minutes | 4 minutes / 24 hours |
| Sports Odds / `sports_odds_watcher.py` | 15 minutes | 3 / 24 hours |
| Jin10 / `jin10_watcher.py` | 60 seconds | 5 minutes / 24 hours |
| BWE (`f1-trackside`) / `f1_watcher.py` | 3 minutes | 5 minutes / 24 hours |
| DeFi Tokens / `defi_token_watch_watcher.py` | 5 minutes | 15 minutes / 24 hours |
| New Market Signals / `new_market_signal_watcher.py` | 5 minutes | 15 minutes / 24 hours |

The legacy Esports/Odds rows describe the feed adapter; current GAME/SPORTS
use the bookmaker owner with independent quote expiry inside the 24-hour
display envelope.

Their existing seed namespaces (`snapshot:sports:nba`, `snapshot:sports:nba-intel`,
`snapshot:sports:nba-matchup-predictor`, `snapshot:esports:esports-intel`,
`snapshot:sports:sports-odds`, `snapshot:macro:jin10`, `snapshot:sports:f1`,
`snapshot:finance:defi-token-watch`) and existing key builders remain authoritative.
New Market keeps its existing Redis queue; public snapshots now use confirmed Redis seed publication.
Collectors retain their existing source schedules; this change adds no producer,
history store, paid fetch or faster acquisition. Finance/Tech and parameterized
resources reuse the shared recovery/status changes with their own domain limits.

The seven NBA/Jin10/BWE/Esports/Odds GETs now use `read_public_seed` in
`scripts/api/services/seed_recovery.py`: the canonical Redis seed store,
original-clock retention, no publication or synchronous upstream work. A cold
read returns warming with no fabricated timestamp. DeFi already follows the
same separation. API read success does not establish collector health.
Account data and execution-sensitive resources retain their explicit contracts;
this is not automatic persistence of every registered resource.

Acceptance covers a real reload after a successful read, fresh-check deferral,
stale-while-refresh, request failure, authoritative empty, expiry, manual retry,
two consumers, and restoration while bootstrap is pending. Local intercepted
tests prove failure semantics; production uses real desktop/mobile requests and
separately reports restored content, current source freshness and source errors.
Checks: `tests/test_public_panel_seed_reads.py`, the existing source/watcher
tests, `resource-cache.test.ts`, `shared/public-feed-snapshot.test.ts`,
`e2e/panel-reload.spec.ts`, and shared lifecycle/resource browser regressions.

## Registration and coverage

Persistence belongs to the data resource, never to a list of selected Panel IDs.
Every `runtimePanelFromRenderer` owner must declare a `snapshot`; every
`PanelSnapshotContract` (including `PanelResource`) must declare `cache`.
A public snapshot supplies its schema/version/size budget. `cache: null` is an
explicit memory-only policy, documented at the owner. Omission is a type and
registry error. The common cache/runtime handles restoration, validation, writes,
expiry and background refresh for every such owner; no Panel implements a second
storage loop. Pure `dataSourceId` views inherit their owner's policy and key.

The nine public feeds above are one group of owners, not a cache-engine
allowlist. Finance, Tech, Macro, Politics, disclosures and parameterized news,
quotes and signals already use the same engine. AI Insights (three lenses),
media directories, radar, weather/news, transport, energy/calendar/nowcast and
commodity transmission now follow the same rule. Domain parsers, time limits and
identity stay with the owner. The shared public-snapshot constructor has no Panel
ID allowlist; it requires a parser and original clock.

Selected market order books and designated contract reference stay explicitly
memory-only because reloading must recheck current eligibility and continuity.
The weather book demand resource is also memory-only; the weather forecast and
catalog owner can restore public context with independent catalog/date and quote
expiry. Public crypto research inputs use their existing parser and per-source
validity; caching cannot make a retained quote current. Account/bootstrap settings
are never copied wholesale into a public cache. Market workspace views reuse the
existing catalog/focus owners; their low-latency flow/oracle/book requests remain
separate from public metadata/history recovery.

Coverage is checked against the imported registry, including shared views and
parameterized owners. A cached resource is not evidence that its upstream is
healthy. Source failures, capacity eviction, first visits and expired data still
require a network read. Each storage backend has a shared budget; one resource cannot allocate another
independent quota.


The current imported registry has 86 views, with this coverage:

| Views | Public persistence |
| --- | --- |
| 58 static fetch owners | All declare and use the shared snapshot/cache contract |
| 7 pure weather views | Reuse the weather owner's payload/key; no copied cache |
| 12 parameterized research/news/quote/signal views | Shared resource contracts; complete asset/query/limit identities |
| 4 market context views (catalog, summary, featured, history) | Existing catalog/detail/history reads now owned by shared Runtime |
| 4 current-state views (Crypto Reference, selected OrderFilled, Oracle, LOB) | Memory only; current eligibility/continuity must be rechecked |
| 1 Trade Policy view | Static view, no data acquisition/cache |

Thus 81 views consume persistent public context; this does not mean all their
fields are current or all their sources are healthy. Weather quote demand and
account state remain outside public persistence. Registry and type checks reject
an omitted policy for a new Runtime/resource owner; pure views reuse an owner.

Newly covered owners retain their existing acquisition and server storage:

| Owner / existing read chain | Browser check | Fresh / retained source age | Browser identity |
| --- | --- | --- | --- |
| AI Insights: existing agent snapshot API, three lenses | 15 min | 12 h / 12 h, also explicit snapshot expiry | lens + version |
| TV / YouTube: existing content directory snapshots | 15 min | 30 min / 6 h | panel + limit 60 + version |
| Breaking radar: existing evidence snapshot | 5 min | 15 min / 30 min | panel + limit 12 + version |
| Weather: existing forecast + catalog/books join | 1 min | forecast 2 h / 24 h; catalog 15 min; quote clocks independent | panel + limit 60 + version |
| Weather news: `snapshot:weather:news / panel-v1` | 5 min | 15 min / 24 h | panel + configured limit + version |
| Transport: `snapshot:transport:global-shipping / panel-v3` | 15 min | 2 h / 6 h; source sample clocks unchanged | panel + limit 14 + version |
| Energy / CPI calendar / nowcast: existing macro snapshot APIs | 6 h / 1 h / 30 min | 18 h / 3 h / 90 min, no further stale extension | panel + configured limit where applicable + version |
| Commodity transmission: existing composition API | 5 min | 5 min / 15 min from original response generation | panel + limit 8 + version |
| Crypto strategy/history: existing aggregate API and domain parser | existing domain intervals | existing independent per-source validity | existing full resource identity + version |
| Market catalog: existing bounded PostgreSQL-backed API | 5 min | 5 min / 15 min | active + page 1 + limit 50 + sort + version |
| Market detail: existing stored metadata API | 1 min | 1 min / 5 min | market ID + version |
| Market history: existing bounded OrderFilled history API | 90 s | 90 s / 5 min | market ID + range + interval + version |

These adapters add no server store, collector, upstream call or faster source
schedule. The domain APIs and existing storage keys remain authoritative; this
change does not assert that every API is seed-only. Commodity composition's
`generatedAt` is its assembly clock and cannot prove upstream quote freshness.
Weather reload revalidates catalog age and city date independently of forecast
age. Market detail restoration excludes live book/flow/Oracle/history fields;
history restores historical observations, not executable current quotes.

Coverage/reload checks include `public-snapshot.test.ts`, market resource tests,
and `e2e/panel-reload.spec.ts` (native multi-megabyte IndexedDB, blocked storage,
original clocks, shared owner, expiry), plus market switching and weather quote
regressions. Real production acceptance remains separate from these fixtures.

## Adopted families

| Family | Browser checks | Collector cadence | Fresh seed | Maximum retained seed |
| --- | --- | --- | --- | --- |
| Crypto | 5 minutes | Existing market group watcher, default 5 minutes | 15 minutes | 15 minutes |
| Finance factory (11 panels) | 10 minutes | Existing finance watcher, default 10 minutes | 15 minutes | 24 hours (display) |
| Tech factory (3 panels) | 10 minutes | Existing tech watcher, default 10 minutes | 15 minutes | 24 hours (display) |

See [Panel cadence](panel-data-cadence.md) for domain-specific targets and
production evidence. Undeclared fast/slow intervals default to 1/10 minutes;
bootstrap/manual resources do not poll periodically. Execution-related
resources retain their explicit low-latency intervals.

The Finance/Tech factories preserve batching and their configured limits. Their
shared parser bounds rows, sanitizes malformed fields, rejects mismatched panel
IDs and keeps partial source failures visible. Cold GETs return warming quickly;
overdue GETs return bounded stale seeds quickly. A keyed recovery invokes the
existing builder in the background, with four process slots, a 30-second key
cooldown and the existing cross-process SnapshotStore fetch lock. It carries
Flask application context and refuses to overwrite a newer watcher publication.
Background acquisition still depends on each existing builder's upstream timeout.
This is recovery, not a second periodic collector.

Finance/Tech watcher cadence is start-to-start; collection time no longer adds
another full interval. Their in-process acquisition cache now honors its TTL
instead of reusing the first Yahoo response for the lifetime of the watcher.
Weekends and closed stock markets can legitimately keep
prices unchanged even though the collector seed and check clocks advance.

## Crypto semantics

Crypto owns its contract/model/view in `modules/crypto-watch`. The symbol universe
is the existing 13 assets. Yahoo Finance is primary; the existing CoinGecko
fallback remains. Individual failed symbols retain previous valid quotes only
within 15 minutes of original quote/fetch clocks. Entire acquisition failure
never advances the seed generation clock. Crypto has no weekend closure rule.

Yahoo's chart baseline is not a rolling 24-hour return. The collector requests
five days of five-minute bars, finds a reference at quote time minus 24 hours
(with at most ten minutes of reference-time approximation), and exposes
`reference24hAt`. Without a reference, return is unknown. CoinGecko's documented
24-hour field uses its own original update clock. Provider volume is displayed
as SOURCE VOL unless the payload explicitly identifies rolling 24-hour volume.
Untimestamped CoinGecko sparkline values are not assigned fabricated timestamps.

## Acceptance

Unit and browser checks cover uncooperative producers, deadline cancellation,
independent completion, shared batch cancellation, unified parsing, bad clocks,
wrong identity, healthy empty, bounded stale retention, public cache size,
Crypto interval updates and outages, Finance/Tech interval updates and source
partial states. Release acceptance additionally requires the pushed commit's
production identity, backend hashes, real desktop/mobile screenshots and actual
source/check clock advancement without API substitution.

The shared lifecycle applies broadly. Domain parsers and real upstream readiness
must still be adopted and verified family by family; this change does not assert
that every registered Panel is healthy or fully migrated.

### Relay transfer budget

Geo/Sanctions uses 60s total / 35s complete-body transport. Shared crypto strategy
and historical inputs use 45s total / 35s transport; the contract-reference and
LOB deadlines remain independent. The API HTTP layer negotiates gzip for these
large public payloads and the weather payload before the Tencent relay, preserving
source time and cache headers. See the resource contract for the exact public
allowlist and the full audit for measured pre-compression latency.
