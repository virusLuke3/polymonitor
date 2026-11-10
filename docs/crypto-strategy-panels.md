# 加密策略 Panel 首版实现

沿用 `document/开发/Panel开发统一指南.md`：一个 Panel 一个前端目录，保留现有 Panel 外壳、等宽字体、紧凑指标、表格和详情折叠；后端按数据领域共享拥有者。此次共八个入口，四个既有入口升级、四个新增，不创建新主题或额外行情大屏。

## 范围与策略

| Panel | 策略依据 | 本次实现 | 尚未覆盖 |
|---|---|---|---|
| `crypto-watch` 加密同步行情 | Q046 / Q073 / G071；O089–O091；O093 / Q077 / G075 | 保留全币种概览；共享币种的现货、PM 同轴观测和相对收益。 | 未计算领先时长、择时信号或模型概率。PM 图仅绘制通过现有盘口拥有者校验的实际观测。 |
| `crypto-order-flow` 订单流 | C080 | Bybit 最近最多 60 笔现货主动买卖、样本 CVD、50 档快照失衡及前 10 档详情。 | 不是完整时间区间流量；增量 OFI、多交易所确认尚未实现。 |
| `crypto-funding-watch` 资金费率 | C079 | 保留原有双交易所费率、真实结算周期和覆盖；增加共享币种最近最多 100 次 Bybit 已结算费率及样本分位。 | 历史未补齐长期窗口；样本分位不能称为长期极端程度。 |
| `crypto-perp-funding` 持仓与基差 | C078 / C079 | 永续 OI 数量及名义金额、5 分钟 OI 序列、15m/1h/4h 变化、mark/spot 与 mark/index bps。 | REST 跨响应基差超过 5 秒时间差不计算；未实现完整期限结构、清算和跨所 OI。 |
| `crypto-oracle-reference` 合约指定源 | O043 / C081 / G072 / C082 | 通过 market-data 现有只读入口直接投影 canonical 合约、原始 60 秒官方 TWAP、开盘阈值和 E18；验证币种、窗口、比较符、期限、token 和阈值归属。 | 指定源过期就禁用当前距离；开盘展示值保留精度标签。原始窗口贡献和剩余窗口概率未实现；四币种均沿原 owner 获取指定源及当轮绑定，实际可用性由逐币种观测/anchor 决定。 |
| `options-implied-probability` 期权隐含概率 | O041 / C075 / Q074 / G077 | BTC/ETH、未来七天中最多三个到期、真实双边报价支持的看涨价差概率带与买卖区间。 | 折现因子假设为 1；是阈值带平均风险中性尾概率参考，不是精确数字期权概率。未与 PM 到期匹配，不给 PM 概率差或交易结论。 |
| `crypto-exchange-inflow` 交易所链上流入 | Q076 | 复用现有 Dune BTC 历史研究归档，按日期与 Binance/Coinbase 聚合转入、转出、净额；30/90/180 日历天。 | 实时来源未接入；标签为事后获取，严格 PIT 未验收；转入不是卖出，未识别内部转账仍可能存在。 |
| `stablecoin-monitor` 稳定币压力 | Q079 | USDC/USDT 的 Coinbase 与 Kraken USD 报价、偏离 bps、来源差异和观测持续时间。 | 连续采样缺口重置持续时间；无原生报价时间时明确为接收时间。不是完整压力事件档案。 |

## 数据与模块边界

### 历史与期权请求恢复

参考 `polymarket-crypto-options/scripts/deribit/download.py`、`scripts/common/http.py`
和 `scripts/deribit/snapshot_recorder.py`：慢来源给予完整的 45 秒连接／读取超时，
最多四次尝试，重试等待 1、2、4 秒；成功数据持久化，失败不清空最后成功值。
继续复用本领域 worker、公共 HTTP Session、已授权的来源路由与 SQLite，
不新建采集服务，不改变 LOB、Clash 或研究项目的下载任务。

- 范围：Bybit BTC/ETH/SOL/XRP 的分钟 K 线、5 分钟 OI 和资金费率历史；
  Deribit BTC/ETH 的当前期权合约及报价。成功周期仍为 1/5/15/5 分钟。
