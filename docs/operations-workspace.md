# Operations Workspace

`/operations` is PolyMonitor's read-only operational view. It combines application health,
synchronization checkpoints and seed watcher metadata without exposing SSH, systemd control,
credentials or mutation endpoints to the browser.

## Data sources

- `/wm-api/system/health`: API, Redis, database type, LOB readiness, content mode and
  market/trade/oracle/price synchronization checkpoints.
- `/wm-api/system/seed-health`: watcher heartbeat, freshness, record count, source states,
  payload status and current error summary.
- Panel Runtime status: every dashboard panel receives a shared status marker from its
  existing runtime phase and v1 cache/freshness metadata.

The workspace refreshes every 30 seconds and keeps the last good observation visible if one
endpoint temporarily fails. Watcher status is application heartbeat evidence, not a claim that
the corresponding host-level systemd unit is active. Production service truth must still be
verified with `systemctl --user` during deployments.

## Design system boundary

Shared design tokens and status primitives live in:

- `webpage/src/styles/design-system.css`
- `webpage/src/components/design-system/StatusPrimitives.tsx`

The token layer defines the color, typography, spacing, radius, shadow, motion and semantic
status vocabulary. Product CSS continues to use its existing `--wm-*` names through aliases,
which lets panels migrate incrementally without visual drift or a large rewrite.

Semantic tones are limited to:

- positive: healthy, live and fresh
- warning: warming, aging, stale, degraded and suspended
- critical: error, missing, offline and unavailable
- info: loading and observed
- neutral: unknown or informational

World Cup panels remain hidden and are excluded from Operations watcher rows.
