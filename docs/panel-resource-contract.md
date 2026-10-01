# Parameterized panel resources

Related Intelligence (`related-news`, titled Global Updates in global scope) is
the first consumer of `webpage/src/panels/usePanelResource.ts`. Other panels can
adopt this contract incrementally; this change does not migrate their fetch paths.

## Ownership and dependency direction

The panel directory owns request parameters, API parsing, source semantics and
reader behavior. Its memoized `PanelResource<T>` declares a key containing **all**
parameters, `fetch`, `parse`, `updatedAt`, refresh policy and a maximum snapshot age.
Key the resource-owning component by that identity. No panel imports a sibling's
implementation. App and the explicit registry retain composition ownership.

`usePanelResource` adapts this declaration to `usePanelRuntime` using `batch:false`.
The existing runtime owns scheduling, request deduplication, cancellation, bounded
retry and page visibility. It does not wait for other panels' batch endpoints.
`checkedAt` means the last successfully validated request completion;
`updatedAt` remains the actual source snapshot timestamp. Neither is article
publication time. A successful check with unchanged content still advances
`checkedAt`, without making the source snapshot newer.

## Recovery contract

- `parse` validates identity, shape and safe public content before display or cache.
  Unavailable empty responses throw, including legacy HTTP 200 envelopes; they
  enter the runtime error/retry path rather than becoming healthy empty lists.
- Optional browser persistence is **only for reviewed public data**, never private
  or user-specific resources. Cache schema versions invalidate old formats. Keys
  separate global/market and 7/30-day windows. Every hydration is revalidated.
- Persistence failures do not fail the request. At most eight cache entries of
  256,000 characters each are retained; other localStorage keys are untouched.
- A saved snapshot renders before the network completes, and is labelled as such.
  Failure retains valid data only within `maxAgeMs`; neither cache writes nor
  successful requests extend its original source timestamp. Expiry removes it
  even when the network remains unavailable. Future timestamps beyond one minute
  of clock tolerance are rejected. No timestamp means no persistent cache.
- New cards wait for reader acceptance. Revisions, withdrawals, source state and
  expired alerts update immediately. Resource changes cancel old requests and
  cannot transfer a previous market's data to the new identity.

## Related Intelligence data path and timings

The existing content worker acquires the allowlisted feeds according to their
own schedules (3–15 minutes). It refreshes the shared 30-day candidate seed after
each cycle, then sleeps up to 60 seconds. This is not a promise of acquisition
every exactly 60 seconds: work duration is additional.

API reads project the shared seed into the selected market/window and recheck
current public-display permission and alert expiry. Redis freshness and SQLite
freshness are 90 seconds; bounded SQLite fallback and browser recovery stop at
300 seconds of **seed age**. A warm global read needs no content database query.
Cold reads use the existing indexed database query, under a one-second ownership
lock. Lock contention fails instead of duplicating queries. A failed optional
cache filesystem can still serve a successful database result; SQLite and Redis
writes are independent. The worker reports seed success only when at least one
cache write succeeds (the existing Redis setter is verified by reading it back
if SQLite did not persist). Failed refreshes never overwrite the last good seed.

The browser checks every 30 seconds while the page is visible. The runtime retries
failures twice with its existing 1/2-second backoff, then continues the normal
30-second check schedule. Global requests have a 12-second deadline, market
requests eight seconds; cancellation covers response-body decoding as well.
Hidden pages pause and resume checks. Source degradation is distinct from
request failure: public content remains visible with individual source status.

Unavailable empty content returns HTTP 503, `Retry-After: 30` and
`Cache-Control: no-store`. Healthy empty matches return HTTP 200. Public content
reads do not initiate feed acquisition or substitute global data for a market.

## Verification

Run the resource-cache and related-news model unit tests, runtime-store unit tests,
`tests/test_free_content.py`, and `webpage/e2e/related-intelligence.spec.ts`, then
the frontend build. Local fixtures cover scope/window races, malformed payloads,
legacy failures, automatic recovery, unchanged-seed checks, saved-data recovery,
age limits and visibility. Production acceptance must use the exact pushed
commit, real APIs and real desktop/mobile browsers over several seed cycles.
Partial upstream sources must remain reported as partial.
