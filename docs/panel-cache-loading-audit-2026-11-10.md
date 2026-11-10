# 全量 Panel 缓存、读取与展示核验（2026-11-10）

后续实际采集、API 与公网修复见 [新数据与传输恢复记录](panel-source-recovery-2026-11-10.md)，两次观察的时间与结果分开保留。

这是指定版本的代码审计与当次运行记录，不是长期健康承诺。当前规范仍以 panel-data-pipeline、panel-resource-contract、panel-runtime-lifecycle、panel-data-cadence 和领域文档为准。所有时长必须注明所属层，不能把“刷新间隔”当成“删除期限”。

## 范围与证据边界

- 本项目显式 registry **121 个 Panel**：93 个直接 Runtime 数据拥有者、7 个复用天气拥有者的视图、21 个参数化资源／业务上下文／静态视图。下面逐项列出，不能把 93 当成全部 Panel。
- 111 个默认启用；10 个宏观派生／基础视图原本默认关闭。生产现有布局实测挂载 111 个，保留原布局，没有通过重置布局制造覆盖率。
- 93 个直接拥有者的公网接口逐个读取，随后使用实际前端解析函数验收；不是仅数 HTTP 200。13 份参数化资源声明另行求值，去重后额外读取 11 个真实 API；示例市场为 550186，不代表全部市场。LOB 的空 token 仅用于静态导出，未发往线上。
- WorldMonitor 固定到 `6f1f170def8d8a5b1f89c4615655034d5a4818ef`（2026-11-10 远端 main）。扫描全部 `src` 中 107 处 createCircuitBreaker，并另外追踪 bootstrap、RSS/digest、服务端缓存、采集、调度和渲染。107 是缓存组件调用数，**不是 Panel 数或所有存储路径数**。
- 实测文件与桌面截图位于本机 `/home/jiahuaiyu/.codex/visualizations/2026/11/10/panel-cache-investigation/`。状态、时间、体积、字段覆盖均为该观察时点；未做真实隔夜连续稳定性验收。

## 先回答 15 分钟／30 分钟

NBA 15 分钟、DeFi 30 分钟是本项目原先浏览器副本的恢复上限，不是 WorldMonitor 的通用规定。WorldMonitor 的当前源码没有 NBA 对应 Panel，不能用它捏造 NBA 参数。

WorldMonitor DeFi 的不同参数为：后台 bundle 每 30 分钟尝试采集；Redis TTL 5400 秒（90 分钟）；浏览器 breaker 新鲜期默认 10 分钟；持久缓存恢复上限默认 24 小时；市场 UI 调度 12 分钟。五个值各管一层。源更新时间、Redis 写入时间和浏览器 updatedAt 也不是同一时间。

其 breaker 恢复时，age > 24h **不采用这份副本**，该分支直接返回，并不调用删除。执行时另设 `maxServeAgeMs` 或 `shouldCache` 校验失败才可能显式驱逐、删除。24h 也不是默认内存硬删除期限；已经驻留内存的旧值是否还能回退，受 execute 参数控制。底层 persistent-cache 本身没有统一的 24h 定时删除任务。

## WorldMonitor 从采集到展示

1. **后台采集。** DeFi/AI/Other tokens 由同一 seed-token-panels 脚本采集 CoinGecko，允许 CoinPaprika 回退，按组发布；CoinGecko 总预算 45s、单请求 15s，回退并发 4。空／不合格结果不能覆盖已有成功快照。bundle 每 30m 调度，单任务超时 120s。TTL 与调度间隔独立。
2. **服务端快照。** `market:defi-tokens:v1` 等 Redis key 保存处理过的数据。DeFi API 只读 getCachedJson 并转换字段；缺 seed 返回空并禁止缓存该兜底，不同步采集 CoinGecko。地震也是 seed 读取；额外加密币种、允许重建的新闻摘要等仍可能在未命中时请求上游。不能把所有 API 都说成只读 seed。
3. **批量启动。** bootstrap 的 fast/slow/on-demand registry 批量 Redis pipeline，3s 预算，不做采集。浏览器 fast 预算 1.2s、slow 3s；桌面分别 5/8s。网页通常先请求网络，失败或缺 key 才合并本地 tier 副本。tier 副本通常限 24h；桌面明确离线的 allowStale 分支可以跳过年龄限制，不等于网页都无限期恢复。`getHydratedData` 是一次性消费（读取后从 Map 删除）。当前 R2 路径用于影子测量，不能宣称已承担真实 bootstrap 返回。
4. **HTTP/CDN。** fast 浏览器 max-age/SWR/SIE 为 60/120/900s，slow 为 300/600/3600s；CDN fast 为 600/120/900s，slow 为 7200/1800/7200s。on-demand 有逐 key 例外，不能让 CDN 覆盖来源完整发布周期。Redis 故障返回 503、Retry-After 5、no-store；不能把 warming/错误变成长期 CDN 内容。
5. **浏览器持久化。** Web 使用 IndexedDB `worldmonitor_persistent_cache` / `entries`，envelope 为 key、updatedAt、data；失败可回退 localStorage。桌面另有磁盘路径。默认 updatedAt 是浏览器存储时间，**不是上游观察时间**。我们保留源时间验收，不照搬写入时间来延长报价寿命。
6. **浏览器缓存决策。** breaker 默认 persist=false，fresh=10m、persistent ceiling=24h、maxFailures=2、cooldown=5m、内存每 breaker 最多256 key、半开探测30s。有效缓存直接返回；过新鲜期而仍可用时默认立即返回旧值、后台请求自身 API；同 key 合并刷新。forceRefresh / staleRefreshMode=await 改为等待。shouldCache、maxServeAgeMs、evictOnRefreshFailure 是调用点独立规则；revivePersistedData 负责恢复 Date 等类型。失败通常保留 last good，部分执行路径明确要求失败驱逐。
7. **渲染与调度。** fetchDefiTokens 先取已到达的 bootstrap 数据，再走持久化 breaker，并有当页 lastSuccessfulDefi。data-loader 将数据交给 renderTokens。loadMarkets 本身仍有先后等待和 Promise.all 分组，不能声称每个 Panel 都不受启动等待影响。市场调度12m，RSS10m，风险5m，FRED6h等是另外的周期；隐藏页面暂停，回到前台仅补到期任务并错峰。通用 Panel 错误重试15/30/60/120/180s，成功后复位；调度器另有 in-flight 与最多4倍退避。
8. **不走同一 breaker 的例外。** 新闻 digest:last-good 按 variant/language 分键、恢复6h，并比较分类覆盖度，较差/servedStale 响应不能重写 last good。RSS feed:v2 的内存新鲜期30m、最多100条、清理大于60m；其持久 feed 回退没有统一24h年龄门。风险 breaker 的持久上限1h；GDELT execute maxServeAge1h；China Policy/Renewable Energy 工厂可用7d；TTL=0 的实时路径禁用持久化。下方完整107项表列出这些差异。

源码入口：
- [scripts/seed-token-panels.mjs](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/scripts/seed-token-panels.mjs)
- [scripts/seed-bundle-market-backup.mjs](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/scripts/seed-bundle-market-backup.mjs)
- [server/worldmonitor/market/v1/list-defi-tokens.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/server/worldmonitor/market/v1/list-defi-tokens.ts)
- [api/bootstrap.js](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/api/bootstrap.js)
- [shared/bootstrap-tier-keys.js](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/shared/bootstrap-tier-keys.js)
- [src/services/bootstrap.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/bootstrap.ts)
- [src/services/persistent-cache.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/persistent-cache.ts)
- [src/utils/circuit-breaker.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/utils/circuit-breaker.ts)
- [src/services/market/index.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts)
- [src/app/data-loader.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/app/data-loader.ts)
- [src/components/MarketPanel.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/components/MarketPanel.ts)
- [src/config/variants/base.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/config/variants/base.ts)
- [src/app/refresh-scheduler.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/app/refresh-scheduler.ts)
- [src/components/Panel.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/components/Panel.ts)
- [src/services/rss.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/rss.ts)
- [src/app/news-digest-acceptance.ts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/app/news-digest-acceptance.ts)

## 本项目确认的问题与修复边界

| 问题 | 因果证据 | 处理 |
| --- | --- | --- |
| 隔夜副本不可恢复 | NBA原15m、DeFi原30m；读取时超过源时间上限即删除本缓存项 | 公共概览统一采用24h展示恢复，fresh与后台采集周期不变；显示stale及原时间 |
| 缓存容量彼此挤占 | 当次可解析公共响应按原localStorage分配约317万字符；Geo约108万超过单项25.6万，排除它后仍约210万超过总200万 | 所有非null缓存资源写同一IndexedDB，16M字符/256项；原2M/96项只作同步热副本；Geo单项2M |
| NBA格式拒收 | API有8场比赛，新增 homePeriods/awayPeriods/leaders/season 被旧校验器拒绝 | 接受这些实际结构，继续拒绝非法嵌套；添加真实结构回归 |
| 混合天气快照续期旧预报 | 整包generatedAt可因目录刷新推进，而forecastFetchedAt仍旧 | 逐城市以forecastFetchedAt限制24h恢复；剔除过期小时/日预报及派生值，保留有效METAR与合约 |
| 大天气响应被截断 | 一次真实完整body约2.76MB/21s；旧外层10s、传输12s先取消，HTTP200仍未完成JSON | weather网络完整body35s、总期限60s；保留共享并发预算 |
| 宏观请求排队失败 | 生产Geo及多个宏观Panel显示 request exceeded 12000ms；独立API可读 | 宏观共享总期限改为45s（含排队），实际API网络超时仍独立；不无限排队 |
| 恢复时反复满屏Loading | 无内容失败后自动重试又覆盖成Loading | 保留错误/已有内容，成功才清除；有界重试仍继续 |
| 静态数据冒充实时 | Trade Policy 内置 ALERTS/score 常量，UI曾标LIVE | 改REFERENCE并明确为示例，动态采集仍未实现 |

这些修复不证明全部来源已恢复。没有成功过的副本无法靠持久化凭空生成；超过领域硬期限的执行证据不能恢复成有效数据。

## 本项目共用链路与每个参数的含义

- 生产者 → 正式存储 → API投影 → 传输准入 → parser → Runtime状态 → 浏览器持久化／恢复 → Panel渲染。纯视图没有第二个生产者或缓存。
- 正式公共快照是既有 SQLite `panel_snapshots(namespace,cache_key,payload_json,updated_at,expires_at)`；optional Redis是镜像/缺本地回退，不能反过来宣称Redis拥有全部数据。get_stale可读已过存储TTL的记录，但原始source clock仍受服务端retention限制。金融/政治/外源部分另外保存逐来源证据和失败状态。
- NBA 实测正式存储TTL240s，DeFi实测TTL360s；DeFi GET源新鲜900s、源保留1800s。这些参数与浏览器24h展示恢复完全分开。重新写入seed不续期原观察时间。
- `read_public_seed` 只读；`read_watch_seed` 在拥有者心跳失效时可异步调用同一builder恢复，最多4槽、每key至少30s，并不让GET等待采集。外源/政治API是存储证据投影，不能把它们说成Redis固定整包；也不能把所有GET一概说成重新爬。
- API共享下载槽：桌面3、手机2；目录优先级-1，主风险/实时信号0，批量地图1，一般Panel2；每等待4s老化优先级，取消移出队列。API请求计时从准入开始并包含完整JSON；Runtime总deadline包含排队。表中的deadline是后者。
- `maxAgeMs` 控制fresh/stale；`staleAgeMs` 控制可恢复展示上限；`acceptStale` 控制是否接纳过fresh的网络响应。恢复及写入还执行同一parser、key/version、源时间不超前60s、单项容量校验。
- `checkedAt` 是上次验收成功的浏览器检查时刻，只决定下次检查到期，不用来续期源数据。恢复不会改写checkedAt。有效本地值先显示，过期或检查到期才后台联网；失败保留上次有效值，合法空结果可以替换。warming/失败不得写成成功缓存。
- IndexedDB默认所有非null公共owner共用；小型localStorage命中同步显示，未命中再读IDB。800ms释放网络准入、存储事务最长5s；迟到本地结果只填空、不覆盖新网络值。额度失败不清布局、不破坏已有画面。写入和淘汰同一事务。旧localStorage键可继续读，无需用户清缓存。
- 缓存大小单位为JSON字符，不等于磁盘字节；预算仍是有限的，不能承诺无限历史市场。资源key含市场/窗口/limit/sort/version；身份改变取消旧请求并隔离缓存。
- 通用失败恢复为15/30/60/120/180s并加最多10%抖动；显式快速重试后仍进入恢复退避，Retry-After为下界。隐藏/离线不触发高频重试；恢复可见/online错峰补试；同owner只允许一个在途请求。
- Quote/Oracle/资格/分析过期是字段或领域规则，不因外层24h副本延长：天气目录15m及城市当地日期、天气盘口、bookmaker quote/fixture expiry、AI snapshotExpiresAt、Alpha撤销、Funding可交易资格、Crypto reference source age继续校验。

