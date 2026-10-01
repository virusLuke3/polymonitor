# World Event Map 对齐与验收

## 第三轮恢复：2026-10-01

依据本轮 `POLYMONITOR_MAP_VISUAL_RECOVERY_V3/CODEX_GUIDE.md`、两张原图和 46 项 acceptance cases 实施。实际基线为 `6510c776` 加任务开始的工作区；177 个原有修改的 SHA 清单在 `webpage/artifacts/map-visual-recovery-v3/worktree-before.json`，未回退、代为提交或覆盖。对照本地 WorldMonitor `4691d9213` 的实际 viewport、稳定底图/图层、刷新及 context 生命周期；继续使用 MapLibre、deck.gl、Protomaps 和现有 feature，不复制它的全局 AppContext 或新建并行加载框架。

| 需求 | 实现归属 | 当前验证与证据 |
| --- | --- | --- |
| 默认构图、概览、重点保护、唯一计数 | `WorldEventMap.tsx` 统一实际高度；state/URL 恢复；`eventDisclosure`、`eventClusters`、`screenClusters` 在两级聚合前分离重要记录；普通簇弱化 | 1536×1000 默认高度 501→730 CSS px；2048×567 紧凑与 390×844 小屏另测。`before/`、`after/default-*`；普通/重点身份守恒；多重点高缩放成员测试 |
| 海陆、语言、控件和剩余字体 | `weatherBasemap.ts`、map `styles.css`、aviation scene/layers；移除旧固定高度及被替代声明 | 主/本地/SVG 共用固定海陆 token；保留比例地名；航空和正文 Noto，技术 ID 仍等宽。中英同镜头原始快照 `before-real/`→`after/real-*`，未改事件时间和等级 |
| 航空真实范围和完整入口 | renderer viewport callback、`useAviationViewport`、既有 transport adapter 与 AviationLens；API shared bounded executor | resize 500→800、日期线两半、边缘点、迟到结果、关闭/空/部分/失败/过期/恢复；返回、有效和视野内数量分开，不用 All 声称全球完整。`after/aviation-*.json`、hook 专项 |
| 渲染恢复 | 既有 WorldEventMap / DeckMapRenderer 生命周期、validated revision 隔离 | 小屏真实 GPU；慢下载迟到恢复；context 原位恢复与 SVG 晋级；每 5 分钟最多两次重建、稳定 60 秒才开始新 episode；一层坏数据不毁掉全图。`context-cycle`、`recovery-episodes`、`layer-cycle`、`slow-download-*` |
| 底图局部失败 | 既有 MapLibre source / archive protocol 清理与有限重试 | 指定 PMTiles 叶 Range 503：同一个 GPU canvas 显示部分底图提示→解除→真实 206 恢复；全 Range 故障：本地几何→原主底图恢复。`after/leaf-cycle.json`、`range-cycle.json` |
| 核心 NWS 和可选几何 | `natural_hazards/providers/nws.py`、service、snapshots、RuntimeResources、SnapshotStore 原模块 | 目录和 queue/HTTP/lock 共用绝对 deadline；目录不等待可选几何；每进程最多 6 个 zone worker/12 个 pending；source 与官方 zone 跨进程 singleflight/cache；同 CAP revision 才合并几何。`backend-final.log` 及三个 NWS 浏览器完整周期 |
| 独立来源和雷达恢复 | `useNaturalHazards`、hazard cache、`useWeatherRadar`、DeckMapRenderer 双 bank | 认证/限流保留真实状态与成功时间；轮询暂停时 stale 也按预算过期。真实雷达新帧失败保留旧帧及 coverage，解除后原子提交新帧，关闭后无请求。`nws-retention-cycle`、`auth-throttle-cycle`、真实 `map-alignment/v3-radar` |
| 性能/资源 | 持久 Supercluster、稳定航空层；语义相同来源发布不重建灾害索引 | 750+180 与 5000+1000 同浏览器真实矢量资源、30 秒连续交互和完整成员检查；50 次图层/来源/详情循环、卸载请求停止。原阈值 RAF P95≤32 ms / hover≤100 ms / 本地详情≤150 ms 未放宽 |
| 发布链 | 既有 `verify-live-map.mjs` 和 GCP release 流程 | 生产验收使用正常 SW、真实 API/瓦片；非相邻 Range、If-Range/ETag、两个远距矢量瓦片；旧页面延迟 import、新页面及前后端版本单列，不以本地预检替代 |

证据入口及执行矩阵：`webpage/artifacts/map-visual-recovery-v3/cases.json`。每项记录源码、具体测试和 screenshot/trace/运行记录；中间失败日志保留。实时生产验证和本地受控故障注入分别标识。固定真实输入的 `real-input/receipt.json` 保存 URL、原始时间和 SHA；它验证同数据视觉，不声称当天所有来源健康。

