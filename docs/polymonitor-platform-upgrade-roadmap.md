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

#### 2.3 API Schema、统一 Envelope 与 Freshness 元数据（已完成，2026-07-28）

- 新增 OpenAPI 3.1 文档端点 `/openapi.json` 与 `/v1/openapi.json`，运行时从 panel registry 生成 panel ID、路由和 limit 契约。
- 新增版本化 `/v1/runtime/panels` 与 `/v1/runtime/panels/{panelId}`；统一返回 `apiVersion`、`requestId`、`generatedAt`、`status`、`data`、`meta` 和结构化 `errors`。
- batch 响应在 `meta.panels` 中统一发布 panel route、status、cache mode、age、freshness observation 和 limit 边界。
- 前端 Panel Runtime 已迁移到 v1 envelope；旧 `/runtime/panels`、单 panel 与业务别名端点继续返回原始 payload，避免破坏外部消费者。
- 本阶段只改变 API 平台契约，不改写 Quant、LOB、PolySignal/PolyBeats、PnL/position/address、数据管道、World Cup、Kaggle 或测试业务实现。

下一批平台骨架工作：建立 Design System token/component 边界，然后建设面向数据与服务健康的 Operations Workspace。

#### 2.4 Design System 与 Operations Workspace（已完成，2026-07-28）

- 新增统一设计 token 层，覆盖 canvas/surface/border/text、单一主色、语义状态色、字体、间距、圆角、阴影、动效与 reduced-motion。
- 原有 `--wm-*` 变量映射到平台 token，允许现存 panel 渐进迁移，避免一次性重写全部业务样式。
- 新增共享 Status、Freshness、Runtime Status 与 Metric primitives；Panel Runtime 的 ready/stale/degraded/error/suspended、cache mode 和 age 已形成统一可视状态。
- 新增只读 `/operations` 工作台，消费 system health 和 seed health，展示 API/Redis/数据库类型、同步水位、watcher heartbeat、source states、records、freshness 与 active gaps。
- Operations 不暴露 SSH、systemd 控制、凭据或修复写接口；watcher heartbeat 不冒充 host-level systemd 状态，生产发布仍独立使用 `systemctl --user` 验证。
- World Cup 仍保持隐藏；本阶段未修改 Quant、LOB、PolySignal/PolyBeats、PnL/position/address、数据管道、Kaggle 或测试业务实现。

本批已完成 Market Workspace 信息架构与证据链统一；后续产品化阶段见第三阶段边界说明。

### 第三阶段：预测市场产品化

- Market Workspace
- Address Workspace
- Oracle lifecycle
- 可解释 PolySignal
- 可复现 Quant
- 数据质量面板

#### 3.1 Market Workspace 信息架构与证据链（已完成，2026-07-28）

- 新增可分享的 `/markets/<localMarketId>` Market Dossier，将市场规则、Outcome/token、概率历史、CLOB、OrderFilled、Oracle、事件分组和关联情报组织到一个只读工作区。
- `/markets/<localMarketId>/workspace` 新增 `market-workspace-evidence.v1` 契约，按 identity、price、history、trades、oracle 和 group 发布来源、状态、观测时间、记录数、标识符与问题清单。
- 浏览器为独立加载的 CLOB 和 linked intelligence 补充证据节点；缺新闻不等同于缺市场证据，空 Oracle timeline 不冒充已结算。
- Atlas command palette 和 focused market strip 均可进入 Market Dossier；Outcome 可以切换到对应本地 market ID，URL 可直接复制分享。
- 页面统一显示 loading、empty、fresh、aging、stale、partial、missing 和 error；刷新失败保留最后一次成功数据。
- 公共 Atlas 导航已隐藏 Operations 入口；`/operations` 仍保持只读，等待后续权限阶段纳入管理员访问控制。
- 本阶段未改写 LOB runtime、Quant、PolySignal/PolyBeats、PnL/position/address、non-trade/CTF/ERC20/Data API trades、World Cup、Kaggle 或测试业务实现。

#### 3.2 Oracle lifecycle 与数据质量面板（已完成，2026-07-28）

- 新增公共 `/data-quality` 工作台及 `prediction-market-data-quality.v1` 只读 API，集中展示市场身份、token registry、serving price、Oracle binding、closed-market finality 与 trade/Oracle freshness。
- 市场全生命周期按 Discovered、Tradeable、Recently active、Closed、Proposed、Disputed、Resolved 和 Redeemed 展示；不同来源的历史 universe 不冒充转化漏斗，尚未采集的 Redeemed 明确标记为 `not-collected`。
- Oracle lifecycle 独立展示 Request、Propose、Dispute 和 Settle；事件身份固定为 `tx_hash + log_index`，规范顺序为 `block_number + log_index`，未绑定本地市场的链上事件仍作为可审计 gap 保留。
- 建立加权质量分数、七项维度阈值、active gap ledger、代表性 awaiting-Oracle 市场、同步水位和刷新失败保留 last-good 的降级语义。
- Market Dossier 同步增加四阶段 Oracle rail 与 `logIndex`，公共 Atlas 导航增加 Quality 入口；Operations 仍不在公共导航展示。
- 本阶段只读现有数据，不启动或修改已停止的 Oracle collector，也未改写 LOB runtime、Quant、PolySignal/PolyBeats、PnL/position/address、non-trade/CTF/ERC20/Data API trades、World Cup、Kaggle 或测试业务实现。

