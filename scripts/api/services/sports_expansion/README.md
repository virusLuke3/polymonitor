# Sports expansion ownership

Eight independent body modules use six shared source projections. They do not import the design-preview fixtures. API entry is `get_snapshot(store, panel_id, limit=100)`, collector entry is `collect(store, force=False)`; the common external worker schedules the collector. GET performs no HTTP, source writes, cache renewal or model inference.

| Source key in `source:external-panels:v1` | Consumers | Acquisition / fresh / retain |
| --- | --- | --- |
| `sports:nba-game-summary:v1` | Spread, Total, Player Props | 10 min / 30 min / 24 h |
| `sports:nba-standings:v1` | Season Race | 6 h / 18 h / 72 h |
| `sports:nba-leaders:v1` | Awards Watch | 6 h / 18 h / 72 h |
| `sports:atp-tournament:v1` | Tournament Path | 15 min / 45 min / 24 h |
| `sports:dota-pro-matches:v1` | Esports Tournament Path; map detail discovery | 15 min / 45 min / 24 h |
| `sports:dota-map:v1` | Esports Map State | 15 min / 45 min / 24 h |

NBA summary chooses one native event from the **existing NBA scoreboard owner**, live first then most recent completed, and validates the returned ID. The existing owner now retains its already-fetched quarter/player-leader facts; it does not acquire additional scoreboard copies. Detail covers actual players, minutes, per-period scores and recorded bookmaker references. Publication time can be absent, so neither acquisition time nor a stored handicap is presented as a verified current/executable quote. A retained game keeps its original ID/time even if a later game's request fails.

ATP data contains men's singles round names, actual opponents and set scores. Upcoming sets stay absent. Round facts are shown directly; no future edges are invented. OpenDota is a completed professional-game replay source. Latest 100 records, named teams only, yield native league/series identity. Ten-player detail includes actual kills, economy and bounded minute curves. Incomplete sampled series are not declared won/lost; championship bracket/advancement rules are absent. It is not a substitute for authorized CS2/LoL live feeds. [OpenDota API documentation](https://docs.opendota.com/) describes the public source.

NBA statistical leaders are current research inputs, not official award nominations or MVP probabilities. Complete qualifying minutes and medical/appeal exceptions are unavailable; no games-played shortcut certifies eligibility. Official NBA award pages were tried but returned HTTP errors in this acquisition environment, so no historical winner was fabricated or mislabeled as the current season.

## Storage, retries and budgets

All sources use `panel_evidence_store`: raw bytes plus normalized revisions archived in the configured evidence SQLite file; source state/last-good data in the injected SnapshotStore. Source raw revisions are SHA-deduplicated and preserve original acquisition times. They do not create eight stores or eight workers. The common store imposes 2 GiB evidence capacity; source bodies max 8 MiB, normalized source max 2 MiB and Panel response max 512 KiB. Frontend persistence is 200,000 chars per resource under the shared Runtime total budget.

Collection serializes sources, at most one network request active per domain, 45 s complete attempts (maximum two under one source deadline). Base sources have a 300 s round budget; two dependent details have separate bounded 95 s requests, so the domain maximum is 490 s. Per-source cadence, attempts, errors, Retry-After and failure backoff are persisted; restart does not clear them. Existing environment source routes handle bounded alternate egress. Failures preserve original data and clock, while successful empty data clears prior content. SQLite publication is checked; request success alone is not acceptance.

Browser checks every 10 minutes, Awards every 30 minutes, through the common resource Runtime. Hidden consumers pause and shared keys deduplicate. Freshness uses acquisition age per source; event time remains separately visible, and final matches are labeled final/replay even when recently checked.

## Configuration

Existing `POLYDATA_ESPN_NBA_BASE_URL` and the NBA owner remain unchanged. New actual values exist only in personal `.env`:

- `POLYDATA_SPORTS_ESPN_STANDINGS_URL`
- `POLYDATA_SPORTS_ESPN_LEADERS_URL`
- `POLYDATA_SPORTS_ESPN_SUMMARY_URL` with `{event_id}`
- `POLYDATA_SPORTS_ESPN_TENNIS_URL`
- `POLYDATA_ESPORTS_OPENDOTA_PRO_MATCHES_URL`
- `POLYDATA_ESPORTS_OPENDOTA_MATCH_URL` with `{match_id}`

No new key is required by these public endpoints. No hidden default URL or proxy appears in source. `POLYMONITOR_SOURCE_ROUTES_JSON` supplies authorized egress; no main Clash change or undeclared system proxy inheritance. Common environment loading gives explicit process configuration precedence. `.env.example` contains empty placeholders maintained by integration.

## Evidence and limitations

2026-11-08 actual installed-store collection produced eight usable projections: one NBA game with 24 player records, one bookmaker line and four periods per team; 30 NBA teams; 16 categories/160 statistical leader rows; Paris Masters 76 and Stockholm Open 39 matches; 76 named professional Dota records; one detailed ten-player game with 28 minute observations. OpenDota initially timed out, then a subsequent actual acquisition recovered; this is not a long-term stability claim.

`tests/test_sports_expansion.py` covers null/zero/DNP, handicap sign, provider ranks, unplayed sets, replay/sample boundaries, source identity, bad response rejection, read-only projection, expiry and failure retention. Existing NBA watcher and predictor tests also pass. Production routing/default discovery and real desktop/mobile acceptance belong to the parent release verification. No full live-game interval or six-hour source cycle has yet been observed by this implementation task.
