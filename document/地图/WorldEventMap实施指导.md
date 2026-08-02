# World Event Map 实施、鲁棒性与解耦重构指导

> 文档性质：产品决策、架构约束与实施验收契约
> 适用范围：Polymonitor 主工作区的 2D 地图，以及为其提供现实事件数据的前后端模块
> 首次制定：2026-07-29

## 1. 使用方式

任何开始修改 Polymonitor 2D 地图的开发者或自动化代理，都必须先阅读本文。

本文同时约束：

- 地图为什么存在，以及什么数据可以进入地图。
- 从 WorldMonitor 吸收哪些能力，以及明确不复制哪些内容。
- 如何把当前巨型地图组件拆成稳定边界。
- 如何修复底图黑屏、数据超时、竞态、资源泄漏和持续动画等鲁棒性问题。
- 每个阶段必须补什么测试，以及什么情况下允许部署。

如果实现与本文发生冲突，先更新并说明产品或架构决策，不得在代码里静默改变边界。

## 2. 产品定义

### 2.1 唯一目标

Polymonitor 的 2D 地图是：

> **World Event Map：影响预测市场的现实世界事件地图。**

它首先回答：

1. 世界哪里发生了什么？
2. 事件发生在什么时候，现在是否仍然有效？
3. 严重程度、来源、时效、置信度和限制是什么？
4. 是否存在与该事件相关的 Polymarket 市场？
5. 用户是否需要进入 Market Workspace 继续分析价格、成交、LOB 和 Oracle？

地图以现实事件为主实体。Polymarket 是事件的关联分析结果，不是地图的空间数据来源。

在 Natural Hazards 阶段，地图默认主体是强风暴、飓风、洪水、极端温度、地震、火山、野火和重大气象异常。存在天气市场的城市既不定义覆盖范围，也不生成默认 marker。

### 2.2 核心用户流程

```text
扫描全球事件
  → 按时间、类型、严重度和地区过滤
  → 选择一个真实地理事件
  → 查看来源、时间、位置精度、证据和历史
  → 查看相关 Polymarket 市场
  → 进入市场工作台分析概率、OrderFilled、LOB 和 Oracle
```

### 2.3 非目标

以下内容不得成为独立地图图层：

- Polymarket Markets 全量列表
- Oracle 事件流
- 逐笔 OrderFilled
- Runtime LOB
- 钱包、地址、PnL 或 Smart Money
- “存在天气市场的城市”静态点位
- 没有可靠地理信息的新闻、市场或研究内容

这些内容只能出现在选中现实事件后的关联面板或 Market Workspace 中。

不得为了填满地图而：

- 从标题关键词猜测精确坐标。
- 把所有国家级事件放在首都。
- 用字符串哈希生成伪随机经纬度。
- 把钱包、成交或订单簿解释成用户所在地区。
- 用视觉上的“热点”掩盖数据源实际为空、过期或降级。

## 3. 从 WorldMonitor 吸收什么

WorldMonitor 的 2D 地图价值分为“内容覆盖”和“地图操作系统”。Polymonitor 不复制完整内容目录，但要选择性吸收成熟的地图平台能力。

### 3.1 必须吸收的地图平台能力

| 能力 | Polymonitor 目标 |
|---|---|
| 统一图层注册表 | 图层 UI、数据依赖、渲染、图例、帮助和 URL 使用同一配置 |
| 时间窗口 | 支持 1h、6h、24h、48h、7d、all，并真正过滤动态事件 |
| URL 状态 | 恢复 center、zoom、region、layers、timeRange、severity 和 selected event |
| 渐进披露 | 图层和标签按 zoom 展开，全球视图只显示高优先级信号 |
| 空间聚类 | 使用可验证的空间聚类，不在组件中继续堆临时网格算法 |
| 标签冲突控制 | 按事件严重度、时效和选中状态决定标签优先级 |
| 统一详情 | 所有可点击事件进入同一个 Event Inspector 契约 |
| 图层可解释性 | 每层声明 source、freshness、confidence、limitations 和 evidence |
| 渲染降级 | DeckGL/MapLibre 失败时切换真实数据的 SVG/静态地图 |
| 生命周期控制 | 地图离屏、页面隐藏或 reduced motion 时停止不必要渲染 |
| 测试与视觉基线 | 对图层、聚类、Popup、错误和 fallback 建立确定性验证 |

### 3.2 不直接复制的内容

- 不复制 56 个图层的完整目录。
- 不复制与 Polymonitor 当前产品目标无关的 Startup Hubs、Tech HQs、Happiness、Kindness 等变体图层。
- 不把所有军事基地、核设施、电缆、管道和数据中心一次性引入第一版。
- 不复制 WorldMonitor 的后端、用户系统或部署结构来解决单一地图问题。
- 不直接复制 WorldMonitor 源文件；只复用经过本仓库边界适配的设计模式。

### 3.3 内容选择原则

一个数据域只有同时满足以下条件，才能成为地图图层：

1. 具有真实且可声明精度的地理信息。
2. 空间关系能帮助用户判断事件影响。
3. 有时间、来源和 freshness。
4. 点击后能形成证据闭环。
5. 数据缺失或降级时可以被明确表达。

## 4. 内容路线图

### 4.1 World Event Map v1

第一版只做现有服务能够支撑的三个领域。

#### Intel Hotspots

来源基础：

- `breaking-event-radar`
- GDELT
- Wikimedia pageview proxy

展示内容：

- 突发事件
- 新闻速度
- 来源多样性
- 事件严重度和置信度
- 国家或区域影响
- 已有关联市场

现有 `RuntimeBreakingEventRadarItem` 已包含 `country`、`eventTime`、`source`、`velocityScore`、`confidence` 和 `markets`。它应通过 adapter 转为标准 `GeoEvent`，不能直接传给 renderer。

#### Conflict & Unrest

来源基础：

- UCDP
- ACLED
- GDELT 冲突证据
- 自定义冲突 feed

展示内容：

- 国家间冲突
- 非国家冲突
- 单方面暴力
- 抗议、骚乱和军事升级
- 参与方、死亡估计和发生时间

UCDP 已有经纬度。ACLED adapter 必须保留 API 返回的 latitude/longitude；在完成之前，ACLED 只能按 country/region 精度展示，不能伪装成精确点。

#### Sanctions & Country Risk

来源基础：

- OFAC
- Federal Register
- 冲突强度聚合
- 已验证的国家风险指标

展示方式：

- 国家 polygon 填色或轮廓
- 国家级详情
- 制裁新增、解除或升级
- source health 和更新时间

国家级数据不应渲染成首都 marker。

### 4.2 必交付的 v1.1：Natural Hazards 是地图主体，不是天气城市

这一阶段不能继续围绕“哪些城市存在 Polymarket 天气市场”组织地图。默认地图必须先回答：

> 世界上正在发生哪些值得关注的自然灾害，它们在哪里、处于什么阶段、影响多大、证据来自哪里？