- 单来源请求最多四次、最多切换一次已授权出口；每次获得完整预算，
  不将 12 秒平分。429 遵守 Retry-After，403/404 不换出口或立即重试。
  响应仍限制 8 MB，六个采集线程，不启动重叠轮次。整轮 90 秒后不再启动请求或重试；
  已进行中的连接／读取仍受本次 I/O 超时限制，不承诺 DNS 与流式读取的严格墙钟上限。
- 失败重采按 60、120、最多 300 秒退避，且不超过正常来源周期。
  `source_cache` 表与展示 `snapshot` 共用 `crypto_strategy.sqlite3`，
  key 包含来源 URL、币种和数据类型，保存最后尝试／成功、下次尝试及具体错误。
  发布快照与缓存状态在同一事务提交，重启不重置成功时间或退避。
- 保留成功历史／期权最多 30 分钟；失败、等待重试和未采集分别表达。
  保留期间不改 K 线、报价或成功时间，期权已到期项仍删除；成功的空结果可替换旧值。
  有保留来源时共享快照为 stale，沿用现有延迟提示；逐来源原因与时钟保存在 sourceStates/sourceState。
  该表是有界恢复缓存，不是完整历史数据库。
- 研究档案仍归 `polymarket-crypto-options`：`/data/cryptOptions/data` 的 Tardis
  历史期权与 Binance 历史行情不冒充当前报价，也不替换 Bybit 交易所口径。
- 验收：完整响应／流式读取失败重试、429/403 边界、持久化重启、保留上限、
  空结果和到期过滤；正式 worker 连续自动采集、SQLite 原始时钟及公网 API 读取。

本次验收记录（2026-11-04，北京时间 18:37–18:54；只代表该观察窗口）：

- 当前写入者是本机用户服务 `polymonitor-backend-crypto-strategy-seed.service`，
  运行目录 `$HOME/.local/share/polymonitor/backend`，
  数据库为该目录下 `data/crypto_strategy.sqlite3`。六个任务相关后端文件经目标差异核对后部署；
  `source_cache` 有 19 个来源身份、约 233 KB JSON。18:38 的受控服务重启后，
  期权观测时间、最后成功时间和下次尝试时间保持一致，没有因重启提前采集。
- BTC/ETH/SOL/XRP 各有 179 条已收盘现货分钟 K 线、179 条永续分钟 K 线、
  100 条 OI、100 条资金费率历史。分钟历史和 OI 的来源成功时钟按各自周期前进；
  资金费率历史从 18:37:23 的首次采集，自动推进至 18:52:52 发起的成功轮次。
  已结算费率数值只有出现新结算时才变化，成功请求不代表产生了新结算记录。
- BTC/ETH 各三个有效到期日。首次期权观测约 18:37:27–29，随后自动更新至
  18:42:49、18:48:07、18:52:57；来源错误为空。五分钟是调度目标，
  实际观测间隔还受 30 秒 worker tick、请求耗时影响。
- 裸域与 www 的 `/wm-api/runtime/crypto/options` 均读到正式数据。
  前端提交 `2e54d5191d5e2afd56e1550973be851f7a91d1ee` 已从干净导出构建并发布到腾讯云；
  真实站点桌面 2518×1249、手机 390×844 验证了版本、报价、概率带与 ETH 切换，无横向溢出。
  手机首次加载发生网络切换错误，重试通过。截图已检查并清理。
  此提交只包含延迟提示与对应前端测试；后端文件部署身份独立核对，不归入该前端提交。
- 42 项后端测试、两项桌面／手机浏览器测试及前端构建通过。
  失败重试、保留上限和重启恢复有自动化覆盖；没有人为切断生产出口来制造故障，
  本次短窗口不能作为长期无失败证明。

前端共享资源 `webpage/src/panels/shared/crypto-strategy/resource.ts` 使用 `usePanelResource`，key 为 `crypto-strategy:four-assets:v1`，浏览器检查 30 秒，服务采集目标 30 秒，快照超过 120 秒标记 stale。多个消费者共享请求与取消；没有新建每 Panel 定时器。共享 BTC/ETH/SOL/XRP 选择仅影响这一组 Panel，不冒充主工作区的任意合约绑定。历史期权与资金费率保留自己的到期/结算时刻。

