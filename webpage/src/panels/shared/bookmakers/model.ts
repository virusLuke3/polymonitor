import type { PanelSnapshotContract } from '@/panels/resource-cache';
import { RuntimeResponseError, runtimeTimestamp } from '@/panels/runtime-store';
import type { RuntimeGridEsportsItem } from '@/types';

export type Outcome = { name: string; decimal: number; implied: number; probability: number; point: number | null };
export type Quote = { book: string; label: string; category: string; market: string; period: string; provider: string;
  sourceUpdatedAt: string | null; url: string | null; overround: number; outcomes: Outcome[] };
export type Fixture = { id: string; provider: string; tier: string; sport: string; competition: string;
  home: string; away: string; startTime: string; fetchedAt: string; sourceStale: boolean; sourceError: string | null; quotes: Quote[] };
export type Source = { id: string; label: string; usable: boolean; stale: boolean; error: string | null; lastSuccessAt: string | null };
export type Prop = { id: string; sport: string; player: string; stat: string; line: number; decimal: number;
  direction: string; book: string; startTime: string | null; url: string | null; fetchedAt: string };
export type Board = { schemaVersion: number; family: string; fixtures: Fixture[]; props: Prop[]; sources: Source[];
  generatedAt: string | null; availableFixtures: number; omittedFixtures: number };
export type Payload = { panelId: string; generatedAt: string; status: string; bookmakerBoard: Board;
  officialGeneratedAt?: string; items: RuntimeGridEsportsItem[];
  sportsContext: { source: Source; rows: { title: string; value: string; detail: string | null; url: string | null }[] }[] };
const object = (x: unknown): x is Record<string, unknown> => !!x && typeof x === 'object' && !Array.isArray(x);
const finite = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);
const text = (x: unknown): x is string => typeof x === 'string' && x.length <= 2000;
const date = (x: unknown) => text(x) && Number.isFinite(Date.parse(x));
const nullableText = (x: unknown) => x === null || text(x);
export const safeLink = (x: unknown) => { try { const u = new URL(String(x)); return u.protocol === 'https:' && !u.username && !u.password ? u.href : undefined; } catch { return undefined; } };
export const quoteCurrent = (q: Quote, now = Date.now()) => !!q.sourceUpdatedAt && Date.parse(q.sourceUpdatedAt) <= now + 60_000 && now - Date.parse(q.sourceUpdatedAt) < 30 * 60_000;
export const lineKey = (q: Quote) => q.market === 'h2h' ? String(q.outcomes.length) : q.outcomes.map(o => `${o.name}:${o.point}`).sort().join('|');
export const teamKey = (value: string) => value.toLocaleLowerCase().replace(/[^\p{L}\p{N}_]/gu, '');

