# External Panels: production data contracts

This feature index covers the 35 formerly preview-only designs now registered as real modules. The five-column shell, existing order/sizes and explicit hides are retained. The shared default-panel reconciliation adds newly introduced IDs to both local and account layouts. No special workspace, URL, activation button, reset or cache clearing is required.

Each module has its own `webpage/src/panels/modules/<id>/` UI and README. The original preview fixtures are never imported. Shared mechanics live in `panels/shared/external`; domain models, validation and parsers remain with their domain. Existing WorldMonitor screenshots and approved design previews guided distinct typography, category colors and body compositions; the public shell is unchanged.

## Ownership and usable scope

| Owner | New views | Actual acquisition and coverage |
| --- | --- | --- |
| `geopolitics_expansion` | Conflict Evidence, Ceasefire Watch, Territorial Claims, Diplomacy Calendar, Treaty Tracker | Public FCDO Search API statements; UN Treaty Collection Paris Agreement depositary; existing conflict owner for separately dated historical records |
| `sports_expansion.snapshot_service` | Spread Monitor, Total Monitor, Player Props, Tournament Path, Season Race, Awards Watch, Esports Map State, Esports Tournament Path | Existing NBA scoreboard identity plus ESPN game details, standings, leaders and ATP; OpenDota completed professional games and actual series identifiers |
| `finance_expansion` | Token Listings, Project Milestones, Chain Metrics, Fiscal & Tax, Merger Progress, Private Valuations | Coinbase products, configured repository releases, Aave TVL/fees, Treasury DTS/MTS, IRS, existing SEC transport and configured issuer filings, official financing announcements |
| `culture_tech` | AI Leaderboard, Art Auctions, Box Office, Awards Race, Music Charts, Product Releases, Public Figure Events, Reality Progress, Research Evidence, Social Window, Space Missions, Mentions Evidence | Arena dataset, Christie's calendar, BFI UK GBP reports, Golden Globes announcements, Apple Music US chart, Steam, Fed speeches, Survivor schedule, Crossref, configured Bluesky profile, Launch Library 2, acquired official written remarks |
| `weather_expansion` | Precipitation, Drought Monitor, Extreme Weather, Storm Advisories | Existing weather forecast and NWS/NHC owners; only USDM adds a new acquisition source |

A populated view is not complete coverage of every proposed strategy field. FCDO publications do not verify territorial control, treaty signatures do not prove current participation after withdrawal, and ceasefire keywords do not establish legal stages. Those distinctions and all six geopolitical evidence fields remain explicit. Treaty register entries and official current-party counts have different denominators. USDM region identities are never mixed in week comparisons; cumulative categories are converted to exclusive areas only after validation.

Sports covers current NBA/ATP and completed Dota2 records; there is no manufactured CS2/LoL real-time feed, full championship bracket, award vote or bookmaker line history. Product catalogs do not establish initial listing dates, releases do not establish mainnet execution, and SEC form types do not prove closing. Historical financing dates/rounds remain visible. Culture coverage is the named country, organization or account, not an implied global feed. Weather forecasts are not gauge observations; NHC advisories are not landfall confirmation. See each domain's service README and module README for remaining fields.

## Acquisition, persistence, recovery and environment

All source URLs, catalogs, contact identification, keys and proxy routes are personal `.env` configuration, with empty placeholders in `.env.example`. Runtime scripts supply no production source/proxy default. The existing `POLYMONITOR_SOURCE_ROUTES_JSON` selects authorized exits; no changes to main Clash, LOB, or stopped PolySignal. SEC reuses the existing disclosure transport and authorized User-Agent.

Scheduled `runtime.external_panels_watcher --owner <family>` runs one systemd instance per family. A five-minute wakeup checks persisted per-source due times; it does not fetch all sources every five minutes. A source gets two complete bounded 45-second attempts through existing routing, response byte limits, backoff and shared per-source lock. A lock collision defers work rather than clearing data. Family work budgets stop slow sources from unbounded acquisition. HTTP 429 honors Retry-After; 401/403 waits the source cadence. Failures store a redacted error type and original last-success clock.

- Normalized source state: the existing formal SnapshotStore, namespace `source:external-panels:v1`, source-specific key. Views read this owner; GET never fetches upstream or renews clocks.
- Raw evidence: `POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH`, or a sibling `external-panel-evidence.sqlite3` beside the existing store. SQLite WAL, SHA-256 revisions, compressed original response and normalized projection, original first reception and latest same-version reception. Same raw revision may rebuild its normalized projection after parser corrections. Capacity limit 2 GiB requires review; no silent deletion or unlimited growth.
- A successful state is published only after raw evidence and normalized state are durably written. Failed acquisition preserves last-good data only up to declared retention. Healthy empty results replace old rows. A source check or API read never refreshes its acquisition timestamp.
- Common budgets: response usually 8 MiB, explicit larger Aave bound; normalized source 2 MiB; projected Panel 512 KiB; browser entry 200,000 encoded characters under the shared resource cache's global budget. Public persistence uses the existing Runtime; each complete key is `external:<panel-id>:v1`.
- Three weather views and historical conflict records reuse existing snapshot namespaces and clocks. They do not copy data into another collector or renew original forecast/alert timestamps. Alerts are filtered for cancellation/expiry before display.

## Independent clocks

| Source family | Acquisition | Stale / maximum retention | Browser check |
| --- | --- | --- | --- |
| FCDO statements | 1 h | 3 h / 7 d | 10 min |
| UN treaty / USDM | 24 h | 3 d / 14 d | 1 h |
| Existing precipitation forecast | existing owner, 1 h target | 2 h / 6 h; each city clock checked | 10 min |
| Existing NWS / NHC | existing owner cadence | 10 / 15 min; 30 / 60 min respectively | 5 / 10 min |
| NBA detail / Dota records | source-specific 5–15 min | see `sports_expansion` SourceSpecs; snapshots retain source dates | 10 min |
| Sports standings / leaders / ATP | source-specific 15 min–6 h | see SourceSpecs and module resource declarations | 10 min |
| Coinbase / releases / protocol metrics | 5 / 30 / 30–60 min | source-specific 15 min–3 h; bounded retention | 10 min |
| Fiscal / tax / capital documents | source-specific 1–24 h | source-specific 3 h–3 d; bounded retention | 10 min–1 h |
| Arena, chart, auction, awards, TV schedule, BFI, research | 6 h | 24 h / 7 d (BFI 14 d) | 10 min–1 h |
| Launches, social profile, Fed speech index | 1 h | 3 h / 7 d (social 1 d) | 10 min |
| Acquired written speeches | 24 h | 48 h / 7 d | shared Mentions projection |

Exact source clocks and retention limits are exposed in `sources`; source publication/event time is a separate field. Collector attempt, successful acquisition, original observation, projection and browser check are not interchangeable. A market price or forecast may expire sooner than a historical document. No stale value is changed to zero.

## Verification and release

Preflight covers schema/identity/unit boundaries, future dates, empty vs failed, retry retention, expiry, durable publication, shared lock contention and default-layout reconciliation. Real source acquisitions in the formal store must be checked separately from parser fixtures. Production acceptance requires the pushed release identity, ordinary homepage with a pre-existing layout, all 35 new IDs, actual API data, desktop/mobile screenshots, no substituted API/map data, preserved sizes/order and explicit later hides.

Initial real acquisition is not overnight or full-cycle stability. Six-hour/daily source cycles require later observation. API availability and source completeness remain separate from Panel visibility. Production evidence for this release is recorded with its actual commit and timestamp after deployment.