只有用户选中某个灾害事件后，Inspector 才回答：

> Polymarket 是否有与该事件在地点、时间和指标上真正相关的天气市场，市场当前如何定价？

这不是“以后有空再做”的候选图层。Phase 9 的完整地图生产交付必须包含本节；如果只交付 v1 foundation，必须明确标记为 foundation release，不能宣称灾害地图已经完成。

地图至少提供五个真实生效的一级图层：

| 图层 | 必须覆盖的事件 | 默认表达 |
|---|---|---|
| `weather-alerts` | 强风暴、龙卷风、飓风/热带气旋、洪水、暴雪等官方警报 | 警报 polygon、风暴轨迹、当前位置和预报锥 |
| `extreme-temperature` | 极端高温、极端低温及官方温度警报 | 警报区域 polygon；气候异常使用独立色标 |
| `earthquakes-volcanoes` | 地震、火山活动，存在可靠来源时增加海啸 | 地震点、火山图标、必要的影响区域 |
| `wildfires` | 命名火灾事件和卫星热异常/火点 | 聚合热点、事件范围和最近观测时间 |
| `climate-anomalies` | 显著温度、降水或其他有基线定义的气象异常 | 网格或区域 anomaly layer |

上述图层可以在 UI 中归入 `Natural Hazards` 图层组，但不能合并成一个无法过滤、无法解释的散点层。

#### 4.2.1 数据源分工

单个 provider 不足以同时提供全球覆盖、官方警报、实时观测和灾害影响。实现时按职责组合来源：

