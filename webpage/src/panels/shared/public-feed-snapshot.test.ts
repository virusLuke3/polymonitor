import { describe, expect, it } from 'vitest';
import { publicFeedSnapshot } from './public-feed-snapshot';
import { parseRuntimeSnapshot } from '../runtime-store';
import type { PanelModule } from '../types';

describe('public feed persistence contracts', () => {
  const generatedAt = new Date().toISOString();
  it('isolates panel and request limit, rejects failed snapshots and bounds rows', () => {
    const contract = publicFeedSnapshot('nba-scoreboard', 1);
    expect(contract.key).not.toBe(publicFeedSnapshot('nba-scoreboard', 10).key);
    expect(contract.key).not.toBe(publicFeedSnapshot('nba-intel', 1).key);
    const value = { generatedAt, items: [{ id: 'game' }, { id: 'second' }] };
    expect(contract.parse(value)).toMatchObject({ items: [{ id: 'game' }] });
    for (const status of ['error', 'warming', 'unavailable', 'invalid']) expect(() => contract.parse({ ...value, status })).toThrow();
    expect(() => contract.parse({ ...value, panelId: 'nba-intel' })).toThrow('identity');
    expect(() => contract.parse({ ...value, generatedAt: '' })).toThrow();
  });
  it('preserves source time and explicit partial states; rejects overdue data through the shared parser', () => {
    const contract = publicFeedSnapshot('defi-token-watch', 10);
    const old = new Date(Date.now() - 20 * 60_000).toISOString();
    const value = { generatedAt: old, status: 'stale', items: [{ id: 'uni', price: 7 }] };
    const panel = { id: 'defi-token-watch', snapshot: contract } as PanelModule;
    expect(parseRuntimeSnapshot(panel, value)).toMatchObject({ generatedAt: old, status: 'stale' });
    expect(() => parseRuntimeSnapshot(panel, { ...value, generatedAt: new Date(Date.now() - 24 * 60 * 60_000).toISOString() })).toThrow('overdue');
    expect(contract.parse({ ...value, generatedAt, status: 'ok', sources: { provider: 'error' } })).toMatchObject({ status: 'degraded' });
  });
  it('validates nested lineups and feed cards without losing legitimate empty results', () => {
    const nba = publicFeedSnapshot('nba-intel', 12);
    expect(nba.parse({ generatedAt, items: [], lineups: [], status: 'empty' })).toMatchObject({ items: [], lineups: [], status: 'empty' });
    expect(() => nba.parse({ generatedAt, items: [], lineups: {} })).toThrow();
    expect(nba.parse({ generatedAt, items: [{ headline: 'News' }], lineups: [{ gameId: 'g', starters: [{ playerName: 'A' }] }] })).toMatchObject({ lineups: [{ gameId: 'g' }] });
    const news = publicFeedSnapshot('f1-trackside', 10);
    expect(() => news.parse({ generatedAt, cards: [{ id: 'bad', title: { text: 'bad' } }] })).toThrow();
    expect(() => news.parse({ generatedAt, cards: [{ id: 'bad', summary: true }] })).toThrow();
    expect(news.parse({ generatedAt, cards: [{ id: 'ok', title: 'News' }, { id: 'bad', title: {} }] })).toMatchObject({ status: 'degraded', cards: [{ id: 'ok' }] });
  });
  it('expires retained token rows by their own acquisition clock even under a newer seed', () => {
    const contract = publicFeedSnapshot('defi-token-watch', 10);
    const old = new Date(Date.now() - (24 * 60 - 1) * 60_000).toISOString();
    const value = contract.parse({ generatedAt, items: [{ id: 'old', fetchedAt: old }, { id: 'new', fetchedAt: generatedAt }] });
    expect(contract.revalidate!(value, Date.now() + 2 * 60_000)).toMatchObject({
      status: 'stale', items: [{ id: 'new' }], generatedAt,
    });
  });
  it('accepts the published NBA periods, season and leaders without accepting malformed nested data', () => {
    const contract = publicFeedSnapshot('nba-scoreboard', 10);
    const row = { id: 'game', name: 'LAL @ ATL', season: { year: 2027, type: 2, slug: 'regular-season' },
      homePeriods: [{ period: 1, value: 22 }], awayPeriods: [{ period: 1, value: 31 }],
      leaders: [{ athleteId: 'a', name: 'Player', category: 'points', side: 'home', value: 21 }] };
    expect(contract.parse({ generatedAt, items: [row] })).toMatchObject({ items: [row] });
    expect(() => contract.parse({ generatedAt, items: [{ ...row, leaders: [{ name: {} }] }] })).toThrow();
    expect(() => contract.parse({ generatedAt, items: [{ ...row, homePeriods: {} }] })).toThrow();
  });
});
