# Panel 数据可靠性修复与逐项线上复验（2026-11-10，第二轮）

这是有时间边界的验收记录，不是默认部署配置或永久健康声明。承接 [上一轮来源恢复记录](panel-source-recovery-2026-11-10.md) 与 [缓存生命周期审计](panel-cache-loading-audit-2026-11-10.md)。采集、存储、API、共享 Runtime 的当前契约见 [数据管线](panel-data-pipeline.md)、[采集时钟](panel-data-cadence.md)、[资源预算](panel-resource-contract.md)、[生命周期](panel-runtime-lifecycle.md)。

本轮解决 Breaking Radar 无即时报道、ClickHouse 有界查询仍超预算，以及网站回连链路的主要瓶颈；同时修复 CFTC、Edison、体育定时任务及 Cleveland Fed 的实际采集问题。**不能据此声称 121 个 Panel 的所有来源都完整、实时、连续可用。** LOB 源读取的 503、源连续性 UNKNOWN、需要授权的来源和本身没有发布的数据，仍单独保留。随后 LOB 与慢周期来源的跟进见文末，前面的检查表保留当时状态。

## 发布身份与检查边界

- `bbfd237d`：Radar RSS 回退；仅发布所属后台采集/服务文件，既有 owner 于 18:24:39 CST 重启。
- `31957113aaa4a0579c7d57b9342a4750692bda3b`：ClickHouse 简化读取、流量分路和前端有限样本说明。前端从这个已推送提交的干净 `git archive` 构建并发布到**实际承载根域名/www 的腾讯云**；两个域名的 release-sha 已核对。没有发布脏工作区，也没有把 GCP 文档当作实际入口。
- `bdd5f8a5`：Edison 证券代码解析；部署文件与提交逐字核对，Finance watch 正式 owner 重新采集成功。其后的来源路由/systemd 调整在私有部署配置中，未把密钥或私人出口地址写入仓库。
- 本轮针对测试：Radar/seed 恢复 89 项、市场读取/私有服务 35 项、Finance watch 48 项，合计 172 个针对性测试；前端生产构建通过。这不是全仓测试覆盖声明，也没有沿用上一轮的前端单测数字。
- 所有测试浏览器访问真实 `https://polymonitor.club/`，没有替换 API、快照或地图瓦片。桌面 1600×1000；手机 CSS 视口 390×844，设备像素比使截图为 1024×2216。服务器 headless Chrome 的地图使用真实 SVG fallback，不能据此验收 WebGL 地图渲染性能。
- 注册表共 **121 项：111 默认启用、10 可选**。111 项逐一滚动检查桌面和手机；另 10 项通过普通 Panel 库添加后逐一检查桌面。两种设备刷新前后默认布局 ID/顺序一致，仅操作测试浏览器，未清理或重置用户个人布局。

## 修复及实际新数据证据

### ClickHouse：只做可核验的最近成交展示

原 value 查询经过 `orderfilled_fact_primary_v1` 的多分支 UNION，触发 `TOO_MANY_BYTES`。现在 key/value 都只读 `orderfilled_events_v1` 中 **`fact_base_matches = 1`** 的已核验基础事实，与既有 fact view 第一分支一致。不是任意 raw 回退，不修改采集器、库表或数据库权限。

保留精确 key/value 身份比对、UInt64 可空转换以及总 64 MiB / 6 秒 / 单线程 / 256 MiB 内存 / readonly 限额；字段用 `f.` 限定，避免 token_id 别名参与过滤。缓存版本改为 `verified-base-v3`，coverage 明确 `verified-base-facts`。Flow 显示最多 50 条样本，chart 仍是有界近期成交，不冒充全历史、全日成交量或完整资金流。

正式部署直读：549771 flow 50 条/0.593 秒，chart 54 点/0.387 秒；550186 flow 50 条/0.767 秒。公网三轮都成功，实际页面显示成交和曲线。24 次采样中底层 `sourceUpdatedAt` 从 10:38:01Z 推进到 11:00:48Z；这是底层事实进度，**不是保证每个抽样市场每分钟都有新成交**，也不以 API `generatedAt` 推进代替交易事件证据。 后续公网三次相同市场读取进一步确认：3848348 的最新成交事件从 11:15:30Z 到 11:16:48Z，3846901 从 11:15:30Z 到 11:17:01Z，两者成交行 hash 都变化，证明新成交已经入库并进入 Panel API。

### Breaking Radar：既有后台 owner 持续采集报道

保留 GDELT 429 冷却，不清限流。顺序为 GDELT → 已采集的合规公开 feed → Google News RSS → 日级 Wikimedia 注意力。只有后台 owner 请求来源，API 仍只读 SQLite 快照；没有增加另一套采集器。

5 个既有主题各轮询一次/300 秒，一轮约 25 分钟。RSS 请求沿用来源路由，12 秒请求、20 秒来源截止、1 MiB 响应、24 小时报道窗口、URL 去重、每次至多 20 篇；保留 publishedAt 与 acquiredAt，不把采集时刻伪造成报道时刻。只存展示所需标题/来源/链接等元数据，不抓整篇正文。

正式轮转已覆盖全部 5 主题：geopolitical-risk 10:24:50Z、crypto-policy 10:29:51Z、天气公开告警 10:31:16Z、Iran 10:39:53Z、US politics 10:44:55Z。随后 10:49:56Z、10:54:57Z 又取得 RSS 报道，5 项都成为 WIRE 证据。GDELT 仍 rate-limited，Panel 正确保留 DEGRADED，不能把备用来源成功写成 GDELT 恢复。

### 公网链路

旧跳板 SSH 实测重传约 12%、RTT 337–436ms、拥塞窗口降至 3；约 228 KB 压缩天气响应需要 12–14 秒。同路径的 Tailscale 替代实测更慢，未采用；另一个跳板禁止转发，未修改其 ACL。

现有三个网站转发 profile 使用经过实测的隔离 loopback HTTP CONNECT 出口；SSH 专用身份、HostKeyAlias、keepalive 保留。只允许显式端口、无认证/路径/query 的本地 HTTP 代理，与跳板互斥。**未切换用户主 Clash。** bulk 从两个质量不同的链接 least_conn 改为主链路优先、旧链接备用；panels/interactive/bulk 分别在 18:30:31、18:31:02、18:31:25 CST 启用。Nginx 校验/重载成功，既有旧默认 tunnel 未重启。

三轮各 100 个真实公网请求（93 个注册直接 API + 7 个选中市场补充读取）：

| 开始时间 UTC | HTTP 成功 | 中位数 | P95（本次 100 样本） | 最大 |
| --- | --- | --- | --- | --- |
| 10:34:42 | 100/100 | 0.430s | 1.312s | 3.480s |
| 10:47:38 | 100/100 | 0.603s | 2.737s | 4.989s |
| 11:03:47 | 100/100 | 0.572s | 1.745s | 4.914s |

