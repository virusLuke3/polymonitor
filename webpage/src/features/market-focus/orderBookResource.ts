import type { LobPayload } from '@/types';
import type { PanelResource } from '@/panels/usePanelResource';
import { RuntimeResponseError } from '@/panels/runtime-store';
import { fetchMarketLobByToken } from '@/services/api';
import { lobMatchesTokens, timestampMillis } from './orderBook';

// One resource for Detail, Order Book and Summary. No browser persistence.
export function orderBookResource(marketId: number | null, yes: string, no: string): PanelResource<LobPayload> {
  return {
    key: `market-book:v1:${marketId}:${yes}:${no}`, title: 'Market order book',
    // Current book demand/eligibility is rechecked after reload.
    cache: null,
    maxAgeMs: 30_000,
    refreshPolicy: { tier: 'fast', intervalMs: 2000, staleAfterMs: 30_000, requestTimeoutMs: 3500,
      retry: { attempts: 5, baseDelayMs: 2000, maxDelayMs: 60_000 } },
    fetch: context => fetchMarketLobByToken(yes, '', no, 3000, context?.signal, marketId),
    parse: value => {
      if (!value || typeof value !== 'object' || Array.isArray(value)) throw new RuntimeResponseError('Invalid order book');
      const lob = value as LobPayload;
      if (!lobMatchesTokens(lob, yes, no)
        || (lob.marketId != null && lob.marketId !== marketId)
        || (lob.localMarketId != null && lob.localMarketId !== marketId)) {
        throw new RuntimeResponseError('Order book identity mismatch', false);
      }
      if (lob.bookStatus === 'unavailable') throw new RuntimeResponseError('Order book source unavailable');
      for (const side of [lob.yes, lob.no]) {
        if (!side) continue;
        for (const levels of [side.bids, side.asks]) {
          if (levels != null && (!Array.isArray(levels) || levels.length > 1000 || levels.some(level =>
            !level || level.price == null || level.price === '' || !Number.isFinite(Number(level.price))
            || Number(level.price) < 0 || Number(level.price) > 1
            || level.size == null || level.size === '' || !Number.isFinite(Number(level.size)) || Number(level.size) < 0))) {
            throw new RuntimeResponseError('Invalid order book levels');
          }
        }
      }
      return lob;
    },
    // Observation/heartbeat controls retention; event time stays separate.
    updatedAt: lob => {
      const times = [lob.yes, ...(no ? [lob.no] : [])].map(side =>
        timestampMillis(side?.observedAt || side?.heartbeatAt || side?.receivedAt));
      return times.some(time => time == null) ? null : Math.min(...times as number[]);
    },
  };
}
