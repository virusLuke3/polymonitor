# Weather workbench runtime

The existing panel directories, Preact registry and public panel runtime remain the owners of rendering and scheduling. This change covers the temperature monitor, city snapshot, market browser, quote table, quote curve, hourly forecast and seven-day forecast.

## Collection and freshness

- The permanent weather watcher owns collection. Ordinary API reads prefer the authoritative SQLite business snapshot (including an explicitly stale retained seed); Redis is only a fallback mirror when SQLite has no snapshot. Reads never launch another provider collector or copy an older mirror over SQLite.
- Business publication uses `runtime.seed_meta.publish_snapshot`: SQLite rejection or a write exception stops publication before any success metadata or Telegram notification. Redis is optional at startup and publication; a missing or failed mirror does not discard an accepted SQLite snapshot. Provider caches and quota state remain separate from this business-publication receipt. First failures retain a null success clock.
- The watcher schedules from the start of a cycle (3600 seconds by default). Storage TTL is at least two cycles (7200 seconds). The browser checks saved snapshots every 60 seconds; selected-city official books use separate 30-second checks. Expired snapshot timestamps still cause STALE even when a retained value remains cached.
- All Open-Meteo callers (global cities, map point forecasts/geocoding and World Cup intel) reserve quota in the existing SQLite snapshot store under an atomic transaction. Forecasts use their weighted cost; geocoding counts as one call. The default app budget is 6000 weighted calls per UTC day, capped at 9000; storage failure blocks provider acquisition. Current global demand is approximately 2160 calls/day (50 cities, 18 variables, 24 cycles). This bounds Polymonitor callers, not unrelated consumers of the same public IP.
- A provider daily-limit 429 blocks that API group until the next UTC day (or a later Retry-After). Other 429s keep a shared cooldown. Forecast and geocoding cooldowns are independent while their budget is shared. Retained data keeps its original timestamps. Deployments or process restarts do not reset the persisted daily counter.
- `generatedAt` measures snapshot assembly, `forecastFetchedAt` measures model acquisition, `weatherUpdatedAt` measures the provider's current-model sample, `observationUpdatedAt` measures the METAR observation, and `marketFetchedAt` measures catalog reading. Request time does not replace a missing source timestamp.
- Open-Meteo native local timestamps are converted with the city/provider IANA timezone. Dates in daily forecasts and market contracts remain local calendar dates.
- Missing forecasts may be retained with their original acquisition time and carry-forward fields. A newly assembled snapshot does not turn retained data into a new forecast.
- A failed market database read retains the last known nonexpired contracts independently of fresh weather, with the original catalog clock and explicit retained status. Saved ladders are cleared, contract eligibility becomes unknown, and the selected-city quote resource reads current books independently. A successful empty catalog is not treated as an outage and does not resurrect removed contracts.

## Market and quote ownership

