# 全量 Panel 新数据与传输恢复记录（2026-11-10）

后续修复与全 121 项线上复验见 [第二轮数据可靠性记录](panel-data-reliability-2026-11-10.md)；以下保留当时的失败和验收边界。
这是当次修复和观察记录，不是全站长期健康声明。缓存/TTL/WorldMonitor 完整参数仍见 [前次逐项审计](panel-cache-loading-audit-2026-11-10.md)；当前约束见 [数据链路](website-data-link.md)、[天气](weather-panel-runtime.md)、[宏观](macro-panel-data-contract.md) 与 [Agent](../agent/README.md)。

## 范围与结果边界

- 前端 registry 121 项逐项归类：93 个直接 Runtime 拥有者、7 个天气共享视图、21 个参数化/上下文/静态视图。111 项默认启用，10 项原本默认关闭；没有重置用户布局或强行开启隐藏项。
- 本机正式 API 的 93 份实际 payload 经前端真实 parser 检查，对应 100 项 owner/共享视图均接纳，0 项拒收。此结论不等于字段齐全、行情可交易或来源完整。
- 从腾讯云经真实 `https://polymonitor.club` 逐一读取 93 个公共接口：93/93 可解析 JSON；中位 2.145s、95 分位 9.034s、最慢天气 33.366s。这一轮使用 gzip，不能当成后续 Brotli 的性能数据。
- 另读 15 份上下文 API；选中市场 549771 的成交流和真实 token LOB 单独检查。表中的 API 200 不掩盖其子字段、历史覆盖和来源资格。
- 浏览器实际访问生产 URL，未替换 API/瓦片；桌面逐一经过 111 个默认 Panel，刷新前后布局一致。访问端代理发生过 ERR_NETWORK_CHANGED，另用腾讯云上的临时 Chrome 排除本机代理，仍复现网站侧传输错误。桌面首轮最终 68 ready / 19 degraded / 16 stale / 7 idle / 1 error，不能汇总成“111 个健康”。idle 是上下文组件标记，不自动等于没有数据。

## 已修复且取得新数据的链路

1. Breaking Radar：采集遵守来源时间，Wikimedia 使用带运营方联系信息的 Bot 标识；每日关注度有独立持久缓存和原始日期，不伪装为当前新闻。复用既有、符合公开权限的 public-content 文章，修正 15m/1h/24h 计数与市场列表读取。最后观察有 20 条新 NWS 报道、5 个主题；只有极端天气主题具备本轮合格实时报道，另外主题主要为每日关注度。GDELT 仍在 429 冷却，未清除冷却或通过换 IP 规避。
2. 天气：修正市场目录/盘口恢复后整包仍停留在 degraded 的状态；50 城市的模型、METAR、24 小时/7 天预报逐项核查。预报生成时间从 07:47:49Z 推进到 08:47:47Z，再到 09:47:48Z，独立目录与盘口时间继续推进。未使用 wttr 回退不是缺源，49 城市匹配市场也不等于第 50 城市应编造市场。
3. 天气新闻：发现普通 GET 还会启动每个 API worker 的 RSS 采集，绕过正式拥有者；已改为默认只读 SQLite，Redis 仅本地缺失回退。后台采集使用验证成功的既有专用出口；09:18:56Z 与 09:24:15Z 两轮正式结果为 55 查询正常、1 合法空结果、0 来源错误。原文章发布时间未改写。
4. Big Tech：报价先于慢市值批次，仍共用 3 线程和 180s 总预算；Nasdaq 使用既有独立出口。正式多轮达到 24/24 新报价、24/24 市值、0 保留旧值，API 读取最新发布。
5. CPI 日历：复用已验证 FRED 传输和有界读取，保留原解析、时区、参考期；CPI/就业/PPI 三个 FRED 来源及其余日历来源全部正常，08:29:26Z 正式发布且验收仍为 ok。
6. FEC：正式定时任务完整取得并解析支出 CSV，08:40:41Z 新发布；候选人文件随后于 09:15:17Z 再次正常发布。状态仍 degraded 的原因是若干官方记录缺支出方向，不能伪填；这与下载失败分开。
7. ESPN：预测接口直连反复 8s 超时，通过既有独立出口同一接口约 1s 返回。正式分钟任务连续发布 8 场预测，09:27:07Z 为 ok。随后确认 site.api.espn.com 比分/新闻仍走直连并超时，已接入同一验证出口；09:48:56–09:49Z 与 09:50:04–09:50:09Z 两轮重新发布比分/新闻/预测，最新为 8/6/8 条且 ok。NBA 官方阵容仍缺失，使用 ESPN 回退，不把比分可读当官方阵容齐全。
8. 三个 AI lens：SQLite 已有 08:00/08:02/08:04Z 新结果，而 API 曾优先返回 Redis 00:56/00:57/00:59Z 旧副本。读取改为正式 SQLite 优先、Redis 缺失回退；API 现与正式发布一致。模型生成成功不证明输入、计算或论断完整正确。

