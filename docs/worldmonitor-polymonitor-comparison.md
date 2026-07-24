# WorldMonitor 与 Polymonitor 实现对比

> 文档性质：架构与产品评估快照
> 评估日期：2026-07-24
> 说明：仓库规模、提交数量、面板数量和运行状态会持续变化；本文重点保存稳定的架构判断与升级含义。

## 结论摘要

- `worldmonitor` 是面向全球情报、新闻、地缘政治、金融、能源和灾害监控的横向产品平台。
- `polymonitor` 是围绕 Polymarket 市场、链上事件、订单簿、钱包画像、PnL 和量化回测构建的纵向数据与交易研究系统。
- 两者没有共同 Git 祖先，不能通过 `git merge` 或“直接更新到 WorldMonitor”完成升级。
- `worldmonitor` 在产品化、工程治理、认证、国际化、部署、测试和安全门禁方面明显领先。
- `polymonitor` 在 Polymarket 数据深度、链上解析、Oracle、LOB、地址分析和回测能力方面明显领先。

因此，正确的升级方式是选择性移植平台能力，而不是替换 Polymonitor 的预测市场数据核心。

## 1. 仓库与技术基线

评估快照显示：

| 维度 | worldmonitor | polymonitor |
|---|---|---|
| 产品定位 | 全球情报 SaaS 平台 | Polymarket 专业数据与量化终端 |
| 前端 | TypeScript、Preact、平台化面板体系 | TypeScript/TSX、Preact Hooks、多工作区 |
| 后端 | TypeScript/Node.js、Proto/RPC | Python、Flask/Gunicorn、HTTP Blueprint |
| 数据重点 | 实时聚合、缓存、用户产品状态 | 可追溯事实、历史重建、回测与研究 |
| 部署重点 | Vercel、Railway、Cloudflare、Docker、Tauri | GCP、Nginx、systemd、数据库容器 |
| 工程成熟度 | 多 CI、E2E、契约、安全与发布体系 | 功能丰富，但本机状态、服务和 Git 仍存在漂移 |

两个项目只是产品形态和交互思路相似，不是同一代码库的不同分支。共同资源很少，绝大多数 TypeScript、CSS、后端和组件实现已经独立演化。

## 2. 产品定位差异

### WorldMonitor：横向全球情报平台

主要覆盖：

- 全球新闻、RSS、Telegram、GDELT 和热点聚合
- 地缘政治风险、国家不稳定指数和战略态势
- 军事航班、军舰、军事基地和国防信息
- 冲突、制裁、贸易、采购和关键矿产
- 地震、火灾、台风、气候、疾病、空气质量和辐射
- 航班、机场、NOTAM、船舶、港口和供应链
- 能源、油气管道、天然气储量和燃料价格
- 股票、ETF、宏观、加密货币、稳定币、COT 和黄金
- 国家与区域 briefing、跨来源信号融合和风险摘要
- Web、PWA、桌面端、CLI、SDK、MCP 与 A2A

其核心优势是覆盖面、平台化和产品完整度。

### Polymonitor：纵向预测市场系统

核心链路是：

```text
Gamma / CLOB / Data API 市场发现
            ↓
市场、事件、outcome、token 身份统一
            ↓
Polygon OrderFilled 链上同步
            ↓
maker/taker、成交、现金流和持仓解析
            ↓
UMA / Adapter / UpDown Oracle 生命周期
            ↓
LOB 实时订单簿和历史快照
            ↓
地址画像、PnL、PolySignal、异常资金流
            ↓
价格序列、回测、订单、成交、账本和绩效指标
```

其核心优势是预测市场数据深度、可追溯性和执行研究能力。

## 3. 预测市场能力差异

WorldMonitor 主要把预测市场当作全球情报信号源：

- 拉取 Polymarket Gamma 和 Kalshi events
- 按地缘政治、科技、金融等分类
- 展示 Yes 概率、成交量、标题和链接
- 生成缓存或 seed 供面板读取

它不提供完整的 Polygon `OrderFilled`、maker/taker 解析、Oracle 生命周期、实时 LOB、钱包级 PnL 或成交级回测。

Polymonitor 则把 Polymarket 当作完整研究对象：

