import { describe, expect, it } from 'vitest';
import { expire, lineKey, parsePayload, quoteCurrent, safeLink, type Payload, type Quote } from './model';

const now = Date.now();
const quote = { book: 'pinnacle', label: 'Pinnacle', provider: 'oddslink', category: 'sportsbook', market: 'h2h', period: 'full',
  sourceUpdatedAt: new Date(now).toISOString(), url: null, overround: .05,
  outcomes: [{ name: 'A', decimal: 2, implied: .5, probability: .5, point: null }, { name: 'B', decimal: 2, implied: .5, probability: .5, point: null }] } satisfies Quote;
const base = { panelId: 'esports-intel', generatedAt: new Date(now).toISOString(), status: 'ok', items: [], sportsContext: [],
  bookmakerBoard: { schemaVersion: 1, family: 'game', generatedAt: new Date(now).toISOString(), availableFixtures: 1, omittedFixtures: 0, props: [], sources: [],
    fixtures: [{ id: 'x', provider: 'oddslink', tier: 'public-board', sport: 'lol', competition: 'LoL', home: 'A', away: 'B', startTime: new Date(now).toISOString(),
      fetchedAt: new Date(now).toISOString(), sourceStale: false, sourceError: null, quotes: [quote] }] } } satisfies Payload;

describe('bookmaker snapshots', () => {
  it('rejects cross-panel cache and broken probabilities', () => {
    expect(() => parsePayload(base, false)).toThrow();
    const corrupt = structuredClone(base);
    corrupt.bookmakerBoard.fixtures[0]!.quotes[0]!.outcomes[0]!.probability = .8;
    expect(() => parsePayload(corrupt, true)).toThrow();
  });
  it('does not use fetch time as the quote clock', () => {
    expect(quoteCurrent({ ...quote, sourceUpdatedAt: null }, now)).toBe(false);
    expect(quoteCurrent({ ...quote, sourceUpdatedAt: new Date(now - 1900_000).toISOString() }, now)).toBe(false);
    expect(quoteCurrent(quote, now)).toBe(true);
  });
  it('expires recovered browser data without another network response', () => {
    expect(expire(base, now + 7200_001).bookmakerBoard.fixtures).toHaveLength(0);
  });
  it('separates two and three outcome markets and prohibits unsafe links', () => {
    expect(lineKey(quote)).toBe('2');
    expect(lineKey({ ...quote, outcomes: [...quote.outcomes, { ...quote.outcomes[0]!, name: 'Draw' }] })).toBe('3');
    expect(safeLink('javascript:alert(1)')).toBeUndefined();
    expect(safeLink('https://user:password@example.test')).toBeUndefined();
  });
});
