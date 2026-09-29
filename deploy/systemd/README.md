# polymonitor systemd templates

Market, OrderFilled and Oracle acquisition is owned by
`/path/to/market-data`. Install those collectors
only from that repository's `deploy/systemd/acquisition` directory. The former
polymonitor collector, history-repair, placeholder-remap and taxonomy units
have been removed.

This directory now contains polymonitor consumers and shared infrastructure:

- GCP/API and seed-cache services
- serving-table and panel refresh jobs
- Polygon RPC tunnel and health check
- LOB API consumer of market-data (`MARKET_DATA_LOB_URL`, default port 18610)

Do not add Market, OrderFilled or Oracle writers here. In particular, never
run a second OrderFilled writer beside `polydata-trade-sync.service`.

## Targets

- `polydata-gcp.target` starts the API and seed-cache consumers. It must not
  start chain collectors.
- `polydata.target` is the compatibility alias for the GCP target.
- `polydata-local-collector.target` is installed from `market-data`, not this
  directory.

## Environment

Units read the private `~/.config/polydata/polydata.env` where required. Keep
that file mode `0600`; never commit it. PostgreSQL readers use the existing
`core,oracle,ops,public` schemas, and OrderFilled readers use the existing
ClickHouse `poly_orderfilled` database.

The API reads existing market-data tables and the live book HTTP service;
it does not require installing the `market-data` Python package. Set
`MARKET_DATA_LOB_URL` to the engine accessible from this host (default
`http://127.0.0.1:18610`). The loopback default requires a co-located service or
an explicitly provisioned tunnel. Consumer installation does not provision
that upstream service.

Gunicorn uses `scripts.api.app:create_app(start_runtime=True)`: the factory
registers HTTP routes and explicitly starts cache warmers. Previously
installed `polydata-lob-*` and `polydata-worldcup-lob-guard.*` producer units
must be disabled/removed as part of rollout; their templates are retired here.

## PostgreSQL connection ownership

Install `polydata-postgres-gcp-tunnel.service` on the database host when GCP
reads the local canonical PostgreSQL instance. It forwards GCP loopback port
45434 to local port 45432. Set `POLYDATA_POSTGRES_GCP_SSH_TARGET` and, if needed,
`POLYDATA_POSTGRES_GCP_HOST_KEY_ALIAS` in the private environment or a unit drop-in.
The optional ports are `POLYDATA_CONSUMER_POSTGRES_REMOTE_PORT` and
`POLYDATA_CONSUMER_POSTGRES_LOCAL_PORT`. Set GCP consumers' `POLYDATA_POSTGRES_PORT`
to the dedicated remote port only after a database query through it succeeds.
The existing ClickHouse consumer tunnel remains separate.

Do not borrow a collector or paper-trading tunnel for the API. This unit never
kills listeners or reclaims another service's port: a collision fails startup.

## GCP/API install

Use `scripts/deploy/setup_remote_readonly_api.sh` from the same commit being
deployed. The helper installs the GCP target and explicitly disables collector
units on the serving host.

The API side is read-only with respect to raw Market, OrderFilled and Oracle
tables. Runtime panel caches are separate consumer outputs. Quant job templates and
standalone entrypoints and the old LOB writer/maintenance units have been retired.
Install `market-data-lob-live.service` from the market-data repository beside
its raw collector. Polymonitor reads this service; it does not write LOB data.

## Local acquisition install

Follow
`/path/to/market-data/docs/POLYMONITOR_MIGRATION.md`.
The intended local units are exactly:

- `polydata-market-sync.service`
- `polydata-trade-sync.service`
- `polydata-oracle-sync.service`
- `polydata-market-backfill.timer`
- `polydata-market-revisit.timer`
- `polydata-oracle-backfill.timer`

The Polygon tunnel remains infrastructure and may be shared by OrderFilled
and Oracle. Hosted RPC fallback is configured per collector;
endpoint secrets belong only in the private environment file.

## Safety checks

- Render all placeholder roots before installing a template.
- Run `systemd-analyze --user verify` before `daemon-reload`.
- Confirm the effective `WorkingDirectory`, `ExecStart` and `PYTHONPATH` with
  `systemctl --user cat`.
- Verify producer health from committed cursors and bounded storage receipts,
  not process liveness alone.
- Keep acquisition and serving roles separate. GCP/API services consume the
  shared databases; they do not start or repair collectors.

## Logs

Every repository service sets `StandardOutput=journal` and
`StandardError=journal`. Do not add file redirection, `tee`, or PID files to
production launchers. systemd tracks the service process directly.

`deploy/journald/60-polymonitor.conf` sets:

- persistent journal capacity: 1 GiB, leaving 1 GiB free on disk;
- volatile journal capacity: 128 MiB;
- maximum retention: 14 days;
- maximum journal-file age before rotation: 1 day.

Capacity can shorten the retained history; 14 days is a maximum, not a
minimum. Journal retention removes archived files, so expiry is governed by
file rotation rather than exact per-entry deletion time.

This is a **host-wide** journal policy, covering system and user services.
Install it explicitly on the production host:

```bash
make services-log-policy
systemd-analyze cat-config systemd/journald.conf
journalctl --disk-usage
make services-logs SERVICE=polydata-api.service
```

The GCP setup helper installs the same policy and restarts journald. A normal
backend code release does not apply this host configuration. Applying the
policy requires administrator privileges; editing this repository alone does
not change an already running production host. The cleanup change has not
been deployed to production.

Development uses terminal output. Optional local captures and their cleanup
are documented in [development](../../docs/development.md#logs-and-generated-files).
