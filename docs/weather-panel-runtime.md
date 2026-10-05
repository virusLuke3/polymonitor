# Weather workbench runtime

The existing panel directories, Preact registry and public panel runtime remain the owners of rendering and scheduling. This change covers the temperature monitor, city snapshot, market browser, quote table, quote curve, hourly forecast and seven-day forecast.

## Collection and freshness

- The permanent weather watcher owns collection. Ordinary API reads use Redis, SQLite, or a retained seed; they never launch another provider collector.
- The watcher schedules from the start of a cycle (180 seconds by default). Storage TTL is at least two cycles. Expired snapshot timestamps still cause STALE even when a retained value remains cached.
- `generatedAt` measures snapshot assembly, `forecastFetchedAt` measures model acquisition, `weatherUpdatedAt` measures the provider's current-model sample, `observationUpdatedAt` measures the METAR observation, and `marketFetchedAt` measures catalog reading. Request time does not replace a missing source timestamp.
- Open-Meteo native local timestamps are converted with the city/provider IANA timezone. Dates in daily forecasts and market contracts remain local calendar dates.
- Missing forecasts may be retained with their original acquisition time and carry-forward fields. A newly assembled snapshot does not turn retained data into a new forecast.

## Market and quote ownership

- `marketDate` comes from the normalized market group. `forecastDate`, market-day high/low and the hourly graph select that exact date. An unavailable target date produces a missing forecast rather than substituting another day or a seven-day maximum.
- The collector reads one representative book per city with at most four concurrent read-only consumers. Secondary catalog groups explicitly retain `not-queried` bins.
- The selected-city table and curve share one parameterized resource, keyed by the complete sorted YES token set. The existing runtime checks every 15 seconds; it provides single flight, visibility suspension, request deadlines, cancellation and manual refresh. There is no additional component timer or persistent promise cache.
- Live prices require continuity, a current heartbeat, an unexpired source deadline and valid uncrossed prices. Failed or stale ladders are cleared. Saved reference prices are identified as previous book prices and never plotted as live mid prices.
- Weather health and book health are separate. City coverage exposes total, queried, quoted and two-sided denominators. Some open contracts legitimately have empty or unavailable books; these are not repaired by synthesizing prices.

## Display semantics

- Hourly Forecast uses hourly model temperature and a three-point moving mean.
- Seven-day Forecast uses daily high and the high/low midpoint. That midpoint is not a daily average.
- Neither chart claims Weather Underground station observations. The nonfunctional quote-history control is removed until a real history source exists.
- Market catalog rows display their own date and book coverage. Missing catalog bins are not fabricated around a forecast temperature.

## Acceptance

Run the weather, geo-sanctions and transport backend tests, weather contract unit tests, weather browser refresh/recovery test and production build. Deploy only owned files from the pushed commit, then verify the real production desktop/mobile UI, successive snapshot times and autonomous quote checks without API substitution.
