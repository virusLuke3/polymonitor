import type { LobPayload, RuntimeWeatherQuoteBin } from '@/types';
import { num } from './model';

export type LiveWeatherQuote = Pick<RuntimeWeatherQuoteBin,
  'bestBidYes' | 'bestAskYes' | 'bookStatus' | 'priceSource' | 'quoteUpdatedAt' | 'quoteObservedAt' | 'quoteStaleAfter'>;
export const RETAINED_BOOK_MS = 2 * 60 * 60 * 1000;

function bestLevel(levels: Array<{ price?: string | number | null }> | undefined, bid: boolean) {
  const prices = (levels || []).map(level => num(level.price)).filter((value): value is number => value !== null && value >= 0 && value <= 1);
  return prices.length ? (bid ? Math.max(...prices) : Math.min(...prices)) : null;
}
function recent(value: string | null | undefined, age: number, now: number) {
  const time = Date.parse(value || '');
  return Number.isFinite(time) && time <= now && now - time < age;
}
function empty(bookStatus: string): LiveWeatherQuote {
  return { bestBidYes: null, bestAskYes: null, bookStatus };
}

/** Native snapshots and continuous live books have different evidence contracts. */
export function quoteFromLob(lob: LobPayload | null, now = Date.now(), token?: string): LiveWeatherQuote {
  const yes = lob?.yes;
  const status = yes?.bookStatus || lob?.bookStatus || 'unavailable';
  if (token && yes?.tokenId !== token) return empty('unavailable');
  if (yes?.eventAt && (!Number.isFinite(Date.parse(yes.eventAt)) || Date.parse(yes.eventAt) > now)) return empty('invalid');
  const continuous = status === 'live' && yes?.continuity === true
    && Date.parse(yes.staleAfter || '') > now && recent(yes.heartbeatAt, 20_000, now)
    && Number.isFinite(Date.parse(yes.receivedAt || '')) && Date.parse(yes.receivedAt || '') <= Date.parse(yes.heartbeatAt || '');
  const snapshot = status === 'available' && yes?.upstreamReady === true && recent(yes.observedAt, 30_000, now);
  const eventTime = yes?.eventAt || (continuous ? yes?.receivedAt : undefined);
  const retained = ['live', 'available', 'stale'].includes(status) && recent(eventTime, RETAINED_BOOK_MS, now);
  if (!continuous && !snapshot && !retained) return empty(['live', 'available', 'stale'].includes(status) ? 'stale' : status);
  const bid = num(yes?.bestBid) ?? bestLevel(yes?.bids, true);
  const ask = num(yes?.bestAsk) ?? bestLevel(yes?.asks, false);
  if ([yes?.bestBid, yes?.bestAsk].some(value => value != null && num(value) === null) || [bid, ask].some(value => value !== null && (value < 0 || value > 1)) || (bid !== null && ask !== null && bid > ask)) return empty('invalid');
  if (bid === null && ask === null) return empty('no-book');
  return { bestBidYes: bid, bestAskYes: ask, bookStatus: continuous ? 'ok' : snapshot ? 'snapshot' : 'retained',
    priceSource: continuous ? 'clob-book' : snapshot ? 'clob-snapshot' : 'previous-book',
    quoteUpdatedAt: eventTime, quoteObservedAt: yes?.observedAt,
    quoteStaleAfter: continuous ? yes?.staleAfter : new Date(snapshot
      ? Date.parse(yes?.observedAt || '') + 30_000 : Date.parse(eventTime || '') + RETAINED_BOOK_MS).toISOString() };
}

export function mergeLiveQuote(bin: RuntimeWeatherQuoteBin, quote?: LiveWeatherQuote, now = Date.now()): RuntimeWeatherQuoteBin {
  // A response with an empty book is authoritative; request errors are retained by the shared Runtime.
  const value = quote || bin;
  const bid = num(value.bestBidYes), ask = num(value.bestAskYes);
  const pricesValid = [bid, ask].every(price => price === null || (price >= 0 && price <= 1))
    && (bid === null || ask === null || bid <= ask);
  const current = ['ok', 'live', 'snapshot'].includes(value.bookStatus || '') && Date.parse(value.quoteStaleAfter || '') > now;
  const retained = ['ok', 'live', 'snapshot', 'retained'].includes(value.bookStatus || '') && recent(value.quoteUpdatedAt, RETAINED_BOOK_MS, now);
  if (!pricesValid || (!current && !retained) || (bid === null && ask === null)) return { ...bin, ...value,
    bestBidYes: null, bestAskYes: null, midPriceYes: null, priceSource: undefined,
    bookStatus: !pricesValid ? 'invalid' : ['ok', 'live', 'snapshot', 'retained'].includes(value.bookStatus || '') ? 'stale' : value.bookStatus };
  return { ...bin, ...value, bestBidYes: bid, bestAskYes: ask,
    midPriceYes: bid !== null && ask !== null ? (bid + ask) / 2 : null,
    bookStatus: current ? value.bookStatus : 'retained',
    priceSource: current ? value.priceSource : 'previous-book',
    quoteStaleAfter: current ? value.quoteStaleAfter : new Date(Date.parse(value.quoteUpdatedAt || '') + RETAINED_BOOK_MS).toISOString() };
}