这些轮次和有效桌面/手机记录中没有 502/504；浏览器仍各有一次 **LOB 503**。所有记录到的 requestfailed 均为 ERR_ABORTED，包含滚动暂停、换资源和截止取消，不能一律算成功，也不能一律归咎服务端。验证窗口约一小时，不是全天网络 SLA。服务 NRestarts=0 只是进程证据，独立于上面的 HTTP/业务验收。

### 其他来源及自然刷新

- CFTC：原直连超时拖住 Finance external。给该公开域名补既有隔离出口路由；正式 owner 10:39:07Z、10:54:52Z 两轮 COT 5/5 成功。周报仍显示原 11 月 3 日报告期，不伪造每日新报告。
- Edison：介绍页不是报告列表，改用官网公开报告列表；详情只解析明确的 `Code` 表格字段，不猜大写单词。10:50:50Z 正式快照含 Nov 10 的 4imprint 报告，Zacks/Edison 成功；Water Tower 的限制见下。
- 体育定时任务：此前只更新常驻 owner，`polymonitor-external-panels@` 仍被旧 EnvironmentFile 的强制直连覆盖。18:52:45 CST 部署 override，使下一轮通过既有启动器读取主私有来源配置，保留其他端点/资源/凭据。新 NBA summary 11:03:09Z、ATP tournament 11:08:22Z 正式成功；没有强制清除 due/cooldown。
- Cleveland Fed：18:49 的一轮耗尽 90 秒来源预算而保留 10:18 的快照。复查直连失败、既有隔离出口 0.92 秒 HTTP 200；补该公开域名路由并重启其原 owner。11:11:12Z 正式新采集、随后公网 ok；报告 Updated 仍为 11/09。只观察到修复后一次正式采集，下一次 30 分钟轮次未包含在本次验收。
- 50 城天气：全部有小时/每日预报和 METAR；预报独立小时采集从 09:47:48Z 推进到 10:47:48Z。报价由原官方 REST owner 读取，概览每 5 分钟、可视城市需求每 30 秒，独立于小时预报时间。最终公网 627 个主日期 bins 为 539 snapshot / 88 no-book / 0 retained；no-book 是官方空书，不填价格。
- 天气首次滚动曾显示 retained。定点停留后，**无手动刷新**，纽约 11/11 当前盘口、0 retained 连续成立；三个公开响应的 lastSuccessAt 为 11:10:37Z、11:11:57Z、11:12:02Z。这证明重新获取当前报价，不能抹掉首次可视时的短暂旧值。天气新闻 11:01 一轮两地 ConnectionError，11:12:18Z 正式下一轮自动恢复为 ok，sourceErrors 为空。
- NBA 浏览器定点停留，不重载、不点 Retry，11:08:28Z 收到 generatedAt=11:07:52Z，11:09:20Z 又收到 11:08:57Z。24 次/24 分钟后台采样中，NBA 比分、新闻、预测各观察到 19 个不同生成时间，Big Tech 3 个、天气新闻 6 个；采集成功与比赛结果/日级排行恰好变化是不同概念。

## 未通过或仍有边界的项目

1. **LOB 深度及依赖它的市场/合约参考**：桌面 10:55:09Z、手机 11:03:42Z 各记录一次真实 503。订单簿读者是 market-data 既有 18861 HTTP → 本地 gateway committed snapshot，不是 ClickHouse 查询；它有 2 秒截止、4 并发、失败缓存 15 秒。503 历史异常细类未有日志证据，不推断成某一种具体异常。后续直接读 gateway 约 7/16ms 有新事件，但一个市场 upstreamReady=false，另一个虽 true 仍 continuity_unknown，二者 upstreamCompleteness=UNKNOWN。**未修复上游恢复/连续性，不宣称当前可交易或全量最新**；未改动该仓库正在进行的采集工作。
2. **Water Tower / AAII / CNN**：Water Tower 旧研究 URL 是 SPA 404，实际 dashboard 要求登录；未取得授权凭据/feed。AAII 403、CNN 418 的限制仍存在。Zacks、Edison、FRED、alternative.me 的成功不能覆盖缺失来源；API 外层 ok 也不代表这些来源齐全。
3. **政策与竞选资金**：GovInfo 一份材料 404、FEC 部分记录缺方向字段，保留缺失及来源状态，不凭程序猜造事实。
4. **慢源与研究视图**：宏观月度/周度数据仍使用原发布期；6 小时采集的 7 个可选面板会在较短前端阈值后显示 stale，此窗口内下一次正式采集尚未到期/未观察，不能算持续更新已验收。Crypto Exchange Inflows 是历史研究；Trade Policy Radar 当前是静态研究视图，都不是自动采集的新数据流。AI 三个 lens 有正式生成快照，但本轮没有重做模型事实正确性/收益验证。
5. **覆盖范围**：注册直接/共享消费者 100 个用实际前端 parser 对最终公网 payload 验证，100 accepted、0 rejected；其余 21 个通过选中市场/共享 crypto/内容等上下文读取或静态视图验证。另 15 个上下文 API 本地检查成功，实际线上 UI 也访问了这些资源。Parser 接受和 Runtime ready 不等于所有内层数据 qualified；例如 LOB 自定义视图的外层 idle 不代表盘口正常。

## 逐项验收表

下表按注册表列全 121 项。API 列保留请求 limit；共享视图复用同一 owner。快照时间是原始 payload generatedAt 的首轮 → 末轮（统一 UTC），不是浏览器保存时间；只代表该快照身份推进，不自动等同上游发布新事件。采集时钟来自正式 seed-meta；外部 sources 的独立 expectedInterval/lastSuccess 优先于组合时间。浏览器参数依次为检查间隔 / 新鲜阈值 / 最大旧副本保留；不把三个时钟混为一谈。`—` 表示组件自行复用上下文，其资源契约见原模块。

桌面 111 默认项的最后逐项观察为 93 ready / 11 degraded / 7 idle；手机为 87 ready / 16 degraded / 8 idle。10 可选项桌面为 2 ready / 1 degraded / 7 stale。没有逐项观察点仍是满屏 loading，但后续独立 LOB 失败仍按上文保留。表中状态不被之后的定点恢复覆盖。

