# Appointments


本目录拥有本视图及资源声明；共享正文组件与领域类型在 `panels/shared/politics/`。API `/runtime/politics/appointments` 只读既有快照；不在前端采集。数据 owner、来源时钟、持续验证与缺口统一记录在指南的实施清单。默认展示复用全局布局协调。

确认页读取 government owner 的 `judicial-confirmations`（US Courts司法职位名单）；听证页读取 `nomination-hearings` → `hearing:{packageId}`（GovInfo正式出版物及MODS），展示原heldDate/届次/委员会/证人。白宫提交、司法确认、已举行听证分开；未来议程、全行政确认与逐名票仍有限，不按姓名猜PN关联。完整契约与首次采集范围见指南 §10。