## 121个Panel逐项：身份、时钟、预算、API与观察

每行的“检查/fresh/恢复/总期限”互不替代。IDB表示共用持久库，`+LS`表示额外同步热副本。时间戳锚点和字段剔除规则见后续领域表与链接中的parser；未声明deadline按45s。API结果的ok/degraded只是payload状态，不能等于业务全字段完整。路径均为GET；limit固定值在URL中。

### 93个直接Runtime拥有者

| Panel（代码） | 完整浏览器key；存储/单项字符 | 检查 / fresh / 恢复 / 总期限 | API（含参数） | 本次读取得到的状态 |
| --- | --- | --- | --- | --- |
| [price-implications](../webpage/src/panels/modules/price-implications/index.tsx) | `market-insights:overview:v1`<br>IDB+LS / 256,000 | 15m / 12h / 12h / 45s | `/wm-api/runtime/agent/market-wide-insights/overview` | live；2026-11-10T00:56:16.268881Z |
| [sample-chain-trades](../webpage/src/panels/modules/sample-chain-trades/index.tsx) | `market-insights:special:v1`<br>IDB+LS / 256,000 | 15m / 12h / 12h / 45s | `/wm-api/runtime/agent/market-wide-insights/special` | live；2026-11-10T00:57:39.014861Z |
| [oracle-timeline](../webpage/src/panels/modules/oracle-timeline/index.tsx) | `market-insights:trend:v1`<br>IDB+LS / 256,000 | 15m / 12h / 12h / 45s | `/wm-api/runtime/agent/market-wide-insights/trend` | live；2026-11-10T00:59:03.146124Z |
| [breaking-event-radar](../webpage/src/panels/modules/breaking-event-radar/index.tsx) | `public:breaking-event-radar:limit:12:v1`<br>IDB+LS / 256,000 | 5m / 15m / 1d / 45s | `/wm-api/runtime/evidence/breaking-event-radar?limit=12` | stale；2026-11-08T03:37:50.108342Z；超过24h拒收 |
| [market-tv-wire](../webpage/src/panels/modules/market-tv-wire/index.tsx) | `public:market-tv-wire:limit:60:v1`<br>IDB+LS / 256,000 | 15m / 30m / 6h / 45s | `/wm-api/runtime/content/market-tv-wire?limit=60` | degraded；2026-11-10T03:15:45.330912Z |
| [market-youtube-channels](../webpage/src/panels/modules/market-youtube-channels/index.tsx) | `public:market-youtube-channels:limit:80:v1`<br>IDB+LS / 256,000 | 15m / 30m / 6h / 45s | `/wm-api/runtime/content/market-youtube-channels?limit=80` | degraded；2026-11-10T03:15:45.330912Z |
| [ai-model-race](../webpage/src/panels/modules/ai-model-race/index.ts) | `tech:ai-model-race:limit:36:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/tech/ai-model-race?limit=36` | ok；2026-11-10T06:17:41.258294Z |
| [big-tech-market-cap](../webpage/src/panels/modules/big-tech-market-cap/index.ts) | `tech:big-tech-market-cap:limit:16:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/tech/big-tech-market-cap?limit=16` | partial；2026-11-10T06:07:52.710431Z |
| [consumer-app-pulse](../webpage/src/panels/modules/consumer-app-pulse/index.ts) | `tech:consumer-app-pulse:limit:40:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/tech/consumer-app-pulse?limit=40` | partial；2026-11-10T06:08:02.723514Z |
| [defi-token-watch](../webpage/src/panels/modules/defi-token-watch/index.tsx) | `public-feed:defi-token-watch:limit:10:v1`<br>IDB+LS / 128,000 | 5m / 15m / 1d / 45s | `/wm-api/runtime/finance/defi-token-watch?limit=10` | ok；2026-11-10T06:22:56.899399Z |
| [defi-yield-monitor](../webpage/src/panels/modules/defi-yield-monitor/index.tsx) | `finance:defi-yield-monitor:limit:10:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/defi-yield-monitor?limit=10` | ok；2026-11-10T06:07:30.821468Z |
| [defi-security-watch](../webpage/src/panels/modules/defi-security-watch/index.tsx) | `finance:defi-security-watch:limit:12:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/defi-security-watch?limit=12` | ok；2026-11-10T06:17:35.548467Z |
| [tradfi-perp-radar](../webpage/src/panels/modules/tradfi-perp-radar/index.tsx) | `finance:tradfi-perp-radar:limit:24:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/tradfi-perp-radar?limit=24` | partial；2026-11-10T06:09:08.044183Z |
| [ipo-news-watch](../webpage/src/panels/modules/ipo-news-watch/index.tsx) | `finance:ipo-news-watch:limit:12:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/ipo-news-watch?limit=12` | ok；2026-11-10T06:17:38.714106Z |
| [broker-research-watch](../webpage/src/panels/modules/broker-research-watch/index.tsx) | `finance:broker-research-watch:limit:12:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/broker-research-watch?limit=12` | partial；2026-11-10T06:07:58.435750Z |
| [global-index-monitor](../webpage/src/panels/modules/global-index-monitor/index.tsx) | `finance:global-index-monitor:limit:12:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/global-index-monitor?limit=12` | ok；2026-11-10T06:18:28.393716Z |
| [commodity-equity-transmission](../webpage/src/panels/modules/commodity-equity-transmission/index.tsx) | `public:commodity-equity-transmission:limit:8:v1`<br>IDB+LS / 256,000 | 5m / 5m / 15m / 45s | `/wm-api/runtime/finance/commodity-equity-transmission?limit=8` | model；2026-11-10T06:10:43.456037Z；前端拒收:Error: Resource snapshot is overdue |
| [crypto-fear-greed](../webpage/src/panels/modules/crypto-fear-greed/index.tsx) | `finance:crypto-fear-greed:limit:6:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/crypto-fear-greed?limit=6` | partial；2026-11-10T06:19:50.776666Z |
| [crypto-etf-flow](../webpage/src/panels/modules/crypto-etf-flow/index.tsx) | `finance:crypto-etf-flow:limit:8:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/crypto-etf-flow?limit=8` | proxy；2026-11-10T06:09:08.044183Z |
| [blockchain-policy-news](../webpage/src/panels/modules/blockchain-policy-news/index.tsx) | `finance:blockchain-policy-news:limit:12:v1`<br>IDB+LS / 128,000 | 10m / 15m / 1d / 45s | `/wm-api/runtime/finance/blockchain-policy-news?limit=12` | ok；2026-11-10T06:19:54.063445Z |
| [geo-sanctions-shock](../webpage/src/panels/modules/geo-sanctions-shock/index.tsx) | `macro:geo-sanctions-shock:latest:v2`<br>IDB / 2,000,000 | 5m / 10m / 1d / 60s | `/wm-api/runtime/world/geo-sanctions-shock?limit=2000` | ok；2026-11-10T06:09:33.922622Z |
| [global-transport-shipping](../webpage/src/panels/modules/global-transport-shipping/index.tsx) | `public:global-transport-shipping:limit:14:v1`<br>IDB / 2,000,000 | 15m / 2h / 6h / 45s | `/wm-api/runtime/transport/global-shipping?limit=14` | stale；2026-11-10T03:13:26.363167Z |
| [cpi-release-command-center](../webpage/src/panels/modules/cpi-release-command-center/index.tsx) | `macro:cpi-release-command-center:latest:v2`<br>IDB+LS / 256,000 | 30m / 45m / 18h / 45s | `/wm-api/runtime/macro/cpi-release-command-center?limit=36` | degraded；2026-11-10T06:07:28.773614Z |
| [cpi-components-pressure-registry](../webpage/src/panels/modules/cpi-components-pressure-registry/index.tsx) | `macro:cpi-components-pressure-registry:latest:v2`<br>IDB+LS / 256,000 | 30m / 45m / 18h / 45s | `/wm-api/runtime/macro/cpi-components-pressure-registry?limit=48` | ok；2026-11-10T06:07:29.264035Z |
| [goods-tariff-supply-watch](../webpage/src/panels/modules/goods-tariff-supply-watch/index.tsx) | `macro:goods-tariff-supply-watch:latest:v2`<br>IDB+LS / 256,000 | 30m / 45m / 18h / 45s | `/wm-api/runtime/macro/goods-tariff-supply-watch?limit=36` | ok；2026-11-10T06:07:29.748566Z |
| [labor-services-inflation-monitor](../webpage/src/panels/modules/labor-services-inflation-monitor/index.tsx) | `macro:labor-services-inflation-monitor:latest:v2`<br>IDB+LS / 256,000 | 30m / 45m / 18h / 45s | `/wm-api/runtime/macro/labor-services-inflation-monitor?limit=36` | ok；2026-11-10T06:07:30.123779Z |
| [fed-reaction-growth-risk-board](../webpage/src/panels/modules/fed-reaction-growth-risk-board/index.tsx) | `macro:fed-reaction-growth-risk-board:latest:v2`<br>IDB+LS / 256,000 | 30m / 45m / 18h / 45s | `/wm-api/runtime/macro/fed-reaction-growth-risk-board?limit=36` | degraded；2026-11-10T06:07:30.541918Z |
| [polymarket-macro-map](../webpage/src/panels/modules/polymarket-macro-map/index.tsx)（默认关闭） | `macro:polymarket-macro-map:outcomes:v2`<br>IDB+LS / 256,000 | 3m / 3m / 2h / 45s | `/wm-api/runtime/macro/polymarket-map?limit=12` | degraded；2026-11-10T06:25:28.810633Z |
| [cpi-release-calendar](../webpage/src/panels/modules/cpi-release-calendar/index.tsx)（默认关闭） | `public:cpi-release-calendar:limit:8:v1`<br>IDB+LS / 256,000 | 1h / 3h / 3h / 45s | `/wm-api/runtime/macro/cpi-release-calendar?limit=8` | degraded；2026-11-10T06:07:34.101632Z |
| [energy-gasoline-shock](../webpage/src/panels/modules/energy-gasoline-shock/index.tsx)（默认关闭） | `public:energy-gasoline-shock:limit:6:v1`<br>IDB+LS / 256,000 | 6h / 18h / 18h / 45s | `/wm-api/runtime/macro/energy-gasoline-shock?limit=6` | ok；2026-11-10T02:05:43.442011Z |
| [global-temperature-monitor](../webpage/src/panels/registry.tsx) | `public:global-temperature-monitor:limit:60:v1`<br>IDB / 4,000,000 | 1m / 2h / 1d / 1m | `/wm-api/runtime/weather/temperature-monitor?limit=60` | degraded；2026-11-10T06:07:31.259919Z |
| [weather-news](../webpage/src/panels/modules/weather-news/index.tsx) | `public:weather-news:limit:24:v1`<br>IDB+LS / 256,000 | 5m / 15m / 1d / 45s | `/wm-api/runtime/weather/news?limit=24` | stale；2026-11-10T03:24:41.118531Z |
| [food-retail-basket-pressure](../webpage/src/panels/modules/food-retail-basket-pressure/index.tsx)（默认关闭） | `macro:food-retail-basket-pressure:latest:v2`<br>IDB+LS / 256,000 | 6h / 45m / 18h / 45s | `/wm-api/runtime/macro/food-retail-basket?limit=8` | degraded；2026-11-10T06:07:29.563139Z |
| [supply-tariff-import-watch](../webpage/src/panels/modules/supply-tariff-import-watch/index.tsx)（默认关闭） | `macro:supply-tariff-import-watch:latest:v2`<br>IDB+LS / 256,000 | 6h / 45m / 18h / 45s | `/wm-api/runtime/macro/supply-tariff-import-watch?limit=8` | degraded；2026-11-10T06:07:30.689226Z |
| [shelter-rent-oer-pressure](../webpage/src/panels/modules/shelter-rent-oer-pressure/index.tsx)（默认关闭） | `macro:shelter-rent-oer-pressure:latest:v2`<br>IDB+LS / 256,000 | 6h / 45m / 18h / 45s | `/wm-api/runtime/macro/shelter-rent-oer-pressure?limit=8` | degraded；2026-11-10T06:07:30.705990Z |
| [labor-wage-services-pressure](../webpage/src/panels/modules/labor-wage-services-pressure/index.tsx)（默认关闭） | `macro:labor-wage-services-pressure:latest:v2`<br>IDB+LS / 256,000 | 6h / 45m / 18h / 45s | `/wm-api/runtime/macro/labor-wage-services-pressure?limit=8` | degraded；2026-11-10T06:07:30.739283Z |
| [growth-demand-recession-tracker](../webpage/src/panels/modules/growth-demand-recession-tracker/index.tsx)（默认关闭） | `macro:growth-demand-recession-tracker:latest:v2`<br>IDB+LS / 256,000 | 6h / 45m / 18h / 45s | `/wm-api/runtime/macro/growth-demand-recession-tracker?limit=8` | degraded；2026-11-10T06:07:30.755185Z |
| [inflation-nowcast](../webpage/src/panels/modules/inflation-nowcast/index.tsx)（默认关闭） | `public:inflation-nowcast:v1`<br>IDB+LS / 256,000 | 30m / 90m / 90m / 45s | `/wm-api/runtime/macro/inflation-nowcast` | ok；2026-11-10T06:07:34.084041Z |
| [fed-rates-polymarket-gap](../webpage/src/panels/modules/fed-rates-polymarket-gap/index.tsx)（默认关闭） | `macro:fed-rates-polymarket-gap:latest:v2`<br>IDB+LS / 256,000 | 6h / 45m / 18h / 45s | `/wm-api/runtime/macro/fed-rates-polymarket-gap?limit=8` | degraded；2026-11-10T06:07:30.770136Z |
| [nba-scoreboard](../webpage/src/panels/modules/nba-scoreboard/index.tsx) | `public-feed:nba-scoreboard:limit:10:v1`<br>IDB+LS / 128,000 | 1m / 3m / 1d / 45s | `/wm-api/runtime/sports/nba?limit=10` | ok；2026-11-10T06:26:05.135420Z |
| [nba-intel](../webpage/src/panels/modules/nba-intel/index.tsx) | `public-feed:nba-intel:limit:12:v1`<br>IDB+LS / 128,000 | 1m / 3m / 1d / 45s | `/wm-api/runtime/sports/nba-intel?limit=12` | ok；2026-11-10T06:10:35.668685Z |
| [espn-matchup-predictor](../webpage/src/panels/modules/espn-matchup-predictor/index.tsx) | `public-feed:espn-matchup-predictor:limit:8:v1`<br>IDB+LS / 128,000 | 1m / 3m / 1d / 45s | `/wm-api/runtime/sports/nba-matchup-predictor?limit=8` | ok；2026-11-10T06:10:38.640603Z |
| [esports-intel](../webpage/src/panels/modules/esports-intel/index.tsx) | `bookmakers:esports-intel:10:v1`<br>IDB / 600,000 | 2m / 30m / 1d / 45s | `/wm-api/runtime/esports/grid-intel?limit=10` | degraded；2026-11-10T06:10:28.879671+00:00 |
| [sports-odds](../webpage/src/panels/modules/sports-odds/index.tsx) | `bookmakers:sports-odds:8:v1`<br>IDB / 600,000 | 5m / 30m / 1d / 45s | `/wm-api/runtime/sports/odds-monitor?limit=8` | degraded；2026-11-10T06:11:05.019341+00:00 |
| [jin10-flash](../webpage/src/panels/modules/jin10-flash/index.tsx) | `public-feed:jin10-flash:limit:24:v1`<br>IDB+LS / 128,000 | 1m / 5m / 1d / 45s | `/wm-api/runtime/macro/jin10?limit=24` | ok；2026-11-10T14:10:33.984069+08:00 |
| [new-market-signals](../webpage/src/panels/modules/new-market-signals/index.tsx) | `public-feed:new-market-signals:limit:12:v1`<br>IDB+LS / 128,000 | 5m / 15m / 1d / 45s | `/wm-api/runtime/markets/new-signals?limit=12` | stale；2026-11-10T03:26:38.367840Z |
| [f1-trackside](../webpage/src/panels/modules/f1-trackside/index.tsx) | `public-feed:f1-trackside:limit:10:v1`<br>IDB+LS / 128,000 | 3m / 5m / 1d / 45s | `/wm-api/runtime/sports/f1?limit=10` | ok；2026-11-10T06:08:30.569442Z |
| [company-events](../webpage/src/panels/modules/company-events/index.tsx) | `official-disclosures:company-events:v1`<br>IDB+LS / 240,000 | 10m / 1d / 7d / 15s | `/wm-api/runtime/disclosures/company-events` | degraded；2026-11-10T03:20:38.873389+00:00 |
| [policy-progress](../webpage/src/panels/modules/policy-progress/index.tsx) | `official-disclosures:policy-progress:v1`<br>IDB+LS / 240,000 | 10m / 1d / 7d / 15s | `/wm-api/runtime/disclosures/policy-progress` | ok；2026-11-10T06:07:36.363207+00:00 |
| [politics-election](../webpage/src/panels/modules/politics-election/index.tsx) | `politics:politics-election:v1`<br>IDB+LS / 220,000 | 10m / 3h / 7d / 15s | `/wm-api/runtime/politics/election` | ok；2026-11-10T06:08:55.787009+00:00 |
| [politics-early-vote](../webpage/src/panels/modules/politics-early-vote/index.tsx) | `politics:politics-early-vote:v1`<br>IDB+LS / 220,000 | 10m / 3h / 7d / 15s | `/wm-api/runtime/politics/early-vote` | ok；2026-11-10T06:07:45.554550+00:00 |
| [politics-nomination](../webpage/src/panels/modules/politics-nomination/index.tsx) | `politics:politics-nomination:v1`<br>IDB+LS / 220,000 | 10m / 3d / 7d / 15s | `/wm-api/runtime/politics/nomination` | ok；2026-11-10T02:55:11.278429+00:00 |
| [politics-seats](../webpage/src/panels/modules/politics-seats/index.tsx) | `politics:politics-seats:v1`<br>IDB+LS / 220,000 | 10m / 90m / 7d / 15s | `/wm-api/runtime/politics/seats` | ok；2026-11-10T06:07:31.612919+00:00 |
| [politics-campaign-finance](../webpage/src/panels/modules/politics-campaign-finance/index.tsx) | `politics:politics-campaign-finance:v1`<br>IDB+LS / 220,000 | 30m / 18h / 7d / 15s | `/wm-api/runtime/politics/campaign-finance` | degraded；2026-11-10T03:10:52.769999+00:00 |
| [politics-government](../webpage/src/panels/modules/politics-government/index.tsx) | `politics:politics-government:v1`<br>IDB+LS / 220,000 | 10m / 90m / 7d / 15s | `/wm-api/runtime/politics/government` | ok；2026-11-10T06:07:31.612919+00:00 |
| [politics-executive](../webpage/src/panels/modules/politics-executive/index.tsx) | `politics:politics-executive:v1`<br>IDB+LS / 220,000 | 10m / 1d / 7d / 15s | `/wm-api/runtime/politics/executive` | ok；2026-11-10T06:07:36.872435+00:00 |
| [politics-appointments](../webpage/src/panels/modules/politics-appointments/index.tsx) | `politics:politics-appointments:v1`<br>IDB+LS / 220,000 | 10m / 90m / 7d / 15s | `/wm-api/runtime/politics/appointments` | ok；2026-11-10T06:07:41.967481+00:00 |
| [politics-funding](../webpage/src/panels/modules/politics-funding/index.tsx) | `politics:politics-funding:v1`<br>IDB+LS / 220,000 | 5m / 90m / 7d / 15s | `/wm-api/runtime/politics/funding` | ok；2026-11-10T06:07:34.941308+00:00 |
| [geo-conflict-watch](../webpage/src/panels/modules/geo-conflict-watch/index.tsx) | `external:geo-conflict-watch:v1`<br>IDB+LS / 200,000 | 10m / 3h / 7d / 20s | `/wm-api/runtime/external/geo-conflict-watch` | ok；2026-11-10T06:09:33.922622Z |
| [geo-ceasefire-watch](../webpage/src/panels/modules/geo-ceasefire-watch/index.tsx) | `external:geo-ceasefire-watch:v1`<br>IDB+LS / 200,000 | 10m / 3h / 7d / 20s | `/wm-api/runtime/external/geo-ceasefire-watch` | ok；2026-11-10T06:09:01.385399+00:00 |
| [geo-territory-control](../webpage/src/panels/modules/geo-territory-control/index.tsx) | `external:geo-territory-control:v1`<br>IDB+LS / 200,000 | 10m / 3h / 7d / 20s | `/wm-api/runtime/external/geo-territory-control` | ok；2026-11-10T06:09:01.385399+00:00 |
| [geo-diplomacy-calendar](../webpage/src/panels/modules/geo-diplomacy-calendar/index.tsx) | `external:geo-diplomacy-calendar:v1`<br>IDB+LS / 200,000 | 10m / 3h / 7d / 20s | `/wm-api/runtime/external/geo-diplomacy-calendar` | ok；2026-11-10T06:09:01.385399+00:00 |
| [geo-treaty-tracker](../webpage/src/panels/modules/geo-treaty-tracker/index.tsx) | `external:geo-treaty-tracker:v1`<br>IDB+LS / 200,000 | 1h / 3d / 14d / 20s | `/wm-api/runtime/external/geo-treaty-tracker` | ok；2026-11-09T08:12:20.091065+00:00 |
| [weather-precipitation](../webpage/src/panels/modules/weather-precipitation/index.tsx) | `external:weather-precipitation:v1`<br>IDB+LS / 200,000 | 10m / 2h / 6h / 20s | `/wm-api/runtime/external/weather-precipitation` | ok；2026-11-10T06:07:31.259919Z |
| [weather-drought](../webpage/src/panels/modules/weather-drought/index.tsx) | `external:weather-drought:v1`<br>IDB+LS / 200,000 | 1h / 3d / 14d / 20s | `/wm-api/runtime/external/weather-drought` | ok；2026-11-09T08:03:58.056204+00:00 |
| [weather-extremes](../webpage/src/panels/modules/weather-extremes/index.tsx) | `external:weather-extremes:v1`<br>IDB+LS / 200,000 | 5m / 10m / 15m / 20s | `/wm-api/runtime/external/weather-extremes` | ok；2026-11-10T06:10:52.061581Z；前端拒收:Error: Source component exceeds its original retention |
| [weather-storm-advisory](../webpage/src/panels/modules/weather-storm-advisory/index.tsx) | `external:weather-storm-advisory:v1`<br>IDB+LS / 200,000 | 10m / 30m / 1h / 20s | `/wm-api/runtime/external/weather-storm-advisory` | ok；2026-11-10T06:09:14.086309Z |
| [sports-spread-monitor](../webpage/src/panels/modules/sports-spread-monitor/index.tsx) | `external:sports-spread-monitor:v1`<br>IDB+LS / 200,000 | 10m / 30m / 1d / 20s | `/wm-api/runtime/external/sports-spread-monitor` | degraded；2026-11-10T03:25:49.216095+00:00 |
| [sports-total-monitor](../webpage/src/panels/modules/sports-total-monitor/index.tsx) | `external:sports-total-monitor:v1`<br>IDB+LS / 200,000 | 10m / 30m / 1d / 20s | `/wm-api/runtime/external/sports-total-monitor` | degraded；2026-11-10T03:25:49.216095+00:00 |
| [sports-player-props](../webpage/src/panels/modules/sports-player-props/index.tsx) | `external:sports-player-props:v1`<br>IDB+LS / 200,000 | 10m / 30m / 1d / 20s | `/wm-api/runtime/external/sports-player-props` | degraded；2026-11-10T03:25:49.216095+00:00 |
| [sports-tournament-path](../webpage/src/panels/modules/sports-tournament-path/index.tsx) | `external:sports-tournament-path:v1`<br>IDB+LS / 200,000 | 10m / 45m / 1d / 20s | `/wm-api/runtime/external/sports-tournament-path` | ok；2026-11-10T06:09:10.145238+00:00 |
| [sports-season-race](../webpage/src/panels/modules/sports-season-race/index.tsx) | `external:sports-season-race:v1`<br>IDB+LS / 200,000 | 10m / 18h / 3d / 20s | `/wm-api/runtime/external/sports-season-race` | ok；2026-11-10T02:23:29.619944+00:00 |
| [sports-awards-watch](../webpage/src/panels/modules/sports-awards-watch/index.tsx) | `external:sports-awards-watch:v1`<br>IDB+LS / 200,000 | 30m / 18h / 3d / 20s | `/wm-api/runtime/external/sports-awards-watch` | ok；2026-11-10T02:23:30.932814+00:00 |
| [esports-map-state](../webpage/src/panels/modules/esports-map-state/index.tsx) | `external:esports-map-state:v1`<br>IDB+LS / 200,000 | 10m / 45m / 1d / 20s | `/wm-api/runtime/external/esports-map-state` | degraded；2026-11-10T03:15:27.004204+00:00 |
| [esports-tournament-path](../webpage/src/panels/modules/esports-tournament-path/index.tsx) | `external:esports-tournament-path:v1`<br>IDB+LS / 200,000 | 10m / 45m / 1d / 20s | `/wm-api/runtime/external/esports-tournament-path` | ok；2026-11-10T06:09:12.390193+00:00 |
| [crypto-listing-watch](../webpage/src/panels/modules/crypto-listing-watch/index.tsx) | `external:crypto-listing-watch:v1`<br>IDB+LS / 200,000 | 5m / 15m / 30m / 20s | `/wm-api/runtime/external/crypto-listing-watch` | ok；2026-11-10T06:09:26.603854+00:00 |
| [crypto-project-milestones](../webpage/src/panels/modules/crypto-project-milestones/index.tsx) | `external:crypto-project-milestones:v1`<br>IDB+LS / 200,000 | 10m / 90m / 7d / 20s | `/wm-api/runtime/external/crypto-project-milestones` | ok；2026-11-10T06:09:21.862776+00:00 |
| [chain-metrics-monitor](../webpage/src/panels/modules/chain-metrics-monitor/index.tsx) | `external:chain-metrics-monitor:v1`<br>IDB+LS / 200,000 | 15m / 3h / 1d / 20s | `/wm-api/runtime/external/chain-metrics-monitor` | ok；2026-11-10T06:09:21.024080+00:00 |
| [fiscal-tax-monitor](../webpage/src/panels/modules/fiscal-tax-monitor/index.tsx) | `external:fiscal-tax-monitor:v1`<br>IDB+LS / 200,000 | 30m / 1d / 7d / 20s | `/wm-api/runtime/external/fiscal-tax-monitor` | ok；2026-11-10T06:09:09.570235+00:00 |
| [merger-progress](../webpage/src/panels/modules/merger-progress/index.tsx) | `external:merger-progress:v1`<br>IDB+LS / 200,000 | 15m / 90m / 1d / 20s | `/wm-api/runtime/external/merger-progress` | degraded；2026-11-10T03:01:22.518713+00:00 |
| [private-valuation-watch](../webpage/src/panels/modules/private-valuation-watch/index.tsx) | `external:private-valuation-watch:v1`<br>IDB+LS / 200,000 | 30m / 12h / 7d / 20s | `/wm-api/runtime/external/private-valuation-watch` | ok；2026-11-10T03:16:51.867925+00:00 |
| [ai-leaderboard-watch](../webpage/src/panels/modules/ai-leaderboard-watch/index.tsx) | `external:ai-leaderboard-watch:v1`<br>IDB+LS / 200,000 | 30m / 1d / 7d / 20s | `/wm-api/runtime/external/ai-leaderboard-watch` | ok；2026-11-10T06:09:12.466943+00:00 |
| [art-auction-watch](../webpage/src/panels/modules/art-auction-watch/index.tsx) | `external:art-auction-watch:v1`<br>IDB+LS / 200,000 | 30m / 1d / 7d / 20s | `/wm-api/runtime/external/art-auction-watch` | ok；2026-11-10T06:09:18.152961+00:00 |
| [culture-box-office](../webpage/src/panels/modules/culture-box-office/index.tsx) | `external:culture-box-office:v1`<br>IDB+LS / 200,000 | 30m / 1d / 14d / 20s | `/wm-api/runtime/external/culture-box-office` | ok；2026-11-10T06:09:57.534812+00:00 |
| [culture-awards-race](../webpage/src/panels/modules/culture-awards-race/index.tsx) | `external:culture-awards-race:v1`<br>IDB+LS / 200,000 | 30m / 1d / 7d / 20s | `/wm-api/runtime/external/culture-awards-race` | ok；2026-11-10T06:09:26.120318+00:00 |
| [culture-music-charts](../webpage/src/panels/modules/culture-music-charts/index.tsx) | `external:culture-music-charts:v1`<br>IDB+LS / 200,000 | 30m / 1d / 7d / 20s | `/wm-api/runtime/external/culture-music-charts` | ok；2026-11-10T03:09:12.730586+00:00 |
| [product-release-watch](../webpage/src/panels/modules/product-release-watch/index.tsx) | `external:product-release-watch:v1`<br>IDB+LS / 200,000 | 10m / 3h / 7d / 20s | `/wm-api/runtime/external/product-release-watch` | ok；2026-11-10T06:09:35.717564+00:00 |
| [public-figure-events](../webpage/src/panels/modules/public-figure-events/index.tsx) | `external:public-figure-events:v1`<br>IDB+LS / 200,000 | 10m / 3h / 7d / 20s | `/wm-api/runtime/external/public-figure-events` | ok；2026-11-10T06:09:32.821648+00:00 |
| [reality-show-progress](../webpage/src/panels/modules/reality-show-progress/index.tsx) | `external:reality-show-progress:v1`<br>IDB+LS / 200,000 | 30m / 1d / 7d / 20s | `/wm-api/runtime/external/reality-show-progress` | ok；2026-11-10T06:09:23.151901+00:00 |
| [research-evidence-watch](../webpage/src/panels/modules/research-evidence-watch/index.tsx) | `external:research-evidence-watch:v1`<br>IDB+LS / 200,000 | 30m / 1d / 7d / 20s | `/wm-api/runtime/external/research-evidence-watch` | ok；2026-11-10T06:09:48.673231+00:00 |
| [social-window-monitor](../webpage/src/panels/modules/social-window-monitor/index.tsx) | `external:social-window-monitor:v1`<br>IDB+LS / 200,000 | 10m / 3h / 1d / 20s | `/wm-api/runtime/external/social-window-monitor` | ok；2026-11-10T06:09:39.549367+00:00 |
| [space-mission-watch](../webpage/src/panels/modules/space-mission-watch/index.tsx) | `external:space-mission-watch:v1`<br>IDB+LS / 200,000 | 10m / 3h / 7d / 20s | `/wm-api/runtime/external/space-mission-watch` | ok；2026-11-10T06:09:32.019068+00:00 |
| [mentions-evidence](../webpage/src/panels/modules/mentions-evidence/index.tsx) | `external:mentions-evidence:v1`<br>IDB+LS / 200,000 | 10m / 3h / 7d / 20s | `/wm-api/runtime/external/mentions-evidence` | ok；2026-11-10T06:09:32.821648+00:00 |

