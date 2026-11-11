import { expect, it } from 'vitest';
import { bookmakerPage } from './resource';

const query = { sport: 'nba', provider: 'fanduel', search: 'Celtics', offset: 20, limit: 20 };
const payload = { panelId: 'sports-odds', generatedAt: new Date().toISOString(), status: 'ok',
  bookmakerBoard: { schemaVersion: 1, family: 'sports', sources: [], fixtures: [], props: [],
    availableFixtures: 100, omittedFixtures: 100, matchedFixtures: 20, nextOffset: null, query } };

it('separates every page, filter, sport and panel in the shared resource key', () => {
  const resource = bookmakerPage(false, query);
  expect(resource.parse(payload).bookmakerBoard.query).toEqual(query);
  for (const changed of [{ offset: 0 }, { sport: 'nfl' }, { search: 'Bulls' }, { provider: '' }, { limit: 10 }]) {
    const other = bookmakerPage(false, { ...query, ...changed });
    expect(other.key).not.toBe(resource.key);
    expect(() => other.parse(payload)).toThrow();
  }
  expect(() => bookmakerPage(true, query).parse(payload)).toThrow();
});

it('rejects a cursor that cannot advance or counts that are not integers', () => {
  const resource = bookmakerPage(false, query);
  expect(() => resource.parse({ ...payload, bookmakerBoard: { ...payload.bookmakerBoard, nextOffset: 20 } })).toThrow();
  expect(() => resource.parse({ ...payload, bookmakerBoard: { ...payload.bookmakerBoard, matchedFixtures: 1.2 } })).toThrow();
});