| Panel ID | owner/API（省略 /wm-api） | API 状态；快照时间 UTC 首→末 | 采集频率；最近成功 UTC | 浏览器 检查/新鲜/保留 | 桌面 / 手机 | 限制或后续恢复 |
| --- | --- | --- | --- | --- | --- | --- |
| `active-markets` | `/markets?page=1&pageSize=50&status=active&sort=volume` | ok；11-10 10:46:17 | —；— | —/—/— | idle / idle | 保留原始来源时间/覆盖范围 |
| `global-orderfilled` | `/markets/549771/flow?limit=50` | ok；11-10 10:35:10 → 11-10 11:04:23 | —；— | —/—/— | idle / idle | 仅 verified-base-facts，至多 50 条 |
| `oracle-feed` | `/markets/549771/oracle` | ok；11-10 10:34:02 → 11-10 11:04:25 | —；— | —/—/— | idle / idle | 保留原始来源时间/覆盖范围 |
| `market-summary` | `/markets/549771/focus-tile` | 200；11-10 10:46:17 | —；— | —/—/— | ready / ready | 目录价格/样本；依赖 LOB 的部分仍不合格 |
| `featured-market` | `/markets/549771/focus-tile` | 200；11-10 10:46:17 | —；— | —/—/— | idle / idle | 保留原始来源时间/覆盖范围 |
| `price-implications` | `/runtime/agent/market-wide-insights/overview` | live；11-10 08:00:03 | —；— | 15m/12h/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `price-chart` | `/markets/549771/chart?range=1d&interval=5m` | ok；11-10 10:46:17 | —；— | —/—/— | idle / idle | 有界近期成交，不代表全时间窗 |
| `sample-chain-trades` | `/runtime/agent/market-wide-insights/special` | live；11-10 08:02:02 | —；— | 15m/12h/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `oracle-timeline` | `/runtime/agent/market-wide-insights/trend` | live；11-10 08:04:02 | —；— | 15m/12h/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `related-news` | `/content/latest?limit=100&days=7` | partial；11-10 10:45:31 | 1m；11-10 11:10:43 | —/—/— | degraded / degraded | 保留原始来源时间/覆盖范围 |
| `breaking-event-radar` | `/runtime/evidence/breaking-event-radar?limit=12` | degraded；11-10 10:29:51 → 11-10 10:58:07 | 5m；11-10 11:10:01 | 5m/15m/1d | degraded / degraded | 新 RSS/public-feed 持续到达；GDELT 429 |
| `market-tv-wire` | `/runtime/content/market-tv-wire?limit=60` | ok；11-10 10:17:45 → 11-10 10:47:45 | 15m；11-10 11:05:27 | 15m/30m/6h | ready / ready | 保留原始来源时间/覆盖范围 |
| `market-youtube-channels` | `/runtime/content/market-youtube-channels?limit=80` | ok；11-10 10:17:45 → 11-10 10:47:45 | 15m；11-10 11:05:27 | 15m/30m/6h | ready / ready | 保留原始来源时间/覆盖范围 |
| `alpha-signal` | `/runtime/signals/alpha?limit=8` | ok；11-10 10:46:10 | 2m；11-10 11:10:17 | —/—/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `whale-tracker` | `/runtime/trades/whales?limit=14` | ok；11-10 10:46:11 | 2m；11-10 11:10:13 | —/—/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `suspicious-flow` | `/runtime/trades/suspicious?limit=12` | ok；11-10 10:45:43 | 2m；11-10 11:11:45 | —/—/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `commodities-watch` | `/runtime/markets/commodities` | ok；11-10 10:43:08 | 5m；11-10 11:08:15 | —/—/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `crypto-watch` | `/runtime/markets/crypto` | ok；11-10 10:43:18 | 5m；11-10 11:08:25 | —/—/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `crypto-order-flow` | `/runtime/crypto/order-flow` | ok；11-10 10:45:52 | 共享 crypto-strategy；不引用旧 Finance 同名 owner | 30s/2m/15m | ready / ready | 保留原始来源时间/覆盖范围 |
| `crypto-oracle-reference` | `/runtime/crypto/oracle-reference` | partial；11-10 10:46:17 | 共享 market-data 原始参考源 | 5s/15s/15m；不持久化 | degraded / degraded | 原始 TWAP 可见；PM book/连续性有缺口 |
| `options-implied-probability` | `/runtime/crypto/order-flow` | ok；11-10 10:45:52 | 共享 crypto-strategy；不引用旧 Finance 同名 owner | 30s/2m/15m | ready / ready | BTC/ETH 期权分布；不是任意资产全覆盖 |
| `crypto-exchange-inflow` | `/runtime/crypto/order-flow` | ok；11-10 10:45:52 | 共享 crypto-strategy；不引用旧 Finance 同名 owner | 启动/1d/1d | ready / ready | 历史 BTC，非实时流入 |
| `ai-model-race` | `/runtime/tech/ai-model-race?limit=36` | ok；11-10 10:31:39 → 11-10 11:01:46 | 10m；11-10 11:01:46 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `big-tech-market-cap` | `/runtime/tech/big-tech-market-cap?limit=16` | ok；11-10 10:32:17 → 11-10 11:02:26 | 10m；11-10 11:02:26 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `consumer-app-pulse` | `/runtime/tech/consumer-app-pulse?limit=40` | ok；11-10 10:32:30 → 11-10 11:02:39 | 10m；11-10 11:02:39 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `crypto-funding-watch` | `/runtime/crypto/funding-watch?limit=120` | ok；11-10 10:46:12 | 1m；11-10 11:11:04 | —/—/— | ready / ready | 保留原始来源时间/覆盖范围 |
| `defi-token-watch` | `/runtime/finance/defi-token-watch?limit=10` | ok；11-10 10:30:54 → 11-10 11:01:10 | 5m；11-10 11:11:14 | 5m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `defi-yield-monitor` | `/runtime/finance/defi-yield-monitor?limit=10` | ok；11-10 10:24:48 → 11-10 10:59:54 | 10m；11-10 11:09:54 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `defi-security-watch` | `/runtime/finance/defi-security-watch?limit=12` | ok；11-10 10:24:54 → 11-10 10:59:55 | 10m；11-10 11:09:55 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `crypto-perp-funding` | `/runtime/crypto/order-flow` | ok；11-10 10:45:52 | 共享 crypto-strategy；不引用旧 Finance 同名 owner | 30s/2m/15m | ready / ready | 保留原始来源时间/覆盖范围 |
| `tradfi-perp-radar` | `/runtime/finance/tradfi-perp-radar?limit=24` | partial；11-10 10:18:22 → 11-10 10:54:52 | 共享 finance-external；15m；11-10 11:09:51 | 10m/15m/1d | ready / degraded | 保留原始来源时间/覆盖范围 |
| `ipo-news-watch` | `/runtime/finance/ipo-news-watch?limit=12` | ok；11-10 10:24:59 → 11-10 10:59:56 | 10m；11-10 11:09:56 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `broker-research-watch` | `/runtime/finance/broker-research-watch?limit=12` | ok；11-10 10:25:26 → 11-10 11:00:27 | 10m；11-10 11:10:50 | 10m/15m/1d | degraded / ready | Zacks/Edison 已恢复；Water Tower no-links/需登录 |
| `global-index-monitor` | `/runtime/finance/global-index-monitor?limit=12` | ok；11-10 10:25:40 → 11-10 11:00:40 | 10m；11-10 11:11:00 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `commodity-equity-transmission` | `/runtime/finance/commodity-equity-transmission?limit=8` | ok；11-10 10:34:47 → 11-10 11:03:52 | —；— | 5m/5m/15m | ready / ready | 保留原始来源时间/覆盖范围 |
| `crypto-fear-greed` | `/runtime/finance/crypto-fear-greed?limit=6` | partial；11-10 10:26:43 → 11-10 11:02:12 | 10m；11-10 11:02:12 | 10m/15m/1d | degraded / degraded | AAII/CNN 缺失，其余来源可读 |
| `crypto-etf-flow` | `/runtime/finance/crypto-etf-flow?limit=8` | ok；11-10 10:18:22 → 11-10 10:54:52 | 共享 finance-external；15m；11-10 11:09:51 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `stablecoin-monitor` | `/runtime/crypto/order-flow` | ok；11-10 10:45:52 | 共享 crypto-strategy；不引用旧 Finance 同名 owner | 30s/2m/15m | ready / ready | 保留原始来源时间/覆盖范围 |
| `blockchain-policy-news` | `/runtime/finance/blockchain-policy-news?limit=12` | ok；11-10 10:26:46 → 11-10 11:02:12 | 10m；11-10 11:02:12 | 10m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `trade-policy-radar` | `静态` | context；— | —；— | —/—/— | idle / idle | 静态研究视图，无后台新数据采集 |
| `geo-sanctions-shock` | `/runtime/world/geo-sanctions-shock?limit=2000` | ok；11-10 10:33:10 → 11-10 10:57:08 | 5m；11-10 11:05:23 | 5m/10m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `global-transport-shipping` | `/runtime/transport/global-shipping?limit=14` | ok；11-10 09:49:45 → 11-10 10:51:04 | 1h；11-10 10:52:20 | 15m/2h/6h | ready / ready | 保留原始来源时间/覆盖范围 |
| `cpi-release-command-center` | `/runtime/macro/cpi-release-command-center?limit=36` | degraded；11-10 10:22:45 → 11-10 10:57:45 | 30m；11-10 10:22:45 | 30m/45m/18h | ready / degraded | 曾继承 nowcast stale；后续原源恢复 |
| `cpi-components-pressure-registry` | `/runtime/macro/cpi-components-pressure-registry?limit=48` | ok；11-10 10:22:45 → 11-10 10:57:45 | 30m；11-10 11:07:46 | 30m/45m/18h | ready / ready | 保留原始来源时间/覆盖范围 |
| `goods-tariff-supply-watch` | `/runtime/macro/goods-tariff-supply-watch?limit=36` | ok；11-10 10:22:45 → 11-10 10:57:46 | 30m；11-10 11:07:47 | 30m/45m/18h | ready / ready | 保留原始来源时间/覆盖范围 |
| `labor-services-inflation-monitor` | `/runtime/macro/labor-services-inflation-monitor?limit=36` | ok；11-10 10:22:46 → 11-10 10:57:46 | 30m；11-10 11:07:47 | 30m/45m/18h | ready / ready | 保留原始来源时间/覆盖范围 |
| `fed-reaction-growth-risk-board` | `/runtime/macro/fed-reaction-growth-risk-board?limit=36` | ok；11-10 10:22:46 → 11-10 10:57:46 | 30m；11-10 11:07:48 | 30m/45m/18h | ready / ready | 保留原始来源时间/覆盖范围 |
| `polymarket-macro-map` | `/runtime/macro/polymarket-map?limit=12` | degraded；11-10 10:32:52 → 11-10 11:02:52 | 3m；11-10 11:08:53 | 3m/3m/2h | degraded / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `cpi-release-calendar` | `/runtime/macro/cpi-release-calendar?limit=8` | ok；11-10 10:31:33 | 1h；11-10 10:31:33 | 1h/3h/3h | ready / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `energy-gasoline-shock` | `/runtime/macro/energy-gasoline-shock?limit=6` | ok；11-10 06:47:53 | 6h；11-10 06:47:53 | 6h/18h/18h | ready / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `global-temperature-monitor` | `/runtime/weather/temperature-monitor?limit=60` | degraded；11-10 09:47:48 → 11-10 10:47:48 | 1h；11-10 10:47:50 | 1m/2h/1d | degraded / idle | 50 城预报；最终 539 snapshot / 88 空书 |
| `weather-market-browser` | `复用 global-temperature-monitor；/runtime/weather/temperature-monitor?limit=60` | degraded；11-10 09:47:48 → 11-10 10:47:48 | 1h；11-10 10:47:50 | 1m/2h/1d | ready / degraded | 共享 owner，不另采集 |
| `weather-city-snapshot` | `复用 global-temperature-monitor；/runtime/weather/temperature-monitor?limit=60` | degraded；11-10 09:47:48 → 11-10 10:47:48 | 1h；11-10 10:47:50 | 1m/2h/1d | degraded / degraded | 共享 owner，不另采集 |
| `weather-quote-detail` | `复用 global-temperature-monitor；/runtime/weather/temperature-monitor?limit=60` | degraded；11-10 09:47:48 → 11-10 10:47:48 | 1h；11-10 10:47:50 | 1m/2h/1d | degraded / degraded | 定点自动刷新后 11/11 当前、0 retained |
| `weather-quote-table` | `复用 global-temperature-monitor；/runtime/weather/temperature-monitor?limit=60` | degraded；11-10 09:47:48 → 11-10 10:47:48 | 1h；11-10 10:47:50 | 1m/2h/1d | degraded / degraded | 定点自动刷新后 11/11 当前、0 retained |
| `weather-trend-detail` | `复用 global-temperature-monitor；/runtime/weather/temperature-monitor?limit=60` | degraded；11-10 09:47:48 → 11-10 10:47:48 | 1h；11-10 10:47:50 | 1m/2h/1d | ready / degraded | 共享 owner，不另采集 |
| `weather-trend-7d` | `复用 global-temperature-monitor；/runtime/weather/temperature-monitor?limit=60` | degraded；11-10 09:47:48 → 11-10 10:47:48 | 1h；11-10 10:47:50 | 1m/2h/1d | ready / degraded | 共享 owner，不另采集 |
| `weather-news` | `/runtime/weather/news?limit=24` | degraded；11-10 10:34:50 → 11-10 11:01:38 | 5m；11-10 11:06:56 | 5m/15m/1d | ready / degraded | 两地错误于下一轮 11:12:18Z 自动恢复 |
| `world-clock` | `复用 global-temperature-monitor；/runtime/weather/temperature-monitor?limit=60` | degraded；11-10 09:47:48 → 11-10 10:47:48 | 1h；11-10 10:47:50 | 1m/2h/1d | ready / degraded | 时钟正常；外层共用天气来源状态 |
| `food-retail-basket-pressure` | `/runtime/macro/food-retail-basket?limit=8` | ok；11-10 06:47:45 | 6h；11-10 06:47:45 | 6h/45m/18h | stale / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `supply-tariff-import-watch` | `/runtime/macro/supply-tariff-import-watch?limit=8` | ok；11-10 06:52:58 | 6h；11-10 06:52:58 | 6h/45m/18h | stale / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `shelter-rent-oer-pressure` | `/runtime/macro/shelter-rent-oer-pressure?limit=8` | ok；11-10 06:52:58 | 6h；11-10 06:52:58 | 6h/45m/18h | stale / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `labor-wage-services-pressure` | `/runtime/macro/labor-wage-services-pressure?limit=8` | ok；11-10 06:52:58 | 6h；11-10 06:52:58 | 6h/45m/18h | stale / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `growth-demand-recession-tracker` | `/runtime/macro/growth-demand-recession-tracker?limit=8` | ok；11-10 06:52:58 | 6h；11-10 06:52:58 | 6h/45m/18h | stale / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `inflation-nowcast` | `/runtime/macro/inflation-nowcast` | stale；11-10 10:18:12 | 30m；11-10 11:11:12 | 30m/90m/90m | stale / 未启用 | 可选；后续路由修复 11:11:12Z ok；未观察下一 30m 轮次 |
| `fed-rates-polymarket-gap` | `/runtime/macro/fed-rates-polymarket-gap?limit=8` | ok；11-10 06:52:58 | 6h；11-10 06:52:58 | 6h/45m/18h | stale / 未启用 | 可选；慢源下一次采集未在本窗口验证 |
| `nba-scoreboard` | `/runtime/sports/nba?limit=10` | ok；11-10 10:34:44 → 11-10 11:03:37 | 1m；11-10 11:11:29 | 1m/3m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `nba-intel` | `/runtime/sports/nba-intel?limit=12` | ok；11-10 10:34:47 → 11-10 11:03:38 | 1m；11-10 11:11:29 | 1m/3m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `espn-matchup-predictor` | `/runtime/sports/nba-matchup-predictor?limit=8` | ok；11-10 10:34:50 → 11-10 11:03:40 | 1m；11-10 11:11:29 | 1m/3m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `esports-intel` | `/runtime/esports/grid-intel?limit=10` | ok；11-10 10:34:14 → 11-10 11:00:19 | 2m；11-10 11:10:13 | 2m/30m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `sports-odds` | `/runtime/sports/odds-monitor?limit=8` | ok；11-10 10:34:23 → 11-10 10:59:37 | 2h；11-10 10:49:04 | 5m/30m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `jin10-flash` | `/runtime/macro/jin10?limit=24` | ok；11-10 10:34:12 → 11-10 11:03:21 | 1m；11-10 11:11:24 | 1m/5m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `new-market-signals` | `/runtime/markets/new-signals?limit=12` | ok；11-10 10:33:14 → 11-10 11:03:20 | 20s；11-10 11:08:21 | 5m/15m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `lob-depth` | `/runtime/lob/token/<selected>` | 200/503；UNKNOWN；见源读回记录 | —；— | —/—/— | idle / idle | market-data gateway；2 次 503；连续性 UNKNOWN，见残留 1 |
| `f1-trackside` | `/runtime/sports/f1?limit=10` | ok；11-10 10:32:10 → 11-10 11:02:43 | 3m；11-10 11:08:51 | 3m/5m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `company-events` | `/runtime/disclosures/company-events` | ok；11-10 10:15:40 → 11-10 10:50:27 | —；— | 10m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `policy-progress` | `/runtime/disclosures/policy-progress` | degraded；11-10 10:25:20 → 11-10 11:00:09 | —；— | 10m/1d/7d | degraded / degraded | 保留 GovInfo 404 |
| `politics-election` | `/runtime/politics/election` | ok；11-10 10:25:27 | 1h；11-10 10:25:22..11-10 10:25:27 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `politics-early-vote` | `/runtime/politics/early-vote` | ok；11-10 10:25:23 | 1h；11-10 10:25:23 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `politics-nomination` | `/runtime/politics/nomination` | ok；11-10 08:15:24 | 1d；11-10 02:55:11..11-10 08:15:24 | 10m/3d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `politics-seats` | `/runtime/politics/seats` | ok；11-10 10:15:17 → 11-10 10:45:26 | 30m；11-10 10:45:26 | 10m/90m/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `politics-campaign-finance` | `/runtime/politics/campaign-finance` | degraded；11-10 09:15:17 | 6h；11-10 08:40:41..11-10 09:15:17 | 30m/18h/7d | degraded / degraded | 保留 FEC 缺失字段 |
| `politics-government` | `/runtime/politics/government` | ok；11-10 10:15:17 → 11-10 10:45:26 | 30m；11-10 10:45:26 | 10m/90m/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `politics-executive` | `/runtime/politics/executive` | ok；11-10 10:25:22 → 11-10 11:00:10 | ；11-10 11:00:10 | 10m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `politics-appointments` | `/runtime/politics/appointments` | ok；11-10 10:15:20 → 11-10 10:45:29 | 30m,1h,1d；11-10 06:07:41..11-10 10:45:29 | 10m/90m/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `politics-funding` | `/runtime/politics/funding` | ok；11-10 10:05:12 → 11-10 10:45:31 | 30m,105m,1d；11-10 03:10:22..11-10 10:45:31 | 5m/90m/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `geo-conflict-watch` | `/runtime/external/geo-conflict-watch` | ok；11-10 10:33:10 → 11-10 10:57:08 | 1h；11-10 10:17:03..11-10 10:57:08 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `geo-ceasefire-watch` | `/runtime/external/geo-ceasefire-watch` | ok；11-10 10:17:03 | 1h；11-10 10:17:03 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `geo-territory-control` | `/runtime/external/geo-territory-control` | ok；11-10 10:17:03 | 1h；11-10 10:17:03 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `geo-diplomacy-calendar` | `/runtime/external/geo-diplomacy-calendar` | ok；11-10 10:17:03 | 1h；11-10 10:17:03 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `geo-treaty-tracker` | `/runtime/external/geo-treaty-tracker` | ok；11-10 08:17:46 | 1d；11-10 08:17:46 | 1h/3d/14d | ready / ready | 保留原始来源时间/覆盖范围 |
| `weather-precipitation` | `/runtime/external/weather-precipitation` | ok；11-10 09:47:48 → 11-10 10:47:48 | ；11-10 10:47:48 | 10m/2h/6h | ready / ready | 保留原始来源时间/覆盖范围 |
| `weather-drought` | `/runtime/external/weather-drought` | ok；11-10 08:07:41 | 1d；11-10 08:07:41 | 1h/3d/14d | ready / ready | 保留原始来源时间/覆盖范围 |
| `weather-extremes` | `/runtime/external/weather-extremes` | ok；11-10 10:34:36 → 11-10 11:04:14 | ；11-10 11:04:14 | 5m/10m/15m | ready / ready | 保留原始来源时间/覆盖范围 |
| `weather-storm-advisory` | `/runtime/external/weather-storm-advisory` | ok；11-10 10:34:36 → 11-10 11:02:58 | ；11-10 11:02:58 | 10m/30m/1h | ready / ready | 保留原始来源时间/覆盖范围 |
| `sports-spread-monitor` | `/runtime/external/sports-spread-monitor` | ok；11-10 10:27:58 → 11-10 11:03:09 | 10m；11-10 11:03:09 | 10m/30m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `sports-total-monitor` | `/runtime/external/sports-total-monitor` | ok；11-10 10:27:58 → 11-10 11:03:09 | 10m；11-10 11:03:09 | 10m/30m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `sports-player-props` | `/runtime/external/sports-player-props` | ok；11-10 10:27:58 → 11-10 11:03:09 | 10m；11-10 11:03:09 | 10m/30m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `sports-tournament-path` | `/runtime/external/sports-tournament-path` | ok；11-10 10:22:58 → 11-10 10:49:40 | 15m；11-10 10:49:40 | 10m/45m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `sports-season-race` | `/runtime/external/sports-season-race` | ok；11-10 08:28:25 | 6h；11-10 08:28:25 | 10m/18h/3d | ready / ready | 保留原始来源时间/覆盖范围 |
| `sports-awards-watch` | `/runtime/external/sports-awards-watch` | ok；11-10 08:28:27 | 6h；11-10 08:28:27 | 30m/18h/3d | ready / ready | 保留原始来源时间/覆盖范围 |
| `esports-map-state` | `/runtime/external/esports-map-state` | ok；11-10 10:33:27 → 11-10 10:49:43 | 15m；11-10 10:49:43 | 10m/45m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `esports-tournament-path` | `/runtime/external/esports-tournament-path` | ok；11-10 10:22:56 → 11-10 10:58:04 | 15m；11-10 10:58:04 | 10m/45m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `crypto-listing-watch` | `/runtime/external/crypto-listing-watch` | ok；11-10 10:33:58 → 11-10 10:59:24 | 5m；11-10 10:59:24 | 5m/15m/30m | ready / ready | 保留原始来源时间/覆盖范围 |
| `crypto-project-milestones` | `/runtime/external/crypto-project-milestones` | ok；11-10 10:18:00 → 11-10 10:49:09 | 30m；11-10 10:49:09 | 10m/90m/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `chain-metrics-monitor` | `/runtime/external/chain-metrics-monitor` | ok；11-10 10:17:59 | 1h；11-10 10:17:58..11-10 10:17:59 | 15m/3h/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `fiscal-tax-monitor` | `/runtime/external/fiscal-tax-monitor` | ok；11-10 08:13:07 | 6h,1d；11-10 06:09:09..11-10 08:13:07 | 30m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `merger-progress` | `/runtime/external/merger-progress` | ok；11-10 10:33:55 | 30m；11-10 10:33:49..11-10 10:33:55 | 15m/90m/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `private-valuation-watch` | `/runtime/external/private-valuation-watch` | ok；11-10 09:20:35 | 6h；11-10 08:28:43..11-10 09:20:35 | 30m/12h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `ai-leaderboard-watch` | `/runtime/external/ai-leaderboard-watch` | ok；11-10 06:09:12 | 6h；11-10 06:09:12 | 30m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `art-auction-watch` | `/runtime/external/art-auction-watch` | ok；11-10 06:09:18 | 6h；11-10 06:09:18 | 30m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `culture-box-office` | `/runtime/external/culture-box-office` | ok；11-10 06:09:57 | 6h；11-10 06:09:57 | 30m/1d/14d | ready / ready | 保留原始来源时间/覆盖范围 |
| `culture-awards-race` | `/runtime/external/culture-awards-race` | ok；11-10 06:09:26 | 6h；11-10 06:09:26 | 30m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `culture-music-charts` | `/runtime/external/culture-music-charts` | ok；11-10 09:10:29 | 6h；11-10 09:10:29 | 30m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `product-release-watch` | `/runtime/external/product-release-watch` | ok；11-10 10:17:51 | 1h；11-10 10:17:51 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `public-figure-events` | `/runtime/external/public-figure-events` | ok；11-10 10:22:57 | 1h；11-10 10:22:57 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `reality-show-progress` | `/runtime/external/reality-show-progress` | ok；11-10 06:09:23 | 6h；11-10 06:09:23 | 30m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `research-evidence-watch` | `/runtime/external/research-evidence-watch` | ok；11-10 06:09:48 | 6h；11-10 06:09:48 | 30m/1d/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `social-window-monitor` | `/runtime/external/social-window-monitor` | ok；11-10 10:22:56 | 1h；11-10 10:22:56 | 10m/3h/1d | ready / ready | 保留原始来源时间/覆盖范围 |
| `space-mission-watch` | `/runtime/external/space-mission-watch` | ok；11-10 10:17:43 | 1h；11-10 10:17:43 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |
| `mentions-evidence` | `/runtime/external/mentions-evidence` | ok；11-10 10:22:57 | 1h,1d；11-10 08:12:53..11-10 10:22:57 | 10m/3h/7d | ready / ready | 保留原始来源时间/覆盖范围 |