- `marketDate` comes from the normalized market group. `forecastDate`, market-day high/low and the hourly graph select that exact date. An unavailable target date produces a missing forecast rather than substituting another day or a seven-day maximum.
- Weather quotes use the official public CLOB `POST /books`, independently of the internal LOB reader. This is the user's explicit weather-display exception to the usual market-data ownership rule: full LOB capture, journals and history stay with market-data. No trading/account requests or LOB routes are changed.
- `weather_market_watcher` owns one shared weather catalog and quote acquisition loop, independently of the hourly forecast worker. The catalog reuses the existing market database/parser every 300 seconds with `query_books=False`; database reading time is not the upstream market synchronizer's success time. Closed/resolved contracts are removed, dates use city timezones, valid empty catalogs replace old ones, and failed catalogs retain original clocks for at most 900 seconds. Expired local dates are filtered even between collection cycles.
- Storage uses the configured existing `SnapshotStore`: `snapshot:weather:markets / catalog-v1` and `books-v1`, plus `state:weather:markets / demand:<cityId>` bounded to configured cities. Catalog and book state have separate attempt/success clocks. The single worker serializes publication; a cross-process owner lock prevents duplicate acquisition. SQLite must confirm writes before success is reported. These are current display snapshots, not historical LOB archives.
- A selected-city `/runtime/weather/books` read registers a 90-second bounded demand lease for validated catalog tokens and reads stored quotes only. It never performs HTTP acquisition. The worker refreshes demanded tokens every 30 seconds and other primary-city books every 300 seconds, prioritizing demand. Repeated viewers share the same tokens and worker; expired demand stops fast acquisition. Catalog changes and removed tokens invalidate old demand. Browser resources use the complete sorted token set, schema v4 and the existing shared Runtime at 30 seconds. The weather overview reads the joined catalog every 60 seconds without refreshing forecasts.
- Public `POLYDATA_CLOB_API_BASE` and `POLYMONITOR_SOURCE_ROUTES_JSON` come from `.env`; no credentials are needed. Weather alone opts into the common bounded source transport for the exact configured read-only `/books` POST. At most 100 tokens per request, two approved exits, a complete 12-second attempt, a 24-second request budget, a 90-second round budget, and a 2 MiB response cap. HTTP 429 obeys Retry-After; 403 never changes exits. No main Clash or LOB key configuration changes.
- Official quote identity, finite prices in [0,1], positive sizes, uncrossed spread and source milliseconds are validated before publication. Buy/ask levels are explicitly reduced by max/min without assuming upstream array order. Missing tokens/errors retain their own last good snapshot; a valid empty book clears it. One-sided books and zero prices remain valid; midpoint needs both sides.
- Official data is labeled **snapshot**, never continuous live. `eventAt` is the original provider timestamp; `observedAt` is successful acquisition, never an API read. Active quote freshness is 90 seconds (30-second cadence plus bounded I/O); background overview freshness is 600 seconds. Failures mark retained data explicitly and cannot advance either success clock. Retention is at most two hours from the original source event; expired/invalid/mismatched quotes have no prices. Independent expiry continues in the shared Runtime even if requests fail.
- Domain API composition overlays the newest catalog/books on the stored forecast without changing forecast/model/observation clocks. Weather table, curve, city snapshot, market browser and overview reuse this owner. Forecast dates are realigned to the selected contract after joining. Missing forecast dates remain unknown.
- Configuration names: `POLYMONITOR_WEATHER_CATALOG_INTERVAL_SECONDS` (300), `POLYMONITOR_WEATHER_CATALOG_MAX_AGE_SECONDS` (900), `POLYMONITOR_WEATHER_BOOK_INTERVAL_SECONDS` (30), `POLYMONITOR_WEATHER_BOOK_TIMEOUT_SECONDS` (12), `POLYMONITOR_WEATHER_BOOK_ROUND_SECONDS` (90), plus the existing SQLite path, CLOB base and source routing. Private values are loaded through `runtime.environment`; examples contain placeholders only.
- Verification covers read-only API acquisition boundaries, demand expiry/sharing, catalog replacement and local-date rollover, token/price/time validation, valid empty and missing rows, outage/retention/recovery, storage rejection, 429 backoff and exact-commit production desktop/mobile. Dated observations below remain historical evidence, not current source-health claims.

## Display semantics

- Hourly Forecast uses hourly model temperature and a three-point moving mean.
- Seven-day Forecast uses daily high and the high/low midpoint. That midpoint is not a daily average.
- Neither chart claims Weather Underground station observations. The nonfunctional quote-history control is removed until a real history source exists.
- Market catalog rows display their own date and book coverage. Missing catalog bins are not fabricated around a forecast temperature.

## Independent news and transport sources

- Weather News keeps its existing `weather_news_watcher → weather_news_service → snapshot:weather:news / panel-v1 → /runtime/weather/news → shared Panel Runtime` chain. The owner retains its 300-second interval and configured query concurrency (default four). HTTP reads use the shared source session and existing host routes, with at most two attempts of up to 45 seconds, a 90-second request budget and a 2.5 MB body limit. All queries share a 240-second collection budget; a query with less than 45 seconds remaining does not start. No new route or collector is introduced.
- A valid RSS channel with no matching articles is a successful empty result and replaces old news. Invalid RSS and failed requests are source errors, recorded per query without credential-bearing URLs. A wholly failed refresh retains the previous articles and original `generatedAt`/success clock, marks them stale and records the latest attempt independently. First failure has no success timestamp. SQLite publication remains authoritative and Redis remains optional.
- The existing Transport owner uses `global_transport_shipping_watcher → global_transport_shipping_service → snapshot:transport:global-shipping / panel-v3 → /runtime/transport/global-shipping`, with its one-hour interval unchanged. OpenFlights/Transitland text reads use the same existing source routing and two-attempt/90-second request budget, a 12 MiB body limit, and a shared 240-second text-collection budget. Existing short OpenSky authentication/JSON budgets and map coordinates are unchanged. A failed build preserves the old snapshot clock, marks the payload/source-health stale, and does not present retained source statuses as a new successful refresh.
- AIS, OpenSky and ADSB sample health uses each source's original `sampledAt`, explicit error/stale flags and the shorter of its declared cache TTL and its own configured sampling interval (defaults: six hours, 900 seconds and 1800 seconds respectively). Reading a cache does not by itself mean the sample is overdue; a missing or future clock remains unknown. Nonempty source-error lists and partial results remain degraded, while an unused fallback remains skipped. Public source metadata includes the original sample clock and TTL. This freshness classification never resamples a provider or advances its clock and does not claim live positions between samples.

