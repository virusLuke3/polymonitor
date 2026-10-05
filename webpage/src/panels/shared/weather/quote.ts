import type { LobPayload, RuntimeWeatherQuoteBin } from '@/types';
import { num } from './model';

export type LiveWeatherQuote = Pick<RuntimeWeatherQuoteBin,
  'bestBidYes' | 'bestAskYes' | 'bookStatus' | 'priceSource' | 'quoteUpdatedAt' | 'quoteStaleAfter'>;

function bestLevel(levels: Array<{ price?: string | number | null }> | undefined, bid: boolean) {
  const prices = (levels || []).map(level => num(level.price)).filter((value): value is number => value !== null && value >= 0 && value <= 1);
  return prices.length ? (bid ? Math.max(...prices) : Math.min(...prices)) : null;
}

export function quoteFromLob(lob: LobPayload | null, now = Date.now()): LiveWeatherQuote {
  const yes = lob?.yes;
  const status = yes?.bookStatus || lob?.bookStatus || 'unavailable';
  const deadline = Date.parse(yes?.staleAfter || '');
  const heartbeat = Date.parse(yes?.heartbeatAt || '');
  const received = Date.parse(yes?.receivedAt || '');
  if (status !== 'live' || yes?.continuity !== true || !Number.isFinite(deadline) || deadline <= now
    || !Number.isFinite(heartbeat) || heartbeat > now + 60_000 || now - heartbeat > 20_000
    || !Number.isFinite(received) || received > heartbeat) {
    return { bestBidYes: null, bestAskYes: null, bookStatus: status === 'live' ? 'stale' : status };
  }
  const bid = num(yes?.bestBid) ?? bestLevel(yes?.bids, true);
  const ask = num(yes?.bestAsk) ?? bestLevel(yes?.asks, false);
  if ([bid, ask].some(value => value !== null && (value < 0 || value > 1)) || (bid !== null && ask !== null && bid > ask)) {
    return { bestBidYes: null, bestAskYes: null, bookStatus: 'invalid' };
  }
  return { bestBidYes: bid, bestAskYes: ask, bookStatus: bid !== null || ask !== null ? 'ok' : 'no-book',
    priceSource: bid !== null || ask !== null ? 'clob-book' : undefined,
    quoteUpdatedAt: yes?.receivedAt, quoteStaleAfter: yes?.staleAfter };
}

export function mergeLiveQuote(bin: RuntimeWeatherQuoteBin, quote?: LiveWeatherQuote, now = Date.now()): RuntimeWeatherQuoteBin {
  if (!quote) {
    if (bin.quoteStaleAfter && Date.parse(bin.quoteStaleAfter) <= now) {
      return { ...bin, bestBidYes: null, bestAskYes: null, bookStatus: 'stale',
        priceSource: bin.priceSource === 'clob-book' ? 'previous-book' : bin.priceSource };
    }
    return bin;
  }
  const valid = quote.bookStatus === 'ok' && Date.parse(quote.quoteStaleAfter || '') > now;
  const bid = valid ? num(quote.bestBidYes) : null;
  const ask = valid ? num(quote.bestAskYes) : null;
  return { ...bin, ...quote, bestBidYes: bid, bestAskYes: ask,
    bookStatus: quote.bookStatus === 'ok' && !valid ? 'stale' : quote.bookStatus,
    midPriceYes: bid !== null && ask !== null ? (bid + ask) / 2 : bin.midPriceYes,
    priceSource: bid !== null && ask !== null ? 'clob-book' : bin.priceSource === 'clob-book' ? 'previous-book' : bin.priceSource };
}