## 证据与回滚

原始证据目录：`/home/jiahuaiyu/.codex/visualizations/2026/11/10/panel-reliability/`。

- `public-{first,second,final}.json`：三轮完整 payload/响应时间；`public-targeted.json` 为随后 Nowcast/天气/体育/研究正式回读。
- `parsers-final.json`、`desktop-panels.json`、`mobile-panels.json`、`hidden-panels.json`：121 项身份、解析结果、可视 DOM、网络记录。`desktop-first-pass-mixed-viewport.json` 是作废的交叉视口首轮，不用于桌面验收。
- `public-trade-progress.json` 是两个相同市场的新成交事件/行 hash 变化；`source-cycles.jsonl`：9 个关键 API、每分钟一次、24 轮；`owner-meta-{first,second,final}.json` 为正式采集元数据（含不属于当前 Panel 的历史条目，不能把 91 条全算活跃 owner）。
- `browser-autorefresh.json` 与 `browser-weather-recovery.json`：没有手动刷新时收到新 payload 的证据；`lob-origin.json` 与 `lob-gateway-check.json` 保留 LOB 未通过部分。
- `deployment.json`、构建日志、`desktop-verified-*.jpg`、`mobile-*.jpg`、`desktop-weather-quotes-recovered.jpg` 为发布和真实页面证据。

