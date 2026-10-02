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
| Demand gate | `MapContainer.afterFirstPaint()`、`waitForDeckRendererDemand()` | `WorldEventMap.tsx:scheduleRendererInstall()`：shell → first paint → 15% visible → idle/input；有最大等待；小屏也按 WebGL 能力探测，明确能力失败或显式 SVG 选择才用 fallback | `rendererVisibility.test.ts`；桌面/移动 Playwright | 完成 |
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

### 6.2 本轮实施前的产品差距（2026-10-02 基线）

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

边界数据额外核对：两份基础 GeoJSON 都有 240 个要素，但当前更新后的上游已非历史所说的逐字相同。
RU/UA 的 geometry 有差异；本地仍用 `CN-TW`，上游已用 `TW`。本地 `countryGeometry.ts:countryFeature`
要求严格两字母 ISO2，因此 `CN-TW` 要素不会进入国家命中/适配索引（不等于矢量底图不画该地区）。
这是 **P1 的地区标识归一化缺口**；应保留原始来源信息和几何，统一索引标识，补命中与报告测试。
边界几何的差异则需核对来源版本和表达口径，不应为追求截图一致直接改坐标或悄悄替换地域边界。

已有且不应重建：MapLibre/deck/Protomaps、2D/3D、SVG fallback、国家点击/过滤、10 层 registry、
灾害点线面、两级聚合与重要事件保护、完整记录列表、来源详情、真实雷达最新帧、航空视口
取消/代次/日期变更线、离屏暂停恢复与动态画布清晰度机制。当前差距在业务覆盖和生产闭环，
不是要重新换地图框架。

### 6.3 本轮证据位置

`webpage/artifacts/map-all-layers-20261002/` 保存旧七层 URL 的生产 before/after、
桌面/窄视口 Chrome、手动关闭/刷新、请求与 SW/release 身份、trace/video。
本轮测试明确区分 all-on 入场验收与用户手动选择的单图层回归场景。
实际执行结果及未通过项以该目录 README 为准；本节不提前声称发布或全功能对齐完成。


## 7. 2026-10-02 地图业务补齐与服务稳定性

沿用既有 renderer、图层 registry、hazard snapshot、服务缓存和 AIS 采集所有权。
本轮不是 WorldMonitor 全功能复制；下表分别说明实现与真实来源限制。

