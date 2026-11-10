# Sports 与 Game：赛事、博彩赔率与赛况

这两个正式 Panel 升级现有 `sports-odds` 与 `esports-intel`，保持默认显示、已有位置、大小和用户隐藏选择。它们分别汇总体育和电竞，不为每家博彩公司另建 Panel。

## 数据归属与接入

| 来源 | 用途 | 获取与所有者 | 局限 |
| --- | --- | --- | --- |
| OddsLink public board | 多家公司的胜负、让分、大小分 | 新的 bookmaker evidence owner；无需密钥 | 最多 60 场/项目，开赛前 36 小时至开赛后 4 小时；空列表表示这个窗口内无记录 |
| The Odds API | 已有体育博彩公司报价 | 复用 Sports Odds watcher，在同一次请求保存完整报价 | 保持原额度和采集周期，不因新增面板重复请求 |
| OddsLink guest | LoL、Valorant 窗口外的赛前补充 | 每项目每日一次；持久化全局 5 次/日预算，与原研究工具共用 | 试用补充，不能声称是连续实时 feed |
| KashRock public demo | GG.bet 等玩家道具样本 | 每项目每日一次，独立保存 | 单条公开演示，无报价时间不能充当当前市场价格 |
| MoviOdds | bet365 七类运动/电竞的主盘口 | 同一个 bookmaker owner | 第三方镜像；逐市场核实时钟、封盘与期间独立保存 |
| FanDuel public | NBA/NFL/NHL/MLB 胜负、让分、大小分 | 公开网页同源 JSON → bookmaker owner | 只有开赛时间，没有逐报价变价时间；不能用开赛时间当报价时间 |
| Bovada public | 上述四项及 NCAAF/NCAAB 主盘口 | 公开 coupon JSON → 同一 owner | event.lastModified 仅为事件修改时间；排除球员、半场和单节盘 |
| BetRivers / Kambi | 四大联赛公开列表中的主盘口 | 公开 listView → 同一 owner | 列表未必含每个市场；保留暂停状态、双方变价时间与千分位单位 |
| Pinnodds public | Pinnacle 七类看板，包括 LoL/CS2/Dota2/R6 | HTML 表格 → 同一 owner | 页面快照时间与逐报价时间分开；无原生 ID 的行使用精确内容身份 |
| OddsPortal public | NBA 与 LoL Worlds 多家公司独赢报价 | 页面公开 JSON + 每日公司目录 → 同一 owner | 每家公司双边独立配对；不把两侧最高价拼成一家。目录首页不等于全部联赛覆盖 |
| GRID | 官方赛程、比分、地图与选手统计 | 复用 GRID watcher | 账号权限决定覆盖；取得 CS2/Dota 不代表获得 LoL/Valorant 权限 |
| ESPN / OpenDota | 体育排名、比赛详情；Dota 历史结果 | 复用 sports expansion 与 NBA owner | 事实、预测与博彩公司赔率分开显示 |

OddsPapi、认证版 OddsLink / KashRock / Pinnodds 需要个人账号密钥，不能把介绍页面当成已接入 API。Pinnodds 与 OddsPortal 的公开通道独立接入，以扩大事件覆盖；同一家公司的多个通道不增加独立博彩公司数量。API 域名、URL 模板、密钥、代理均来自个人 `.env`；`.env.example` 只列空值。浏览器不收到服务密钥或代理地址。

### 完整调研来源清单与边界（2026-11-10 修订）

“来源通道”与“博彩公司”分别统计。一个 OddsLink / OddsPortal 通道可以承载多家公司的报价；oddswrap 和 OddsHarvester 是获取工具，不是另外两家博彩公司。不得只列 MoviOdds，也不得把已保存的 30 多家公司说成仅有八家。

