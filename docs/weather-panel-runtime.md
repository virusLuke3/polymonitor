# Weather workbench runtime

The existing panel directories, Preact registry and public panel runtime remain the owners of rendering and scheduling. This change covers the temperature monitor, city snapshot, market browser, quote table, quote curve, hourly forecast and seven-day forecast.

## Collection and freshness

- The permanent weather watcher owns collection. Ordinary API reads use Redis, SQLite, or a retained seed; they never launch another provider collector.
- The watcher schedules from the start of a cycle (3600 seconds by default). Storage TTL is at least two cycles (7200 seconds). The browser checks saved snapshots every 60 seconds; selected-city live books retain their separate 15-second checks. Expired snapshot timestamps still cause STALE even when a retained value remains cached.
- All Open-Meteo callers (global cities, map point forecasts/geocoding and World Cup intel) reserve quota in the existing SQLite snapshot store under an atomic transaction. Forecasts use their weighted cost; geocoding counts as one call. The default app budget is 6000 weighted calls per UTC day, capped at 9000; storage failure blocks provider acquisition. Current global demand is approximately 2160 calls/day (50 cities, 18 variables, 24 cycles). This bounds Polymonitor callers, not unrelated consumers of the same public IP.
- A provider daily-limit 429 blocks that API group until the next UTC day (or a later Retry-After). Other 429s keep a shared cooldown. Forecast and geocoding cooldowns are independent while their budget is shared. Retained data keeps its original timestamps. Deployments or process restarts do not reset the persisted daily counter.
- `generatedAt` measures snapshot assembly, `forecastFetchedAt` measures model acquisition, `weatherUpdatedAt` measures the provider's current-model sample, `observationUpdatedAt` measures the METAR observation, and `marketFetchedAt` measures catalog reading. Request time does not replace a missing source timestamp.
- Open-Meteo native local timestamps are converted with the city/provider IANA timezone. Dates in daily forecasts and market contracts remain local calendar dates.
- Missing forecasts may be retained with their original acquisition time and carry-forward fields. A newly assembled snapshot does not turn retained data into a new forecast.
- A failed market database read retains the last known nonexpired contracts independently of fresh weather, with the original catalog clock and explicit retained status. Saved ladders are cleared, contract eligibility becomes unknown, and the selected-city quote resource reads current books independently. A successful empty catalog is not treated as an outage and does not resurrect removed contracts.

## Market and quote ownership

- `marketDate` comes from the normalized market group. `forecastDate`, market-day high/low and the hourly graph select that exact date. An unavailable target date produces a missing forecast rather than substituting another day or a seven-day maximum.
- The collector reads one representative book per city with at most four concurrent read-only consumers. Secondary catalog groups explicitly retain `not-queried` bins.
- The selected-city overview card, snapshot, table and curve share one parameterized resource, keyed by the complete sorted YES token set. The existing runtime checks every 15 seconds; it provides single flight, visibility suspension, request deadlines, cancellation and manual refresh. One bounded `/runtime/lob/books` read fetches up to 24 tokens with four backend readers, preventing one slow interval from discarding completed quotes. Each source read has a 3-second read deadline; the 22-second HTTP and 25-second resource deadlines cover the maximum batch while preventing overlapping polls. Other token readers retain their existing deadlines. There is no additional component timer or persistent promise cache.
- The existing market-data LOB owner writes its durable P/Q/G journals; the read-only HTTP projection and Polymonitor `/runtime/lob/books` consume those committed books. Weather adds no collector, provider fallback, storage or recovery process. Endpoint and route configuration remain private `.env` values.
- Continuous **live** prices still require continuity, a heartbeat no older than 20 seconds, an unexpired source deadline and valid uncrossed prices. A committed **snapshot** is separately usable when `upstreamReady=true` and its reader `observedAt` is within 30 seconds. Snapshot availability does not prove continuous live reception. `eventAt` remains the original source-event clock even if an unchanged book is read again; `observedAt` is only the reader-check clock.
- A source-gap book may be shown as **retained**, with amber styling and its original `eventAt`, for at most two hours after that event. The limit never advances on API reads, failed retries or new weather envelopes. Missing/future event times, invalid/crossed prices and token mismatches cannot create retained quotes. A current snapshot that expires becomes retained only within that original-event bound. Current coverage excludes retained books, and the curve draws them as a separate labeled series with missing intervals preserved.
- The table keeps one-sided books and valid zero prices. Midpoints require both sides. A failed request can preserve only a previously validated book within the same two-hour source-clock bound; it cannot retain an undated catalog price indefinitely or extend a success clock. A successful empty book clears the old quote. The shared resource continues to retry through its existing 15-second lifecycle, with no component timer.
- Weather health and book health are separate. City coverage exposes total, queried, quoted and two-sided denominators. Some open contracts legitimately have empty or unavailable books; these are not repaired by synthesizing prices.

## Display semantics

- Hourly Forecast uses hourly model temperature and a three-point moving mean.
- Seven-day Forecast uses daily high and the high/low midpoint. That midpoint is not a daily average.
- Neither chart claims Weather Underground station observations. The nonfunctional quote-history control is removed until a real history source exists.
- Market catalog rows display their own date and book coverage. Missing catalog bins are not fabricated around a forecast temperature.

## Quote recovery verification — 2026-11-07

The consumer contract was checked against the local installed API and the real public homepage. A scan of all 627 selected quote tokens across 49 cities found 377 usable native snapshots, 162 source-gap retained books and 88 books older than the two-hour display limit. These are point-in-time counts, not continuing availability. New York and Dallas had 22 retained books, including 20 two-sided books; their source owner had not recovered at verification time. The local P/Q cohort 0330 journals recorded connection failures and recovery-budget waits; a separate route probe observed a P connection closure and a Q 45-second handshake timeout. No LOB route, key restriction, collector or capture journal was changed by this consumer repair.

The weather owner published `2026-11-07T10:46:36.215694Z` to its configured installed SQLite store under `snapshot:weather:global-map / panel-v1`; the API returned that same generation. The repository's old data directory is not this active store. Production desktop and mobile read real APIs, and the existing-layout reload kept the quote panel present. Observed selected-city request completions were about 15.4 seconds apart. Source timestamps stayed unchanged during the outage. Targeted checks passed: 51 weather/LOB backend tests, 88 related weather/transport/geo tests, 32 weather/resource unit tests, browser refresh/expiry/recovery checks and the clean release build. Whole-project quality remains blocked by an unrelated pre-existing personal-path check in the crypto strategy document.

## Acceptance

Run the weather, geo-sanctions and transport backend tests, weather contract unit tests, weather browser refresh/recovery test and production build. Deploy only owned files from the pushed commit, then verify the real production desktop/mobile UI, successive snapshot times and autonomous quote checks without API substitution.