| 需求 | 实现归属 | 验证入口 / 覆盖边界 |
|---|---|---|
| P0 API 断连 | `gcp_serving_healthcheck.py`、`routes/system.py`、healthcheck unit | 新增无依赖 `/health/live`；依赖 readiness 失败不重启仍响应的 API；重启前持久化次数；oneshot 预算覆盖有界恢复。Oct2 03:24 的 GCP 日志确认旧健康检查因内容查询超时重启 API，引发请求重置。不是把上游异常改成成功。09:26 日志另证实认证 DB 连接超时导致轮换 worker 启动失败并终止 master；`auth_service.validate_runtime_config` 现保留公共 API 启动，认证操作仍 fail-closed，静态配置错误/缺表仍阻止启动。 |
| NWS/USGS 缓存返回 | `natural_hazards/service.py`、`snapshots.py` | fresh 直接返回；保留期内 stale 立即返回，后台 singleflight 刷新；缓存 IO 不占调度锁；保留 429、blocked 和原成功时间；NWS deadline 从真正执行时起算。 |
| 雷达恢复 | `useWeatherRadar.ts`、现有雷达状态面板 | 失败后 5/15/45 秒有限快速重试，再回正常周期；手动刷新、过期退出；401/403/429 冷却不能被按钮和可见性变化绕过。不是历史帧播放。 |
| 地区温度 | 现有 `global_weather_map_service.py` 的 map-query、`MapExplore` | 国家/地点/机场/已加载飞机搜索，选择真实坐标定位；Open-Meteo 当前模式温度、湿度、风速、24 小时及七天温度。请求可取消，缓存/singleflight 复用；标注模式估计，不当作官方灾害预警。 |
| 国家详情 | `CountryBrief`、既有事件详情 | 当前已加载且符合筛选的唯一记录、分类、来源、时间线、定位/筛选/事件详情。覆盖不足明确显示；不声称完整国家新闻档案或生成式国家研判。 |
| 地区索引 | `countryGeometry.ts` | CN-TW 仅归一化索引到 TW，保留原几何；单测与搜索→国家简报→筛选浏览器测试。 |
| 机场运行 | 现有运输 service 的 map source `faa` | 真实 FAA NAS 延误/限制/关闭通告，保留适用机型等原始条件；机场坐标来自现有 OpenFlights。不是全球机场正常状态目录。 |
| 官方天气覆盖 | 既有 hazard pipeline 新增 ECCC / SWIC provider | ECCC 加拿大原生区域、更新及取消/过期；WMO 成员国 CAP 目录保留时间/级别/国家。SWIC 没有原生灾害几何，保留完整返回目录供事件列表和国家简报，不造中心点；US/CA 仍由原生来源负责。 |
| 船舶 | 现有 AIS sampler/cache → `ais-vessels` | 保存真实 PositionReport 坐标、MMSI、时间和速度；修正订阅 bbox 的纬经顺序；不扩大原采样频次/配额，不由浏览器另开采集；低频最后观测，不标实时全球覆盖。 |
| 水道/管道/海缆 | `map_infrastructure_service.py` → 现有路径 renderer | OSM 原始 way 几何，实际 renderer bbox（日期变更线分片）；需放大到 25 平方度内，ODbL 归属及覆盖提示。不是全球完整基础设施数据库。 |
| GNSS / 网络 | 同 service 的 GPSJAM / IODA → 现有面 renderer | GPSJAM 原始 H3 边界、官方去噪比例 `100*max(0,bad-1)/(good+bad)`；显示 >=2% 的异常精度格，保留完整源目录及分母。IODA 24h 国家测量信号；均不直接断言干扰原因或全国断网。 |
| 全开视觉 | `weatherBasemap.ts`、地图组件样式、航空路径工厂 | 删除额外底图文字颜色/描边覆盖，使用 WorldMonitor 同类 Protomaps palette/rank；保留本地比例字体。来源状态折叠但异常数量可见，小屏过滤折叠，航空面板默认紧凑，普通航线减弱，国家菜单避让且可点击。事件列表首次打开后保留 DOM，避免移除焦点输入框导致原生节点持续保留；关闭时 hidden 并退出可访问树。 |

### 7.1 验证与来源限制

- 单测入口：`tests/test_map_completion.py`、自然灾害/运输现有测试；前端 map unit tests 与 `weatherBasemap.test.ts`。
- 浏览器入口：`e2e/map-completion.spec.ts`、`world-event-map.spec.ts`；覆盖重试、取消/需求隔离、温度查询、TW 简报、小屏、SVG/2D、离屏恢复与 50 次交互资源检查。3D 既有专项单独记录，不计入本轮地图 24 项结果。测试失败必须修复，不能更新阈值掩盖。
- 本轮证据目录：`webpage/artifacts/map-completion-20261002/`。生产截图/trace、来源响应、同制品 SHA 和实际运行结果以其中验收记录为准；候选测试成功不等同于已经上线。
- **全球 NOTAM 仍受真实授权来源约束**：WorldMonitor 自身通过 `ICAO_API_KEY` 获取 ICAO 通告。当前未发现对应可用配置。FAA 美国限制通告不能当作全球 NOTAM，也不能从静态航线推断运行正常。
- 实际来源可能为空、stale、partial 或 unavailable；保留这些状态。实机 iOS/Android 验收由用户明确排除；窄视口 Chrome 不替代实机结论。

- 布局基线修订：原首页截图仍为旧矮地图/旧工具栏。本轮按实际概览、紧凑控件和搜索入口复核，原图与新图保存在证据目录 `reviewed-baselines/`；布局截图固定 SVG 分支，WebGL 几何、恢复及生产真实底图分别验收。仍使用零像素差异，不放宽容差。冷来源失败场景明确清空测试缓存，避免把上一场景保留的 stale 误判为 unavailable；中文冷/热字体复跑保持相同图层选择。
