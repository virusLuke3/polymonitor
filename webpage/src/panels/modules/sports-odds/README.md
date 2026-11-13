# Sports

既有 Panel ID `sports-odds`，默认开启。前端入口 `index.tsx`，共享领域模型和比较表位于 `panels/shared/bookmakers/`。使用 `/runtime/sports/odds-monitor?limit=8`，完整浏览器缓存身份 `bookmakers:sports-odds:8:v4`；十五秒只读共享 WS / 公共快照，不触发外部采集。

The Odds API 和 ESPN 沿用原数据拥有者；公共博彩看板由 bookmaker owner 获取，浏览器不创建第二个采集器。规则测试位于共享模型和 `tests/test_bookmaker_panels.py`。

全部已采集比赛通过同一 owner 的 `/runtime/bookmakers/board` 只读分页，完整 Runtime key 为 `bookmakers:page:v4:<family/sport/provider/search/offset/limit>`，共享实现位于 `panels/shared/bookmakers/resource.ts`。不新增采集器，筛选及翻页不回源；每页 20 场及字节预算见领域契约。

MoviOdds 常驻流与档案复用 bookmaker owner，详细契约见上方领域文档。“历史与赛果”只读 `/runtime/bookmakers/moviodds/archive`，Runtime key 包含 sport/fixture/selection/offset/limit；历史一分钟重读、五分钟缓存新鲜期、最多一天浏览器副本保留。逐点源时间及首次取得时间独立，历史与收盘不混入当前概率。
