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
