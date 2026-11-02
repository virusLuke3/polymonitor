# Market panel read contract

The UI reads the existing market-data stores through the existing API. This path
has no collection, exchange fallback, schema migration, replay, or trading task.

| Panel | Store and bounded selection | Refresh / shared cache |
| --- | --- | --- |
| Catalog | PostgreSQL; 50 rows from at most 5,000 newest registry candidates, canonical identity and active lifecycle checks; indexed text search for other markets | 45 s / 45 s |
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
  Alpha display reads share this pool. Queue admission is 200 ms; a cold TCP
  connection has a separate eight-second deadline. Connections have a recognizable
  application name, and every returned lease is rolled back.
- Panel SQL: two concurrent queries per host, eight queries/s maximum, read-only transactions, 1 s statement
  timeout, 100 ms lock timeout, 4 MiB work memory, no parallel query workers or JIT.
  Timeouts affect this reader only, never the shared database role globally.
- Panel ClickHouse reads: two concurrent requests per host, one request/s (burst two); one thread, 256 MiB memory, at
  most three queries (4 MiB watermark + 56 MiB facts + 4 MiB timestamps) and a four-second request budget.
  ClickHouse checks limits at granule/part boundaries, so 64 MiB is a query budget,
  not an absolute disk IO ceiling. Errors never become successful empty results.
- Cross-worker cache ownership uses the existing SQLite snapshot store's fixed
  64 lock stripes. Worker exit releases locks. Redis availability does not govern
  admission. Two rebuilds maximum; same-key cold requests do not wait or duplicate
  work. Failures cool down for 15 s without replacing good data.
- The new namespace holds at most 512 payloads, each at most 1 MiB, plus 512 small
  cooldown markers. Stale reuse expires after 60 s for flow, 120 s for Oracle,
  and 300 s for catalog/chart/metadata. Unrelated snapshot namespaces are untouched.
- LOB reads share the same token-pair cache across browsers, with two concurrent
  upstream reads and eight reads/s (burst four). Book timestamps and continuity
  come from the existing reader; unavailable books are not reused as live.
- Source outcome evidence is cached for 30 s with no stale reuse. Public value
  projection still revalidates each response; cached capability assertions are
  not accepted as evidence. Repeated receipt JSON is deduplicated without
  changing any source fields.
- Browser requests are independent, single-flight, canceled on selection changes,
  paused while hidden, and use backoff plus Retry-After. Hovering unselected rows
  and bootstrap do not launch historical/global scans.

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
