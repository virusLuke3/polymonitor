import { describe, expect, it } from 'vitest';
import { catalogCurrent, matchCurrent, validMatch, type MatchedMarket, type Match } from './matching';

const now = Date.now();
const market: MatchedMarket = { marketId: '1', conditionId: `0x${'1'.repeat(64)}`, title: 'A vs B', slug: 'a-b', type: 'h2h', metric: 'match', period: 'full',
  line: null, handicapTeam: null, observedAt: new Date(now).toISOString(), sourceUpdatedAt: null, url: null, settlement: 'unknown', reason: 'rules_unverified', comparisonReady: false,
  outcomes: [{ tokenId: '1', label: 'A', catalogPrice: .4 }, { tokenId: '2', label: 'B', catalogPrice: .6 }],
  books: [{ book: 'book', provider: 'feed', pairs: [{ selection: 'B', tokenId: '2' }, { selection: 'A', tokenId: '1' }] }] };
const match: Match = { state: 'linked', reason: 'exact', checkedAt: now / 1000, markets: [market] };
describe('matching evidence boundary', () => {
  it('checks actual condition and outcome identities from unknown input', () => {
    expect(validMatch(match)).toBe(true);
    expect(validMatch({ ...match, markets: [{ ...market, conditionId: 'wrong' }] })).toBe(false);
    expect(validMatch({ ...match, markets: [{ ...market, outcomes: [market.outcomes[0], market.outcomes[0]] }] })).toBe(false);
    expect(validMatch({ ...match, markets: [{ ...market, books: [{ ...market.books[0], pairs: [{ selection: 'A', tokenId: '3' }] }] }] })).toBe(false);
    expect(validMatch({ ...match, markets: [{ ...market, comparisonReady: true }] })).toBe(false);
  });
  it('expires identity checks and catalog prices independently even after cache restore', () => {
    expect(matchCurrent(match, now + 120001)).toBe(true);
    expect(catalogCurrent(market, now + 120001)).toBe(false);
    expect(matchCurrent(match, now + 600001)).toBe(false);
    expect(matchCurrent({ ...match, stale: true }, now)).toBe(false);
    expect(matchCurrent({ ...match, checkedAt: (now + 120000) / 1000 }, now)).toBe(false);
    expect(matchCurrent({ ...match, verifiedAt: (now - 600001) / 1000 }, now)).toBe(false);
    expect(matchCurrent({ ...match, state: 'unavailable' }, now)).toBe(false);
  });
  it('distinguishes no match from an unavailable search', () => {
    expect(validMatch({ state: 'unavailable', reason: 'catalog_timeout', markets: [] })).toBe(true);
    expect(validMatch({ state: 'unknown', reason: 'anything', markets: [] })).toBe(false);
  });
});


it('accepts a three-way complement and explicit rule conflicts without enabling arbitrage', () => {
  const football = { ...market, settlement: 'conflict', books: [{ book: 'book', provider: 'feed',
    pairs: [{ selection: 'A', tokenId: '1' }, { selection: 'Draw', tokenId: '2' }, { selection: 'B', tokenId: '2' }],
    ruleCheck: { status: 'conflict', reasons: [], scenarios: [{ case: 'equal_to_line', bookmaker: 'stake_refund', polymarket: 'split' }] } }] };
  expect(validMatch({ ...match, markets: [football] })).toBe(true);
  expect(validMatch({ ...match, markets: [{ ...football, comparisonReady: true }] })).toBe(false);
});
