# 稳定币压力

- Panel ID: `stablecoin-monitor`。业务 UI 位于本目录；公共壳、图表、币种状态和资源位于 `../../shared/crypto-strategy/`。
- 策略依据：Q079。USDC/USDT 的 Coinbase 与 Kraken USD 报价、偏离 bps、来源差异和观测持续时间。
- 数据拥有者：共享 `crypto-strategy:four-assets:v1`，由 `usePanelResource` 管理请求、缓存、刷新和取消；不导入其他 Panel 实现。无新增 App 级上下文依赖。Crypto 概览和原有 Funding 另保留自身已验证资源。
- 后端：`scripts/api/services/crypto_strategy/`；唯一写入者 `scripts/runtime/crypto_strategy_watcher.py`；API 只读共享 SQLite。注册在前后端显式 registry。
- 测试：`tests/test_crypto_strategy_inputs.py`、`shared/crypto-strategy/model.test.ts`、`webpage/e2e/crypto-strategy.spec.ts`；保留现有 Crypto/Funding 测试。
- 当前边界：连续采样缺口重置持续时间；无原生报价时间时明确为接收时间。不是完整压力事件档案。

完整依赖、运行和验收说明见 `docs/crypto-strategy-panels.md`。
