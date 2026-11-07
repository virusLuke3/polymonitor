# Campaign Finance

实现契约与数据覆盖见 [Politics 指南](../../../../../docs/politics-panels-design.md)。

本目录拥有本视图及资源声明；共享正文组件与领域类型在 `panels/shared/politics/`。API `/runtime/politics/campaign-finance` 只读既有快照；不在前端采集。数据 owner、来源时钟、持续验证与缺口统一记录在指南的实施清单。默认展示复用全局布局协调。

独立支出/修订页复用 campaign-finance owner 的 `fec-independent-{cycle}`，来源为官方24/48小时通知CSV；保留原文和修订链，整份 superseded 申报不重复显示，不计算跨报告总额。方向未知逐项隔离并显示分母；API最多各100条，原文全部归档。完整契约与首次采集范围见指南 §10。