function validQuote(q: unknown): q is Quote {
  return object(q) && ['book', 'label', 'category', 'market', 'period', 'provider'].every(k => text(q[k])) &&
    ['h2h', 'spreads', 'totals'].includes(String(q.market)) && nullableText(q.url) &&
    (q.sourceUpdatedAt === null || date(q.sourceUpdatedAt)) && finite(q.overround) &&
    Array.isArray(q.outcomes) && [2, 3].includes(q.outcomes.length) && q.outcomes.every(o => object(o) && text(o.name) &&
      finite(o.decimal) && o.decimal > 1 && finite(o.implied) && o.implied > 0 && o.implied < 1 &&
      finite(o.probability) && o.probability > 0 && o.probability < 1 && (o.point === null || finite(o.point))) &&
    Math.abs(q.outcomes.reduce((sum, o) => sum + o.probability, 0) - 1) < .00001;
}
function validSource(s: unknown): s is Source {
  return object(s) && text(s.id) && text(s.label) && typeof s.usable === 'boolean' && typeof s.stale === 'boolean' && nullableText(s.error) && (s.lastSuccessAt === null || date(s.lastSuccessAt));
}
export function parsePayload(value: unknown, game: boolean): Payload {
  const id = game ? 'esports-intel' : 'sports-odds';
  if (!object(value) || value.panelId !== id || !date(value.generatedAt) || !object(value.bookmakerBoard)) throw new RuntimeResponseError('Bookmaker data is unavailable');
  const b = value.bookmakerBoard;
  if (b.schemaVersion !== 1 || b.family !== (game ? 'game' : 'sports') || !Array.isArray(b.fixtures) || b.fixtures.length > 60 ||
      !Array.isArray(b.sources) || !b.sources.every(validSource) || !finite(b.omittedFixtures) || !finite(b.availableFixtures) ||
      !Array.isArray(b.props) || b.props.length > 10) throw new RuntimeResponseError('Invalid bookmaker board');
  if (!b.fixtures.every(f => object(f) && ['id', 'provider', 'tier', 'sport', 'competition', 'home', 'away'].every(k => text(f[k])) &&
    date(f.startTime) && date(f.fetchedAt) && typeof f.sourceStale === 'boolean' && nullableText(f.sourceError) &&
    Array.isArray(f.quotes) && f.quotes.length <= 1600 && f.quotes.every(validQuote))) throw new RuntimeResponseError('Invalid bookmaker fixture');
  if (!b.props.every(p => object(p) && ['id', 'sport', 'player', 'stat', 'direction', 'book'].every(k => text(p[k])) &&
    finite(p.line) && finite(p.decimal) && p.decimal > 1 && nullableText(p.url) && date(p.fetchedAt))) throw new RuntimeResponseError('Invalid player prop');
  const items = game && Array.isArray(value.items) ? value.items.filter(i => object(i) && text(i.id) &&
    ['gameTitle', 'tournament', 'teamA', 'teamB', 'score', 'currentMap', 'state', 'startTime'].every(k => i[k] == null || text(i[k]))) : [];
  const context = Array.isArray(value.sportsContext) ? value.sportsContext.filter(c => object(c) && validSource(c.source) &&
    Array.isArray(c.rows) && c.rows.every(r => object(r) && text(r.title) && text(r.value) && nullableText(r.detail) && nullableText(r.url))) : [];
  return { ...value, items, sportsContext: context } as Payload;
}

export function expire(value: Payload, now: number): Payload {
  const fixtures = value.bookmakerBoard.fixtures.filter(f => {
    const ttl = f.tier === 'daily-sample' ? 86400_000 : f.tier === 'quota-feed' ? 21600_000 : 7200_000;
    const age = now - Date.parse(f.fetchedAt);
    return age >= -60_000 && age < ttl;
  });
  // Once official rows have expired, keep the empty array stable. Sports has
  // no GRID rows at all; its older quota-feed clock must not degrade live odds.
  const items = value.items.length && (!value.officialGeneratedAt || now - Date.parse(value.officialGeneratedAt) >= 900_000)
    ? [] : value.items;
  const props = value.bookmakerBoard.props.filter(p => now - Date.parse(p.fetchedAt) < 86400_000);
  if (fixtures.length === value.bookmakerBoard.fixtures.length && props.length === value.bookmakerBoard.props.length && items === value.items) return value;
  return { ...value, items, bookmakerBoard: { ...value.bookmakerBoard, fixtures, props } };
}
export function bookmakerSnapshot(game: boolean): PanelSnapshotContract<unknown> {
  return { key: `bookmakers:${game ? 'esports-intel:10' : 'sports-odds:8'}:v1`,
    cache: { version: 1, maxChars: 600_000, storage: 'indexeddb' }, maxAgeMs: 1800_000, staleAgeMs: 7200_000,
    acceptStale: true, updatedAt: runtimeTimestamp,
    parse: value => expire(parsePayload(value, game), Date.now()),
    revalidate: (value, now) => expire(value as Payload, now),
    shouldPersist: value => (value as Payload).bookmakerBoard.sources.some(s => s.usable),
  };
}