第三阶段在当前允许边界内已经完成 Market Workspace、Oracle lifecycle 和数据质量面板。Address Workspace、可解释 PolySignal 与可复现 Quant 仍属于明确排除域；不改变该边界时，下一阶段应进入用户与分发能力。

### 第四阶段：用户与分发

- 登录、权限和 API key
- watchlist 和告警
- 布局同步
- 分享和 briefing
- PWA、国际化和 MCP

#### 4.1 身份、角色与 Operations 管理员访问控制（已完成，2026-07-28）

- 新增 PostgreSQL `product` schema，建立用户、服务端 session、API key、分钟/日配额、登录限速和安全审计模型；生产 API 在启用 auth 后若 schema 或 audit pepper 缺失会启动失败。
- 密码采用逐用户 salt 的 scrypt；浏览器只持有 `Secure`、`HttpOnly`、`SameSite=Lax` 的 `__Host-` 不透明 cookie，数据库只保存 session、CSRF 和 API key 哈希。
- 新增 `/login` 与 `/account`，支持 bootstrap 密码强制更换、登出、管理员 API key 一次性签发/吊销和审计事件查看；API key 当前只允许 `operations:read`。
- `/system/health`、`/system/seed-health` 与 `/operations` 已纳入管理员保护；普通 `/health` 保持公开，继续服务 GCP 发布探针。
- Operations 仍是只读应用控制面，不提供 SSH、systemd、凭据回显或修复写操作；原有 Quant、LOB、PolySignal/PolyBeats、PnL/position/address、non-trade/CTF/ERC20/Data API trades、World Cup、Kaggle 和测试业务文件保持不动。

#### 4.2 Watchlist、市场/Oracle 告警与通知偏好（已完成，2026-07-29）

- 新增受 session 与 CSRF 保护的 `/watchlist`，支持按 canonical local market ID 跟踪市场，并从 Market Dossier 一键加入。
- `product` schema 只保存用户选择、规则、事件与通知偏好；价格、市场状态和 Oracle lifecycle 继续读取 canonical `core` 数据，不建立第二份事实表。
- 自动规则覆盖 Oracle gap 与 dispute；可配置规则覆盖价格上下穿、proposal、resolution 和 market close。独立 evaluator 仅在 false→true 转换时生成事件，支持 rearm、cooldown、去重和运行状态记录。
- 新增 in-app inbox、read/read-all、digest cadence、quiet hours 与 timezone；Telegram 继续由原隔离 runtime 管理，email 明确为 unavailable。
- 保持 Quant、LOB、PolySignal/PolyBeats、PnL/position/address、non-trade/CTF/ERC20/Data API trades、World Cup、Kaggle 和测试文件不动。

#### 4.3 服务端布局同步与可分享 briefing（已完成，2026-07-29）

- 匿名用户继续使用 localStorage；登录用户自动同步 panel ID/顺序、row/column span、region、map mode、zoom、panel library 和 market-group sort。
- 服务端 layout 使用单调 revision 与乐观锁；旧 revision 写入返回 conflict，不静默覆盖其他设备。离线本地布局只在 client timestamp 更新时回写。
- 新增 `/briefings` registry；浏览器只提交可选标题，服务端从 canonical market serving、Oracle status、用户 watchlist 和 workspace lens 生成 `prediction-market-briefing.v1` 快照。
- 公共 `/briefings/<publicId>` 为只读页面，明确 generated-at、expiry、来源契约和非交易建议；192-bit 随机链接 30 天过期、可撤销、每用户最多 20 个 active links。
- 私人 notes、alert rules/events、session、credential 不进入快照；原排除域和测试文件保持不动。

下一批用户产品能力：PWA、国际化和 MCP 分发。

#### 4.4 PWA、国际化和 MCP 分发（已完成，2026-07-29）