第三轮密集对照：750+180 与 5000+1000 的拖动 P95 均为 24 ms（旧版 26/27），hover P95 为 73/80 ms（旧版 70/75），本地详情为 93/124 ms（旧版 74/136）。索引 1→1，拖动没有全量展开叶子；普通记录和航空入口一起验收。各项仍满足原 32/100/150 ms 阈值，不将微小差异解释为所有操作都更快。连续 trace 在 `map-polish-round2/after-v3-final/`。

已执行前端单元 **216 passed / 1 原有 opt-in skipped**；后端相关 **94 passed**；类型/边界/locale/build 与 lazy bundle 检查通过。最终浏览器、性能及发布状态以逐项矩阵和生产 receipt 为准，不把未执行、跳过或外部不可用记 PASS。原生 Chrome 125% tab zoom、DPR 1/2、键盘/touch/reduced-motion 已独立验证；viewport 模拟项明确注明，不冒充真实 iOS/Android 设备。

复现（Node 22.23.3；硬件 WebGL 测试需要能提供 GPU 的 Chrome）：

```bash
cd webpage
npm run test:unit
npm run build
POLYMONITOR_E2E_PREVIEW=1 POLYMONITOR_E2E_HARDWARE_WEBGL=1 MAP_RECOVERY_PHASE=after npx playwright test e2e/map-recovery-v3.spec.ts
POLYMONITOR_E2E_PREVIEW=1 POLYMONITOR_E2E_HARDWARE_WEBGL=1 MAP_POLISH_PHASE=after-v3-final npx playwright test e2e/map-polish.spec.ts
POLYMONITOR_E2E_PREVIEW=1 POLYMONITOR_E2E_HARDWARE_WEBGL=1 MAP_ALIGNMENT_PHASE=v3-radar npx playwright test e2e/map-alignment.spec.ts --grep 'real radar'
# /e2e/lifecycle.html 是 dev harness，不能用 production preview 代替。
npx playwright test e2e/frontend-lifecycle.spec.ts --grep 'aviation|natural hazard'
# 设置实际已推送的 40 位 SHA；正常 production 页面，无 route/fixture。
POLYMONITOR_RELEASE_SHA=<pushed-sha> POLYMONITOR_E2E_HARDWARE_WEBGL=1 node scripts/verify-live-map.mjs
```



## 第二轮精修：2026-09-29

依据 `POLYMONITOR_MAP_POLISH_ROUND2/CODEX_GUIDE.md`，以任务开始的 `c9b97a0c43e7b35daed3f362a8b60e024deef063` 加实际 dirty worktree 为基线。原有未提交文档、后端、部署文件和公开文档素材不属于本轮提交范围。对照 WorldMonitor `4691d9213a74c25bc2190146a11ebeba02b8cc85` 的比例地图字体、稳定图层、事件摘要和交互入口；没有引入第二张地图或第二个业务注册表。

| 批次 | 本轮改变 | 证据 |
| --- | --- | --- |
| A | 桌面图例默认折叠，分组 popover；实际控件安全区同时服务标签、tooltip 和选中避让；展开地图复用实例；健康底图标签收进状态详情。新访客图层面板默认收起，保存偏好继续恢复。 | `round2-A/`、安全区单元测试、行为测试 |
| B | 小型计数圆；跨类型碰撞形成中性混合堆叠，限制屏幕跨度，不改记录坐标；同类型保留类型与等级；地震/火山符号简化；密集命中显示候选列表。 | `round2-B/`、713/5000 成员报告 |
| C | 地名、地图控件、报告改用本地比例无衬线；保留 provider 的字体角色、rank、字号和密度；原始字段继续等宽；只请求必要字形样本。 | `round2-C/`、字体 readiness、provider 契约测试 |
| D | 全部已加载/当前视野/簇范围；发生与更新时间分开；阅读时保留列表顺序，新增记录由用户应用；详情返回恢复筛选和位置，筛选外选择保留说明；雷达关闭状态可发现，天气预设是显式操作。 | `round2-D/`、列表/详情/天气预设浏览器测试 |
| E | Supercluster map/reduce 摘要取代普通视口中的全量 getLeaves；成员每页最多 30，引用带索引代次；实际资源、成员完整性、互动 trace 和性能验证。 | `map-polish-round2/after/`、`resource-cycles-production.json` |

第二轮截图入口：`webpage/artifacts/map-polish-round2/index.html`。保留 `round2-before` 与 A—E 的中英同镜头截图，另外有 2040×620 的密集数据对照。测试夹具明确标识，不进入生产；没有屏蔽地图、隐藏多数记录、修改坐标、降低 DPR 或放宽截图容差。测试预设打开图层面板，以保持改动前后的相同保存状态；产品新访客默认收起另行验证。

性能对照使用同一 Chrome / GPU、相机、DPR、真实矢量资源与固定夹具，双方均关闭开发热更新。重测旧版的 713/5000 截图与原始 before 文件 SHA-256 相同。旧版对照图与复跑哈希已保留；验收后移除了临时隔离工作区，没有覆盖原始截图。

