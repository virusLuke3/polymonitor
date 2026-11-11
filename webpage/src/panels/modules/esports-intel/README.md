# Game

既有 Panel ID `esports-intel`，默认开启。前端入口 `index.tsx`，共享领域模型和比较表位于 `panels/shared/bookmakers/`。使用 `/runtime/esports/grid-intel?limit=10`，完整浏览器缓存身份 `bookmakers:esports-intel:10:v3`；两分钟重读存储以兼容原 GRID 赛况，公共赔率自身十五分钟获取，演示/guest 每日获取。

数据链、源环境变量、存储身份、独立报价/采集/比赛时间、恢复预算、限制和验收见 [领域契约](../../../../../docs/sports-game-panels.md)。保留 GRID 官方赛况消费者与 OpenDota 历史消费者；博彩公司赔率不冒充官方赛况，单边 GG.bet 道具样本不冒充完整实时胜率。测试复用共享模型及 `tests/test_bookmaker_panels.py`。

全部已采集比赛通过同一 owner 的 `/runtime/bookmakers/board` 只读分页，完整 Runtime key 为 `bookmakers:page:v3:<family/sport/provider/search/offset/limit>`，共享实现位于 `panels/shared/bookmakers/resource.ts`。不新增采集器，筛选及翻页不回源；每页 20 场及字节预算见领域契约。
