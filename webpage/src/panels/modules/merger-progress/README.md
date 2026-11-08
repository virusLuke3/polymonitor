# 并购进程 / `merger-progress`

本目录是正式生产模块；设计参考位于 `webpage/design-previews/market-domains/` 相应目录。独立正文保留设计里的字体层级、领域色彩和结构，公共 Panel 外壳、五列与尺寸不修改；新模块默认启用，由共享旧布局补齐逻辑发现，不创建专属入口。

## 领域链路

- 数据：SEC配置发行人的S-4/DEFM14A及相关8-K items原始披露；复用已有SEC Transport/contact UA/专用env代理。
- 业务拥有者：`scripts/api/services/finance_expansion/` 按 token-events、chain-metrics、fiscal、company-capital 来源身份扩展；采集统一由外部领域定时owner调用 `collect(store)`，不为此Panel单起worker或缓存。共享传输复用 `api.clients.source_transport`；SEC复用既有 `runtime.official_disclosures_watcher.Transport`。
- 原始及规范化证据：共用 `api.services.panel_evidence_store` 的 SQLite evidence 表，按source+SHA256修订幂等追加，保留first_received/last_received；正式路径由 `POLYMONITOR_EXTERNAL_EVIDENCE_SQLITE_PATH` 注入，未配置时与SnapshotStore同目录。2GiB总容量上限，超限拒写并保留旧成功，不承诺完整历史回测。
- 当前来源：既有 `SnapshotStore` / `POLYDATA_SNAPSHOT_SQLITE_PATH` / `panel_snapshots`，namespace `source:external-panels:v1`，key `company-capital:sec:<issuerId>`。GET纯读取这些源并组装，不发上游请求或新写快照。
- API：`/runtime/external/merger-progress`；前端 `shared/external/resource.ts` 的 `externalPanel` 声明 `external:merger-progress:v1`，通过共享Runtime执行取消、隐藏暂停、重试及浏览器恢复；200,000字符/资源，受全局缓存总预算约束。
- 范围：配置中的有限对象，不声称全市场全覆盖；来源自己的native ID与业务窗口保留。UI筛选仅针对已加载集合。

## 时钟、预算与配置

SEC30分钟；浏览器15分钟；90分钟新鲜，最多保留24小时。

源日期/观察时间、采集lastSuccessAt、API投影generatedAt、浏览器checkedAt分别记录。失败保留最后成功及原时钟；正常空可以更新，错误不能把旧值清空。源最大保留期在每次GET重新校验；缺源的局部内容显示具体缺口。

单源45秒完整尝试，最多2次（由共享传输遵守429 Retry-After及授权出口），整个family采用720秒新请求准入预算、串行同源并发1，不重叠；已开始的阻塞I/O仍受45秒I/O超时约束，进程最终截止由运行服务限制，不将软预算声称为严格总墙钟期限；已到期来源按最旧尝试排序。锁繁忙标deferred，不阻塞后续源。TVL原件最大16MiB，其它8MiB；规范化源2MiB、投影512KiB、返回最多100事件。浏览器有界20秒请求、一次重试；不因刷新按钮加速上游。

个人配置全部位于 `.env`：`POLYMONITOR_CAPITAL_SUBMISSIONS_JSON / POLYMONITOR_SEC_USER_AGENT / POLYMONITOR_DISCLOSURES_SEC_PROXY_URL / POLYMONITOR_URL_WWW_SEC_GOV_ARCHIVES_EDGAR_DATA_69AE63`；复用 `POLYMONITOR_SOURCE_ROUTES_JSON`。没有源码真实URL/密钥/代理回退，不改主Clash。通过 `runtime.environment` 加载，显式进程变量优先；公开API只给审核过的证据链接，不透出配置对象。

## 当前字段边界

对价、截止日、监管审批、具体deal身份未从条款提取。2.01表示收购/处置完成披露，不等于已核实某个并购Market交割；1.01可能是其它重大协议。

## 验证入口

`tests/test_finance_expansion.py` 验证真实业务解析边界、单位/财年身份、失败保留、原始时钟、只读GET。此文档不把本地测试当生产验收；根任务统一核对正式store、API、真实公网桌面/手机、旧布局自动发现和后续周期。首次接入成功也不代表长期连续性或上述缺口已经补全。
