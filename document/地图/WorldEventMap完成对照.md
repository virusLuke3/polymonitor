# World Event Map 完成对照与发布证据

> 本文记录 WorldMonitor 机制到 Polymonitor 灾害情报地图的逐项映射。它是
> `WorldEventMap实施指导.md` 的交付证据，不代表复制 WorldMonitor 的业务图层或视觉资产。
> Polymonitor 的地图主体仍是可验证灾害、异常、冲突与航空参考；预测市场只在事件详情中关联。

> 下面第 1–3 节的“完成”指历史批次所列机制，不等于当前生产全来源正常，也不表示与 WorldMonitor 全功能等价。2026-10-02 的重新核对见第 6 节。

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


## 6. 2026-10-02 全开策略与 WorldMonitor 差距复核

对照版本：本地 WorldMonitor 已从 `4691d9213` 快进到
`0a74f70d8e0f6900bc5af967923f3127d44f83ad`。依据为该版本源码、当前
Polymonitor 工作区和本项目实施契约，不能把上游 registry 的声明当作所有线上来源均可用。

### 6.1 本轮明确改变的行为

用户确认“每次进入都全开，之后可手动关闭”。`initialWorldEventMapState()` 在 URL/本地
调查条件恢复后，只将 `activeLayerIds` 设为现有 registry 的全部 executable 项。
当前生产配置对应 10 层：天气预警、地震火山、野火、极端温度、气候异常、航空、情报热点、
冲突、制裁与国家证据、天气雷达。没有新建第二份 registry，也没有重置相机、时间、severity、
国家或航空 lens。旧链接、刷新、本地空列表不再把航空/雷达关闭；当前页面手动关闭不会被
普通刷新/缩放重新打开。URL 仍记录当前状态，但新一轮入场按全开策略执行。

全开表示请求该功能，不承诺每层都有事件、每个来源新鲜，或 SVG 能绘制 WebGL 雷达。
真实飞机仍要求有效 bbox、zoom >= 2 和有效观测；全球 trunk 动画仍是明确标识的参考表现。
2D/3D 是互斥视图，并非同时加载的“图层”。

本轮回归另修正两处就绪语义：替代底图按真实 source id 判断内容就绪，不能只识别 PMTiles 的 `basemap`；SVG/本地降级成功保留原故障原因，直到 primary-ready 才清除。

### 6.2 仍需完成的产品差距

