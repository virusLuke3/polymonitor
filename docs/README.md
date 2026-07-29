# polyData Public Docs

This directory contains public-facing engineering documentation for polyData.

Private notes, credentials, deployment journals, and non-public research should stay in `document/`, which is intentionally ignored by Git.

## Documents

- `architecture.md` - current architecture and target boundaries.
- `development.md` - local development, build, and verification commands.
- `worldmonitor-polymonitor-comparison.md` - WorldMonitor/Polymonitor product, data, architecture, and engineering comparison.
- `polymonitor-platform-upgrade-roadmap.md` - staged platform upgrade roadmap that preserves Polymarket specialization.
- `market-workspace.md` - evidence contract and source boundaries for shareable market dossiers.
- `layout-sync-briefings.md` - revisioned workspace synchronization and canonical public briefing boundaries.
- `operations-workspace.md` - read-only application health and freshness workspace.
- `data-quality-workspace.md` - Oracle lifecycle, data-quality contract and gap semantics.
- `pwa-i18n.md` - install/update behavior, offline shell boundary, locale contracts, and completeness gate.
- `mcp-distribution.md` - read-only prediction-market MCP tools, authentication, and privacy boundary.
- `updates.md` - daily public progress log and reusable update template.
- `../deploy/README.md` - deployment templates for local `systemd` runtime and remote frontend hosting.

## Documentation Rules

- Keep docs free of secrets, private infrastructure details, and local-only credentials.
- Prefer stable architecture and workflow information over one-off notes.
- When implementation boundaries change, update the relevant public doc in the same change.
