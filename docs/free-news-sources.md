# Related Intelligence 免费信息源

本轮只使用免账号、免 API Key、无付费试用的官方 RSS / Atom / JSON。纯文字卡片，不采集媒体、调用搜索服务或 LLM。

## 现有链路与边界

- 保留 `related-news` 的注册标识、Preact、独立 panel 目录和共享面板 runtime。面板输入仅为所选市场及 ID；面板自行并行请求已有 `/content/market/{id}`，首页与 dossier 共用同一关联服务。
- 原库已有 RSS、Google News、Tavily、研究摘要等 723 条历史记录，缺少本轮可核验的展示许可；不删除，服务端公开允许名单隔离。旧 bootstrap/workspace 缓存同样过滤。
- 复用 `content_items` / `content_links`、ServiceRuntime 数据库连接、requests、SQLite/PostgreSQL 和既有 `polydata-content-topic-refresh.service`。不新增 cron 或 scheduler。
- 采集器首次运行通过现有 schema 初始化追加 `content_source_state`、`content_versions`、`content_discoveries` 与 provider/time 索引；原表字段复用，额外出处、许可、时间、版本保存在 raw_payload。
- USGS/NWS 正常采集只读 `snapshot:world:natural-hazards` 中的现有快照，不重复联网；`--probe` 才直接请求种子接口验证技术状态。地图快照是有边界的来源子集，不代表完整上游或历史覆盖。

FRASER 三源仍每六小时检查目录及最新条目。对相同条目、相同 PDF URL 且本地 PDF 哈希和正文文件完整的归档，24 小时内复用原件；独立 `pdf_checked_at` / `pdf_http` 写入现有 `content_source_state`，复用不会推进这个 PDF 核验时钟或原 `receivedAt`。每日继续请求原 URL 检查修订；服务器未提供 ETag/Last-Modified 时用响应哈希识别原件，内容相同则不重复提取正文。新条目、归档损坏、显式 force/probe 均会重新取得 PDF。域名互斥等待不扣减其后的 45 秒 I/O 预算，既有内容进程的 90 秒整轮硬预算继续生效。

独立的 Breaking Event Radar 继续由现有五分钟 watcher 与 `snapshot:evidence:breaking-event-radar / panel-v1` 提供数据；HTTP Session 使用共享 SourceSession 读取已配置路由，GDELT 的 `state:content / gdelt-backoff` 持久退避保持不变。Wikimedia 仅请求已结束 UTC 日，保留 `sourceDay` 和获取时间；缺失 observations 是错误，不能转成零访问量。所有来源失败而仅沿用旧主题时，不推进 seed 的成功时间或快照 `generatedAt`，用 `lastAttemptAt` 记录本轮尝试并标记 `stale`；主题轮转仍继续。

2026-11-06 只读核验：三份生产 BLS 原件与归档哈希一致、正文存在；两个指定出口的三个 FRASER 目录请求均读超时，直连 CPI 连接超时，Wikimedia 的本机请求也读超时。缓存与失败处理的回归测试不代表这些生产连接已恢复，仍需有效内容请求、正式入库和 API 消费证据。

## 来源登记

配置文件：`scripts/runtime/free_news_sources.json`。每源分别记录技术探测、保存字段、标题/摘要展示、许可依据、署名、限制及核验时间。以下地址均为官方；所有源免账号、免 Key。

