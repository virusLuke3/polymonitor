# Parameterized panel resources

Related Intelligence (`related-news`, titled Global Updates in global scope) was
the first consumer. Crypto, Commodities, Alpha and trade watch use parameterized
resources. The Finance/Tech factories declare the same snapshot contract while
preserving the existing workspace runtime and batched transport.

## Ownership and dependency direction

The panel directory owns parameters, parsing, source semantics and reading state.
A `PanelResource<T>` declares the complete request key, fetch, parse,
source timestamp, age limit, refresh policy and optional persistence promotion.
The explicit panel registry still owns composition. No sibling implementation
imports are needed.

`PanelResourceProvider` mounts once at the application entry. It registers
consumer demand by resource key and adapts contracts to the existing
`usePanelRuntime` with `batch:false`. Same-key consumers share data, scheduling,
inflight requests, retries and cancellation. Releasing one consumer never cancels
another consumer's request. Releasing the last consumer removes its in-memory
request/status/data; opt-in public persistence remains bounded. There is no
second scheduler or collector. Declarations are stabilized by complete identity
and policy, so a fresh object literal does not cancel/re-register on each render.

Workspace slots provide panel identity and visibility. Their status badge uses
the actual resource owner. Parameterized panels retain their own loading/status
region so controls stay usable during a cold request. Offscreen demand pauses;
a still-active summary consumer may legitimately keep the same resource alive.
Page hiding suspends all automatic checks. Manual refresh is an explicit override.

The dashboard summary consumes the same global/7-day/100-item resource and selects
its first 12 items; it does not make another content request or promote an
unvalidated bootstrap preview into the complete resource.

## Response and recovery contract

- Identity, window and `generatedAt` are mandatory. Missing source time cannot
  acquire a new lifetime from a successful request. Future time tolerance is one
  minute. Fresh response acceptance is five minutes of original seed age.
  Related Intelligence opts into 30 minutes of bounded browser recovery with
  `staleAgeMs`; after five minutes it is explicitly STALE, with the original
  snapshot time retained. Other resources keep their existing age limit.
- Wrong market/scope/window rejects the whole response. Individual invalid cards
  are isolated, counted and surfaced as partial; an entirely malformed list is
  rejected. Card render boundaries protect valid siblings.
- `checkedAt` means validated request completion; `generatedAt` means candidate
  seed generation. Neither is article publication or revision time. Unchanged
  content still advances the successful check clock.
- HTTP 503 and legacy unavailable/empty HTTP 200 enter the error path. Healthy
  empty results stay distinct. Automatic retry observes Retry-After, bounded
  exponential backoff and jitter. Non-retryable HTTP/identity failures await a
  parameter change or manual retry. Persistent failure slows to five minutes.
- Fresh validated partial responses replace older complete snapshots: a temporary
  source failure must not freeze persistence while verified items keep changing.
  Invalid/stale data never becomes the new saved snapshot. This does not exempt displayed content
  from current permission, window and expiry rules.
- Persistence is only for reviewed public data. Schema version 4, complete keys
  including the 100-item request limit, revalidation and 32 entries bound this
  cache. This resource explicitly permits 512,000 characters per entry for the
  larger page; other resources retain their 256,000-character default.
  Storage failure does not fail a panel or remove other application storage.
  All panel caches together are capped at 2,000,000 encoded characters; older
  writes are evicted first, and unrelated preferences are never evicted.
- Every successful scheduled response becomes the displayed list immediately,
  including new entries, revisions and removals. There is no pending-reader state
  or acceptance button. Permission changes and expiry still apply immediately.
  Absence from a finite top-N page is not labelled a withdrawal.
- The panel requests up to 100 items, renders the first 30 cards, and offers
  Show more in batches of 30. Counts and category tabs describe the whole loaded
  response, while an explicit showing/loaded counter describes the rendered
  portion. An expanded list continues receiving automatic updates.


## Scope and coverage

First opening selects explicit Global Updates, including when a market is selected.
The user's subsequent Market/Global choice is saved separately from article cache.
Market responses remain strict and never silently acquire global articles. A known
sports/crypto market without any reviewed dedicated feed declares `marketCoverage`
unsupported, hides meaningless zero category tabs and offers an explicit Global
button. A healthy no-match result, missing dedicated coverage, bounded candidates,
source partial failure and runtime request failure have distinct status labels.
Underlying source states remain available even for an unsupported market; total
acquisition failure still returns unavailable rather than a healthy coverage gap.
The generic resource binding accepts a panel-owned status label; the runtime still
owns scheduling, failures, retries and cancellation.

## Candidate seed and acquisition