### 7个复用视图

这7个Panel不产生独立副本或采集器，复用global-temperature-monitor的请求、时钟和缓存。World Clock自身每秒钟的动画不代表每秒拉天气。

| Panel | owner | 独立请求/缓存 |
| --- | --- | --- |
| weather-market-browser | global-temperature-monitor | 无；复用owner |
| weather-city-snapshot | global-temperature-monitor | 无；复用owner |
| weather-quote-detail | global-temperature-monitor | 无；复用owner |
| weather-quote-table | global-temperature-monitor | 无；复用owner |
| weather-trend-detail | global-temperature-monitor | 无；复用owner |
| weather-trend-7d | global-temperature-monitor | 无；复用owner |
| world-clock | global-temperature-monitor | 无；复用owner |

### 21个参数化／上下文／静态Panel（没有遗漏出分母）

| Panel | 实际拥有者、身份及展示规则 |
| --- | --- |
| active-markets | marketCatalogResource(sort)；page1/50/active/sort，搜索另外按query隔离、180ms防抖；目录过期15m后不再充当当前市场列表。 |
| global-orderfilled | 实际是FocusedMarketStrip/useMarketFocus的选中市场Flow（registry旧description写cross-market不准确）；按marketId隔离，10s读取/初始1s，失败最多保留60s，内存。 |
| oracle-feed | useMarketFocus selectedOracle；按marketId隔离，20s检查；失败保留原数据最多120s，内存。 |
| market-summary | marketDetailResource(id)的已校验元数据，LOB使用单独实时owner，禁止持久化整份交易bundle。 |
| featured-market | 与market-summary同一个选择/元数据owner；不复制采集。 |
| price-chart | marketChartResource(id,range)；2M字符IDB，源时间90s变旧、300s到期。 |
| related-news | useIntelResource(marketId,scope,days)；key含市场/全局/7或30天；检查5m/fresh15m/恢复30m；v4/512k；每条expires_at仍剔除，来源失败不能冒充空。 |
| alpha-signal | alphaResource，见下表；current ownership/label verification与readIntegrity撤销优先，不能恢复失效方向。 |
| whale-tracker | whaleResource，见下表；规范链上成交，不把大额启发式当做已验证鲸鱼身份。 |
| suspicious-flow | flowResource，见下表；Oracle窗口与大额成交分开，旧source不能用新GET时间续期。 |
| commodities-watch | commodityResource，见下表；closed previous-close与盘中观察分开，每条源失败/保留状态独立；较差覆盖不能覆盖last good。 |
| crypto-watch | 组件实际消费共享cryptoStrategyResource（图表与合同）；另存cryptoResource用于全币种概览，不能把二者当同一key。 |
| crypto-order-flow | cryptoStrategyResource；四资产共用输入快照，逐交易/盘口源时间继续限制。 |
| crypto-oracle-reference | cryptoReferenceResource，cache:null；恢复页面必须重新验证当前合约绑定与指定源。 |
| options-implied-probability | cryptoStrategyResource；期权分布必须满足instrument/expiry/source条件，不把无分布改成0。 |
| crypto-exchange-inflow | cryptoHistoryResource；只读已有历史文件，bootstrap/manual，不宣称实时链上流入。 |
| crypto-funding-watch | fundingResource；估计费率、结算周期和报价资格独立，15m副本不能无限保留。 |
| crypto-perp-funding | cryptoStrategyResource；OI/basis按asset/window取投影，无额外同源采集。 |
| stablecoin-monitor | cryptoStrategyResource；USD source与连续脱锚时长单独验证，gap重置持续时间。 |
| trade-policy-radar | 静态ALERTS示例，无数据owner/API/缓存；此次去掉LIVE标记，实时化尚未实现。 |
| lob-depth | orderBookResource(marketId,yesToken,noToken)，cache:null；2s检查/3.5s总期限；双边identity和原source/heartbeat必验。 |

