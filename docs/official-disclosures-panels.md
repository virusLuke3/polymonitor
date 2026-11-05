# 公司财报与公告 / 政策进程

本轮仅交付这两个独立 Panel。入口是原工作台，默认启用并复用旧布局合并机制。

## 数据获取先于视图

候选来源包是调研目录，不是可用数据证明。先验证响应、实体身份、覆盖范围和来源时间，再实现字段。不能把样例中的预期 EPS、BMO/AMC、投票进度或未来日期写成真实数据。来源失败保留实体级最后成功值及时间；合法空结果和失败分开。

两个 Panel 共用 `official_disclosures_service` 与一个定时任务，API 只读 `SnapshotStore`，不会因用户刷新再抓上游。不修改现有 Market、OrderFilled、LOB、Oracle、AI Agent 或链上分析。

| 消费者 | 来源与边界 | 身份与周期 |
| --- | --- | --- |
| Company Events | SEC submissions 的 10-K、10-Q、8-K 及修订；companyfacts 的 diluted EPS / revenue。首批 AAPL、MSFT、NVDA、AMZN、GOOGL、META、TSLA、AVGO。只展示实际披露，不推测分析师共识或下一次财报时间 | CIK + accession；submissions 30 分钟，XBRL 6 小时；单独标注报告起止期、单位和提交日，不混合季度与年报 |
| Policy Progress | Federal Register 已公布的 Rule、Proposed Rule、Notice、Presidential Document；使用源提供的 effective_on/comments_close_on | document_number；最近 30 天最多 100 项，30 分钟；美国联邦监管公告，不宣称覆盖 Congress 立法、各国政策或所有历史文件 |