| 夹具规模 | 旧版拖动 P95 | 新版拖动 P95 | 新版 hover P95 | 拖动时索引/叶子读取 |
| --- | --- | --- | --- | --- |
| 713 | 23 ms | 25 ms | 91 ms | 索引 1→1，getLeaves 0→0 |
| 5,000 | 21 ms | 23 ms | 70 ms | 索引 1→1，getLeaves 0→0 |

这些数据满足本轮 32 ms / 120 ms 的指定环境目标，但不证明平均帧速更快，也不代表任意设备。新增碰撞分组带来额外计算；收益是消除每次查询的全量展开、明确成员入口和消除遮挡。713/5000 个输入 ID 均恰好有一个主表示，卫星原始观测、雷达瓦片及附属轨迹/区域使用不同分母；debug 表说明输入已经经过用户筛选，不冒充未加载的全球事件全集。

资源检查曾发现开发 Prefresh 的 `lastSeen` Map 持有历史 vnode（堆路径 `Window.__PREFRESH__ → module Map → vnode → detached select`）。测试模式关闭该开发热更新；普通开发模式保留。生产构建没有该模块，30 次连续操作在第 10/20/30 次均为 1,884 个 DOM 节点、466 个监听器，未完成灾害请求为 0；堆约 18.1/19.0/19.0 MB。原失败日志保留，不将开发缓存误报成已部署组件泄漏；没有放宽资源阈值。禁用热更新后，进一步用堆快照定位到 `preact/debug` 的 owner stack（`vnode.__o` / module stack）保留了历史报告。资源断言因此在已有 startup 生产构建检查中执行，开发诊断通过 `MAP_RESOURCE_HEAP=1` 单独复现，不把开发失败写成通过。

字体下载有 3 秒等待上限；下载停滞时主地图与 SVG 仍能显示并打开报告。列表透明外框不拦截其他控件；筛选外选择的说明置于报告内，避免被图层面板遮挡。

新版截图先生成到独立候选目录，再审阅原图、差异区域和透明面板背景；仅把本轮设计变化纳入 golden，保留零像素容差。`reviewed-goldens.json` 记录逐张前后 SHA、范围和理由。

第二轮已执行的检查（中间失败保留，最终结果分别列出）：

| 检查 | 本轮结果 |
| --- | --- |
| 单元测试 | 202 passed，1 个 opt-in 在线测试 skipped；`map-polish-round2/unit-final.log` |
| 类型、边界、locale 与生产构建 | 通过；`build-final.log`，包括 lazy bundle 检查 |
| 页面 / 组件 / 视觉回归 | 52/52 passed；`visual-final.log`。38 张已审阅的设计变更 golden，零容差，无地图遮罩。14 个独立路由截图与旧 golden 保持一致。 |
| 生产地图、启动、字体停滞、列表行为 | `production-regression.log` 26 passed、2 failed、1 opt-in skipped；两项失败分别是硬件运行配置与 SVG 专项预期冲突，以及测试点击图例后再读取已隐藏 tooltip。按各自场景修正执行后 `production-closure.log` 2/2 passed。未删除失败记录。 |
| 30 次资源循环 | `resource-ci-final.log` 1/1 passed；沿用 startup 生产验收测试入口，通过独立无 trace 的 worker 采样，其他启动失败 trace 保留。 |
| 真实主底图 | `real-basemap-final.log` 1/1 passed，中英实际底图截图和 Range/字体响应证据；前一次 Range 下载 20 秒超时导致本地底图降级，见 `real-basemap.log`，没有延长产品期限掩盖失败。 |
| 真实雷达 | `radar-final.log` 1/1 passed；实际清单与瓦片、停止/重开、受控 503 后旧帧保留与恢复。 |

当前工作区已有的 CI workflow 修改属于任务开始前的未提交工作，本轮保留且不代为提交；本次提交补充测试入口，不能将本地执行记录写成远端 CI 全套运行通过。

最终同镜头、产品视口、DPR 1/1.25/1.5/2、原生浏览器 125% 缩放、符号原生尺寸与 713/5000 成员/性能矩阵：`acceptance-final.log` **14/14 passed**。英文与中文的最终连续 trace 分别约 30.7 / 30.2 秒；密集数据还保留完整拖动、hover 采样、簇列表、详情、缩放和图层开关 trace。`performance-comparison.json` 为最终数值。

发布：主体 `8889d03480c2c29030d8b478a0ab733fd0cac7fa` 和控件补修 `980149aeb9edc09dca66ed79fa1c248aa579454d` 已推送到 `codex/map-polish-round2`，从干净 checkout 构建并部署 GCP，保留线上 51 份独立文档/素材的原始哈希。GitHub runs `36598045956`、`36599670162` 的 frontend-build 与 python-quality 通过。

真实页面检查与失败分别保留：

