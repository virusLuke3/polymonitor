# Identity and Access Control

PolyMonitor keeps public market intelligence open while placing operational internals behind
an explicit product identity boundary.

## Access model

- Anonymous visitors can use the World monitor, Market Dossiers and Data Quality workspace.
- Users receive server-side sessions, can manage their own password, and own private watchlists,
  alert rules, in-app events, notification preferences and synchronized workspace layouts.
- Administrators can open `/operations`, inspect the audit trail and issue scoped API keys.
- API keys currently support only `operations:read`; every key has a per-minute rate limit and
  daily quota.

`/wm-api/health` remains public for deployment health checks. `/wm-api/system/health` and
`/wm-api/system/seed-health` require an administrator session or an administrator-owned API key
with `operations:read`.

## Security properties

- Passwords use salted scrypt hashes and are never encrypted or logged.
- Browser sessions use random opaque tokens. PostgreSQL stores only SHA-256 token hashes.
- The production cookie is `Secure`, `HttpOnly`, `SameSite=Lax` and uses the `__Host-` prefix.
- State-changing browser requests require a session-bound CSRF token in `X-CSRF-Token`.
- Raw API keys are returned once. PostgreSQL stores only their hashes and non-secret prefixes.
- Login attempts, session changes, password changes, API-key lifecycle events and product
  preference changes are audited.
  Client addresses and user agents are stored only as peppered hashes.
- Briefing creation and revocation require a session and CSRF. Public briefing links expose only
  server-generated canonical snapshots, expire after 30 days and can be revoked by their owner.
- Authentication is fail-closed at API startup when enabled but the schema or audit pepper is
  missing.

## Provisioning

Authentication is deliberately disabled by default. On PostgreSQL, apply the schema and create
the first administrator before enabling it:

```bash
PYTHONPATH=scripts python -m api.manage_auth migrate
printf '%s\n' "$BOOTSTRAP_PASSWORD" |
  PYTHONPATH=scripts python -m api.manage_auth upsert-user \
    --username admin \
    --role admin \
    --password-stdin
```

Then set:

```dotenv
POLYDATA_AUTH_ENABLED=1
POLYDATA_AUTH_COOKIE_NAME=__Host-polydata-session
POLYDATA_AUTH_COOKIE_SECURE=1
POLYDATA_AUTH_SESSION_TTL_SECONDS=43200
POLYDATA_AUTH_AUDIT_PEPPER=<at-least-32-random-characters>
```

The bootstrap administrator is forced to replace the initial password before protected data can
be opened. The bootstrap password and audit pepper belong only in the host's mode-600 environment
or credential store, never in Git, shell history, URLs or service logs.

## Operational boundary

This phase does not add public registration, OAuth, password-reset email or write controls for
systemd. `/operations` remains a read-only application control plane. Host truth and service
mutation remain outside the browser and are independently verified through `systemctl --user`
during deployment.