参数化资源求值（550186是示例市场；实际key随参数改变；不持久化登录或私有数据）：

| 完整key示例 | 检查 / fresh / 恢复 / 总期限 | cache / cap | GET |
| --- | --- | --- | --- |
| `markets:active:page:1:limit:50:sort:volume:v1` | 5m / 5m / 15m / 30s | v1 / 256,000，IDB+LS | `/wm-api/markets?page=1&pageSize=50&status=active&sort=volume` |
| `market-detail:550186:v1` | 1m / 1m / 5m / 45s | v1 / 256,000，IDB+LS | `/wm-api/markets/550186/focus-tile` |
| `market-chart:550186:range:1d:interval:auto:v1` | 90s / 90s / 5m / 10s | v1 / 2,000,000，IDB | `/wm-api/markets/550186/chart?range=1d&interval=5m` |
| `market-book:v1:<id>:<yes>:<no>` | 2s / 30s / 30s / 3500ms | null，内存 | `/wm-api/runtime/lob/token/<YES/NO token>?marketId=<id>&_ts=<request>` |
| `crypto-strategy:four-assets:v1` | 30s / 2m / 15m / 45s | v1 / 1,000,000，IDB | `/wm-api/runtime/crypto/order-flow` |
| `crypto-history:exchange-inflows:v1` | 0（不轮询） / 1d / 1d / 45s | v1 / 1,000,000，IDB | `/wm-api/runtime/crypto/order-flow` |
| `crypto-reference:market-data:v1` | 5s / 15s / 15m / 12s | null，内存 | `/wm-api/runtime/crypto/oracle-reference` |
| `alpha-signal:global:token-flow-v1:8` | 2m / 5m / 15m / 45s | v2 / 96,000，IDB+LS | `/wm-api/runtime/signals/alpha?limit=8` |
| `whale-tracker:global:trade-watch-v1:14` | 2m / 5m / 15m / 45s | v1 / 96,000，IDB+LS | `/wm-api/runtime/trades/whales?limit=14` |
| `suspicious-flow:global:trade-watch-v1:12` | 2m / 5m / 15m / 45s | v1 / 96,000，IDB+LS | `/wm-api/runtime/trades/suspicious?limit=12` |
| `commodities:global:previous-close:v4` | 5m / 15m / 15m / 45s | v4 / 192,000，IDB+LS | `/wm-api/runtime/markets/commodities` |
| `crypto:global:rolling-24h:v1` | 5m / 15m / 15m / 45s | v1 / 128,000，IDB+LS | `/wm-api/runtime/markets/crypto` |
| `funding:usdt-perpetual:latest:v3` | 1m / 3m / 15m / 10s | v3 / 512,000，IDB+LS | `/wm-api/runtime/crypto/funding-watch?limit=120` |

