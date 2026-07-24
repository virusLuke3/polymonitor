# 002 - API Server Context Refactor

Status: active
Priority: P1

## Goal

Replace the large helper dictionary in `scripts/api_server.py` with an explicit service context object.

## Motivation

Route modules currently receive many dependencies through string keys. This makes call sites harder to understand and lets missing dependencies fail late.

## Target Direction

- Add a `ServiceContext` dataclass or equivalent typed object.
- Move API runtime configuration and shared runtime managers into that context.
- Keep `scripts/api_server.py` as a compatibility entrypoint.
- Update route factories to receive the explicit context.

## Current Progress

- API startup owns one shared `ServiceContext` with explicit settings,
  database, cache store, content provider, and LOB runtime dependencies.
- Route registration receives an immutable `RouteContext` linked to that
  service context.
- Legacy string-key consumers remain supported during incremental migration.
- Dependency entries are immutable; private runtime statistics are stored
  separately from configured dependencies.

Remaining work is to migrate route and service modules from compatibility
lookups to typed attributes, then remove the legacy helper wrapper.

## Verification

- `python scripts/api_server.py --help` still works.
- `/health`, `/system/health`, `/bootstrap`, market, content, runtime, and LOB routes still respond.
- Frontend dashboard loads against the API without payload changes.

## Non-Goals

- Do not change endpoint paths.
- Do not change response shapes.
- Do not migrate directories in the same change unless needed for imports.
