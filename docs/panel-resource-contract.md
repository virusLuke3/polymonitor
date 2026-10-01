# Parameterized panel resources

Related Intelligence (`related-news`, titled Global Updates in global scope) is
the first consumer. Other panels adopt this contract incrementally; their existing
runtime fetch paths remain in place.

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

The dashboard summary consumes the same global/7-day/20-item resource and selects
its first 12 items; it does not make another content request or promote an
unvalidated bootstrap preview into the complete resource.

## Response and recovery contract

- Identity, window and `generatedAt` are mandatory. Missing source time cannot
  acquire a new lifetime from a successful request. Future time tolerance is one
  minute; maximum browser recovery age is five minutes of original seed age.
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
- Acceptance and persistence are independent: a useful partial response may
  display without replacing a complete recovery snapshot. Invalid/stale data
  never becomes the new saved snapshot. This does not exempt displayed content
  from current permission, window and expiry rules.
- Persistence is only for reviewed public data. Schema version 3, complete keys,
  revalidation, eight entries and 256,000 characters per entry bound this cache.
  Storage failure does not fail a panel or remove other application storage.
- New entries wait for acceptance while the current page remains readable. If a
  finite page rolls over completely, show the newly verified page immediately,
  avoiding a blank area containing only a pending button. Absence from top-N is
  not labelled a withdrawal. Revisions, permission changes and expiry apply
  without reader confirmation. Pending count is explicit.

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

The existing collector executes in a spawned process with fresh service runtime
and connections. The parent retains the single worker/advisory lock. A 90-second
cycle budget terminates a blocked child, marks unfinished due sources as failed,
and preserves completed records/last-success evidence. Source HTTP/rights work
shares a 45-second budget; the process boundary also bounds blocked DNS or reads.
The parent publishes a validated seed before acquisition, every 30 seconds while
acquisition runs, and afterward. Watch sleeps 30–60 seconds. Failed publication
or acquisition is reported and does not permanently stop watch mode.

The indexed candidate query reads up to 2,048 raw records per publisher, using
explicit NULL ordering and stable ID ties. Permission, expiry, malformed data and
low-magnitude earthquake filters run before reserving 256 eligible candidate
slots per publisher. Raw and eligible denominators, both bounds and projection
drop reasons remain visible; hitting either bound is still explicitly partial. A high-frequency provider cannot consume another
publisher's quota; quota overflow is explicitly partial, never comprehensive
recall. Direct statistical relations require positive jurisdiction and matching
metric/reference period/basis; unknown jurisdiction is at most context.

Local SQLite is checked before optional Redis for a fresh seed, avoiding a Redis
outage delay on every warm request. Freshness is 90 seconds; bounded stale SQLite
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
balance, cross-country rejection, page rollover, partial cache promotion and real
blocked-process termination. Fixtures never enter production data.

Build from the exact pushed commit via `git archive`, preserving unrelated dirty
work. Deploy that backend/frontend revision, verify release identity, and inspect
real desktop/mobile UI across several checks/seed cycles without substituted APIs
or tiles. Report upstream partial/failure states separately from code readiness.