SEC API 不需要密钥；使用真实项目身份与经用户确认的联系邮箱配置 `POLYMONITOR_SEC_USER_AGENT`，仅存放在权限为 0600 的私有运行配置 `~/.config/polymonitor/official-disclosures.env`。联系信息只发送到精确匹配的 `data.sec.gov`；其他来源使用通用项目标识，自动重定向关闭，避免将邮箱转发给其他站点。Federal Register 不需要密钥，正文网页链接与 GovInfo 正式 PDF 分开保留。可见网页不是法律正式版本。来源依据：[SEC API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)、[公平访问](https://www.sec.gov/about/developer-resources)、[Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1)。

## 存储、时钟和预算

- 正式快照：现有 `POLYDATA_SNAPSHOT_SQLITE_PATH`，namespace `snapshot:official-disclosures`，key `company-events` / `policy-progress`。不假设 Upstash、R2 或 Redis 是必须的新基础设施。
- 来源状态：同一库 `source:official-disclosures`，key `sec:<CIK>:submissions|facts` / `federal-register`。成功数据、lastSuccessAt、lastAttemptAt、nextAttemptAt、错误各自保存。失败不改 lastSuccessAt。
- 原始响应版本：相邻 `official_disclosures.sqlite3`，压缩 JSON 按来源与 SHA256 去重，保留 90 天，记录首次见到与最近见到。是接入后观测档案，不能倒推成历史当时可知。
- 公告 publication/acceptance 时间、报告 period、采集成功、尝试、快照生成分开。GET 会重新判断来源是否超过有效期，进程停止后也不会永久显示为新鲜。
- 串行采集，单来源 15 秒连接 / 45 秒读取、至多两次、100 秒响应检查预算；429 遵守 Retry-After；无全局高频补抓。失败 5/10/20/30 分钟退避，成功来源按原周期复用。单响应上限 24 MB；单任务周期最多 20 分钟，systemd 禁止任务重叠。
- 浏览器通过共享 Runtime 每 10 分钟读一次快照，15 秒 API 截止，最多一次重试。30 分钟采集不能被手动刷新或浏览器轮询加速。
- 24 小时后旧值继续作为已披露历史，明确提示更新中断；超过 7 天不再进入当前列表，原始档案保留。当前政策状态按日期计算；没有日期不能补造节点。

## 视觉与单独调整

共享 Panel 外壳、标题工具、字体资源和五列槽位不变；各 Panel 自己拥有目录、模型、CSS、交互。共用请求/契约放在 `panels/shared/official-disclosures`，无相互实现导入。

WorldMonitor 实际截图观察：Earnings Calendar 的日期分组、Strategic Posture 的分类侧边色条、Macro Signals 的强调条、AAII 的大号分组值。统一视觉语言允许不同正文结构、字号和有意义的类别色。

- Company Events：青色公司代码、醒目的报告实际值、紫色定期报告/橙色临时公告，日期块和紧凑事件列表；公司切换与报告/公告筛选真正过滤；财报期和原始文件可展开。没有预测共识时不显示“超预期”。
- Policy Progress：橙色下一截止日、紫色提案/青色规则/中性通知；带侧边色条的文件标题、机构与发布日期；有源日期才显示“公布 → 截止/生效”的进程。标题和颜色不能把“发布”误当“已生效”。
- 不显示 Check/Source 周期、PARTIAL 或重复刷新行。数据详情和刷新位于公共标题栏；短提示说明具体缺失。红绿只用于有意义的方向，分类不使用好坏判断。

## 验收

解析、报告期/修订去重、合法空结果、失败保留/恢复、重启后退避、来源时间过期和 API 只读必须有测试。真实采集核验实体、日期、字段、正式存储与 API；长周期未观察完整轮次要明示。普通首页旧布局发现、隐藏后重开仍隐藏、桌面五列与移动单列、筛选/展开/原文链接须在真实生产 URL 验收。生产版本与提交一致才算发布。

## 2026-11-05 首轮运行证据

本机正式 backend 的两条只读 API 及两个公网域名都已返回对应数据：8 家公司各 24 条最近申报，EPS 与收入均存在并附带各自报告期；政策本批 100 份，其中 11 份规则、5 份提案、84 份通知，36 份有截止或生效日期。原始档案有 17 个来源响应版本（8×2 + 1），压缩 payload 合计约 2.39 MB。实际目录为 `~/.local/share/polymonitor/backend/data/`；没有把数据存到前端或新增云存储。

实际定时器是本机 `polymonitor-backend-official-disclosures.timer`，五分钟检查各来源是否到期；自动唤醒日志与正式快照核对一致，未到期时原 lastSuccessAt 保持不变。SEC 经既有腾讯 SOCKS 18992，Federal Register 直连；主 Clash、LOB 和旧 GCP 隧道未修改。长周期 30 分钟 / 6 小时尚未完整观察，不据此宣称整夜稳定。

后端解析/失败保留/恢复/存储/只读/registry 相关 11 项测试通过；前端解析、筛选逻辑、默认布局合并以及真实 registry 启动有测试。真实浏览器发现并修复了同一模块同时声明 fetchData/dataSourceId 的启动冲突。所有发布从已推送提交的 git archive 构建，Node 22.23.3 / npm 10；临时构建和上传目录完成后清理。

### 生产 UI 验收

前端发布 `2227e0423b280205832bb2188522fb2463fcef57`，`polymonitor.club` 与 `www.polymonitor.club` 的 release-sha 均核对一致。通过普通 www 首页恢复旧布局（Crypto、Big Tech、Order Flow），两个新 Panel 自动追加；原有顺序及测试尺寸保留。1440px 实测五列约 283px，2518px 五列约 499px，390px 单列 382px，无页面横向溢出。

真实数据下 MSFT 切换、定期报告过滤、5 条政策提案过滤、标题刷新、显式隐藏后再加载均通过，浏览器无 JS 异常。截图位于本机 `document/开发/核验数据/2026-11-05-official-disclosures/`；未替换 API 或地图瓦片。公网浏览器测试有网络中断/超时后重试，不能据这次验收宣称链路长期稳定。全仓 quality 的现有阻塞仍是另一个腾讯出口 systemd 单元缺少 StandardOutput/StandardError=journal；未覆盖其他任务的该文件。