API 注册四个新增视图路径：`/runtime/crypto/order-flow`、`/runtime/crypto/oracle-reference`、`/runtime/crypto/options`、`/runtime/crypto/exchange-inflow`。订单流、期权、流入继续共享公共行情快照。合约指定源独立使用 `/runtime/crypto/oracle-reference` 与公共 Runtime 资源 `crypto-reference:market-data:v1`，5 秒刷新，15 秒观测时效；不依赖公共行情采集是否成功。响应必须匹配 schemaVersion、kind 和资产身份；嵌套序列、盘口、期权与流入记录也校验。

数据拥有者为 `scripts/api/services/crypto_strategy/`。`crypto_strategy_watcher.py` 是单写入者（文件锁），落盘到主 snapshot SQLite 相邻的 `crypto_strategy.sqlite3`，或由 `POLYDATA_CRYPTO_STRATEGY_DB` 指定。API 使用 SQLite `mode=ro`，GET 不采集、不建表。全周期异常保留旧快照与原始时间；单来源失败保留其他来源并标注缺失。观测保留七天；单序列响应最多 300 点；上游价格档案最多 900 点。该存储不是研究级长期原始归档。

公共源：Bybit 现货/USDT 永续行情、分钟收盘、5m OI、资金费率历史、60 笔现货成交与 50 档深度；Deribit BTC/ETH 期权元数据和双边报价；Coinbase/Kraken USD 稳定币价格。Bybit spot 与 perp 分别请求，基差只有时间差不超过五秒才计算。不能把快照深度失衡叫作增量 OFI。

指定源的数据拥有者是 `market-data`。实盘原始观测在 XUE 的 `/mnt/hdd22t/market-data/chainlink-twap-60/YYYY-MM-DD/twap.sqlite3`；读取应使用只读连接，保留 E18、来源身份、观察/发布/接收时钟，并排除冲突、重复和时钟异常。采集与 reader allowlist 覆盖 BTC/ETH/SOL/XRP；正式验收仍逐资产检查原始落盘与当轮 anchor。

合约源复用 market-data 现有 `market-data-lob-http.service` 的 `/crypto/reference` 只读投影：canonical PostgreSQL 提供当前 5 分钟合约与原始规则，原始 TWAP SQLite 提供四币种观测。数据当前物理位于 XUE，拥有者通过已有归档 SSH 访问执行有时限的只读查询；不启动工作台或复制原始库。GCP 复用已运行的 18861 数据读取通道。入口单次并发合并、1 秒缓存；API 失败退避 3 秒并保留已读观测及原始时间。

四币种共用原 `polydata-chainlink-twap.service`，每资产一个精确 symbol 过滤的 RTDS 连接，合计四连接，仍只写同一日分区 WAL/FULL SQLite；队列上限与断线退避沿原 owner。原采集入口将 asyncio 默认线程池限制为 8 个工作线程，容纳四个来源的 DNS 工作和串行写入，同时给主线程及 shutdown 留余量；不随主机 CPU 数增长到 32 并碰到原服务的 TasksMax=32。writer 仍逐项 await 提交，未增加并行写库者。扩资产时按上一份持久 status 的历史资产集恢复水位，新资产不扫描不存在的历史；旧资产缺水位仍继续原有历史恢复。status 的 `archive_assets` 随真实提交扩展，不能把订阅成功当作数据落盘。

指定源传输由原 owner 使用独立 `polydata-chainlink-twap-egress.service`：XUE 环回
SSH 转发经已授权 Tencent 到官方 WebSocket TLS 端点。新用途密钥只允许该官方
主机的 443 转发，没有 shell、PTY、agent 或 X11；私钥仅在 XUE，配置保存在私有
market-data `.env`，仓库例子留空。沿用已验证主机密钥，严格校验并以
`-F /dev/null` 排除其他 SSH 配置；TLS server name 与 HTTP Host 保留官方身份，
证书校验开启，重定向关闭响应后拒绝，忽略继承的代理变量。TCP/TLS/HTTP 101
握手合计 15 秒，期限不包含已建立 stream 的存续时间。SSH 保活 15 秒、连续
3 次失败退出，systemd 等待 15 秒重启；采集连接保留 1–30 秒退避及原持久缺口。
该转发不增加数据拥有者、归档或 API 缓存，不依赖 LOB relay、旧 GCP 专用隧道
或主 Clash；盘口读取仍沿用原 reader。

