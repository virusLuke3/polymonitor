# Politics：8 类 Market 的数据补齐与 Panel 设计

设计日期：2026-11-06。状态：**公开来源版本已部署，九个新增面板和升级后的 Policy Progress 接入原工作台。§9 保留首版发布证据；四项证据字段的后续实现、范围与部署界限见 §10。不能将公开来源版本解释为全部政治数据已补齐。**

用户要求把上一轮政治数据缺口全部纳入，并先设计 Panel。本文件覆盖所有缺口，不把访问权限、来源覆盖、模型或历史缺口删除后称为完成。设计原型的政治实体、数值与事件全部是虚构样例。

## 1. 范围与交付

采用 10 个视图：9 个新增，升级现有 `policy-progress`。8 个主体覆盖 8 类 Market，提前投票、竞选资金作为跨选举类型的两个辅助视图。拆分依据是判断任务与数据粒度，不是为每个来源建一个 Panel。新增面板将直接合并进原工作台，保留旧顺序、尺寸与明确隐藏；设计页的集中摆放不是新导航方案。

| 编号 | Panel / 拟用 ID | 要回答的问题 | 对应 Market | 本体视觉 |
| --- | --- | --- | --- | --- |
| P1 | 选举观察 / `politics-election` | 当前应看民调、实际票数，还是结果程序？ | 选举结果；兼容初选单场 | 分类大数字、多序列趋势；计票横条；认证时间线 |
| P2 | 提前投票 / `politics-early-vote` | 票从哪些地区、以什么方式进入？ | 选举结果、提名、议席 | 青色主数值、申请→寄出→退回、同距选举日曲线 |
| P3 | 提名路径 / `politics-nomination` | 实际代表票离提名门槛还差多少？ | 候选人提名 | 紫色代表票、门槛刻线、下一州日期块 |
| P4 | 议席格局 / `politics-seats` | 已获多少席、还剩哪些未决席位？ | 议席数量、控制权 | 分类席位格、三组大数字、未决选区表 |
| P5 | 竞选资金 / `politics-campaign-finance` | 同期资金与独立支出如何变化？ | 选举结果、提名、议席 | 橙/青配对条形图、现金/债务、申报修订 |
| P6 | 控制权与组阁 / `politics-government` | 谁能控制议会或完成组阁？ | 政府控制权 | 联盟席位条、带色背景的程序结论、信任投票节点 |
| P7 | 立法与监管进程 / 保留 `policy-progress` | 法案还缺哪些必要程序？ | 政策立法 | 两院程序分支、下一动作强调块、版本和投票明细 |
| P8 | 行政命令 / `politics-executive` | 是口头表态、签署、公布，还是已生效？ | 行政命令 | 文件标题、签署/公布/生效三日期、效力变化 |
| P9 | 政治任命 / `politics-appointments` | 人选走到哪一步，实际确认票如何？ | 政治任命 | 人选/职位、委员会票数、最终确认及任职节点 |
| P10 | 拨款与停摆 / `politics-funding` | 哪些资金何时到期，还有哪些立法窗口？ | 政府停摆 | 琥珀倒计时、12 类资金覆盖矩阵、议程时间线 |

本轮不修改 Market、OrderFilled、LOB、Oracle、AI Agent 或链上分析。读取已有市场身份、价格和 Rules 作为关联上下文；不另起 Polymarket 采集器。政治事实不由 LLM 无证据推断。

## 2. 视觉与真实参考

遵循 [统一指南](../document/开发/Panel开发统一指南.md) §8.1–8.3。原型直接导入现有 `Panel.tsx`、`PanelDataControls`、字体、`base-layer.css`、`panel-layout-stability.css`，没有复制标题外框。桌面 1440/2518px 为五列，默认行高使用现有 268/282px；正文单一纵向滚动。手机单列。原型的“展开设计内容”仅供检查内容，不写布局、不改生产尺寸。

本次实际查看了仓库保存的 2026-11-05 WorldMonitor 线上截图：[AAII](../webpage/design-previews/external-panels/worldmonitor-reference/finance-aaii-sentiment-expanded.png)、[Strategic Posture](../webpage/design-previews/external-panels/worldmonitor-reference/www-strategic-posture.png)、[Macro Signals](../webpage/design-previews/external-panels/worldmonitor-reference/finance-macro-signals-expanded.png)。更多日期块/热图参考及当次 computed style 在[参考记录](../webpage/design-previews/external-panels/worldmonitor-reference/README.md)。这不是声称 WorldMonitor 已有上述政治业务面板。

- 外壳：共享 1px 灰边、直角、公共标题和工具区，不增加装饰蓝框。
- 标题沿用 mono；中文正文沿用已有 Noto Sans SC；主数字 20–28px 等宽，重要实体 13–16px，普通正文 12px，说明 10px。
- 只用已有语义变量：美国民主党（D/DEM）用蓝、共和党（R/REP）用红，由共享 `partyTone` 按来源党派字段映射，主数字、票数条、席位格及多数党摘要一致。其他或未知党派先用中性色；不得按候选人顺序、得票高低或姓名猜测党派。民调未提供党派字段时使用中性色。党派红蓝只表达身份，不表示好坏或涨跌；非美党派另按当地事实建立映射。紫保留给非党派的程序分类，青用于投票量和已核实程序，橙用于资金/文件类别，琥珀用于期限或待决。
- 允许分类浅底、侧边色条、突出主数值和不同图形；不统一为“三个小框+折线”。未知值不填零，图表有系列标签与单位。
- 正文不显示 `Check / Source / Snapshot / PARTIAL / READY` 等内部调度字段。对判断有意义的发布期、原始时点、预计/正式口径仍可见。
- 首屏显示判断所需的数值与主要图形；完整来源、修订及方法进入展开区。窄屏不靠缩小所有字体塞内容。

## 3. 逐 Panel 内容与交互

### P1 选举观察

首屏对象是选定国家、选举/轮次、州/选区与职位。民调期显示最新有效调查的候选人支持率、明确未决定比例、原始调查序列。需要聚合时标注机构原平均或本地计算及方法版本；没有模型就不生成“胜选概率”。支持率与已有 PM 价格分开显示。

