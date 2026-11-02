# 合约指定源

- Panel ID: `crypto-oracle-reference`。业务 UI 位于本目录；公共壳、图表、币种状态和资源位于 `../../shared/crypto-strategy/`。
- 策略依据：O043 / C081 / G072 / C082。复用既有 workbench 只读来源的合约身份、60 秒官方 TWAP、开盘展示阈值和原始 E18；验证币种、窗口、比较符、合约期限及阈值归属。
- 数据拥有者：共享 `crypto-strategy:four-assets:v1`，由 `usePanelResource` 管理请求、缓存、刷新和取消；不导入其他 Panel 实现。无新增 App 级上下文依赖。Crypto 概览和原有 Funding 另保留自身已验证资源。
- 后端：`scripts/api/services/crypto_strategy/`；唯一写入者 `scripts/runtime/crypto_strategy_watcher.py`；API 只读共享 SQLite。注册在前后端显式 registry。
- 测试：`tests/test_crypto_strategy_inputs.py`、`shared/crypto-strategy/model.test.ts`、`webpage/e2e/crypto-strategy.spec.ts`；保留现有 Crypto/Funding 测试。
- 当前边界：指定源过期就禁用当前距离；开盘展示值保留精度标签。原始窗口贡献和剩余窗口概率未实现；SOL/XRP 暂无绑定。

完整依赖、运行和验收说明见 `docs/crypto-strategy-panels.md`。
