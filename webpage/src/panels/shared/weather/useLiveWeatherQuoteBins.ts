import { useEffect, useMemo, useState } from 'preact/hooks';
import { fetchMarketLobByToken } from '@/services/api';
import type { LobPayload, RuntimeGlobalWeatherCity, RuntimeWeatherQuoteBin } from '@/types';
import { num, displayQuoteBins } from './model';

type LiveWeatherQuote = Pick<RuntimeWeatherQuoteBin, 'bestBidYes' | 'bestAskYes' | 'bookStatus' | 'priceSource'>;

const LIVE_WEATHER_BOOK_TTL_MS = 10_000;
const LIVE_WEATHER_BOOK_CACHE = new Map<string, { expiresAt: number; quote?: LiveWeatherQuote; promise?: Promise<LiveWeatherQuote> }>();

function bestLevelValue(levels: Array<{ price?: string | number | null }> | undefined, mode: 'bid' | 'ask') {
  const values = (levels || []).map((level) => num(level.price)).filter((value): value is number => value !== null);
  if (!values.length) return null;
  return mode === 'bid' ? Math.max(...values) : Math.min(...values);
}

function quoteFromLob(lob: LobPayload | null): LiveWeatherQuote {
  const yes = lob?.yes || {};
  const bid = num(yes.bestBid) ?? bestLevelValue(yes.bids, 'bid');
  const ask = num(yes.bestAsk) ?? bestLevelValue(yes.asks, 'ask');
  return {
    bestBidYes: bid,
    bestAskYes: ask,
    bookStatus: bid !== null || ask !== null ? 'ok' : (lob?.bookStatus || 'no-book'),
    priceSource: bid !== null || ask !== null ? 'clob-book' : undefined,
  };
}

function liveBookPromise(tokenId: string, title: string) {
  const now = Date.now();
  const cached = LIVE_WEATHER_BOOK_CACHE.get(tokenId);
  if (cached?.quote && cached.expiresAt > now) return Promise.resolve(cached.quote);
  if (cached?.promise && cached.expiresAt > now) return cached.promise;
  const promise = fetchMarketLobByToken(tokenId, title, '', 1800)
    .then((lob) => quoteFromLob(lob))
    .catch((): LiveWeatherQuote => ({ bestBidYes: null, bestAskYes: null, bookStatus: 'error', priceSource: undefined }))
    .then((quote) => {
      LIVE_WEATHER_BOOK_CACHE.set(tokenId, { quote, expiresAt: Date.now() + LIVE_WEATHER_BOOK_TTL_MS });
      return quote;
    });
  LIVE_WEATHER_BOOK_CACHE.set(tokenId, { promise, expiresAt: now + LIVE_WEATHER_BOOK_TTL_MS });
  return promise;
}

function mergeLiveQuote(bin: RuntimeWeatherQuoteBin, quote?: LiveWeatherQuote): RuntimeWeatherQuoteBin {
  if (!quote) return bin;
  const bid = num(quote.bestBidYes);
  const ask = num(quote.bestAskYes);
  const next: RuntimeWeatherQuoteBin = {
    ...bin,
    bookStatus: quote.bookStatus || bin.bookStatus,
  };
  if (bid !== null || ask !== null) {
    next.bestBidYes = bid;
    next.bestAskYes = ask;
    next.priceSource = 'clob-book';
    if (bid !== null && ask !== null) next.midPriceYes = Math.round(((bid + ask) / 2) * 10_000) / 10_000;
  }
  return next;
}

export function useLiveWeatherQuoteBins(city?: RuntimeGlobalWeatherCity | null) {
  const seedBins = useMemo(() => displayQuoteBins(city), [city]);
  const tokenKey = seedBins.map((bin) => String(bin.yesTokenId || '')).filter(Boolean).join('|');
  const [state, setState] = useState<{ key: string; quotes: Record<string, LiveWeatherQuote>; loading: boolean }>({
    key: '',
    quotes: {},
    loading: false,
  });

  useEffect(() => {
    if (!tokenKey) {
      setState({ key: '', quotes: {}, loading: false });
      return;
    }
    let cancelled = false;
    const now = Date.now();
    const immediate: Record<string, LiveWeatherQuote> = {};
    const requests: Array<Promise<[string, LiveWeatherQuote]>> = [];
    for (const bin of seedBins) {
      const tokenId = String(bin.yesTokenId || '').trim();
      if (!tokenId) continue;
      const cached = LIVE_WEATHER_BOOK_CACHE.get(tokenId);
      if (cached?.quote && cached.expiresAt > now) {
        immediate[tokenId] = cached.quote;
        continue;
      }
      requests.push(liveBookPromise(tokenId, String(bin.label || '')).then((quote) => [tokenId, quote]));
    }
    setState({ key: tokenKey, quotes: immediate, loading: requests.length > 0 });
    if (!requests.length) return;
    Promise.all(requests).then((entries) => {
      if (cancelled) return;
      setState({
        key: tokenKey,
        quotes: entries.reduce<Record<string, LiveWeatherQuote>>((acc, [tokenId, quote]) => {
          acc[tokenId] = quote;
          return acc;
        }, { ...immediate }),
        loading: false,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [seedBins, tokenKey]);

  const quotes = state.key === tokenKey ? state.quotes : {};
  return {
    bins: seedBins.map((bin) => mergeLiveQuote(bin, quotes[String(bin.yesTokenId || '')])),
    loading: state.key === tokenKey && state.loading,
  };
}
