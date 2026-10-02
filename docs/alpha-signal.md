# Alpha Signal 实现契约：token-flow-v1

Alpha 展示资金流观测；多因素钱包 PnL/胜率模型仍是规划。本次限定为全市场 token 资金流观测：以真实 token_id 分组，统计来源区块水位之前约 15 分钟净买卖量，与约 60 分钟市场成交基线比较；不读取 outcome_code 推断标签。窗口按区块估算，来源时间单独展示。

- 核验信号必须通过现有 canonical token/source-label 投影、receipt 和 capability 校验。支持实际 Yes/No 或 Up/Down 标签，显示观测到的 token 买卖；不把 Buy No 简化为全市场上涨。
- 标签投影缺失时，只允许显示已核对当前 core.markets token 归属的中性资金流候选。候选与核验信号分开，不能显示 YES/NO、预测方向、价格概率、评分或 STR。冲突、错误 token 以及不支持的标签不能进入此回退。
- 门槛：净方向强度 >= 0.55，并满足主方向流量 >= max($1000,p95)、单笔 >= $2500，或流量 >= $500 且占基线 >= 12% 之一。核验信号评分由净流量/强度/市场占比/价格位置/taker 数构成，是启发式排序，不是收益预测。同市场最多一条，身份使用市场+token+side。
- worker 每 120 秒生成 Redis/SQLite seed；API 只读 seed 并重新核验标签。前端复用共享 PanelResource/runtime，每 30 秒检查并自动展示更新，隐藏时暂停。显式全局资源 key，5 分钟新鲜期、最多 15 分钟旧快照恢复，可用缓存先显示。检查、seed、来源时间分别展示。
- 返回候选/核验/拒绝分母及拒绝原因。来源失败不是 healthy empty；失败时保留上次成功读取的数据及原成功时间，附带最新诊断；HTTP 200 的 degraded 空响应也按失败处理，不能清空已有卡片。候选量受限时标记 truncated。
- UI、解析、样式和资源契约归 alpha-signal 目录；查询/评分归 alpha_signal_service.py；signal_service 保留原 API/worker 兼容入口。调度、取消、重试、可见性与缓存复用共享 runtime，不借用 Whale 面板实现。
