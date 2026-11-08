# Research evidence

Production module: `research-evidence-watch`. Visual reference and original input scope: [reviewed design](../../../../design-previews/market-domains/panels/research-evidence/README.md). This implementation replaces prototype records with acquired public evidence. AI title search, DOI, publisher, publication date and indexed citations. Publication is not breakthrough validation, verified review quality, clinical trial success or regulator approval.

## Ownership and data path

This directory owns its body and local filters; imports only shared primitives. `scripts/api/services/culture_tech` is the shared acquisition/projection owner, source key `research`. Source endpoints and proxy routes come only from `.env` through `source_value()` and the existing `SourceSession`; API GET does not collect. The common `panel_evidence_store` owns bounded acquisition, SQLite source state, content revisions and failure recovery. No per-panel worker or business cache is introduced.

Formal raw/normalized evidence uses `POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH`; snapshots reuse `POLYDATA_SNAPSHOT_SQLITE_PATH`, namespace `source:external-panels:v1`, source-specific keys from `SPECS`. A source revision is SHA-256 of actual acquired bytes and preserves first/last received times. Source publication/event times stay in rows, separate from successful acquisition and API read time. API `GET /runtime/external/research-evidence-watch` projects a bounded read of the same store. The browser uses shared `externalPanel`, resource `external:research-evidence-watch:v1`, schema 1, explicit public persistence (200,000 characters) and the existing Runtime cancellation/retry/visibility controls.

Runtime configuration variables: `POLYMONITOR_RESEARCH_WORKS_URL`, `POLYMONITOR_SOURCE_ROUTES_JSON`, `POLYDATA_SNAPSHOT_SQLITE_PATH`, `POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH`. Only private `.env`/service injection supplies values; `.env.example` contains placeholders.

## Cadence and recovery

Acquisition: 6 hours; acquisition stale after 24 hours; visible browser check: 30 minutes. Providers publish at their own cadence. Retained source values are limited by `SourceSpec` (normally seven days; BFI fourteen days; social one day). Unknown source timestamps stay unknown. Every failure preserves the original last successful clock; true empty data differs from unconfigured/failed acquisition. Browser persistence cannot extend the server's source retention. Missing fields stay absent/null, never zero. Long publication periods do not imply a live-tick feed.

One shared serialized culture/tech lane, source GETs at most two full attempts, 45 seconds per attempt, source transport cooldown/Retry-After and source cadence. Each source is bounded to 8 MiB (linked BFI and speech downloads 2 MiB); current projections at most 100 objects and 512 KiB. The whole batch budget and speech/BFI bounded subjobs are declared in the owner; no round overlaps. Formal SQLite writes must succeed before reporting source success.

## Visual and behavior

Blue publication-stage paper blocks with journal/date/DOI hierarchy; recent/cited sorting. The shared Frame keeps the existing Panel shell, mono numbers, token colors, 12px body and 10px metadata. The module preserves five-column defaults and existing persisted dimensions. Controls operate on the acquired projection; they do not start new source requests. Source failures and scope restrictions stay visible. Full methodological limits and source clocks are expandable.

Attribution: Crossref public DOI metadata. There is no claim that all original design fields or market-settlement bindings are available. Data content is metadata/factual observations, not copied article bodies except US government written remarks.

## Verification

Semantic coverage: `tests/test_culture_tech.py` validates score/rank separation, currency minor units, unknown auction results, social privacy filters, BFI units, failed-source retention and invalid values. Actual acquisition and production screenshot evidence is recorded by the release owner; source HTTP success alone does not prove full-market or long-term coverage. Default discovery is integrated by the existing registry/default reconciler, preserving prior explicit hides.
