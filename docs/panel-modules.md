# Panel Modules

polyData dashboard panels are registered through frontend and backend manifests so new panels can be added without editing the dashboard shell.

## Design Intent

The panel system is intentionally moving away from "large central scripts" and toward small, explicit modules. A panel should own its data access, render entrypoint, metadata, refresh behavior, and backend snapshot logic. Central files should only compose manifests; they should not accumulate panel-specific business logic.

This keeps the public dashboard stable while making internal development easier:

- Public API paths stay stable, especially existing `/runtime/...` routes.
- The default workspace keeps the same visible panel behavior unless a product change explicitly says otherwise.
- `App.tsx` should not gain new per-panel `useState`, `fetchRuntimeX`, or `setRuntimeX` wiring.
- Backend route files should not grow one route function per panel; runtime panel routes are registered from the backend manifest.
- A new panel should be reviewable as a small frontend module plus, when needed, a small backend runtime module.

The current design uses explicit registry lists rather than filesystem auto-discovery. That is deliberate: Vite and Python deployments are easier to reason about when imports are static, and failures are caught at build/test time. The price is one small registry addition on the frontend and one on the backend; the benefit is predictable public deployment behavior.

## Frontend

Each panel owns a module under `webpage/src/panels/modules/<panel-id>/` and exports `panel`.

Runtime panels declare `fetchData` and `refreshPolicy.tier`; the dashboard loads those through the generic runtime store instead of adding per-panel `useState` and refresh code in `App.tsx`. The helper below accepts `tier` and constructs that policy.

The constructors live in `webpage/src/panels/definePanel.ts`. A renderer defaults
to snapshot inputs only. A panel that uses workspace state declares, for example,
`PanelRenderMap<'selectedWeatherCityId'>` and
`contextKeys: ['selectedWeatherCityId']`. The constructor passes only these fields
and the snapshots named by the panel ID, `dataSourceId`, and `dataDependencies`;
the full `PanelRenderContext` remains at the application composition boundary.

Declare a request `limit` in the runtime options once. The constructor exposes it
as `panel.request.limit` for batching and binds the same value as the second
argument to the individual `fetchData` callback. The runtime store must not keep
a separate table of panel-specific request parameters.

The frontend runtime uses the versioned `/v1/runtime/panels` envelope. Legacy
`/runtime/panels` and per-panel routes remain raw-payload compatibility
endpoints. The v1 response always includes `apiVersion`, `requestId`,
`generatedAt`, `status`, `data`, `meta`, and `errors`; per-panel cache and
freshness observations live under `meta.panels`.

The machine-readable OpenAPI 3.1 contract is served from `/openapi.json` and
`/v1/openapi.json`.

Minimal runtime panel shape:

```ts
import { runtimePanelFromRenderer } from '@/panels/definePanel';

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'example-panel',
  title: 'Example Panel',
  eyebrow: 'example',
  description: 'What this panel shows.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  limit: 12,
  fetchData: (context, limit) => fetchExamplePanel(limit, context?.signal),
});
```

For a new frontend panel:

1. Create `webpage/src/panels/modules/<panel-id>/index.ts` (or `.tsx` when it contains UI).
2. Keep panel-specific UI in that directory. Shared Finance, Tech and Macro templates live under `panels/shared/`; do not reintroduce grouped renderer registries or import another panel's implementation. The fixed price/book/trade strip remains owned by `FocusedMarketStrip`.
3. Add the module to `webpage/src/panels/modules/index.ts`.
4. Do not add panel-specific state or refresh code to `App.tsx`.

Weather sharing is split into pure `shared/weather/model.ts` and `trend.ts`,
the token-book hook, and reusable chart components. Views share these modules
without importing another weather panel entrypoint. `check:boundaries` enforces
sibling-panel import restrictions, declared workspace inputs and snapshot reads.

## Backend

Runtime API panels are registered in `scripts/api/runtime_panels/registry.py`. Each module under `scripts/api/runtime_panels/modules/` declares `PANEL_ID`, `ROUTE`, limit bounds, and `get_snapshot`.

The Flask route layer uses `scripts/api/routes/runtime_panels.py` to register all runtime routes while preserving existing API paths.

Finance watch snapshot/cache orchestration remains in
`scripts/api/services/finance_watch_panels_service.py`. Its payload builders are
owned by `finance_watch/research.py`, `news.py`, `markets.py`, and `sentiment.py`;
their dependencies and common request/payload utilities live in `common.py`.
Builders do not import the orchestration service. Existing API and watcher
entrypoints, cache keys, stale-snapshot handling and public payloads stay stable.

Minimal backend runtime module shape:

```py
PANEL_ID = "example-panel"
ROUTE = "/runtime/example/panel"
DEFAULT_LIMIT = 8
MIN_LIMIT = 1
MAX_LIMIT = 20


def get_snapshot(ctx: dict, *, limit: int = DEFAULT_LIMIT) -> dict:
    ...
```

For a new backend runtime panel:

1. Create `scripts/api/runtime_panels/modules/<panel_name>.py`.
2. Register that module in `scripts/api/runtime_panels/registry.py`.
3. Keep the existing public API path stable if replacing an old endpoint.
4. Do not add another one-off runtime route file unless it is not a panel API.

## Guardrails

- Build after frontend panel changes: `cd webpage && npm run build`.
- Run backend registry and affected runtime tests after backend changes.
- Keep old compatibility paths working during refactors.
- Avoid moving visual behavior and architecture in the same change; split UI redesign from module decomposition.
- If a panel needs shared helpers, put reusable code under `webpage/src/panels/shared/` or an appropriate backend service module instead of coupling unrelated panels together.

## Market analysis panels

`price-implications`, `sample-chain-trades` and `oracle-timeline` retain their saved-layout IDs and own the overview, special and trend views. Each declares a cancellable snapshot fetch, a one-minute polling interval and `batch: false` because the analysis API has its own endpoints. Refreshing a view reads a saved snapshot; it does not trigger a model call. The shared runtime owns visibility, retry and cancellation.

`shared/market-insights` validates the lens and response cards and supplies common presentation. It contains no local market-ranking algorithm. AI results, rules summaries, expired snapshots, unknown timestamps and unavailable data remain distinct. Empty server arrays are authoritative. Snapshot generation and sample-scoped deterministic observations live in `agent/market_wide`, with rules in `rules.py`. Absolute volume cannot imply a spike; category counts cannot imply rotation. Failed generation remains observable even when a usable rules snapshot is saved.

`featured-market` consumes only selected-market identity, metadata and the matching bundle. It never substitutes a bootstrap market or another market's oracle/reference rule.