|source_id / 用途|具体入口|官方目录|展示政策 / 限制|
|---|---|---|---|
|global-voices / news_report|[feed](https://globalvoices.org/feed/)|[目录](https://globalvoices.org/feeds/)|[政策](https://globalvoices.org/about/global-voices-attribution-policy/)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|bls-cpi / official_release|[FRASER 原件目录](https://fraser.stlouisfed.org/title/consumer-price-index-6838?browse=2020s)|[BLS 目录](https://www.bls.gov/feed/)|[政策](https://www.bls.gov/bls/linksite.htm)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|bls-empsit / official_release|[FRASER 原件目录](https://fraser.stlouisfed.org/title/employment-situation-144?browse=2020s)|[BLS 目录](https://www.bls.gov/feed/)|[政策](https://www.bls.gov/bls/linksite.htm)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|bls-ppi / official_release|[FRASER 原件目录](https://fraser.stlouisfed.org/title/producer-price-indexes-6837?browse=2020s)|[BLS 目录](https://www.bls.gov/feed/)|[政策](https://www.bls.gov/bls/linksite.htm)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|fed-monetary / official_release|[feed](https://www.federalreserve.gov/feeds/press_monetary.xml)|[目录](https://www.federalreserve.gov/feeds/feeds.htm)|[政策](https://www.federalreserve.gov/disclaimer.htm)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|fed-all / official_release|[feed](https://www.federalreserve.gov/feeds/press_all.xml)|[目录](https://www.federalreserve.gov/feeds/feeds.htm)|[政策](https://www.federalreserve.gov/disclaimer.htm)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|ecb-press / official_release|[feed](https://www.ecb.europa.eu/rss/press.html)|[目录](https://www.ecb.europa.eu/home/html/rss.en.html)|[政策](https://www.ecb.europa.eu/services/using-our-site/disclaimer/html/index.en.html)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|nasa-release / official_release|[feed](https://www.nasa.gov/news-release/feed/)|[目录](https://www.nasa.gov/rss-feeds/)|[政策](https://www.nasa.gov/nasa-brand-center/images-and-media/)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|nhc-at / official_release|[feed](https://www.nhc.noaa.gov/index-at.xml)|[目录](https://www.nhc.noaa.gov/aboutrss.shtml)|[政策](https://www.weather.gov/disclaimer)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|nhc-ep / official_release|[feed](https://www.nhc.noaa.gov/index-ep.xml)|[目录](https://www.nhc.noaa.gov/aboutrss.shtml)|[政策](https://www.weather.gov/disclaimer)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|usgs / observation|[feed](https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson)|[目录](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php)|[政策](https://www.usgs.gov/information-policies-and-instructions/copyrights-and-credits)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|nws / alert|[feed](https://api.weather.gov/alerts/active)|[目录](https://www.weather.gov/documentation/services-web-api)|[政策](https://www.weather.gov/disclaimer)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|

Global Voices 必须具备作者和文章自身的 CC BY 3.0 许可区域；有限补取 approved host 上的许可元数据，不抓正文作为摘要。伙伴转载和特殊权利声明隔离。ECB 仅机构 `/press/pr/date/` 新闻稿；NASA 仅 `/news-release/`；BLS/Fed 为对应机构官方文字。NWS 保留原始 severity，仅有效 Actual 警报可公开；USGS 标为观测与“数据整理”。

## 可执行入口

使用现有 `.config/polydata/polydata.env` 的数据库配置和项目 Python 环境；没有新闻或模型 Key 仍能运行。正常的 GCP unit 已加载该环境。手动命令也须先加载同一受管环境，不将凭据写入仓库。

```bash
python scripts/runtime/content_topic_refresh.py --probe
python scripts/runtime/content_topic_refresh.py --force
python scripts/runtime/content_topic_refresh.py --status
python scripts/runtime/content_topic_refresh.py --watch --interval 60
# 单源诊断
python scripts/runtime/content_topic_refresh.py --force --sources global-voices,nhc-ep
# GCP：只管理原有内容 worker
systemctl --user restart polydata-content-topic-refresh.service
journalctl --user -u polydata-content-topic-refresh.service -n 50 --no-pager
```

停用某源：将配置 enabled 改为 false；公开读取立即拒绝该源，重启内容 worker 后停止采集。整体停用使用原 unit 的 stop。添加来源必须先真实探测官方地址、核验展示政策、声明允许 host 和字段权限，补充解析/隔离测试，再启用。

## 标准化、保存与 HTTP

- UTC；缺失发布时间为 null，不借 fetched_at 补齐。first_seen 不因更新改变；版本保存独立首次获取时间。RSS 摘要纯文本截取，HTML 引用块和脚本隔离；无摘要不补写。
- URL 去除已知跟踪参数，保留业务 query。publisher + canonical URL 确定跨 feed 身份；NHC 用风暴 ID + 官方公告产品（忽略 refresh URL 中的变化时间戳）、USGS/NWS 用现有稳定事件 ID。变化记录版本，发现入口独立记录；标题相似不合并。
- 最多 3 并发、连接/读取 6/18 秒、2.5MB 上限、最多 3 次重定向；每跳检查批准 host、HTTPS、公开 IP、无 credentials/其他端口。禁止 XML DTD/实体。
- ETag/Last-Modified 与 304；429 Retry-After、5xx/超时/XML 错误退避；尊重 Cache-Control max-age。单源失败不终止整轮。共享文件锁和 PostgreSQL advisory lock 防止同机/跨主机重复 worker。
- 90 天 / 20,000 条 / 每条 12 版本为可配置上限，仅清理本 worker 的记录；不保存完整响应、不动旧历史。

## 关联及 API

- `/content/latest?limit=20&days=7`；`/content/market/{id}?limit=20&days=7`。days 只允许 7 或显式 30 天。保持原 items、marketId、contentType 字段，添加 scope、market_id、count、window、来源状态、最近成功检查时间和 empty_reason。
- 读取只投影共享候选 seed；冷读复用 provider/time 索引，每个 publisher 有界读取最多 2,048 条原始记录，先过滤许可、过期、异常和低震级，再保留最多 512 条合格候选进行确定性关联。返回候选总数、截断和过滤原因；不是每市场采集，配额溢出明确 partial，不能声称全面召回。
- 明确拒绝不同年份/所属月份、CPI/PPI、headline/core、同比/环比和货币/统计辖区冲突。普通词 economy/AI/weather 或公司名独自不能匹配。
- direct 仅在国家/统计辖区、具体指标、所属月年和测量口径均正向建立时输出；其余特定实体/事件为 context 并说明未确定条件。风暴需 ID、年份、海盆；观测需地点证据。观察窗口不完整时绝不写成已满足结算。direct 不表示 YES、支持买卖或因果。
- Market 无匹配时 items=[]；异常返回同市场 unavailable，无全局回填。面板 AbortController + 请求代次 + 响应 ID 校验防串市场；同 key 才可保留旧列表。

## 面板行为

Market / Global 为显式选择，市场标题可见；首次打开明确默认 Global Updates，即使已选市场；之后记住用户手动选择。Market 无专门的已核验来源时显示 NO COVERAGE 和查看全局入口，健康无匹配显示 NO MATCH，真实源失败显示具体来源缺失说明，内部状态保留 PARTIAL；首页不显示通用 PARTIAL 徽标；不自动回填全局内容。全部 / 报道 / 公告 / 事件区分来源性质。默认过去 7 天，30 天标为历史。作者、来源、发布时间或未知、允许摘要、原文、安全新标签、许可入口和市场关联原因可见；纯文本，展开仅显示允许的 feed 节选/数据整理，不冒充全文。移除 could → CAUTION。

30 秒检查同源 API；摘要与面板共享资源 owner，不重复请求。新内容显示待接受数量；当前页全部滚动换新时立即显示已核验新页，避免空白。默认全局按 publisher 轮转，每个 NHC/NWS/USGS 最多 4 条且小于 4.5 的地震不进入列表。来源数、显示文章数和匹配数分开。来源状态可展开，保留失败/过期/未请求信息。

## 真实探测与入库验收（UTC）

2026-10-01 的初次种子探测均 HTTP 200，真实返回 RSS/Atom/GeoJSON 可解析，最终 URL 与种子相同。下表 parsed 是上游探测数，非公开文章数。许可不等于能访问；公开数必须经过逐项过滤。

|source_id|探测 UTC|HTTP|解析条数|
|---|---|---:|---:|
|global-voices|2026-10-01T02:37:38.686544+00:00|200|15|
|bls-cpi|2026-10-01T02:37:38.689135+00:00|200|12|
|bls-empsit|2026-10-01T02:37:38.690926+00:00|200|12|
|bls-ppi|2026-10-01T02:37:38.692382+00:00|200|12|
|fed-monetary|2026-10-01T02:37:39.381805+00:00|200|15|
|fed-all|2026-10-01T02:37:39.387461+00:00|200|20|
|ecb-press|2026-10-01T02:37:39.423026+00:00|200|15|
|nasa-release|2026-10-01T02:37:40.073673+00:00|200|10|
|nhc-at|2026-10-01T02:37:40.092618+00:00|200|2|
|nhc-ep|2026-10-01T02:37:40.538226+00:00|200|13|
|usgs|2026-10-01T02:37:40.856002+00:00|200|234|
|nws|2026-10-01T02:37:40.960302+00:00|200|293|

采集每轮输出配置 source_id、final_url、checked_at、HTTP、parsed_count、new/updated/duplicate/excluded/public、last_success_at、error；`--status` 提供持久化最近状态。计数是该轮分母，304 不将缓存总量当成本轮新增。正式 API 另按时间、许可、过期、震级、scope 过滤，数量不同正常。

本地首次 USGS/NWS 快照缺失记录为 error，不另抓一次假装复用成功；GCP 已实测两份快照持续更新，生产验收在部署后核对。Global Voices 补许可每轮上限 5 篇，未核验者隔离后续重试，不伪造作者或授权。


首次真实入库（重复入口合并，按主 source_id 计；尚未按 7/30 天和震级过滤）：

|source_id|已落库|许可允许|隔离|
|---|---:|---:|---:|
|bls-empsit|12|12|0|
|bls-cpi|12|12|0|
|bls-ppi|12|12|0|
|fed-monetary|15|15|0|
|fed-all|16|16|0|
|global-voices|15|5|10|
|nasa-release|10|3|7|
|ecb-press|15|6|9|
|nhc-at|2|2|0|
|nhc-ep|13|13|0|

2026-10-01T03:11Z 已重新实测 BLS 三源，各 HTTP 200、解析 12、更新 12、公开许可允许 12；修正 Python 3.10 对 Atom 任意小数秒的解析以及 BLS Atom content 摘要。真实日期仍是原发布月，默认 7 天不塞入旧统计发布。

本地预检：内容及原关联测试 23 项、加上 registry/release 共 39 项，另有 10 项 runtime snapshot 检查通过；5 项浏览器交互测试通过。Node 22.23.3 构建、类型、i18n 和 panel 边界通过。生产部署身份和真实桌面/移动页面以最终验收回报为准，本节不把本地成功称作部署完成。

GCP 完整采集轮（2026-10-01T03:50:59Z–03:51:19Z，所有错误为 null）：10 个 RSS/Atom 的最终地址均为上表配置地址，HTTP 200；USGS/NWS 复用实际快照，HTTP 不适用，快照成功时间分别为 03:50:19Z / 03:50:20Z。解析数包含后续隔离条目；重复数与排除数可重叠，公开数是本轮许可允许数，尚未按默认窗口和震级筛选。

|source_id|检查/成功 UTC|解析|新增|更新|重复|排除|本轮许可允许|
|---|---|---:|---:|---:|---:|---:|---:|
|global-voices|03:50:59|15|0|0|15|1|14|
|bls-cpi|03:50:59|12|0|0|12|0|12|
|bls-empsit|03:50:59|12|0|0|12|0|12|
|bls-ppi|03:51:04|12|0|0|12|0|12|
|fed-monetary|03:51:06|15|0|0|15|0|15|
|fed-all|03:51:07|20|0|0|20|0|20|
|ecb-press|03:51:09|15|0|0|15|9|6|
|nasa-release|03:51:10|10|0|0|10|7|3|
|nhc-at|03:51:13|2|0|1|1|0|2|
|nhc-ep|03:51:15|11|0|0|11|0|11|
|usgs|03:51:17 / 03:50:19|320|0|1|319|0|320|
|nws|03:51:19 / 03:50:20|141|3|0|138|3|138|

04:07 UTC 数据库快照：本轮来源 612 个去重身份，574 个满足当时许可/有效期条件；既有 723 条历史记录保留。7 天全局 API 显示 20 条；真实市场 1600659 在显式 30 天范围内返回 2 条 Fed 背景关联，16834828 返回 0 条、no_market_match。22 条 API 返回记录的标题、时间、原文链接和版本逐条与数据库一致。这些是该时刻的实测数量，常驻采集会继续变化，不是覆盖所有新闻的证明。

## 测试与限制

自动化测试使用隔离 SQLite/显式浏览器 fixtures，不写真实内容表。覆盖 RSS/Atom、纯文本/实体防护、去重/版本/first_seen、许可/旧内容隔离、304/429/失败/合法空、指标月年口径/辖区冲突、过期警报、快照复用、高频限额、无全局回填、A→B/错误 ID、署名许可/展开、新内容提示。正式验收只使用真实数据库、真实 API 与 https://polymonitor.club，不替换 API/地图瓦片。

这些源以国际报道、宏观官方发布、航天新闻稿、热带气旋、地震和美国天气警报为主；不声称覆盖全部政治/体育/Crypto 新闻。不做全文阅读、自动翻译、AI 摘要、行情因果、交易建议或自动结算。月度无新增是正常状态；一日快照不代表全历史。

## 发布范围

现有 GCP 发布入口支持显式 `DEPLOY_VERIFY_SCOPE=related-intelligence`，验证 health、真实免费内容、来源许可/署名、计数及最近成功检查时间，仍保留冲突检测、失败回滚和目标 unit 的 active 检查。默认范围继续检查交易、Whale Tracker 和 Flow Watch。资讯 API GET 仅本地读取，不再触发 Telegram 发送。

首轮发布默认全站验收失败并自动回滚：ClickHouse OrderFilled 不可用，最近交易 500，Whale Tracker/Flow Watch 过期。相关问题不作为资讯验收通过，也不修改无关交易模块。最终资讯范围部署及真实页面状态见交付验收。

NHC feed 的 summary/full advisory 同 URL 只保留更完整的 feed 节选；同一风暴产品跨公告更新保存版本，数据库 URL 同步原文最新地址。初轮本任务形成的旧 URL 身份保留历史、按未核验事件身份隔离。Dossier 同样提供 7/30 天显式范围、来源优先于内部 provider、作者、许可入口、节选与关联原因。

生产发现跨地区数据库逐条写入事件的往返耗时过长；已复用原数据库封装的批量查询/写入，保留同一事务、内容身份、版本及发现入口。304 本轮 parsed/new/public 为 0，不沿用上一轮计数；最近实际入库计数另保留 last_ingest_counts / last_ingested_at。

公开资讯冷读合并来源状态与索引候选为一次数据库查询；市场关联只读取 markets 中的原始问题/规则字段，复用路由已经读取的市场，不依赖价格、交易、Oracle 或结算 join。

## Related Intelligence 的资源与缓存契约

面板目录负责视图、`model.ts` 的响应校验及阅读状态、`useIntelFeed.ts` 的取数契约。市场 ID、market/global 范围和 7/30 天组成资源身份；切换时释放旧订阅，只有旧资源没有其他消费者时才取消请求和重试。参数化端点以 `batch:false` 接入现有共享 Runtime，30 秒检查一次，页面隐藏时暂停，失败保留同资源的已核验列表并支持手动重试。共享 Runtime 增加通用退避、Retry-After 和资源释放能力，其他面板仍保留原取数路径。

现有 `content_topic_refresh.py` 在采集前、中、后预热最近 30 天、每个 publisher 最多 512 条合格候选的 seed（原始扫描上限 2,048；先过滤再应用候选配额）（`snapshot:content:free-public` / `candidates-v4`），同时保存 `seed-meta:content` / `related-news` 的成功时间、失败原因及来源状态。复用既有 Redis 和 SQLite；有效期 90 秒，超过有效期但年龄不超过 300 秒可显式标记 stale 返回，超过 300 秒必须重新读取数据库。worker 每轮休眠 30–60 秒，完整周期还包含有 90 秒上限的采集耗时；采集中每 30 秒发布 seed。各来源仍按自身调度与退避采集，不新增 collector，不在 API GET 中抓取外部源。

API 优先读新鲜或 300 秒内的有界较旧 SQLite seed，本地无可用快照时才尝试可选 Redis，冷缓存使用现有跨进程锁合并候选查询。市场/时间范围投影不缓存，每次读取按当前契约、时间窗口、来源许可、警报有效期重新过滤。`generatedAt` 是候选列表核验时间，`lastSuccessfulCheckAt` 是来源最近成功时间；来源超期或失败保留 partial/unavailable，不因缓存命中变成 ready。

新条目等待读者点击查看；已显示条目的修订、撤回、过期和来源健康立即生效。显式选择全局后，后台市场更新不改变这个选择；切回市场模式时使用当前市场 ID。浏览器按真实 expiry 到期移除警报。响应身份、卡片结构、日期及公开链接在渲染前校验，局部错误边界隔离渲染异常。专属样式由目录内的 `styles.css` 维护，滚动区域避开工作区缩放手柄的点击范围。来源内容与覆盖面仍受前述限制，合法空结果不回填全局新闻。

Dossier 请求失败保留同市场 unavailable 状态，页面不再将超时标成无匹配；首页和 dossier 的共同 API reader 校验响应市场 ID/作用范围，拒绝错误市场的数据。

## 2026-10-01 架构整改

共享资源、缓存晋升、Retry-After、可见性和阅读状态见 `docs/panel-resource-contract.md`。原 worker 内的采集执行增加 90 秒可终止进程边界；父进程在采集前、中、后发布 seed，慢来源不阻止其余已核验资讯展示。单条来源状态 JSON 错误被隔离。seed-meta 已接入统一健康列表，contentSync 检查实际 seed 年龄和状态。HTTP 的连接/读取超时仍为 6/18 秒上限，且与许可补取共用 45 秒源预算。当前查询优先读取本地新鲜或有界较旧 SQLite seed，本地不可用时再降级 Redis/数据库；保留 90 秒新鲜、300 秒有界回放。

RSS 实体检查只检查 XML 标记，不把 CDATA/注释内的 HTML DOCTYPE 当成 XML 声明；真实 DTD/ENTITY 仍拒绝。来源上轮解析或写入失败时，重试不发送旧 ETag/Last-Modified，必须重新验证响应体后才能恢复。

## 2026-10-02 空白恢复修复

浏览器的 5 分钟新鲜响应门槛与 30 分钟最大故障回放期分开：仅此面板 opt-in `staleAgeMs`，较旧内容明确标记 STALE 并保留原始快照时间，30 分钟后移除。警报按原 expiry 移除，不延长许可或条目时间。新鲜有效的 PARTIAL 结果可以更新已有 READY 缓存，避免来源部分失败时缓存永久停留在旧版本。未知数据数量显示 — 而非 0；实际请求错误即使没有列表也可见。

watch 父进程启动时完成 schema 初始化，周期子进程不再重复执行 ALTER TABLE，避免与父进程 seed 查询争夺表锁；独立 collector 默认仍初始化。SQLite 有界回放不先等待 Redis，300 秒上限保持不变。

## 来源连接与失败恢复

部署使用既有 `POLYMONITOR_SOURCE_ROUTES_FILE`，示例见
`deploy/systemd/polymonitor-source-routes.example.json`。Global Voices 的 feed 和文章许可检查
共用用户指定的 Rabisu 独立接口 `http://127.0.0.1:17890`；ECB 明确直连。
该配置复用已部署的 `source_session` 路由能力。Rabisu 接口由现有
`polydata-clob-profile12-proxy.service` 提供；内容 worker 不管理代理进程或主 Clash。
FRASER 使用同一 Rabisu 接口优先、直连备用；未配置 host route 的安装仍默认直连，
不继承 worker 的默认代理。来源状态用 `configured-routes` 区分显式路由策略与纯直连，
该字段不声称每个目录/PDF 请求走了同一出口。
Fed、NASA、NHC 保留既有路径；USGS/NWS 继续只复用地图快照。
灾害 owner 的 `earthquake.usgs.gov` 与 `api.weather.gov` 路由也使用
`["http://127.0.0.1:17890", ""]`，在既有 `POLYMONITOR_SOURCE_ROUTES_FILE` 中配置。
长期 HTTP session 只在创建时读取该文件，因此配置后重启既有
`polymonitor-backend-natural-hazards-seed.service`；不在新闻 worker 内另抓这两路数据。
地图提供者的 60 秒快照时效、独立失败退避、来源覆盖和事件时间保持不变。

正常采集时钟不变：Global Voices/ECB 每 15 分钟，FRASER 三类各每 6 小时。
非限流失败的恢复时钟独立为 60、120、240、480、960、1920、3600 秒，之后上限 1 小时；
`Retry-After` 可以延长等待。HTTP 429 至少等待正常来源周期及服务器指定时间，
`--force` 也不能跳过限流。90 秒整轮超时使用相同恢复时钟并累计失败次数。
成功解析与入库后清零失败计数，回到正常周期；失败不会推进 `last_success_at`。

复用原内容 owner、三线程采集、45 秒源预算、90 秒整轮预算、既有正式内容表及
`snapshot:content:free-public / candidates-v4`，不新增采集器或公共 GET 外部请求。
BLS PDF、正文和版本继续保存在既有 `data/bls-release-archive/{cpi,nfp,ppi}`；
FRASER 收录时间不能代替原公告发布时间。连接恢复不代表 FRASER 与原站实时同步，
也不代表候选配额截断或其他来源异常消失。

### 2026-11-06 来源恢复验收

以下为北京时间 10:13—10:23 的运行证据，不代表未来持续健康。
代码提交 `052edaf2`、`6e67694a`、`69acc516` 已推送；本机现有后端安装了本任务的
collector 恢复时钟、worker 超时退避和 FRASER 路由状态修改，并更新上述 host routes。
安装前核对原文件哈希，保留既有未提交的共享路由代码；这不是整个脏工作树的发布。

| 来源 | 正式采集/存储结果 |
| --- | --- |
| Global Voices | 10:13:22 经 Rabisu 解析 15 条、公开合格 15 条；新增 1 条、去重 14 条，错误清零。新文章的原始发布时间为 09:38:56，已进入 `/content/latest`。 |
| ECB | 10:13:35 直连解析 14 条；6 条符合公开政策，其余 8 条按原规则隔离，错误清零。 |
| BLS CPI、就业、PPI | 10:13 的直连采集仍超时，恢复时钟将下次检查安排到 10:15；常驻 worker 于 10:16:09 自动重试成功，三份 PDF 完成验证，各复用 1 条既有正式记录，失败计数清零；下一次正常到期 16:16:09。 |
| USGS / NWS | 核验中原路径连续失败造成共享快照过期；更新原灾害 owner 出口后，10:19—10:22 多轮快照时间继续推进。10:22:23 USGS 346 事件、10:22:34 NWS 42 事件；新闻只读取共享快照。 |
| Fed 两路、NASA、NHC 两路 | 保留原路径；成功检查或内容未变，未因新闻修复新增采集 owner。 |

本机 API 在 `2026-11-06T02:22:50.560458Z` 的快照中，12 路均为 `ok` 或 `unchanged`，
`error=null`、`stale=false`。总体 `partial` 来自 `coverage.truncated=true`，不隐藏候选配额限制。
三份归档 PDF 的 SHA-256 与既有元数据一致；公告仍是 2026 年 9 月参考期，
原发布时间分别为 10 月 14 日、10 月 2 日、10 月 15 日，不能作为今日新公告。

公网 `/wm-api/content/latest` 曾读取到 10:19:38 的真实快照，确认 Global Voices、ECB、BLS
恢复结果已到公开接口；该时点新闻尚未读入刚恢复的 USGS 快照。随后公网 TLS/页面加载
间歇超时，因此最终 12 路健康状态的证据来自运行后端，桌面/移动页面暂未完成验收。
未修改或重新发布前端。PolySignal 仍为 `inactive` / `disabled`。

验证：内容/worker 测试 62 通过；FRASER 回归 10 通过；路由及既有地图相关后端回归
72 通过。干净提交导出的内容/worker/归档预检 70 通过，排除 1 项既有固定日期已过期的
测试；后续 FRASER 修改另在干净导出中 10 通过。连接预算测试使用独立临时目录，
避免与真实 worker 的 permits 竞争。干净导出的前端 production build、边界及 map bundle
检查通过；仅修改后端连接配置，未运行前端地图交互/视觉回归。临时导出均已清理。
Global Voices/ECB 的下一完整 15 分钟自动周期、BLS 的下一完整 6 小时周期及真实新公告
发布窗口尚未观察，不能把本次恢复核验写成长期连续性保证。
