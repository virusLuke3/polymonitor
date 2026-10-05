import { useMemo } from 'preact/hooks';
import { fetchMarketLobByToken } from '@/services/api';
import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import type { RuntimeGlobalWeatherCity, RuntimeWeatherQuoteBin } from '@/types';
import { displayQuoteBins } from './model';
import { mergeLiveQuote, quoteFromLob, type LiveWeatherQuote } from './quote';

type QuoteSnapshot = { checkedAt: number; status: string; quotes: Record<string, LiveWeatherQuote> };
export const WEATHER_QUOTE_REFRESH_MS = 15_000;

export function weatherQuoteResource(bins: RuntimeWeatherQuoteBin[]): PanelResource<QuoteSnapshot> {
  const tokens = [...new Set(bins.map(bin => String(bin.yesTokenId || '').trim()).filter(Boolean))].sort();
  return {
    key: `weather:books:v2:${tokens.join(',') || 'none'}`, title: 'Weather books',
    maxAgeMs: 20_000, staleAgeMs: 120_000, acceptStale: true,
    refreshPolicy: { tier: 'fast', intervalMs: WEATHER_QUOTE_REFRESH_MS, staleAfterMs: 20_000, requestTimeoutMs: 12_000 },
    updatedAt: value => value.checkedAt,
    parse: value => {
      const snapshot = value as QuoteSnapshot;
      if (!snapshot || !Number.isFinite(snapshot.checkedAt) || !snapshot.quotes || tokens.some(token => !snapshot.quotes[token])) {
        throw new Error('Invalid weather quote response');
      }
      return snapshot;
    },
    fetch: async context => {
      const quotes: Record<string, LiveWeatherQuote> = {};
      let index = 0;
      // Share the public runtime's cancellation, visibility and single flight.
      // Four concurrent reads bound demand on the live book exporter.
      await Promise.all(Array.from({ length: Math.min(4, tokens.length) }, async () => {
        while (index < tokens.length) {
          context?.signal?.throwIfAborted();
          const token = tokens[index++];
          if (!token) continue;
          try {
            quotes[token] = quoteFromLob(await fetchMarketLobByToken(token, '', '', 2500, context?.signal));
          } catch (error) {
            context?.signal?.throwIfAborted();
            quotes[token] = { bestBidYes: null, bestAskYes: null, bookStatus: 'error' };
          }
        }
      }));
      const values = Object.values(quotes);
      return { checkedAt: Date.now(), quotes, status: values.every(quote => quote.bookStatus === 'ok') ? 'ok' : 'partial' };
    },
  };
}

export function useLiveWeatherQuoteBins(city?: RuntimeGlobalWeatherCity | null) {
  const seedBins = displayQuoteBins(city);
  const identity = seedBins.map(bin => bin.yesTokenId || '').filter(Boolean).sort().join('|');
  const contract = useMemo(() => weatherQuoteResource(seedBins), [identity]);
  const feed = usePanelResource(contract, Boolean(identity));
  const quotes = feed.data?.quotes || {};
  return { ...feed, bins: seedBins.map(bin => mergeLiveQuote(bin, quotes[String(bin.yesTokenId || '')])),
    loading: Boolean(identity) && feed.loading, checkedAt: feed.status.checkedAt,
    refreshing: feed.status.fetching };
}
