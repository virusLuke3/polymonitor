# Development

This page documents stable public development commands for polyData.

## Reproducible Runtime

The repository pins:

- Python `3.10.12` in `.python-version`
- Node.js `20.19.1` in `.nvmrc`
- frontend dependencies in `webpage/package-lock.json`
- Python production dependencies in `scripts/requirements.lock.txt`
- Python test and quality dependencies in `scripts/requirements-dev.lock.txt`

With the pinned Python and Node versions active:

```bash
make bootstrap
make quality
```

`make bootstrap` creates `.venv`, installs the locked Python environment, and
runs `npm ci`. `make quality` performs the same repository contract, secret,
syntax, lint, test, systemd, and frontend build checks used by CI.
The frontend gate also rejects high or critical `npm audit` findings.

Regenerate the Python locks only under the pinned Python version:

```bash
.venv/bin/pip-compile --resolver backtracking --strip-extras \
  --output-file scripts/requirements.lock.txt scripts/requirements.txt
.venv/bin/pip-compile --resolver backtracking --strip-extras \
  --output-file scripts/requirements-dev.lock.txt scripts/requirements-dev.in
```

The first repository-wide pytest baseline exposed a small set of pre-existing
contract-drift failures. Their exact node IDs are visible in
`scripts/qa/pytest-quarantine.txt`. CI deselects only those IDs, reports the
count, and continues to block every new failure. Run the full unfiltered suite
with:

```bash
.venv/bin/python scripts/qa/run_pytest.py --include-quarantined
```

## Frontend

```bash
cd webpage
npm ci
npm run dev
npm run build
```

The Vite dev server defaults to port `3000`. API proxy requests use `/wm-api`
and target `VITE_POLYDATA_API_BASE_URL` when set, otherwise
`http://127.0.0.1:18500`.

Production frontend deployment is expected to publish `webpage/dist` from CI,
not build on the remote server.

## API

```bash
python scripts/api_server.py --help
python scripts/api_server.py --host 127.0.0.1 --port 18500
```

Health checks:

```bash
curl http://127.0.0.1:18500/health
curl http://127.0.0.1:18500/system/health
curl http://127.0.0.1:18500/bootstrap
```

## Local systemd runtime

Public systemd templates live in `deploy/systemd/`.

The same codebase is used on the local collector host and on GCP. Select the
role by target:

- `polydata-local-collector.target`: local market/orderfilled/oracle collectors.
- `polydata-gcp.target`: GCP API and seed-cache watchers.

Local collector commands:

```bash
make services-install
make services-start
make services-status
```

GCP manual target commands:

```bash
systemctl --user daemon-reload
systemctl --user enable --now polydata-gcp.target
systemctl --user status polydata-gcp.target polydata-api
journalctl --user-unit polydata-api -f
```

Shared runtime configuration is read from `~/.config/polydata/polydata.env`.
On shared servers, enable lingering so the services keep running after logout:

```bash
loginctl enable-linger "$USER"
```

## Convenience Commands

The root `Makefile` wraps existing commands without changing their behavior:

```bash
make web-build
make api
make dev
make status
```

`make dev` uses `scripts/start_dashboard.sh`, which starts the API only and
prints the frontend command to run separately.

## Refactor Safety Checklist

- Run `make quality` before publishing a branch.
- Keep `scripts/start_dashboard.sh` working as a local API helper until a better
  replacement is proven.
- Keep `scripts/api_server.py` working as the compatibility API entrypoint.
- Run `cd webpage && npm run build` after frontend or shared type changes.
- Avoid committing runtime data, logs, private docs, or generated dependency
  directories.
