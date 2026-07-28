# Polymonitor 平台升级路线图

> 决策日期：2026-07-24
> 目标：吸收 WorldMonitor 的平台能力，同时保留并强化 Polymonitor 的预测市场专攻性。

## 目标架构

Polymonitor 不应复制 WorldMonitor，而应形成三层：

```text
产品平台层
面板系统、工作区、用户、权限、通知、国际化、PWA

预测市场智能层
市场研究、事件解释、地址画像、信号、策略、风险分析

数据与执行层
Market Registry、OrderFilled、Oracle、LOB、PnL、Quant、回测
```

当前最需要优化的不是继续增加面板，而是把已有能力组织成稳定、可信、可持续演进的产品。

## 核心原则

1. 任何生产功能都能由 Git 和锁定依赖重建。
2. 任何展示数据都能说明来源、时间、完整性和质量。
3. Market、Address、Oracle、LOB 和 Quant 形成统一工作流。
4. 平台能力可以借鉴，预测市场数据核心必须保留。
5. 新功能进入清晰边界，旧功能逐步迁移，避免一次性大重写。

## P0：工程可复现

### 清理工作树

- 按 frontend、API、data pipeline、quant、deployment 拆分提交。
- 区分正式源码、运行数据、缓存、日志和实验产物。
- 将 Kaggle、PnL、Parquet、日志等移出源码提交范围。
- 所有生产运行服务必须能在仓库中找到对应模板。
- 本机运行实现与 Git HEAD 不再长期分叉。

### 固定运行环境

- 明确 Python 版本。
- 引入 `pyproject.toml`。
- 生成可复现的依赖 lock 或 constraints。
- 固定 Node、Python、Postgres、ClickHouse 和 Redis 版本。
- 提供从空 checkout 到完整开发环境的一键启动流程。

### 建立部署单一事实来源

- 仓库中的 systemd、Nginx 和环境变量模板与生产一致。
- 禁止仅在服务器上手工修改服务。
- 自动检查 target 引用的 service 是否存在。
- 部署后自动验证 API、数据库、worker、Telegram 和前端。

验收标准：

> 从全新 checkout 出发，不依赖本机历史状态，可以构建、测试并启动完整开发环境。

## P0：CI 与质量门禁

### 前端流水线

- TypeScript typecheck
- Vite production build
- lint/format
- 单元测试
- 面板注册完整性检查
- Playwright E2E
- 核心页面截图回归

核心流程至少覆盖：

- 主地图加载
- 面板打开、关闭、拖动和布局恢复
- 市场搜索与 Market Workspace
- OrderFilled、Oracle 和 LOB
- 地址画像
- Quant Workspace

### Python 后端流水线

- pytest
- Ruff
- Mypy 或 Pyright
- import boundary 检查
- Flask 路由注册检查
- 数据库 smoke test
- SQL migration 检查

### 数据与部署流水线

- systemd unit 语法检查
- target/service 引用检查
- Nginx 配置检查
- 数据表 schema contract
- Market Registry 完整性
- API response schema
- 依赖和容器安全扫描
- secret 扫描

目标发布链路：

```text
提交
  → 静态检查
  → 单元测试
  → 前后端构建
  → E2E
  → staging smoke
  → 生产部署
  → 生产健康检查
```

## P0：重构后端边界

当前 `scripts/` 同时承担 API、数据库、同步、市场发现、runtime panel、修复、运维和导出。目标结构建议为：

```text
polymonitor/
├── api/
├── domains/
│   ├── markets/
│   ├── orderfilled/
│   ├── oracle/
│   ├── orderbook/
│   ├── addresses/
│   ├── pnl/
│   ├── signals/
│   └── quant/
├── infrastructure/
│   ├── postgres/
│   ├── clickhouse/
│   ├── redis/
│   ├── polygon/
│   └── clob/
├── workers/
├── ops/
└── cli/
```

迁移规则：

- 新功能进入新结构，旧模块按变更机会逐步收拢。
- 路由不直接拼数据库查询。
- 数据访问集中到 repository/query 层。
- runtime panel 只组装展示数据。
- pipeline 和 API 不共享无边界的大型 helper。
- 关键依赖缺失时启动失败。
- 未注册 route 要么正式接入，要么删除。

## P1：前端平台化

### 拆分巨型模块

优先拆分：

- `App.tsx`
- `QuantWorkspace.tsx`
- Price Chart 和 Strategy Tester
- `types.ts`
- `panels.css`
- `main.css`

目标边界：

```text
app-shell/
workspace-runtime/
panel-runtime/
map-runtime/
data-client/
design-system/
features/
```