回滚使用本轮保留的部署前文件/私有 profile 值，按所属文件或 profile 单独回退；不恢复整个脏工作区、不删除已采集数据、不重置用户布局。主链接保持备用；来源路由只改目标域名。此记录后续若发现新失败，应追加新观察，不能以本次 300 个成功响应覆盖未来故障。

## LOB 与慢周期来源跟进（19:46 CST 起）

这一段只验收本次相关消费者，不把前面的 121 项首轮检查升级为全部来源持续通过。
原始证据位于 `/home/jiahuaiyu/.codex/visualizations/2026/11/10/lob-panel-recovery/`。

### 已发布的修复

- market-data `946a05ea`：HTTP reader 保持最多 4 个实际读取，允许至多 16 个不同 key 在同一 2 秒总预算内等待；重复 key 合并请求。过去四个加密参考读取会直接排斥第五个页面请求。已确认的 snapshot handoff 不再因为关闭连接时的 reset 误报失败；传输错误的负缓存从 15 秒缩短为 2 秒，校验错误仍为 15 秒。7 项并发、取消、截止和连接交接测试通过。19:46:19 重启 reader。生产文件还包含任务开始前已有的 7 行新增、16 行删除（快照语义与 process-only health），这些未纳入本次提交，部署文件 hash 单列在 `deployment.json`。
- 前端 `d712ea50bf6bad623cb2ee7999f50ebe30e09428`：七个六小时来源的浏览器检查从六小时改为五分钟；freshness 统一为九小时，保留十八小时展示边界和原来源时钟。采集仍由既有六小时 owner 完成。8 项共享宏观缓存测试通过，Node 22 干净 `git archive` 生产构建通过。约 19:57 发布到实际腾讯云入口，根域名和 www 的 `/release-sha` 核对一致，页面主脚本为 `index-Dz8_v7eg.js`。
- 后端 `fbce718b`：日历和能源使用已有 `collection_delay`，部分成功也按失败轮次调度；5/10/20/30 分钟退避，成功后恢复正常周期，扣除本轮耗时且至少休息 30 秒。17 项针对测试通过。20:35 日历自然轮次出现三个 FRED 日历错误后，日历任务于 20:40:44 发布。能源保留原定时轮次再发布，实际身份另见 `deployment.json`。

