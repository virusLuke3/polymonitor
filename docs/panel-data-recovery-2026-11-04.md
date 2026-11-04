# Panel 数据更新修复：2026-11-04

这是一次运行修复记录，不替代 [数据链路规范](panel-data-pipeline.md)、[周期规范](panel-data-cadence.md) 或各领域功能索引。用户接受普通网络波动；继续使用已指定的腾讯云出口，不更换主 Clash，不恢复旧 GCP 采集器。

## 修复契约

| 数据拥有者 / 消费者 | 处理内容 | 时钟、预算与验收 |
| --- | --- | --- |
| Sports odds、Finance watch | 安装遗漏的响应校验、新闻七天窗口和合法空结果修复；失败保留值必须携带失败状态 | 保留正常 2 小时 / 10 分钟采集周期；权威空列表清除旧比赛/新闻，失败不得刷新原始数据时间 |
| Food basket、Macro CPI | 明确客户端出口；正常六小时与失败恢复分开 | 成功来源按原周期复用，失败有限退避，避免每次恢复重拉全部序列；统计参考期不因检查成功而改变 |
| Macro Map、Tech、Radar、TV | 对实际请求客户端配置已授权出口，修复缺失依赖与来源适配 | 保持领域周期；429 遵守来源退避；错误不得发布成新鲜空结果 |
| Natural Hazards / 地图 | GDACS 改用官方事件集合 API，验证 GeoJSON 类型、身份和原生时间 | 复用现有 provider 调度、持久快照及失败隔离；不修改地理坐标或地图 UI |
| AI model race | 移除失效的硬编码网页 Server Action，解析公开排名页的周榜查询 | 校验 `rankings / models / view=week`，保存页面查询更新时间；失败分类有界保留三十分钟，不用价格数据替代使用量 |
| TV、Finance external | 先选有限展示候选，再执行昂贵探测；补齐 JSON HTTP 依赖；从轮次开始计算间隔 | 单频道超时、并发和候选数量均有上限；十五分钟目标周期不再叠加执行耗时 |

来源继续由现有领域 worker 写入本机 backend 的 `data/panel_snapshots.sqlite3`；现有 Redis 展示快照继续使用 `polymonitor-sun:` 前缀，API 和前端消费已有 namespace/key。Natural Hazards 的逐来源快照本来由 SQLite 提供，不要求复制到 Redis。不新增 Panel、数据库或浏览器缓存，不改用户布局。加密原始历史继续使用 `data/crypto_strategy.sqlite3`，基础 LOB 继续归 `market-data` 所有。

领域 `generatedAt` / 来源观察时间、尝试时间、成功时间、SQLite/Redis 写入时间分别核对。失败保留旧数据不能重置数据时钟；来源成功返回空数组与失败必须区分。部署核对仓库文件与实际安装文件，而不是仅检查 Git 提交或服务 active。

## 验证与范围

先运行受影响的来源解析、快照替换、失败恢复和采集预算测试，再安装到实际运行目录并只重启受影响单元。检查自动采集日志、SQLite 与 Redis 的身份/时钟、真实 API 响应。长周期未覆盖整轮的部分单列，不把一次手动探测当成整夜验收。

LOB 特定 token 的上游未就绪继续检查已有 owner 的实际状态；不擅自增加全局连接额度。Price Chart / Flow 的历史覆盖 `partial` 不等于刷新故障。仅有超时退出堆栈的 API worker 故障不武断归因于内存或某个 Panel。

## 实施与验收结果

本节是 **2026-11-04 上午的修复窗口记录（北京时间）**，不是所有 Panel 持续健康的声明。

### 实际安装与运行配置

- 安装目录：`/home/jiahuaiyu/.local/share/polymonitor/backend`。23 个本次修改的 Python 文件与运行目录逐文件一致；另补装已提交但运行目录遗漏的 Sports Odds 响应校验和 Finance 新闻过滤。
- 配置模板：[polymonitor-panel-data-recovery.env.example](../deploy/systemd/polymonitor-panel-data-recovery.env.example)。实际文件为 `~/.config/polymonitor/panel-data-recovery.env`，由受影响服务的 `96-data-recovery.conf` 在迁移环境文件之后加载。只配置使用已有腾讯云出口，不改变隧道或主 Clash。
- 作用于 Food、Macro CPI、CPI registry、Tech、Finance watch、Finance external、Natural Hazards、Radar、Macro Map、TV、NBA、GRID、Content topic refresh 共 13 个 worker。FRED 已实测直连成功，加入 `NO_PROXY`；其余受影响外部来源使用已授权的 `127.0.0.1:18992`。
- API 已重新加载受影响模块，消费者继续读取原快照身份。没有前端样式、布局或轮询频率变更。

### 数据和自动采集证据

