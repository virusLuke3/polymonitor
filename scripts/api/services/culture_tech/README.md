# Culture and technology evidence owner

`collect(store)` is invoked by the shared external-panel watcher; `get_snapshot(store, panel_id, limit=100)` performs only local reads. Twelve independent Panel modules consume eleven acquired sources, with Federal Reserve remarks shared by the public-figure and mentions views. The common evidence store owns SQLite revision archival and bounded last-good retention; existing `SourceSession` owns `.env`-declared routing, complete-attempt timeouts, connection cooldown and Retry-After. No account data or credentials are published.

| Environment variable | Reviewed public source | Scope |
| --- | --- | --- |
| `POLYMONITOR_ARENA_ROWS_URL` | [Arena's published dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset) | Text/overall top-100 raw-score sample, CC BY 4.0; no style-control substitution |
| `POLYMONITOR_APPLE_MUSIC_CHART_URL` | [Apple feed generator](https://rss.marketingtools.apple.com/) | US most-played songs, source rank without play counts |
| `POLYMONITOR_SPACE_LAUNCHES_URL` | [Launch Library 2](https://thespacedevs.com/llapi) | Upcoming feed and source-reported status, no telemetry |
| `POLYMONITOR_RESEARCH_WORKS_URL` | [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) | Bounded journal metadata query; request end-date follows UTC today and invalid/future dates are rejected |
| `POLYMONITOR_STEAM_FEATURED_URL` | [Steam storefront](https://store.steampowered.com/) | US new-release and coming-soon listings, not inferred 1.0 dates |
| `POLYMONITOR_AUCTION_CALENDAR_URL` | [Christie's official calendar](https://www.christies.com/en/auction/auction-calendar) | Structured public Event records, no lot prices |
| `POLYMONITOR_REALITY_SCHEDULE_URL` | [TVmaze public API](https://www.tvmaze.com/api) | Configured Survivor season episodes; attribution CC BY-SA; third-party schedule only |
| `POLYMONITOR_MENTIONS_SPEECHES_URL` | [Federal Reserve speeches](https://www.federalreserve.gov/feeds/speeches.xml) | Official published remarks and up to three bounded written documents; government text, no audio proof |
| `POLYMONITOR_SOCIAL_PROFILE_FEED_URL` | [Bluesky public feed API](https://docs.bsky.app/docs/api/app-bsky-feed-get-author-feed) | Configured profile page; reposts and restricted anonymity labels excluded |
| `POLYMONITOR_BOX_OFFICE_INDEX_URL` | [BFI weekend statistics](https://www.bfi.org.uk/industry-data-insights/weekend-box-office-figures) | Automatically selects latest published OpenDocument spreadsheet |
| `POLYMONITOR_BOX_OFFICE_DOWNLOAD_ORIGIN` | [BFI official content host](https://core-cms.bfi.org.uk/) | Explicit allowlisted origin for response-discovered documents, not an arbitrary URL proxy |
| `POLYMONITOR_CULTURE_AWARDS_FEED_URL` | [Golden Globes official feed](https://goldenglobes.com/feed/) | Original announcement metadata; winner/nominee fields are not inferred from headlines |

All actual endpoint values, optional credentials and `POLYMONITOR_SOURCE_ROUTES_JSON` belong to the private `.env`; this table is reference documentation, not a default URL source. Root configuration uses the existing environment loader with explicit process values taking precedence. The normalizer never reads another `.env` or an undeclared system proxy. Linked BFI documents and speech pages must stay on their reviewed configured origins.

Storage: source state `panel_snapshots / source:external-panels:v1 / culture-tech:<source>`, raw and normalized revisions in the common `external-panel-evidence.sqlite3` (or explicit `POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH`). `POLYDATA_SNAPSHOT_SQLITE_PATH` passed by the production service identifies the formal snapshot store. A clean checkout's `.env` path is not assumed to be the running backend's path.

Cadence: hour for Steam, launch schedule, social activity and speech feed; six hours for charts, research, auction calendar, weekly BFI index, award announcements and TV schedules; acquired speech body once daily. Maximum retained ages: social one day, BFI fourteen days, other sources seven days. The UI keeps these limits and original row dates. Feed acquisition and body acquisition have independent source success clocks. Snapshot publication does not claim a new event, stream count or updated official result.

Budget: serialized family lane; ordinary source batch 330 seconds, research 90 seconds, BFI discovery/document 120 seconds, speech-body sublane 120 seconds and at most three documents. Each HTTP request has up to two complete 45-second attempts within its enclosing allowance; 8 MiB source and 2 MiB linked-document caps; ODS expands at most 4 MiB. API projects at most 100 rows/512 KiB; written paragraphs are capped at 120 / 50,000 characters per document. No browser action invokes these tasks. A running family job must retain the shared watcher's single-flight slot until completion. Oldest-attempt ordering prevents permanent starvation after budget exhaustion.

Actual acquisition check on 2026-11-08 reached every configured source and the three official speech texts. This is point-in-time evidence, not a guarantee of all-day source availability or full original design coverage. The view-level README files state precise public coverage and unavailable licensed/settlement fields. Tests: `tests/test_culture_tech.py`; final production deployment, desktop/mobile screenshots, default discovery and periodic execution are verified by the release owner.