| 调研过的通道 | 本轮处理 | 可核实边界 |
| --- | --- | --- |
| The Odds API | 保持既有持久采集及个人密钥，复用整份响应 | 不新增消耗额度的重复请求 |
| OddsLink public board | 扩到其公开目录列出的 14 个项目，包括 MMA、NCAAB、NCAAF、WNBA | 实测多数项目只返回 3 场；是公开样本窗口，不是完整付费目录 |
| OddsLink guest | 保留两项日级补充与全局 5 次/日配额 | 不当连续 feed，不额外消耗匿名额度去反复探测 |
| MoviOdds | 保持七项目生产快照 | WS/历史等额外能力不能写成已常驻采集 |
| KashRock public demo | 保留演示样本，独立标识 | 不当完整 GG.BET 实时数据；正式密钥接口未配置 |
| Pinnodds public | 新接七看板 | 页面可用；认证 REST/WS 是另一项权限，不假定已有 key |
| FanDuel public（oddswrap 调研路线） | 新接四大联赛 | 已取得真实价格；原生报价时钟缺失保持未知 |
| Bovada public（oddswrap 路线） | 新接六联赛 | 已取得真实价格；不按数组位置猜球队 |
| BetRivers/Kambi public（oddswrap 路线） | 新接四大联赛 | 有真实报价；空赛季目录与请求失败分别处理 |
| OddsPortal（OddsHarvester 调研路线） | 新接 NBA / LoL Worlds，读取公开页面 JSON | 不需要另装浏览器抓取库；不执行页面 JS；电竞总目录只有客户端占位数据，不能记成零场成功 |
| Pinnacle guest API | 本轮公开配置返回 403，未启用直连 | Pinnacle 价格仍可经 OddsLink / Pinnodds 获得 |
| DraftKings public（oddswrap 路线） | 本轮返回 403，未启用直连 | DraftKings 价格仍由 The Odds API / OddsLink 提供 |
| BetMGM public（oddswrap 路线） | 本轮 clientconfig 返回 403，未启用直连 | BetMGM 价格仍由已有聚合通道提供 |
| Caesars public（oddswrap 路线） | 本轮 schedule 返回 403，未启用直连 | Caesars 价格仍由 OddsLink 提供 |
| Oddschecker | 本轮普通 HTTP 返回 403，未启用采集 | 不能把一次拒绝说成永久不可用，也不能当作已接入 |
| OddsPapi authenticated | 未找到个人密钥，未启用 | 没有以他人密钥代替；不是虚构的“已连通备用” |
| OddsLink / KashRock / Pinnodds authenticated | 私有配置占位与边界登记 | 公开通道可用不代表认证通道有权限；需要密钥后仍须校验相应 schema |
| GRID | 保留官方赛况 owner | 不是赔率来源；不纳入博彩公司数量 |

以上拒绝访问记录是本轮探测结果，非永久健康状态。探测元数据保存在现有 `research:bookmakers:source-audit:v1`；成功原文与规范化响应沿用正式 evidence 存储。生产源状态以最新持久记录为准。未接通的认证/拒绝通道不会每五分钟空转请求，也不通过换出口规避 403。

新增解析归属 `scripts/api/services/bookmaker_panels/public_books.py`，没有新增 Panel、重复数据库或采集守护进程。每个来源/项目有独立 `bookmakers:<provider>:<sport>:v1` 身份；OddsPortal 公司目录 `bookmakers:portalbooks:catalog:v1` 每日获取、最长保留七天，先验证目录再发布价格，不猜公司 ID。

新增报价源目标周期 15 分钟，30 分钟标旧、两小时停止展示；同一 owner 每五分钟检查到期状态。仍使用 240 秒整轮上限、45 秒完整单次、最多两次、8 MiB 响应与 2 MiB 规范化上限；超预算下轮优先，不压缩备用出口的请求时间。源预算不足时明确 deferred，不能宣称全部项目准点。超时保留旧原文/成功时间，恢复后由下一轮到期采集重新验证并入库。

FanDuel 的 marketTime、Bovada 的 lastModified、Pinnodds 的 dateModified 都不冒充逐报价时钟。页面可展示这些真实观测价格，但未知时钟不进入“当前博彩公司均值”。Kambi 取双方中较早的 changedDate，封盘与不完整市场不进入当前均值。Stake.com / Stake、GG.BET / GGBET 等明确别名统一公司身份；Betfair Exchange 单独归为交易所。跨来源队名/时间不一致时保留不同事件，不强行合并。

前端“全部公司”统计投影前的完整存储覆盖，显示公司、通道及赛事数量；赔率页可按通道筛选，每行标注实际 provider。API 仍有 60 场/450 KB 投影上限，先保证每个可用 provider 至少一场，再按项目轮转；未含场次明确显示，完整覆盖计数不能误称这些比赛全部已经在下拉列表中。两种时效各自显示，禁止把“有保留价格”说成“当前可成交”。

