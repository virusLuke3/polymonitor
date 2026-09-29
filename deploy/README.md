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

When releasing these readers, restart `polydata-api.service`, `polydata-whale-trades-seed.service`, and `polydata-suspicious-trades-seed.service`. Verify both runtime signal endpoints and an active market workspace against canonical trade identities and timestamps, not HTTP status alone. Wallet-history migration is released separately after its index readiness check.

### Backend release acceptance

The quality and deploy jobs use the same tested Git commit. The backend release
backs up installed systemd units before changes; removing an owned unit stops
and disables it, and rollback restores its previous file and enabled/active
state. Acquisition services owned by market-data are excluded.

`python scripts/deploy/gcp_release.py verify --url http://127.0.0.1:18500`
checks dependency health, current recent trades, and fresh Whale Tracker / Flow
Watch payloads. HTTP 200 with a stale, warming or failed signal is rejected.
This acceptance gate does not assert complete historical coverage or prove
unknown outcome labels. Inspect those upstream contracts separately.

Runtime-panel GETs are read-only with respect to Telegram delivery. Notification
publishing remains owned by the background publishing processes.