| 来源 | 用途 | 边界 |
|---|---|---|
| [USGS Earthquake GeoJSON](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php) | 地震实时事件、震级、深度、显著度、PAGER alert、海啸标记和详情链接 | 地震 canonical source；摘要 feed 每分钟更新 |
| [NWS Alerts API](https://www.weather.gov/documentation/services-web-alerts) | 美国及其责任区的强风暴、洪水、极端温度等 CAP 警报 | 区域来源，不得标记为全球覆盖；遵守不快于 30 秒的请求建议 |
| [NASA EONET API](https://eonet.gsfc.nasa.gov/how-to-guide) | 全球开放自然事件发现和分类，包括风暴、洪水、火山与野火等 | 适合发现和交叉验证；不自动等同当地官方警报 |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html) | 全球近实时卫星火点/热异常 | 热点不是已确认火灾边界；需要 MAP_KEY、聚合、缓存和 attribution |
| [GDACS API](https://www.gdacs.org/gdacsapi/swagger/index.html) | 全球热带气旋、洪水、地震、火山等事件发现与影响级别交叉验证 | 上线前必须固定实际 endpoint、schema、许可、限流和可用性测试 |
| [NHC GIS](https://www.nhc.noaa.gov/gis/) | NHC 责任海域的热带气旋当前位置、预报路径和预报锥 | 区域 enrichment，不得宣称全球热带气旋覆盖 |
| [NOAA NCEI CDO](https://www.ncdc.noaa.gov/cdo-web/webservices/v2) | 历史气候观测与 anomaly baseline 的候选数据源 | 用于可复现的基线计算，不是实时灾害警报 |

来源策略：

1. 地震优先由 USGS 形成 canonical event，EONET/GDACS 只做补充证据或影响 enrichment。
2. 热带气旋使用全球 discovery source；NHC 只在其覆盖区域补充 track/cone。
3. 强风暴、洪水和极端温度优先采用当地官方 CAP/alert polygon。NWS adapter 只代表美国覆盖；其他地区没有 adapter 时必须显示 coverage gap。
4. 野火将“命名事件”和“卫星热异常”建成两类记录；不能用单个 FIRMS pixel 生成“重大野火”结论。
5. 气候异常必须由确定的观测/预报值与确定的历史基线计算，不能把当前城市温度高低直接称为 anomaly。

任何新增外部数据源都必须先确认：

- 授权、attribution 和再分发限制
- 更新时间、历史范围和覆盖区域
- API rate limit、身份凭据和成本
- 地理精度、geometry 类型和跨日期变更语义
- 失败、缓存、重试和 stale snapshot 策略
- GCP 生产访问路径和健康探针

#### 4.2.2 灾害事件与观测必须分开

后端不得把 provider 的每一条原始记录直接当成地图事件。数据链路必须明确区分：

```text
source-native alert / observation / advisory
  → provider adapter
  → validated HazardObservation
  → dedupe / revision / cancellation
  → canonical HazardEvent
  → severity + lifecycle + coverage
  → map layer
  → selected event
  → evidence-based related weather markets
```

- `HazardObservation` 保留原生 provider id、时间、geometry、原始级别和 revision。
- `HazardEvent` 是供地图选择、聚类和 Inspector 使用的稳定事件。
- 同一飓风的多次 advisory 更新同一个 event，不得在地图上生成一串重复风暴。
- CAP update/cancel、地震 updated time 和火点新观测必须采用各自来源语义处理。
- 跨 provider 合并必须保留全部证据和合并理由；不确定时宁可并存，不做错误合并。

#### 4.2.3 严重度、生命周期和过期规则

`info/watch/warning/critical` 是 Polymonitor 的统一展示级别，不得用一个全局公式生硬套用所有灾害。

优先级：

1. provider 的官方 alert/impact level；
2. provider 的 severity、urgency、certainty 或 PAGER 等影响字段；
3. 只有在缺失官方级别时，才使用版本化、可测试的 per-hazard fallback mapping。

最低规则：

| 灾害 | 严重度依据 | 生命周期/过期 |
|---|---|---|
| 强风暴、洪水、极端温度警报 | CAP/provider 的 severity、urgency、certainty 和 event type | 使用 effective/onset/expires；cancel/update 必须替换旧版本 |
| 热带气旋 | provider alert level、强度、forecast/observed 状态和影响信息 | 按 storm id 合并 advisory；停止发布或明确结束后进入 ended |
| 地震 | PAGER alert、significance、tsunami 标记优先，震级只作 fallback | 保留发生时间和 updated time；由全局 timeRange 控制可见性，不伪造“结束时间” |
| 火山 | 官方活动/警戒状态和更新时间 | 没有新状态不能自动升级；stale 与低严重度是两件事 |
| 野火 | 官方事件级别/影响优先；卫星热点仅表达检测密度、时间和置信信息 | 火点按 observation time 衰减；命名事件使用来源状态 |
| 气候异常 | anomaly 数值、单位、空间范围、baseline period 和算法版本 | 每个窗口独立计算，必须显示数据窗口和生成时间 |

所有 mapping 放在独立 `hazardSeverity.ts`/后端等价模块中，并带：

- provider 与 schema version
- mapping version
- raw level
- normalized level
- mapping reason

不能让图层颜色成为唯一的严重度证据。

#### 4.2.4 地图表达与渐进披露

不同灾害需要不同 renderer，不能全部变成相同大小的发光圆点：

- 强风暴/洪水/温度警报：`PolygonLayer` 表示实际警报范围；无 geometry 时按来源声明的 region/country 精度表达。
- 热带气旋：当前位置使用 icon，历史/预报轨迹使用 `PathLayer`，预报不确定性使用 cone polygon；forecast 与 observed 必须视觉区分。
- 地震：点大小参考震级，颜色参考统一严重度；低 zoom 聚类，高 zoom 显示震级、深度和时间。
- 火山：稳定火山 icon；只有存在可靠 geometry 时才画影响区。
- 野火：全球视图显示聚合热区和命名重大事件，放大后才展开 FIRMS detections；不得默认绘制全球数万原始点。
- 气候异常：使用带单位、范围和 baseline 的连续色标；不得与官方 warning polygon 共用同一 legend。

全球默认态只展示 `warning/critical`、重大命名事件和代表性 cluster。`watch/info` 在用户开启或 zoom 增加后逐步展开。

地图和 legend 必须同时表达：

- event type
- severity
- observed / forecast / warning
- freshness/staleness
- coverage

不得只依赖颜色；icon、线型、填充纹理和文字状态至少再提供一种区分。

#### 4.2.5 灾害 Inspector

点击灾害后，Inspector 的第一屏始终展示现实事件，而不是市场卡片：

通用字段：

- 灾害类型、标题、位置和 geometry precision
- 当前严重度、生命周期和 mapping reason
- occurred/effective/onset/updated/expires
- 来源、原生链接、freshness、coverage 和 limitations

专属字段：

- 风暴/飓风：当前位置、最大风速、移动方向、advisory number、预报轨迹和 cone 限制
- 洪水/温度/强天气警报：影响区域、severity/urgency/certainty、官方说明和有效期
- 地震：震级、深度、地点、significance、PAGER、海啸标记和更新时间
- 火山：活动状态、最近报告时间和来源说明
- 野火：命名事件状态，或 satellite/sensor、观测时间、检测数、置信字段和 FRP（来源提供时）
- 气候异常：实际/预报值、anomaly、单位、基线区间、空间分辨率和算法版本

`Related Weather Markets` 放在 Inspector 下方，允许为空。没有可靠关联时显示“未发现满足证据门槛的相关市场”，而不是推荐相似标题。

#### 4.2.6 天气市场关联规则

城市天气市场不再产生地图 marker。后端 market linker 只有同时完成以下判断，才允许把市场挂到灾害：

1. **类型兼容**：温度市场只能直接关联温度异常/警报；飓风登陆市场关联对应 storm；降雨市场不能仅因附近发生洪水就自动变成直接关联。
2. **空间相交**：市场目标城市/区域与事件 geometry 相交，或在该灾害定义允许的影响半径内。
3. **时间重叠**：市场结算窗口与 event/advisory 的有效或预测窗口重叠。
4. **指标兼容**：温度、降水、风速、登陆位置、命名风暴数量等指标和单位可比较。
5. **证据可解释**：返回空间、时间、类型和指标四类 reason，以及 linker version。

关联等级：

- `direct`：地点、时间、灾害类型和结算指标均匹配，可以默认展示。
- `contextual`：只满足区域或主题关系，默认折叠并明确标记“背景相关”。
- `rejected`：缺少关键字段、时间不重叠或仅标题相似，不进入 UI。

关联结果至少包含：

```ts
interface RelatedHazardMarket {
  marketId: string | number;
  relation: 'direct' | 'contextual';
  matchScore: number;
  matchReasons: Array<{
    dimension: 'hazard-type' | 'space' | 'time' | 'metric';
    evidence: string;
  }>;
  eventWindow?: { start: string; end: string };
  marketWindow?: { start: string; end: string };
  linkerVersion: string;
  matchedAt: string;
}
```

当前 `global_weather_map_service` 继续作为天气详情和候选市场数据来源，但不得决定地图默认城市、事件位置或灾害严重度。

### 4.3 v1.2：Transport Disruptions & Chokepoints

增加：

- 机场关闭和大面积延误
- 航线暂停和区域空域异常
- 港口关闭与拥堵
- AIS 中断
- 战略水道异常
- 影响能源、战争和供应链市场的运输事件

当前 OpenFlights 全量航线属于静态拓扑，不能作为默认主视觉。默认态只允许显示经过预算裁剪、低对比度的 trunk 走廊、移动 route runner 和明确标记为 illustrative 的模拟飞机；完整拓扑继续由 Aviation Lens 显式开启。

Live aircraft 和完整机场/航线详情只能在用户进入 Aviation Lens 后显示。全局默认的 trunk 动画必须受 zoom 数量预算、25 fps 帧率预算、页面可见性、viewport 和 reduced-motion 生命周期约束，且不得压过灾害和风险事件。

### 4.4 后续候选

只有在存在明确用户场景和稳定数据源后再评估：

- Internet outages
- Cyber incidents
- GPS jamming
- Displacement flows
- Strategic waterways
- Critical infrastructure
- Military activity
- Nuclear and radiation watch
- Energy storage、fuel shortages 和 live tankers

不得仅因为 WorldMonitor 有对应图层就进入路线图。

## 5. 当前实现事实与主要债务

### 5.1 当前核心文件

| 文件 | 当前责任 | 问题 |
|---|---|---|
| `webpage/src/App.tsx` | 页面模式、图层按钮、region、zoom、请求和布局 | 地图状态与整个 App 强耦合，2D 与页面状态没有完整贯通 |
| `webpage/src/components/WeatherDeckMap.tsx` | 数据归一化、风险计算、地图生命周期、Deck layers、动画、控件、tooltip 和 inspector | 约 3,179 行，领域、渲染和 UI 生命周期混在一个文件 |
| `webpage/src/config/weatherBasemap.ts` | 主底图和本地 GeoJSON fallback | 仍是 weather 命名，缺少明确 provider 状态机 |
| `webpage/src/components/WeatherMapCityInspector.tsx` | 天气与天气市场详情 | 属于天气业务，不应成为通用 Event Inspector |
| `webpage/src/components/WorldFlatMap.tsx` | SVG 世界地图 | 会从标题猜坐标，并在无法识别时用哈希生成伪坐标 |
| `tests/test_weather_map_browser.py` | 浏览器截图 smoke | 默认跳过，只用 PNG 大小判断是否黑屏 |

### 5.2 必须消除的错误边界

- `App.tsx` 不再维护地图专属 fetch、loading、error、layer toggle 和 camera 细节。
- renderer 不得接收 `RuntimeGlobalWeatherMapPayload`、`RuntimeGeoSanctionsShockPayload` 等 API payload。
- Deck layer factory 不得读 Preact state、localStorage 或 API。
- source adapter 不得访问 MapLibre、DeckGL 或 DOM。
- Event Inspector 不得依赖 DeckGL picking object。
- basemap failure 不得清空已经成功加载的事件数据。
- 单一数据源超时不得遮挡整个地图。
- 3D Globe 与 2D Map 不得通过一个包含大量条件分支的组件共享实现。

### 5.3 必须删除或替换的当前行为

- 删除 2D 地图的 Markets、Oracle、OrderFilled、LOB 和含义不清的 Linked Intel 开关。
- 删除未实现的 Heatmap 和 Risk Density 模式。
- 删除默认全量 Air Routes；保留受预算约束、低对比度的 trunk 走廊与 illustrative 动画作为默认航空上下文。
- 把世界时钟移出地图绘图区。
- 用 `WorldEventMap` 替换 `WeatherInlineMap` 的产品入口。
- `WeatherDeckMap` 在迁移完成后删除，不能长期保留为第二套主实现。
- `WorldFlatMap.resolveGeo()` 的标题猜测和哈希坐标不得进入新实现；fallback 只能渲染标准 `GeoEvent`。

## 6. 目标前端架构

建议目标目录：

```text
webpage/src/features/world-event-map/
  domain/
    types.ts
    validation.ts
    geo.ts
    freshness.ts
  config/
    layerRegistry.ts
    regions.ts
    basemap.ts
  adapters/
    breakingEventAdapter.ts
    geoShockAdapter.ts
    weatherHazardAdapter.ts
    transportDisruptionAdapter.ts
  state/
    mapState.ts
    urlState.ts
    mapReducer.ts
  data/
    useWorldEventData.ts
    sourceStatus.ts
  renderer/
    MapRenderer.ts
    DeckMapRenderer.ts
    SvgMapRenderer.ts
    layerFactories/
      eventPointLayer.ts
      eventClusterLayer.ts
      countryRiskLayer.ts
      routeDisruptionLayer.ts
      labelLayer.ts
  components/
    WorldEventMap.tsx
    MapToolbar.tsx
    LayerPanel.tsx
    MapStatus.tsx
    EventInspector.tsx
    RelatedMarketsPanel.tsx
  index.ts
```

目录可以根据实施调整，但依赖方向必须保持：

```text
domain
  ↑
adapters / state
  ↑
renderer / data
  ↑
components
  ↑
App
```

禁止反向依赖：

- `domain` 不依赖 Preact、API、MapLibre 或 DeckGL。
- `adapters` 不依赖 renderer。
- `renderer` 不导入具体 runtime service payload。
- `App` 只导入 feature 的公开入口。

### 6.1 标准 GeoEvent 契约

示例：

```ts
type GeoEventCategory =
  | 'intel'
  | 'conflict'
  | 'unrest'
  | 'sanctions'
  | 'country-risk'
  | 'weather'
  | 'natural-hazard'
  | 'transport-disruption'
  | 'infrastructure';

type LocationPrecision =
  | 'exact'
  | 'city'
  | 'region'
  | 'country'
  | 'unknown';

type GeoEventGeometry =
  | { type: 'Point'; coordinates: [number, number] }
  | { type: 'Polygon'; coordinates: number[][][] }
  | { type: 'MultiPolygon'; coordinates: number[][][][] }
  | { type: 'LineString'; coordinates: [number, number][] };

interface GeoEventSource {
  provider: string;
  url?: string;
  nativeId?: string;
  observedAt?: string;
  ingestedAt?: string;
  freshness?: 'live' | 'fresh' | 'stale' | 'unknown';
  status?: 'ok' | 'partial' | 'degraded' | 'error';
}

interface GeoEvent {
  id: string;
  category: GeoEventCategory;
  title: string;
  summary?: string;
  severity: 'info' | 'watch' | 'warning' | 'critical';
  occurredAt?: string;
  updatedAt?: string;
  expiresAt?: string;
  geometry?: GeoEventGeometry;
  locationPrecision: LocationPrecision;
  countryCode?: string;
  regionCode?: string;
  locationLabel?: string;
  confidence?: number;
  sources: GeoEventSource[];
  limitations: string[];
  relatedMarketIds: Array<string | number>;
  properties: Record<string, unknown>;
}
```

约束：

- `id` 必须稳定，优先使用 `provider + nativeId`。
- 所有时间使用 ISO 8601 UTC。
- longitude 必须在 `[-180, 180]`，latitude 必须在 `[-90, 90]`。
- `locationPrecision=unknown` 时不得生成 marker。
- country 精度优先使用 country polygon；不得伪造 exact point。
- `confidence` 必须有定义来源，不能用视觉随机数。
- `limitations` 不能为空时必须进入 Inspector。
- source status 与 event severity 是两个独立概念。

#### 6.1.1 HazardEvent 扩展契约

自然灾害不能把所有专属字段塞进不受约束的 `properties`。在 `GeoEvent` 之上增加可判别的扩展：

```ts
type HazardKind =
  | 'severe-storm'
  | 'tornado'
  | 'tropical-cyclone'
  | 'flood'
  | 'extreme-heat'
  | 'extreme-cold'
  | 'earthquake'
  | 'volcano'
  | 'tsunami'
  | 'wildfire'
  | 'fire-detection'
  | 'temperature-anomaly'
  | 'precipitation-anomaly'
  | 'other-weather-anomaly';

type HazardLifecycle =
  | 'forecast'
  | 'watch'
  | 'active'
  | 'observed'
  | 'contained'
  | 'ended'
  | 'unknown';

interface HazardCoverage {
  scope: 'global' | 'regional' | 'country' | 'provider-area';
  label: string;
  isComplete: boolean;
  gaps: string[];
}

interface HazardEvent extends GeoEvent {
  category: 'weather' | 'natural-hazard';
  hazardKind: HazardKind;
  lifecycle: HazardLifecycle;
  effectiveAt?: string;
  onsetAt?: string;
  endedAt?: string;
  coverage: HazardCoverage;
  severityEvidence: {
    provider: string;
    rawLevel?: string;
    mappingVersion: string;
    reason: string;
  };
  revision: {
    nativeEventId: string;
    advisoryId?: string;
    revisionAt?: string;
    replaces?: string[];
    cancelled?: boolean;
  };
  metrics:
    | {
        kind: 'earthquake';
        magnitude: number;
        depthKm?: number;
        significance?: number;
        pagerAlert?: string;
        tsunami?: boolean;
      }
    | {
        kind: 'tropical-cyclone';
        maximumWind?: { value: number; unit: 'kt' | 'km/h' | 'm/s' };
        pressureHpa?: number;
        categoryLabel?: string;
        advisoryNumber?: string;
      }
    | {
        kind: 'weather-alert';
        urgency?: string;
        certainty?: string;
        providerSeverity?: string;
        instruction?: string;
      }
    | {
        kind: 'wildfire';
        detectionCount?: number;
        fireRadiativePowerMw?: number;
        sensor?: string;
        satellite?: string;
        confidenceLabel?: string;
      }
    | {
        kind: 'climate-anomaly';
        variable: string;
        value: number;
        anomaly: number;
        unit: string;
        baselinePeriod: string;
        calculationVersion: string;
      }
    | {
        kind: 'volcano-or-other';
        statusLabel?: string;
      };
}
```

约束：

- `HazardEvent.metrics.kind` 必须与 `hazardKind` 兼容，并由 runtime validator 验证。
- forecast track、cone 和 observed position 可作为同一 event 的命名 geometries 返回，不能丢进含义不明的坐标数组。
- `coverage.isComplete=false` 不是请求失败；它表示来源天生只覆盖部分区域，必须进入 UI 说明。
- `fire-detection` 是观测，不得在 adapter 中静默升级为 `wildfire`。
- derived climate anomaly 必须带 baseline 和 calculation version，否则拒绝进入图层。

### 6.2 图层注册表

所有图层必须由 registry 驱动，禁止在 `App.tsx` 和 renderer 中各维护一份名称或开关。

示例：

```ts
interface MapLayerDefinition {
  id: string;
  label: string;
  categories: GeoEventCategory[];
  sourceKeys: string[];
  defaultEnabled: boolean;
  minZoom: number;
  labelMinZoom: number;
  cluster: boolean;
  timeFilter: boolean;
  legend: Array<{ label: string; color: string }>;
  explanation: {
    purpose: string;
    sources: string[];
    freshness: string;
    confidence: string;
    limitations: string[];
  };
}
```

Layer Panel、URL serializer、renderer、source status 和测试都从同一 registry 读取。

### 6.3 统一 MapState

```ts
interface WorldEventMapState {
  center: { lon: number; lat: number };
  zoom: number;
  region: string;
  activeLayerIds: string[];
  timeRange: '1h' | '6h' | '24h' | '48h' | '7d' | 'all';
  severities: Array<GeoEvent['severity']>;
  selectedEventId: string | null;
  hoveredEventId: string | null;
  basemapTheme: string;
}
```

规则：

- MapLibre camera 与 state 双向同步，避免循环更新。
- URL 状态优先于 localStorage。
- 无 URL 参数时才使用 localStorage。
- 未知或过期 URL 参数必须安全忽略。
- Copy Link 必须序列化当前 MapState。
- reset 只重置地图，不得顺带切换市场、面板或工作区。

### 6.4 Renderer 接口

Preact 组件只负责挂载和传递 canonical state。MapLibre/DeckGL 的命令式生命周期进入 renderer。

```ts
interface MapRenderer {
  mount(container: HTMLElement, callbacks: MapRendererCallbacks): Promise<void>;
  setState(state: WorldEventMapState): void;
  setEvents(eventsByLayer: Record<string, GeoEvent[]>): void;
  resize(): void;
  pause(): void;
  resume(): void;
  destroy(): void;
}
```

`DeckMapRenderer` 与 `SvgMapRenderer` 实现同一接口。3D Globe 可以以后增加独立 adapter，但不能让 2D renderer 出现大量 `if (viewMode === '3d')`。

### 6.5 纯 layer factory

每个 Deck layer factory：

- 输入 canonical events、viewport 和 selection。
- 输出 DeckGL layer。
- 不读取 DOM。
- 不发请求。
- 不更新 Preact state。
- 不创建长期 timer。
- 使用稳定 id。
- 允许确定性单元测试。

## 7. 数据层解耦

### 7.1 第一阶段复用现有 runtime payload

为了避免前后端同时大重写，第一阶段由前端 adapters 转换：

```text
existing runtime payload
  → source-specific adapter
  → validated GeoEvent[]
  → layer registry
  → renderer
```

初始 adapters：

- `breakingEventAdapter`
- `geoShockAdapter`
- `weatherHazardAdapter`，在真正 hazard 数据存在后启用
- `transportDisruptionAdapter`，只处理异常，不处理全量静态航线

### 7.2 后端演进

等 GeoEvent contract 经 v1 验证稳定后，再考虑增加统一的 `/runtime/world-event-map` 聚合接口。

如果增加该接口：

- 通过现有 runtime panel registry 注册。
- 保持旧 `/runtime/...` 接口兼容。
- 后端返回 canonical contract，不让前端重复推断字段。
- 各来源独立返回 source state。
- 部分来源失败时仍返回其余成功事件。
- 响应明确 `generatedAt`、`isPartial`、`errors` 和数据版本。

### 7.3 关联市场

地图 adapter 不负责模糊匹配市场。

关联市场由后端 evidence/linking service 产生，并返回：

- `marketId`
- `matchScore`
- `matchReasons`
- `matchedAt`
- `linkerVersion`

没有证据的关系不进入 Event Inspector。地图不得仅靠标题包含相同国家名就声称关联。

### 7.4 Natural Hazards 后端模块

灾害接入不能堆进 `global_weather_map_service.py`，也不能由前端分别请求六个外部 API。建议边界：

```text
scripts/api/services/natural_hazards/
  contracts.py
  service.py
  source_health.py
  normalize.py
  dedupe.py
  severity.py
  snapshots.py
  market_linker.py
  providers/
    usgs.py
    nws.py
    eonet.py
    firms.py
    gdacs.py
    nhc.py
    ncei.py
```

责任：

- `providers/*`：只负责认证、请求、provider schema 解析和原生错误映射。
- `normalize`：产生 validated `HazardObservation`，不做市场匹配。
- `dedupe`：处理 stable id、revision、cancel、同源更新和跨源合并证据。
- `severity`：保存版本化 per-provider/per-hazard mapping。
- `snapshots`：保留 last-known-good、generatedAt、source freshness 和 schema version。
- `market_linker`：执行 4.2.6 的类型、空间、时间和指标匹配。
- `service`：聚合成功来源，返回 partial result，不了解 MapLibre/DeckGL。

前端只消费 Polymonitor 同源 runtime endpoint。外部 provider 的 key、rate limit、重试和 schema 漂移全部留在后端。

### 7.5 灾害 endpoint 与 partial response

第一版可以按图层分 endpoint，也可以使用统一 endpoint；无论选择哪种形式，都必须返回相同 envelope：

```ts
interface HazardMapResponse {
  schemaVersion: string;
  generatedAt: string;
  events: HazardEvent[];
  sources: Array<{
    key: string;
    status: 'ok' | 'partial' | 'degraded' | 'error';
    coverage: HazardCoverage;
    fetchedAt?: string;
    dataUpdatedAt?: string;
    staleAfter?: string;
    lastSuccessAt?: string;
    errorCode?: string;
  }>;
  isPartial: boolean;
}
```

实现要求：

- 每个 provider 独立 timeout、retry budget、circuit state 和 cache key。
- USGS、NWS、FIRMS 等不同更新频率不得共用一个全局 TTL。
- 轮询频率必须尊重官方建议；例如 NWS 不得快于官方建议的 30 秒。
- provider 失败时返回其他成功事件和失败来源状态，不能清空整张灾害地图。
- stale snapshot 可以继续展示，但必须显式标记 stale 和 last success。
- API key 不得进入浏览器 bundle、日志、响应或文档示例。
- 保存 source-native fixture 供 contract test，生产日志不保存无界完整 payload。

### 7.6 去重与事件身份

事件 identity 优先使用来源稳定 id，不使用标题或浮点坐标拼接：

```text
canonical id = hazard kind + canonical provider + native event id
```

跨来源合并至少需要：

- hazard kind 兼容；
- 时间窗口重叠；
- geometry 相交或距离低于该灾害的版本化阈值；
- 名称/风暴编号/官方 id 等额外证据；
- 记录 `mergedSourceIds` 和 merge reason。

热带气旋应以 basin + storm identifier 等来源稳定身份为主；地震以 USGS event id 为主；CAP alert 按 identifier/references 处理更新与取消；FIRMS detections 先按时空窗口聚合，不为每个 pixel 创建永久事件。

## 8. 鲁棒性修复契约

### 8.1 Basemap 状态机

必须建立显式状态：

```text
idle
  → initializing
  → primary-ready
  → local-fallback-ready
  → renderer-fallback-ready
  → failed
```

要求：

- 主远程 basemap 有可配置超时。
- fallback 只能执行一次，避免 `setStyle()` 错误循环。
- 本地 `/map-data/world-countries.geojson` 必须有独立 smoke test。
- basemap 错误不得清空 Deck events。
- style reload 后重新安装必要的 country sources、layers 和 overlay。
- UI 明确显示当前是 primary、local fallback 还是 SVG fallback。
- attribution 必须保留。
- 不增加第二个远程 fallback 来替代本地 fallback。

### 8.2 WebGL 和 context loss

- mount 前检测 WebGL2。
- 软件光栅、context 创建失败或 renderer 初始化异常时进入 SVG fallback。
- 监听 `webglcontextlost` 和 `webglcontextrestored`。
- context lost 时停止 RAF、释放 Deck overlay 并显示降级状态。
- 恢复策略必须有最大尝试次数；不能无限重建 context。
- fallback 地图继续允许选择真实事件。

### 8.3 请求、竞态和 stale data

- 所有地图专属请求支持 `AbortController`。
- 切换过滤条件或卸载组件后，旧响应不得覆盖新状态。
- 使用 request sequence 或 generation id 丢弃过期响应。
- 刷新失败时保留上一份成功数据并标记 stale。
- 单个 source error 只影响该 source 或 layer。
- 不在重试开始时清空已显示事件。
- retry 使用有上限的退避和抖动。
- 页面不得因为天气超时而遮挡冲突和制裁图层。

### 8.4 数据验证

adapter 输出进入 renderer 前必须经过 validation：

- 非有限数、越界坐标和空 geometry 被拒绝。
- 反经线 LineString 必须切分或标准化。
- Polygon ring 必须闭合。
- 缺少稳定 id 的事件不得进入长期 selection state。
- 重复事件按 provider/native id 去重。
- 时间无法解析时标记 unknown，不用当前时间替代原始发生时间。
- 事件 expiry 与 time filter 分开处理。
- country code alias 通过单一映射模块标准化。

### 8.5 地图生命周期与资源清理

`destroy()` 必须清理：

- MapLibre listeners
- Deck overlay
- MapLibre instance
- `requestAnimationFrame`
- `setTimeout` / `setInterval`
- `ResizeObserver`
- `IntersectionObserver`
- `document.visibilitychange`
- media query listeners
- WebGL context listeners
- pending fetch 和 abort controller

重复 mount/unmount 不得累积 listener、RAF 或 WebGL context。

### 8.6 动画和后台暂停

- 没有动态层时不得存在持续 RAF。
- `document.hidden` 时暂停动画。
- 地图不在 viewport 时暂停动画。
- `prefers-reduced-motion` 时禁用持续运动，只保留状态变化。
- 航空或运输动画必须有帧率预算，不能默认按显示器刷新率持续更新所有对象。
- 数据刷新与动画 tick 分开；不能每帧重新归一化完整 payload。
- 返回可见状态后批量应用积压更新。

### 8.7 错误表达

MapStatus 必须区分：

- basemap 状态
- renderer 状态
- 每个数据源状态
- 每个图层事件数
- freshness
- fallback mode

不得只显示一个覆盖整张地图的通用错误条。

## 9. 性能与视觉密度

### 9.1 全球视图预算

全球 zoom 默认只展示：

- critical 和 warning 事件
- 高置信度 Intel Hotspots
- 聚类后的 Conflict & Unrest
- 国家风险 polygon
- 被选中的事件

普通点、标签、完整路线和低优先级事件随 zoom 展开。

### 9.2 聚类与可见性

- 点事件采用 Supercluster 或同等级稳定方案。
- 每个图层声明 cluster radius、minZoom 和 labelMinZoom。
- renderer 只构建当前 viewport 与必要 buffer 内的数据。
- 聚类点击使用 fitBounds 或 expansion zoom。
- 选中事件始终可以显示，不受普通预算裁剪。

### 9.3 数据与对象稳定性

- adapter 只在 payload 实际变化时重新运行。
- canonical event 尽量保持对象引用稳定。
- layer data 不因 tooltip 或 hover 状态整体重建。
- tooltip 更新使用 RAF 合并，但不能启动持续循环。
- geometry 简化与预计算放在 adapter 或 worker，不放在每帧逻辑。

### 9.4 视觉层级

默认优先级：

```text
selected event
  > critical event
  > warning event
  > active cluster
  > country risk
  > watch/info event
  > static context
```

约束：

- 航线不得成为全球视图最高对比度元素。
- 风险 polygon、路径、点和标签不能同时全部满强度。
- hover 只预览，click 打开持久 Inspector。
- 颜色不是唯一编码；同时使用形状、图标、边框或文字。
- 世界时钟、市场状态和全局宣传信息不得覆盖地图核心绘图区。

## 10. Event Inspector

统一 Inspector 至少展示：

- 标题、类别和严重度
- 发生时间、更新时间和 freshness
- 位置名称与 `locationPrecision`
- 来源列表和外部链接
- confidence 与 limitations
- 参与方、死亡估计或类别专属指标
- 相关国家和区域
- 相关 Polymarket 市场

相关市场区域展示：

- 标题与当前概率
- 1h/24h 变化
- 成交异动
- spread / depth / LOB freshness
- Oracle 状态
- `Open Market Workspace`

这些市场数据只在用户选中事件后按需获取；不得成为 renderer 依赖。

## 11. 可访问性

- 所有地图功能都必须有非地图列表入口。
- Layer Panel、时间筛选和严重度筛选可用键盘操作。
- 点击事件后焦点移动到 Inspector 标题；关闭后返回触发对象或地图容器。
- Escape 关闭 Inspector。
- Tooltip 不是唯一信息入口。
- MapStatus 使用适当的 live region，但避免高频播报。
- 图例为屏幕阅读器提供等价文字，不使用单纯 `aria-hidden`。
- reduced motion 生效。
- 地图 canvas 有明确 accessible name 和操作说明。
- 移动端使用可关闭的 bottom sheet，不能依赖 hover。

完成键盘和屏幕阅读器验证前，不得宣称完整 WCAG 合规。

## 12. 可观测性

开发和生产诊断至少暴露：

- renderer kind：deck / svg
- basemap mode：primary / local fallback
- WebGL support 和 context loss 次数
- 每层输入、通过验证、过滤、聚类后和可见数量
- 每个 source 的 status、last success 和 freshness
- 请求失败、超时和 abort 计数
- 当前是否 paused
- 活跃 RAF 数量
- 最近一次完整 render 时间

这些指标可以先进入开发日志和 debug snapshot，再接入正式 telemetry。

日志不得包含用户凭据、API key、完整私有 payload 或敏感地址数据。

## 13. 测试策略

### 13.1 当前测试缺口

当前前端没有 `test` script，也没有 Vitest 或 Playwright 依赖。`tests/test_weather_map_browser.py` 默认跳过，并只验证 screenshot 文件大于 25 KB，不能证明：

- 底图真实可见。
- 图层开关生效。
- Heatmap 等模式真实存在。
- fallback 正确。
- click/Inspector 工作。
- URL 可以恢复状态。
- 没有 console error 或资源泄漏。

### 13.2 测试基础建设

在进入大规模拆分前，增加并锁定：

- 前端单元测试 runner。
- Preact component test 支持。
- Playwright 地图 E2E。
- 确定性的 map harness 和 fixtures。
- 视觉基线目录。

建议 scripts：

```json
{
  "test": "...",
  "test:map": "...",
  "e2e:map": "..."
}
```

具体工具和命令在落地时写入 `webpage/package.json` 和 `docs/development.md`，不得只写在私人操作记录中。

### 13.3 必须具备的单元测试

- GeoEvent coordinate validation
- country/region/exact precision 规则
- UCDP、ACLED、GDELT、OFAC adapters
- deduplication 和 stable id
- time range filtering
- severity filtering
- URL parse/serialize round trip
- anti-meridian path split
- layer registry coverage
- fallback state machine
- stale response race suppression
- source status aggregation
- USGS GeoJSON、NWS CAP、EONET、FIRMS 等 source-native fixture contract
- CAP update/cancel 和 cyclone advisory revision
- earthquake id/update、FIRMS 时空聚合和跨源 dedupe
- per-hazard severity mapping 与 mapping reason
- forecast track/cone 和跨日界线 geometry
- fire detection 不得自动升级为 confirmed wildfire
- climate anomaly 缺少 baseline/version 时拒绝
- hazard-to-market 类型、空间、时间和指标匹配
- 仅标题相似、时间不重叠和地点不匹配的 false-positive rejection

### 13.4 必须具备的组件与 E2E

- 地图主状态正常加载
- 每个 layer toggle 真正改变可见图层
- 时间窗口真正改变事件数
- cluster 展开
- event click 打开 Inspector
- Escape 和焦点恢复
- Copy Link 后新页面恢复相同状态
- 一个 source 超时，其余图层继续显示
- 主 basemap 被阻断时进入本地 fallback
- WebGL 不可用时进入 SVG fallback
- 页面隐藏或地图离屏时 RAF 停止
- reduced motion 下动画停止
- 移动端 bottom sheet
- 五个 Natural Hazards 一级图层都由真实 fixture 驱动并可独立切换
- 选中灾害先出现事件证据，再按需加载 Related Weather Markets
- 没有关联市场时正常显示空状态，不生成推荐
- NWS 区域来源不会让全球其他区域误显示为“无灾害”
- FIRMS 大量 detections 在全球视图聚合，放大后才展开
- provider revision 后 selection 保持在同一个 canonical event

### 13.5 视觉基线

至少覆盖：

- Global 默认态
- 三个 v1 图层单独开启
- cluster zoom
- selected event
- country risk
- partial data
- primary basemap failure
- SVG fallback
- empty but healthy
- all sources failed
- desktop 和 mobile
- 强风暴 polygon 与 cyclone track/cone
- 极端温度 warning 和 climate anomaly 不同 legend
- 地震 cluster 与 selected earthquake
- wildfire aggregate 与 detection drill-down
- hazard selected with direct、contextual 和 no-related-market 三种状态

视觉 fixture 必须固定时间、数据和 viewport，不能使用生产实时数据作为 golden。

## 14. 分阶段实施

### Phase 0：建立安全基线

- 保存当前生产与本地 2D 地图截图。
- 记录当前 basemap、数据源和浏览器 console 状态。
- 为现有真实能力增加最小 characterization tests。
- 标记地图相关工作树状态，避免覆盖无关本地改动。
- 禁止先做大规模文件移动。

验收：

- 能明确列出当前真实工作的交互。
- 有可以比较重构前后的固定 fixture。

### Phase 1：纠正产品表面

- 删除五个伪 Polymarket 图层开关。
- 删除 Heatmap 和 Risk Density。
- 默认只开启受预算约束、低对比度的 trunk 航空上下文；完整 Air Routes 与 live aircraft 继续由 Aviation Lens 显式开启。
- 移除世界时钟覆盖。
- 页面命名改为 World Event Map。
- 错误状态按 source 拆分。

验收：

- 页面上不存在无效控件。
- 天气失败不再遮挡冲突数据和 basemap。

### Phase 2：引入 domain、adapters 和 registry

- 增加 GeoEvent contract 和 validation。
- 增加三个 v1 adapters。
- 增加 layer registry。
- 让旧 renderer 先消费 canonical events。
- 为 adapters 和 registry 补单元测试。

验收：

- renderer 不再接收 runtime API payload。
- 未知位置和无效坐标不会进入地图。

### Phase 3：抽离 MapState 和 URL

- 建立 reducer/controller。
- camera、region、layers、time 和 selection 进入统一 state。
- URL 与 localStorage 实现明确优先级。
- 修复 zoom、region、reset 和 Copy Link。

验收：

- App 不再拥有地图专属细节状态。
- URL round trip 测试通过。

### Phase 4：拆 Renderer

- 把 MapLibre/DeckGL 生命周期移入 `DeckMapRenderer`。
- 把 layer creation 拆为纯 factories。
- 抽离 tooltip、selection 和 country risk 渲染。
- 删除 WeatherDeckMap 内已迁移代码。

验收：

- Preact 组件只负责组合和用户界面。
- renderer 可以被 harness 独立挂载和销毁。

### Phase 5：交付 Natural Hazards 数据产品

按可独立验收的 vertical slice 接入，不先画五个空开关：

1. `earthquakes-volcanoes`
   - 接入 USGS 地震 canonical feed。
   - 接入 EONET/GDACS 火山 discovery，并明确来源覆盖。
   - 完成地震 cluster、severity、time filter 和专属 Inspector 字段。
2. `weather-alerts`
   - 接入 NWS CAP 作为首个区域官方 alert adapter。
   - 接入全球风暴/洪水 discovery source。
   - 完成警报 polygon、revision/cancel、cyclone track/cone 和 coverage gap。
3. `wildfires`
   - 接入 EONET 命名事件和 FIRMS detections。
   - 完成时空聚合、zoom disclosure、sensor/freshness 和“热异常不等于火灾”说明。
4. `extreme-temperature` 与 `climate-anomalies`
   - 官方温度警报进入前者。
   - 建立有 baseline、单位、窗口和算法版本的 anomaly pipeline 后才启用后者。
5. 对每个已选灾害运行 weather market linker；只返回 direct/contextual evidence。

验收：

- 地图默认主体是现实灾害，不是天气市场城市。
- 用户能看到强风暴、飓风、洪水、极端温度、地震、火山、野火和重大气象异常；某区域未覆盖时显示 coverage gap，不伪装成“没有事件”。
- 五个一级图层只有在存在真实数据、空态、source health 和测试后才显示为可用。
- 同一事件更新不会重复，取消/过期不会继续显示为 active。
- 单个灾害 provider 失败不影响其他灾害图层。

### Phase 6：统一 Inspector 与关联市场

- 增加 Event Inspector。
- 增加 source/freshness/confidence/limitations。
- 增加 Related Markets 按需加载。
- 航空、冲突或天气专属字段使用 section adapter，而不是独立 Popup 系统。
- 灾害事件信息位于天气市场之前。
- market linker 返回 direct/contextual、四维 evidence 和 linker version。

验收：

- 所有可点击对象都有持久详情。
- 航线、枢纽或事件不再在 click handler 中直接 `return`。
- 不存在“因为标题或城市相似就关联市场”的路径。
- 灾害没有相关市场时 Inspector 仍然完整可用。

### Phase 7：鲁棒性与 fallback

- basemap 状态机
- WebGL 检测/context loss
- SVG renderer
- abort/race suppression
- stale data preservation
- 完整 lifecycle cleanup

验收：

- 阻断外部瓦片、禁用 WebGL、超时一个 source 时地图仍可用。
- 无 unhandled promise rejection。

### Phase 8：性能、可访问性和视觉回归

- Supercluster 和 zoom disclosure
- visibility pause
- reduced motion
- keyboard/Inspector focus
- visual golden
- mount/unmount leak test

验收：

- 地图隐藏时无持续 RAF。
- 2,000 个事件 fixture 可以平移、缩放和选择。
- 桌面和移动核心流程通过 E2E。

### Phase 9：生产交付

- 只从已提交、已推送的精确 commit 构建。
- 本地 production build 和测试通过。
- 部署到 GCP 后检查静态资源、API、source health 和地图 fallback。
- 用生产 URL 做桌面和移动 smoke。
- 对比预先保存的截图。
- 记录 commit、部署时间和验证结果。

验收：

- GitHub、GCP 运行 commit 和本地验证 commit 一致。
- 生产刷新后没有旧 bundle 或 service-worker 漂移。

## 15. 每个变更的工作纪律

### 修改前

1. 检查 `git status`，保护无关脏工作树。
2. 明确本次只属于哪个 phase。
3. 列出将修改的文件和不修改的边界。
4. 读取现有测试和可复用模块。
5. 如果涉及生产，先检查当前生产链路，不直接改服务器配置。

### 修改中

- 产品行为变化与纯文件拆分尽量分开。
- 每次只迁移一类责任。
- 保持旧入口兼容，直到新入口测试通过。
- 不以“顺便清理”为理由修改无关模块。
- 不复制第二套 helper、类型或 registry。
- 不把临时 seed 当作 live。

### 修改后

至少执行：

```bash
cd webpage && npm run build
pytest -q tests/test_geo_sanctions_shock.py \
  tests/test_global_transport_shipping_panel.py \
  tests/test_weather_panels.py
```

如果已经增加地图单元/E2E scripts，还必须执行相应命令。

交付报告必须说明：

- 修改了什么产品行为。
- 哪些模块被拆分。
- 哪些失败模式已覆盖。
- 执行了哪些测试。
- 哪些测试未执行以及原因。
- 是否修改、提交、推送或部署。
- 生产验证看到的真实状态。

## 16. 禁止事项

- 禁止在 `App.tsx` 增加新的地图数据源专属 `useState` 和 fetch。
- 禁止继续扩大 `WeatherDeckMap.tsx`。
- 禁止把 renderer 变成第二个 API client。
- 禁止新增看起来可用但没有实现的 tab、模式和开关。
- 禁止伪造经纬度、来源、freshness、confidence 或关联市场。
- 禁止因为一个 source 失败而清空所有图层。
- 禁止依赖持续 RAF 绘制静态状态。
- 禁止只以截图文件大小判断地图成功。
- 禁止在没有 fallback 测试时更换 basemap provider。
- 禁止在未核对工作树、commit 和生产状态时直接推送或部署。

## 17. Definition of Done

World Event Map v1 只有同时满足以下条件才算完成：

- 地图只展示有真实地理依据的现实事件。
- Intel、Conflict/Unrest、Sanctions/Country Risk 三个图层真实生效。
- 不存在无效图层开关或伪视图模式。
- 统一 MapState 控制 camera、region、layers、time、severity 和 selection。
- URL 可以完整恢复地图分析现场。
- 所有事件进入统一 Inspector。
- 相关 Polymarket 市场只在事件详情中出现。
- 主 basemap 失败时本地 fallback 可用。
- WebGL 不可用时 SVG fallback 可用。
- 单个 source 超时不会破坏其他图层。
- 页面隐藏和地图离屏时停止持续动画。
- unknown location 不进入地图。
- 单元、E2E、视觉和生产 smoke 达到本文要求。
- GitHub 与 GCP 部署 commit 可追溯且一致。

Natural Hazards v1.1 只有同时满足以下条件才算完成：

- `weather-alerts` 真实展示强风暴、飓风/热带气旋和洪水事件。
- `extreme-temperature` 真实展示官方极端高温/低温警报。
- `earthquakes-volcanoes` 真实展示地震和火山事件。
- `wildfires` 同时区分命名火灾事件与卫星热异常。
- `climate-anomalies` 只展示有单位、时间窗口、baseline 和算法版本的重大气象异常。
- 城市天气市场不再作为地图默认数据或空间覆盖代理。
- 每个图层都有真实来源、coverage、freshness、空态、错误态和 limitations。
- storm advisory、CAP update/cancel、earthquake update 和 fire observations 能正确更新同一事件。
- 全球视图使用聚类与渐进披露，不全量绘制火点、警报标签或风暴轨迹。
- 点击事件先展示灾害证据；天气市场仅作为 `direct/contextual` 关联显示。
- 无市场关联、区域未覆盖、来源 stale 和来源失败四种状态不会被混为“无数据”。
- 本文列出的 source contract、severity、dedupe、market linker、E2E 和视觉测试通过。

最终产品判断标准：

> WorldMonitor 告诉用户世界发生了什么；Polymonitor 的 World Event Map 在保留同等地图可信度的基础上，进一步告诉用户预测市场如何定价这件事。
