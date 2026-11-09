# Sports

既有 Panel ID `sports-odds`，默认开启。前端入口 `index.tsx`，共享领域模型和比较表位于 `panels/shared/bookmakers/`。使用 `/runtime/sports/odds-monitor?limit=8`，完整浏览器缓存身份 `bookmakers:sports-odds:8:v1`；五分钟重读持久快照，不触发外部采集。

数据链、源地址环境变量、SQLite evidence / SnapshotStore 身份、三个独立时钟、保留和恢复规则、报价比较口径及发布验收见 [领域契约](../../../../../docs/sports-game-panels.md)。The Odds API 和 ESPN 沿用原数据拥有者；公共博彩看板由 bookmaker owner 获取，浏览器不创建第二个采集器。规则测试位于共享模型和 `tests/test_bookmaker_panels.py`。