2026-11-07 08:28–08:30 UTC 的只读验收窗口：原 TWAP owner 自动重连恢复后，
BTC/ETH/SOL/XRP 均在正式日分区落盘，原 BTC/ETH 历史记录仍可读取。08:30 当轮四个
精确开盘观测（`1794040200000`）均经 canonical 合约绑定，由实际
`/runtime/crypto/oracle-reference` 读出，E18 与原库一致；每币种返回 300 个历史点与
UP/DOWN 盘口引用，原 reader 的健康和 BTC 盘口读取仍可用。08:25–08:30 有效逐秒
观测分别为 298/299/299/299，不能称为无缺口采集；08:30:21 XRP 延迟超过 15 秒时
API 如实为 stale，其余三币种为 ok，阈值仍保留原始时间。08:30:57 再次读取时，
四币种源时钟均已自动推进至 `1794040255000`，原库与实际 API 一致，年龄约 2.4 秒，
均恢复 ok；期间未重启 owner。未新增代理、密钥、隧道或采集服务，未更改 LOB 和主
Clash。此记录只证明该窗口的实际获取、持久化、绑定和消费；新连接的出口波动及
长期连续性仍须独立观察。

同日后续复核（08:43–08:50 UTC）覆盖上述成功窗口后的变化：四币种最后真实观测
停在 08:41:43（`1794040903000`），原库和 API 一致；08:45 与 08:50 当轮精确开盘
观测均缺失，API 保留原时钟并标 stale，未用旧价格补 anchor。当轮 canonical 合约
绑定仍正确，UP/DOWN 是已有盘口快照，`upstreamCompleteness=UNKNOWN`。
旧进程在 08:42:49 出现 `can't start new thread`；48 CPU 主机的默认线程池上限 32
与原 unit `TasksMax=32`（包含主线程）存在预算冲突，故障瞬时线程数没有留存。
08:48:10 仅将原 TWAP owner 的默认池限为 8 后重启一次，服务上限保持 32；
8 项回归通过，含 40 任务突发峰值、40 项 writer 顺序、关闭无死锁或残留线程。
安装源码 SHA-256 为 `75c307502b8f4d7d159f7aac96e1179ac4dd5fe31356c3b14b9c8957a9f61fad`。
08:50:30 新进程维持 6 线程、无自动重启或新线程异常，控制与重试记录可正常落盘；
四连接仍为 `ClientConnectorError`，实际退避 1/2/4/8/16/30 秒后保持 30 秒，未见
frame 解析错误。该轮真实价格写入尚未恢复，观测已滞后约 527 秒，不能用线程补丁、
服务 active 或此前成功截图宣称来源恢复。未改代理、路由、密钥、LOB 或主 Clash；
该时点剩余连接失败与长期连续性仍未验收。

同日 09:07–09:15 UTC 的正式恢复验收：进一步核对确认旧 HTTP 代理进程仍在，
但其依赖的本地 LOB SOCKS relay 没有监听，实际错误为该本地端点拒绝连接；不能
把 `ClientConnectorError` 类名归为泛化的远端波动。未修改或重启 LOB、原代理
或主 Clash，而按授权建立上述专属出口。09:07:52 原 TWAP owner 切换后四资产
恢复真实写入。09:08:34 仅 SIGKILL 专属 SSH，systemd 于 09:08:49 自动重启；
原 owner PID 不变，按 1/2/4/8/16 秒退避，于 09:09:07 四资产恢复，约 33 秒
不确定区间保留 `history_replayed=false`。09:10 四个精确 anchor 均取得。

