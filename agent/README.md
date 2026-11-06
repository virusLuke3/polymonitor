polyData server-side agents live here.

- `common/`: shared environment loading, OpenAI-compatible LLM calls, Tavily search, and JSON helpers.
- `market_insight/`: market-focused AI insight API; the current three dashboard panels use `market_wide/`.
- `market_wide/`: market-wide AI insight agent for market brief, special-market radar, and trend radar panels.
- `gateway/`: local Flask gateway for machines that can reach private AI endpoints; GCP can call it through a reverse SSH tunnel.

Agents read secrets from server-side `.env` files only. Frontend code calls the Flask API and never receives `API_KEY` or `TAVILY_API_KEY`.

## Market-wide panels and local Qwen

`price-implications` (AI Insights), `sample-chain-trades` (Special Radar), and
`oracle-timeline` (Trend Watch) are enabled by default in both registries.
The shared workspace reconciliation adds newly enabled defaults to existing
local/account layouts while preserving order, sizes and subsequent explicit hides.

The existing producer is `scripts/agent/seed_market_wide_insights.py`; it reads
bounded market-data evidence (80 markets, 60 groups, 24 trades/oracle events,
12 content items and cached flow signals). `agent/market_wide` owns analysis.
It uses the existing local Agent gateway and OpenAI-compatible Qwen3.5-9B service:

```dotenv
POLYDATA_AGENT_API_BASE=http://127.0.0.1:18003/v1
POLYDATA_AGENT_MODEL=qwen3.5-9b
POLYDATA_AGENT_API_KEY=EMPTY
POLYDATA_AGENT_RUNTIME=chat
```

These settings belong on the model host. Remote consumers use the existing
private gateway connection, never a public model port. Qwen requests disable
thinking so the bounded output budget produces dashboard JSON. Explicit provider
overrides remain supported; the shared client also serves single-market analysis
and optional PolySignal explanations.

The seed and serving API must share `POLYDATA_SNAPSHOT_SQLITE_PATH` and the same
Redis configuration. The persisted namespace is `agent:market-wide:snapshot`,
with keys `v1:overview`, `v1:special`, and `v1:trend`. Existing quant/history and
node-event records stay with that producer. No browser-side generation is added.

Historical price change is optional for these three panels. When `price24hAgo`
and `change24h` are absent, skip historical momentum analysis without reporting
missing-history warnings, requesting acquisition or discounting unrelated
supported findings. Supplied price history remains usable; volume alone cannot
establish a price move. This policy adds no source, storage, query or refresh
work. Existing source failure/staleness reporting and snapshot clocks remain
unchanged. `tests/test_market_wide_agent_graph.py` covers absent and supplied
history alongside the existing trade-source failure tests.

News evidence reuses the `related-news` owner's reviewed public-content reader:
`content-topic-refresh` writes `content_items` and the shared
`snapshot:content:free-public / candidates-v4` seed; `ServiceRuntime` injects
`content_service.get_latest_content_payload` into the Agent seed context. Each
lens reads at most 12 items from the global seven-day window. Model context keeps
at most six excerpts (four when the context-size budget requires trimming),
with their original publisher and publication time. No additional feed request,
collector, database pool or cache is introduced. The existing content owner
retains its source schedules, 90-second fresh seed and 300-second stale recovery;
AI generation and browser checks keep their independent clocks below. The
`contentItems` metric counts loaded input items, not complete news coverage or
the number of excerpts retained in every specialist prompt. Source failures and
candidate truncation remain limitations of the shared news feed.

Whale evidence reuses `signal_service.get_whale_trades_snapshot` through
`ServiceRuntime.agent_snapshot_context`, exactly as Whale Tracker does. The
signal owner controls the `snapshot:signals:whales / {"limit":14,"v":2}` identity,
300-second freshness and read-time outcome verification. The Agent consumes at
most ten items; it does not reconstruct a cache key, run the whale builder or
renew its generation clock. Stale/warming/error snapshots are excluded, while
their original status, generation time and available item count remain visible
in `sourceStates`. Recent global trades reuse the existing 24-row snapshot and
15-second read cache. Successful empty reads and failed reads have distinct
states; those states reach every model prompt through `metrics.sourceStates`
and produce deterministic limitations in both AI and fallback responses.
Once an incomplete analysis is at least five minutes old, the existing scheduled
seed checks its failed trade inputs using those same bounded readers. A recovered
source can trigger regeneration before the usual AI minimum interval; unchanged
failures retain the current snapshot without spending another model run. This
does not add a timer or reader-triggered generation to public GETs.
`tests/test_market_wide_trade_inputs.py` covers the real runtime/SQLite reader,
canonical key, stale exclusion, failure versus empty, and prompt/output paths.

