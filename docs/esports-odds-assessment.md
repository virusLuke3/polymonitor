# 电竞免费赔率接入与匹配试验

本文保留 2026-11-09 18:05 的免密钥匹配试验。后续正式接入以 [Sports / Game 数据与界面契约](sports-game-panels.md) 为准；下文没有生产采集的描述仅适用于原试验工具，不代表后续实现状态。

## 入口与实际覆盖

| 来源 | 无密钥能力 | 本次结果 | 边界 |
| --- | --- | --- | --- |
| [OddsLink guest API](https://oddslink.app/docs/api-reference/operations/runtryit/) | 每个 UTC 日 5 次公开只读请求 | LoL 4 场；目标书商双边整场赔率 8 组：Pinnacle 3、Thunderpick 4、Stake 1；Bet365 0 | 第三方聚合报价，未独立向每家书商核验；不是无限制免费采集 |
| [KashRock Try Me](https://www.kashrock.com/) | 无注册单条 prop 演示 | GG.BET：Knight 第 2 局击杀大于 4.5，American +136 | 一侧球员盘口，不是双边整场胜率；没有独立报价更新时间，不能计算同盘去水概率 |
| [Pinnodds public esports board](https://pinnodds.com/pinnacle-odds/esports) | 公开 HTML 赔率表 | 直接请求得到 LoL 3 场，另有 CS2、Dota 2 | 无逐行原生赛事 ID/报价时间；仅交叉参考，未编写生产 HTML 采集器 |

两个 JSON 来源的 Valorant 请求均 HTTP 200、返回合法空列表。KashRock 明确说明当前没有 active props。当前证明的是“本轮没有样本”，不能推出全年无覆盖、也不能承诺有稳定 Valorant 数据。

后续实际验证：OddsLink public board 支持 `lol`、`valorant`、`cs2`、`dota2` 参数，LoL / CS2 已取得非空结果。它有近期开赛窗口、最多 60 场和限频，不能称为无限覆盖；已选作正式公共报价入口。guest 保留为低频补充。已有 GRID 权限与 The Odds API 的额度独立管理。

## 数据链与配置

实现：[probe_esports_odds.py](../scripts/devtools/probe_esports_odds.py)。

```text
私有 .env → 共享 SourceSession → 免密钥只读响应 → 形状/游戏校验
    → 现有 SnapshotStore 的 research 命名空间
    → 现有 build_market_search / MarketPanelReader 只读本机 Market
    → 整场胜负候选匹配 / 原始赔率 / 双边比例去水
```

- 基础 Market 的拥有者仍为 `market-data`，复用已有本机数据和读取预算；没有新建 Gamma 采集器，也没有依赖 LOB。
- 本次直接请求 Gamma 遇到 TLS 连接失败；匹配证据来自实际可用的本机 Market，不使用赔率聚合器内置的 Polymarket 行来冒充独立验证。
- 入口通过统一环境加载器读取。新增 `POLYDATA_ODDSLINK_TRY_URL`、`POLYDATA_KASHROCK_DEMO_PROPS_URL`；人工核验参考页使用 `POLYDATA_ODDSLINK_TRY_PAGE_URL`、`POLYDATA_KASHROCK_PUBLIC_URL`、`POLYDATA_PINNODDS_PUBLIC_ESPORTS_URL`。实际 URL 只在私有 `.env`，`.env.example` 留空。
- 代理复用 `POLYMONITOR_SOURCE_ROUTES_JSON`。本次新来源无配置路由，实际使用直连；入口设置 `trust_env=False`，不继承主 Clash。没有增加或改变代理节点。
- 使用 `POLYDATA_SNAPSHOT_SQLITE_PATH` 指向的现有 SQLite。namespace 为 `research:esports:anonymous-odds:v1`；成功响应 key 为 `response:{source}:{game}`，失败尝试为 `attempt:{source}:{game}`，匹配结果为 `assessment:latest`；最多 16 个 key。不写 tmp 文件。
- 这是有界试验快照，不是追加历史。研究回放最长 24 小时，回放保留原 `fetchedAt` / `sourceUpdatedAt`；24 小时保留不表示报价可交易 24 小时。接口失败不覆盖原成功响应，合法空响应可以更新为空。
- 没有生产 API/resource key、浏览器消费者、systemd 服务或自动刷新周期。未来正式接入应由已有体育/电竞领域的数据拥有者统一发布，不能由每个 Panel 页面请求触发采集。

## 独立时钟、预算和恢复

| 项目 | 当前试验契约 |
| --- | --- |
| 来源时间 | 保留 OddsLink 每个 market/book 的 `last_update`，允许未知，不用抓取时间填充 |
| 获取时间 | 请求成功后的 `fetchedAt` |
| 比赛时间 | 来源 `commence_time` 对比本机合约描述中的原定开赛时间；ET 按纽约时区转换 |
| PM 时间 | 分别保留 `quoteUpdatedAt` 与 `observedAt`，不混为当前抓取时间 |
| 检查频率 | 手动；默认仅回放，显式 `--live` 才联网 |
| HTTP 预算 | 每次最多 45 秒，整轮 180 秒，单响应 2 MB；禁自动重定向 |
| 次数预算 | 每轮 2 次 OddsLink guest + 2 次 KashRock demo；guest 每 UTC 日持久计数上限 5，失败也保守计入本机预算 |
| 重试 | 本试验每次仅尝试一次，避免意外消耗配额；不旋转出口绕过限频。后续手动运行可恢复，默认回放不联网 |
| 本机读取 | 每个游戏最多抽 5 场；每场最多 2 个队名查询，每次最多 50 条；复用现有 PostgreSQL 只读并发/statement timeout |
| 失败 | 保存失败类型，不记录带凭据的 URL/代理异常文本；成功数据和旧时间保留，当前失败不会伪装成新成功 |

运行方式（项目根目录）：

```bash
PYTHONPATH=scripts python scripts/devtools/probe_esports_odds.py
# 仅在需要新样本时执行；会占用免费试用次数
PYTHONPATH=scripts python scripts/devtools/probe_esports_odds.py --live
```

## 匹配规范

1. 仅接收目标书商的完整双边 `h2h`，期间必须为完整系列赛。排除聚合器中的 Polymarket/Kalshi，也不混入地图胜负、让局、大小、冠军和球员击杀。
2. 当前接口明确请求 American odds；验证整数且绝对值至少 100，再转换 decimal 与比例去水。不把小数赔率按 American 解释；来源已四舍五入的 American 价格转换后不冒充原始精确 decimal。
3. 两边各自保留原队名、方向与报价，比较时按队名而非 home/away 的数组位置绑定。
4. 游戏、两队、开赛时间（最多相差 5 分钟）、整场胜负都吻合才输出 `same_event_candidate`；不能用 `endDate` 替代开赛时间。名字规范化只处理大小写和标点，不删除 Academy/Team/Gaming，不自动创造别名。
5. 多候选、达到搜索条数上限、缺开赛时间、不同游戏或缺 condition 身份时不自动接受。
6. 保留 PM condition/token/market ID。PM catalog 价格只为指示性快照；不声称可成交，也不计算同步套利空间。
7. 赛事同一性候选与结算规则等价分开。书商 BO 格式、赛事别名以及取消/弃赛/延期规则未核实时，`settlementCompatibility=unverified`、`comparisonReady=false`。

## 2026-11-09 实测记录

正式试验于北京时间 **18:05:25–18:05:30** 运行。4 个响应全部成功写入并读回。加上前面的两次探索，本轮共实际发出 4 次 OddsLink guest 请求，已纳入本机日预算，不再继续消耗。

| LoL 比赛 | 本机 PM market ID | 结果 |
| --- | --- | --- |
| FENNEL — Nothin'Here | 6711874 | 游戏、双方队名、时间、整场胜负匹配 |
| Ground Zero Gaming — Frank Esports | 6337341 | 同上 |
| Bilibili Gaming — Gen.G | 6889027 | 同上 |
| Saigon Warriors — Team Gromp | 6711908 为待核实候选 | PM 是 `Gromp Esports`；不擅自合并别名 |

小范围分母为 **4 场 / 31 条候选记录 / 8 组目标书商双边报价**；3 场同事件候选，1 场别名待核实，0 场完成书商结算等价验证。

BLG 对 Gen.G 样本：Pinnacle 的 BLG 比例去水概率约 **37.98%**，Stake **39.72%**，Thunderpick **39.29%**；本机 PM catalog 为 **37.5%**。外部报价时间约 18:04:50–18:05:20，本机该条 PM 源时间为 17:35:26。它们不是同步可成交报价，差值不构成已验证优势。

自动检查覆盖方向反转、非法赔率、地图/让局排除、跨游戏与跨日期误配、ET 夏令时、不用结算时间冒充开赛时间、多候选拒绝、失败保留旧值、合法空结果，以及跨进程 guest 日预算。测试只证明这些行为；正式采集、自动重连、持续新鲜度、网站显示和完整 Valorant 覆盖均不在本次已完成范围内。