## 传输修复与实际边界

- API 在回连之前压缩所有注册公共 Panel JSON、相关公共地图 JSON 与 content/latest；浏览器接受且运行环境有 Brotli 时选择 br quality 4，否则 gzip level 5。保持数据、原始时钟、缓存头与 Vary，错误/流/私有内容不参与。天气同一完整约 3.18MB JSON，gzip 约 331KB、br 约 229KB；离线压缩耗时约 22ms，不是公网下载耗时。
- 已有两条 bulk、interactive 分开；新增公共 Panel 连接，失败回退既有 bulk。公共快照只匹配 registry 精确路径，避免慢地图按需查询使普通 Panel 一起被摘除。关闭 bulk 的整池被动摘除，但保留有界单请求切换和 systemd 重连。服务端 SSH 保活负责释放失联反向端口。
- 私网路径试验出现较高 RTT/重传，已撤回，生产仍使用原验证过的网站跳板；没有切换主 Clash。
- 天气 books 和 LOB 传输隔离到交互连接；LOB 原 3s 期限、限流、源资格与 UNKNOWN 保持。隔离后首次回读仍有 504，随后三次真实公网读取为 200、2.965/3.063/2.849s；不能称为彻底消除链路波动。
- 选中市场 flow 的 ClickHouse 第三步明确报 TOO_MANY_BYTES，32MiB 限额处读到 33.06MiB。三次单独进程内、总额仍 64MiB 的只读预算分配试验也失败（最后 2/12/48/2MiB 分配，第三步读到 51.51MiB 仍被拒绝）；未修改生产预算，未取消限额，未换用未经事实校验的底表。额外只读验证中，移除结果排序仍收到 24 行后跟 JSON exception，而不是完整 51 行；修改查询设置被 readonly=1 拒绝，未放宽权限。公共解析器现拒绝这种 HTTP 200 后追加的 JSON exception，防止把执行失败当成数据行；生产查询和限额保持不变。

## 尚未解决与既有业务边界

- GDELT 429 冷却仍生效，Breaking Radar 并未恢复所有主题的新闻覆盖。
- AAII 返回 403、CNN 返回 418；没有绕过访问限制。FRED 与 Alternative.me 可用不代表这两个源已恢复。
- Broker Research：Zacks 有新结果；Edison 当前列表无旧解析器识别的报告链接，Water Tower 为客户端渲染页且任务仍出现失败。已有可用报告不是全部供应商恢复。
- Policy Progress：100/101 跟踪法案取得，1 个 GovInfo 官方地址 404。FEC 有 9 条独立支出记录缺方向；宏观市场集合仍是有界候选，完整性 NOT_PROVEN；TradFi 有个别来源字段缺失；Crypto reference 原始窗口观测与部分合约资格缺失。这些不伪造补齐。
- 天气最新小时模型/METAR为 ok；盘口仍有部分保留值。09:49Z 附近一次 627 档检查为 528 snapshot / 88 no-book / 11 retained；no-book 表示该盘口读回无书，不伪造成可交易报价。被选择城市的 11/11 盘口持续刷新不能替代全部城市盘口连续性。
- 选中市场成交流的事实查询预算/索引问题未解决；LOB 源连续性 UNKNOWN 且公网短期限仍有超时。天气整包偏大，网络尾延迟仍存在，尚未完成真实隔夜或全天稳定性验收。