- `production-final/receipt.json`：首轮航班视口两次 HTTP 500；GCP 日志定位 API 线程耗尽（`RuntimeError: can't start new thread`）。16:38 UTC 服务由外部操作重启后恢复返回真实 ADS-B 数据，本任务没有变更后端或执行该重启。
- `production-patch-final/receipt.json`：补修后 17 项检查中 16 项通过。主底图、雷达、字体、航空控件位置、真实事件/航班详情、主题更换和桌面/移动端 Service Worker 刷新均通过。航班返回 180 条 ADSB.lol 观测，状态 `partial`，不代表完整区域覆盖。唯一失败为来源健康组中的 FIRMS provider deadline，16:50 UTC 后只读探测恢复 `ok`。失败截图和日志保留。
- `production-recovery-final/receipt.json`：恢复复验遇到桌面 `ERR_NETWORK_CHANGED`；移动端 trace 则发现 SVG 模块下载约 12.5 秒，原 12 秒期限永久作废了迟到模块。后者是明确的前端恢复缺口，已按“下载告警与挂载期限分开”补修：同一次下载完成可恢复，卸载或新渲染器代次仍使旧结果失效，不增加重试循环、不延长挂载期限。`frontend-startup.spec.ts` 补充慢下载恢复与退出后禁止迟到挂载的回归。
- 发布脚本在替换控制文件前校验入口哈希、SW build ID、当前版本和已上传资产；一次误用 HTML 包含 SHA 的断言提前拦截了发布，未改变控制文件。该次提前运行的版本不匹配检查单列于 `production-patch-before-publish/`，不算页面功能失败或通过。

慢下载与失败恢复专项 `slow-svg-regression.log` **5/5 passed**。补修 `e7025c07b644022767c80c5b9ab46f0b55abeef2` 已推送并从干净 checkout 发布，GitHub run `36602570421` 通过；`production-svg-final/receipt.json` 的真实站点 **17/17 passed**，包括 NHC/NWS/FIRMS/国家风险健康检查。实际 ADSB.lol 响应为 `ok`、180 条观测，但依旧是有范围和数量上限的采样。移动端人工检查另外发现航空卡与缩放/列表/底部入口重叠，补修只调整既有移动端定位和可滚动最大高度；`mobile-aviation-controls.log` **2/2 passed**，覆盖 watch 卡和实际控件点击，最终补修 `eab2ea40fbb8fae195841331731d69208e3f333f` 已推送、从干净 checkout 构建并部署 GCP；GitHub run `36663693396` 通过。真实 iOS/Safari/Android 设备仍不在本地 Chrome 矩阵内。雷达沿用最新实际帧，没有新增历史雷达播放、假轨迹或推测覆盖范围。


### 2026-09-30 最终交付状态

A—E 的前端实现、固定条件对照及针对性回归已完成；**最新整体验收仍受后端故障阻塞，不能写成全部通过**。最终代码版本 `eab2ea40` 的真实页面检查见 `map-polish-round2/production-mobile-final/receipt.json`：**18 项中 16 项通过、2 项失败**。实际检查了桌面主底图、移动端 SVG、真实雷达瓦片、比例字体、中英文详情、深浅主题、航空卡与导航/事件入口不重叠、Service Worker 重载及发布 SHA；无页面脚本错误或静态资源 HTTP 错误。市场目录的刷新失败没有纳入地图通过项。

未关闭的两项：来源健康组在 NWS `nws-provider-deadline-exceeded` 上失败，截图中 USGS/GDACS/FIRMS 也有降级；航班视口收到 HTTP 502，未获得可验收的新观测。此时 GCP API 状态为 `activating`，日志记录 worker 被 SIGKILL、PostgreSQL 连接超时、ClickHouse OrderFilled 读取不可用。日志提示可能内存不足，但本任务没有完成该根因证明，也没有修改、重启后端或改变数据状态以通过前端验收。证据：`production-current-api.log`。上一版本的 17/17 记录仅表示当时状态，不能替代这一轮的失败。

最终截图及生产 trace 保存在 `production-mobile-final/`；阶段 A—E 固定夹具的 before/after、30 秒交互 trace、713/5000 的成员一致性与性能数据继续保留。`map-polish-round2/index.html` 汇总入口，`release.json` 记录构建版本与发布证据。51 份线上独立文档/素材未被此次静态部署覆盖；本轮提交仅包含任务所有的文件/修改。验收期间多次哈希核对 176 份原有修改均相同；收尾又观察到独立文档 SVG `webpage/public/docs-assets/images/paperbanana/polymarket-market-lifecycle-overview.svg` 缺失，本任务没有操作、恢复、提交或部署这一并行变化。临时基线与发布 worktree 在证据保存后移除。

以下首轮记录依据用户提供的 `POLYMONITOR_MAP_ALIGNMENT_CODEX.md` 和两张原始参考图实施，描述当时的本地验证；发布及第二轮状态以本文最前面的更新为准。对照 WorldMonitor 本地 `4691d9213a74c25bc2190146a11ebeba02b8cc85`，并保留 Polymonitor 的数据事实、报告和已有 feature 边界。