09:13:51 仅原 owner 和专属 SSH 载入最终握手/重定向隔离补丁。源码 SHA-256
为 `dedde6e80b8837b490e083dd373522a6f55e5a8dda0acdfb9857fab448242448`。
18 项回归通过，覆盖八线程突发、writer 顺序/关闭、四资产身份与绑定、冷启动
水位、TLS/Host 参数、真实环回 HTTP 静默握手超时释放、未读 302 body 关闭且
无第二请求，以及正常 stream 超过握手期限仍可通信；ruff 通过。
09:15:13 实际 API 四资产均 `ok`，最新观测为 09:15:12，年龄约两秒；09:15
当轮合约、精确 anchor、E18 和原始接收纳秒均与正式 SQLite 逐项一致。原 reader
健康与 BTC 盘口读取仍为 200，每资产两个报价仍是 `snapshot/UNKNOWN`。
09:10–09:15 有效逐秒覆盖 BTC/ETH/SOL/XRP 分别为 288/289/287/289，包含部署
重启缺口，未补造缺秒或缺失 anchor；旧 BTC/ETH 归档仍保留。此窗口证明实际
获取、持久化、当轮绑定、消费及一次自动重连，不证明长期连续或完整逐秒覆盖。

同日 09:16:33 UTC（17:16:33 CST）公网消费者验收：普通 `www.polymonitor.club`
首页发布身份为 `e806a43dd66eeab4c587073257d78fd149780db4`；真实 API 四资产
均 `ok`，最新源时钟 09:16:31，年龄 2.272 秒，09:15 四个 anchor 均为
`EXACT_SOURCE_TIMESTAMP`。实际 SOL 与 XRP 视图显示 Reference、Price to beat、
Distance 和当轮合约链接，浏览器 `pageerrors=[]`；生产截图已由主验收流程检查。
盘口仍保留原 snapshot 来源时间与 `UNKNOWN` 完整性，此 UI 验收不扩展为实时
LOB 或全期连续采集证明。

开盘阈值仅取观察时间**恰好等于合约开始时间**的有效官方 TWAP，保留原始 E18；缺失就显示缺失，不用临近价格或上一轮代替。查询限定当天/前一天文件、每资产最多 901 条，图表最多 300 点；断流保留最后真实观测，长期停采超出两天不扫描整个档案。过期观测不能计算当前距离。

PM 报价复用同一个 market-data 拥有者的已提交盘口快照，核验 condition/token 归属并保留源事件时间。当前盘口只证明可读取快照，显示 `Book snapshot`，`upstreamCompleteness=UNKNOWN`；读取时间不是行情产生时间，不把它标为连续实时盘口，也不从这种快照制造 PM 历史。不开新 LOB 采集器。

旧 workbench `/snapshot` 和 SUN 28075 → GCP 28076 专用转发均不再参与本 Panel；已停用的专用转发保持停用。上游采集连接故障、原始库读取故障、观测过期、当轮规则/阈值缺失分别核验，不能用服务 active 状态代替原始数据时效。

链上历史导出工具 `scripts/runtime/export_crypto_flow_history.py` 只读已有归档的 manifest 和 transaction_flows，校验记录数，用 Decimal 按日聚合。生产仅需要约 44 KB 的派生 JSON，保留原 manifest hash、dataset ID、实际覆盖期与标签限制；不复制原始归档、不把历史标为 live。

## 部署与运行

当前公共行情写入者及数据库路径见上方“历史与期权请求恢复”；前端已迁移到腾讯云。以下为原 GCP 部署记录，不是当前默认安装步骤：当时公共行情由 `polydata-crypto-strategy-seed.service` 写入，已移除旧 28076 和重复盘口入口配置。API 安装 `deploy/systemd/polydata-api.service.d/70-crypto-reference.conf`，配置 `POLYDATA_CRYPTO_REFERENCE_READER_URL=http://127.0.0.1:18861`。源端配置见 market-data 的 `lob_v2/deploy/systemd/market-data-lob-http.service.d/30-crypto-reference.conf`，只增加已有 HTTP reader 的读库配置，不添加监听端口、采集器或专用转发。当时链上派生文件默认 `/opt/polyData/data/crypto_exchange_flow_history.json`。本次未更改合约指定源链路，也未重新验收其部署配置。

