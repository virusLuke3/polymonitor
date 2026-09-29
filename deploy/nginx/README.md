# Nginx Templates

This directory contains public Nginx templates for serving the built frontend
as static files and proxying `/wm-api` to the local Tailscale-backed API.

## Frontend release acceptance

Production TLS must advertise HTTP/2. On Nginx 1.24, retain the Certbot
certificate settings and use `listen 443 ssl http2;`. Validate with `nginx -t`
before reloading. With HTTP/1.1, slow API requests can occupy the browser's
connections and delay lazy map modules even while individual static downloads
are fast. Confirm the negotiated protocol in the browser, not only the config.

Build from the exact pushed commit and compare `release-sha` and artifact hashes
with the public server. Deploy assets before the entry HTML and service worker;
retain previous hashed assets and the old shell for active tabs and rollback.
A frontend-only release must preserve public documentation, private files and
backend services owned by other tasks.

Run `webpage/scripts/verify-live-map.mjs` from `webpage/` with
`POLYMONITOR_RELEASE_SHA` set to the full commit. Set
`POLYMONITOR_E2E_HARDWARE_WEBGL=1` when headless Chrome requires Vulkan to reach
real hardware. The verifier visits `https://polymonitor.club` with real APIs,
tiles and service workers, records negotiated protocols, and captures desktop,
mobile, language, event-detail, theme and reload screenshots. Source degradation
and failed API requests remain in the receipt; passing renderer checks does not
prove every provider is healthy.

## Included templates

- `polydata-static.conf.example`
- `polydata-lob-limits.conf.example`

## Server contract

The production frontend server is expected to:

- serve static files from `/var/www/polydata`
- use SPA fallback via `try_files ... /index.html`
- proxy `/wm-api/` to the local-machine API over Tailscale
- serve byte-range PMTiles and compact hazard feeds through bounded Nginx caches
- not build frontend code on the server

The checked-in template uses placeholders instead of private values:

- `__POLYDATA_SERVER_NAME__`
- `__POLYDATA_API_UPSTREAM__`

Example upstream value:

```text
http://<tailscale-ip>:18500
```

## Typical install flow

```bash
sudo mkdir -p /var/www/polydata
sudo install -d -o www-data -g www-data -m 750 /var/cache/nginx/polymonitor-pmtiles
sudo install -d -o www-data -g www-data -m 750 /var/cache/nginx/polymonitor-hazard-map
sudo cp deploy/nginx/polydata-lob-limits.conf.example /etc/nginx/conf.d/polydata-lob-limits.conf
sudo cp deploy/nginx/polydata-static.conf.example /etc/nginx/sites-available/polydata
sudo nano /etc/nginx/sites-available/polydata
sudo ln -sf /etc/nginx/sites-available/polydata /etc/nginx/sites-enabled/polydata
sudo nginx -t
sudo systemctl reload nginx
```

The frontend release must be built with
`VITE_PMTILES_URL=/map-tiles/planet.pmtiles`; otherwise it intentionally uses
the OpenFreeMap fallback and the Range cache is not exercised.

## Notes

- GCP only needs Nginx, Tailscale, OpenSSH, rsync, and the static site
  directory.
- The API continues to live on the local machine; this template does not
  change the `/wm-api` topology.
- The LOB connection zone must be installed in the Nginx `http` context before
  enabling the site. It limits only concurrent public LOB reads per client; it
  does not change LOB data, matching, storage, or runtime code.
