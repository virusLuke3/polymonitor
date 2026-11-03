# 加密策略 Panel 首版实现

沿用 `document/开发/Panel开发统一指南.md`：一个 Panel 一个前端目录，保留现有 Panel 外壳、等宽字体、紧凑指标、表格和详情折叠；后端按数据领域共享拥有者。此次共八个入口，四个既有入口升级、四个新增，不创建新主题或额外行情大屏。

## 范围与策略

| Panel | 策略依据 | 本次实现 | 尚未覆盖 |
|---|---|---|---|
| `crypto-watch` 加密同步行情 | Q046 / Q073 / G071；O089–O091；O093 / Q077 / G075 | 保留全币种概览；共享币种的现货、PM 同轴观测和相对收益。 | 未计算领先时长、择时信号或模型概率。PM 图仅绘制通过现有盘口拥有者校验的实际观测。 |
| `crypto-order-flow` 订单流 | C080 | Bybit 最近最多 60 笔现货主动买卖、样本 CVD、50 档快照失衡及前 10 档详情。 | 不是完整时间区间流量；增量 OFI、多交易所确认尚未实现。 |
| `crypto-funding-watch` 资金费率 | C079 | 保留原有双交易所费率、真实结算周期和覆盖；增加共享币种最近最多 100 次 Bybit 已结算费率及样本分位。 | 历史未补齐长期窗口；样本分位不能称为长期极端程度。 |
| `crypto-perp-funding` 持仓与基差 | C078 / C079 | 永续 OI 数量及名义金额、5 分钟 OI 序列、15m/1h/4h 变化、mark/spot 与 mark/index bps。 | REST 跨响应基差超过 5 秒时间差不计算；未实现完整期限结构、清算和跨所 OI。 |
| `crypto-oracle-reference` 合约指定源 | O043 / C081 / G072 / C082 | 目标为直接复用 market-data 的合约身份、60 秒官方 TWAP、开盘阈值和原始 E18；当前适配器仍接收旧快照契约，原始库直读尚未接入；验证币种、窗口、比较符、合约期限及阈值归属。 | 指定源过期就禁用当前距离；开盘展示值保留精度标签。原始窗口贡献和剩余窗口概率未实现；SOL/XRP 暂无绑定。 |
| `options-implied-probability` 期权隐含概率 | O041 / C075 / Q074 / G077 | BTC/ETH、未来七天中最多三个到期、真实双边报价支持的看涨价差概率带与买卖区间。 | 折现因子假设为 1；是阈值带平均风险中性尾概率参考，不是精确数字期权概率。未与 PM 到期匹配，不给 PM 概率差或交易结论。 |
| `crypto-exchange-inflow` 交易所链上流入 | Q076 | 复用现有 Dune BTC 历史研究归档，按日期与 Binance/Coinbase 聚合转入、转出、净额；30/90/180 日历天。 | 实时来源未接入；标签为事后获取，严格 PIT 未验收；转入不是卖出，未识别内部转账仍可能存在。 |
| `stablecoin-monitor` 稳定币压力 | Q079 | USDC/USDT 的 Coinbase 与 Kraken USD 报价、偏离 bps、来源差异和观测持续时间。 | 连续采样缺口重置持续时间；无原生报价时间时明确为接收时间。不是完整压力事件档案。 |

## 数据与模块边界

前端共享资源 `webpage/src/panels/shared/crypto-strategy/resource.ts` 使用 `usePanelResource`，key 为 `crypto-strategy:four-assets:v1`，浏览器检查 15 秒，服务采集目标 30 秒，快照超过 120 秒标记 stale。多个消费者共享请求与取消；没有新建每 Panel 定时器。共享 BTC/ETH/SOL/XRP 选择仅影响这一组 Panel，不冒充主工作区的任意合约绑定。历史期权与资金费率保留自己的到期/结算时刻。