- Gamma `/markets`、`/events` 市场发现
- CLOB condition/token 映射
- Data API 补充和交叉验证
- event、market、outcome、token canonical registry
- Polygon `OrderFilled` 索引和成交方向解析
- ClickHouse 成交事实表、同步窗口和缺口修复
- cashflow、non-trade、ERC20、CTF 和 position pipeline
- UMA、Adapter、UpDown Oracle 生命周期
- LOB WebSocket、快照和维护服务
- 地址画像、持仓、PnL、edge、鲸鱼和异常资金流
- 历史数据集和 Kaggle/Parquet 导出

一句话概括：

> WorldMonitor 把 Polymarket 当作一个情报源；Polymonitor 把 Polymarket 当作完整的数据、研究和执行对象。

## 4. 量化与历史数据

WorldMonitor 的分析能力主要面向股票、宏观、趋势和通用情景预测。

Polymonitor 的 [Quant Workspace](../webpage/src/workspaces/quant/QuantWorkspace.tsx) 与 [`quant`](../quant) 模块专门服务于预测市场：

- CLOB 时间轴价格和 OrderFilled 区块轴价格
- event tile、head、window 和流式读取
- 策略任务队列与后台 worker
- 订单、成交、账本、权益曲线和指标
- benchmark、coverage 和数据完整性
- builtin、Backtrader、Nautilus 多执行引擎
- passive limit replay
- block/time 双坐标系统
- 数据版本和执行模型验证

这是 Polymonitor 最有价值、也最不能被 WorldMonitor 替代的能力之一。

## 5. 前端与面板架构

WorldMonitor 的前端更接近平台框架：

- 统一 Panel 基类和清晰依赖边界
- fast/slow bootstrap
- viewport-aware 加载
- 统一刷新调度、缓存和 circuit breaker
- 多产品 variant
- MapLibre、Deck.gl、Globe.gl、D3/SVG 多级回退
- IndexedDB、本地存储、PWA 和离线缓存

Polymonitor 使用标准 Preact Hooks：

- 主应用支持面板拖动、缩放、面板库、布局和模式切换
- 存在 World、Quant 等不同工作区
- 业务功能落地直接，但部分主组件、类型文件和 CSS 体量过大
- 面板各自实现请求、轮询、错误和刷新逻辑，统一运行时边界不足

Polymonitor 的前端优势是业务表达直接；主要技术债是巨型组件、巨型样式文件和缺少统一 Panel Runtime。

## 6. 地图与现实事件

WorldMonitor 的地图是全球情报数据底座，覆盖军事、冲突、航班、船舶、基础设施、灾害、气候、疾病、网络安全、能源、供应链和金融风险等大量图层。

Polymonitor 的地图重点是解释：

- 预测市场与现实事件的关系
- Oracle 和结算状态
- OrderFilled 与大额资金行为
- LOB 和流动性
- 外部情报与市场定价变化

因此，Polymonitor 不需要复制 WorldMonitor 的全部全球图层，而应优先建设“现实事件如何影响市场定价”的关联能力。

## 7. World Cup 专项能力

评估时 Polymonitor 曾具有独立 World Cup 工作区、赛程、比赛结果、赔率、天气、区域风险和 Polymarket 市场关联。WorldMonitor 没有对应的世界杯预测市场工作区。

该专项实现证明了 Polymonitor 可以构建垂直事件工作台，但赛后不应继续占据主产品入口。通用的赛事数据、概率对比和事件关联方法可以保留，世界杯专属面板应隐藏或归档。

## 8. 后端与 API

WorldMonitor 的 API 更接近公开产品网关，包含：

- CORS、匿名 session、JWT、API key
- entitlement、rate limit、quota
- Redis cache、idempotency、HMAC
- usage telemetry 和统一错误映射
- Proto/OpenAPI contract

Polymonitor 的 API 更接近内部数据平台：

- Flask/Gunicorn 和多个 Blueprint
- 大量 service 与 runtime panel provider
- API、数据库访问、pipeline、runtime 和 ops 边界仍有混杂
- 部分 route 定义与注册状态需要持续校准

Polymonitor 不必照搬 Proto，但需要统一请求/响应模型、OpenAPI、错误格式、分页、时间与身份字段。

## 9. 存储架构

WorldMonitor 的存储重点是产品状态和缓存：

- Redis
- Convex
- R2/KV
- IndexedDB、localStorage
- OS keyring 和 Workbox cache

Polymonitor 是持久化数据平台：

