# World Event Map 完成对照与发布证据

> 本文记录 WorldMonitor 机制到 Polymonitor 灾害情报地图的逐项映射。它是
> `WorldEventMap实施指导.md` 的交付证据，不代表复制 WorldMonitor 的业务图层或视觉资产。
> Polymonitor 的地图主体仍是可验证灾害、异常、冲突与航空参考；预测市场只在事件详情中关联。

## 1. 架构与交互对照

| 要求 | WorldMonitor 对照函数/机制 | Polymonitor 实现 | 自动化证据 | 状态 |
|---|---|---|---|---|
| 可执行图层注册表 | `map-layer-definitions.ts:isLayerExecutable()` | `layerRegistry.ts:isWorldEventLayerExecutable()`；registry 同时定义 renderer、source、availability、alias、capability、legend/presentation token；`LayerPanel.tsx` 禁用 unavailable 并排除 active count | `layerRegistry.test.ts`；Playwright `required source failure...` | 完成 |
| Basemap provider/theme | `basemap-styles.ts`、`map-locale.ts`、style reload | `mapState.ts`/`urlState.ts` 保存 provider/theme；`weatherBasemap.ts` 提供 PMTiles primary 和 OpenFreeMap/CARTO fallback；`DeckMapRenderer.reloadStyle()` 重建 country/overlay | `mapState.test.ts`；Playwright provider/theme reload | 完成 |
| Demand gate | `MapContainer.afterFirstPaint()`、`waitForDeckRendererDemand()` | `WorldEventMap.tsx:scheduleRendererInstall()`：shell → first paint → 15% visible → idle/input；有最大等待；移动/省流模式优先 SVG | `rendererVisibility.test.ts`；桌面/移动 Playwright | 完成 |
| 单图层错误隔离 | `DeckGLMap` overlay error/quarantine | `DeckMapRenderer.handleDeckLayerError()` 记录 layer id、只剔除失败 layer；renderer/context 级失败才切 SVG | `rendererHoverLifecycle.test.ts`；context failure Playwright | 完成 |
| 国家交互 | `country-interactive`、rAF feature query、fit bounds/context menu | `DeckMapRenderer` 透明命中、rAF hover、click、context menu、fit；`SvgMapRenderer` 等价操作；country 进入 URL 和事件过滤 | `countryGeometry.test.ts`；WebGL/SVG country Playwright | 完成 |
| 屏幕空间标签 | WorldMonitor SVG 的矩形碰撞；MapLibre symbol occupancy | `DeckMapRenderer` 使用投影 bbox、MapLibre symbol bbox 和优先级；`SvgMapRenderer` 复用相同优先级并计算文字 bbox | map layer factory tests；高密度视觉截图 | 完成 |
| Hover/click 分离 | `MapboxOverlay.getTooltip()` + popup click | WebGL 按 layer id formatter；SVG `RendererTooltip`；hover 只描边/tooltip，click 才打开 `EventInspector` | tooltip/lifecycle unit tests；WebGL/SVG event Playwright | 完成 |
| Renderer 生命周期 | `MapContainer` renderer handoff | renderer switch/destroy 统一清 hover、tooltip、timer、rAF、overlay；状态仍由 map state 保存 | `rendererHoverLifecycle.test.ts`；context loss Playwright | 完成 |

## 2. 数据与来源对照

| 要求 | WorldMonitor 对照函数/机制 | Polymonitor 实现 | 自动化证据 | 状态 |
|---|---|---|---|---|
| 分源紧凑加载 | `data-loader.ts` 分层 hydration、`Promise.allSettled` 独立提交 | `useNaturalHazards.ts` 分源并发、Abort/generation/retry、last-good；`map_feed.py:compact_hazard_event()`；详情按需 endpoint | `naturalHazards.test.ts`、`test_natural_hazards.py` | 完成 |
| ETag/cache/source isolation | 源独立请求和持久缓存 | `runtime_panels.py:_public_conditional_json()`；源级 Cache-Control/ETag；IndexedDB snapshot；一个源失败保留其他源 | `test_runtime_panel_registry.py`；source status tests | 完成 |
| NHC observed/forecast/cone | WorldMonitor 的 path/polygon 分层机制（无同等 NHC 契约） | `providers/nhc.py` 使用 NHC CurrentStorms/GIS KMZ；observed position/track、forecast track/cone、advisory、dateline split | `test_nhc_preserves...`、`test_nhc_splits...`；NHC Playwright 截图 | 完成 |
| Climate anomaly 可复现性 | 数据源独立 hydration | `providers/ncei.py` 使用 NOAA NCEI 5° monthly anomaly；baseline、unit、window、resolution、calculationVersion；前端拒绝元数据不全对象 | NCEI backend test；validation/unit；climate Playwright | 完成 |
| Observation → canonical event | 源独立数据对象 | `dedupe.py:canonical_event_identity/latest_revision` 与 `naturalHazards.ts:mergeCanonicalHazardEvents()`；只接受 provider canonical id 或显式 USGS event URL，不做距离盲合并 | 前后端 canonical merge tests | 完成 |
| NWS CAP 生命周期 | provider 独立更新 | `providers/nws.py` 请求 alert/update/cancel，沿 references 保持 canonical identity，处理 ended/expired 和上一版官方 geometry | alert/update/cancel/expired 参数化测试 | 完成 |
| FIRMS drill-down | WorldMonitor FIRMS ScatterplotLayer | 低 zoom 聚合；zoom≥5 只请求当前 bbox raw detection；raw 不进入 pulse；完整 sensor/confidence/FRP/coverage | FIRMS viewport backend test；Playwright drill-down | 完成（需生产 FIRMS key） |
| Volcano/CAP coverage | 图层来源与限制说明 | `providers/usgs_volcano_cap.py` 接 USGS HANS elevated CAP；coverage 明确限定 USGS responsibility area；EONET 仅 discovery | USGS volcano test；Layer brief | 完成（非全球覆盖） |
| Aviation viewport | `DeckGLMap.fetchViewportAircraft()` + `aircraftFetchSeq` | `get_aviation_viewport_snapshot()` 接 bbox/zoom、server token、量化 viewport cache；`useAviationViewport()` Abort/generation/stale discard | aviation backend test；live aircraft Playwright | 完成（需生产 OpenSky credentials） |

