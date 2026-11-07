# Election Watch

实现契约与数据覆盖见 [Politics 指南](../../../../../docs/politics-panels-design.md)。

本目录拥有本视图及资源声明；共享正文组件与领域类型在 `panels/shared/politics/`。API `/runtime/politics/election` 只读既有快照；不在前端采集。数据 owner、来源时钟、持续验证与缺口统一记录在指南的实施清单。默认展示复用全局布局协调。

认证页读取 elections owner 的 `nc-certification-20261103`，由 NCSBE 官方公告展示 pending 与预定州级 canvass。到期后结果未核实仍为 outcome-unverified，不根据票数或时间推断已认证。采集、归档、预算、配置和首次实测边界见指南 §10。