### 建立统一 Panel Runtime

统一处理：

- 注册与加载
- 可见性和 viewport
- 刷新周期
- 缓存与 stale 状态
- retry 和错误降级
- loading skeleton
- suspend/resume
- 数据依赖声明

示例契约：

```ts
interface PanelDefinition {
  id: string
  title: string
  workspace: string[]
  dataSources: string[]
  refreshPolicy: RefreshPolicy
  permissions?: string[]
  component: ComponentType
}
```

### 建立 Design System

统一色彩、字体、间距、卡片、表格、图表 tooltip、状态标签、风险颜色、freshness、空状态、loading/error 和响应式布局。

## P1：API 契约化

- 使用 Pydantic 或同等级 schema 管理。
- 自动生成 OpenAPI 和 TypeScript client。
- 统一错误、分页、时间、地址和 ID 格式。
- 建立 `/api/v1/...` 版本策略。
- 区分查询接口和写入/任务接口。
- Quant run、repair 和 backfill 增加幂等键。

统一身份体系：

```text
event_id
market_id
condition_id
token_id
slug
question_id
oracle_request_id
```

前端不再自行猜测字段之间的关系。

## P1：数据可信度

重要接口统一返回：

- `source`
- `source_timestamp`
- `ingested_at`
- `freshness_seconds`
- `quality_status`
- `coverage`
- `is_partial`
- `last_complete_block`
- `repair_status`
- `dataset_version`

前端统一显示来源、更新时间、完整度、缓存/降级状态、缺口和同步水位。

### Market Registry 指标

- Gamma/CLOB/Data API 覆盖差异
- 无 token 或 condition 的市场
- 重复市场
- outcome/token 数量异常
- 已关闭但仍活跃的市场

### OrderFilled 指标

- 最新区块与连续水位
- 首个缺口和重复率
- maker/taker 解析失败率
- token 无法关联市场的比例

### Oracle 指标

- request、proposal、dispute、settlement 生命周期完整度
- 市场与 oracle request 关联率
- resolved market 缺失 settlement 的比例

### LOB 指标

- WebSocket 在线状态
- 快照延迟和 sequence gap
- crossed book 和无效价差
- 市场关闭后仍更新

### Quant 指标

- 数据覆盖区间和数据版本
- look-ahead 检查
- 执行模型、费用和滑点版本
- 时间轴/区块轴说明

数据可信度应成为 Polymonitor 相对 WorldMonitor 的核心优势。

## P1：预测市场专攻能力

### Market Workspace

统一市场规则、outcome/token、价格、成交量、LOB、大额成交、地址结构、Oracle、新闻、现实事件时间线、相似市场、相关风险和 AI 摘要。

### Address Workspace

提供累计/已实现 PnL、持仓、成交、maker/taker 行为、持仓时间、领域偏好、入场领先程度、赔率偏好、资金来源、smart-money 证据和质量评分。

### 可解释 PolySignal

每个信号显示：

- 触发原因和原始证据
- 对应交易和地址历史准确率
- 市场流动性与可执行性
- 信号失效条件
- 后续表现

### 可复现 Quant

每次回测记录：

- strategy version
- dataset version
- execution model version
- fee/slippage
- market coverage
- rejected orders 和 partial fills
- oracle resolution source

### 市场生命周期

统一状态：

```text
discovered
→ tradeable
→ active
→ closed
→ proposed
→ disputed
→ resolved
→ redeemed
→ archived
```

### 现实事件与市场关联

- 新闻事件影响哪些市场
- 事件前后的价格变化
- 同一事件下多个市场是否定价冲突
- 预测市场与 bookmaker、民调、宏观指标的偏差

## P1：安全与权限

公开产品必须补齐：

- 登录、session/JWT 和 RBAC
- workspace 权限
- API key、rate limit 和 quota
- audit log
- 写操作和导出授权

立即处理：

- 收紧 Quant API CORS。
- 认证回测、repair、backfill 和 Agent 写接口。
- Agent token 未配置时 fail-closed。
- Redis 仅监听必要网络。
- systemd 服务拆分凭据。
- 增加 `NoNewPrivileges`、`ProtectSystem`、`ProtectHome` 和 `PrivateTmp`。

## P1：可观测性与运行控制

统一采集：

- API latency 和 error rate
- worker heartbeat
- 数据库延迟与空间
- Redis/ClickHouse/Postgres 健康度
- 同步水位、缺口和修复状态
- RPC 429/timeout
- CLOB WebSocket
- queue depth 和 backfill progress
- systemd failed unit
- 数据 freshness
- Agent token/cost

建设 Operations Workspace，直接回答：

