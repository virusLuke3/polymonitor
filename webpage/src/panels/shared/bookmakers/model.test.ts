import { describe, expect, it } from 'vitest';
import { currentWinnerQuotes, expire, lineKey, parsePayload, quoteCurrent, safeLink, type Fixture, type Payload, type Quote } from './model';

const now = Date.now();
const quote = { book: 'pinnacle', label: 'Pinnacle', provider: 'oddslink', category: 'sportsbook', market: 'h2h', period: 'full',
  sourceUpdatedAt: new Date(now).toISOString(), url: null, overround: .05,
  outcomes: [{ name: 'A', decimal: 2, implied: .5, probability: .5, point: null }, { name: 'B', decimal: 2, implied: .5, probability: .5, point: null }] } satisfies Quote;
const base = { panelId: 'esports-intel', generatedAt: new Date(now).toISOString(), status: 'ok', items: [], sportsContext: [],
  bookmakerBoard: { schemaVersion: 1, family: 'game', generatedAt: new Date(now).toISOString(), availableFixtures: 1, omittedFixtures: 0, props: [], sources: [],
    fixtures: [{ id: 'x', provider: 'oddslink', tier: 'public-board', sport: 'lol', competition: 'LoL', home: 'A', away: 'B', startTime: new Date(now).toISOString(),
      fetchedAt: new Date(now).toISOString(), sourceStale: false, sourceError: null, quotes: [quote] }] } } satisfies Payload;

describe('bookmaker snapshots', () => {
  it('counts a company once using its newest eligible quote across providers', () => {
    const event: Fixture = structuredClone(base.bookmakerBoard.fixtures[0]!);
    event.quotes = [quote, { ...quote, provider: 'pinnodds', sourceUpdatedAt: null },
      { ...quote, provider: 'other', sourceUpdatedAt: new Date(now - 30_000).toISOString() }];
    expect(currentWinnerQuotes(event, now)).toEqual([quote]);
    expect(event.quotes).toHaveLength(3);
  });
  it('validates coverage independently of the bounded fixture projection', () => {
    const payload = structuredClone(base) as Payload;
    payload.bookmakerBoard.bookmakerCoverage = [{ book: 'ggbet', label: 'GG.BET', category: 'sportsbook',
      fixtures: 30, providers: ['oddsportal'], sports: ['lol'] }];
    expect(parsePayload(payload, true).bookmakerBoard.bookmakerCoverage?.[0]?.fixtures).toBe(30);
    payload.bookmakerBoard.bookmakerCoverage[0]!.fixtures = Number.NaN;
    expect(() => parsePayload(payload, true)).toThrow('Invalid bookmaker coverage');
  });
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
  it('uses provider market confirmation without overwriting the price-change clock', () => {
    const unchanged = { ...quote, sourceUpdatedAt: new Date(now - 86400_000).toISOString(), sourceCheckedAt: new Date(now).toISOString() };
    expect(quoteCurrent(unchanged, now)).toBe(true);
    expect(quoteCurrent({ ...unchanged, sourceCheckedAt: null }, now)).toBe(false);
    expect(quoteCurrent({ ...unchanged, suspended: true }, now)).toBe(false);
    expect(quoteCurrent({ ...unchanged, sourceStale: true }, now)).toBe(false);
    expect(quoteCurrent({ ...unchanged, sourceError: 'HTTP 502' }, now)).toBe(false);
    expect(quoteCurrent({ ...unchanged, phase: 'inplay' }, now + 120_001)).toBe(false);
  });
  it('expires each source quote even when another provider renews the fixture', () => {
    const mixed: Payload = structuredClone(base);
    mixed.bookmakerBoard.fixtures[0]!.quotes.push({ ...quote, provider: 'moviodds',
      receivedAt: new Date(now - 1800_001).toISOString(), retentionSeconds: 1800 });
    const expired = expire(mixed, now);
    expect(expired.bookmakerBoard.fixtures[0]!.quotes).toHaveLength(1);
    expect(expire(expired, now)).toBe(expired);
  });
  it('expires recovered browser data without another network response', () => {
    expect(expire(base, now + 7200_001).bookmakerBoard.fixtures).toHaveLength(0);
  });
  it('uses a slow mirror source own retention and rejects future received clocks', () => {
    const value: Payload = structuredClone(base);
    value.bookmakerBoard.fixtures[0]!.tier = 'mirror-feed';
    value.bookmakerBoard.fixtures[0]!.quotes = [{ ...quote, receivedAt: new Date(now).toISOString(), retentionSeconds: 7200 }];
    expect(expire(value, now + 1900_000).bookmakerBoard.fixtures).toHaveLength(1);
    expect(expire(value, now + 7200_001).bookmakerBoard.fixtures).toHaveLength(0);
    expect(expire(value, now - 60001).bookmakerBoard.fixtures).toHaveLength(0);
  });
  it('does not repeatedly degrade live odds when there are no official score rows', () => {
    const oldOfficial = { ...base, officialGeneratedAt: new Date(now - 3600_000).toISOString() };
    expect(expire(oldOfficial, now)).toBe(oldOfficial);
    const expired = expire(base, now + 7200_001);
    expect(expire(expired, now + 7200_002)).toBe(expired);
  });
  it('separates two and three outcome markets and prohibits unsafe links', () => {
    expect(lineKey(quote)).toBe('2');
    expect(lineKey({ ...quote, outcomes: [...quote.outcomes, { ...quote.outcomes[0]!, name: 'Draw' }] })).toBe('3');
    expect(safeLink('javascript:alert(1)')).toBeUndefined();
    expect(safeLink('https://user:password@example.test')).toBeUndefined();
  });
});
