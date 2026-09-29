import type { LobPayload, L2Level } from '@/types';
export type BookSide = 'yes' | 'no';
export type RefreshDirection = 'up' | 'down' | 'flat';

export function liveBookStatus(lob: LobPayload | null | undefined, side: 'yes' | 'no', now = Date.now()) {
  const book = lob?.[side];
  if (!book) return 'unavailable';
  if (book.bookStatus !== 'live') return book.bookStatus || 'unavailable';
  const received = timestampMillis(book.receivedAt);
  const heartbeat = timestampMillis(book.heartbeatAt);
  const deadline = timestampMillis(book.staleAfter);
  return book.continuity === true && received != null && heartbeat != null && deadline != null
    && received <= heartbeat && heartbeat <= now && now - heartbeat <= 20_000 && now < deadline
    ? 'live' : 'stale';
}

export function lobMatchesTokens(lob: LobPayload | null | undefined, yes: string, no: string) {
  return Boolean(lob && yes && lob.yes?.tokenId === yes && (!no || lob.no?.tokenId === no));
}

export function staleLob(lob: LobPayload | null): LobPayload | null {
  if (!lob) return null;
  const stale = (side: LobPayload['yes']) => side ? { ...side, bookStatus: 'stale' as const } : side;
  return { ...lob, bookStatus: 'stale', yes: stale(lob.yes), no: stale(lob.no) };
}

export function timestampMillis(value?: string | null) {
  const parsed = value ? Date.parse(value) : Number.NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

export function hasBookLevels(lob?: LobPayload | null) {
  return Boolean(
    lob
      && ((lob.yes?.asks || []).length
        || (lob.yes?.bids || []).length
        || (lob.no?.asks || []).length
        || (lob.no?.bids || []).length),
  );
}

export function hasSideBookLevels(side?: { asks?: L2Level[]; bids?: L2Level[] } | null) {
  return Boolean(side && ((side.asks || []).length || (side.bids || []).length));
}

function nullableBookNumber(value?: string | number | null) {
  if (value == null || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export function bookMidValue(lob?: LobPayload | null, side: BookSide = 'yes') {
  const book = side === 'no' ? lob?.no : lob?.yes;
  if (!hasSideBookLevels(book)) return null;
  const bid = nullableBookNumber(book?.bestBid);
  const ask = nullableBookNumber(book?.bestAsk);
  if (bid != null && ask != null) return (bid + ask) / 2;
  if (bid != null) return bid;
  if (ask != null) return ask;
  return null;
}

export function directionFromValues(next?: number | null, previous?: number | null): RefreshDirection {
  if (next == null || previous == null || !Number.isFinite(next) || !Number.isFinite(previous)) return 'flat';
  if (next > previous + 0.0001) return 'up';
  if (next < previous - 0.0001) return 'down';
  return 'flat';
}