| 领域 | 上游当前源码 | Polymonitor 当前事实 | 下一步与优先级 |
|---|---|---|---|
| 雷达加载/恢复 | `DeckGLMap.ts:fetchAndApplyRadar` 随 weather 开关启动，取最后一帧，每 5 分钟刷新 | `useWeatherRadar` 是独立 layer，已有真实瓦片/覆盖/错误状态；首次失败同样等 5 分钟才定时重试 | **P1** 区分首次失败重试与正常刷新，增加有限退避和手动重试；保留过期退出与真实错误。历史雷达播放是两边当前实现之外的新需求 |
| 航空业务 | `data-loader.ts:loadFlightDelays`、`AviationCommandBar`、`DeckGLMap.fetchViewportAircraft`：机场扰动、NOTAM、航班查询、视口飞机 | `transportReferenceAdapter` + `AviationLens` + `useAviationViewport`：静态航线/机场、参考动画、真实视口观测与风险筛选 | **P1** 实施契约 v1.2 的 transport disruption 尚未交付；需要真实机场关闭/延误、空域通告来源和事件报告，不能用 OpenFlights 航线代替运营状态 |
| 天气覆盖 | `map-layer-definitions.ts:weather` 与 weather service 包含 NWS、ECCC、WMO SWIC | 八类灾害来源含 NWS、NHC、USGS、EONET、GDACS、FIRMS、NCEI；NWS 不是全球气象预警目录 | **P1** 按来源扩展加拿大/全球官方预警，保留 native id、取消更新、几何增强和覆盖边界；先治理现有 deadline/过期来源 |
| 国家详情 | `country-intel.ts` + `CountryBriefPanel` 汇合国家新闻、事件时间线和航空等信号 | 国家点击菜单目前是 Fit country / Filter events；事件详情有来源和灾害报告 | **P1** 复用现有 Inspector/Runtime 增加国家汇总入口，显示来源时间/缺失项；当前不等于国家综合简报 |
| 地图搜索 | `search-manager.ts` 有国家、位置、图层和实时飞机结果与定位分发 | LayerPanel 搜图层名；EventList 搜已加载事件；首页命令面板主要是市场、panel、命令 | **P1** 将已有入口扩展为统一地理搜索与定位；保留事件/来源类型和不在当前筛选内的说明，不增加第二套加载 |
| 国家区域含义 | 上游 CII 是多源复合分数，conflict 与 sanctions 另外建模 | `geoShockAdapter` 是制裁/冲突证据背景，`severityBasis=evidence-context-only`，不是 CII | **P1** 图例、国家报告持续明确证据与风险区别；如要分级评分，需另立可验证公式/来源/版本。不可为模仿红黄配色伪造风险 |
| 边界一致性 | Protomaps 矢量底图 + 国家 GeoJSON；country-geometry 支持可选精细 overrides | 底图已恢复 provider 国界，风险 outline 像素单位与 beforeId 已修；国家命中/证据区域仍用独立 GeoJSON | **P2** 按缩放和地区对比边界贴合、接缝和争议边界语义；不能把叠加 GeoJSON 与不同 zoom 瓦片差异当作 CSS 修掉 |
| 字体与视觉密度 | Protomaps 角色字体、symbol 排序和标签碰撞；不同业务 layer 自有语义 | 本地比例地图字体已保留 Regular/Medium/Bold/Italic，控件/报告用 body，代码字段用 mono；语言跟随当前 EN/中文 | **P2** 继续做全开状态的地名/事件/航线遮挡预算、全屏与普通高度、桌面/小屏验收。英文截图不能直接按中文字形判断渲染失败 |
| 更多空间情报 | 上游 registry 有 AIS、tradeRoutes、水道、军事实体、海缆、管道、outages、GPS、cyber、displacement 等 | 当前地图 registry 没有这些执行链；面板存在类似主题不等于已经进入地图 | **P2/后续需求** 按本项目 §4.3/4.4 先做运输中断、重要基础设施及市场联动；每项要来源→规范化→layer→详情→测试闭环，不一次性复制全部变体/付费层 |
| 生产可靠性 | 上游也受来源配额、覆盖、缓存与网络影响，声明能力不等于实时健康 | 全开只修启用策略；NWS/其他来源 ERROR/STALE，目录 REFRESH FAILED 等需要各自运行证据 | **P0** 按前端请求、CDN/cache、API deadline、provider 获取逐层定位；不隐藏 ERROR，不把 HTTP 200 算作 fresh，不用截图证明长期稳定 |

已有且不应重建：MapLibre/deck/Protomaps、2D/3D、SVG fallback、国家点击/过滤、10 层 registry、
灾害点线面、两级聚合与重要事件保护、完整记录列表、来源详情、真实雷达最新帧、航空视口
取消/代次/日期变更线、离屏暂停恢复与动态画布清晰度机制。当前差距在业务覆盖和生产闭环，
不是要重新换地图框架。

### 6.3 本轮证据位置

`webpage/artifacts/map-all-layers-20261002/` 保存旧七层 URL 的生产 before/after、
桌面/窄视口 Chrome、手动关闭/刷新、请求与 SW/release 身份、trace/video。
本轮测试明确区分 all-on 入场验收与用户手动选择的单图层回归场景。
实际执行结果及未通过项以该目录 README 为准；本节不提前声称发布或全功能对齐完成。
