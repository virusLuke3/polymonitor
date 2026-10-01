# Related Intelligence 免费信息源

本轮只使用免账号、免 API Key、无付费试用的官方 RSS / Atom / JSON。纯文字卡片，不采集媒体、调用搜索服务或 LLM。

## 现有链路与边界

- 保留 `related-news` 的注册标识、Preact、独立 panel 目录和共享面板 runtime。面板输入仅为所选市场及 ID；面板自行并行请求已有 `/content/market/{id}`，首页与 dossier 共用同一关联服务。
- 原库已有 RSS、Google News、Tavily、研究摘要等 723 条历史记录，缺少本轮可核验的展示许可；不删除，服务端公开允许名单隔离。旧 bootstrap/workspace 缓存同样过滤。
- 复用 `content_items` / `content_links`、ServiceRuntime 数据库连接、requests、SQLite/PostgreSQL 和既有 `polydata-content-topic-refresh.service`。不新增 cron 或 scheduler。
- 采集器首次运行通过现有 schema 初始化追加 `content_source_state`、`content_versions`、`content_discoveries` 与 provider/time 索引；原表字段复用，额外出处、许可、时间、版本保存在 raw_payload。
- USGS/NWS 正常采集只读 `snapshot:world:natural-hazards` 中的现有快照，不重复联网；`--probe` 才直接请求种子接口验证技术状态。地图快照是有边界的来源子集，不代表完整上游或历史覆盖。

## 来源登记

配置文件：`scripts/runtime/free_news_sources.json`。每源分别记录技术探测、保存字段、标题/摘要展示、许可依据、署名、限制及核验时间。以下地址均为官方；所有源免账号、免 Key。

|source_id / 用途|具体入口|官方目录|展示政策 / 限制|
|---|---|---|---|
|global-voices / news_report|[feed](https://globalvoices.org/feed/)|[目录](https://globalvoices.org/feeds/)|[政策](https://globalvoices.org/about/global-voices-attribution-policy/)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|bls-cpi / official_release|[feed](https://www.bls.gov/feed/cpi.rss)|[目录](https://www.bls.gov/feed/)|[政策](https://www.bls.gov/bls/linksite.htm)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|bls-empsit / official_release|[feed](https://www.bls.gov/feed/empsit.rss)|[目录](https://www.bls.gov/feed/)|[政策](https://www.bls.gov/bls/linksite.htm)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
|bls-ppi / official_release|[feed](https://www.bls.gov/feed/ppi.rss)|[目录](https://www.bls.gov/feed/)|[政策](https://www.bls.gov/bls/linksite.htm)；text-only；no-media；no-logo；no-endorsement；exclude-special-rights|
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
- 读取仅本地数据库，复用 provider/time 索引召回最近候选，上限 2,000，再确定性关联；不是每市场采集。候选有上限，不能声称全面召回。
- 明确拒绝不同年份/所属月份、CPI/PPI、headline/core、同比/环比和货币/统计辖区冲突。普通词 economy/AI/weather 或公司名独自不能匹配。
- direct 仅在具体指标、所属月年和测量口径均建立时输出；其余特定实体/事件为 context 并说明未确定条件。风暴需 ID、年份、海盆；观测需地点证据。观察窗口不完整时绝不写成已满足结算。direct 不表示 YES、支持买卖或因果。
- Market 无匹配时 items=[]；异常返回同市场 unavailable，无全局回填。面板 AbortController + 请求代次 + 响应 ID 校验防串市场；同 key 才可保留旧列表。

## 面板行为

Market / Global 为显式选择，市场标题可见；未选市场可默认 Global Updates。全部 / 报道 / 公告 / 事件区分来源性质。默认过去 7 天，30 天标为历史。作者、来源、发布时间或未知、允许摘要、原文、安全新标签、许可入口和市场关联原因可见；纯文本，展开仅显示允许的 feed 节选/数据整理，不冒充全文。移除 could → CAUTION。

30 秒轮询本地 API；列表有变化时提示“有新内容”，点击后更新。默认全局按 publisher 轮转，每个 NHC/NWS/USGS 最多 4 条且小于 4.5 的地震不进入列表。来源数、显示文章数和匹配数分开。来源状态可展开，保留失败/过期/未请求信息。

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

本地预检：后端内容测试 19 项、相关 runtime/release 检查共 43 项（最后增加 Atom 回归后内容 19 项）；3 项浏览器交互测试通过；Node 22.23.3 构建、类型、i18n 和 panel 边界通过。生产部署身份和真实桌面/移动页面以最终验收回报为准，本节不把本地成功称作部署完成。

## 测试与限制

自动化测试使用隔离 SQLite/显式浏览器 fixtures，不写真实内容表。覆盖 RSS/Atom、纯文本/实体防护、去重/版本/first_seen、许可/旧内容隔离、304/429/失败/合法空、指标月年口径/辖区冲突、过期警报、快照复用、高频限额、无全局回填、A→B/错误 ID、署名许可/展开、新内容提示。正式验收只使用真实数据库、真实 API 与 https://polymonitor.club，不替换 API/地图瓦片。

这些源以国际报道、宏观官方发布、航天新闻稿、热带气旋、地震和美国天气警报为主；不声称覆盖全部政治/体育/Crypto 新闻。不做全文阅读、自动翻译、AI 摘要、行情因果、交易建议或自动结算。月度无新增是正常状态；一日快照不代表全历史。

## 发布范围

现有 GCP 发布入口支持显式 `DEPLOY_VERIFY_SCOPE=related-intelligence`，验证 health、真实免费内容、来源许可/署名、计数及最近成功检查时间，仍保留冲突检测、失败回滚和目标 unit 的 active 检查。默认范围继续检查交易、Whale Tracker 和 Flow Watch。资讯 API GET 仅本地读取，不再触发 Telegram 发送。

首轮发布默认全站验收失败并自动回滚：ClickHouse OrderFilled 不可用，最近交易 500，Whale Tracker/Flow Watch 过期。相关问题不作为资讯验收通过，也不修改无关交易模块。最终资讯范围部署及真实页面状态见交付验收。

NHC feed 的 summary/full advisory 同 URL 只保留更完整的 feed 节选；同一风暴产品跨公告更新保存版本，数据库 URL 同步原文最新地址。初轮本任务形成的旧 URL 身份保留历史、按未核验事件身份隔离。Dossier 同样提供 7/30 天显式范围、来源优先于内部 provider、作者、许可入口、节选与关联原因。

生产发现跨地区数据库逐条写入事件的往返耗时过长；已复用原数据库封装的批量查询/写入，保留同一事务、内容身份、版本及发现入口。304 本轮 parsed/new/public 为 0，不沿用上一轮计数；最近实际入库计数另保留 last_ingest_counts / last_ingested_at。
