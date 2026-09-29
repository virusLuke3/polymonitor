import { describe, expect, it } from 'vitest';
import { compactTimeLabel, marketLifecycleIsClosed } from './FocusedMarketStrip';
import { bookMidValue, liveBookStatus, lobMatchesTokens, staleLob } from '@/features/market-focus/orderBook';
import type { LobPayload } from '@/types';

describe('live book provenance', () => {
  const now = Date.parse('2026-09-27T12:00:00Z');
  const live: LobPayload = {
    marketId: 1,
    fetchedAt: new Date(now).toISOString(),
    yes: {
      tokenId: '123', bookStatus: 'live', continuity: true,
      receivedAt: new Date(now - 120_000).toISOString(),
      heartbeatAt: new Date(now - 1_000).toISOString(),
      staleAfter: new Date(now + 19_000).toISOString(),
      bids: [{ price: '.4', size: '10' }], asks: [{ price: '.5', size: '20' }],
    },
  };

  it('allows a quiet continuous book, but expires it without another HTTP response', () => {
    expect(liveBookStatus(live, 'yes', now)).toBe('live');
    expect(liveBookStatus(live, 'yes', now + 20_000)).toBe('stale');
  });

  it('never treats response time or levels as freshness evidence', () => {
    expect(liveBookStatus({ ...live, yes: { ...live.yes, heartbeatAt: null } }, 'yes', now)).toBe('stale');
    expect(liveBookStatus({ ...live, yes: { ...live.yes, continuity: false } }, 'yes', now)).toBe('stale');
    expect(liveBookStatus({ ...live, yes: { bids: live.yes?.bids } }, 'yes', now)).toBe('unavailable');
  });

  it('preserves old levels after a failed fetch while withdrawing live status', () => {
    const stale = staleLob(live);
    expect(stale?.yes?.bids).toEqual(live.yes?.bids);
    expect(liveBookStatus(stale, 'yes', now)).toBe('stale');
    expect(liveBookStatus(live, 'yes', now)).toBe('live');
  });

  it('rejects another outcome and requires both requested token identities', () => {
    expect(lobMatchesTokens(live, '123', '')).toBe(true);
    expect(lobMatchesTokens(live, '456', '')).toBe(false);
    expect(lobMatchesTokens(live, '123', '456')).toBe(false);
    expect(liveBookStatus({ ...live, yes: { ...live.yes, bookStatus: 'warming' } }, 'yes', now)).toBe('warming');
  });
});


describe('FocusedMarketStrip closed-market evidence', () => {
  it('does not coerce nullable empty-book prices into a zero midpoint', () => {
    expect(bookMidValue({
      marketId: 3712655,
      yes: { bestBid: null, bestAsk: null, bids: [], asks: [] },
      no: { bestBid: null, bestAsk: null, bids: [], asks: [] },
    })).toBeNull();
    expect(bookMidValue({
      marketId: 3712655,
      yes: { bestBid: 0, bestAsk: 0, bids: [], asks: [] },
      no: { bestBid: 0, bestAsk: 0, bids: [], asks: [] },
    })).toBeNull();
  });

  it('does not call a historical final chart tick Now', () => {
    const timestamp = Date.parse('2026-08-13T12:34:00Z');

    expect(compactTimeLabel(timestamp, 3, 4, false)).not.toBe('Now');
    expect(compactTimeLabel(timestamp, 3, 4, true)).toBe('Now');
  });

  it('recognizes closed and awaiting-oracle lifecycle evidence', () => {
    expect(marketLifecycleIsClosed(true, 'Active')).toBe(true);
    expect(marketLifecycleIsClosed(false, 'Closed')).toBe(true);
    expect(marketLifecycleIsClosed(false, 'Awaiting Oracle')).toBe(true);
    expect(marketLifecycleIsClosed(false, 'Active')).toBe(false);
  });
});
