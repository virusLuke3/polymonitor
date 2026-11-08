# Panel Modules

## Retirement and inventory maintenance

Retiring a Panel removes its production registration, dedicated worker/API,
operations contract, delivery-catalog entry and obsolete visual baselines.
Replace tests that expect the old feature to load with retirement checks for
both local and account layouts. Keep only the historical-ID filter needed to
prevent saved layouts from restoring it; preserve other panels, sizes and
explicit hides. Dated incident records remain historical evidence.

`tests/test_panel_operations_contract.py` compares the operations inventory with
the real frontend registry and checks reused data owners. Inventory coverage is
not a source-health claim: missing source evidence remains UNKNOWN. The contract
uses repository service-template names; deployed service identities and
source-level clocks still need runtime verification.

`webpage/e2e/retired-panels.spec.ts` verifies that the two retired signal IDs stay
absent, do not trigger requests and are removed from synchronized preferences.
The ordinary-homepage discovery suite covers active defaults and later hides.

polyData dashboard panels are registered through frontend and backend manifests so new panels can be added without editing the dashboard shell.

This document owns the panel interface contract. The
[frontend optimization plan](frontend-architecture-optimization.md) owns migration
steps and acceptance; the [WorldMonitor architecture](worldmonitor-frontend-architecture.md)
is the upstream reference, not an alternative implementation contract.

Before adding or upgrading a panel, read the [data pipeline contract](panel-data-pipeline.md)
and [cadence rules](panel-data-cadence.md). Identify the existing producer, storage,
API and shared Runtime before writing the view. Requests and caching also follow
the [resource contract](panel-resource-contract.md) and [shared lifecycle](panel-runtime-lifecycle.md).
Keep these choices in the existing feature index or domain document.

All credentials, upstream source endpoints/templates and proxy nodes/routes must
come from `.env`, including public sources and fallback destinations. Do not
hard-code their values in scripts, catalogs, defaults or deployment units. Follow
the [environment configuration contract](panel-data-pipeline.md#31-密钥数据源和代理统一由-env-配置)
for shared loading, missing configuration, safe examples and migration checks.
This rule also applies when the ignored local guide is absent; it does not claim
that existing hard-coded configuration has already been migrated.

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

When a map or another feature consumes the same runtime data, keep one owner for
the snapshot, cache, and refresh lifecycle. Consumer visibility is aggregated by `usePanelRuntime`: enabled visible panels and
`setConsumerPanels(consumerId, sourceIds)` are independent consumers. Removing a
consumer only aborts a batch when no remaining consumer needs it. Page hiding
pauses shared requests and retry timers; resuming uses the same request owner.

A view that renders another panel's snapshot declares `dataSourceId` and omits
`fetchData`. Weather detail views use `global-temperature-monitor` this way.
A panel with additional inputs declares `dataDependencies`, including views with
no fetcher of their own. Macro panels use this for `polymarket-macro-map`; the three
market-wide AI views consume `alpha-signal`, `whale-tracker` and `suspicious-flow`.
Dependency-only views must remain in `RUNTIME_PANEL_MODULES` so their visibility
can keep those owners active. Register the source owner once.
`getData(id)`, `getStatus(id)` and explicit refresh resolve these declarations;
renderers read the canonical key from `runtimeData`. App does not translate these
snapshots into a second set of provider-specific context fields.

`fetchData(context, limit)` must forward `context?.signal` to its service, including
individual fallback requests. The Runtime owns in-flight sharing, retries and
refresh intervals; bodies must not start a second loop for these snapshots.
Payload observation time remains distinct from request completion time. Retaining
a useful snapshot after a warming response also retains its observation time.

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
5. Add body styles to the owning family in `webpage/src/panels/styles/`; map, globe and focused-market styles have their own feature/component files. Keep generic shell rules in `panels/styles/shell.css` and grid policy in `styles/panel-workspace.css` / `styles/panel-layout-stability.css`. Remove replaced rules in the same migration.

`styles/panels.css` is an import-only entry. Each family explicitly preserves its
`base` layer and the existing unlayered dashboard constraints; moving a declaration
between these changes the cascade, including the reversed priority of important
layers. `scripts/frontend-style-owners.mjs` defines private selector ownership and
`npm run check:boundaries` rejects rules in the wrong owner. Responsive variants,
state selectors, shorthand fallbacks and detached drag previews remain part of the
contract, not automatically redundant rules.

`e2e/panel-styles.spec.ts` mounts production registry renderers with the shared shell
and fixed local fixtures. Its desktop/mobile checks cover every non-focus registered
body plus populated finance, tech, macro and weather examples. Dashboard, focused
market, real panel sizing and interactions remain covered by
`e2e/frontend-architecture.spec.ts`; isolated body snapshots do not replace those
integration checks. Both are included in `npm run test:frontend:e2e` and CI's
`npm run test:browser`.

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

Finance external inputs remain owned by `runtime/finance_external_sources_watcher.py`
and stored as `runtime:finance:external-sources / v1` in the existing snapshot store.
OKX uses the `.env`-configured batch ticker endpoint once per source refresh,
validates the SWAP response, then intersects the returned instrument IDs with
the watchlist. Missing watchlist IDs are distinct from transport failures; an
empty/invalid catalog cannot establish unsupported instruments. Last trade price,
24-hour change and base-currency volume keep their own meanings: unknown mark,
spot, funding and dollar notional remain null. Yahoo futures are labeled reference
futures. COT keeps the original report date and HTTP failures, and stops repeated
queries after a 401/403 rejection. GET acquisition shares the existing transport
with at most two complete attempts, a 90-second source deadline and an 8 MiB body
cap. Successful row acquisition times survive composition; failed rows retain
their original clocks only within the existing 30-minute retention bound. API
views read these snapshots and do not start another collector or cache.

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

## 公司公告与政策进程（首批）

开发与验收遵循 [首批数据/视觉契约](official-disclosures-panels.md)。共用领域采集拥有者，SEC submissions / Federal Register 30 分钟，SEC companyfacts 6 小时，浏览器 10 分钟只读快照。失败逐来源退避并保留原始成功时间；新 Panel 默认合并进旧布局。

### 新来源与正文差异的共同规则

候选目录不等于已接入：先验证实体、字段、时间、覆盖和真实响应，再画视图；预测和官方实际值分开。失败保留实体级最后成功值与时间。拥有 `fetchData` 的模块直接使用自身 `id`；只有纯视图才设置 `dataSourceId` 引用另一拥有者。必须运行真实 registry 启动测试。

共享外框/标题/五列槽位，正文按业务使用不同布局：20–28px 主指标或日期、13–16px 重要实体、12px 正文、9–10px 元信息；共用字体资源。分类可使用 design-system 的 cyan/purple/orange 角色和对应浅背景/侧边色条，必须带文字标签，不能把类别伪装为涨跌。先截图观察 WorldMonitor 的不同正文层级，再在实际槽位验收；不再统一套用三指标框或灰白列表。