- 新增可安装 PWA、按构建 SHA 版本化的静态壳缓存、显式更新提示和中英双语断网降级页；所有 `/wm-api` 请求保持严格 `NetworkOnly`，实时市场、Oracle、流动性、账户与 MCP 数据不会从 Service Worker 缓存返回。
- 建立 `en`/`zh` 稳定词条、浏览器语言检测、用户语言持久化、`html lang` 同步以及日期、数字、百分比格式化服务；构建前完整性门禁会拒绝非法 key、空翻译和两种语言的 key 漂移。
- 公共 Shell、设置、PWA 状态和 Developer Workspace 已完成双语接入；其余专业面板按同一契约逐步迁移，不以本阶段伪装成全站翻译完成。
- 新增 `/wm-api/mcp` 的无状态 Streamable HTTP JSON-RPC 入口，工具只覆盖市场搜索、市场概览、Oracle 生命周期、有限深度流动性、数据质量、公开 Briefing 和其中主动发布的 Watchlist 快照。
- 数据工具统一要求独立 `mcp:read` Bearer API key，并继承分钟限速、日配额、一次性密钥显示、吊销和审计；输出使用字段白名单，排除私人布局、私人 Watchlist、notes、提醒规则/事件、session、凭据、管理员接口和任意 API 代理。
- 保持 Quant、LOB runtime 控制、PolySignal/PolyBeats、PnL/position/address、non-trade/CTF/ERC20/Data API trades、World Cup、Kaggle 和测试文件不动。

#### 4.5 移动端信息架构、专业页面国际化与公开 SDK（已完成，2026-07-29）

- 新增移动端五入口工作区导航，统一 Atlas、Data Quality、Watchlist、Briefings 和 Developers；使用 62px 触控区域、safe-area、当前页状态和 reduced-motion，避免把桌面链接横向塞入小屏。
- Market Dossier 与 Data Quality 的导航、Hero、刷新/错误状态和核心指标接入稳定 `en`/`zh` key；嵌套证据表继续按专业面板逐步迁移，不宣称全站正文已经全部翻译。
- OpenAPI 升级到 1.1，除原 Panel Runtime 外，新增市场搜索、市场身份、Market Workspace、Oracle lifecycle、数据质量、公开 Briefing 与 MCP 的只读契约；私人产品和管理员端点继续排除。
- 发布零依赖 ESM JavaScript SDK 与 TypeScript 声明，公共读取无需凭据，MCP 工具调用必须由调用方显式提供 `mcp:read` Key。
- 按 MCP 官方授权规范和 RFC 9728 核验后，未在没有真实 OAuth 2.1 authorization server 的情况下伪造 Protected Resource Metadata；当前生产仍明确使用受配额和审计约束的 API Key。
- Web Push 在本小节完成时尚未启用；后续 4.6 已把 VAPID、subscription、quiet hours/digest、失败退订和后台 publisher 作为一个闭环落地。

#### 4.6 Web Push 闭环与专业工作区国际化（已完成，2026-07-29）

- 新增按用户存储和撤销的浏览器 Push subscription；API 只返回可用性、公钥和连接计数，不向公共 API、MCP、Briefing、日志或审计明细泄露 endpoint、`p256dh`、auth secret 或 VAPID 私钥。
- 新增持久化 delivery outbox；realtime/hourly/daily/off、IANA timezone、跨午夜 quiet hours、最多五次指数退避、`404/410` 自动撤销和 publisher runtime state 均由独立 product-alert 服务执行。
- API 和 publisher 启动时验证成组 VAPID 配置；systemd 在启动受影响服务前幂等执行 product schema migration，避免代码与表结构短暂错配。
- subscription endpoint 仅允许标准浏览器推送服务的 HTTPS 主机，拒绝 localhost、云元数据地址和任意主机，避免形成 SSRF 出口。
- Service Worker 新增加密 push 展示与同源 notification click 路由；实时 `/wm-api` 继续严格 `NetworkOnly`。
- Watchlist、Briefing 和 Auth/Access 正文接入 `en`/`zh` 稳定目录；当前两种语言各 381 个 key，由同一完整性门禁校验。
- Quant、LOB runtime 控制、PolySignal/PolyBeats、PnL/position/address、non-trade/CTF/ERC20/Data API trades、World Cup、Kaggle 和测试文件继续保持不动。

## 下一步执行建议

工程基线、CI、类型化路由、Panel Runtime、Design System、Operations、Market
Workspace、Oracle/data-quality、PWA、MCP、移动端导航、公开 SDK、Web Push
以及 Watchlist/Briefing/Auth 双语正文均已建立。下一批在现有边界内的工作：

1. 选择并接入真实 OAuth 2.1 issuer，完成 MCP Protected Resource Metadata、PKCE 和客户端注册。
2. 继续迁移 Market/Data Quality 内层证据表和其余专业 panel 正文，保留市场术语与来源字段原义。
3. 为 Web Push 增加真实浏览器端到端验收与投递 SLO 看板；这需要至少一个用户在生产浏览器中主动授权通知。

若要优先建设 Address Workspace、可解释 PolySignal 或可复现 Quant，必须先重新确认
PnL/position/address、PolySignal 和 Quant 的修改边界，再建立独立实施计划。
