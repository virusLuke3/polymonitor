# Tests

Maintained business, API, data-consumption, agent and Telegram tests live in
`tests/`. Shared import paths are configured once in `pyproject.toml`;
`conftest.py` isolates workstation dotenv and provider credentials.

```bash
make test
make test PYTHON=python3 PYTEST_ARGS='tests/test_api_http_client.py -k session'
```

The Makefile and CI call pytest directly. There is no custom runner or
permanent quarantine list: collection errors and failing cases fail the run.
`make test` suppresses bytecode writes and pytest's disk cache is disabled.
Use mocks and temporary storage; do not run collectors, access production
credentials or send real notifications from unit tests.

The NBA suite is colocated with its module:

```bash
make test PYTEST_ARGS='scripts/NBA/test_nba_pipeline.py'
```

Frontend map behavior is tested in the maintained Vitest and Playwright
suites. The old Python screenshot-size smoke test and the fixed-date SQLite
coverage script have been removed.

```bash
npm --prefix webpage run test:map
npm --prefix webpage run test:map:e2e
make clean
```

`make clean` removes generated test reports, screenshots/traces, build output
and source caches. It preserves dependencies, runtime databases, credentials
and application checkpoints. Run it after debugging, with development/test
servers stopped. Reports are local disposable output, not source assets.

LOB tests verify upstream token identity, continuity and freshness without
collecting or writing books. Weather tests use canonical database markets and
the injected LOB reader. Factory tests cover independent configuration/caches
and construction without startup jobs or database access. Regression cases also
cover different database targets in two apps, health-cache and HTTP-session
isolation, shutdown during connection acquisition, refresh capacity/deduplication,
and environment precedence/opt-out without import-time loading.

World Cup fixtures fix the schedule clock; tests must not depend on today's
date or workstation credentials. Optional NBA archive reader checks require
pyarrow and duckdb and report a skip when absent. Unit tests and a successful
build do not establish production freshness or coverage.
