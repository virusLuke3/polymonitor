import { useMemo } from 'preact/hooks';
import { fetchWeatherBooks } from '@/services/api';
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
    refreshPolicy: { tier: 'fast', intervalMs: WEATHER_QUOTE_REFRESH_MS, staleAfterMs: 20_000, requestTimeoutMs: 25_000 },
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
      const response = await fetchWeatherBooks(tokens, context?.signal);
      for (const token of tokens) quotes[token] = quoteFromLob(response.books[token] || null);
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
