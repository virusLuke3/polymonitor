# Nomination Path

实现契约与数据覆盖见 [Politics 指南](../../../../../docs/politics-panels-design.md)。

本目录拥有本视图及资源声明；共享正文组件与领域类型在 `panels/shared/politics/`。API `/runtime/politics/nomination` 只读既有快照；不在前端采集。数据 owner、来源时钟、持续验证与缺口统一记录在指南的实施清单。默认展示复用全局布局协调。

NC 2026 国会初选的总统代表票明确不适用；代表票页单独读取 elections owner 的 `dnc-roll-call-2024` 历史全国党代会结果，不混用年份/赛事或用普通选票推算。门槛与未分配票未见该结果页证据，保持未知。完整契约与首次采集范围见指南 §10。