## 证据与重现

证据入口：`webpage/artifacts/map-alignment/index.html`。它并列显示 P0 与 P1—P6 的中英文底图、事件和详情截图。阶段目录中的 `evidence-{en,zh}.json` 记录浏览器、相机、DPR、事件数、错误和性能。P0 保留不覆盖；不是把两家不同数据的实时网页做像素相等判断。

固定条件：Chrome 149.0.7827.196、1536×1100 视口、1536×768 地图、中心 0°/20°、zoom 1.5、固定现有事件夹具 2026-08-26 03:00 UTC、全部时间和严重度、相同四个灾害图层、11 个逻辑事件、字体就绪、静态截图 reduced-motion。PMTiles、字形和 sprite 使用真实资源并按 URL/Range 缓存原始响应；没有用图片替代地图，没有遮罩 canvas，没有降低静态 DPR。

参考截图不是本应用测试夹具。固定夹具的事件分布少于参考图，是测试数据的真实差异，不通过制造事件补齐密度。另有 `P6-LIVE` 真实来源检查，与固定视觉证据明确分开。

```bash
cd webpage
# 使用项目要求的 Node 22.23.3 / npm 10
npm run preview:map-alignment
# http://127.0.0.1:4191/ ：真正可交互的本地新前端，匿名读取公开线上数据。
# 本地代理只允许 GET/HEAD，去除 Cookie/Authorization；POST/PUT 等返回 405。
# 不部署前端，不写生产数据；实时事件数量和状态会随来源改变。

npm run preview:map-fixtures
# 有图形桌面时打开固定数据浏览器并停在 Playwright Inspector。
# 截图对照使用此测试夹具；不会把夹具接入产品。

VITE_PMTILES_URL=/map-tiles/planet.pmtiles MAP_ALIGNMENT_PHASE=P6 \
  POLYMONITOR_E2E_HARDWARE_WEBGL=1 npx playwright test e2e/map-alignment.spec.ts \
  --grep 'fixed camera|product map'

MAP_ALIGNMENT_PHASE=P5 VITE_WEATHER_RADAR_ENABLED=1 \
  VITE_PMTILES_URL=/map-tiles/planet.pmtiles POLYMONITOR_E2E_HARDWARE_WEBGL=1 \
  npx playwright test e2e/map-alignment.spec.ts --grep 'real radar'

npx playwright show-trace artifacts/map-alignment/P6/interaction-en.zip
```

`POLYMONITOR_E2E_PORT` 可更换测试服务器端口；浏览器 URL 仍固定为 4174，由既有 local-assets fixture 路由到实际服务器。硬件验收使用 NVIDIA RTX 5090 / ANGLE Vulkan；未配置该环境时不能把软件渲染结果称为硬件性能。`MAP_ALIGNMENT_DPR=2` 可复跑参考场景的双倍像素密度。

## 实施与归属

| 阶段 | 现有归属与改变 | 前后证据 |
| --- | --- | --- |
| P0 | 记录实际 dirty worktree、入口、样式链、renderer、数据与测试。未以 HEAD 覆盖工作区。 | `workspace-baseline.json`、`P0/`、`P0-DPR2/` |
| P1 | `config/weatherBasemap.ts` 保留 Protomaps 原生层级、rank、碰撞与字体栈，只调整暗色 paint；删除重复地名层和强制字体/大小规则。相机状态区分初始 fit 与已保存/URL 相机。 | `P1/basemap-{en,zh}.png` |
| P2 | 现有 layerFactories 负责小型严重度符号、单体聚合及真实计数、观测/预测/锥/区域；选中事件单列但不重复计数。多边形摘要点在真实内部；任意轨迹端点不充当观测中心。SVG 复用语义并修正球面绕向。 | `P2/events-{en,zh}.png` |
| P3 | 现有 Toolbar、LayerPanel、EventList、EventInspector 与样式。缩短提示、移除浮动 BETA；来源/覆盖/关键指标优先，原始证据折叠；中英切换、统一 tooltip 安全区、手机底部报告。 | `P3/` 与最终 `P6/product-detail-*.png` |
| P4 | renderer 内现有 RAF：仅新到且时间有效的重要事件产生有限提醒，首批/历史/重新开启不重播；拖动、hidden、离屏、reduced-motion 暂停；静态图层不随脉冲重建。 | `P4/`、`P0/interaction-*.zip`、`P6/interaction-*.zip` |
| P5 | `useWeatherRadar` 只管理真实雷达清单的独立生命周期；现有 layerRegistry/MapLibre raster 管理显示。实际最新 past 帧、实际覆盖瓦片、明确时间/状态/归属，无假雷达。 | `P5/radar-{before,after}.png`、`P5/radar-evidence.json` |
| P6 | 原有地图/生命周期/视觉设施，补充几何、到达时间、竞态、安全文本、右边缘 tooltip、DPR、横屏、真实底图与雷达恢复。 | 本节以下最终检查记录与 `P6/` |

