import { fetchBookmakerPage } from '@/services/api';
import type { PanelResource } from '@/panels/usePanelResource';
import { bookmakerSnapshot, expire, parsePayload, type BoardQuery, type Payload } from './model';

export function bookmakerPage(game: boolean, query: BoardQuery): PanelResource<Payload> {
  const family = game ? 'game' : 'sports';
  const params = { family, sport: query.sport, provider: query.provider, search: query.search,
    offset: String(query.offset), limit: String(query.limit) };
  const snapshot = bookmakerSnapshot(game);
  return { ...snapshot, key: `bookmakers:page:v4:${new URLSearchParams(params)}`, title: game ? 'Game' : 'Sports',
    fetch: context => fetchBookmakerPage(params, context?.signal),
    parse: value => {
      const result = parsePayload(value, game), b = result.bookmakerBoard;
      if (!b.query || (Object.keys(query) as (keyof BoardQuery)[]).some(k => query[k] !== b.query?.[k]) ||
          !Number.isInteger(b.matchedFixtures) || b.matchedFixtures! < 0 ||
          b.fixtures.length > query.limit ||
          !(b.nextOffset === null || Number.isInteger(b.nextOffset) && b.nextOffset === query.offset + b.fixtures.length && b.nextOffset > query.offset) ||
          b.fixtures.some(f => query.sport && f.sport !== query.sport || query.provider && f.quotes.some(q => q.provider !== query.provider))) {
        throw new Error('Bookmaker response does not match requested page');
      }
      return expire(result, Date.now());
    },
    revalidate: expire,
    refreshPolicy: { tier: 'slow', intervalMs: 15000, staleAfterMs: 1800000, requestTimeoutMs: 45000 },
  };
}