## 3. 渲染、动画与性能对照

| 要求 | WorldMonitor 对照函数/机制 | Polymonitor 实现 | 自动化证据 | 状态 |
|---|---|---|---|---|
| 统一 rAF / latest commit | `DeckGLMap.updateLayers()`、deferred heavy commit | `MapRenderScheduler` 合并 invalidation；`deferredCommit.ts` 用 `scheduler.yield()`；无固定 900ms/逐标签 160ms 延迟 | scheduler/deferred unit tests；performance trace | 完成 |
| 两阶段重型 geometry | `DeferredHeavyCommit` | 点/路径先提交，geometry yield 后 latest-only；resize 只调用 map/overlay resize | renderer tests；performance trace | 完成 |
| 航空 overlay 按需 | WorldMonitor 单 overlay + viewport aircraft | air-routes 未启用不创建动态 overlay；启用且有动态对象时才装第二 Canvas；动态帧只提交 aviation layers | layer factory/unit；Playwright Canvas count/perf dynamic commit | 完成 |
| 航空视觉/交互 | Aircraft `IconLayer`、route motion points | 真实 aircraft IconLayer；2–4px runner；端点淡出；屏幕网格去重/计数；alpha/selected route dim；hover 单环、selected 双环 | `layerFactories.test.ts`；aviation Playwright | 完成 |
| 灾害 emphasis | 重要对象的克制强调 | 实体点稳定 pickable；pulse 为空心、不可拾取；critical/recent/selected 和弱 warning；500ms；reduced motion/hidden/drag/offscreen 停止 | emphasis/lifecycle tests；reduced-motion Playwright | 完成 |
| 图层顺序 | polygon/path/icon/text 分层 | polygon → route → runner → hub → aircraft → selected outline → labels | layer factory ordering test | 完成 |
| 图例/视觉 token | `createLegend()` 与 layer encoding | registry presentation token 同时驱动 Layer Panel、legend、map、event list；类型、severity、fresh/stale、observed/forecast、coverage；无 `.slice(0, 8)` | registry/unit；全部视觉截图 | 完成 |
| 懒加载与清晰度 | Deck renderer demand import；DPR cap 2 | MapLibre/deck/PMTiles/Supercluster 独立 lazy chunks；静态 DPR 保持最高 2；英文 label + halo | `check:map-bundle`；build | 完成 |

## 4. 自动化命令与证据位置

- Frontend unit/type/build: `cd webpage && npm run test:map && npm run build`
- Browser contract: `cd webpage && npm run test:map:e2e`
- Isolated backend contract: `env -i ... PYTHON_DOTENV_DISABLED=1 python3 -m pytest ...`
- Performance: `cd webpage && npm run perf:map -- <production-url> --strict --require-hazards --require-dynamic`
- Stable screenshots: `webpage/artifacts/world-event-map-e2e/01-global-default.png` through `09-mobile.png`
- Trace/report: `webpage/artifacts/map-performance/`

Fixture 截图只证明确定性 UI/交互，不证明生产来源实时性。生产验收必须另外记录 source status、
deployed SHA、asset hash、PMTiles 206、航空 dynamic commit、service/log 与真实浏览器截图。

## 5. 发布记录

发布 SHA、CI、GCP deployed SHA、生产性能 JSON、桌面/移动截图和外部 coverage 限制在发布验收后写入本节。