Targeted source-route/body-retry, schema/empty, first-failure, retained-clock, per-provider cadence and publication tests passed with the existing weather, transport, shared transport and seed-recovery suites (164 tests). Normal owner rounds after the 2026-11-06 reload wrote Transport at 15:28:38 UTC and Weather News at 15:30:39 UTC; both consumer APIs read those snapshots successfully. These observations establish that cycle's recovery, not continuous availability. AIS health was corrected by the next normal build at 15:36; the equivalent OpenSky/ADSB correction is installed and awaits the final owner reload/build. None of these classification changes modifies the original raw sample.

## Quote recovery verification — 2026-11-07

The consumer contract was checked against the local installed API and the real public homepage. A scan of all 627 selected quote tokens across 49 cities found 377 usable native snapshots, 162 source-gap retained books and 88 books older than the two-hour display limit. These are point-in-time counts, not continuing availability. New York and Dallas had 22 retained books, including 20 two-sided books; their source owner had not recovered at verification time. The local P/Q cohort 0330 journals recorded connection failures and recovery-budget waits; a separate route probe observed a P connection closure and a Q 45-second handshake timeout. No LOB route, key restriction, collector or capture journal was changed by this consumer repair.

The weather owner published `2026-11-07T10:46:36.215694Z` to its configured installed SQLite store under `snapshot:weather:global-map / panel-v1`; the API returned that same generation. The repository's old data directory is not this active store. Production desktop and mobile read real APIs, and the existing-layout reload kept the quote panel present. Observed selected-city request completions were about 15.4 seconds apart. Source timestamps stayed unchanged during the outage. Targeted checks passed: 51 weather/LOB backend tests, 88 related weather/transport/geo tests, 32 weather/resource unit tests, browser refresh/expiry/recovery checks and the clean release build. Whole-project quality remains blocked by an unrelated pre-existing personal-path check in the crypto strategy document.

## Acceptance

Run the weather, geo-sanctions and transport backend tests, weather contract unit tests, weather browser refresh/recovery test and production build. Deploy only owned files from the pushed commit, then verify the real production desktop/mobile UI, successive snapshot times and autonomous quote checks without API substitution.


## Independent official quote rollout — 2026-11-07

Commit `745b2415dd62895bc9383f7c926e0bd6d6054ad4` introduced the independent catalog and official REST quote owner. The frontend was built from a clean archive of the pushed commit and served on the public homepage. Existing weather panels use the same shared resource; their order and sizes were not changed.

After correcting the service's explicit private environment-file path at 11:35:44 UTC, automatic primary-city acquisitions at 11:35:51 and 11:41:03 UTC each validated and wrote 627 of 627 requested token books. Catalog generations at 11:36:02 and 11:41:04 UTC held 3,638 unique tokens across available dates/families. Catalog read attempts are scheduled 300 seconds apart; successful publication also includes database I/O time. While a browser viewed New York, successive 11-token acquisitions succeeded at 11:36:16, 11:36:47, 11:37:18, 11:37:49 and 11:38:19 UTC. After its demand lease expired, fast cycles requested zero tokens while five-minute overview acquisition continued. This evidence confirms scheduled acquisition and formal SQLite publication during this observation window, not an uninterrupted long-term guarantee or upstream market-database completeness.