实现依据：[oddswrap](https://github.com/sjhouston23/oddswrap)、[OddsLink 公开看板](https://oddslink.app/docs/api-reference/operations/publicboard/)、[Pinnodds 公开电竞板](https://pinnodds.com/pinnacle-odds/esports)、[OddsPortal LoL Worlds](https://www.oddsportal.com/esports/league-of-legends/league-of-legends-world-championship/)。实际报价以采集证据为准。

## 获取、存储与恢复

### MoviOdds 补充链路

MoviOdds 是第三方 bet365 报价来源，补进同一 Sports / Game，不替代 GRID 的官方赛况身份。配置读取 `POLYDATA_MOVIODDS_BASE_URL`、可选 `POLYDATA_MOVIODDS_API_KEY`，代理沿用 `.env` 的来源路由。它的免费访问规则以当前响应为准，401/403 停止并保留错误，不寻找他人的密钥。

当前落地范围为七个项目的有界 REST 主盘口快照：足球、篮球、网球、美式足球、冰球、棒球及电竞，每五分钟到期采集；按来源实际 group 过滤，赛前和滚球 group 分开。沿用 bookmaker owner、正式 evidence SQLite、SnapshotStore 和只读 API，不再创建重复历史库或页面取数。单来源 45 秒完整尝试、最多两次，整轮仍 240 秒；响应上限 8 MiB、规范化 2 MiB，未执行来源下轮优先。新源 10 分钟标旧、30 分钟停止展示；来源级失败保留原成功时间。原有来源周期与付费额度不变。

`ts` 是价格变化时间，`group_status[group].polled_at` 是该市场最近核实时间，两者单独保存；不能拿本次抓取时间给旧报价续期。该来源缺少 group 核实时钟的报价不参与主概率。封盘、上游 stale、采集失败的保留值及滚球采集超过两分钟的值不参与当前共识。匿名 API 不承诺一秒更新，本轮页面消费仍按已有分钟级 Runtime。

来源纳秒时间先截取至微秒，再做带时区解析，兼容正式采集器 Python 3.10。回归必须使用生产 Python 验证，避免开发环境版本较新时掩盖时间解析失败；真正无效的源时间仍为未知。

方向只读取来源明确的 `side` / `label` 并核对双方实体；`sel_id` 仅作为身份，禁止按数字大小或数组位置猜主客。不同 group、market_id、盘口线、比赛阶段及期间先隔离再验完整双边／三边。足球保留平局；地图盘不能混进系列赛；电竞篮球不能归为 NBA。源端预热空响应是失败，合法空窗口才可覆盖旧目录。不同源只有精确队名与开赛时间一致才合并；报价独立保留采集时间和错误，避免其他源给旧值续期。

WebSocket、历史、收盘和赛果接口分别验证能力，不因握手 101 就宣称增量采集已上线；本轮 REST 快照与既有历史证据是生产更新链。Pinnacle 报价继续复用已接入聚合源；公开访客配置访问失败不能描述成已接入直连。后续流式接入需另外验证 snapshot/delta/remove/resync、断线封旧、重新快照及历史容量预算。

2026-11-10 北京时间约 10:10–10:24 实测：匿名 MoviOdds REST 返回有效 JSON；七个主盘口源分别写入正式 evidence 与 snapshot，原始哈希和规范化读回逐一相同。电竞当轮 22 场（LoL 4、CS2 4、Dota 2 8、R6 6），Valorant 无当轮记录；篮球当轮 133 场规范化记录中含 NBA 13 场，明确排除了电竞篮球。棒球过滤后的主盘口为空，未伪造报价。网站单次响应仍有 60 场及字节上限，按项目及来源轮转展示，并报告未包含场数。

同轮 LoL 四场与本机 Polymarket 目录独立匹配：FENNEL / Nothin'Here、Ground Zero Gaming / Frank Esports、Bilibili Gaming / Gen.G 三场满足游戏、双方与开赛时间；Saigon Warriors / Team Gromp 因别名未核实保留未匹配。结算规则等价四场均未核实，不计算可执行套利。WS 单次 20 秒连接收到两份真实 snapshot 及 polled 消息，超过仅握手的验证，但不是生产常驻订阅验收。Pinnacle 公开配置在现有出口返回 403，未启用新访客直连；现有聚合报价继续工作。

协议依据：[MoviOdds 当前文档](https://moviodds.com/doc)、[项目及盘口类型](https://moviodds.com/docs/sports/)。当前文档说明 API key 暂时可选；不得把旧“永久无密钥、所有字段都实时”的描述固化为契约。解析与恢复测试覆盖明确 side、缺失 label、封盘、市场核实与变价时钟、混合盘口线、完整三项胜负、预热响应拒绝、跨来源保留期限。此段为采集实测记录，最终公网展示另行验收。

- 公共看板每 15 分钟检查；调度器每 5 分钟唤醒，持久化 `nextAttemptAt` 防止多实例重复获取。单次 45 秒，两次完整尝试，整轮 240 秒，未执行的来源下轮优先。
- guest 额度通过 `.env` 的 `POLYDATA_BOOKMAKER_QUOTA_SQLITE_PATH` 指向同一个持久账本；研究工具和正式采集即使使用不同快照库，也不能各自获得 5 次额度。额度耗尽后等到下一个 UTC 日。
- 复用 `panel_evidence_store`：原始响应与规范化版本先写压缩 SQLite evidence，再发布源状态到 `SnapshotStore`。失败保留原始成功时间，不把空失败写成成功；429 遵守 Retry-After，401/403 不轮换出口绕过限制。
- 公共看板源状态新鲜阈值 30 分钟、最长保留 2 小时。每家公司的 `sourceUpdatedAt` 单独决定报价时效；重新下载不刷新旧报价时间。日级试用单独标识，不能混入当前共识。
- 原始 evidence 共用现有 2 GiB 硬上限。响应最多 8 MiB、规范化最多 2 MiB、每个面板最多 60 场。浏览器共享 Runtime 缓存有固定版本、完整 panel 身份、时效和大小上限；页面刷新只读取持久快照。
- 两个响应含完整博彩公司矩阵，使用共享 Runtime 的独立请求模式（`batch:false`），45 秒资源总预算，其中 HTTP 与响应体读取最多 30 秒；不排在其他 Panel 的批量队列后等待，仍遵守全站请求并发预算。Sports 每五分钟、Game 每两分钟重读，网络失败走 Runtime 已有退避，不加快来源采集。
- 代理使用现有 `SourceSession` 和 `.env` 的来源路由；不改变主 Clash。失败次数、最近尝试、成功时间、下一次尝试、原始版本哈希在源状态中保留。

## 比较规则

博彩公司、交易所和预测市场分开标记。每家公司完整两项或三项报价分别进行比例去水；不能删掉足球平局后算二项概率，不能混合不同让分或大小分线。源数据不是可执行盘口，不标注套利或确定性收益。

不同聚合来源只有项目、规范化队名和开赛时间完全一致时才合并比赛；同一公司、同一市场和同一盘口线只保留源时间较新的报价。不自动合并球队别名，也不把同一家公司的两个聚合商记录算成两家。

Polymarket 匹配要求游戏、球队、比赛时间和胜负市场类型一致；同一比赛候选不代表结算规则一致。缺少规则/BO/时间时保留未核实。聚合器直接提供的 Polymarket 行单独展示为预测市场，不作为博彩共识的一家。GRID 赛况不转换成假造的胜率。

## 前端设计

- 共用现有细灰边框、标题、刷新入口和五列布局；正文有领域差异。
- Sports：青色/橙色对阵、醒目的主概率、赔率比较表、不同盘口线筛选，下面为赛程或统计事实。
- Game：紫色/蓝色游戏标签、系列赛对阵、完整博彩公司矩阵，独立的官方赛况与道具样本页签。LoL/Valorant 赔率可用不代表 GRID 赛况可用。
- 数值使用等宽字体，主数字 24px，标签/来源弱化；表格在单列宽度内显示，手机不横向撑开。颜色表达队伍与类别，不把所有数字统一灰白。
- 保留 `sports-odds` / `esports-intel` IDs；只更新显示名为 Sports / Game。资源由 Runtime 管理，Panel 不创建计时器、HTTP 客户端或独立缓存。

## 验收

解析测试覆盖三项胜负、正负美式赔率、不同盘口线、损坏响应、失败保留和来源时效；真实请求需取得博彩公司报价且完成落库读回。已有 The Odds API / GRID 的成功不代替新来源验证。发布后从普通首页确认两张面板、筛选与数据展示，并分别记录桌面和手机证据。单轮成功不能声称全部渠道持续正常。


### 2026-11-09 接入与发布验收

- 数据链路：15 个配置来源状态（Sports 7、Game 8）均已取得有效响应并落库；空列表同样是可验证的响应，不代表该项目有赔率。正式 SQLite 为后端数据目录中的 `panel_snapshots.sqlite3` / `external-panel-evidence.sqlite3`，guest 额度账本由 `.env` 单独指向同一持久位置。
- 19:26 北京时间快照：Sports 来源共 24 场，当前有界响应 11 场、34 家博彩公司；Game 11 场、16 家博彩公司。计数随来源窗口变化，不作为固定覆盖承诺。Sports 的完整矩阵有 450 KB 响应上限，按项目轮转保留；未包含场数明确报告。
- 实际读到了 Pinnacle、bet365、Stake、Thunderpick，以及 DraftKings、FanDuel 等报价。NBA、LoL、CS2、Dota 2 的多轮持久版本中，源报价时间随下一轮前进；更新成功不是仅改 `fetchedAt`。公共看板采集服务由五分钟 timer 唤醒，来源自身十五分钟到期才请求。
- 82 项 Python 回归测试与 45 项前端测试通过，TypeScript、边界、样式归属和干净发布构建通过。测试包含保留值过期、来源时钟、不同盘口线、交易所分类、匿名配额跨存储共享、30 秒 HTTP 截止与传输取消。
- 普通 `www` 首页能直接发现 Sports / Game，保存布局后重新打开顺序及尺寸一致；在 1920px 和 390px 视口检查真实接口数据。截图保存在 `webpage/design-previews/sports-game/`。没有替换接口、地图瓦片或注入虚构响应。
- 本次新来源走 `.env` 中已配置的腾讯出口，未改变主 Clash 选择。当前实际服务在腾讯前端与本机后端，不恢复已停止的旧 GCP 采集器。

明确保留的边界：Valorant 本轮公开窗口没有比赛；KashRock 只接公开演示，当前演示也可能为空，不能算完整 GG.BET 实时接口；GRID 的 LoL / Valorant 官方赛况权限未取得。OddsPapi 等需要未提供密钥的认证接口仍未启用。公开 guest 总预算共享改造前的两份账本被保守合并为当天已用 7 次，当天不再发请求，次日按 UTC 重置，不能把先前超额记成未发生。

公网验收期间出现过反向链路慢响应、502 和浏览器连接变化；共享 Runtime 重试后两面板取得真实数据。这个观察证明恢复路径工作，不代表全天稳定或每次首屏都快速成功。退避期间已有未过期数据继续展示，真实请求失败与来源无比赛分开提示。


最终功能版本：`1789055ed23b37656ae58c745fcfccb956b914ca`。`www` 与裸域名的 `/release-sha` 一致；页面实际载入 `index-Bhprnarm.js`，后端本次修改的文件与该提交逐字节相同。部署使用推送提交的 `git archive` 干净构建，构建目录已清理。

最终浏览器验证中，两个 Panel 均为 `ready`；切换第二场 NBA 比赛、让分（`Charlotte Hornets +8.5 / Cleveland Cavaliers -8.5`）、大小分均出现 8 条默认比较行；CS2 官方赛况显示 3 条记录。Valorant 空窗口与未取得 GRID 权限分别显示。再次载入保存布局后，桌面与手机均读到真实快照。最后一轮浏览器使用 HTTP/1.1 排除测试代理的 HTTP/2 干扰；此前默认协议也已取得两面板实际报价，测试过程中均未替换网络响应。

- [Sports 桌面](../webpage/design-previews/sports-game/production-sports-odds-desktop.png)
- [Sports 赔率表桌面](../webpage/design-previews/sports-game/production-sports-prices-desktop.png)
- [Game 桌面](../webpage/design-previews/sports-game/production-esports-intel-desktop.png)
- [Sports 手机](../webpage/design-previews/sports-game/production-sports-odds-mobile.png)
- [Game 手机](../webpage/design-previews/sports-game/production-esports-intel-mobile.png)
