# GCP Deployment Contract

Polymonitor uses one repository with two runtime roles. It is not deployed as a
single all-in-one host.

## Runtime topology

- The local collector host runs `polydata-local-collector.target`. It owns
  market discovery, OrderFilled, oracle, derived-table, and quant price-source
  pipelines.
- The GCP serving host runs `polydata-gcp.target`. It owns the public API,
  Redis/SQLite-backed runtime seed workers, Telegram publishing, and selected
  serving-side quant/LOB workers.
- PostgreSQL and ClickHouse remain on the collector side and are exposed to the
  GCP API through bounded SSH tunnels.
- Nginx serves the frontend from `/var/www/polydata` and proxies `/wm-api/` to
  the API on `127.0.0.1:18500`.
- GCP backend source currently lives under `/opt/polyData`.

The systemd targets, rather than separate source trees, enforce the runtime
boundary.

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
2. builds a payload containing only changed backend/runtime files;
   systemd templates are limited to units owned by the target commit's
   `polydata-gcp.target`, so local collector units are never installed on GCP;
   source files are limited to the API, serving-side runtime workers, Telegram,
   GCP quant workers, required market lookup modules, and the GCP healthcheck;
   frontend, documentation and CI assets are recorded as externally owned,
   while any unclassified changed path fails the release with `ignored > 0`;
3. compares every destination file with both its expected old and new hashes;
4. blocks the entire release if any changed destination contains an unknown
   remote edit;
5. backs up every affected file before replacement;
6. installs changed user-systemd templates and restarts only the units named by
   the operator;
7. verifies `/health`, latest content, the Nginx API proxy, and restarted unit
   state;
8. rolls files back automatically if verification fails.

This process never runs `git reset`, never replaces the whole `/opt/polyData`
tree, and does not start collector services on GCP.

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
successful release advances the deployment state. The initial approvals retain
the live Quant error backoff, Telegram linking guard, runtime-panel publish-loop
guard, and GCP target split while allowing the reviewed repository versions to
replace their ad-hoc remote forms.

Choose restart units from the changed runtime ownership. Examples:

- API routes/services: `polydata-api.service`
- Telegram publishing: `polydata-telegram-publisher.service`
- a runtime watcher: that watcher's exact `polydata-*.service`
- a changed target or unit template: the exact changed unit plus any service
  whose process must reload it

After a successful release, verify representative Market, OrderFilled, Oracle,
LOB, Quant, and runtime-panel payloads in addition to the generic health probes.
