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
  deadline (`requestTimeoutMs`, default 30 seconds). A provider which ignores
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
- Public caches are opt-in, versioned and parameter-complete. They are bounded
  by count, total encoded size and each resource's original source age.
- Hidden pages and offscreen views pause automatic demand. Returning catches
  up; explicit summary/map demand can keep a resource active. Unmount cancels
  only that consumer's demand. Manual refresh is an explicit override.

## Reload recovery

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

The cache is bounded to 96 entries and 2,000,000 encoded characters in total;
the additional public feeds cap each entry at 128,000 characters. The envelope
adds the complete key and last validated `checkedAt`; old entries without that
check clock may still restore under their existing schema, but must recheck.
No layout keys are migrated or removed. `public-feed:<id>:limit:<n>:v1` identifies
the nine reviewed static feeds below; the declarations remain in each module.

| Public feed / reused owner | Browser check | Fresh / maximum retained source age |
| --- | --- | --- |
| NBA scoreboard, intel, ESPN predictor / `nba_watcher.py` | 60 seconds | 3 / 15 minutes |
| Esports / `grid_esports_watcher.py` | 2 minutes | 4 / 15 minutes |
| Sports Odds / `sports_odds_watcher.py` | 15 minutes | 3 / 6 hours |
| Jin10 / `jin10_watcher.py` | 60 seconds | 5 / 30 minutes |
| BWE (`f1-trackside`) / `f1_watcher.py` | 3 minutes | 5 / 30 minutes |
| DeFi Tokens / `defi_token_watch_watcher.py` | 5 minutes | 15 / 30 minutes |
| New Market Signals / `new_market_signal_watcher.py` | 5 minutes | 15 / 30 minutes |

Their existing SQLite namespaces (`snapshot:sports:nba`, `snapshot:sports:nba-intel`,
`snapshot:sports:nba-matchup-predictor`, `snapshot:esports:esports-intel`,
`snapshot:sports:sports-odds`, `snapshot:macro:jin10`, `snapshot:sports:f1`,
`snapshot:finance:defi-token-watch`) and existing key builders remain authoritative.
New Market keeps its existing Redis queue and confirmed SQLite publication.
Collectors retain their existing source schedules; this change adds no producer,
history store, paid fetch or faster acquisition. Finance/Tech and parameterized
resources reuse the shared recovery/status changes with their own domain limits.

The seven NBA/Jin10/BWE/Esports/Odds GETs now use `read_public_seed` in
`scripts/api/services/seed_recovery.py`: local SQLite before optional Redis,
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

## Adopted families

| Family | Browser checks | Collector cadence | Fresh seed | Maximum retained seed |
| --- | --- | --- | --- | --- |
| Crypto | 5 minutes | Existing market group watcher, default 5 minutes | 15 minutes | 15 minutes |
| Finance factory (11 panels) | 10 minutes | Existing finance watcher, default 10 minutes | 15 minutes | 30 minutes |
| Tech factory (3 panels) | 10 minutes | Existing tech watcher, default 10 minutes | 15 minutes | 30 minutes |

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