### 后端拥有者／存储投影入口（与93项一一对应）

下面是实际runtime module绑定，getter中的同名领域服务负责存储key、逐源规则和采集器复用。来源部分参数来自 payload 的 sources，而不是从前端轮询间隔猜测；当前部署与源码可能存在差异。

| Panel | API module | getter |
| --- | --- | --- |
| price-implications | 由专门版本化API读取，见前端fetchData | `专门API/共享投影` |
| sample-chain-trades | 由专门版本化API读取，见前端fetchData | `专门API/共享投影` |
| oracle-timeline | 由专门版本化API读取，见前端fetchData | `专门API/共享投影` |
| breaking-event-radar | [breaking_event_radar.py](../scripts/api/runtime_panels/modules/breaking_event_radar.py) | `get_breaking_event_radar_snapshot` |
| market-tv-wire | [market_tv_wire.py](../scripts/api/runtime_panels/modules/market_tv_wire.py) | `get_market_tv_wire_snapshot` |
| market-youtube-channels | [market_youtube_channels.py](../scripts/api/runtime_panels/modules/market_youtube_channels.py) | `get_market_youtube_channels_snapshot` |
| ai-model-race | [ai_model_race.py](../scripts/api/runtime_panels/modules/ai_model_race.py) | `专门API/共享投影` |
| big-tech-market-cap | [big_tech_market_cap.py](../scripts/api/runtime_panels/modules/big_tech_market_cap.py) | `专门API/共享投影` |
| consumer-app-pulse | [consumer_app_pulse.py](../scripts/api/runtime_panels/modules/consumer_app_pulse.py) | `专门API/共享投影` |
| defi-token-watch | [defi_token_watch.py](../scripts/api/runtime_panels/modules/defi_token_watch.py) | `专门API/共享投影` |
| defi-yield-monitor | [defi_yield_monitor.py](../scripts/api/runtime_panels/modules/defi_yield_monitor.py) | `专门API/共享投影` |
| defi-security-watch | [defi_security_watch.py](../scripts/api/runtime_panels/modules/defi_security_watch.py) | `专门API/共享投影` |
| tradfi-perp-radar | [tradfi_perp_radar.py](../scripts/api/runtime_panels/modules/tradfi_perp_radar.py) | `专门API/共享投影` |
| ipo-news-watch | [ipo_news_watch.py](../scripts/api/runtime_panels/modules/ipo_news_watch.py) | `专门API/共享投影` |
| broker-research-watch | [broker_research_watch.py](../scripts/api/runtime_panels/modules/broker_research_watch.py) | `专门API/共享投影` |
| global-index-monitor | [global_index_monitor.py](../scripts/api/runtime_panels/modules/global_index_monitor.py) | `专门API/共享投影` |
| commodity-equity-transmission | [commodity_equity_transmission.py](../scripts/api/runtime_panels/modules/commodity_equity_transmission.py) | `专门API/共享投影` |
| crypto-fear-greed | [crypto_fear_greed.py](../scripts/api/runtime_panels/modules/crypto_fear_greed.py) | `专门API/共享投影` |
| crypto-etf-flow | [crypto_etf_flow.py](../scripts/api/runtime_panels/modules/crypto_etf_flow.py) | `专门API/共享投影` |
| blockchain-policy-news | [blockchain_policy_news.py](../scripts/api/runtime_panels/modules/blockchain_policy_news.py) | `专门API/共享投影` |
| geo-sanctions-shock | [geo_sanctions_shock.py](../scripts/api/runtime_panels/modules/geo_sanctions_shock.py) | `专门API/共享投影` |
| global-transport-shipping | [global_transport_shipping.py](../scripts/api/runtime_panels/modules/global_transport_shipping.py) | `专门API/共享投影` |
| cpi-release-command-center | [cpi_release_command_center.py](../scripts/api/runtime_panels/modules/cpi_release_command_center.py) | `专门API/共享投影` |
| cpi-components-pressure-registry | [cpi_components_pressure_registry.py](../scripts/api/runtime_panels/modules/cpi_components_pressure_registry.py) | `专门API/共享投影` |
| goods-tariff-supply-watch | [goods_tariff_supply_watch.py](../scripts/api/runtime_panels/modules/goods_tariff_supply_watch.py) | `专门API/共享投影` |
| labor-services-inflation-monitor | [labor_services_inflation_monitor.py](../scripts/api/runtime_panels/modules/labor_services_inflation_monitor.py) | `专门API/共享投影` |
| fed-reaction-growth-risk-board | [fed_reaction_growth_risk_board.py](../scripts/api/runtime_panels/modules/fed_reaction_growth_risk_board.py) | `专门API/共享投影` |
| polymarket-macro-map | [polymarket_macro_map.py](../scripts/api/runtime_panels/modules/polymarket_macro_map.py) | `专门API/共享投影` |
| cpi-release-calendar | [cpi_release_calendar.py](../scripts/api/runtime_panels/modules/cpi_release_calendar.py) | `专门API/共享投影` |
| energy-gasoline-shock | [energy_gasoline_shock.py](../scripts/api/runtime_panels/modules/energy_gasoline_shock.py) | `专门API/共享投影` |
| global-temperature-monitor | [global_temperature_monitor.py](../scripts/api/runtime_panels/modules/global_temperature_monitor.py) | `get_global_weather_map_snapshot` |
| weather-news | [weather_news.py](../scripts/api/runtime_panels/modules/weather_news.py) | `get_weather_news_snapshot` |
| food-retail-basket-pressure | [food_retail_basket.py](../scripts/api/runtime_panels/modules/food_retail_basket.py) | `专门API/共享投影` |
| supply-tariff-import-watch | [supply_tariff_import_watch.py](../scripts/api/runtime_panels/modules/supply_tariff_import_watch.py) | `专门API/共享投影` |
| shelter-rent-oer-pressure | [shelter_rent_oer_pressure.py](../scripts/api/runtime_panels/modules/shelter_rent_oer_pressure.py) | `专门API/共享投影` |
| labor-wage-services-pressure | [labor_wage_services_pressure.py](../scripts/api/runtime_panels/modules/labor_wage_services_pressure.py) | `专门API/共享投影` |
| growth-demand-recession-tracker | [growth_demand_recession_tracker.py](../scripts/api/runtime_panels/modules/growth_demand_recession_tracker.py) | `专门API/共享投影` |
| inflation-nowcast | [inflation_nowcast.py](../scripts/api/runtime_panels/modules/inflation_nowcast.py) | `专门API/共享投影` |
| fed-rates-polymarket-gap | [fed_rates_polymarket_gap.py](../scripts/api/runtime_panels/modules/fed_rates_polymarket_gap.py) | `专门API/共享投影` |
| nba-scoreboard | [nba_scoreboard.py](../scripts/api/runtime_panels/modules/nba_scoreboard.py) | `专门API/共享投影` |
| nba-intel | [nba_intel.py](../scripts/api/runtime_panels/modules/nba_intel.py) | `专门API/共享投影` |
| espn-matchup-predictor | [espn_matchup_predictor.py](../scripts/api/runtime_panels/modules/espn_matchup_predictor.py) | `专门API/共享投影` |
| esports-intel | [esports_intel.py](../scripts/api/runtime_panels/modules/esports_intel.py) | `专门API/共享投影` |
| sports-odds | [sports_odds.py](../scripts/api/runtime_panels/modules/sports_odds.py) | `专门API/共享投影` |
| jin10-flash | [jin10_flash.py](../scripts/api/runtime_panels/modules/jin10_flash.py) | `专门API/共享投影` |
| new-market-signals | [new_market_signals.py](../scripts/api/runtime_panels/modules/new_market_signals.py) | `get_new_market_signals_snapshot` |
| f1-trackside | [f1_trackside.py](../scripts/api/runtime_panels/modules/f1_trackside.py) | `专门API/共享投影` |
| company-events | [company_events.py](../scripts/api/runtime_panels/modules/company_events.py) | `get_official_disclosures_snapshot` |
| policy-progress | [policy_progress.py](../scripts/api/runtime_panels/modules/policy_progress.py) | `get_official_disclosures_snapshot` |
| politics-election | [politics_election.py](../scripts/api/runtime_panels/modules/politics_election.py) | `get_politics_snapshot` |
| politics-early-vote | [politics_early_vote.py](../scripts/api/runtime_panels/modules/politics_early_vote.py) | `get_politics_snapshot` |
| politics-nomination | [politics_nomination.py](../scripts/api/runtime_panels/modules/politics_nomination.py) | `get_politics_snapshot` |
| politics-seats | [politics_seats.py](../scripts/api/runtime_panels/modules/politics_seats.py) | `get_politics_snapshot` |
| politics-campaign-finance | [politics_campaign_finance.py](../scripts/api/runtime_panels/modules/politics_campaign_finance.py) | `get_politics_snapshot` |
| politics-government | [politics_government.py](../scripts/api/runtime_panels/modules/politics_government.py) | `get_politics_snapshot` |
| politics-executive | [politics_executive.py](../scripts/api/runtime_panels/modules/politics_executive.py) | `get_politics_snapshot` |
| politics-appointments | [politics_appointments.py](../scripts/api/runtime_panels/modules/politics_appointments.py) | `get_politics_snapshot` |
| politics-funding | [politics_funding.py](../scripts/api/runtime_panels/modules/politics_funding.py) | `get_politics_snapshot` |
| geo-conflict-watch | [geo_conflict_watch.py](../scripts/api/runtime_panels/modules/geo_conflict_watch.py) | `get_external_panel_snapshot` |
| geo-ceasefire-watch | [geo_ceasefire_watch.py](../scripts/api/runtime_panels/modules/geo_ceasefire_watch.py) | `get_external_panel_snapshot` |
| geo-territory-control | [geo_territory_control.py](../scripts/api/runtime_panels/modules/geo_territory_control.py) | `get_external_panel_snapshot` |
| geo-diplomacy-calendar | [geo_diplomacy_calendar.py](../scripts/api/runtime_panels/modules/geo_diplomacy_calendar.py) | `get_external_panel_snapshot` |
| geo-treaty-tracker | [geo_treaty_tracker.py](../scripts/api/runtime_panels/modules/geo_treaty_tracker.py) | `get_external_panel_snapshot` |
| weather-precipitation | [weather_precipitation.py](../scripts/api/runtime_panels/modules/weather_precipitation.py) | `get_external_panel_snapshot` |
| weather-drought | [weather_drought.py](../scripts/api/runtime_panels/modules/weather_drought.py) | `get_external_panel_snapshot` |
| weather-extremes | [weather_extremes.py](../scripts/api/runtime_panels/modules/weather_extremes.py) | `get_external_panel_snapshot` |
| weather-storm-advisory | [weather_storm_advisory.py](../scripts/api/runtime_panels/modules/weather_storm_advisory.py) | `get_external_panel_snapshot` |
| sports-spread-monitor | [sports_spread_monitor.py](../scripts/api/runtime_panels/modules/sports_spread_monitor.py) | `get_external_panel_snapshot` |
| sports-total-monitor | [sports_total_monitor.py](../scripts/api/runtime_panels/modules/sports_total_monitor.py) | `get_external_panel_snapshot` |
| sports-player-props | [sports_player_props.py](../scripts/api/runtime_panels/modules/sports_player_props.py) | `get_external_panel_snapshot` |
| sports-tournament-path | [sports_tournament_path.py](../scripts/api/runtime_panels/modules/sports_tournament_path.py) | `get_external_panel_snapshot` |
| sports-season-race | [sports_season_race.py](../scripts/api/runtime_panels/modules/sports_season_race.py) | `get_external_panel_snapshot` |
| sports-awards-watch | [sports_awards_watch.py](../scripts/api/runtime_panels/modules/sports_awards_watch.py) | `get_external_panel_snapshot` |
| esports-map-state | [esports_map_state.py](../scripts/api/runtime_panels/modules/esports_map_state.py) | `get_external_panel_snapshot` |
| esports-tournament-path | [esports_tournament_path.py](../scripts/api/runtime_panels/modules/esports_tournament_path.py) | `get_external_panel_snapshot` |
| crypto-listing-watch | [crypto_listing_watch.py](../scripts/api/runtime_panels/modules/crypto_listing_watch.py) | `get_external_panel_snapshot` |
| crypto-project-milestones | [crypto_project_milestones.py](../scripts/api/runtime_panels/modules/crypto_project_milestones.py) | `get_external_panel_snapshot` |
| chain-metrics-monitor | [chain_metrics_monitor.py](../scripts/api/runtime_panels/modules/chain_metrics_monitor.py) | `get_external_panel_snapshot` |
| fiscal-tax-monitor | [fiscal_tax_monitor.py](../scripts/api/runtime_panels/modules/fiscal_tax_monitor.py) | `get_external_panel_snapshot` |
| merger-progress | [merger_progress.py](../scripts/api/runtime_panels/modules/merger_progress.py) | `get_external_panel_snapshot` |
| private-valuation-watch | [private_valuation_watch.py](../scripts/api/runtime_panels/modules/private_valuation_watch.py) | `get_external_panel_snapshot` |
| ai-leaderboard-watch | [ai_leaderboard_watch.py](../scripts/api/runtime_panels/modules/ai_leaderboard_watch.py) | `get_external_panel_snapshot` |
| art-auction-watch | [art_auction_watch.py](../scripts/api/runtime_panels/modules/art_auction_watch.py) | `get_external_panel_snapshot` |
| culture-box-office | [culture_box_office.py](../scripts/api/runtime_panels/modules/culture_box_office.py) | `get_external_panel_snapshot` |
| culture-awards-race | [culture_awards_race.py](../scripts/api/runtime_panels/modules/culture_awards_race.py) | `get_external_panel_snapshot` |
| culture-music-charts | [culture_music_charts.py](../scripts/api/runtime_panels/modules/culture_music_charts.py) | `get_external_panel_snapshot` |
| product-release-watch | [product_release_watch.py](../scripts/api/runtime_panels/modules/product_release_watch.py) | `get_external_panel_snapshot` |
| public-figure-events | [public_figure_events.py](../scripts/api/runtime_panels/modules/public_figure_events.py) | `get_external_panel_snapshot` |
| reality-show-progress | [reality_show_progress.py](../scripts/api/runtime_panels/modules/reality_show_progress.py) | `get_external_panel_snapshot` |
| research-evidence-watch | [research_evidence_watch.py](../scripts/api/runtime_panels/modules/research_evidence_watch.py) | `get_external_panel_snapshot` |
| social-window-monitor | [social_window_monitor.py](../scripts/api/runtime_panels/modules/social_window_monitor.py) | `get_external_panel_snapshot` |
| space-mission-watch | [space_mission_watch.py](../scripts/api/runtime_panels/modules/space_mission_watch.py) | `get_external_panel_snapshot` |
| mentions-evidence | [mentions_evidence.py](../scripts/api/runtime_panels/modules/mentions_evidence.py) | `get_external_panel_snapshot` |