API 注册四个新增视图路径：`/runtime/crypto/order-flow`、`/runtime/crypto/oracle-reference`、`/runtime/crypto/options`、`/runtime/crypto/exchange-inflow`。它们读取同一个快照；前端仅请求第一个路径避免重复传输。响应必须匹配 schemaVersion、kind 和资产身份；嵌套序列、盘口、期权与流入记录也校验。

数据拥有者为 `scripts/api/services/crypto_strategy/`。`crypto_strategy_watcher.py` 是单写入者（文件锁），落盘到主 snapshot SQLite 相邻的 `crypto_strategy.sqlite3`，或由 `POLYDATA_CRYPTO_STRATEGY_DB` 指定。API 使用 SQLite `mode=ro`，GET 不采集、不建表。全周期异常保留旧快照与原始时间；单来源失败保留其他来源并标注缺失。观测保留七天；单序列响应最多 300 点；上游价格档案最多 900 点。该存储不是研究级长期原始归档。

公共源：Bybit 现货/USDT 永续行情、分钟收盘、5m OI、资金费率历史、60 笔现货成交与 50 档深度；Deribit BTC/ETH 期权元数据和双边报价；Coinbase/Kraken USD 稳定币价格。Bybit spot 与 perp 分别请求，基差只有时间差不超过五秒才计算。不能把快照深度失衡叫作增量 OFI。

指定源的数据拥有者是 `market-data`。实盘原始观测在 XUE 的 `/mnt/hdd22t/market-data/chainlink-twap-60/YYYY-MM-DD/twap.sqlite3`；读取应使用只读连接，保留 E18、来源身份、观察/发布/接收时钟，并排除冲突、重复和时钟异常。当前覆盖 BTC/ETH。

旧适配器把 workbench `/snapshot` 当成必需中转，并配置 SUN 28075 → GCP 28076 专用 SSH 转发；用户已明确停用这条通道，不能将其当成故障自动恢复。已有本机数据不需要重新采集，workbench 也不是正式数据拥有者。当前线上尚未改为读取原始 TWAP 库，不得把本机读库成功说成公网 Panel 已有实时价格。现有 PostgreSQL/ClickHouse 连接不会自动包含 XUE 的 SQLite 文件；新的接入必须先验证已有数据访问入口，不能默认增加每个 Panel 独有的传输服务。

PM 报价优先使用源中已核验的绑定报价，缺失时读取现有 `/runtime/lob/books` 的 market-data live book，核验 token、continuity、heartbeat 和 staleAfter；不另建 LOB 采集器。PM 历史按 condition/token 分开，避免下一轮合约串线。

链上历史导出工具 `scripts/runtime/export_crypto_flow_history.py` 只读已有归档的 manifest 和 transaction_flows，校验记录数，用 Decimal 按日聚合。生产仅需要约 44 KB 的派生 JSON，保留原 manifest hash、dataset ID、实际覆盖期与标签限制；不复制原始归档、不把历史标为 live。

## 部署与运行

GCP 使用既有 `polydata-crypto-strategy-seed.service` 采集公共行情。旧单元仍声明指定源 28076，这不是有效的数据接入证明；截至本次核验该端口不可用，专用转发已停用。LOB 只读入口为 18500，链上派生文件默认 `/opt/polyData/data/crypto_exchange_flow_history.json`。服务重启不清空历史；网络不可用不会阻塞 API 请求。

`polydata-crypto-reference-tunnel.service` 保留为旧部署记录，不再作为安装步骤。禁止为修复空 Panel 擅自启动已停用的工作台、下载网关或专用转发。

发布使用 main 上本任务提交的 `git archive` 干净导出，构建时传入 `POLYDATA_BUILD_SHA`。只发布任务拥有的后端文件与用户服务，发布前比对目标文件哈希并保存可回滚备份；前端保留其他任务发布的 docs 资源。前端 release-sha 和后端按范围收据均记录同一提交，真实站点桌面与手机截图作为 UI 验证。构建或测试通过不能替代生产数据覆盖验收。

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