Both trade sources depend on the existing OrderFilled owner and ClickHouse
`block_timestamps`; they do not use the optional PolySignal producer. RPC repair
belongs to the existing `polydata-trade-sync`, `polydata-block-timestamps-live`
and `polydata-orderfilled-health` units. Service-specific route overrides must
load after their other environment files and preserve sequential cursors,
confirmation depth, original block timestamps and existing resource budgets.
Verify effective process environment and actual cursor/store progress: a
responsive stale RPC can otherwise report false `caught_up` / empty windows.

The production seed checks hourly, generates each successful lens at most once
per six hours (`POLYDATA_AGENT_MARKET_WIDE_MIN_LIVE_INTERVAL_SECONDS=21600`), and
publishes all three lenses. Snapshots expire after twelve hours; browsers read
them every fifteen minutes through `/runtime/agent/market-wide-insights/<lens>`.
Source observation time, generation time and browser check time remain separate.
An unsuccessful model run remains a rules fallback/error, never an AI success.

Generation is sequential: up to three specialists, a skeptic and a writer per
lens. Deployment bounds the existing oneshot worker to fifteen minutes, with one
database connection under the seed-specific permit and the existing model input,
output and timeout limits. Page GETs do not invoke the model. The six-hour minimum
and systemd oneshot lifecycle bound scheduled work independently of user count.

Verification: `tests/test_agent_llm_client.py`, `tests/test_market_wide_agent_graph.py`,
`tests/test_market_wide_node_budget.py`, and `webpage/e2e/panel-discovery.spec.ts`.
Production acceptance additionally checks the actual model identity, stored
snapshots, public API and desktop/mobile panels; tests alone do not establish it.
`tests/test_market_wide_content_binding.py` exercises actual runtime assembly
through seed input and model context for all three lenses, including an empty
feed, bounded input and unchanged publication timestamps.

### Trade-input repair observed on 2026-11-06

- Changes `7d8ffbc1` and `b9b2def3` repair the whale reader and propagate source
  health, including regeneration after recovery. Only their owned backend hunks
  were installed; the gateway was restarted. All 26 focused tests passed in a
  clean archive of the pushed commit, and scoped Ruff passed.
- At 10:55 Asia/Shanghai, all three public API responses matched persisted and
  local API snapshots: Qwen3.5-9B generated them at 10:48:26, 10:49:42 and
  10:51:03, with no graph-node errors. They explicitly reported failed recent
  trade reads and seven stale whale items excluded from analysis. Counts remain
  zero for those two inputs until source recovery; this is not acceptance of
  real-time trade or whale coverage. The frontend release was unchanged; no new
  desktop/mobile UI acceptance is claimed by this backend repair.
- The self-hosted Polygon RPC returned head 96787899 with an approximately
  12.5-hour-old block. PublicNode and Tenderly returned current Polygon 137
  heads directly. The configured Chainstack fallback returned HTTP 401.
  Rabisu was also checked: Tenderly worked, PublicNode returned HTTP 403.
  The three existing chain units now load the scoped
  `~/.config/market-data/panel-chain-rpc.env` after their other environment files;
  direct bypass is limited to the verified RPC hostnames. The main proxy was
  unchanged, and the stale self-hosted node itself was not repaired.
- Block-time batches of 100 hit HTTP 429 under catch-up load. The existing
  timestamp worker now uses batches of ten with four workers, preserving
  sequential progress and confirmation depth. It reached block 96818819 with
  time 10:54:45 and completed successive 30-second live cycles. The trade
  collector uses its normal bounded 200-block windows and
  `POLYDATA_RPC_HEADER_BATCH_SIZE=10`; the owner module
  `market-data/src/common/rpc.py` caps header batches without dropping blocks.
  Its focused and existing RPC/timestamp tests passed (123 tests). Those narrow
  changes remain in the market-data working checkout because its source module
  is part of a pre-existing uncommitted reorganization, not this repo's release.