The existing content worker still owns the reviewed feeds (3–15 minute source
schedules) and reuses existing USGS/NWS map snapshots. Public GETs never acquire
external feeds or substitute global data for a market.

Global Voices rights replay reads prior metadata in batches of up to 400 article
IDs, preserving per-article rights checks while avoiding a remote DB round trip
per card and the connection deadline that it can exhaust.

The existing collector executes in a spawned process with fresh service runtime
and connections. The watch parent initializes the schema once before running
cycles; children skip repeated schema DDL, which otherwise acquires PostgreSQL
table locks concurrently with parent seed reads. Standalone collectors still
initialize the schema. The parent retains the single worker/advisory lock. Worker-only PostgreSQL
connection setup/lease acquisition has a 20-second bound and one connection,
inside the unchanged cycle budget; HTTP API connection policy is unchanged. A 90-second
cycle budget terminates a blocked child, marks unfinished due sources as failed,
and preserves completed records/last-success evidence. Source HTTP/rights work
shares a 45-second budget; the process boundary also bounds blocked DNS or reads.
The parent publishes a validated seed before acquisition, every 30 seconds while
acquisition runs, and afterward. Watch sleeps 30–60 seconds. Failed publication
or acquisition is reported and does not permanently stop watch mode.

The indexed candidate query reads up to 2,048 raw records per publisher, using
explicit NULL ordering and stable ID ties. Permission, expiry, malformed data and
low-magnitude earthquake filters run before reserving 512 eligible candidate
slots per publisher. Raw and eligible denominators, both bounds and projection
drop reasons remain visible; hitting either bound is still explicitly partial. A high-frequency provider cannot consume another
publisher's quota; quota overflow is explicitly partial, never comprehensive
recall. Direct statistical relations require positive jurisdiction and matching
metric/reference period/basis; unknown jurisdiction is at most context.

Local SQLite is checked before optional Redis for fresh and bounded stale seeds,
avoiding optional Redis delays throughout local recovery. Freshness is 90 seconds; bounded stale SQLite
recovery is 300 seconds. Cold reads use the existing database under a one-second
cross-process lock. Failed queries do not replace the previous seed; SQLite and
Redis writes are independent, and worker success requires a verified write.

The related-news seed is registered in unified seed health. `contentSync` checks
seed age/status rather than just table existence. Request, seed, source and
article freshness remain separate. Source `next_check_at` is a scheduling due
time; one collector cycle plus watch sleep (150 seconds) bounds the time allowed
to complete a due check before reporting overdue. Explicitly expired shared map
snapshots remain stale immediately and are retried next worker cycle using only
the existing local cache; external feed Retry-After/backoff stays intact; source failure or truncated candidates stay
visible even when seed publication succeeds.

## Verification and rollout

Run model/cache/runtime unit tests, free-content/worker-budget/seed-health tests,
Related Intelligence E2E and shared frontend lifecycle tests, then the frontend
build. Cases include two consumers/one request, visibility demand, Retry-After,
unknown timestamps, malformed item/source isolation, 2,001-candidate source
balance, cross-country rejection, automatic new-item insertion, large-page rendering, partial cache promotion and real
blocked-process termination. Fixtures never enter production data.

Build from the exact pushed commit via `git archive`, preserving unrelated dirty
work. Deploy that backend/frontend revision, verify release identity, and inspect
real desktop/mobile UI across several checks/seed cycles without substituted APIs
or tiles. Report upstream partial/failure states separately from code readiness.

## Local WorldMonitor comparison

The local WorldMonitor checkout schedules its news lane in `src/App.ts` using
`REFRESH_INTERVALS.feeds` (20 minutes in `src/config/variants/base.ts`).
`src/app/refresh-scheduler.ts` owns in-flight protection, a bounded lane lease,
backoff, page-hidden suspension and staggered catch-up after visibility returns.
`src/app/data-loader.ts` retains digest fallback and rejects superseded load
results; `src/components/NewsPanel.ts::renderNews` immediately renders a flat
list, with optional clustering afterward and windowed rendering for large
cluster lists. Newly fetched articles do not require reader acceptance.

Polymonitor retains its existing shared scheduler and bounded retries, with a
30-second seed check rather than copying WorldMonitor's 20-minute interval.
The important adoption is observable list insertion on successful checks;
advancing checkedAt or generatedAt alone does not prove this. Source acquisition
still follows each source's 3–15 minute schedule. Larger data pages use bounded
progressive rendering instead of adding a second scheduler or virtualization
system. High-frequency event publisher quotas scale from four at a 20-item
preview to twenty at a 100-item page, retaining publisher-balanced ordering.