### LOB：传输与采集分别验收

两个实际页面市场为 `3848348`（Fed 加息 25bps）与 `3846901`（Fed 不变），分别归属 `0009`、`0041` cohort。19:55 和 20:00 分别将既有 Q-0009/Q-0041 的 `assets_per_connection` 从 2000 调整为 64，保留 token 范围、路由与共享额度。确实出现新 native baseline、source event 和 Gateway cut 推进，页面也自动收到更新；随后又出现来源未就绪，**小批次调整不是连续性修复通过**。21:07:44–21:07:49 已仅将这两个试验字段恢复为原来的 2000 并重启对应 Q 服务，其他当前配置不回退；没有把未通过的试验留作正式修复。

观察期间独立 LOB 发布把来源版本从 2.2.36 连续推进到 2.2.40，并重启 P/Q/G；这些源码/部署不属于本次提交。20:26 的一次公网 LOB 503 对应 Gateway 重启窗口，HTTP reader 日志出现 `ConnectionRefusedError`，随后自动恢复，不能声称零 503。另有五个并行测试页面触发按 IP 的 `2r/s + burst 4` 盘口限流，保留 429；没有放大限流来掩盖测试负载。浏览器所在机器还持续出现 `ERR_NETWORK_CHANGED`，与服务器返回 503 分开统计。