## 发布与验证记录

- 前端：干净导出的推送提交 `5eadb52362a0a215bf50c22ad3e5fec96d35f2c6` 构建，部署到实际承载域名的腾讯云。根域名/www 的 release-sha、入口与构建产物一致；没有把通用 GCP 文档当作实际主机。
- 后端自本轮 `0ef5c95d` 至 `31803aea` 的任务文件逐个核对前版本后发布；后续传输配置至 `4cf3efdd`；流式 ClickHouse 异常解析修正为 `110f9b72`。私有域名/出口/转发保存在 .env，未提交密钥或私有路由。
- 初次 Radar 依赖新增字段导致 API 启动失败，约 16:09:52–16:13:50 CST 不可用；已将 collector-only 依赖改为兼容可选字段并恢复服务。这个发布事故保留记录，不以随后成功覆盖。
- 前端 474 单测通过、1 跳过；构建和类型检查通过。相关后端聚合 208 项通过；随后 Brotli 130 项、天气新闻与路由 41 项、LOB renderer 7 项相关测试通过，计数有重叠，不相加为总覆盖。最后 JSON exception 修正另从提交的干净 archive 验证 ClickHouse 读取与市场 Panel 共 37 项通过；正式 API 中超预算的 flow 继续返回 503，没有伪造完整结果。
- 证据目录：`$HOME/.codex/visualizations/2026/11/10/panel-source-recovery/`。主要文件 acceptance-api.json、acceptance-parser.json、public-all-panels.json、verified-context-api.json、production-desktop-remote.json 与后续恢复/手机记录。临时并行 CDP 控制导致视口交叉的截图不纳入验收，后续按设备顺序复验。

## 浏览器后续复验（时间独立）

- 桌面恢复复验截至 09:35:21Z，111 项最后观察为 54 ready / 35 degraded / 13 stale / 7 idle / 2 error。两项 error 是 market-summary 与 weather-extremes；一次长滚动测试期间未继续可视的组件会停止请求，ERR_ABORTED 不能一律当作服务端失败。浏览器仍记录实际 502/503/504 与 HTTP/2 错误，故不宣称稳定性通过。
- 浏览器 IndexedDB 中直接读取到 DeFi 09:25:18Z、NBA 09:27Z、天气新闻 09:24:15Z、Breaking Radar 09:19:32Z，AI 三个 lens 为 08:00/08:02/08:04Z。这些是 payload 原时间，checkedAt 另存，证明本轮收到正式新发布，不是把隔夜副本刷新成“刚更新”。
- Brotli 的实际公网单次回读：天气新闻 8,058 bytes / 11.767s，content/latest 110,479 bytes / 13.762s，天气 225,331 bytes / 22.174s。仍有明显尾延迟；不能凭这组样本推导全日 P95 或所有用户网络改善幅度。
- 手机按设备顺序单独验证 390×844，已拍到 Breaking Radar、天气、小时预报、NBA、Big Tech 与 Market Summary 六个目标。前五项的实际内容/来源提示正常可见；Market Summary 的查询失败仍保留，旁边 Fed/Growth 的 12 秒传输超时也未算通过。重新加载后第一次定位被动态布局打断，补做重新载入前后布局对比一致，390px 页面无水平溢出；该次目标被上方动态内容移出视口，补充截图实际记录 Global Updates 新数据，不用它证明 Radar 恢复。原定位失败及离屏 idle 记录不删除。
- 临时浏览器仅访问真实生产网页，未拦截替换 API 或瓦片；未清除用户浏览器数据或重置布局。桌面与手机测试中的布局前后对比仅针对测试浏览器，不冒称读到了用户个人设备布局。