Real public desktop (2518×1249) and mobile (390×844) screenshots show New York 11/11 current snapshot books. No API or map-tile substitution was used. Artifacts are `webpage/design-previews/market-domains/images/weather-official-snapshots-{desktop,mobile}-20261107.png`. Quote source timestamps remain separate from acquisition, catalog and forecast clocks; forecast collection stays hourly. The API's source-health summary is joined from the independent catalog/books as well, so the old hourly snapshot cannot incorrectly report the new quote source as empty.

Validation includes the clean-commit backend tests, 32 frontend weather/resource tests, two browser refresh/expiry/recovery tests and the clean frontend build. The additional independent-source-health regression passed with the weather tests (50 total). Whole-project `make quality` remains blocked by the unrelated pre-existing personal-path finding in `docs/crypto-strategy-panels.md`; it is not claimed as passed.


## Browser reload recovery

The existing `global-temperature-monitor` owner and its seven `dataSourceId`
views share one persistent public snapshot. The key includes the limit (60) and
schema version. The existing forecast/catalog/books API chain and all collection
cadences above are unchanged. Forecast display retention is 24 hours from its original
generation, with a two-hour fresh limit; city catalog selections expire after
15 minutes or their city-local date rollover independently. Revalidation removes
expired selections without changing forecast/catalog/source clocks. The existing
quote validators still apply their own source event/observation clocks. The
selected-token book resource explicitly stays memory-only.

The roughly 3 MB joined snapshot uses the shared IndexedDB backend with a
4,000,000 encoded-character entry cap, not a separate weather cache or poller.
Blocked storage falls through to network within 800 ms; stale restores keep the
original check and source clocks. Weather News and Transport use the same Runtime
persistence contract and their existing source stores described above. Unit and
browser checks exercise catalog expiry, shared ownership, large reload recovery
and independent live quote expiry; production source health is reported separately.

### Overnight display and complete-body read budget

The shared `weatherSnapshot(60)` retains public forecast context for 24 hours,
marks forecast age beyond two hours stale/carry-forward, and still removes old
catalog dates/selections using the original 15-minute catalog clock. Book quote
eligibility is unchanged. All seven dependent views reuse this one owner and its
IndexedDB key; there is no extra collector or view cache.

A saved payload can exceed 2.7 MB. Its same-origin read allows 35 seconds through
JSON completion inside a 60-second total Runtime budget including admission;
the former 12-second transport / 10-second owner combination could cancel a
valid body before it reached persistent storage. Concurrency and 60-second
browser checks remain unchanged. Production acceptance must prove full body,
parse, IndexedDB publication and cached reload, not just HTTP 200 headers.

### 浏览器混合快照恢复边界（2026-11-10）

市场目录更新不能延长旧预报：浏览器除整包展示期限外，按每个城市的 `forecastFetchedAt` 单独检查24小时恢复上限，超过后清除小时/日序列和预报派生值。2小时后仍标旧；当前METAR、市场目录和报价沿用自己的来源时钟。新整包夹带25小时前预报的回归需同时验证12小时旧预报可恢复，以及有效观测/合约不会被一并删除。全量链路见 [121 Panel核验](panel-cache-loading-audit-2026-11-10.md)。

### Independent source recovery state

The API join recomputes the catalog/books contribution when their existing owner publishes recovery between hourly forecast rounds. An earlier catalog/book failure no longer keeps an otherwise healthy weather snapshot degraded for the rest of the hour. Failed/partial model or observation sources and expired books remain degraded; a stale forecast stays stale. Original forecast and observation clocks never advance during the join. Regression coverage lives in `test_weather_market_snapshots.py`; current source completeness is measured separately for all configured cities, not inferred from this status correction.

### 天气新闻的采集与读取边界

天气新闻复用既有 `weather_news_watcher`，一轮预算 240 秒，单响应最多 2.5 MB，单次读取 45 秒、最多两次尝试；具体来源由私有 source routes 配置。API 默认只读正式 SQLite 快照，Redis 仅在本地缺失时回退；缺 seed 返回明确空/不可用，过期副本保留原生成时间。普通 GET 不再派生每个 API worker 的 RSS 采集线程，避免与正式拥有者重复抓取、绕过采集出口和覆盖发布。显式 `allow_live_build=True` 仅保留给独立开发调用，不用于默认生产路由。