操作边界：20:18 尝试调整 P-0041 时，版本前置检查因来源已升级而失败，配置没有写入；但后续独立 shell 命令仍执行了 P-0041 重启。其 `assets_per_connection` 保持 2000，此次重启不能计为小批次修复，已保存 `p0041-restart-note.json`。后续源变更没有继续扩大，避免与独立发布互相覆盖。

`upstreamCompleteness=UNKNOWN` 是当前来源明确保留的证据边界，不是缓存 TTL 或 HTTP 错误码。原生消息的时间戳/hash 与本地提交序号不能证明没有遗漏每一条上游变化；本次没有伪造 complete/continuous。`upstreamReady`、原事件时间、cut/sourceRef 推进以及期间的 GAP 必须分别记录。窗口内已经看到真实的 `SOURCE_EVENT_LAG`（推进中的事件延迟约 34–71 秒）、恢复额度排队及握手超时，故不能宣布采集连续可用。

### 慢周期轮次与展示验证

浏览器在真实生产 URL 保持开启，无 API/瓦片替换；七个来源在 19:58、20:03、20:08 等轮次自动检查。文化、Nowcast、能源保留了原定时轮次；FRED 日历原轮次失败后进行了来源路由恢复，食品及五个 driver 随之由既有 owner 重启重采。这是故障恢复采集，不能冒充未经干预的定时轮次。没有删除快照或修改系统时间。正式 SQLite、采集元数据、API payload 和页面自动响应分别保存。统计发布日期没有变化不代表未采集；反过来，仅 `generatedAt` 改变也不足以证明逐项来源重采。

已确认六个文化来源在 20:12 的原定时服务轮次重新成功采集，20:19 页面自动收到对应版本；Nowcast 在 20:11、20:41 正常重采，20:19 页面已收到 20:11 版本。五个宏观汇总在 20:28 生成新快照，20:29 页面自动接收；当时多数基础行仍是旧采集时间，未把汇总写入当作基础来源更新。

FRED 两个原出口在 20:44–20:45 的同 URL 比较中出现 ConnectTimeout、ReadTimeout，成功的 CSV 也耗时约 19.9 秒。现有隔离出口同 CSV 0.775 秒、同日历 1.198 秒，日历真实解析出 12 个 CPI 日期。仅替换 `.env` 中 FRED 域名的 primary，保留原第二出口为 backup；其他域名值逐项比对不变，未切换主 Clash。20:47:10 重启日历、食品和五-driver owner；20:50:54 重启既有 registry 应用同一路由并合成新基础数据。该 registry 的既有去重发布器同时发出 1 条 goods/tariff 通知，未新建通知任务。