- Actual OrderFilled recovery remains incomplete: nine contiguous audited
  windows, blocks 96788380–96789579, contained 86,563 chain/stored events and
  zero missing keys. Raw/fact cursors reached 96789579, whose block time is still
  November 5 22:43:45. Exact event-index admission remains slow; no financial
  identity/readback guards, cursor ranges or historical gaps were bypassed.
  The original collector continues catch-up, the original whale worker retries,
  and the existing hourly Agent timer checks for source recovery. PolySignal
  remains disabled/inactive. These observations do not claim the backlog or
  historical coverage is complete.

### Acceptance observed on 2026-11-05

- Frontend release `696061ed3ea1727c309518a872e78f68137a6912` was built from the
  pushed commit's clean `git archive` using Node 22.23.3. The current serving host
  is Tencent; the API/seed and model gateway run on the existing local backend
  host. The old GCP units are not the serving path.
- All three persisted snapshots matched the serving API: `status=live`,
  `generationMode=ai`, `model=qwen3.5-9b`, with five successful model calls each.
  Generation times were 13:42:04, 13:43:12 and 13:44:19 Asia/Shanghai. A second seed
  execution reused these snapshots without model calls or timestamp renewal.
- The real `https://polymonitor.club` homepage, reached through the existing TLS
  tunnel without substituted APIs/tiles, passed 1440px and 390px checks: all three
  AI badges and timestamps, old-layout discovery, order/size preservation,
  persistence of a later saved hide, and no document horizontal overflow or page
  JavaScript errors. Public release identity matched the commit above.
- Local checks: 25 backend tests, seven frontend contract tests, five browser
  discovery tests, scoped Ruff, and both workspace/clean-release builds passed.
  Whole-worktree `make quality` stopped at an unrelated personal-path finding in
  `docs/crypto-strategy-panels.md`; it is not recorded as passing.
- Coverage remains sampled: 80 markets/60 groups; this run had no content-feed
  items or cached whale signals, some trade reads failed, and some bid/ask and
  historical-change inputs were missing. Other page regions still showed a book
  timeout/map fallback during inspection. Model recovery does not repair those
  sources. The six-hour automatic regeneration interval has not yet been observed.
- PolySignal's running client also uses the local 9B endpoint; its existing daily
  budget was exhausted during verification, so its observed explanation remained
  a template. Its budget was not reset or increased.

### News binding recovery observed on 2026-11-06

- Backend change `33c83218` supplies the missing content reader. Only that owned
  binding hunk was installed in the existing backend, preserving its other live
  changes; installed `scripts/api/bindings.py` SHA-256:
  `4f8b5fb6a4892bd85e6a7f9571a6330ddc0f47445635bbddb50ef5546c53aa3d`.
- A bounded one-off execution of the existing Agent seed regenerated the three
  lenses with `qwen3.5-9b`. AI Insights, Special Radar and Trend Watch each loaded
  12 content items and made five model requests, with no recorded node errors.
  Generation times were 09:51:57, 09:53:00 and 09:53:53 Asia/Shanghai. The catalyst
  tool trace contains real content titles, excerpts and original publication
  times. SQLite, the serving API and the public API agreed on the snapshots.
- All 19 targeted tests passed in both the working checkout and a clean archive
  of the pushed commit; scoped Ruff passed. The whole-repository gate remains
  blocked by the unrelated personal-path finding in `docs/crypto-strategy-panels.md`.
- The public desktop homepage displayed all three new generation timestamps;
  its unchanged frontend release was `696061ed3ea1727c309518a872e78f68137a6912`.
- The 390px cold-page check did not complete: it waited for the AI response and
  then timed out loading fonts. A subsequent navigation was refused at the
  existing TLS tunnel; the Tencent link journal recorded peer timeouts and
  automatic reconnection attempts. Mobile production acceptance remains open.
- PolySignal is stopped and disabled at the user's request. Source-feed errors,
  sampled coverage, missing whale inputs, failed trade reads and missing
  price-history/LOB fields are outside this news-binding repair. Loaded content
  does not establish complete or continuously fresh news coverage.
