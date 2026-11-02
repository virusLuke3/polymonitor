# 交易所链上流入

- Panel ID: `crypto-exchange-inflow`。业务 UI 位于本目录；公共壳、图表、币种状态和资源位于 `../../shared/crypto-strategy/`。
- 策略依据：Q076。复用现有 Dune BTC 历史研究归档，按日期与 Binance/Coinbase 聚合转入、转出、净额；30/90/180 日历天。
- 数据拥有者：共享 `crypto-strategy:four-assets:v1`，由 `usePanelResource` 管理请求、缓存、刷新和取消；不导入其他 Panel 实现。无新增 App 级上下文依赖。Crypto 概览和原有 Funding 另保留自身已验证资源。
- 后端：`scripts/api/services/crypto_strategy/`；唯一写入者 `scripts/runtime/crypto_strategy_watcher.py`；API 只读共享 SQLite。注册在前后端显式 registry。
- 测试：`tests/test_crypto_strategy_inputs.py`、`shared/crypto-strategy/model.test.ts`、`webpage/e2e/crypto-strategy.spec.ts`；保留现有 Crypto/Funding 测试。
- 当前边界：实时来源未接入；标签为事后获取，严格 PIT 未验收；转入不是卖出，未识别内部转账仍可能存在。

完整依赖、运行和验收说明见 `docs/crypto-strategy-panels.md`。
