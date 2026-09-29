# Deployment Templates

This directory contains public deployment templates and operational examples.

Private deployment notes, machine-specific commands, and secrets should stay in
`document/`.

## Included templates

- `systemd/` - local long-running service templates for the API and sync jobs
- `nginx/` - reverse proxy examples for serving the dashboard and proxying API traffic

## Current recommendation

For local production-style runtime on one machine, use the `deploy/systemd/`
templates and keep PostgreSQL and Redis managed outside this repo.

For remote frontend hosting, prefer CI-built `webpage/dist` deployment to a
static directory such as `/var/www/polydata` instead of cloning the repo and
building on the server.

The private step-by-step setup for the current machine lives in
`document/deploy.md`.

### Recent trade panels

Whale Tracker and Flow Watch read current ClickHouse facts over a wall-clock window; they do not require the wallet-history address index. Signal workers must receive the same `ApiSettings` used by their entrypoint. Successful empty results replace previous signals; failed refreshes preserve the original data timestamp and return `stale`. Market workspace flow freshness is reported separately from the response assembly time.

Signal GETs only read the canonical worker snapshot and apply the current outcome-semantics checks. Cold caches return `warming`; expired snapshots keep their original timestamp and return `stale`. Requests never build signals or create refresh threads. One worker per component/cache directory owns writes, including PolyBeats. Request limits slice the shared snapshot instead of creating new cache keys.

`POLYDATA_SIGNAL_WATCH_INTERVAL_SECONDS` defaults to 120 seconds (minimum 120). `POLYDATA_SIGNAL_RUNTIME_TTL_SECONDS` defaults to two intervals plus 60 seconds: 300 seconds at the default cadence. It must leave at least 60 seconds beyond an interval. API and workers share these settings; the separate seed TTL and MySQL-only signal timeout were removed. Slow runs do not trigger catch-up bursts.

When releasing these readers, restart the API and all four signal seed services (alpha, whales, suspicious, PolyBeats). Verify both runtime signal endpoints and an active market workspace against canonical trade identities and timestamps, not HTTP status alone. Wallet-history migration is released separately after its index readiness check.

Consumer PostgreSQL sessions default to a 5-second connection timeout, 15-second statement timeout, 3-second lock timeout, 30-second idle-transaction timeout and 20-second TCP user timeout. Configure `POLYDATA_POSTGRES_CONNECT_TIMEOUT` (seconds) and `POLYDATA_POSTGRES_{STATEMENT_TIMEOUT,LOCK_TIMEOUT,IDLE_IN_TRANSACTION_SESSION_TIMEOUT,TCP_USER_TIMEOUT}_MS` with positive values. These are per-session settings and do not alter market-data database roles or server defaults. Pool acquisition defaults to 5 seconds and no longer retries connections six times. Runtime shutdown has one `POLYDATA_SHUTDOWN_TIMEOUT_SECONDS` budget (20 seconds, capped below the 30-second Gunicorn grace period); queued tasks are cancelled and remaining work is reported without waiting indefinitely. Running calls still depend on their driver/provider timeouts; systemd retains the final process stop deadline.

### Backend release acceptance

The quality and deploy jobs use the same tested Git commit. The backend release
backs up installed systemd units before changes; removing an owned unit stops
and disables it, and rollback restores its previous file and enabled/active
state. Acquisition services owned by market-data are excluded.

Before replacing any backend file, the release validates the entire payload and saves all previous files plus a durable receipt. Apply failures and interrupts restore the saved files. The deployment shell arms rollback before apply. A hard-killed process can be recovered with `gcp_release.py rollback --root <deploy-path> --receipt <backup-root>/<target-sha>/receipt.json`; recovery is repeatable. Keep this single recovery copy until the release has been accepted. Dependency installation and database migrations are not reversed by file rollback.

`python scripts/deploy/gcp_release.py verify --url http://127.0.0.1:18500`
checks dependency health, current recent trades, and fresh Whale Tracker / Flow
Watch payloads. HTTP 200 with a stale, warming or failed signal is rejected.
This acceptance gate does not assert complete historical coverage or prove
unknown outcome labels. Inspect those upstream contracts separately.

Runtime-panel GETs are read-only with respect to Telegram delivery. Notification
publishing remains owned by the background publishing processes.