正式 SQLite 对比：食品 8 条、五个 driver 的 59 条共 **67 条原采集时间全部推进**；这些是条目数，含重复 FRED 序列和公告条目，不是 67 个唯一源。日历 55 条 `verifiedAt` 全部推进，所有必需来源为 ok。EIA 在未重启前于 20:47:54 正常重采 3 项，然后 20:49:13 发布失败重试修复并完成启动采集。EIA 没有逐行 fetchedAt，证据是正式轮次确实执行三次 XLS 获取并成功解析，而不是给统计日期补写当前时间。Cleveland Fed 的原始 Updated 仍为 11/09；经济统计月、公告发布时间和 EIA 观察日保持来源原值。

以下时间均为 CST；自动响应来自持续打开的生产页面，未点击 Refresh/Retry。记录的是新正式快照进入浏览器，不等于每个数值都发生变化。

| Panel ID | 本轮正式新快照 | 页面自动收到 | 数据边界 |
| --- | --- | --- | --- |
| `energy-gasoline-shock` | 20:49:16 | 20:53:02 | 3 项 XLS；原自然轮次 20:47:54 已于 20:48:01 进入页面 |
| `food-retail-basket-pressure` | 20:47:15 | 20:48:02 | 正式 8 条采集时间推进；API 响应 8 条 |
| `supply-tariff-import-watch` | 20:47:32 | 20:48:02 | 正式 15 条采集时间推进；API 响应 8 条 |
| `shelter-rent-oer-pressure` | 20:47:35 | 20:48:02 | 正式 7 条采集时间推进；API 响应 7 条 |
| `labor-wage-services-pressure` | 20:47:42 | 20:48:02 | 正式 17 条采集时间推进；API 响应 8 条 |
| `growth-demand-recession-tracker` | 20:47:46 | 20:48:03 | 正式 10 条采集时间推进；API 响应 8 条 |
| `fed-rates-polymarket-gap` | 20:47:53 | 20:48:03 | 正式 10 条采集时间推进；API 响应 8 条 |
| `inflation-nowcast` | 20:41:18 | 20:49:28 | 另有 20:11 自然轮次；原发布 Updated=11/09 |
| `cpi-release-calendar` | 20:47:17 | 20:49:28 | 55 条重新核验；当前响应 8 条，发布期不伪造 |
| `cpi-release-command-center` | 20:50:56 | 20:59:19 | 24 条汇总，复用新基础行及其原时钟 |
| `cpi-components-pressure-registry` | 20:50:56 | 20:59:19 | 25 条汇总，复用新基础行及其原时钟 |
| `goods-tariff-supply-watch` | 20:50:57 | 20:59:20 | 15 条汇总，复用新基础行及其原时钟 |
| `labor-services-inflation-monitor` | 20:50:58 | 20:59:20 | 17 条汇总，复用新基础行及其原时钟 |
| `fed-reaction-growth-risk-board` | 20:50:59 | 20:59:21 | 20 条汇总，复用新基础行及其原时钟 |
| `ai-leaderboard-watch` | 20:12:21 | 20:19:21 | 既有六小时来源自然轮次；响应 100 条 |
| `art-auction-watch` | 20:12:27 | 20:19:24 | 既有六小时来源自然轮次；响应 22 条 |
| `culture-box-office` | 20:12:53 | 20:19:24 | 既有六小时来源自然轮次；响应 50 条 |
| `culture-awards-race` | 20:12:41 | 20:19:23 | 既有六小时来源自然轮次；响应 10 条 |
| `reality-show-progress` | 20:12:38 | 20:19:23 | 既有六小时来源自然轮次；响应 13 条 |
| `research-evidence-watch` | 20:12:46 | 20:19:25 | 既有六小时来源自然轮次；响应 32 条 |

桌面相关消费者逐项 DOM 与自动网络响应见 `desktop-final-panels.json`、`culture-rendered-final.json`。手机实际 390×844 视口：9 个可选宏观 Panel 通过普通库添加，已有布局前缀保留；添加后刷新前后的 120 个 ID/顺序一致。初轮滚动后前方长内容改变高度，目标 Panel 离开视口，出现 idle/取消后错误，不能算通过；最终保持目标在视口后 9/9 为 ready，见 `mobile-stable-panels.json` 与 `mobile-stable-*.png`。没有点 Retry 或清缓存。手机 CPI 日历窄列仍有挤压，数据可见不代表窄屏排版全部通过。

### 最终未通过项与证据边界

- LOB 本地 19:53:02–21:07:49 每个市场采样 300 次，600 次均为 HTTP 200；但 3848348 只有 71 次两侧 upstreamReady，3846901 只有 107 次。最长连续 ready 采样段分别约 255 秒、510 秒，不能证明采样间隙无缺口。第一市场末次原事件停在 20:42:34，重读观察时间推进不算新数据。
- 同期主页面 LOB HTTP 响应 1694 次均为 200；另外两个关联页面共 2185 次中 2165 个 200、19 个 429、1 个 503。不同采样覆盖不同时间点；不能用本地 600 个 200 抹去公网实际 503。浏览器网络变化造成的失败请求不在 HTTP 响应分母内。
- Relay 最后直读：Q-0009 对应 Relay 275 条连接，最大发送耗时约 0.35 秒；Q-0041 对应 Relay 326 条连接，曾出现约 **26.65 秒发送阻塞**。这是 Relay→采集端传输压力的证据，不足以独自归因所有上游事件滞后。尝试现有隔离出口访问这两个 Relay 均获来源 IP ACL 403，未改白名单、未换正式 LOB 路径。源恢复排队、native baseline 缺失和推进中事件滞后仍存在，UNKNOWN 保留。
- 相关页面另记录 11 次选中市场 Flow 503、1 次 weather/books 503；后来自动恢复。当前 ClickHouse 简化查询不等于完全消除了间歇服务失败。Crypto 指定 TWAP 原事件继续推进，但 LOB 报价仍有数分钟旧事件，不能将 TWAP 新数据作为盘口连续性证据。
- 未到期的其他六小时/日级来源没有借此升级为多周期通过；本轮是上表 20 个相关慢周期消费者的补充验收，并非所有 121 个 Panel 的所有源已持续健康。

新增证据：`acceptance-summary.json`、`macro-sqlite-{before,after}-cycle.json`、`macro-owner-rounds.json`、`fred-route-{probe,recovery}.json`、`canary-rollback.json`、`relay-final-health.json`、`deployment.json`。持续采样的 `.jsonl` 在采样结束后压缩为 `.jsonl.gz`，保存完整原响应/原始时间，不只保留成功摘要。临时浏览器和观察进程已结束；任务构建/探针文件清理，回滚文件另行保留。
