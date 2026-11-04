# BLS 403：原因、替代来源与接入方案

**实施状态（2026-11-04）：**用户已选择“日常监控与公告归档”，授权替换。
现行接入契约见 [宏观数据契约](macro-panel-data-contract.md#bls-replacement-for-daily-monitoring-and-release-archives)。
下方“尚未实施”属于早先调研时点；替换实现、部署及验收分别记录在本文末尾，不能混用两次状态。

核验时间：2026-11-04 10:42—10:50，北京时间。本文是一次调研和读取验证，不代表已修改生产采集器、已完成发布窗口验收或所有来源持续健康。没有切换代理、启动隧道、订阅邮箱或购买数据服务。

**10:53—10:55 补充结论：**用户要求核对其代理影响后，有限对照证明当前终端 Clash 路径能够取得有效的 BLS 原站 RSS、日历和 API；同址直连仍 403，腾讯路径仍超时。因此应优先修复生产采集的实际出口及配置读取，不能再将“BLS 原站不可访问”作为所有网络路径的结论。下方 10:42—10:50 的结果保留为原窗口证据，详细对照见第 8 节。未更改 Clash 节点或生产服务出口。

## 结论

- 直连 BLS RSS、日程、公告页面，以及 Public API v1/v2，均收到 HTML `Access Denied`，不是有效 RSS/JSON。RSS/页面响应包含 `Server: AkamaiGHost`。可以定位到访问控制层；无法仅凭这些响应确定命中的具体规则、IP 信誉或历史请求因素。
- 当前日历 worker 的代码写死 `requests.Session().trust_env = False`，运行目录也一样。配置代理环境变量不会改变它的直连行为。这是本项目需要修正的独立实现问题；修正本身不保证 BLS 放行。
- 经既有腾讯云 SOCKS 出口进行的本轮请求在 5 秒连接预算内超时，连 FRED 对照请求也超时。不能把这些请求记成 BLS 403，也不能据此认定所有超时都由 BLS 拒绝造成。
- **日历：FRED 公共日历可以实际读取并解析，纽约联储日历可以交叉核对。**不需要为当前验证创建 API key。
- **数值：原有 FRED CSV 链路实际可读，四条 CPI 序列均取得最新已发布的 2026-09 观测。**未来月份没有数值不能当作抓取故障。
- **公告：FRASER 的 CPI、PPI、就业报告三个目录都能自动发现最新条目，取得 BLS 原始 PDF 并解析正文和原始发布日期。**可用于补齐与归档，但收录延迟不受本项目控制，不能承诺与 BLS RSS 等时到达。
- 因此，免费组合已经有“取得数据并解析所需字段”的可行证据；尚无“免费、完整、发布瞬间、长期无故障”的等价替代验收。

## 1. 当前失败和代码问题

| 路径 | 本轮实际结果 | 含义 |
| --- | --- | --- |
| `www.bls.gov/feed/{cpi,empsit,ppi}.rss` | 直连三个均 403，约 385—388 字节 HTML | 被拒绝发生在 XML 解析之前；不是合法空 feed |
| BLS CPI/就业日程 HTML | 直连两个均 403 | 无法动态核验日程 |
| BLS `schedule/news_release/bls.ics` | 直连 403 | 官方 ICS 确实存在，但本机改用 ICS 仍不能直接解除拒绝 |
| BLS `news.release/cpi.nr0.htm` | 直连 403 | 同域公告 HTML 也不是当前可用备用 |
| `api.bls.gov/publicAPI/v1/...` 与 v2 | 直连均为 403 HTML | 不能把“换成官方 API”直接写成已验证成功的方案 |
| CPI RSS 使用普通浏览器 User-Agent 字符串 | 仍为 403 | 仅更换 User-Agent 无法解决本轮问题；没有测试绕过验证码或隐蔽浏览器 |
| 上述首次探测经已授权腾讯出口 | 连接超时 | 本轮无法验证该出口对 BLS 的最终 HTTP 响应 |

BLS [公开机器人访问规则](https://www.bls.gov/bls/pss.htm)说明，过度请求及缺少可联系所有者信息的机器人可能被阻止；这只是政策背景，不证明本项目具体命中了哪条规则。RSS 本身仍由 [BLS 官方目录](https://www.bls.gov/feed/)提供，没有找到这些 feed 已停用的依据。

本项目需修正的点：

1. [日历 watcher](../scripts/runtime/cpi_release_calendar_watcher.py) 第 93 行关闭代理环境读取。应按现有共享客户端配置选择直连或用户授权出口，记录实际路由，不另起采集服务。
2. [日历服务](../scripts/api/services/cpi_release_calendar_service.py)在请求异常、拒绝页面或解析无结果时使用 `BLS_2026_FALLBACK_ROWS`。硬编码表不能跟踪改期，且年份有边界。
3. 同一服务目前只要任一来源成功，就可能将整个日历标为 `ok`。BEA/FOMC 成功不能证明 CPI/就业日历已核验；应保留逐来源及逐事件的证据状态。
4. 当前 RSS collector 只解析 RSS/Atom。接入 FRASER 需要在现有内容 owner 内增加目录/PDF 适配，不能只把 `feed_url` 替换成 HTML 或 PDF。

原站恢复措施：统一真实可联系的采集标识、域名级并发与预算；403 进入长退避并保留响应错误编号；核实授权出口后做有限对照；如持续被拒绝，可向 [BLS 联系入口](https://www.bls.gov/bls/contact.htm)提交 URL、UTC 时间、错误编号、出口和频率，请求确认。没有 BLS 的回复，不能断言某项请求头改动或注册 API key 一定能解除拒绝。本次没有联系对方。

## 2. 日历替代：已完成字段级验证

| 来源 | 实测入口与结果 | 能力边界 |
| --- | --- | --- |
| FRED | [CPI `rid=10`](https://fred.stlouisfed.org/releases/calendar?rid=10&y=2026) 12 行；[就业 `rid=50`](https://fred.stlouisfed.org/releases/calendar?rid=50&y=2026) 12 行；[PPI `rid=46`](https://fred.stlouisfed.org/releases/calendar?rid=46&y=2026) 13 行。全部 200，成功提取日期、时间、名称及 release ID | 页面时间为美国中部时间；日历行没有统计参考月份，不可无条件用“发布日期减一个月”填充 |
| 纽约联储 | [Economic Indicators Calendar](https://www.newyorkfed.org/research/calendars/nationalecon_cal) 200，找到 11 月三项事件与 08:30 时间 | 页面使用美国东部时间；只能核验日程，不能提供 BLS 公告全文 |
| ALFRED | [CPI 日历](https://alfred.stlouisfed.org/releases/calendar?rid=10&y=2026) 200，能解析同样的 CPI 日期 | 与 FRED 同属圣路易斯联储，不能算完全独立故障域 |

10:47 对 FRED CPI 与纽约联储再次请求，仍成功。属于两次读取验证，不是两轮生产调度或整夜连续验收。

下列下一次发布日期同时得到 FRED、纽约联储和 FRASER 所存 BLS 原公告正文支持：

| 数据／参考期 | 美国东部时间 | 北京时间 | UTC |
| --- | --- | --- | --- |
| 就业报告／2026-10 | 2026-11-06 08:30 | 2026-11-06 21:30 | 2026-11-06 13:30Z |
| CPI／2026-10 | 2026-11-10 08:30 | 2026-11-10 21:30 | 2026-11-10 13:30Z |
| PPI／2026-10 | 2026-11-13 08:30 | 2026-11-13 21:30 | 2026-11-13 13:30Z |

这些是本次核验时的安排，未来仍需重查改期。解析用 `America/Chicago`、`America/New_York` 与 `Asia/Shanghai`，不固定写 UTC 偏移。

FRED 的 [release/dates API](https://fred.stlouisfed.org/docs/api/fred/release_dates.html)可作为后续结构化入口，但需要 API key，并需设置 `include_release_dates_with_no_data=true` 才能包含未来安排。其返回示例只有日期，不能据此声称取得了准确小时。当前已验证的是无需 key 的公共日历页面；FRED 也明确说明发布日程不保证数据同时出现在 FRED。

## 3. 公告替代：实际发现、下载和提取结果

验证流程：公开目录 → 最新条目链接 → 条目 `citation_pdf_url` → PDF 文件签名 → `pdftotext` → 原始发布时间、报告期、公告编号和下一次发布日期。没有靠猜测文件名或搜索结果摘要充当完整公告。

| 类别 | 目录 | 已取得原件 | 原始发布日期 | PDF 字节数 |
| --- | --- | --- | --- | --- |
| CPI | [Consumer Price Index](https://fraser.stlouisfed.org/title/consumer-price-index-6838?browse=2020s) | [September 2026, USDL-26-1574](https://fraser.stlouisfed.org/title/consumer-price-index-6838/september-2026-738026) | 2026-10-14 08:30 ET | 574,292 |
| PPI | [Producer Price Indexes](https://fraser.stlouisfed.org/title/producer-price-indexes-6837?browse=2020s) | [September 2026, USDL 26-1576](https://fraser.stlouisfed.org/title/producer-price-indexes-6837/producer-price-indexes-september-2026-738025) | 2026-10-15 08:30 ET | 1,641,399 |
| 就业 | [Employment Situation](https://fraser.stlouisfed.org/title/employment-situation-144?browse=2020s) | [September 2026, USDL-26-1549](https://fraser.stlouisfed.org/title/employment-situation-144/september-2026-738053) | 2026-10-02 08:30 ET | 580,018 |

三个 PDF 均为 HTTP 200、真实 `%PDF-` 文件，正文提取成功，保留 BLS 作者、公告编号、标题、参考期及表格。CPI 目录/原件重复取得成功。它们是原公告的存档副本，不是用新闻评论或预测改写出来的“官方数据”。

必须保留的限制：

- [FRASER 收录记录](https://fraser.stlouisfed.org/news/archive)显示，2026-08 CPI 原公告于 9 月 11 日发布，新增记录列在 9 月 14 日；8 月就业报告于 9 月 4 日发布，新增记录列在 9 月 9 日。这证明不能承诺同步收录，不等于已经测得每份文件精确的首次可下载时间。
- FRASER [最新收录 RSS](https://fraser.stlouisfed.org/rss/whatsnew.php)本次可读取，但只是一个有界的最新收录列表，不能替代三个专题目录的补漏。RSS 的收录日期不能写成 BLS 原公告发布日期。
- 本次最新已发布公告的参考期为 2026-09；2026-10 尚待上述 11 月日期发布。不能因为现在没有 10 月 PDF 就标记来源失败。
- Related Intelligence 的七天新闻窗口仍须使用原始 `published_at`。今天补下载十月上旬公告，不应伪装成今天新闻，也不应为填满面板而绕过时间窗口。

## 4. 数值链路

本机直连以下正式 CSV 路径返回 `application/csv`，可解析列 `observation_date,CPIAUCNS,CPILFENS,CPIAUCSL,CPILFESL`：

`https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS,CPILFENS,CPIAUCSL,CPILFESL&cosd=2026-07-01`

最新非空观测均为 2026-09：336.940、339.287、336.298、338.896。这里只验证现有 CPI 数值链路；未以此声明所有 PPI/就业系列、首次发布 vintage 或历史完整性已验收。组合 CSV 的历史起始范围不能只信请求参数；适配器仍需检查实际返回区间、大小和每列缺口。

继续复用现有 FRED 序列拥有者。季调/非季调、指数水平/同比/环比、原始值/修订值必须分别绑定。FRED 数据可用不等于 BLS 发布那一秒已被本机接收，不能用下载时间伪造历史策略可用时间。

## 5. 未通过“现成可用”验收的其他方案

| 候选 | 实查 | 判定 |
| --- | --- | --- |
| 美国劳工部 `dol.gov/newsroom/economicdata` 及三份公告 PDF | 本机均 403 | 虽然是官方镜像，当前不能列为本机可用方案 |
| BLS GovDelivery 官方邮件 | [官方 FAQ](https://www.bls.gov/help/gov_delivery_faqs.htm)确认订阅入口；订阅页本机 200；未注册或收到邮件 | 可以作为后续快讯通道，尚未通过本项目端到端收件验收。邮件包含摘要和原件链接，不保证完整 PDF 随邮件到达 |
| GovDelivery 账户公开 RSS | 探测的 `/accounts/USDOLBLS/feed.rss` 返回 404 | 不能凭常见 URL 格式假定此账户有可用 feed |
| Trading Economics 日历 API | [官方文档](https://docs.tradingeconomics.com/economic_calendar/snapshot/)提供 Actual、Previous、Forecast、Reference、SourceURL、LastUpdate 等字段 | 需要本项目凭据、美国数据覆盖与许可验证；未验证授权响应和发布窗口延迟，不能宣称可立即替换，也不能代替 BLS 原文 |

如果要求“官方发布瞬间的快讯及交易输入”，FRASER 不满足等价替代，FRED 也没有该延迟保证。可行方向是正式恢复 BLS，或接入官方邮件/有授权的实时数据服务后，在真实发布窗口验收；当前不能把尚未验收的方向叫作完全解决。

## 6. 建议接入现有架构的方式（尚未实施）

### 日历

- 扩展既有 `cpi_release_calendar_watcher.py` 和 `cpi_release_calendar_service.py`；使用 FRED 作为当前可用日程来源，纽约联储交叉核对，BLS 恢复后作为优先原始来源。
- 原有 SQLite `snapshot:macro:cpi-release-calendar / panel-v1` 与既有 Redis 分发继续供 CPI Calendar、CPI Command 消费；不为备用来源再建 Panel、轮询器或数据库。
- 来源冲突保留双方日期和核验时间，状态为未确认；不自动选择较新或较近日期。参考期从公告或明确元数据取得，缺失保留未知。
- 硬编码 2026 日程退为有明确身份的历史证据；运行失败优先保留最后核实的日程和原始核验时间，不能更新成“刚验证”。

### 公告

- 复用现有 content worker；增加 FRASER 目录/PDF 来源适配，进入既有 `content_items`、`content_versions`、`content_discoveries` 和 `content_source_state`，继续由 `related-news` 快照供视图读取。
- 区分 `publisher=BLS`、传输提供者 `FRASER`、公告原始 URL/公告编号和镜像 URL。利用现有 `event_id` 机制以类型、公告编号/参考期去重，避免原站恢复后同一公告重复显示。
- 提取原始 `published_at`，分别记录镜像发现时间与实际接收时间；按内容版本保留修订。新增来源主机进入既有允许列表，PDF 签名、大小、解析时间与字段校验通过后才发布。
- 如需要将原件用于研究，沿内容 owner 的正式归档能力设计保留；不能把展示 SQLite 当前快照当成原始历史库。

### 周期与预算

以下是建议值，不是已修改的生产配置：

| 链路 | 建议采集节奏 | 失败行为 |
| --- | --- | --- |
| 日历 | 保留正常每小时核验；发布日前有限增加核验，按共享 owner 合并 | 原始核验时间不变；来源冲突单独标记 |
| FRASER 目录 | 平时每 6 小时；目标报告发布后待补齐期间每 30 分钟 | 目录未收录为待收录；网络失败保留旧证据 |
| PDF | 新条目或版本变化才下载 | 不因每轮检查重复下载；按公告身份去重 |
| BLS 403 恢复探测 | 单一 owner、域名级共享退避，初期每 6 小时有限探测 | 不随页面刷新反复试；恢复后再回正常发布节奏 |
| FRED CPI 数值 | 保留现有成功窗口与共享采集 | 失败保留原始数值和来源日期，不无限延长成功时间 |

每域并发 1、连接 5 秒、读取 15 秒、单轮总期限 90 秒、普通 HTML 上限 2.5 MB、PDF 上限 5 MB、PDF 解析上限 15 秒；这些建议预算足以覆盖本次三份 0.57—1.65 MB 文件，实际实现仍需整轮退出和大文件失败验证。浏览器不增加轮询频率，不从公开 GET 下载 PDF。

## 7. 完成标准

- [x] 当前拒绝层及日历代理配置缺陷有代码/实测依据。
- [x] FRED 三类日历可提取实际记录；纽约联储及 BLS 存档正文的下一次日期一致。
- [x] FRASER 三类目录可自动发现最新原件，并完成 PDF 与正文验证。
- [x] 四条既有 CPI 数值系列本次读取成功。
- [ ] 生产来源适配、正式写入与 API/Panel 消费尚未修改。
- [ ] 未完成来源失败、改期冲突、版本重复、跨年、夏令时、合法未发布等代码验证。
- [ ] 未观察两轮正式自动采集及下一次真实发布后的延迟、入库和展示。
- [ ] 未证明完全等价的发布瞬间快讯或长期连续可用性。

未来实施应先更新所属数据契约和领域索引，再改现有 owner、验证存储与消费者。不要把本报告中的成功样本当成全部 Panel 或未来来源的健康声明。

## 8. 代理影响补充核验：10:53—10:55

相同 BLS URL、相同 `Polymonitor/1.0` 请求头，仅对比请求路径：

| 请求路径 | 实际结果 |
| --- | --- |
| 关闭应用层代理环境读取的直连 | CPI feed 再次为 403，响应为 Akamai `Access Denied` |
| 既有腾讯 SOCKS | CPI feed 读取超时；FRED 对照也连接超时。放宽连接预算到 15 秒仍未成功 |
| 当前终端已配置的 Clash HTTP 入口 | CPI、就业、PPI feed 全部 200；各解析出 12 个真实 Atom entry，包含标题、链接及原生时间字段 |
| 同一 Clash 路径读取 BLS 日历 | CPI/就业 HTML 均 200，有实际参考期和发布时间，已列出 2027 年安排；ICS 为真实 VCALENDAR，313 个 VEVENT |
| 同一 Clash 路径读取 BLS Public API v1 | 200，JSON `REQUEST_SUCCEEDED`，一个真实数值序列 |
| 同一 Clash 路径读取劳工部 CPI PDF | 200，574,292 字节，真实 PDF |

Clash 控制器连接记录显示 BLS 命中 `Match` 规则，链路走当前已选的台湾家宽节点。没有更改 mode、规则、selector、节点或常驻采集配置。探测仅用于本次用户要求的网络归因，不代表生产采集已获准长期使用该实例。

实际消费者路径不同：终端环境指向当前 Clash；内容 worker 指向腾讯 SOCKS；日历 worker 因 `trust_env=False` 忽略代理变量。腾讯 SSH 命令明确设置 `ProxyCommand=none`、`ProxyJump=none`，远端连接走 Tailscale。当前 Clash `tun.enable=false`，没有配置 redir/tproxy 监听；系统路由查询显示 BLS 走普通物理网卡。未取得完整主机防火墙规则读取权限，不扩大为“系统任何层都不存在透明转发”的绝对结论。

能够确认的是网络路径决定了本轮成败：当前终端代理路径成功，直连被边缘访问控制拒绝，腾讯链路超时。不能据此断言 BLS 按某个国家或所有云 IP 统一封锁；也不能把腾讯超时解释成 BLS 返回了 403。上一窗口未测试当前 Clash，故不足以判断原站在所有现有路径下均不可达。

优先处理顺序应调整为：修正日历客户端的路由配置读取 → 为生产采集落实经过验证且符合用户出口选择的路径 → 验证真实自动采集、写入及消费者。FRED/纽约联储/FRASER 继续作为冗余与归档方案。不得因本次临时探测成功就把生产 worker 静默改到用户的主代理上。

## 9. 已实施：日常监控与公告归档替换

用户随后明确选择“日常监控与公告归档”，因此本次按该选择替换来源，未采用第 8 节的原站代理修复方向。以下为 **2026-11-04 11:24—11:27，北京时间**的部署及实测记录，持续契约以 [宏观数据契约](macro-panel-data-contract.md#bls-replacement-for-daily-monitoring-and-release-archives) 为准。

### 生效范围、存储与周期

实现提交为 `e31c1f2d`，最终运行代码为 `ef4fa0a4`，均已推送。部署从该提交的 `git archive` 导出，只安装所属的 8 个运行文件；生产目录逐文件 SHA-256 与提交一致。实际运行位置是迁移后的本机后端 `$HOME/.local/share/polymonitor/backend`，不是旧 GCP。四个既有采集/API 服务均处于 active；未新建独立调度器、修改 Clash 或恢复停用隧道。

| 数据链路 | 已生效的采集节奏 | 存储和消费 |
| --- | --- | --- |
| FRED 三类发布日历＋纽约联储交叉核验 | 每小时 | 既有 `snapshot:macro:cpi-release-calendar / panel-v1`，供 CPI Calendar 与 Command 读取 |
| FRASER 的 CPI、就业、PPI 专题及官方 PDF | 各每 6 小时 | 既有内容数据库的 `content_items`、`content_versions`、`content_discoveries`、`content_source_state`；通过既有内容 API 展示 |
| 公告正式原件 | 新内容按哈希保存，支持有条件请求 | 后端 `data/bls-release-archive/{cpi,nfp,ppi}/` 保存 PDF、提取正文、版本元数据与 `latest.json`，不受新闻展示窗口或内容库 90 天清理影响 |
| CPI 数值和 Command 汇总 | 保留 30 分钟成功缓存/汇总周期 | 既有 FRED 四条数值序列及 `snapshot:macro-registry:cpi-release-command-center / panel-v2` |

内容 worker 每 60 秒检查一次到期任务，**不等于每分钟请求 FRASER**。本次三条来源成功入库后，数据库记录下一次到期均为北京时间 **17:26:22**。未启用早期建议中的发布后 30 分钟加速，也未保留 BLS 原站 403 周期探测；采用用户选择的日常监控范围。

日历和 FRASER 的请求明确使用直连；本轮来源状态中的 `proxy_mode` 均为 `direct`。已有 FRED 数值链路沿其直连配置运行。来源冲突不自动选日期；暂时失败最多保留七天的最后核验日程，保留原始 `verifiedAt`，不使用硬编码年度日程充当核验结果。参考期取自公告正文，缺失时保持未知。

### 实际写入及消费者核验

- 日历快照生成于北京时间 **11:24:05**，FRED CPI、就业、PPI、纽约联储及三类合成日程状态均为 `ok`、错误为空。下一轮就业为 11 月 6 日、CPI 为 11 月 10 日、PPI 为 11 月 13 日，均为 08:30 ET；参考期由原件的下一次发布说明绑定为 `October 2026`。
- 三份官方 PDF 已正式归档，共 **2,795,709 字节**，逐份复核哈希、文本及版本元数据。最初接收时间为北京时间 **11:15:24—11:15:30**，公告原始发布时间仍分别为 10 月 14 日、10 月 2 日、10 月 15 日；不会改写成今日新闻。
- 三类公告于北京时间 **11:26:22**成功写入既有内容库，三条来源状态均为 `ok`、错误为空。以原 BLS 公告 URL 作为稳定身份，复用原 RSS 记录；切换过程中生成的三条重复投影已按精确身份合并，保留版本、发现记录及原件，未清空原内容库。
- 真实运行 API 的 `/runtime/macro/cpi-release-calendar?limit=12` 和 `/runtime/macro/cpi-release-command-center?limit=36` 均返回 200，业务状态为 `ok`。Command 有 **4 项前值、4 项模型预测**；10 月实际值仍未发布，`actualCount=0` 是正常业务状态。
- `/content/latest?days=30&limit=100` 返回两条不重复的 BLS 公告（CPI、PPI）；就业公告已超出 30 天。七天窗口为零条，符合原始发布时间。全体新闻仍有其他来源异常，整体 `partial` 不能当成本次三条 BLS 来源失败，也不能将三条成功扩大为全体来源正常。
- 实际日历 worker 初轮 FRED 请求超时、纽约联储接续成功。调整为项目标识请求头后，最终运行 worker 的 FRED 请求也成功；这仅是本轮结果，不据此断言对方访问控制的具体机制。

运行验收文件位于 `$HOME/.local/share/polymonitor/bls-releases/ef4fa0a41cf97c6aa2da6fecda5cc82ad738a23c/`：`receipt.json`、`acceptance-local.json`、`content-ingest-after-merge.log`、`tests.log`。原件目录的 `projection-cutover-receipt.json` 保留本次精确身份合并的原始记录。

### 验证结果与未验收边界

- 相关测试 **94 通过、1 项明确排除**，所属代码 Ruff 检查通过。覆盖日历解析、夏令时/跨年、来源冲突、原始参考期、保留核验时间、PDF 身份、原件版本、去重、重启读取与新闻时间窗。
- 排除的原有测试为 `test_public_read_uses_one_database_query_and_reuses_route_market`：固定使用 2026-09-16 的新闻，却按当前日期查询 30 天窗口，现已过期；首次运行因此失败。没有为此修改本任务以外的测试。
- `make quality` 在文档检查阶段被原有 `docs/panel-data-recovery-2026-11-04.md` 第 32、52 行的个人主目录路径拦截，未改动该文档，不能宣称全仓质量检查通过。
- **本机生产采集、正式落库、原件和运行 API 已验证；公网页面尚未通过验收。**本轮公网 API/浏览器复核及腾讯连接出现连接或读取超时，尚未取得可确认替换结果的公网 Panel 截图。未在此任务中扩大修改网络通道。
- 三类来源此次成功入库是部署时显式执行的采集。每小时/每六小时的配置及下一次到期记录已核对，**尚未连续观察完整自动周期，也未经过下一次真实统计发布窗口**。FRASER 收录存在延迟；本次不宣称发布瞬间送达、首次发布数值 vintage 或全部历史原件已经回填。
