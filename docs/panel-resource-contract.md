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
  including the 100-item request limit, revalidation and 96 entries bound this
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

## External-source routing and recovery

An existing acquisition owner may opt into `api.clients.source_transport` through
`POLYMONITOR_SOURCE_ROUTES_FILE`. Reuse its existing scheduler, validation,
SQLite/Redis namespace and API; routing is transport configuration, not another
collector or data cache. Pure views continue reading the original owner.

All source addresses, credentials, proxy nodes and route choices must be
maintained in `.env`, per the [configuration contract](panel-data-pipeline.md#31-密钥数据源和代理统一由-env-配置).
`POLYMONITOR_SOURCE_ROUTES_FILE` describes an existing compatibility path: its
contents must be generated from `.env`, not maintained as another list of real
hosts and proxy URLs. Configuring only this file's path in `.env` does not meet
the requirement. The examples below describe structure and behavior, not values
to embed in scripts; existing consumers still require migration and verification.

- Configure exact hostnames and approved exits. Public GET/HEAD requests use
  this routing. The only POST exception is the documented read-only
  `https://api.hyperliquid.xyz/info` with exactly `{"type":"metaAndAssetCtxs"}`.
  Local APIs, Polymarket/LOB, account reads and trading writes are excluded.
  The weather snapshot owner explicitly opts into the exact configured public
  `/books` POST with a validated token-only batch; this does not enable other
  Polymarket requests or change internal LOB routing. See [weather ownership](weather-panel-runtime.md).
- Keep independent restricted SSH keys and systemd services. Do not reuse LOB
  keys, weaken their `permitopen` rules, or change the user's main Clash route.
  See the [unit](../deploy/systemd/polymonitor-source-egress@.service),
  [environment example](../deploy/systemd/polymonitor-source-egress@.env.example)
  and [host route example](../deploy/systemd/polymonitor-source-routes.example.json).
- A read tries at most two eligible exits. The connection/read timeout belongs
  to each complete attempt and is not divided between exits. An explicit owner
  deadline caps total work; no request starts after it expires. Two consecutive
  connection failures cool that host/exit for 120 seconds. Read timeouts do not
  cool the host for unrelated collectors. A complete successful body resets the
  failure count (streaming headers alone do not). Retry-After from 429 applies to the source without an immediate
  alternate-exit retry; 403 does not trigger a bypass. Preserve domain-specific
  failure limits. State reuses `panel_snapshots / state:source-transport`; it
  contains cooldown clocks, not market data. Streaming body handling remains
  bounded by the consumer's existing byte/time limits.
- SSH keepalive/restart recovers broken tunnels. Acceptance also requires a real
  source request, valid business fields, a formal write and an API consumer;
  an active SSH unit or HTTP 200 alone is insufficient.
- Keep collection, publication, cache expiry, source observation and browser
  refresh clocks separate. Do not speed up acquisition to mask an outage.
  Partial index/equity refreshes may retain failed identities for 30 minutes from
  their original fetchedAt, mark them STALE, and exclude them from current
  breadth calculations. Successful siblings never renew that clock.

TV adds browser media-progress validation and same-channel fallback; its source
maintenance and playback budgets are in the [TV module contract](../webpage/src/panels/modules/market-tv-wire/README.md).
Dated recovery notes are evidence for their observation window, not deployment
defaults or proof that every source remains healthy.

Crypto history/options explicitly opt into `read_with_retry` via the existing
HTTP client. This collector profile retains a 45-second per-attempt I/O timeout,
at most four attempts and one exit switch, including failures while reading the
body. It does not alter the default request policy for other owners. Source
denials and Retry-After remain authoritative. The worker stops starting reads
or retries after its 90-second slow-task allowance; an outstanding I/O still has its
own timeout. Durable last-good data and retry clocks use the existing crypto
SQLite owner, as specified in [the domain contract](crypto-strategy-panels.md#历史与期权请求恢复).


### External collector failure isolation (2026-11-04)

- Crypto keeps one existing SQLite owner. Fast quotes/flow/depth publish on the
  30-second loop with their own 30-second allowance. Three persistent slow workers
  handle four asset-history jobs and two options jobs; each key has at most one
  queued/running job, a 90-second allowance, and its original source cadence.
- Funding uses two venue slots, 45 seconds per venue and at most 12 seconds per
  request attempt. In-flight work keeps its slot across cycles; timeout is not
  cancellation. A valid cached catalog survives a quote deadline failure.
- Finance/Tech/API recovery share the same durable acquisition lock and canonical
  snapshot size. View limits do not reduce the shared stored universe. If the
  scheduled owner has attempted within two declared intervals, API recovery does
  not compete with it, even when that attempt failed. Recovery remains available
  for absent/overdue owners.
- Tech, Finance, Finance External and commodity overview watchers own persistent Yahoo pools of
  three threads, with one reusable HTTP Session per thread. Batches join before
  the next panel/round. Tech/Finance panels have 180-second budgets; the larger
  Fear & Greed input set has 420 seconds within its unchanged ten-minute schedule.
  Finance External gives each of six independent source branches 90 seconds.
  Yahoo transient failure backoff is per symbol; only 429/Retry-After is source-wide.
  Daily history retains 260 observations for 200-day calculations (intraday: 48).
- Last-good retention belongs to each source/identity, with original observed and
  fetched times. Stablecoin spot retention is five minutes; finance/tech/DeFi
  quote retention is thirty minutes. A refreshed envelope cannot renew old rows.
- SQLite remains authoritative. The modified external watchers bound Redis connect
  and socket waits to two seconds. Optional mirror failure must not erase a
  successful SQLite publication or fabricate an upstream success timestamp.
- Valid empty results (ended events, no news) differ from missing price fields or
  exceptions. Coverage must report expected, received and missing identities.

- OFAC uses the official compressed SDN export (8 MiB compressed / 64 MiB
  expanded cap; 90-second body deadline), with the consolidated XML kept separate.
  Parsed values reuse `source:world:ofac / <original URL>` in the existing SQLite
  store: hourly refresh, at most 24 hours retained with original source clocks.
- News keeps its approved-host, redirect, conditional-request and 2.5 MB limits.
  Its existing source worker uses the shared transport with a 45-second source
  deadline (connect up to 12 seconds, read up to 18); the 90-second process budget
  remains. Per-source schedules and Retry-After still control subsequent attempts.
- NWS scheduled acquisition has 20 seconds, including a 6-second connection cap.
  Browser source waits remain 6.5 seconds; its future continues in the existing
  bounded owner pool and publishes to the same SQLite snapshot. Provider refresh
  cadence, geometry, observation timestamps and stale limits are unchanged.
- Prefer verified direct access where available. GRID has a collector-specific
  `POLYDATA_GRID_ESPORTS_TRUST_ENV_PROXY` override; disabling it does not change
  other services or the user's Clash. SSH destinations must be actually reachable
  through the approved key: a working SOCKS listener alone is insufficient.

Current implementation and acceptance: [external-source recovery](external-panel-recovery-2026-11-04.md).