计票期显示候选人票数、当前差额、分县/选区批次、未报地区与剩余票类型。剩余票估计注明来源和估计时点；无法获得时显示未知，不能由已报告 precinct 比例推算。结果期显示媒体 call、官方复核、重计票、司法事项、认证，允许并行。

按有证据的事件阶段调整默认视图，不仅靠日期。保留三个视图和用户手动选择，刷新不抢回用户当前页签。Rules 决定合约认定事件，不统一强制等待官方认证或一律相信媒体 call。细节包括调查机构、样本、方法、LV/RV/成人口径、原题、公开/田野时间和版本。

### P2 提前投票

邮寄票申请、寄出、退回；现场提前投票、拒收/补正分别保存。主值为实际收到票数；退回率明确分母为已寄出票数。上届对照按距投票日而不是公历日对齐，只有范围和口径一致才可比较。

地区表显示覆盖/缺报辖区。年龄、登记党派等人口统计只显示来源实际提供的维度；登记党派不等于投票选择。EAC/EAVS 历史统计只能校准投票方式和地区分母，不能当成当届逐日提前票。

### P3 提名路径

按政党和届次选择规则，显示代表票总数、门槛、候选人已获票、未分配票及下一州初选。区分 pledged/unpledged、allocated/bound 等来源定义；退选不自动将代表票清零。

下钻查看州级分配规则、达到门槛的条件、初选日历、候选人资格、退选、背书及党代会文件。当前民调作为辅助页签复用 P1 的 owner。FEC 备案不是取得提名，达到数字门槛不代替正式提名事件。

### P4 议席格局

每格代表一个可识别席位；分类显示按选定口径已判定/认证/就任的席位和未决席位，不混用媒体预测与官方结果。普通格子排列不是地图。选区重划以边界版本关联历史，无法跨版本对齐就不画同比。

点击席位显示候选人、实际票数、领先差、待计地区、重计票/认证状态、历史结果、筹款摘要与关联 Market。共用 P1/P5 数据，不重复采集。席位分布概率是独立模型工作项，不能从全国民调直接换算。

### P5 竞选资金

候选人/委员会视图展示同一报告期的筹款、支出、期末现金、债务，明确申报日期、报告期和是否修订。独立支出另页显示支持/反对哪位候选人、支付方、金额及时间；不与候选人自己的收入合计。

去重身份包含 candidate、committee、filing、transaction 及修订链。资金不等于选票；FEC 支出不能被包装成所有广告素材、投放次数、曝光或人群覆盖。若 Market 需要广告本身，增加经许可的广告库/官方政治广告文件来源并单独核验，不在 FEC 上造字段。

### P6 控制权与组阁

按国家、议会/院别、届次装载规则。议会制展示党团席位、正式联盟/支持协议、组阁人选、信任票、任命与就职；美国等场景使用相应院别的党团、议长与平票规则，不能套组阁模板。

仅有新闻报道的谈判标为报道，不升级成正式协议。议员转党、空缺、联盟退出产生事件版本。原型展示议会制样例；非美来源逐国验收，不能将多国语言选择器当作全球接入完成。

### P7 升级 Policy Progress

保留现有 Federal Register “监管公告”能力，新增独立“法案”视图，分别使用行政规则与国会立法的状态。Congress 届次+类型+编号确定法案身份，保存文本版本、共同提案人、委员会、听证、修正案、程序票、最终票、两院文本一致性、送交总统、签署/否决/覆议。

用下一必要动作与两院分支说明程序，不将节点数画成“通过概率”或简单百分比；共同提案人/公开支持不等于实际投票。法规 Proposed Rule 不叫国会法案。正文/正式 PDF 与状态事件都应可追溯。

### P8 行政命令

按总统文件类型与原生编号去重，突出命令题目、签署、公布、各条款生效日。签署证据、Federal Register 记录、GovInfo 正式版本彼此关联。修订、撤销、延期、法院暂停执行保存适用范围和效力时间。

复用 official-disclosures 的 Federal Register owner，补增量游标、分页、目标文件详情、正文及类型字段；不再仅取滚动前 100 条。不新建第二个 Federal Register 采集器；列表中暂时消失不等于撤销。

### P9 政治任命

提名编号+届次+被提名人+职位，处理同一 PN 包含多人、撤回/退回及重新提交。人选区显示履历/资格来源，不由模型判断资格；时间线包括提交、听证、委员会、全院程序、最终确认、任命/就职。

委员会票、结束辩论票、最终确认票分别展示；逐名票记录与公开表态分开。未来日期只有官方议程支持才显示，改期保留版本。任命完成的具体定义使用 Market Rules。

### P10 拨款与停摆

按财政年度和具体资助范围显示全年拨款、CR 或资金缺口。12 类常规拨款不等于 12 个部门，矩阵展开到法案条款覆盖的机构/项目。到期时间包含时区，倒计时在本地计算，不因此高频请求上游。

绑定 CR 及年度法案、两院议程、最终表决、同文核对、签署和拨款效力，计算有事实依据的剩余立法窗口。OMB 规则、机构预案、实际执行通知、恢复通知分别保存。短暂资金缺口、局部停摆和合约定义不能混为一谈。