### 外源与政治来源时钟（本次实际响应）

只有明确给出字段的值才列数字；`—`为payload未给出，不能推成0或已健康。同一Panel每个来源可以不同。sourceMaxRetention会进一步收紧浏览器外层7d上限。

| Panel / source | 采集尝试周期s | stale阈值s | 源最大保留s | 可用 / stale / error |
| --- | --- | --- | --- | --- |
| politics-election / decision-labs | 3600 | 10800 | — | True / False / None |
| politics-election / nc-results-20261103 | 3600 | 10800 | — | True / False / None |
| politics-election / nc-certification-20261103 | 3600 | 10800 | — | True / False / None |
| politics-early-vote / nc-early-20261103 | 3600 | 10800 | — | True / False / None |
| politics-nomination / nc-primary-20260303 | 86400 | 259200 | — | True / False / None |
| politics-nomination / dnc-roll-call-2024 | 86400 | 259200 | — | True / False / None |
| politics-seats / house-roster | 1800 | 5400 | — | True / False / None |
| politics-campaign-finance / fec-2026 | 21600 | 64800 | — | True / False / None |
| politics-campaign-finance / fec-independent-2026 | 21600 | 64800 | — | True / False / SSLError |
| politics-government / house-roster | 1800 | 5400 | — | True / False / None |
| politics-executive / federal-register:presidential | — | — | — | True / False / None |
| politics-appointments / presidential-nominations | 1800 | 5400 | — | True / False / None |
| politics-appointments / judicial-confirmations | 1800 | 5400 | — | True / False / None |
| politics-appointments / nomination-hearings | 3600 | 10800 | — | True / False / None |
| politics-appointments / hearing:CHRG-119shrg63096 | 86400 | 259200 | — | True / False / None |
| politics-appointments / hearing:CHRG-119shrg64619 | 86400 | 259200 | — | True / False / None |
| politics-appointments / hearing:CHRG-118shrg63671 | 86400 | 259200 | — | True / False / None |
| politics-appointments / hearing:CHRG-119shrg64300 | 86400 | 259200 | — | True / False / None |
| politics-funding / bills-119 | 1800 | 5400 | — | True / False / None |
| politics-funding / bill:119hr6500 | 6300 | 18900 | — | True / False / None |
| politics-funding / funding-law-119-103 | 86400 | 259200 | — | True / False / None |
| geo-conflict-watch / geo:govuk | 3600 | 10800 | 604800 | True / False / None |
| geo-conflict-watch / snapshot:world:geo-sanctions-shock:panel-v1 | — | 3600 | 86400 | True / False / None |
| geo-ceasefire-watch / geo:govuk | 3600 | 10800 | 604800 | True / False / None |
| geo-territory-control / geo:govuk | 3600 | 10800 | 604800 | True / False / None |
| geo-diplomacy-calendar / geo:govuk | 3600 | 10800 | 604800 | True / False / None |
| geo-treaty-tracker / geo:un-treaty | 86400 | 259200 | 1209600 | True / False / None |
| weather-precipitation / snapshot:weather:global-map:panel-v1 | — | 7200 | 21600 | True / False / None |
| weather-drought / weather-usdm | 86400 | 259200 | 1209600 | True / False / None |
| weather-extremes / snapshot:world:natural-hazards:nws | — | 600 | 900 | True / False / None |
| weather-storm-advisory / snapshot:world:natural-hazards:nhc | — | 1800 | 3600 | True / False / None |
| sports-spread-monitor / sports:nba-game-summary:v1 | 600 | 1800 | 86400 | True / True / None |
| sports-total-monitor / sports:nba-game-summary:v1 | 600 | 1800 | 86400 | True / True / None |
| sports-player-props / sports:nba-game-summary:v1 | 600 | 1800 | 86400 | True / True / None |
| sports-tournament-path / sports:atp-tournament:v1 | 900 | 2700 | 86400 | True / False / None |
| sports-season-race / sports:nba-standings:v1 | 21600 | 64800 | 259200 | True / False / None |
| sports-awards-watch / sports:nba-leaders:v1 | 21600 | 64800 | 259200 | True / False / None |
| esports-map-state / sports:dota-map:v1 | 900 | 2700 | 86400 | True / True / None |
| esports-tournament-path / sports:dota-pro-matches:v1 | 900 | 2700 | 86400 | True / False / None |
| crypto-listing-watch / token-events:products | 300 | 900 | 1800 | True / False / None |
| crypto-project-milestones / token-events:release:geth | 1800 | 5400 | 604800 | True / False / None |
| chain-metrics-monitor / chain-metrics:tvl:aave | 3600 | 10800 | 86400 | True / False / None |
| chain-metrics-monitor / chain-metrics:fees:aave | 3600 | 10800 | 86400 | True / False / None |
| fiscal-tax-monitor / fiscal:cash | 21600 | 86400 | 604800 | True / False / None |
| fiscal-tax-monitor / fiscal:budget | 86400 | 259200 | 5184000 | True / False / None |
| fiscal-tax-monitor / fiscal:tax | 86400 | 259200 | 604800 | True / False / None |
| merger-progress / company-capital:sec:wbd | 1800 | 5400 | 86400 | True / True / RetryError |
| merger-progress / company-capital:sec:ea | 1800 | 5400 | 86400 | True / True / RetryError |
| private-valuation-watch / company-capital:announcement:anthropic-series-f | 21600 | 43200 | 604800 | True / False / None |
| private-valuation-watch / company-capital:announcement:openai-2025-funding | 21600 | 43200 | 604800 | True / False / None |
| ai-leaderboard-watch / culture-tech:arena | 21600 | 86400 | 604800 | True / False / None |
| art-auction-watch / culture-tech:christies | 21600 | 86400 | 604800 | True / False / None |
| culture-box-office / culture-tech:bfi | 21600 | 86400 | 1209600 | True / False / None |
| culture-awards-race / culture-tech:golden-globes | 21600 | 86400 | 604800 | True / False / None |
| culture-music-charts / culture-tech:apple-music | 21600 | 86400 | 604800 | True / False / None |
| product-release-watch / culture-tech:steam | 3600 | 10800 | 604800 | True / False / None |
| public-figure-events / culture-tech:fed-speeches | 3600 | 10800 | 604800 | True / False / None |
| reality-show-progress / culture-tech:tvmaze | 21600 | 86400 | 604800 | True / False / None |
| research-evidence-watch / culture-tech:crossref | 21600 | 86400 | 604800 | True / False / None |
| social-window-monitor / culture-tech:bluesky | 3600 | 10800 | 86400 | True / False / None |
| space-mission-watch / culture-tech:launch-library | 3600 | 10800 | 604800 | True / False / None |
| mentions-evidence / culture-tech:fed-speeches | 3600 | 10800 | 604800 | True / False / None |
| mentions-evidence / culture-tech:speech:9c2e70ef035e5c9105ce | 86400 | 172800 | 604800 | True / False / None |
| mentions-evidence / culture-tech:speech:424e5488c61308d5245c | 86400 | 172800 | 604800 | True / False / None |
| mentions-evidence / culture-tech:speech:c1f0a867690795e803b8 | 86400 | 172800 | 604800 | True / False / None |

## WorldMonitor 全部107处breaker声明

这是逐调用点配置而非仅挑DeFi。未显式配置的值按构造器默认展开；动态工厂保留表达式，不能算作固定false。87处明确persist=true，2处动态工厂，18处其余／不持久化。默认其余参数：maxFailures2、cooldown5m、maxCacheEntries256、probe30s；表中“其他覆盖”列有差异则优先。`cacheTtlMs=0`强制禁用持久化。execute级特殊规则另列在表后。