`polydata-crypto-reference-tunnel.service` 保留为旧部署记录，不再作为安装步骤。禁止为修复空 Panel 擅自启动已停用的工作台、下载网关或专用转发。

前端发布使用 main 上本任务提交的 `git archive` 干净导出，构建时传入 `POLYDATA_BUILD_SHA`，保留其他任务发布的 docs 资源。后端只发布核对过差异的任务文件与用户服务，发布前比对目标文件哈希，并保留部署期间所需的回滚能力。前后端分别核验实际发布身份；仅当两者确由同一提交构建时才记录为同一提交。真实站点桌面与手机截图作为 UI 验证，检查后清理临时文件。构建或测试通过不能替代生产数据覆盖验收。

## 显示规则

统一外壳、等宽字体和五列布局；业务数据保留语义颜色。价格与数量中性，涨跌/净主动买入/深度偏向保留符号并用红绿区分；参考序列用蓝色，历史范围、开盘阈值和数据缺口用琥珀色。流入流出、OI 和概率的颜色不代表投资好坏。稳定币按绝对脱锚幅度警示，不把高于一美元当成利好。

合约 Panel 分别检查指定源观测、观测时效、当轮合约和开盘阈值。旧观测可保留价格与原始时间，但不计算当前距离；当轮过期时同样禁用距离。未知读取原因不能推断成连接失败或尚未接入。不得展示例行 Check / Source 周期、PARTIAL 标签。

## 验证命令

```bash
python3 -m pytest -q tests/test_crypto_strategy_inputs.py tests/test_runtime_panel_registry.py
cd webpage
npx vitest run src/panels/shared/crypto-strategy/model.test.ts
POLYMONITOR_E2E_PORT=4198 npx playwright test e2e/crypto-strategy.spec.ts e2e/crypto-watch.spec.ts
npm run build
```

测试区分未知值和真实零、买卖方向与重复成交、交叉盘口、期权无效报价、合约/阈值归属、过期/未来时间、只读 API、数据结构和布局。UI 测试使用明确 fixture；生产验证必须使用真实 API，不拦截替换来源。

## 来源口径

- [Bybit recent trades](https://bybit-exchange.github.io/docs/v5/market/recent-trade)
- [Bybit open interest](https://bybit-exchange.github.io/docs/v5/market/open-interest)
- [Bybit order book](https://bybit-exchange.github.io/docs/v5/market/orderbook)
- [Deribit book summaries](https://docs.deribit.com/api-reference/market-data/public-get_book_summary_by_currency)

本首版提供可见、可核验的策略输入；完整领先滞后模型、增量 OFI、剩余 TWAP 窗口模型、精确到期概率匹配和实时链上流入仍需后续数据/模型工作，不得在验收中标为完成。


### 2026-11-04 外源任务隔离

同一 `crypto_strategy_watcher`、同一 `crypto_strategy.sqlite3`，快慢任务分开执行。
快任务每 30 秒检查，30 秒轮预算；先取现货/永续，再取成交/深度，不再让 K 线夹在两份报价之间。
慢任务池最多 3 个执行线程、6 个独立键，每键最多一个未完成任务；单任务 90 秒。
K 线/OI/资金费率历史/期权原采集间隔保持不变，45 秒单次尝试、最多 4 次受总期限约束。
慢任务完成后在下一次快循环合入，不能为等待期权阻塞快报价发布。
稳定币逐 `(asset, source)` 保存成功、失败、重试时间，失败最多保留 5 分钟原报价，不写入空价格覆盖成功值。
详见 [外源恢复验收](external-panel-recovery-2026-11-04.md)。

### 共享展示快照回连预算（2026-11-10）

四资产策略及历史视图共用的 `/runtime/crypto/order-flow` 大快照在既有HTTP层协商gzip，先压缩再经腾讯云回连；公共Runtime总期限45秒、完整网络响应35秒。它不改变30秒/手动历史刷新周期、120秒fresh、900秒展示保留，以及逐来源和合约资格规则。Contract Reference仍用独立12秒总期限/10秒网络期限，LOB保持原规则。逐层证据与其他Panel参数见 [全量缓存核验](panel-cache-loading-audit-2026-11-10.md)。