没有增加第二个地图、注册表或事件加载器。删除旧 cluster count atlas、旧 tooltip HTML 拼接、冲突的标签覆盖、装饰性的强度圈与无限灾害脉冲。保留 MapLibre、deck.gl、Protomaps、SVG fallback、3D、API、来源状态和报告链路。使用与现有 deck.gl 完全一致的 `@deck.gl/extensions@9.4.0` 绘制真实虚线路径，没有升级其他运行时依赖。

阶段实际状态：**P0—P4 已实现并在指定本地 Chrome 环境验证；P5 已实现并验证真实数据链路，使用资格已于 2026-09-29 确认为非商业研究/小型社区用途；P6 已实现并完成下列本地矩阵，真实 iOS/Safari/Android 环境待验证。** 没有将这些不同状态合并为生产验收通过。

宽而矮的单世界视口需要允许 underzoom，否则默认约束会把世界重新放大裁剪。采用 [MapLibre 官方 transformConstrain 扩展点](https://maplibre.org/maplibre-gl-js/docs/examples/customize-the-map-transform-constrain/)，仍将经纬度和缩放限制在现有地图状态边界内。没有重复世界或缩小 canvas 来掩盖问题。

## 真实雷达与外部边界

对照 WorldMonitor 的 source/layer 稳定 ID、五分钟清单刷新、停止需求后移除、样式恢复和 source-loaded 后更新机制。没有复制它旧的 palette 6 URL；根据 [RainViewer 当前过渡说明](https://www.rainviewer.com/api/transition-faq.html) 使用 palette 2、原生最高 z7、最新 past 帧。参见 [清单契约](https://www.rainviewer.com/api/weather-maps-api.html) 与 [色表](https://www.rainviewer.com/api/color-schemes.html)。

雷达与 7d 事件筛选互相独立，界面明确“最新雷达”和帧时间。当前产品没有绝对历史时刻回放，本次未添加历史雷达播放。覆盖瓦片不代表所有地区均有观测；无覆盖不等于无降水。关闭、SVG、hidden/离屏停止请求；清单错误保留最后成功帧并标 stale。

**2026-09-29 使用资格更新：** 项目所有者明确确认为非商业研究/小型社区用途。雷达现对新地图状态默认开启；`VITE_WEATHER_RADAR_ENABLED=0` 可显式禁用。已保存的图层选择和分享 URL 仍然有效，用户关闭后不强行重新开启。署名、帧时间、覆盖和失败保留语义不变。

## 最终检查记录

中间失败日志保留用于追踪，不能当作最终通过证据。最终复跑结果在下表记录。

| 检查 | 结果与证据 |
| --- | --- |
| 前端单元测试 | 192 passed，1 个需要显式联网的测试 skipped；`unit-final.log`。该联网用例另行执行 1 passed，见 `live-api.log`。 |
| 地图后端契约 | 50 passed，`backend-tests.log`；未修改后端业务。 |
| 启动恢复 | 6 passed，`startup-final.log`：慢 bootstrap、模块下载失败/延迟、退出失效和样式加载期限。 |
| 本地构建 | 通过：locale、导入/请求/CSS 边界、TypeScript、Vite 与 lazy bundle 检查，`build-final.log`。仍有 Vite 大 chunk 提示；不将构建作为视觉对齐证据。 |
| 页面、布局、共享请求、生命周期、组件样式 | 74 passed，`regression-final.log`；包含 44 张审阅后 golden 的零容差复跑与中文字体冷/暖加载。 |
| 地图浏览器专项 | 15 个不同场景均有通过记录：`map-final.log` 中 13 passed、1 failed、1 opt-in skipped；失败的 30 次循环清理在 `map-closure.log` 复跑通过；真实底图、中心/四边缘聚合拾取与国家交互在 `map-picking-final.log` 最终 3 passed。并非一次全量 15/15 的记录。 |
| 参考构图与性能 | 2 passed，`fixed-final.log`；完整英文/中文 trace 27.1/27.4 秒，真实矢量底图、固定相机、11 个事件；DPR 2 同构图另行 2 passed（`dpr2-final.log`）。 |
| 产品视口/DPR | 7 passed，`responsive-final.log`；原生 canvas DPR、无横向溢出、详情与选中事件/手机控件不相互遮挡。 |
| 真实雷达 | 1 passed，`radar-final.log`：实际清单、帧与覆盖瓦片、停止请求、重开、503 后 last-good、下一轮恢复。 |
| 真实灾害 GET | 1 passed，`live-final.log`；本地新前端显示 338 个去重逻辑事件。FIRMS error、NWS degraded 保留，没有改写为正常。 |

44 张既有 golden 按实际图片审阅后更新，`reviewed-goldens.json` 保留每张的前后 SHA 和对应 actual 路径。允许的差异是此次用户明确要求的底图/图例/工具栏/报告变化及相应页面构图；没有更新容差、遮罩 canvas 或关闭事件。工具栏中文另有冷字体延迟与复载逐字节相等检查。手机报告修复了焦点导致的上滚；打开时保留地图条带，SVG 与 WebGL 共用选中避让计算，缩放控件保持在报告外。横屏使用有宽度上限的侧栏。

复测发现并修复了快速点击聚合时国家卡片同时打开的问题：mousedown 不再提前清除拾取状态，国家点击再用实际点击位置查询 overlay，不能依赖上一帧 hover。30 次循环测试的退出目标改为实际存在的 `/login`，并验证卸载后的 canvas/tooltip 清理；原来的 `/settings` 会回到首页而非退出地图。Vite 排除 artifacts/test-results 的文件监听，避免 trace 写入触发页面重载；这些修复没有移除活动页面的错误断言。

`map-closure.log` 还记录一次真实 PMTiles Range 请求超时，主底图未就绪后明确进入降级；最终同一真实来源检查复跑通过（`map-picking-final.log`）。保留该网络失败记录，没有延长产品加载期限或把降级算作主底图成功。外部资源的持续可用性仍不由一次成功复测证明。

本地可交互预览已经实际验证：`http://127.0.0.1:4191/`，真实 WebGL 主底图、343 个事件、中文、选择详情及缩放；没有替换 API 或瓦片。`preview-live.json` 记录响应与取消，`preview-live{,-detail}.png` 是实拍。代理已验证 POST 返回 405。该次真实预览仍显示市场目录刷新失败、FIRMS error、NWS degraded；不将这些来源/市场问题归入已解决状态。

实际改动清单：`webpage/artifacts/map-alignment/task-owned-paths.json`，不含任务开始前已经修改的文件。旧聚合 atlas 的测试迁入 `renderer/layerFactories/eventClusters.test.ts`，保留了完整计数与单一可点击实体的断言。

### 性能结果

RTX 5090、Chrome 149、真实 WebGL、DPR 1、同一参考夹具；独立运行的连续拖动 10 秒，未与其他浏览器测试或构建并行。

| 指标 | P0 英文 / 中文 | P6 英文 / 中文 |
| --- | --- | --- |
| RAF 间隔 p95 | 23 / 23 ms | 23 / 22 ms |
| 最大帧间隔 | 59 / 55 ms | 66 / 65 ms |
| 拖动阶段 >50 ms 长任务 | 0 / 0 | 0 / 0 |
| 含初始化的长任务数 | 17 / 18 | 12 / 14 |
| 含初始化的最大长任务 | 632 / 682 ms | 601 / 414 ms |

交互 p95 满足此次约 33 ms 的门槛，没有重复的 >100 ms 交互长任务。初始化仍有较长主线程工作，最大帧间隔也未改善；单次采样不证明整体启动性能已解决。网络加载与本地交互分开，实时源的延迟不冒充前端渲染耗时。

### 验收矩阵对应关系

- V01—V04：P0/P6 中英文同相机、DPR 对照；URL/state 单元测试与现有 WebGL URL 恢复用例；产品默认 fit 不覆盖显式相机。
- V05—V08：聚合完整计数、最高 severity 与选择排除的单元测试；WebGL 实体中心/边缘拾取、同坐标 max zoom 列表和 SVG 键盘测试。
- V09—V12：全局灾害区域/风暴中心、观测线、虚线预测与预测锥截图；凹多边形/洞/多岛/日期变更线/视口跨越/缺坐标单元测试。
- V13—V15：慢报告 A→B、惰性安全文本、右边缘 tooltip、图例 computed style、选中事件在详情外及严重度按钮对比度断言。
- V16—V17：真实雷达独立链路及刷新失败恢复；parser 验证过期/未来帧；界面标注最新帧与覆盖。绝对历史回放未实施，现有产品只有相对事件时间筛选。
- V18—V19：30 次图层/来源/选择循环、资源上界、隐藏/离屏/卸载清理及 reduced-motion；有限新到达脉冲的时间/预算单元测试；最终连续操作 trace。没有把空闲的历史事件伪装成“新事件”录屏。
- V20—V22：1440/2048、390×844、844×390、DPR 1/1.25/1.5/2；provider 切换、WebGL context loss、SVG fallback、empty/degraded/失败与重载。真实移动设备仍未验收。


## 证据范围

本地浏览器矩阵覆盖桌面 1440/2048、手机 390×844、横屏 844×390、DPR 1/1.25/1.5/2。窄视口 Chrome 的 SVG 检查不等同于真实 iOS/Safari/Android 设备验收。固定视觉测试不证明线上所有来源新鲜；真实 GET 烟测也不证明全部 provider 无缺口。

工作区原有后端、部署、文档和文档图片修改未纳入本任务。实施中发现 `docs/panel-modules.md` 相对初始记录另有变化，未覆盖它。产物和截图留在现有 ignored artifacts/test-results 范围；参考输入未复制成新的产品文档体系。

## 与参考图的最终视觉关系

同构图对照下，海面/陆地接近参考图的深灰/近黑层次，原先重复的大字号地名与厚 halo 已退出；保留 provider 的行政层级、碰撞和渐进显示。严重度小符号、单体聚合与真实灾害线面优先于背景；观测线、虚线预测和中性预测锥可以区分。没有用降低 DPR 或隐藏全部 info/watch 获得清爽画面。

雷达纹理在 P5 实际帧截图中存在，时间来自真实清单，与事件 7d 窗口分开。雷达现默认开启（使用资格确认见上文）。点击、聚合展开、报告切换、缩放与拖动有实际 trace 和响应断言；不能把静态截图当作自然动画的唯一证据。用户两张原图尺寸、相机与实时数据不同，因此不声称跨站逐像素相等。


## 2026-09-29 来源与字体修复

- NWS `/alerts/active` 返回 400 的根因是发送了不支持的 `limit` 参数；取消上游参数，继续在规范化后限制数量。区域补全使用请求开始后的剩余预算，避免原先单独 7 秒等待超过来源接口的 6.5 秒期限；保留已缓存几何、明确未补全部分。截止边界重新读取已经成功写入的新快照，不把它误标成超时。保留 CAP 更新/取消及真实失败时的旧快照。
- FIRMS 未配置 key 时，复用同一个适配器读取 NASA 官方 NOAA-20 24h CSV；全局聚合与视口观测共享现有 SnapshotStore 的 15 分钟下载缓存。其他产品仍需 key；不把热异常当成确认火灾。
- NHC 的观测/预测几何使用已有执行器并行获取，并限制总等待；来源计数使用实际 provider 身份，修正 NHC、火山与月度异常的缩写不匹配。
- 国家风险按来源记录的实际国家字段归集；“ISRAEL / GAZA”仅作为主题摘要，不再当作国家边界标识。
- 航空保持共享飞机观测，视口每 30 秒刷新；页面隐藏/卸载/切换时取消，失败保留旧数据。界面区分真实观测与参考航线，提供实际放大入口。
- 地图 DOM 继承页面字体；deck.gl 读取页面字体；MapLibre 使用已有字体生成本地 SDF，保留 Protomaps 的层级、碰撞与尺寸。没有新字体包或 glyph CDN。

本轮针对性证据位于 `webpage/artifacts/map-source-repair/`；固定条件真实矢量底图英文/中文对照位于 `webpage/artifacts/map-alignment/source-repair/`。对照测试现强制检查真实 PMTiles 的 206 响应，缺少配置不能以简化测试底图通过。生产验收运行 `webpage/scripts/verify-live-map.mjs`，记录 release-sha、真实来源响应、字体、雷达瓦片、飞机详情、移动端限制、Service Worker 和 browser trace；具体生产结果以本轮收据为准。


## 2026-10-01 可选来源与匿名首页收口

- NWS 核心 CAP 与可选几何分开：几何使用独立 3 秒预算、既有六线程/十二任务上限、60 秒失败冷却和共享缓存。缓存命中继续推进未完成的区域，不让失败的首批阻塞后续区域；更新/取消、revision、坐标和成功时间保持原值。完整 CAP 多边形不再把备选 affectedZones 计为缺失边界。
- ADSB 区域查询按球面距离选择最多四个、半径最多 250 海里的查询；能覆盖的区域不再一律视为抽样。覆盖描述区分完整区域查询、宽范围抽样、失败扇区和返回数量上限。完整区域查询仍不等于全部飞机的监视覆盖；真实失败、合法空结果与迟到响应继续沿用已有链路。航空现有放大入口也可用于缩小查询缺口。
- 匿名首页的健康消费使用已有公开 `/health`，不再轮询需要 operations:read 的 `/system/health`。管理接口继续要求鉴权，公开响应不虚构私有连接信息。
- ClickHouse 最近时间窗不可用时，已有路由返回可恢复的 503 而非未分类 500。时间索引已更新但事实投影尚未进入该时间窗时，不能把空列表当作完整的实时成交结果；合法空窗仍保持现有列表 API 契约。
- 针对性测试包含：CAP 原生区域、缓存补全及故障解除；航空区域/高纬度/日期线覆盖、分区失败及恢复；成交来源失败到恢复和事实水位；匿名首页首次及持续刷新不请求管理健康接口。
- 真实 iOS/Safari/Android 设备验收按用户本轮明确要求排除。生产截图仍覆盖桌面和窄视口 Chrome，不能称为真实设备结果。构建、单元和固定 fixture 只作发布前检查；发布身份与真实来源结果以 `webpage/artifacts/map-source-closure/` 及清洁发布工作区同名证据为准。