- Postgres：市场、Oracle、运营状态和 Quant
- ClickHouse：成交、现金流、持仓、转账和 PolySignal
- Redis：跨进程缓存
- SQLite：面板快照
- Parquet/Kaggle：历史数据和发布

两者目标不同：

- WorldMonitor 优先实时聚合和产品响应。
- Polymonitor 优先可追溯、可重算和可回测的数据事实。

## 10. 用户、认证与商业化

WorldMonitor 已具备匿名 session、用户认证、API key、OAuth、权益、支付、通知、Webhook、Web Push、用户偏好和分享能力。

Polymonitor 当前更适合作为内部研究平台：

- 缺少完整用户登录、JWT/session 和 RBAC
- 主要依赖 Nginx、同源部署和网络边界
- Agent 接口已有部分 token 与预算控制
- Quant、repair、backfill 和 Agent 写接口需要统一认证

如果准备公开使用，必须优先补齐权限、限流、配额、审计和 fail-closed 行为。

## 11. AI、搜索与自动化

WorldMonitor 的 AI 更偏产品分发：

- 浏览器端模型、Web Worker 和本地向量索引
- 新闻摘要、风险融合、scenario/forecast
- MCP、A2A、开放 API 和多语言 SDK

Polymonitor 的 AI 更偏预测市场研究：

- OpenAI Agents、LangGraph、Tavily
- 市场 insight 和 wide-agent
- 新闻与市场内容分析
- Agent gateway 预算、token 和 fallback
- Telegram publisher 与 query bot

Polymonitor 的优势是 AI 与市场、交易和钱包数据结合更深；需要学习的是 WorldMonitor 的接入、权限和分发方式。

## 12. 构建、测试与部署

WorldMonitor 的工程体系包括：

- 固定 Node/TypeScript 版本和依赖锁
- 严格类型检查
- Docker digest、非 root 和 healthcheck
- 契约生成与 freshness 校验
- 大量单元、E2E、视觉、性能和 live smoke 测试
- 多个 CI/CD workflow 和提交门禁

Polymonitor 的主要缺口是：

- Python 版本和依赖没有完全锁定
- 前端测试与 E2E 不完整
- Python、数据库、systemd 和 SQL 尚未形成统一 CI
- 生产仍大量依赖 systemd、SSH/rsync 和本机运维状态
- 本机运行实现与 Git HEAD 曾存在明显漂移

## 13. 运行与安全风险

评估快照发现过以下风险：

- 失败或 inactive 的 systemd 服务
- 运行服务与仓库模板不一致
- target 引用缺失 unit
- 服务共享大型环境文件
- systemd sandbox 选项不足
- Redis 监听范围需要收紧
- 部分写接口和 CORS 边界需要认证
- 大量未提交改动导致生产难以由 Git 重建

这些属于工程治理风险，不是业务能力不足。

## 14. 双方独有优势

### WorldMonitor 更强

- 全球新闻与多源情报
- 大量地图图层和国家风险 briefing
- 国际化、PWA、桌面端和 Web Push
- 用户、支付、权益、OAuth 和公开 API
- MCP/A2A、SDK 和多 variant
- CI、E2E、视觉回归、安全门禁和可观测性

### Polymonitor 更强

- 市场身份统一
- Polygon `OrderFilled` 全链路
- maker/taker 交易解析
- UMA/Adapter/UpDown Oracle
- LOB 实时与历史订单簿
- 地址持仓、钱包画像和 PnL
- PolySignal、鲸鱼和异常资金流
- 区块级与时间级价格
- 预测市场回测与执行模拟
- Quant 数据库、worker 和大规模历史数据

## 15. 最终升级含义

推荐的能力组合是：

```text
保留 Polymonitor 的垂直数据核心
    ├── Market Registry
    ├── OrderFilled
    ├── Oracle
    ├── LOB
    ├── 地址画像 / PnL
    └── Quant / 回测

选择性吸收 WorldMonitor 的平台能力
    ├── 前端架构边界
    ├── 面板生命周期和刷新调度
    ├── API contract / gateway
    ├── 用户认证和权限
    ├── PWA / 国际化
    ├── telemetry
    ├── CI / E2E / 安全门禁
    └── 部署可复现性
```

最终判断：

> WorldMonitor 更像成熟的全球情报 SaaS 平台；Polymonitor 更像功能深、数据重、但工程治理仍处于快速演进阶段的 Polymarket 专业终端。
