# 期权隐含概率

- Panel ID: `options-implied-probability`。业务 UI 位于本目录；公共壳、图表、币种状态和资源位于 `../../shared/crypto-strategy/`。
- 策略依据：O041 / C075 / Q074 / G077。BTC/ETH、未来七天中最多三个到期、真实双边报价支持的看涨价差概率带与买卖区间。
- 数据拥有者：共享 `crypto-strategy:four-assets:v1`，由 `usePanelResource` 管理请求、缓存、刷新和取消；不导入其他 Panel 实现。无新增 App 级上下文依赖。Crypto 概览和原有 Funding 另保留自身已验证资源。
- 后端：`scripts/api/services/crypto_strategy/`；唯一写入者 `scripts/runtime/crypto_strategy_watcher.py`；API 只读共享 SQLite。注册在前后端显式 registry。
- 测试：`tests/test_crypto_strategy_inputs.py`、`shared/crypto-strategy/model.test.ts`、`webpage/e2e/crypto-strategy.spec.ts`；保留现有 Crypto/Funding 测试。
- 当前边界：折现因子假设为 1；是阈值带平均风险中性尾概率参考，不是精确数字期权概率。未与 PM 到期匹配，不给 PM 概率差或交易结论。
