# Breaking Event Radar data contract

The existing `scripts/runtime/breaking_event_radar_watcher.py` owns collection.
It writes the existing `snapshot:evidence:breaking-event-radar` / `panel-v1` seed through
the shared Redis store; `/runtime/evidence/breaking-event-radar` reads it.
The shared Panel runtime owns browser persistence, scheduling and recovery.
Opening or refreshing this Panel must not collect external news.

## Sources, clocks and bounds

- Source priority is the existing public-content snapshot, then news RSS, then
  GDELT only if neither has usable reports. The owner still rotates one of five
  topics per 300-second round (at least 25 minutes for a complete rotation).
  Changing the backup source does not slow healthy public/RSS collection.
- First reuse the existing public-content owner's
  `snapshot:content:free-public` / `candidates-v4` seed. This is a local read,
  with no extra collector or request-time database query. Require owner age
  at most 300 seconds, current public-display permission, healthy source state,
  matching topic terms, and publication within the last 24 hours. This is
  bounded source coverage, not a complete global news feed.
- Wikimedia is daily attention, not breaking news. Query completed UTC days;
  persist valid nonempty daily observations in `source:breaking-pageviews`,
  keyed by SHA-256 of the date-specific URL, for 6 hours, at most 32 entries.
  Cached reads preserve acquisition time and the provider's observation day.
  Invalid, empty or failed responses do not replace a successful observation.
  Requests identify `PolymonitorBot` and its real website as required by the
  [Wikimedia User-Agent policy](https://foundation.wikimedia.org/wiki/Policy:Wikimedia_Foundation_User-Agent_Policy).
- If the shared public-content snapshot has no usable reports,
  the same watcher reads the configured Google News RSS search endpoint
  (`POLYDATA_GOOGLE_NEWS_RSS_URL`). Reuse the existing RSS metadata parser and
  source transport; no article-body crawler or additional worker is introduced.
  One plain topic query follows the existing topic rotation, with a 20-second
  total deadline and 1 MiB body cap. Keep only dated reports from the past day,
  at most 20, with HTTP(S) evidence links. Publication time and RSS acquisition
  time remain separate. Its success never clears GDELT's persisted cooldown or
  source failure; the API remains seed-only and the browser contract is unchanged.
- GDELT searches a bounded 24-hour window with at most 20 reports by default.
  `POLYDATA_BREAKING_EVENT_GDELT_POLL_SECONDS` defaults to 3600 seconds, with a
  one-hour floor across all topics; success, empty, malformed and failed reads
  all consume an attempt. Persist admission before HTTP so restart/timeout
  does not immediately retry. A 429 retains exponential backoff up to six hours
  and honors a longer `Retry-After`; pre-existing cooldowns are never shortened.
  The existing `state:content` / `gdelt-backoff` record remains private SQLite
  scheduling state, while public seeds stay in Redis. The existing Redis owner
  lease prevents overlapping scheduled collectors. No new source/worker or
  proxy rotation is introduced. Public state includes actual `lastAttemptAt`,
  `lastSuccessAt` and `nextAttemptAt` when known; a skipped read does not invent
  a new 429 or advance provider clocks. The last real failure stays visible,
  including when an alternate source provides usable news.
- Item `eventTime` is the report publication/seen time or Wikipedia observation
  day; `acquiredAt` is the actual successful source read. A newer daily reading
  cannot renew an older headline. Failed rounds preserve original times and
  expose errors. Rotated retained topics are marked `evidenceFreshness=preserved`
  and excluded once their acquisition age exceeds 24 hours.
- `generatedAt` follows acquired evidence; `lastAttemptAt` follows attempts.
  The 15-minute, 1-hour and 24-hour counters count only acquired reports whose
  source timestamps fall inside each window. They are sample counts. Empty
  datasets render no fabricated activity bars.
- Wikipedia-only rows identify Wikimedia and link the statistics endpoint;
  they do not masquerade as GDELT headlines. The frontend displays original
  event time. Partial source failures remain visible even when another source
  succeeds. Private endpoint/routing settings stay in the deployment `.env`.

## Verification

`tests/test_live_evidence_panels.py` covers persisted daily observations,
publication versus acquisition times, current permission and owner-age filters,
real time-window counts, market matching and failed refreshes. Production
acceptance additionally requires source response evidence and successive normal
worker rounds. HTTP 200, retained rows and browser cache alone are insufficient.

### Production check: 2026-11-11 (Asia/Shanghai)

Backend commit `aa459370802e397156e9e4a8bdbc3ff0c1758dd6` was installed from a
clean archive; the two installed modules match that commit. API workers were
gracefully reloaded and the existing radar collector restarted. No frontend
code or layout changed (frontend release remains `d712ea50bf6bad623cb2ee7999f50ebe30e09428`).
The private environment now explicitly sets the GDELT fallback interval to
3600 seconds. All 137 scoped backend tests passed from the clean archive.

- The startup round at 15:27 reused 20 matching public-feed reports for weather.
- Two subsequent ordinary five-minute rounds acquired 20 RSS reports each for
  Iran (15:32) and US politics (15:37). Source acquisition clocks advanced;
  the Iran headline also changed to a more recently published report.
- The real production browser automatically received the 15:32 snapshot after
  displaying the previous one. Reload and desktop/mobile display were verified
  with real APIs; the final public API returned the 15:37 snapshot.
- GDELT's pre-existing 17-failure record and 20:30:42 cooldown were unchanged
  throughout all three rounds. No new GDELT request was needed. Its source
  status remains rate-limited and the panel remains degraded; these checks
  establish alternate-source updates, not recovery of GDELT itself or complete
  news coverage. The remaining two topics were not observed in a full new
  five-topic rotation during this window.

Task evidence is retained in the `gdelt-source-priority` artifact directory:
`deployment.json`, `automatic-rounds.json`, `public-final.json`, `browser.json`,
`tests.log` and desktop/mobile screenshots. This dated check is not a permanent
health claim or a deployment configuration.