| 链路 | 实际观察 | 边界 |
| --- | --- | --- |
| Food / Macro / CPI actual | 09:59 起 Food 8 项、Macro 54 项、CPI actual 4 项获取并落库；Food / Macro 共 62 条序列记录，对应 61 个唯一 seriesId。10:14 的恢复轮次保留此前成功序列的 `fetchedAt`，Federal Register 恢复后 Supply 转为 `ok` | 66 是各视图记录数的合计，不是 66 个互不重复的上游序列；统计参考期仍是来源公布的月/季 |
| GDACS | 09:55 获取并持久化当前事件集合，1 条符合现有类型/告警筛选的事件；来源 `datemodified` 为 11 月 4 日，替换旧快照 | 不包含被现有规则排除的绿色告警；不把 `todate` 未来结束时间当作新观测 |
| AI Model Race | 10:01 的自动采集成功写入 20 条真实周榜使用量记录；已移除过期的固定 Server Action；公网再次读到 10:20:45 生成的 36 条完整快照，状态 `ok` | 中间采集仍遇到请求失败，10:15 读取为 `partial`；分类保留三十分钟，不能据单次成功宣布来源持续正常 |
| TV | 两轮起点为 09:54:20 和 10:09:20，相隔 900 秒；分别于 09:57:00、10:13:13 完成。实际 HLS 探测从之前 1,265 个降为每轮 176 个，存储候选 240 条；补齐 YouTube JSON 请求依赖 | 第二轮部分目录请求超时，状态为 `degraded`；播放探测失败的频道仍保留明确状态，不能当成可播放 |
| Sports Odds | 09:54 来源对当前配置的 MLB 返回合法空数组，发布空快照，清除旧比赛 | 空列表只说明本次配置范围没有返回赛事，不证明所有运动完整 |
| Finance 新闻 | 新七天窗口和发布时间排序生效；IPO 有 12 条，DeFi Security / Blockchain Policy 合法空结果可清除旧新闻 | 这里的新闻 Panel 与 DeFi Tokens 行情不同 |
| Macro Map / NBA / GRID | 10:14 附近各自再次成功发布；10:15 本机读取均为 `ok` | 期间的普通网络超时仍保留原值及原时间，不标成新成功 |
| Finance / Tech 批处理 | 每个 Panel 完成后直接存储；Yahoo 连续三个失败后暂停一分钟，尊重更长 `Retry-After`。Finance external 移除注入客户端失败后的同来源重复请求 | Finance external 原空缓存回调已接入现有 SnapshotStore，使退避跨标的与重启有效；未观察其新版本完整两轮十五分钟采集 |

### 存储身份与失败恢复

- 展示快照仍在 `/home/jiahuaiyu/.local/share/polymonitor/backend/data/panel_snapshots.sqlite3`，复用各领域现有 namespace/key；原有 Redis 同步链路保持不变。
- GDELT 429 状态使用同一 SQLite 的 `state:content / gdelt-backoff`；Finance external 的 Yahoo 失败预算使用 `state:finance-external:yahoo-source-backoff / <Yahoo base URL>`。其他 Yahoo 消费者复用原 Runtime 缓存。前两项是调度状态，不是新增展示数据拥有者。
- Food / Macro 的六小时成功窗口、CPI actual 的三十分钟窗口通过逐来源 `fetchedAt` 复用；失败恢复按 5、10、20、30 分钟退避。正常周期没有改成高频重抓。
- 来源失败保留值时写 `stale` / `stale-seed` 和本次尝试状态，保留原始 `generatedAt`。AI 混合分类保留额外使用逐项 `sourceFetchedAt`，后续发布不能无限延长旧分类。
- 10:15 对相关 namespace 的 89 份 SQLite 记录核对：77 份对应 Redis 内容一致，0 份内容不一致；另 12 份无同名 Redis，其中 10 份是设计上只存 SQLite 的 Natural Hazards 来源快照，另 2 份是旧 bootstrap / polybeats-feed 元数据。不能把这些历史记录当成当前采集失败。

### 验证结果及未完成的外部条件

- 受影响解析、来源失败、时钟、定时恢复、探测数量、有效空结果和存储相关测试 **257 passed**；本次 Python 文件 Ruff 检查和差异检查通过，前端生产构建通过。地图单元测试 221 passed / 1 skipped；来源失败与窄屏 SVG 回退两项地图 E2E 通过，未跑无关的全部浏览器场景。
- 本机 19 个接口采样全部 HTTP 200；`/health` 为 `ok`，数据库与 Redis 均通过。此处同时检查业务状态：`partial`、`degraded`、`stale` 和合法 `empty` 均按实际返回记录，没有用 HTTP 200 替代数据验收。
- 全仓 `make quality` 未通过：当前工作区另一个未跟踪的 `deploy/systemd/polymonitor-tencent-egress.service` 缺少检查器要求的两项 journal 输出设置。本任务未覆盖或提交该文件。
- BLS 发布页 / RSS 的 403、GDELT 限流、部分 Yahoo / OpenRouter / 直播源超时仍存在；已修正退避和失败状态，未宣称解除外部来源限制。CPI 的 FRED 实际值可用，不等于 BLS 发布新闻可用。
- 抽查 LOB 市场 `306833` 的上游仍 `upstreamReady=false`；已有锁与预算有真实运行中的持有者，不能将其作为死锁删除。未修改 `market-data` 全局连接预算或覆盖其他任务中的 owner 配置，因此不计入本次已恢复数据。
- 当前机器直连两个公网域名超时；改用既有腾讯云出口后，公网 `/health` 返回数据库与 Redis 健康。Food、CPI、Supply、TV、Sports Odds、AI 六个公网接口均返回 200，数据时间与本机快照对应：Food / CPI / Supply / AI 为 `ok`，TV 为 `degraded`，Sports Odds 为合法 `empty`。公网 GDACS 地图接口返回 1 条当前事件。未更换网站数据或瓦片，未开展完整生产 UI 视觉验收。
- 六小时正常周期、整夜连续运行以及全部 76 个 Panel 的逐项验收未在本次修复窗口重新覆盖，不能报告“所有 Panel 已持续正常”。

本机证据位于 `document/开发/核验数据/2026-11-04-panel-overnight/` 下的 `repair-deployment.json`、`repair-verification.json` 和 `repair-public-verification.json`；这些带时间的记录只证明对应窗口。

来源接口依据：[GDACS 官方 API 说明](https://www.gdacs.org/Documents/2025/GDACS_API_quickstart_v1.pdf)、[OpenRouter 公开周榜](https://openrouter.ai/rankings?view=week)。OpenRouter 当前适配读取公开页面的周榜查询数据及更新时间；没有使用需要密钥的数据集 API。