- 哪些服务正在运行或失败
- 每条 pipeline 同步到哪里
- 当前有哪些缺口
- 最近完成了哪些修复
- 数据源是否降级
- 当前 RPC 与数据库资源使用情况

## P2：产品化与分发

工程基础稳定后再增加：

- 用户自定义 workspace
- 布局云同步
- 市场收藏和地址关注
- 价格、成交、Oracle 和 smart-money 告警
- Telegram、Web Push 和邮件通知
- 可分享市场报告与每日 briefing
- 多语言、PWA 和移动端
- API key、开发者文档和 MCP

暂不优先：

- 多语言 SDK 发布
- Tauri 桌面端
- 复杂支付系统
- 全套 Convex
- 复制 WorldMonitor 的全部全球图层

## 实施阶段

### 第一阶段：工程止血

- 完成工作树分类与提交
- 固定 Python/Node 依赖
- 校准 systemd 与生产状态
- 建立后端 CI
- 修复失败服务
- 收紧 Quant、Agent 和 Redis 安全边界

### 第二阶段：平台骨架

- 拆分 App 和巨型 CSS
- 建立 Panel Runtime
- API schema/OpenAPI
- 统一错误、缓存和 freshness
- Design System
- Operations Workspace

#### 2.1 Panel Runtime 2.0 与 App Shell（已完成，2026-07-28）

- Panel contract 已增加 workspace、data source、permission、batch limit、refresh policy、retry 和 AbortSignal 边界。
- 单一 `usePanelRuntime` 已接管 batch/single fallback、inflight 去重、后台暂停、interval、指数退避、stale/degraded/error 状态与 last-updated。
- App 不再维护独立的 fast、slow、interval runtime 调度；公共 promo、header 和 navigation 已迁入 `AppShell`。
- panel slot 已统一 loading、stale、degraded、error、suspended 和手动重试状态；旧数据会在瞬时失败时继续显示。
- 已隐藏的 World Cup workspace 和 panels 不再进入活动模块注册表、JavaScript chunk 或独立 CSS import，源码仍保留以便未来赛事复用。
- 本阶段继续保留 Quant、LOB、PolySignal、PnL/position、address 和数据管道边界，不在平台骨架重构中改写其业务实现。

下一批平台骨架工作：继续拆分 `App.tsx` 与巨型 `panels.css`，随后建立 API schema/OpenAPI 和跨 panel 的统一响应 envelope。

#### 2.2 Panel Workspace 与共享 CSS 模块化（已完成，2026-07-28）

- `PanelWorkspaceSlot`、`PanelRuntimeBoundary`、panel layout 类型、拖拽和缩放生命周期已从 `App.tsx` 迁入独立组件；App 只保留工作区状态与面板编排。
- 拖拽与缩放的 document listener、animation frame、ghost、drop indicator 和 body 状态在取消、完成与组件卸载时统一回收。
- loading、runtime notice、slot layout、drag 与 resize 样式已从 `panels.css` 迁入 `panel-workspace.css`，保留原媒体查询和 CSS layer 顺序。
- 共享 `panels.css` 中 984 条已停载 World Cup 规则、1570 个 World Cup selector 以及 layout stability 中的旧 panel slot 已清除；World Cup 业务源码和 workspace 私有样式仍保留，但不进入活动构建。
- 本阶段未改动 Quant、LOB、PolySignal、PnL/position、address、non-trade/CTF/ERC20/Data API trades、Kaggle 或测试文件。

下一批平台骨架工作：建立 API schema/OpenAPI 与跨 panel 的统一响应 envelope，然后再统一错误、缓存和 freshness 语义。

### 第三阶段：预测市场产品化

- Market Workspace
- Address Workspace
- Oracle lifecycle
- 可解释 PolySignal
- 可复现 Quant
- 数据质量面板

### 第四阶段：用户与分发

- 登录、权限和 API key
- watchlist 和告警
- 布局同步
- 分享和 briefing
- PWA、国际化和 MCP

## 下一步执行建议

下一步不应继续增加业务面板，而应启动“工程基线与 CI”阶段：

1. 将当前已审核的 6 个提交推送到远端，形成最新可追溯基线。
2. 对仍在本地的实验改动建立正式的保留/迁移清单。
3. 新建最小后端 CI：Python 编译、pytest、shell/systemd 检查和 secret scan。
4. 固定 Python/Node 版本并建立依赖锁。
5. 增加“从全新 checkout 构建成功”的验收脚本。

这一阶段完成后，再开始 Panel Runtime 或 Design System；否则前端平台化仍会建立在不可复现的运行基础上。
