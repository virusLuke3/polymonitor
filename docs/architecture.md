# polyData Architecture

Polymonitor consumes Polymarket market, trade and oracle data and serves
business panels through a Flask API and a Vite/Preact dashboard. Canonical
acquisition is owned by the separate `market-data` repository.

## Current Shape

```text
polymonitor/
  agent/        analysis and model integration
  scripts/      API, business services, DB readers, panel workers, operations
  webpage/      Vite/Preact dashboard
  telegram/     publishing and query consumers
  deploy/       systemd, journal and reverse-proxy configuration
  tests/        business, API and infrastructure contract tests
  data/         local runtime snapshots and delivery checkpoints (ignored)
  docs/         public documentation
```

```text
market-data acquisition -> PostgreSQL / ClickHouse
  -> Polymonitor readers and panel caches -> Flask API -> dashboard
```

`quant/`, the old standalone Quant entrypoints and their systemd jobs have
been retired. LOB consumes the separate market-data live-book API; the old
Quant snapshot endpoint returns HTTP 410. Archive history belongs to market-data.
Weather reads canonical markets from the database. Consumer
Python imports do not depend on the removed `quant` package or a sibling
`market_data` installation. Upstream availability and freshness still require
runtime verification.
See [development](development.md) and [tests](../tests/README.md).

Production logs belong to journal, with capacity and retention configured in
`deploy/journald/`. Development logs are generated only on demand and are not
source directories. Runtime database snapshots and Telegram checkpoints are
application state, distinct from disposable logs and language/tool caches.

## Boundaries

- Keep raw Market, OrderFilled and Oracle acquisition in `market-data`.
- Keep business projections, panel caches and API presentation in Polymonitor.
- Keep valid consumer tests when repairing or removing a dependency.
- Keep private configuration and machine-specific notes out of public source.
- Validate startup and deployment separately from syntax and unit tests.

Application composition lives in `api/bindings.py`, HTTP construction in
`api/app.py`, and resource ownership in `api/runtime.py`. `RuntimeResources`
keeps each instance's health cache, refresh guards, provider caches and worker
pools together. `CacheState` owns Redis and local snapshot caches; workspace
services receive cache state and business callbacks instead of the full
application context. Shared persistent Redis/SQLite caches are intentionally
shared only when operators configure the same prefix/path.

Routes receive explicit domain dependency objects; the application no longer
retains a global `_bindings` service registry. Some business services still use
small mapping contexts, which must be replaced domain by domain without adding
another registry. ClickHouse connection settings, scan limits and admission
slots belong to the owning runtime and are fixed when settings are loaded.

Generic snapshots use SQLite as their expiry authority. A valid empty result
replaces old data; a failed refresh preserves the previous timestamp and marks
dictionary responses stale. GET routes do not publish Telegram messages.

`outcome_projection` validates existing source-label evidence without schema,
write or repair operations. The upstream canonical registry alone does not yet
persist sufficient source-label evidence to replace that read contract; unknown
labels remain unavailable. Never infer YES/NO from a token's source position.