- Extreme Weather 定点 90 秒观察：idle → error → ready → ready；没有手动重试、没有刷新或清除缓存。第一次 HTTP 200 的响应体未在截止时间内读完而取消，后台自动重试后第二次成功展示新 NWS 告警。HTTP 200 与读取完成是不同的验收状态。
- 09:51Z 最后源复查：50 城预报、天气新闻、NBA 比分/新闻/预测及 Extreme Weather 的正式 API 均为 ok；天气盘口先前 partial 后自动恢复。这仍不抹去期间的保留值、无书盘口和传输错误。

## 121 项检查表

时间为源 payload 的 generatedAt（UTC 或其原始 offset），不是浏览器保存时间。公网列是该 owner 的本次 93 路逐项测试；共享视图复用同一读数。页面列为桌面首轮最后观察，后续恢复单独记录；默认关闭项没有伪造页面访问。

| Panel ID | 源/复用 owner | API 状态；原始时间；行数 | 公网读取 | 页面观察 / 限制 |
| --- | --- | --- | --- | --- |
| `active-markets` | `active-markets` | 市场目录 /markets；50 行；不代表全市场完整覆盖 | 另行上下文检查 | idle |
| `global-orderfilled` | `global-orderfilled` | 当前选中市场 /markets/549771/flow；503；ClickHouse 第三步 TOO_MANY_BYTES | 另行上下文检查 | idle |
| `oracle-feed` | `oracle-feed` | 选中市场 Oracle；200；不是扫描全局所有 Oracle | 另行上下文检查 | idle |
| `market-summary` | `market-summary` | 选中市场 focus-tile 200；flow 独立失败；目录价格不是实时 LOB | 另行上下文检查 | ready |
| `featured-market` | `featured-market` | 复用选中市场 focus-tile；不另采集 | 另行上下文检查 | idle |
| `price-implications` | `price-implications` | live；2026-11-10T08:00:03.427046Z；非列表 | 200 / 2.962s | ready |
| `price-chart` | `price-chart` | 选中市场 chart；200；仅其声明覆盖窗口 | 另行上下文检查 | idle |
| `sample-chain-trades` | `sample-chain-trades` | live；2026-11-10T08:02:02.687914Z；非列表 | 200 / 2.497s | ready |
| `oracle-timeline` | `oracle-timeline` | live；2026-11-10T08:04:02.473115Z；非列表 | 200 / 1.121s | ready |
| `related-news` | `related-news` | 共享 /content/latest；来源投影可读；浏览器发生过传输超时，后续路由隔离 | 另行上下文检查 | error |
| `breaking-event-radar` | `breaking-event-radar` | degraded；2026-11-10T09:19:32.955004Z；5 | 200 / 0.815s | degraded |
| `market-tv-wire` | `market-tv-wire` | ok；2026-11-10T09:17:45.288219Z；60 | 200 / 1.875s | ready |
| `market-youtube-channels` | `market-youtube-channels` | ok；2026-11-10T09:17:45.288219Z；55 | 200 / 2.132s | ready |
| `alpha-signal` | `alpha-signal` | /runtime/signals/alpha?limit=8；200；资格独立校验 | 另行上下文检查 | ready |
| `whale-tracker` | `whale-tracker` | /runtime/trades/whales?limit=14；200；有界事件窗口 | 另行上下文检查 | ready |
| `suspicious-flow` | `suspicious-flow` | /runtime/trades/suspicious?limit=12；200；有界事件窗口 | 另行上下文检查 | ready |
| `commodities-watch` | `commodities-watch` | /runtime/markets/commodities；200；源观察时间保留 | 另行上下文检查 | ready |
| `crypto-watch` | `crypto-watch` | /runtime/markets/crypto；200；源观察时间保留 | 另行上下文检查 | stale |
| `crypto-order-flow` | `crypto-order-flow` | 共享 /runtime/crypto/order-flow；200；crypto-strategy 原始字段，未证明所有资产连续覆盖 | 另行上下文检查 | stale |
| `crypto-oracle-reference` | `crypto-oracle-reference` | /runtime/crypto/oracle-reference；200/partial；原始窗口观测缺失；连续性 UNKNOWN | 另行上下文检查 | stale |
| `options-implied-probability` | `options-implied-probability` | 复用 crypto-strategy；BTC/ETH Deribit；不是每个资产都有合格分布 | 另行上下文检查 | stale |
| `crypto-exchange-inflow` | `crypto-exchange-inflow` | 复用 crypto-strategy；历史数据口径，不能宣称实时入金 | 另行上下文检查 | ready |
| `ai-model-race` | `ai-model-race` | ok；2026-11-10T09:21:39.374992Z；36 | 200 / 2.803s | ready |
| `big-tech-market-cap` | `big-tech-market-cap` | ok；2026-11-10T09:22:26.200582Z；16 | 200 / 2.768s | stale |
| `consumer-app-pulse` | `consumer-app-pulse` | ok；2026-11-10T09:22:39.830265Z；40 | 200 / 1.369s | stale |
| `crypto-funding-watch` | `crypto-funding-watch` | /runtime/crypto/funding-watch?limit=120；200；可交易资格独立于外层快照 | 另行上下文检查 | stale |
| `defi-token-watch` | `defi-token-watch` | ok；2026-11-10T09:25:18.320584Z；10 | 200 / 1.256s | ready |
| `defi-yield-monitor` | `defi-yield-monitor` | ok；2026-11-10T09:24:48.295376Z；10 | 200 / 0.589s | stale |
| `defi-security-watch` | `defi-security-watch` | ok；2026-11-10T09:24:54.004241Z；12 | 200 / 1.669s | stale |
| `crypto-perp-funding` | `crypto-perp-funding` | 复用 crypto-strategy；缺合格合约/原始窗口时明确缺失 | 另行上下文检查 | stale |
| `tradfi-perp-radar` | `tradfi-perp-radar` | partial；2026-11-10T09:20:39.489208Z；22 | 200 / 1.491s | degraded |
| `ipo-news-watch` | `ipo-news-watch` | ok；2026-11-10T09:24:57.218663Z；12 | 200 / 0.731s | degraded |
| `broker-research-watch` | `broker-research-watch` | partial；2026-11-10T09:25:25.619777Z；12 | 200 / 0.792s | ready |
| `global-index-monitor` | `global-index-monitor` | ok；2026-11-10T09:25:40.927136Z；12 | 200 / 1.369s | degraded |
| `commodity-equity-transmission` | `commodity-equity-transmission` | ok；2026-11-10T09:26:48.316276Z；非列表 | 200 / 1.722s | degraded |
| `crypto-fear-greed` | `crypto-fear-greed` | partial；2026-11-10T09:18:10.502715Z；6 | 200 / 2.348s | degraded |
| `crypto-etf-flow` | `crypto-etf-flow` | ok；2026-11-10T09:20:39.489208Z；8 | 200 / 0.822s | stale |
| `stablecoin-monitor` | `stablecoin-monitor` | 复用 crypto-strategy；仅已有币种源与窗口 | 另行上下文检查 | stale |
| `blockchain-policy-news` | `blockchain-policy-news` | ok；2026-11-10T09:18:14.360056Z；12 | 200 / 1.078s | ready |
| `trade-policy-radar` | `trade-policy-radar` | 静态政策说明/条目；不伪称实时采集 | 另行上下文检查 | idle |
| `geo-sanctions-shock` | `geo-sanctions-shock` | ok；2026-11-10T09:24:01.405908Z；2000 | 200 / 17.558s | degraded |
| `global-transport-shipping` | `global-transport-shipping` | ok；2026-11-10T08:49:22.978175Z；14 | 200 / 7.166s | ready |
| `cpi-release-command-center` | `cpi-release-command-center` | ok；2026-11-10T09:22:44.958828Z；24 | 200 / 6.562s | ready |
| `cpi-components-pressure-registry` | `cpi-components-pressure-registry` | ok；2026-11-10T09:22:45.358236Z；25 | 200 / 2.307s | ready |
| `goods-tariff-supply-watch` | `goods-tariff-supply-watch` | ok；2026-11-10T09:22:45.773661Z；15 | 200 / 0.567s | ready |
| `labor-services-inflation-monitor` | `labor-services-inflation-monitor` | ok；2026-11-10T09:22:46.204688Z；17 | 200 / 1.863s | ready |
| `fed-reaction-growth-risk-board` | `fed-reaction-growth-risk-board` | ok；2026-11-10T09:22:46.599218Z；20 | 200 / 3.274s | ready |
| `polymarket-macro-map` | `polymarket-macro-map` | degraded；2026-11-10T09:23:49.672194Z；12 | 200 / 3.396s | 默认关闭/未挂载 |
| `cpi-release-calendar` | `cpi-release-calendar` | ok；2026-11-10T08:29:26.566073Z；8 | 200 / 3.296s | 默认关闭/未挂载 |
| `energy-gasoline-shock` | `energy-gasoline-shock` | ok；2026-11-10T06:47:53.258919Z；3 | 200 / 0.909s | 默认关闭/未挂载 |
| `global-temperature-monitor` | `global-temperature-monitor` | ok；2026-11-10T08:47:47.656739Z；50 | 200 / 33.366s | stale |
| `weather-market-browser` | `global-temperature-monitor` | ok；2026-11-10T08:47:47.656739Z；50 | 200 / 33.366s | degraded |
| `weather-city-snapshot` | `global-temperature-monitor` | ok；2026-11-10T08:47:47.656739Z；50 | 200 / 33.366s | stale |
| `weather-quote-detail` | `global-temperature-monitor` | ok；2026-11-10T08:47:47.656739Z；50 | 200 / 33.366s | stale |
| `weather-quote-table` | `global-temperature-monitor` | ok；2026-11-10T08:47:47.656739Z；50 | 200 / 33.366s | stale |
| `weather-trend-detail` | `global-temperature-monitor` | ok；2026-11-10T08:47:47.656739Z；50 | 200 / 33.366s | degraded |
| `weather-trend-7d` | `global-temperature-monitor` | ok；2026-11-10T08:47:47.656739Z；50 | 200 / 33.366s | degraded |
| `weather-news` | `weather-news` | ok；2026-11-10T09:24:15.853930Z；24 | 200 / 9.48s | degraded |
| `world-clock` | `global-temperature-monitor` | ok；2026-11-10T08:47:47.656739Z；50 | 200 / 33.366s | degraded |
| `food-retail-basket-pressure` | `food-retail-basket-pressure` | ok；2026-11-10T06:47:45.429424Z；8 | 200 / 9.034s | 默认关闭/未挂载 |
| `supply-tariff-import-watch` | `supply-tariff-import-watch` | ok；2026-11-10T06:52:58.669166Z；8 | 200 / 9.678s | 默认关闭/未挂载 |
| `shelter-rent-oer-pressure` | `shelter-rent-oer-pressure` | ok；2026-11-10T06:52:58.694847Z；7 | 200 / 5.708s | 默认关闭/未挂载 |
| `labor-wage-services-pressure` | `labor-wage-services-pressure` | ok；2026-11-10T06:52:58.702986Z；8 | 200 / 1.489s | 默认关闭/未挂载 |
| `growth-demand-recession-tracker` | `growth-demand-recession-tracker` | ok；2026-11-10T06:52:58.710500Z；8 | 200 / 6.529s | 默认关闭/未挂载 |
| `inflation-nowcast` | `inflation-nowcast` | ok；2026-11-10T09:18:05.378293Z；非列表 | 200 / 4.394s | 默认关闭/未挂载 |
| `fed-rates-polymarket-gap` | `fed-rates-polymarket-gap` | ok；2026-11-10T06:52:58.717584Z；8 | 200 / 1.815s | 默认关闭/未挂载 |
| `nba-scoreboard` | `nba-scoreboard` | ok；2026-11-10T09:25:50.307783Z；8 | 200 / 3.374s | ready |
| `nba-intel` | `nba-intel` | ok；2026-11-10T09:25:52.265004Z；6 | 200 / 1.762s | ready |
| `espn-matchup-predictor` | `espn-matchup-predictor` | ok；2026-11-10T09:25:59.279550Z；8 | 200 / 1.64s | degraded |
| `esports-intel` | `esports-intel` | ok；2026-11-10T09:26:28.273223+00:00；10 | 200 / 4.423s | ready |
| `sports-odds` | `sports-odds` | ok；2026-11-10T09:26:44.921824+00:00；8 | 200 / 11.331s | ready |
| `jin10-flash` | `jin10-flash` | ok；2026-11-10T17:25:50.035401+08:00；24 | 200 / 7.115s | ready |
| `new-market-signals` | `new-market-signals` | ok；2026-11-10T09:23:02.967339Z；12 | 200 / 2.426s | ready |
| `lob-depth` | `lob-depth` | market-data book reader；本机 7ms/200，公网仍出现 3s/504；upstreamCompleteness=UNKNOWN | 另行上下文检查 | idle |
| `f1-trackside` | `f1-trackside` | ok；2026-11-10T09:26:16.497090Z；10 | 200 / 2.227s | ready |
| `company-events` | `company-events` | ok；2026-11-10T09:10:17.891608+00:00；非列表 | 200 / 2.851s | ready |
| `policy-progress` | `policy-progress` | degraded；2026-11-10T09:25:04.685875+00:00；100 | 200 / 6.742s | degraded |
| `politics-election` | `politics-election` | ok；2026-11-10T09:20:29.825023+00:00；非列表 | 200 / 5.301s | ready |
| `politics-early-vote` | `politics-early-vote` | ok；2026-11-10T09:20:24.406292+00:00；100 | 200 / 3.316s | ready |
| `politics-nomination` | `politics-nomination` | ok；2026-11-10T08:15:24.322940+00:00；21 | 200 / 2.293s | ready |
| `politics-seats` | `politics-seats` | ok；2026-11-10T08:55:18.230992+00:00；435 | 200 / 2.669s | ready |
| `politics-campaign-finance` | `politics-campaign-finance` | degraded；2026-11-10T09:15:17.551746+00:00；200 | 200 / 5.276s | degraded |
| `politics-government` | `politics-government` | ok；2026-11-10T08:55:18.230992+00:00；435 | 200 / 3.617s | ready |
| `politics-executive` | `politics-executive` | ok；2026-11-10T09:25:05.518035+00:00；67 | 200 / 1.163s | ready |
| `politics-appointments` | `politics-appointments` | ok；2026-11-10T09:15:10.341225+00:00；30 | 200 / 3.272s | ready |
| `politics-funding` | `politics-funding` | ok；2026-11-10T09:05:16.742639+00:00；1 | 200 / 3.586s | ready |
| `geo-conflict-watch` | `geo-conflict-watch` | ok；2026-11-10T09:24:01.405908Z；17 | 200 / 1.693s | ready |
| `geo-ceasefire-watch` | `geo-ceasefire-watch` | ok；2026-11-10T09:14:37.202185+00:00；6 | 200 / 0.998s | ready |
| `geo-territory-control` | `geo-territory-control` | ok；2026-11-10T09:14:37.202185+00:00；8 | 200 / 1.617s | ready |
| `geo-diplomacy-calendar` | `geo-diplomacy-calendar` | ok；2026-11-10T09:14:37.202185+00:00；37 | 200 / 1.954s | ready |
| `geo-treaty-tracker` | `geo-treaty-tracker` | ok；2026-11-10T08:17:46.091618+00:00；非列表 | 200 / 1.359s | ready |
| `weather-precipitation` | `weather-precipitation` | ok；2026-11-10T08:47:47.656739Z；非列表 | 200 / 3.449s | ready |
| `weather-drought` | `weather-drought` | ok；2026-11-10T08:07:41.776171+00:00；非列表 | 200 / 2.591s | ready |
| `weather-extremes` | `weather-extremes` | ok；2026-11-10T09:26:14.024973Z；非列表 | 200 / 2.813s | ready |
| `weather-storm-advisory` | `weather-storm-advisory` | ok；2026-11-10T09:26:14.614314Z；非列表 | 200 / 2.768s | ready |
| `sports-spread-monitor` | `sports-spread-monitor` | ok；2026-11-10T09:25:40.188749+00:00；非列表 | 200 / 1.177s | degraded |
| `sports-total-monitor` | `sports-total-monitor` | ok；2026-11-10T09:25:40.188749+00:00；非列表 | 200 / 1.415s | degraded |
| `sports-player-props` | `sports-player-props` | ok；2026-11-10T09:25:40.188749+00:00；非列表 | 200 / 0.648s | degraded |
| `sports-tournament-path` | `sports-tournament-path` | ok；2026-11-10T09:11:31.450772+00:00；非列表 | 200 / 0.787s | degraded |
| `sports-season-race` | `sports-season-race` | ok；2026-11-10T08:28:25.674226+00:00；非列表 | 200 / 0.724s | ready |
| `sports-awards-watch` | `sports-awards-watch` | ok；2026-11-10T08:28:27.007652+00:00；非列表 | 200 / 1.742s | ready |
| `esports-map-state` | `esports-map-state` | ok；2026-11-10T09:15:20.706844+00:00；非列表 | 200 / 1.621s | ready |
| `esports-tournament-path` | `esports-tournament-path` | ok；2026-11-10T09:20:26.677183+00:00；非列表 | 200 / 2.145s | ready |
| `crypto-listing-watch` | `crypto-listing-watch` | ok；2026-11-10T09:25:45.666397+00:00；非列表 | 200 / 2.56s | ready |
| `crypto-project-milestones` | `crypto-project-milestones` | ok；2026-11-10T09:15:22.807801+00:00；非列表 | 200 / 0.635s | ready |
| `chain-metrics-monitor` | `chain-metrics-monitor` | ok；2026-11-10T09:15:21.876232+00:00；非列表 | 200 / 1.687s | ready |
| `fiscal-tax-monitor` | `fiscal-tax-monitor` | ok；2026-11-10T08:13:07.340402+00:00；非列表 | 200 / 0.607s | ready |
| `merger-progress` | `merger-progress` | ok；2026-11-10T09:00:28.034538+00:00；非列表 | 200 / 1.15s | ready |
| `private-valuation-watch` | `private-valuation-watch` | ok；2026-11-10T09:20:35.250055+00:00；非列表 | 200 / 1.363s | ready |
| `ai-leaderboard-watch` | `ai-leaderboard-watch` | ok；2026-11-10T06:09:12.466943+00:00；100 | 200 / 3.167s | ready |
| `art-auction-watch` | `art-auction-watch` | ok；2026-11-10T06:09:18.152961+00:00；22 | 200 / 3.575s | ready |
| `culture-box-office` | `culture-box-office` | ok；2026-11-10T06:09:57.534812+00:00；50 | 200 / 3.357s | ready |
| `culture-awards-race` | `culture-awards-race` | ok；2026-11-10T06:09:26.120318+00:00；10 | 200 / 1.924s | ready |
| `culture-music-charts` | `culture-music-charts` | ok；2026-11-10T09:10:29.077417+00:00；50 | 200 / 1.521s | ready |
| `product-release-watch` | `product-release-watch` | ok；2026-11-10T09:15:22.975800+00:00；40 | 200 / 1.425s | ready |
| `public-figure-events` | `public-figure-events` | ok；2026-11-10T09:20:22.297035+00:00；15 | 200 / 2.561s | ready |
| `reality-show-progress` | `reality-show-progress` | ok；2026-11-10T06:09:23.151901+00:00；13 | 200 / 2.452s | ready |
| `research-evidence-watch` | `research-evidence-watch` | ok；2026-11-10T06:09:48.673231+00:00；31 | 200 / 1.502s | ready |
| `social-window-monitor` | `social-window-monitor` | ok；2026-11-10T09:15:27.750424+00:00；11 | 200 / 1.685s | ready |
| `space-mission-watch` | `space-mission-watch` | ok；2026-11-10T09:15:17.931027+00:00；10 | 200 / 2.143s | ready |
| `mentions-evidence` | `mentions-evidence` | ok；2026-11-10T09:20:23.093755+00:00；3 | 200 / 4.429s | ready |
