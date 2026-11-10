# Breaking Event Radar data contract

The existing `scripts/runtime/breaking_event_radar_watcher.py` owns collection.
It writes the existing `snapshot:evidence:breaking-event-radar` / `panel-v1` seed through
SQLite and optional Redis; `/runtime/evidence/breaking-event-radar` reads it.
The shared Panel runtime owns browser persistence, scheduling and recovery.
Opening or refreshing this Panel must not collect external news.

## Sources, clocks and bounds

- GDELT searches a bounded 24-hour window, at most 20 records per topic by
  default. The production owner rotates one of five topics per 300-second
  round (25 minutes for a complete rotation). Its persisted rate-limit backoff
  and `Retry-After` remain authoritative; no route switching bypasses a 429.
- When GDELT has no usable reports, reuse the existing public-content owner's
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