本次核对发现旧 OMB `information-for-agencies/agency-contingency-plans/` URL 已 404；[当前 OMB 说明](https://www.whitehouse.gov/omb/information-resources/guidance/miscellaneous/)称机构预案保存在各机构网站。实现必须建立机构官方文件目录，不能继续把旧链接当作统一可用接口。

## 4. 缺口覆盖清单与来源选择

所有下列项目均属于后续实现范围；“拟接”不代表已有生产数据。采集准入按字段检查，未知字段保持未知。

| 缺口 / 验收字段 | 复用 / 拟接来源 | 消费面板 | 当前状态与不能替代的部分 |
| --- | --- | --- | --- |
| 当前民调、样本、方法、公开日、选民口径、未决定、题目 | 本地 538 历史、Decision Labs 解析代码；当届 Decision Labs + 机构原文 | P1/P3/P4 | 本地历史/快照可复用；当届持续采集待建。字段可能为空，不从 100−两人比例推定未决定 |
| 历史民调误差、机构效应、区域相关性 | 538、历史最终结果；独立计算版本 | P1/P4 | 数据不等于模型；按整场选举切分、过去数据训练，禁止未来泄漏 |
| 每日提前票、邮寄票退回、人口统计 | 对应州选举机关；AP advance turnout 按已获权限 | P2/P1/P4 | EAC/EAVS 已有的选后历史不能替代；逐辖区/维度登记覆盖 |
| 分县/选区票数、待计票、媒体 call | 州/县选举机关；AP results 按权限 | P1/P4 | 不存在能保证所有州同字段的免费通用接口；缺源不伪造剩余票 |
| 认证、重计票、诉讼/裁决 | 选举机关、相关法院、官方公报 | P1/P4/P8 | 保存原件、适用对象和时间；相关新闻只辅助发现 |
| 初选日历、分配规则、代表票、正式提名 | 政党、州初选机关、AP delegates | P3 | 候选人登记与正式提名分开；按届次记录规则版本 |
| 候选人、现任者、选区/边界版本、正式席位 | 官方选举名单、议会名册、选区资料 | P1/P3/P4/P6 | 只接身份/边界版本，无地图改动；无法映射不得强连历史 |
| 筹款/支出/独立支出、备案、修订 | OpenFEC | P5/P1/P3/P4 | 需要实际 API 配置；已有 FEC 结果工作簿不能替代 |
| 联盟协议、党团变化、信任票、任职 | 各国议会、政党正式声明、政府公报 | P6 | 按活跃 Market 覆盖国家，逐国来源待核验；不宣称全球完成 |
| 法案文本、行动、听证、修正、议员支持、投票、法律 | Congress.gov、两院、委员会、GovInfo | P7/P10 | 数据源分工；声明与实际票分开，需校验两院同文 |
| 文件分型、EO 编号、签署、公布、生效、修改/撤销 | 复用 Federal Register + 政府签署原文 + GovInfo | P8/P7 | 已有 FR 元数据；需补分页、目标详情、正式正文/版本 |
| 提名/资格记录、听证、委员会及确认票、任职 | Congress nominations、参院/委员会、政府 | P9 | 听证与确认、确认与就职分开；按 PN 子项建身份 |
| CR、12 类拨款、精确截止、议程、实际停摆 | Congress/两院/总统 + OMB规则 + 各机构文件 | P10 | 不能用预案代替停摆，也不能仅用新闻倒计时 |
| PM身份、结算条件、指定证据、截止时区 | 已有 market-data/Market 读取契约 | 全部 | 仅消费；名称相似只是候选映射，未验证映射不输出匹配结论 |

来源依据（本次查阅官方文档，非全部实际采集验收）：

- [Decision Labs API](https://www.decisionlabs.ai/docs/api)：公开无认证；2026 民调导出标明 1 小时边缘缓存、来源链接及署名要求。读取原始民调字段优先，模型/评级与事实分开。
- [AP Elections](https://developer.ap.org/ap-elections-api/index.html)：计票/代表票/提前票能力，需要 API key 及对应访问权限。先核实现有配置，缺授权时登记具体覆盖缺口；不未经授权购买或声称州官网完全等价于 AP。
- [OpenFEC](https://api.open.fec.gov/developers/)：竞选财务；生产配额和密钥需核实。不得将广告支出说成广告曝光。
- [Congress.gov API](https://github.com/LibraryOfCongress/api.congress.gov)：需 key、分页；法案/提名等集合，具体字段与时滞按实际响应验收。
- [参议院投票](https://www.senate.gov/legislative/votes_new.htm)、[听证日程](https://www.senate.gov/committees/committee_hearings.htm)、[Executive Calendar](https://www.senate.gov/legislative/exec_calendar_page.htm)：分别消费实际投票、安排和待全院审议事项。
- [Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1)：无 key；正式法律版原件通过对应 GovInfo PDF 留存。

## 5. 数据拥有者、存储与消费契约（目标契约，实施差异见 §9）

遵循 [pipeline](panel-data-pipeline.md)、[cadence](panel-data-cadence.md)、[resource](panel-resource-contract.md)、[lifecycle](panel-runtime-lifecycle.md)。本节命名为拟定，不声称对应表和 API 已存在。

| 领域 owner | 消费面板 | 生产与共享边界 |
| --- | --- | --- |
| `politics/elections` | P1/P2/P3/P4/P6 | 选举、民调、计票、代表票、席位及政治实体；复用研究解析与原始历史，不复制历史数据包 |
| `politics/campaign-finance` | P5；P1/P3/P4摘要 | 一份 FEC 候选人/委员会/申报读取与修订链；慢来源不会阻塞计票 |
| `politics/government` | P6/P7/P9/P10 | 一份 Congress/参院/委员会采集、法案/提名/拨款事件；国家适配按规则明确分开 |
| 既有 `official-disclosures` | P7监管/P8 | 保留现有来源与快照身份；FR 分页/正文/签署补充归原 owner，其他领域只消费 |

每个前端目录拥有 UI/model/resource/必要测试/README；共用模型与图表进入 `panels/shared/politics/`，不能互相 import 兄弟 Panel 实现。P7 保持现有 ID。后端沿用 services、runtime_panels/modules 和现有 watcher 组织；owner 数不强制等于 worker 数，一个慢来源不能占住全部来源。

**身份与存储：**

- 以配置后的 `POLYDATA_SNAPSHOT_SQLITE_PATH` 为同一快照持久层；新增拟用 `snapshot:politics:<owner> / <version + normalized parameters>`，来源状态为 `source:politics:<owner>`。P7已有 `snapshot:official-disclosures / policy-progress` 兼容保留，不能覆盖成另一语义。
- 需要历史的新增政治数据在相同数据根的领域 SQLite `politics.sqlite3` 存储：原始响应/文件版本、规范实体、事实观察/事件、市场映射、游标/采集状态。FR原件继续沿用已有 `official_disclosures.sqlite3`，通过来源原生ID引用，不复制另一个FR缓存。
- 原始内容按来源、原生ID、版本/内容摘要去重；JSON压缩存储，PDF保留下载校验和、MIME与原URL。历史研究文件只读复用。
- 初始容量预算 2 GiB；正式事件/映射/引用中的原件不能为腾空间静默删除。未引用轮询原件先执行已声明90天策略；达到预算时显式报容量阻塞并调整容量/归档方案，不能继续发布伪成功。关键事件与被引用版本保留整个事件生命周期及至少一年，后续按研究要求调整。
- `publishedAt / observedAt / receivedAt / availableAt / revision` 分开。日级日期不得补造成精确发布时间；事后拉取不能冒充选前可得。
- 当前态以可靠的来源版本/事件排序发布，旧采集任务不得覆盖新结果。计票可向下更正，不能用数值单调递增作为正确性条件。关键状态遇到来源明确撤销要失效，不能无条件保留旧结论。

**读取：** 拟用参数化只读 `/wm-api/runtime/politics/<domain>`，明确 country、jurisdiction、election/legislature、office、race/bill/nomination ID、period、limit、view、schemaVersion；只有实现了历史查询才接受 `asOf/revision`。公共 Runtime 对完整资源 key 去重、取消和缓存；API GET/刷新不触发上游。选举/席位等视图复用相同域记录，关闭 P1 不停止 P4 仍需要的数据。

跨面板使用小型显式选择契约，复用现有 Market 选择入口；只在确有联动需求时给 Panel context 增加政治实体选择，数据仍归 owner。未验证 Market 映射显示“尚未关联”，不强行匹配同名候选人。纯视图声明 `dataSourceId/dataDependencies`，有参数的视图用 `usePanelResource`；不得给同一资源同时注册两套 fetcher。

## 6. 四种时钟与预算（目标，不是当前运行参数）

| 来源组 | 来源节奏 | 默认采集尝试 | 浏览器读快照 | 无成功检查后的提醒 / 当前态最长保留 |
| --- | --- | --- | --- | --- |
| 民调 | 按发布，Decision Labs 导出有1h缓存 | 1h；机构补充按发布安排 | 10min | 3h提醒 / 24h后仅作已发布历史，不宣称当前覆盖完整 |
| 提前票 | 多为日内或每日报告，按具体州记录 | 1h；只对确有更快发布的来源调整 | 10min | 3h检查异常；报告是否晚于预期发布另判 / 48h后历史展示 |
| 开票/代表票分配 | 活跃计票批次 | 确认计票窗口内60s；其他时间1h | 活跃60s；其他10min | 活跃3min提醒 / 15min后退出“当前领先”判断；旧票数进历史 |
| FEC 财务 | 申报/修订，非行情 | 6h | 30min | 18h提醒 / 72h后不宣称最新申报已覆盖；原财报仍是历史事实 |
| 议会/法案/提名/签署 | 随官方行动公布 | 常态30min；有正式活动窗口5min | 常态10min；活动5min | 3倍计划检查周期提醒 / 活动1h、常态48h后当前程序标待核验 |
| FR公告 | 发布批次及目标文件变化 | 保持30min，分页增量 | 10min | 沿用既有公告保留语义，原发布日期不续期 |
| 拨款/停摆 | 发布/议程/执行通知 | 常态30min；到期前48h或实际行动窗口5min | 5min；倒计时本地渲染 | 活动15min提醒 / 1h后状态待核验，不能仅凭本地时钟宣布停摆 |
| 规则、历史及已结束事件 | 静态或官方修订 | 初次/修订发现；规则每日检查 | 首次、手动 | 标记规则版本/历史范围，无伪实时轮询 |

提醒基于采集是否成功和来源预期节奏；没有新事件不等于旧法律事实失效，也不意味着采集已成功。浏览器隐藏暂停需求，后台正式采集按自身日程继续。

HTTP：先复用共享传输与当前授权出口。默认连接15s、读取45s，每次请求最多2次完整尝试，总任务硬期限120s；新请求/退避不得越过剩余期限。响应JSON上限8MiB，选中原文PDF上限20MiB；每owner最多2个在途请求，同host串行，来源配额更低时服从来源。429遵守Retry-After，不立即换出口；403/权限失败不能靠换源伪装授权。失败按5/10/20/30min退避；活跃计票来源可用60/120/300s，限同一事件窗口。正常不成功的来源只重试自己的键。

后台每轮锁去重、不重叠。列表每次最多5页/500条，游标落盘继续；启动回填、增量更新、精确目标刷新分开。达到边界明确覆盖不完整，未扫完不推进完成水位；不能重演FR只取前100且宣称全部。目标集合由已有活动Market映射和明确范围产生，先有覆盖清单，再并发抓取。

API：只读快照，单请求2s读取预算、最多200行/512KiB；历史详情分页。浏览器15s完整截止、最多一次重试，缓存身份与原始年龄重新校验，受现有2M字符公共总上限约束。文档PDF不塞进首屏、浏览器缓存或全量bootstrap。不额外增加全机PostgreSQL连接配额。

## 7. 实现顺序与全部缺口的完成门槛

1. **设计已交付，开发获批准**。本文件、可点击原型、原始尺寸/展开/手机截图核对10种内容和8类需求。设计样例不注册生产，不混入正式存储。
2. **实体与来源准入**。枚举已有活动政治Market，建立国家/选举/法案/人选与Rules映射。核对凭据只报告是否存在，不打印密钥；AP授权和每国/每州覆盖分别记录。缺某一授权只阻塞该分支，不阻塞公开来源。
3. **政府程序链**。扩展现有FR；接Congress/参院/机构文件，完成P7/P8/P9/P10，共用法案、提名、日程与证据。不将程序与文档发布日期混合。
4. **选举链**。复用历史及Decision Labs解析；接当届民调、选区/候选人、提前票、实际计票、代表票，完成P1/P2/P3/P4；竞选资金P5独立慢周期。
5. **控制权与跨国覆盖**。P6消费已核实席位和逐国程序；为当前实际Market涉及的国家补来源。司法事项、广告证据及复杂地区数据保留明确工作项，不能用新闻摘要冒充已补齐。
6. **模型能力**。历史误差、民调聚合、剩余票推算、席位分布分别定义模型与数据分母，具备留出验证后才显示，原始事实视图不等待模型也能使用。
7. **发布验收**。按现有授权与迁移后的真实部署目标交付，先核实环境，不恢复停止的旧GCP服务。新增默认合并旧本地/账号布局；生产桌面五列、手机单列，从普通首页验证并保留显式隐藏。

每项完成都需：真实响应字段→有效解析→正式存储→同身份API→Panel；按适用周期观察自动执行、失败保留及恢复。短周期至少两次自动执行，长周期如未完整观察必须明确写出。当前无选举事件时可验证官方历史回放与代码，但不能声称已验收真实选举夜实时链路。

关键用例：支持率≠胜率；缺未决定字段；早票分母更改；县级更正票数；两家来源冲突；媒体call与认证不同；退选后代表票保留；重划选区；修订申报去重；无多数但组阁；两院不同文本；程序票≠最终确认；部分CR覆盖；到期但无停摆通知；数据获取中断与已发生法律事实的区别；共享消费者退出与旧请求晚到。

完成清单以“所有目标Market的预期对象/已映射对象/实际来源覆盖/待授权/缺字段/历史缺口”报告，不只统计HTTP 200或非空行数。不能保证来源未发布、未授权或不存在的数据自动变为可得。

## 8. 设计产物与当前验证

- 原型：[入口](../webpage/design-previews/politics/index.html)、[视图](../webpage/design-previews/politics/preview.tsx)、[正文样式](../webpage/design-previews/politics/preview.css)。由现有Vite启动后访问 `/design-previews/politics/`。
- 截图与验证范围见[设计预览说明](../webpage/design-previews/politics/README.md)。原型截图只验收设计行为，不作为生产或持续更新验收。

## 9. 公开来源版本实施记录（2026-11-06）

用户确认当前没有 AP / Congress.gov / OpenFEC 密钥，先接公开来源。以下是真实响应及落库结果，不含原型样例。新增九个模块默认启用，`policy-progress` 保留原 ID，增加法案页签。模块目录各自拥有 UI、model、resource、README；共享正文原语在 `panels/shared/politics/`。共享布局协调把新 ID 追加到旧本地/账号布局；后续显式隐藏继续生效。

### 实际来源与范围

| Panel | 已实现的公开链路 | 首轮真实覆盖 | 尚未实现，不能混为已有能力 |
| --- | --- | --- | --- |
| Election Watch | Decision Labs 导出 + NCSBE 分区结果文件 | 导出426条调查，API展示最近200条；北卡2026大选15场联邦职位统计 | 最新调查日期仍在6月，不能称当前民调；无全美实时开票、剩余票估计、认证/司法事件、历史误差模型 |
| Early Vote | NCSBE outstanding absentee ZIP | 北卡100县，寄出/接受/收到未计/未完成/因现场投票作废 | 仅北卡邮寄票；非全美，非现场提前票总数，没有可比历史曲线；原文件选举日期不是报告发布时间 |
| Nomination Path | NCSBE 2026-03-03 primary precinct ZIP | 21场联邦职位初选统计 | 不是总统代表票。党规门槛、代表票、背书/退选、正式提名仍缺，不由最多票推断提名 |
| Seat Balance | House Clerk MemberData XML | 435个有表决权席位；排除6名无表决权代表，包含 AQ 原生代码 | 现任119届，不是2026大选新一届结果；缺选区边界修订、重计票与认证 |
| Campaign Finance | FEC weball26 ZIP | 4,368个候选人财务汇总，API按筹款排序展示前200 | 报告截至日期不同；委员会间转入/转出独立展示。缺逐笔独立支出和申报修订链，归档文件版本不能冒充申报修订 |
| Government Control | 复用 House Clerk 名册 | 官方标记的现任多数党与党派席位 | 未覆盖全球组阁、议长实际投票、党团变化事件和跨国联盟；不套议会制模板 |
| Policy Progress | GovInfo BILLS RSS → BILLSTATUS XML；保留原 FR 公告 | 近期发布及明确观察清单；每轮最多5份法案详情，滚动继续 | 不是全量国会覆盖；未接单独听证、修正案文本、全院逐名票明细与全部同文核验 |
| Executive Actions | 既有 official-disclosures owner → FR总统文件查询 | 最近90天70份总统文件，类型/EO编号/签署/公布/生效字段 | 空生效日不等于立即生效；没有完整法院暂停、撤销或条款效力追踪。原文保留正式链接与元数据，尚未下载全部PDF正文 |
| Appointments | 白宫公开提名 RSS及内嵌正文 | 30批正式提交/撤回公告 | 公告不是确认，不能识别为已任职；参院公开XML实测403，PN子编号、听证与确认票尚未接入 |
| Funding Deadline | GovInfo P.L.119-103 第101/106条 + H.R.6500状态 | FY2027所跟踪法律的12类范围、原文最晚日期2026-12-11、程序记录 | 法律仅日期，未虚构精确时刻/倒计时；仍须核验后续法律及逐机构覆盖、OMB实际停摆/恢复通知。不宣称当前全部政府资金状态 |

来源实测补充：[FEC字段定义](https://www.fec.gov/campaign-finance-data/all-candidates-file-description/)、[NCSBE邮寄票口径](https://www.ncsbe.gov/results-data/absentee-and-provisional-data)、[NCSBE分区统计限制](https://www.ncsbe.gov/results-data/election-results/historical-election-results-data)、[GovInfo批量发布](https://www.govinfo.gov/bulkdata/)、[P.L.119-103原文](https://www.govinfo.gov/content/pkg/PLAW-119publ103/html/PLAW-119publ103.htm)。FEC官方地址会302到其GovCloud桶，传输仅允许实测匹配的HTTPS桶与相同文件路径；不允许任意重定向。北卡NUL空党派字段按来源编码处理，其他嵌入NUL拒绝。

### 实际存储、API与时钟

- 后端 `api/services/politics/`：catalog、严格规范化、独立 owner 采集、版本归档、只读投影。现有 SQLite SnapshotStore 的 `source:politics:v1/<原生来源+届次/日期>` 保存最后成功数据、尝试/成功/下次到期时钟、错误类别、内容版本。与设计中拟用多namespace相比，当前统一namespace并把作用域放进key；没有第二套浏览器fetch队列。
- 同数据根的 `politics.sqlite3/evidence` 按 `(source,revision)` 去重，压缩保存原始字节和规范结果及首次/最近实际取得时刻；先归档成功再发布快照。当前保守保留全部已归档版本，2GiB容量阻塞保护；没有实现自动90天删除、完整事件查询表或市场映射表。不能把定时重取当成来源发布新版本。
- Federal Register仍只有 `official-disclosures` 一个owner，`source:official-disclosures/federal-register:presidential` 保存新增总统文件投影，原件元数据进入既有 `official_disclosures.sqlite3`。总统文件最多5页/500条，真实本轮70/70；超上限标记 truncated，不声称已完成游标续扫。原监管页仍明确最近30天100条限制。
- `/runtime/politics/{election,early-vote,nomination,seats,campaign-finance,government,executive,appointments,funding,legislation}` 全部只读，无HTTP上游访问。公开前缀为 `/wm-api`。P7继续 `/runtime/disclosures/policy-progress`，附带只读 legislation 投影。API按来源重新计算过期，不把GET时间变为成功时间。
- 政治采集使用共享来源传输：单次45秒、至多两次、每个来源120秒总预算（FEC允许的GovCloud重定向共用预算）、8 MiB响应上限。读取完整响应失败亦在有限重试内；429/401/403不轮换出口重复请求。GovInfo BILLSTATUS的404按1/2/4/6小时持久退避，仍保留目标身份、旧成功数据和原成功时间。每轮最多五个详情请求及既有owner锁不变。
- 法案索引分别记录近期目标 `targetIds` 和历史尝试身份 `ids`；API的 `acquiredCount` 只计当前目标中真实取得的详情，公开失败数/待取得数与各来源的下次尝试时间。`generatedAt` 只取实际成功时间，尝试时间另列 `lastAttemptAt`；有失败、过期或尚未取得的依赖返回degraded，无可用依赖返回unavailable。拨款投影仅把拨款相关详情/明确拨款目标当作依赖，不因无关决议404而降级；法案总览继续如实显示该失败。
- 法案详情沿用每5分钟检查、每轮最多5项和最短30分钟重取，API声明的实际期望轮转为 `max(1800, ceil(targetCount/5)*300)` 秒，过期阈值为该轮转的三倍，复用政治领域“三个采集周期”规则。101个目标对应105分钟期望轮转、315分钟过期阈值；这不改变请求频率或并发。来源错误仍立即显示，失败的Retry-After/404退避不延长新鲜度，超过三轮仍标stale；API同时返回 `expectedIntervalSeconds/staleAfterSeconds`，不能再把所有详情统一承诺为90分钟内必刷新。
- 普通列表最多200；**435席位索引是明确例外**，每项仅成员身份/党派/链接，单响应仍限制512KiB。法案详情最多40份、每份60个行动；界面注明有限观察范围。当前不接受虚假的 asOf/revision 查询参数，也不声称已建立自动 Market Rules 映射。
- 定时模板 `polydata-politics@.timer/service`：三个owner实例 elections / campaign-finance / government，每5分钟检查到期；民调/北卡大选邮寄与票数1h、已结束初选每日、FEC6h、成员名册/白宫/GovInfo30min、所跟踪法律每日。还没有启用选举夜60s或自动活动窗口。
- 浏览器公共Runtime：普通面板10min、资金30min、拨款5min；15s请求截止、最多1次重试。刷新仅重新读正式数据。数据源失败保留最后成功值与原时间，不清空；401/403不换出口绕过，429遵守Retry-After。
- 浏览器请求状态与业务空结果分开：首次请求未取得有效快照时，公共 Shell 只显示加载或请求失败，不进入“暂无初选统计／尚无提名公告”等业务分支。已取得快照后请求失败，由公共 Runtime 保留原值并提示更新失败；成功返回的空列表则正常替换旧列表。此规则覆盖九个独立政治面板；没有新增 fetch、缓存或重试拥有者。
- 新鲜度与浏览器轮询独立，公共契约 `shared/politics/resource.ts` 同时提供 Runtime 过期阈值和持久缓存写入有效期。政治 owner 按三个采集周期提醒；总统文件沿用公告 owner 的24h窗口。浏览器只以 `sources[].lastSuccessAt` 的最新成功时刻作为整体快照时间，失败尝试、API读取及投影 `generatedAt` 均不能续期。各来源自己的 `stale/error` 继续独立展示，整体最新成功不能掩盖其他来源失败。

| 面板/来源 | 采集检查周期 | 浏览器只读轮询 | 过期提醒及缓存写入有效期 |
| --- | --- | --- | --- |
| Election / Early Vote | 1h | 10min | 3h |
| Nomination / 已结束初选 | 24h | 10min | 72h |
| Campaign Finance / FEC | 6h | 30min | 18h |
| Seats / Government / Appointments | 30min | 10min | 90min |
| Funding 的法案动态 | 30min | 5min | 90min；固定法律仍由来源元数据按24h采集、72h提醒 |
| Executive / 复用总统文件 owner | 30min | 10min | 24h，沿用公告 owner 的现行规则 |

此前所有面板1h过期、缓存只允许10min内快照的设置废止。缓存身份仍为 `politics:<panel-id>:v1`，每份220,000字符、公共总预算32份/2,000,000字符不变。已存快照最多保留7天供故障恢复，超过上述有效期标记过期；7天不是新鲜保证。缺少成功时间不能用当前时间补造。以后修改采集周期时，必须同时更新来源、此矩阵和契约测试。
- 新来源默认直连，主Clash不变。单请求连接15s/读取45s，最多2次尝试、总120s；8MiB响应及32MiB ZIP解压上限，每owner串行，独立owner互不阻塞。法案队列保留尝试游标和失败退避。
- 配置见 `deploy/systemd/politics.env.example`。AP/Congress/OpenFEC变量名已保留；**本版没有声称填入密钥即完成授权适配和字段验收**。取得密钥后仍需按对应账户能力接入、实测，公开源保持可用。

### 验证与发布

本地已用实际数据逐个运行九个前端模型验证器；后端23个针对性及注册/公告回归测试、前端9个契约/旧布局测试通过，TypeScript、前端边界及语言检查通过。全仓systemd检查仍报另一个任务的未跟踪 `polymonitor-tencent-egress.service` 缺两项journal设置，本任务未改该文件。

前端发布提交为 `b23829e0f439148ee03e6e3bea3c327f9e4a7a8b`：推送 main 后，用该提交的 `git archive` 干净导出及 Node 22.23.3 构建；发布到迁移后的腾讯云 `/var/www/polydata`，两个公网域名的 `/release-sha` 均返回同一身份。临时构建和上传目录已删除。后端为本机 `~/.local/share/polymonitor/backend`，使用上述提交的本任务文件；原有 readiness 修复保留，因此没有声称整个后端目录等同该提交。未恢复 GCP 服务。

普通首页在已有本地布局下已验证：原来的 Crypto、Policy Progress、Company Events 顺序与单格尺寸保留，九个新 ID 自动追加；新增面板随后被明确隐藏，重载后仍隐藏。2518px、1440px 桌面均为五列，九个新面板读取真实 API 后进入 ready。还检查了不预设布局的普通首页。未登录账号做生产验收，因此账号布局只完成公共协调机制的单元测试，不能声称已实测某个账号。

三个 `polymonitor-backend-politics@{elections,campaign-finance,government}.timer` 已启用，11:15、11:20、11:25、11:30、11:35（北京时间）等自动检查记录可查。正式归档证明11:30名册、11:35提名公告再次成功读取，法案详情在多个周期持续写入；11:36时归档有49个来源身份/内容版本。五分钟是到期检查周期，跳过未到期来源不等于刷新成功。补正日志以 `not-due` 区分跳过；FEC六小时、已结束初选/固定法律每日周期尚未观察满，不能宣布长期连续更新验收完成。

浏览器核验经过既有腾讯出口，未更改主 Clash，没有替换生产 API 或地图瓦片。不带 `www` 的入口曾因脚本下载 `ERR_NETWORK_CHANGED` 空白，重试后成功；这是本轮实测网络限制，不能由成功重试推导网络故障已消除。生产截图和手机交互结果见[生产验收记录](../webpage/design-previews/politics/production/README.md)。设计目录其他样例图仍是虚构原型，不能当作正式数据。

11:45自动轮次中，民调导出和GovInfo列表再次成功；总统文件、监管列表与北卡邮寄票请求超时，正式存储继续保留旧数据、原成功时间和退避状态。随后直连只读探测能成功，但不将探测写成正式恢复；腾讯出口对这两个来源反而连接超时，因此保留直连。当前交付是公开来源面板及采集/归档/重试机制，不是所有来源已连续正常的结论。

### 请求状态与采集周期修正验收（2026-11-06）

前端29项针对性单元测试、6项浏览器用例通过；类型、语言与边界检查通过。浏览器覆盖初选、行政文件、任命、拨款的首次503、重试恢复、再次失败保留；另验证成功空列表替换旧列表，以及FEC 5h、历史初选23h的正常展示与重载缓存恢复。生产是否生效需另核对实际版本与桌面/手机页面；上述故障注入仅用于本地测试，不替换生产API。全仓 `make quality` 因本机缺少开发 `.venv` 无法启动，不记为通过。

生产前端提交 `dd2a700899e64f077be01ed219285d7b58b394ea` 已从干净的提交导出构建，并发布到迁移后的腾讯静态站点；两个域名的 `release-sha` 均匹配。2026-11-06 16:33（北京时间）真实 www 首页桌面2518px逐个读取九个政治面板，均为 ready、有实际内容；手机390px核验初选、FEC、行政文件、任命、拨款五个面板，均为 ready，无横向溢出。截图保存在本地 `webpage/artifacts/politics-data-state/`；没有替换生产API或瓦片。生产瞬时核验不能代替完整6h/24h采集周期的持续验收；本次未修改后端采集周期、数据源或代理。

## 10. 四项证据字段扩展（2026-11-07）

这是已有政治 owner 的增量契约；末尾的首次采集记录只证明当次观察。没有新增 Panel、worker、浏览器轮询或缓存。三个 owner、五分钟到期检查、各领域公共 GET 和默认布局保持原入口。

| 消费者 | 新来源及归档 identity | 字段与真实覆盖 | 不能据此成立的推论 |
| --- | --- | --- | --- |
| Election Watch | NCSBE 官方选后程序公告；`nc-certification-20261103` | 2026-11-03 NC 联邦选举的州级 canvass 预定 11-24 11:00 America/New_York，`certifications[].status=pending`，有官方证据链接 | 票数不是认证；到了预定时间只转为 `outcome-unverified`，不能自动标 certified。后续认证决定、重计票和法院事项仍需新官方证据 |
| Nomination Path | DNC 官方 2024 全国虚拟 roll-call 结果；`dnc-roll-call-2024` | `delegateContests` 单独标历史、全国、2024、DEM、实际代表票及口径。2026 NC congressional primary 明确 `delegateApplicability=not-applicable-congressional-primary` | 不把历史党代会移植到当前初选；不由普通选票推算代表票。该结果页没有数值门槛、未分配票或机器可读逐州全表，保持未知 |
| Campaign Finance | FEC 当届 24/48 小时独立支出 CSV；`fec-independent-{cycle}` | 支持/反对、spender、candidate、金额、支出/传播/接收日期、filing/transaction ID、AMN_IND、PREV_FILE_NUM。按同一申报家族保留最新整份申报，保存修订关系及前序是否存在 | 原报告与修订不重复相加；通知不是全部周期报告；不输出误导的全局金额总和。候选人 weball 财务汇总与独立通知修订分开 |
| Appointments | US Courts 确认名单 `judicial-confirmations`；GovInfo CHRG RSS `nomination-hearings` → `hearing:{packageId}` MODS | 司法职位的真实提交/确认日期；近期已出版提名听证的原生 package、届次、heldDate、委员会与证人。确认、听证和白宫提交各自保留源时钟 | 法院名单不是全行政任命；确认不是就任；GovInfo 出版/收录时间不是听证日；不按姓名猜 PN 关联；未来议程、逐名票仍不可用 |

### 获取、存储与读取

- 来源入口只由 `.env` / `data_sources.source_value` 注入：`POLYMONITOR_POLITICS_NC_CERTIFICATION_URL`、`POLYMONITOR_POLITICS_DNC_ROLL_CALL_URL`、`POLYMONITOR_POLITICS_FEC_IE_URL_TEMPLATE`（仅 `{cycle}` 替换）、`POLYMONITOR_POLITICS_JUDICIAL_CONFIRMATIONS_URL`、`POLYMONITOR_POLITICS_HEARINGS_FEED_URL`。示例配置不写真实值；沿用统一 loader 与已授权显式来源路由。AP / Congress / OpenFEC 可选凭据能力保留，本次不需要它们。
- `politics/collector.py` 仍持有 `owner:politics / elections|campaign-finance|government` 跨进程锁。完整请求45秒、最多两次尝试；含官方 FEC 重定向的单来源120秒上限。owner 总预算900秒，低于既有 unit 1200秒；剩余不足完整45秒时 defer，未开始的来源不推进尝试/成功时钟。
- 默认响应8 MiB，仅 FEC IE 经真实大小核验允许32 MiB。GovInfo 详情只允许 RSS 返回的同发布者 HTTPS `/metadata/pkg/{原生ID}/mods.xml`，每轮最多三件，不按网页请求触发。403不换出口规避，429继续原退避。缺配置明确失败并隔离其他来源。
- 沿用 SQLite `panel_snapshots / source:politics:v1 / sourceId` 保存当前解析与独立 lastAttempt/lastSuccess/nextAttempt；同目录 `politics.sqlite3 / evidence` 以原始SHA256归档原文、解析、首次/最近接收时间，容量上限2 GiB。先确认原文归档和 source state 写入，再返回成功。网页GET只读，禁止取源和写回。
- FEC完整CSV全部归档；业务源保存最新200条可展示通知和200条修订，API最多各100，保留原文件、当前可展示、修订排除、方向未知隔离及修订分母。缺方向不补成支持/反对，不将整源判空；来源元数据与面板保留 `partial/degraded`。
- NC公告每小时，DNC已结束党代会每天，FEC IE六小时，法院名单三十分钟，CHRG出版目录一小时、已出版详情每天；浏览器仍 Election/Nomination/Appointments十分钟、Finance三十分钟。源 stale 提醒沿用三倍对应周期；没有把历史事件日期续成“今天发生”。
- 资源key、schemaVersion 1保持兼容，新增字段为可选扩展；公共Runtime复用原来源成功时钟、7天有界浏览器恢复、220,000字符每资源上限。失败保留原值/原时钟；首次失败无成功时间；合法空通知/目录替换旧列表；坏schema不覆盖最后成功。
- 只读API沿用 `/runtime/politics/election`、`/nomination`、`/campaign-finance`、`/appointments`；各来源隔离，没有把某一部分成功当其他部分成功。

### 首次真实采集与验收边界

2026-11-07 UTC 08:03–08:05，限定五个新增source与三份听证详情，在既有owner锁下完成正式SQLite首次写入和evidence归档；没有重采旧源或另启常驻进程：

- NC一项pending州级canvass；DNC一项明确为历史的2024全国roll-call，Harris 4,567代表票。
- FEC 51,082原始行、10,012申报，整份被后续修订排除4,209行；当前可展示46,864行，9条当前通知方向未知（原文件共12条）；696个修订申报。API各展示最近100条通知/修订并保留分母。该源为partial。
- 法院名单57条司法确认，名单更新日2026-11-06，最新实际确认日2026-09-23。GovInfo最近100件出版物里有3件提名听证，2件119届、1件118届历史；三份MODS取得真实heldDate，未用出版时间替代事件时间。
- 正式SQLite的四份新投影通过前端各模块模型；响应约97/9/130/68 KB，低于公共持久缓存预算。后端针对性回归29项通过；前端政治契约、TypeScript、语言及边界检查随最终任务继续核验。
- Senate主站XML/HTML、Judiciary公开页本轮直连403，未换出口规避。US Courts/GovInfo成功不是Senate访问恢复。
- **首次采集使用工作区新代码，不能据此声称后端代码已安装、生产API已加载、前端已发布或真实UI已验收。** 一次成功也不是完整六小时/每日自动周期的连续成功证明。

### 安装与公网消费复核（2026-11-07）

后续已按变更前哈希核对，将四个本任务后端文件安装至既有 backend；`store.py` 未改。真实公网首页已展示待认证日程、明确标为历史的代表票、独立支出及修订、司法确认与已出版听证，没有替换 API 或瓦片。桌面与390px手机截图在 `webpage/design-previews/politics/production-*-20261107.png`；版本与完整任务验收分别记录，首次写入本身仍不能替代这些检查。

16:43:51（北京时间）四条公网政治 API 均返回真实字段。13项来源引用均可用、未过期且无采集错误；FEC IE仍为partial，保留9条方向未知，未改成零或任意党派。NC认证仍pending、`certifiedAt=null`；当前国会初选仍N/A；听证仍按真实heldDate标注历史。正式定时器已将法院确认源推进至16:35:16，而不在读取API时更新时间；FEC六小时与DNC每日完整周期尚未到期，未宣称跨周期连续验收。

17:00:56 的前端正式版本为 `b4d321fef2f937bd7a223bf2ec169ae4bc735624`。用真实 Chrome、继承的浏览器出口，在普通首页分别等待六个新页签的数据后截图：Certification、Delegates、Independent、Amendments、Judicial confirmations、Hearings；没有拦截或替换API/瓦片。390px手机页面宽390、各政治面板宽382，无横向溢出，无脚本错误；桌面为2560×1440。未来听证仍明确unavailable，历史听证日期与司法确认日期可读，FEC的partial仍显示DEGRADED。相邻非本任务面板的已有stale/degraded状态未掩盖，也不据此宣称全站健康。

最终 `e806a43dd66eeab4c587073257d78fd149780db4` 进一步让历史代表票复用 `partyTone`，避免给民主党候选人使用紫色。两域名版本一致；生产代表票DOM为 `pol-blue`，实际颜色 `rgb(100, 164, 255)`。桌面/手机截图已更新，390px仍无溢出，无脚本错误；其余字段与数据链路不变。
