import { expect, it } from 'vitest';
import { archiveResource, parseArchive } from './archive';

const query = { sport: 'cs2', fixture: 'f', selection: '', offset: 0, limit: 100 };
const payload = { schemaVersion: 1, observedAt: new Date().toISOString(), generatedAt: null, query,
  fixture: { id: 'f', home: 'Alpha', away: 'Beta', league: 'Test' }, project: 'cs2', points: [], selections: [],
  tasks: [], closing: null, result: null, total: 0, nextOffset: null };

it('isolates historical cache by every query dimension and rejects a mismatched response', () => {
  const resource = archiveResource(query);
  expect(resource.parse(payload).fixture?.id).toBe('f');
  for (const change of [{ sport: 'nba' }, { fixture: 'other' }, { selection: 'sel' }, { offset: 100 }, { limit: 20 }]) {
    const other = archiveResource({ ...query, ...change });
    expect(other.key).not.toBe(resource.key);
    expect(() => other.parse(payload)).toThrow();
  }
});

it('rejects wrong clocks, corrupt prices and a nonadvancing cursor', () => {
  for (const change of [{ observedAt: 'unknown' }, { nextOffset: 0 }, { total: 1.5 },
    { points: [{ odds_dec: NaN }] }, { closing: { data: { closed: 'true' } } },
    { result: { data: { status: 'settled' } } }]) {
    expect(() => parseArchive({ ...payload, ...change }, query)).toThrow();
  }
});
