# Market panel read contract

The UI reads the existing market-data stores through the existing API. This path
has no collection, exchange fallback, schema migration, replay, or trading task.

| Panel | Store and bounded selection | Refresh / shared cache |
| --- | --- | --- |
| Catalog | PostgreSQL; 50 rows from at most 5,000 newest registry candidates, canonical identity and active lifecycle checks; indexed text search for other markets | browser 5 min / bounded server cache |
| Metadata | PostgreSQL market ID lookup; existing stored trade quote, with its source timestamp | 60 s / 60 s |
| Oracle | PostgreSQL exact identity indexes; newest 50 distinct events and stored lifecycle state | 20 s / 20 s |
| OrderFilled | ClickHouse canonical token and partition/block predicates; one fixed block window, newest 50 events | 10 s / 8 s |
| Chart | Same existing OrderFilled facts; at most 600 events in the requested time range and a bounded block window | 90 s / 90 s |
| LOB | Existing market-data snapshot reader; selected token pair only, no collection | 2 s / 2 s |

The catalog is a bounded page, not a complete global volume leaderboard. Sorting
applies within that page. Missing 24 h volume or counts are unknown. Market
observations deliberately omit changing prices/volumes; they cannot supply a
price chart. Chart coverage is partial and never represented as a complete time
series. No quote is duplicated to fabricate history. An empty trade window does
not prove an empty market history.

## Resource boundaries

- At most four PostgreSQL connections across API worker generations on one host.
  Each worker is capped to its share (two each for two workers), so idle
  connections in one worker cannot consume its sibling's entire allowance.
  Alpha display reads share this pool. Queue admission is at most 1 s; a cold TCP
  connection has a separate eight-second deadline. Connections have a recognizable
  application name, and every returned lease is rolled back.
- Panel SQL: two concurrent queries per host, eight queries/s maximum, read-only transactions, 1 s statement
  timeout, 100 ms lock timeout, 4 MiB work memory, no parallel query workers or JIT.
  Timeouts affect this reader only, never the shared database role globally.
- Panel ClickHouse reads: two concurrent requests per host, one request/s (burst two); one thread, 256 MiB memory, at
  most four queries (4 MiB watermark + 24 MiB indexed keys + 32 MiB facts + 4 MiB timestamps)
  and a six-second network/request budget. The SQL execution limit is 4 s per
  query, within that same total deadline: bounded cold reads of existing parts
  exceeded the former 2 s cap. Token keys are sought independently in primary-key
  order before their bounded top-N merge; fact reads retain explicit token/block
  predicates and the full canonical identity check.
  Admission may wait up to 1.25 s for an existing permit/rate token, within the
  same six-second deadline. This absorbs sibling panel bursts without raising
  throughput or issuing source queries while waiting.
  ClickHouse checks limits at granule/part boundaries, so 64 MiB is a query budget,
  not an absolute disk IO ceiling. Errors never become successful empty results.
- Cross-worker cache ownership uses the existing SQLite snapshot store's fixed
  64 lock stripes per pool, with at most eight pools. Market records, outcome
  evidence, flow and chart use separate pools 1–4; other callers retain pool 0.
  This prevents nested dependencies and sibling flow/chart keys from colliding
  with each other's locks. Worker exit releases locks. Redis availability does
  not govern admission. Two rebuilds maximum; duplicate record/evidence reads
  wait at most 1 s for the existing builder, while other cold reads return
  immediately when busy. Failures cool down for 15 s without replacing good data.
- The new namespace holds at most 512 payloads, each at most 1 MiB, plus 512 small
  cooldown markers. Stale reuse expires after 60 s for flow, 120 s for Oracle,
  and 300 s for catalog/chart/metadata. Unrelated snapshot namespaces are untouched.
- Source outcome evidence is cached for 30 s with no stale reuse. Public value
  projection still revalidates each response; cached capability assertions are
  not accepted as evidence. Repeated receipt JSON is deduplicated without
  changing any source fields.
- Browser requests are independent, single-flight, canceled on selection changes,
  paused while hidden, and use backoff plus Retry-After. Hovering unselected rows
  and bootstrap do not launch historical/global scans.

The production Nginx token-book route uses the existing dedicated market-data
reader on port 18861 directly, avoiding the main API worker queue. That reader
shares a 2 s cache, deduplicates same-pair requests, admits at most four snapshot
reads, retains at most 128 keys, and cools failed reads for 15 s. It reads the
committed gateway snapshot using a read-only SQLite identity lookup; this route
does not open PostgreSQL or ClickHouse connections. Nginx additionally limits
per-client book requests and concurrent connections. The market-ID and batch endpoints forward to this same reader; there is no
second book cache in the API.

## Health and release

`/health/live` tests only the API process. `/health` retains bounded cached
infrastructure probes. `/health/panels` reports the latest requested reads, not
coverage of all markets; it does no source queries. LOB status is reported with
each book response. Source timestamps, successful reads, and current connectivity
are separate facts.

Tests cover process-wide admission and crash release, duplicate cold misses,
failure cooldown, stale expiry, bounded cache retention, fixed trade windows,
read-only SQL cleanup, and browser polling cancellation/backoff. Production
acceptance additionally checks release SHA, actual source responses, and desktop
and mobile screenshots without substituting APIs or tiles. This change does not
start collectors, restart a host, or restore maintenance-stopped trading tasks.

All market HTTP routes, MCP tools, and market-linking consumers use
`market_service.py`. The retired market/group serving implementation, workspace
cache, exchange history fallback, bootstrap seed job and hover prefetch are
removed. Group and workspace URLs remain thin compositions of the same bounded
reads. Finance and other non-market seed jobs retain their existing ownership.


## Browser recovery through the shared Runtime

Catalog, metadata and history now use `usePanelResource` instead of private
polling loops. Public cache keys include sort/page/limit for catalog, market ID
for detail, and market ID/range/interval for history. Catalog uses a five-minute
check/freshness window and a fifteen-minute browser navigation retention limit;
stale/error labels remain visible and individual quote clocks are not renewed.
The server's five-minute fallback limit is unchanged. Metadata checks every minute with at most
five-minute retention; history checks every 90 seconds with five-minute retention.
Source and successful-check clocks survive reload unchanged. Cached catalog
quotes retain their own quote timestamps and existing validity checks.

Catalog/detail use the bounded shared localStorage backend; history uses the
same envelope/validation in IndexedDB (2,000,000 encoded-character entry cap).
Restoration precedes network admission, and background failures preserve only
unexpired data. API identity, shapes and timestamps are validated on both network
and storage reads. Market/range/sort changes cannot reuse another identity's
response. Detail excludes book, flow, Oracle and chart fields; those do not gain
freshness by being embedded in metadata. Selected OrderFilled and Oracle retain
their existing memory-only polling; LOB explicitly declares `cache: null`.
Search is an on-demand query, not another periodic collector. No account data is
persisted in these public snapshots. Runtime deadlines remain 6 s for detail and
10 s for catalog/history; source/SQL budgets above are unchanged.

Unit checks cover parameter identity, original retention and stripped live data;
browser checks cover selection/range cancellation and restore-before-request.
See [shared lifecycle](panel-runtime-lifecycle.md) for storage budgets and release
acceptance. Restored context alone is not live market-data acceptance.

A detail 404 while the catalog is empty preserves the selected ID and records
pending reconciliation. The next nonempty catalog selects its default market
or rechecks the same ID; it never strands selection at null. User selection,
explicit deselection and group focus cancel that pending reconciliation. Recovery
uses the shared Runtime's independent retry/resume policy, not another poller.
