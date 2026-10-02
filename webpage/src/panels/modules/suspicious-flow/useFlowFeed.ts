import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import { fetchRuntimeSuspicious } from '@/services/api';
import { parseTradeFeed, tradeStatusLabel, TRADE_REFRESH_MS, TRADE_MAX_AGE_MS, TRADE_RECOVERY_AGE_MS, type TradeFeed } from '@/panels/shared/trade-feed/model';

export const FLOW_LIMIT = 12;
export const flowResource: PanelResource<TradeFeed> = {
  key: `suspicious-flow:global:trade-watch-v1:${FLOW_LIMIT}`, title: 'Flow Watch',
  maxAgeMs: TRADE_MAX_AGE_MS, staleAgeMs: TRADE_RECOVERY_AGE_MS, acceptStale: true,
  cache: { version: 1, maxChars: 96_000 },
  refreshPolicy: { tier: 'fast', intervalMs: TRADE_REFRESH_MS, staleAfterMs: TRADE_MAX_AGE_MS },
  fetch: ctx => fetchRuntimeSuspicious(FLOW_LIMIT, ctx?.signal),
  parse: value => {
    const data = parseTradeFeed(value, 'flow-watch');
    if (data.status === 'degraded' && !data.items.length) throw new Error(data.error || 'Flow source unavailable');
    return data;
  },
  updatedAt: value => Date.parse(value.generatedAt), statusLabel: tradeStatusLabel,
  shouldPersist: value => ['ok', 'empty', 'partial'].includes(value.status),
};
export const useFlowFeed = () => usePanelResource(flowResource);