| 名称 / 源码 | fresh | persist | persistent恢复上限 | 其他覆盖 |
| --- | --- | --- | --- | --- |
| [Flight Delays v2](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L343) | 2h | True | 1d | {"revivePersistedData": "(alerts) => alerts.map((alert) => ({\n    ...alert,\n    updatedAt: reviveDate(alert.updatedAt),\n  }))"} |
| [Airport Ops](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L353) | 6m | True | 1d | {"revivePersistedData": "(summaries) => summaries.map((summary) => ({\n    ...summary,\n    updatedAt: reviveDate(summary.updatedAt),\n  }))"} |
| [Airport Flights](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L364) | 5m | False | 1d | 默认 |
| [Carrier Ops](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L365) | 5m | False | 1d | 默认 |
| [Flight Status](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L366) | 6m | False | 1d | 默认 |
| [Track Aircraft](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L367) | 15s | False | 1d | 默认 |
| [Flight Prices](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L368) | 10m | True | 1d | {"revivePersistedData": "(result) => ({\n    ...result,\n    quotes: result.quotes.map((quote) => ({\n      ...quote,\n      expiresAt: quote.expiresAt === null ? null : reviveDate(quote.expiresAt),\n    })),\n  })"} |
| [Aviation News](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L380) | 15m | True | 1d | {"revivePersistedData": "(items) => items.map((item) => ({\n    ...item,\n    publishedAt: reviveDate(item.publishedAt),\n  }))"} |
| [Google Flights](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L390) | 0（无新鲜缓存窗口） | False | 1d | 默认 |
| [Google Dates](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L392) | 5m | False | 1d | 默认 |
| [Cable Health](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/cable-health.ts#L8) | 10m | True | 1d | 默认 |
| [Risk Scores](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/cached-risk-scores.ts#L266) | 30m | True | 1h | 默认 |
| [Theater Posture](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/cached-theater-posture.ts#L104) | POSTURE_FRESH_MS | True | 1d | 默认 |
| [Canada alerts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/canada-alerts.ts#L39) | 30m | True | 1d | 默认 |
| [Canada roads](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/canada-roads.ts#L50) | 30m | True | 1d | 默认 |
| [China Activity Nowcast](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/china-activity-nowcast.ts#L21) | 10m | False | 1d | 默认 |
| [options.breakerName ?? 'China Policy Events'](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/china-policy-events.ts#L316) | 1h | options.persistCache ?? true | 7d | 默认 |
| [Climate Anomalies](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/climate/index.ts#L66) | 20m | True | 1d | 默认 |
| [CO2 Monitoring](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/climate/index.ts#L67) | 6h | True | 1d | 默认 |
| [Ocean Ice](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/climate/index.ts#L68) | 26h | True | 1d | 默认 |
| [ACLED Conflicts](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/conflict/index.ts#L14) | 10m | True | 1d | 默认 |
| [UCDP Events](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/conflict/index.ts#L15) | 10m | True | 1d | 默认 |
| [Iran Events](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/conflict/index.ts#L16) | 10m | True | 1d | 默认 |
| [Consumer Prices Overview](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/consumer-prices/index.ts#L42) | 30m | True | 1d | 默认 |
| [Consumer Prices Series](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/consumer-prices/index.ts#L47) | 1h | True | 1d | 默认 |
| [Consumer Prices Categories](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/consumer-prices/index.ts#L52) | 30m | True | 1d | 默认 |
| [Consumer Prices Movers](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/consumer-prices/index.ts#L57) | 30m | True | 1d | 默认 |
| [Consumer Prices Spread](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/consumer-prices/index.ts#L62) | 30m | True | 1d | 默认 |
| [Consumer Prices Freshness](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/consumer-prices/index.ts#L67) | 10m | True | 1d | 默认 |
| [All Markets Overview](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/consumer-prices/index.ts#L267) | 30m | True | 1d | 默认 |
| [Cross-Source Signals](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/cross-source-signals.ts#L11) | 15m | True | 1d | 默认 |
| [Cyber Threats](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/cyber/index.ts#L18) | 10m | True | 1d | 默认 |
| [UNHCR Displacement](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/displacement/index.ts#L138) | 10m | True | 1d | 默认 |
| [IOM DTM Displacement](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/displacement/index.ts#L160) | 30m | True | 1d | 默认 |
| [IDMC Displacement Events](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/displacement/index.ts#L176) | 30m | True | 1d | 默认 |
| [Cross-Border Movement Reports](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/displacement/index.ts#L193) | 30m | True | 1d | 默认 |
| [Seismology](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/earthquakes.ts#L19) | 5m | True | 1d | 默认 |
| [`WB:${indicatorCode}`](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L42) | 30m | True | 1d | 默认 |
| [EIA Energy](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L50) | 15m | True | 1d | 默认 |
| [EIA Capacity](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L51) | 30m | True | 1d | 默认 |
| [BIS Policy](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L53) | 30m | True | 1d | 默认 |
| [BIS EER](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L54) | 30m | True | 1d | 默认 |
| [BIS Credit](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L55) | 30m | True | 1d | 默认 |
| [China Macro Snapshot](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L56) | 30m | True | 1d | 默认 |
| [BLS Batch](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L59) | 15m | True | 1d | 默认 |
| [FRED Batch](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L62) | 15m | True | 1d | 默认 |
| [EIA Crude Inventories](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L66) | 1h | True | 1d | 默认 |
| [EU Gas Storage](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L68) | 4h | True | 1d | 默认 |
| [Eurostat Country Data](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L70) | 4h | True | 1d | 默认 |
| [EIA Nat Gas Storage](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L72) | 1h | True | 1d | 默认 |
| [IEA Oil Stocks Analysis](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L84) | 4h | True | 1d | 默认 |
| [National Debt](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L712) | 6h | False | 1d | 默认 |
| [ECB FX Rates](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/economic/index.ts#L852) | 4h | False | 1d | 默认 |
| [NaturalEvents](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/eonet.ts#L37) | 30m | True | 1d | 默认 |
| [GDELT Intelligence](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/gdelt-intel.ts#L134) | 10m | True | 1d | 默认 |
| [GDELT Positive](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/gdelt-intel.ts#L135) | 10m | True | 1d | 默认 |
| [Global Giving](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/giving/index.ts#L27) | 30m | True | 1d | 默认 |
| [Global Tenders](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/global-tenders.ts#L8) | 10m | False | 1d | 默认 |
| [Internet Outages](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/infrastructure/index.ts#L21) | 30m | True | 1d | 默认 |
| [Service Statuses](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/infrastructure/index.ts#L22) | 30m | True | 1d | 默认 |
| [DDoS Attacks](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/infrastructure/index.ts#L23) | 30m | True | 1d | 默认 |
| [Traffic Anomalies](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/infrastructure/index.ts#L24) | 30m | True | 1d | 默认 |
| [Maritime Snapshot](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/maritime/index.ts#L12) | 10m | True | 1d | 默认 |
| [Market Quotes](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L21) | 5m | True | 1d | 默认 |
| [Commodity Quotes](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L22) | 5m | True | 1d | 默认 |
| [Physical Premiums](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L23) | 0（无新鲜缓存窗口） | False | 1d | 默认 |
| [Sector Summary v2](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L24) | 5m | True | 1d | 默认 |
| [Crypto Quotes](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L25) | 10m | True | 1d | 默认 |
| [Crypto Sectors](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L26) | 10m | True | 1d | 默认 |
| [DeFi Tokens](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L27) | 10m | True | 1d | 默认 |
| [AI Tokens](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L28) | 10m | True | 1d | 默认 |
| [Other Tokens](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/market/index.ts#L29) | 10m | True | 1d | 默认 |
| [Military Flight Tracking](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/military-flights.ts#L102) | 10m | True | 1d | {"maxFailures": 3, "cooldownMs": 300000, "revivePersistedData": "(data) => ({\n    ...data,\n    flights: data.flights.map((f: MilitaryFlight) => ({\n      ...f,\n      lastSeen: f.lastSeen instanceof Date ? f.lastSeen : new Date(f.lastSeen as unknown as string),\n    })),\n  })"} |
| [Military Vessel Tracking](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/military-vessels.ts#L81) | 30s | True | 1d | {"maxFailures": 3, "cooldownMs": 300000, "revivePersistedData": "(data) => limitVesselSnapshot({\n    ...data,\n    vessels: data.vessels.map((v: MilitaryVessel) => ({\n      ...v,\n      vesselType: isStaleAisMilitaryOpsClaim(v) ? 'unknown' : v.vesselType,\n      lastAisUpdate: v.lastAisUpdate instanceof Date ? v.lastAisUpdate : new Date(v.lastAisUpdate as unknown as string),\n    })),\n  })"} |
| [NO2 Activity](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/no2-activity.ts#L21) | 0（无新鲜缓存窗口） | False | 1d | {"maxCacheEntries": 0} |
| [PizzINT](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/pizzint.ts#L15) | 5m | True | 1d | {"maxFailures": 3, "cooldownMs": 300000, "revivePersistedData": "revivePizzIntStatus"} |
| [WM GDELT Dyad Tensions v1](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/pizzint.ts#L26) | 0（无新鲜缓存窗口） | False | 1d | {"maxFailures": 3, "cooldownMs": 300000} |
| [Positive Geo Events](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/positive-events-geo.ts#L27) | 10m | True | 1d | 默认 |
| [Polymarket](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/prediction/index.ts#L25) | 10m | True | 1d | 默认 |
| [Progress Data](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/progress-data.ts#L105) | 1h | True | 1d | 默认 |
| [Radiation Watch](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/radiation.ts#L52) | 15m | True | 1d | {"revivePersistedData": "reviveRadiationWatchResult"} |
| [Energy Capacity](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/renewable-energy-data.ts#L101) | 1h | True | 1d | 默认 |
| [options.breakerName ?? 'Renewable Energy'](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/renewable-energy-data.ts#L110) | 1h | options.persistCache ?? true | 7d | 默认 |
| [ArXiv Papers](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/research/index.ts#L11) | 10m | True | 1d | 默认 |
| [GitHub Trending](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/research/index.ts#L12) | 10m | True | 1d | 默认 |
| [Hacker News](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/research/index.ts#L13) | 10m | True | 1d | 默认 |
| [Sanctions Pressure](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/sanctions-pressure.ts#L60) | 30m | True | 1d | {"revivePersistedData": "reviveSanctionsPressureResult"} |
| [News Summarization](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/summarization.ts#L93) | 0（无新鲜缓存窗口） | False | 1d | 默认 |
| [SummaryResult](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/summarization.ts#L95) | 2h | True | 1d | {"maxCacheEntries": 128} |
| [Shipping Rates](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/supply-chain/index.ts#L86) | 1h | True | 1d | 默认 |
| [Chokepoint Status](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/supply-chain/index.ts#L89) | 5m | True | 1d | 默认 |
| [Critical Minerals](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/supply-chain/index.ts#L90) | 1d | True | 1d | 默认 |
| [China Corridor Control Towers](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/supply-chain/index.ts#L91) | 10m | False | 1d | 默认 |
| [Mineral Production](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/supply-chain/index.ts#L121) | 1d | True | 1d | 默认 |
| [Thermal Escalation](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/thermal-escalation.ts#L70) | 30m | True | 1d | {"revivePersistedData": "(watch) => ({\n    ...watch,\n    fetchedAt: reviveDate(watch.fetchedAt),\n    clusters: watch.clusters.map((cluster) => ({\n      ...cluster,\n      firstDetectedAt: reviveDate(cluster.firstDetectedAt),\n      lastDetectedAt: reviveDate(cluster.lastDetectedAt),\n    })),\n  })"} |
| [AIClassify](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/threat-classifier.ts#L94) | 6h | True | 1d | {"maxCacheEntries": 256} |
| [WTO Restrictions](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/trade/index.ts#L49) | 30m | True | 1d | 默认 |
| [WTO Tariffs](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/trade/index.ts#L53) | 30m | False | 1d | 默认 |
| [WTO Flows](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/trade/index.ts#L54) | 30m | True | 1d | 默认 |
| [WTO Barriers](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/trade/index.ts#L55) | 30m | True | 1d | 默认 |
| [Treasury Revenue](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/trade/index.ts#L56) | 30m | True | 1d | 默认 |
| [Comtrade Flows](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/trade/index.ts#L57) | 6h | False | 1d | 默认 |
| [Unrest Events](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/unrest/index.ts#L11) | 10m | True | 1d | 默认 |
| [USNI Fleet Tracker](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/usni-fleet.ts#L11) | 1h | True | 1d | {"maxFailures": 3, "cooldownMs": 600000} |
| [NWS + ECCC + WMO SWIC Weather](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/weather.ts#L47) | 30m | True | 1d | 默认 |
| [Wildfires](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/wildfires/index.ts#L43) | 30m | True | 1d | 默认 |
| [Wingbits Enrichment](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/wingbits.ts#L147) | 10m | False | 1d | {"maxFailures": 5, "cooldownMs": 300000} |

调用级覆盖（持久化构造器表不足以说明最终展示行为）：

| 源码 | 参数 | 值 |
| --- | --- | --- |
| [src/services/aviation/index.ts:499](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/aviation/index.ts#L499) | evictOnRefreshFailure | True |
| [src/services/cable-health.ts:72](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/cable-health.ts#L72) | staleRefreshMode | await |
| [src/services/cached-theater-posture.ts:205](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/cached-theater-posture.ts#L205) | forceRefresh | options?.forceRefresh |
| [src/services/earthquakes.ts:38](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/earthquakes.ts#L38) | staleRefreshMode | await |
| [src/services/gdelt-intel.ts:207](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/gdelt-intel.ts#L207) | maxServeAgeMs | 3600000 |
| [src/services/gdelt-intel.ts:340](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/gdelt-intel.ts#L340) | maxServeAgeMs | 3600000 |
| [src/services/giving/index.ts:78](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/giving/index.ts#L78) | staleRefreshMode | await |
| [src/services/giving/index.ts:79](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/giving/index.ts#L79) | forceRefresh | lastRefreshFailure !== null |
| [src/services/maritime/index.ts:181](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/maritime/index.ts#L181) | evictOnRefreshFailure | shouldIncludeCandidates() |
| [src/services/pizzint.ts:156](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/pizzint.ts#L156) | staleRefreshMode | await |
| [src/services/supply-chain/index.ts:160](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/supply-chain/index.ts#L160) | staleRefreshMode | await |
| [src/services/usni-fleet.ts:55](https://github.com/koala73/worldmonitor/blob/6f1f170def8d8a5b1f89c4615655034d5a4818ef/src/services/usni-fleet.ts#L55) | forceRefresh | False |

## 当次实测与剩余事项

- 第一次93接口观察发生在后端服务06:07 UTC重新启动后不久：7个Finance/Tech响应warming，随后复查7个均产生有效源时间；不能把启动瞬时warming描述成永久坏源。Macro Map也从旧快照恢复。Fear & Greed后续仍partial（CNN/AAII失败），不算完整恢复。
- Breaking Event Radar 仍为2026-11-08源时间，GDELT rate-limited、Wikimedia error，超过24h；拒绝它是正确的陈旧数据保护，不应伪造新时间解除报错。
- Flow Watch读到2026-11-10 03:26 UTC旧快照，当前source refresh failed，已经超过15m恢复窗口；采集日志明确为 get_recent_trades 连续两次TimeoutError（Oracle-window候选成交读取）；不能通过浏览器TTL掩盖。
- 真实生产旧版本现有111个Panel滚动观察：64 ready、22 error、7 degraded、4 loading、3 stale、11 idle（各Panel最后一次可见采样，非同一时刻全屏）；网络同时有ERR_NETWORK_CHANGED和取消。数据是否可用、是否新鲜、UI是否完成是三个指标，不能把93次HTTP200称为全站恢复。
- 当前全量代码扫描不是每个市场、每个过滤条件、每个来源每条记录的业务正确性证明。10个默认关闭的Panel只做API/代码核验；不会擅自重置用户布局。报价执行资格、历史实时化、来源字段缺口与长期稳定性继续单列。

下面的发布验收记录独立于前述故障时刻；代码修复、线上可见内容、来源完整性分别判断。

### 真实上线后追加发现：回连压缩与完整响应期限

`896ab394`已发布并核对公网HTML/JS入口。实际桌面恢复记录中，NBA显示8场、DeFi的持久副本10条、天气副本50城/315万字符；82份资源已写入IndexedDB。刷新后NBA没有再次发出API请求，仍显示比赛；布局值未改变。不过Geo完整网络响应仍受12s限制，Crypto Strategy受10s限制，手机冷启动亦有未完成/错误，不能据此宣称全站已恢复。

定位到正式API进程端口18502后，直接完整读取Geo/共享加密/天气分别约0.091/0.424/0.244s，原始字节为1,080,267 / 327,814 / 3,213,198，均未协商出gzip。腾讯云本机经正式反向链路完整读取Geo/加密约9.44/10.13s；腾讯云对浏览器已经启用gzip；后端HTTP响应未启用Content-Encoding。补查实际interactive/bulk回连进程，两条SSH命令均已有 `-C`，因此不能把HTTP未压缩推断为隧道传输完全未压缩，也不能据此断言新增HTTP gzip显著改善回连速度。另有本访问环境的ERR_NETWORK_CHANGED和截断响应，加长超时也不能消除所有链路故障。

补充修复在既有HTTP共享钩子中，仅对三个明确公开的大快照路径提供gzip，压缩发生在回连之前；不另建缓存、不改源时间、不改采集周期，强ETag降为同语义弱ETag并保留Vary/Cache-Control。同内容gzip级别5估计HTTP编码字节为98,676 / 73,649 / 334,827，这不是SSH实际线上字节或节省量测量。发布后腾讯云本机读取Geo/加密/天气约10.08/8.28/32.91s，仍有明显波动，不能作为稳定提速的证明。Geo总期限60s/网络35s；共享Crypto Strategy和历史总期限45s/网络35s；Contract Reference和LOB不延长。对应回归包括解压逐字节等价、原时间、协商q=0、CORS/Vary、既有编码、流式与私有路径不变，以及延迟21s完整body成功/35s停滞终止。

追加定点复查：Funding Rate 通过自动重试恢复ready；其正式API为76个资产/148条合格报价。Market Summary元数据请求在45s观察中仍受旧6s总期限反复取消，正式API直读约54ms/5,890字节且focusStatus=ready。将这一共享元数据owner的总期限改45s、准入后完整网络预算35s；保持fresh=60s、恢复上限5m、市场身份校验和剥离LOB/Oracle/Trades规则。13s延迟body回归验证保留原时间且不恢复实时字段。


### 正式页面验收记录

`ae322adc496e647db2a3dfee82fc983ee14f4a65`从已推送提交的干净archive构建，发布到当前实际承载网站的腾讯云前端。公网根域与www的release-sha、入口 `/assets/index-CXACkN0x.js`、HTML SHA256均一致。后台只安装该提交的共享HTTP文件并HUP重载；没有部署工作区其他后端变更，也没有改动回连/代理路由。

- 桌面真实www地址，1920×1080，使用前一轮留下的浏览器配置和原布局，逐项滚动111个默认Panel。各Panel最后一次可见采样为89 ready、9 degraded、3 stale、3 error、7 idle。idle包含独立业务owner/静态视图，不等于空白；这不是同一时刻的全站健康快照。此次无最后样本处于loading，不能推断未来永不出现Loading。
- 三个error为Market Summary、Funding Rate、Breaking Radar。定点停留45s复查：Funding自动恢复ready；Market Summary仍受旧6s请求期限取消，已追加上述元数据预算修复；Breaking Radar正式API仍是2026-11-08旧源。Flow Watch本轮已经恢复ready，显示12条large-trade观察，源时间07:21:33 UTC；不再把前述03:26 UTC故障状态冒充当前状态。12条均非Oracle-linked，不能称Oracle-linked覆盖已恢复。
- IndexedDB已有91份、合计8,728,083个JSON字符，localStorage同步热副本63份。NBA8场、DeFi10条、天气50城约310万字符、Geo约108万字符均成功存储。刷新前后NBA/DeFi/天气的generatedAt和checkedAt未改，布局字符串相同；ESPN后台刷新更新了自己的项，不能宣称整库完全没有变化。
- 桌面刷新后NBA继续显示8场，无Loading覆盖；原采样从reload开始至读取约5.61s，包含导航和固定等待，不是内容首次绘制耗时。后续独立复查记录真实request事件，在reload至已显示内容的约5.07s区间内没有NBA请求；此时NBA已转stale，旧内容仍可见。这证明当次持久副本恢复，不证明断网冷启动或整夜连续运行。
- 手机真实根域地址390×844：NBA、NBA Intel、DeFi、Geo为ready，ESPN为stale、小时天气为degraded但有图表；重载NBA仍显示8场，无Loading覆盖。页面scrollWidth=innerWidth=390，未发现横向溢出；未重置布局或替换API/地图瓦片。
- 桌面未记录到pageerror；网络仍出现3次ERR_NETWORK_CHANGED和26次ERR_ABORTED。取消可能来自滚出视口、重载或期限，不能将全部取消视为后端故障，也不能将本访问环境的连接变化等同用户的网络。
- 缓存恢复与报价/业务完整性分开：天气部分源缺失，NBA阵容字段仍有空项；Fear & Greed、研究、政策、竞选资金存在partial；ESPN/运输/Oracle参考存在stale。Trade Policy仍为静态REFERENCE。市场实时盘口与来源连续稳定性不在缓存恢复结果中冒充通过。

本轮证据目录中的 `production-after-desktop.json`、`production-after-mobile.json`、`production-final-recheck.json`、`public-release-check.json`、`deployment.json` 保存对应时刻数据；截图 `after-desktop-reload.png`、`after-mobile-reload.png`、`final-mobile-*.png` 来自真实网站。`896ab394-*`为前一版本观察，不能混作本版结果。完整源码表覆盖121项，但10个默认关闭项没有擅自打开做页面验收；每个筛选组合、每个资产与真实隔夜稳定性仍未全量验证。


### 最终发布与验收（追加元数据修复）

最终前端发布提交为 **`7bca16b10389510064e731aa951f3021b3bd5286`**，入口 `/assets/index-B5m9fxIb.js`。根域与www的release-sha、HTML SHA256均与干净archive构建一致。上述ae322adc的HTTP改动在这个提交中未变化；后端安装文件hash仍与该源码一致。

最终提交的干净构建通过：前端单元测试 **474通过、1跳过**，类型检查、locales、前端边界和地图bundle检查通过；缓存恢复/自动重试浏览器测试 **22通过**（包含桌面/手机模拟12h旧快照、真实IndexedDB、丢失热副本、存储延迟竞争、失败自动恢复、Retry-After、原始时间不续期）。HTTP压缩与相关信号期限Python回归 **19通过**。浏览器回归使用本地受控来源，是预检，不混作生产数据源验收；未声明全仓质量门禁全部通过。

最后在真实桌面www和手机根域原浏览器配置回看：**Market Summary两端ready、NBA两端stale且保留8场内容、DeFi桌面ready/手机stale但均有报价内容**，均无Loading覆盖。首次回看元数据请求约1.87s/1.73s返回200并被真实UI接纳；最终截图另外等待可见正文，避免把缓存owner的ready误当成懒加载组件已经绘制。这次没有出现旧6s取消，单次通过不构成链路长期稳定证明。两端布局字符串未变，无pageerror，宽度分别1920/1920、390/390。证据为 `metadata-release-acceptance.json`、`release-desktop-market-summary.png`、`release-mobile-market-summary.png`、`release-mobile-nba-scoreboard.png`、`release-mobile-defi-token-watch.png`；最新 `deployment.json` / `public-release-check.json` 对应该最终版本，ae322adc对应回执已加前缀保留。

结论限于：已上线的共用持久缓存、原时间保留、NBA解析、天气字段过期、恢复重试与有界传输期限修复得到代码及当次真实UI证据。Breaking Radar过期采集、若干来源partial/stale、短暂链路异常、真实隔夜连续稳定性仍不能标为全部解决。无需清缓存、重置布局或手动启用默认Panel。


线上未全绿的逐项记录（ae322adc全页采样，后续修复另标；不把stale/partial都称空白）：

| Panel ID | 当次显示 | 具体边界 |
| --- | --- | --- |
| breaking-event-radar | error/无可接纳快照 | GDELT限流、Wikimedia失败，旧源超过24h；采集未恢复 |
| related-news | degraded/有内容 | 来源覆盖不全，已有文章继续显示 |
| broker-research-watch | degraded/有内容 | 部分研究来源不全，不保证覆盖所有券商 |
| crypto-fear-greed | degraded/有内容 | CNN/AAII缺失，不保证复合指标完整 |
| weather-market-browser | degraded/有内容 | 目录/观测/模型覆盖分别不足，部分城市盘口缺失 |
| weather-trend-detail | degraded/有图表 | 共享天气owner部分源缺失，保留模型原时间 |
| weather-trend-7d | degraded/有图表 | 同一天气owner，不另采集或续期模型 |
| world-clock | degraded/时间显示 | 状态来自共享天气owner；时钟仍走本地时间，不是时钟停止 |
| policy-progress | degraded/有内容 | 部分政策来源不全 |
| politics-campaign-finance | degraded/有内容 | 来源更新延迟，保留已发布FEC观察 |
| crypto-oracle-reference | stale/有限显示 | 旧观察与原时间仍可见，当前距离字段因观察过期不再计算 |
| global-transport-shipping | stale/有内容 | 源快照超fresh窗口，不能当成当前机场状态 |
| espn-matchup-predictor | stale/8场 | 模型快照超fresh，旧预测不应冒充刚更新 |
| market-summary | error→ready | 追加元数据传输预算后最终桌面/手机确认恢复 |
| crypto-funding-watch | error→ready | 定点可见停留期间自动重试成功，未修改报价资格或该owner期限 |

此外NBA Intel虽ready，阵容姓名仍存在源空项；Trade Policy的REFERENCE示例也不是已完成动态来源。ready只表示当前owner有可接纳内容，不承诺逐字段完整。
