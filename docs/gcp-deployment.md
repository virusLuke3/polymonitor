# GCP Deployment Contract

Polymonitor deploys the consumer API and business workers. Canonical data
acquisition is installed separately from the `market-data` repository.

## Runtime topology

- The collector host runs the Market, OrderFilled, Oracle and live LOB services
  supplied by `market-data`.
- The GCP serving host runs `polydata-gcp.target`. It owns the public API,
  Redis/SQLite-backed business workers and Telegram publishing. LOB is consumed
  through `MARKET_DATA_LOB_URL`.
- PostgreSQL and ClickHouse remain on the collector side and are exposed to the
  GCP API through bounded SSH tunnels.
- Nginx serves the frontend from `/var/www/polydata` and proxies `/wm-api/` to
  the API on `127.0.0.1:18500`.
- GCP backend source currently lives under `/opt/polyData`.

When ClickHouse lives on XUE, the existing local XUE tunnel supplies port
18123. `polydata-clickhouse-gcp-tunnel.service` forwards that port to GCP
independently of the PostgreSQL tunnel; install this unit on the tunnel host.
Use `POLYDATA_CLICKHOUSE_GCP_SSH_TARGET` to select a private-network SSH target
without changing other tunnels. Set `POLYDATA_CLICKHOUSE_GCP_HOST_KEY_ALIAS`
to the existing trusted hostname when both addresses identify the same host.
The SSH server should enable `ClientAliveInterval 30` and
`ClientAliveCountMax 3` for the tunnel user so dead connections release their
forwarded ports. Validate changes with `sshd -t` before reloading SSH.

Only units reachable from `polydata-gcp.target` are installed by a backend
release. Shipping a shared Python module does not start its CLI or grant it
database write privileges.

## CI and deployment

`Repository Quality` is a pre-deployment gate. It runs on GitHub-hosted runners
and does not modify either runtime host.

After that gate succeeds on `main`, `Deploy Frontend Dist`:

1. checks out the exact tested commit;
2. builds the frontend with the pinned Node version;
3. uploads `webpage/dist` to a temporary directory on GCP;
4. promotes the files into `/var/www/polydata`;
5. validates and reloads Nginx;
6. verifies the public document root and `/wm-api/health`.

Backend deployment is deliberately manual while the existing GCP worktree has
live hotfixes. `Deploy GCP Backend` requires the `gcp-production` GitHub
environment and an explicit `DEPLOY_GCP` confirmation. It always checks out the
current `main`, reruns the backend quality contract, and defaults to a dry run.
Installing the locked Python environment is a separate opt-in input so a source
release cannot silently replace the live GCP environment.

The backend release:

1. reads the last deployed commit from
   `~/.local/state/polydata-deploy/current.json`, falling back to the GCP Git
   HEAD only for the first managed release;
2. builds a payload containing the complete consumer source packages from the
   target commit, including unchanged dependencies that an older release may
   have omitted, plus deletions of changed runtime files;
   systemd templates are limited to units owned by the target commit's
   `polydata-gcp.target`, so local collector units are never installed on GCP;
   API, workers, database readers, market identity, Oracle parsing, weather,
   F1/Jin10 helpers, Telegram, Agent, operations and runtime data files travel
   together; archive migration tools, raw ClickHouse writers, development
   tools, frontend, documentation and CI assets stay outside this release;
   any unclassified changed path still fails with `ignored > 0`;
3. compares every destination file with both its expected old and new hashes;
4. restores missing runtime files, but blocks the release if any included
   destination contains an unknown remote edit;
5. backs up every affected file before replacement;
6. installs changed user-systemd templates and restarts only the units named by
   the operator;
7. verifies `/health`, latest content, the Nginx API proxy, and restarted unit
   state;
8. rolls files back automatically if verification fails.

This process never runs `git reset`, never replaces the whole `/opt/polyData`
tree, and does not start collector services on GCP. Runtime databases, private
configuration and logs are not release payloads.

`scripts/db/trade_v2.py` is still a consumer dependency: it selects existing
trade tables and converts stored values/SQL projections for API responses.
It does not fetch data. Its MySQL migration helpers are used by archived
commands; removing the entire module would break API imports.

`tests/test_gcp_release.py` verifies missing-dependency repair, remote-edit
protection, deletion/rollback and startup from an isolated release directory.
The startup check blocks network access and does not validate live upstream
data, credentials or freshness.

## Required GitHub configuration

Repository or `gcp-production` environment secrets:

- `GCP_DEPLOY_HOST`
- `GCP_DEPLOY_PORT`
- `GCP_DEPLOY_USER`
- `GCP_DEPLOY_PATH` for the frontend, normally `/var/www/polydata`
- `GCP_DEPLOY_SSH_KEY`

The `gcp-production` environment should require approval for backend releases.

## First managed backend release

Before the first release, reconcile every GCP-only hotfix that overlaps the
target commit. The preflight will print only file names and redacted hashes and
will refuse to overwrite those paths.

One-time, reviewed GCP content can be recorded in
`deploy/gcp/accepted-remote-overrides.json`. The approvals are scoped to one
exact base commit and exact file SHA-256 values. They stop applying as soon as a
successful release advances the deployment state.

Choose restart units from the changed runtime ownership. Examples:

- API routes/services: `polydata-api.service`
- Telegram publishing: `polydata-telegram-publisher.service`
- a runtime watcher: that watcher's exact `polydata-*.service`
- a changed target or unit template: the exact changed unit plus any service
  whose process must reload it

After a successful release, verify representative Market, OrderFilled, Oracle,
LOB and runtime-panel payloads in addition to the generic health probes.
