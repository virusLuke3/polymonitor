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

## Adopted families

| Family | Browser checks | Collector cadence | Fresh seed | Maximum retained seed |
| --- | --- | --- | --- | --- |
| Crypto | 5 seconds | Existing market group watcher, default 60 seconds | 3 minutes | 15 minutes |
| Finance factory (11 panels) | 5 minutes | Existing finance watcher, default 10 minutes | 15 minutes | 30 minutes |
| Tech factory (3 panels) | 5 minutes | Existing tech watcher, default 10 minutes | 15 minutes | 30 minutes |

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
that every one of the 72 panels is healthy or fully migrated.
