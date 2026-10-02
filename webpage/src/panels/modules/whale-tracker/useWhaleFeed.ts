import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import { fetchRuntimeWhales } from '@/services/api';
import { parseTradeFeed, tradeStatusLabel, TRADE_REFRESH_MS, TRADE_MAX_AGE_MS, TRADE_RECOVERY_AGE_MS, type TradeFeed } from '@/panels/shared/trade-feed/model';

export const WHALE_LIMIT = 14;
export const whaleResource: PanelResource<TradeFeed> = {
  key: `whale-tracker:global:trade-watch-v1:${WHALE_LIMIT}`, title: 'Whale Tracker',
  maxAgeMs: TRADE_MAX_AGE_MS, staleAgeMs: TRADE_RECOVERY_AGE_MS, acceptStale: true,
  cache: { version: 1, maxChars: 96_000 },
  refreshPolicy: { tier: 'fast', intervalMs: TRADE_REFRESH_MS, staleAfterMs: TRADE_MAX_AGE_MS },
  fetch: ctx => fetchRuntimeWhales(WHALE_LIMIT, ctx?.signal),
  parse: value => {
    const data = parseTradeFeed(value, 'whale-trades');
    if (data.status === 'degraded' && !data.items.length) throw new Error(data.error || 'Whale source unavailable');
    return data;
  },
  updatedAt: value => Date.parse(value.generatedAt), statusLabel: tradeStatusLabel,
  shouldPersist: value => ['ok', 'empty', 'partial'].includes(value.status),
};
export const useWhaleFeed = () => usePanelResource(whaleResource);
