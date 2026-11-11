import type { PanelResource } from '@/panels/usePanelResource';
import { fetchMoviOddsArchive } from '@/services/api';

export type ArchiveQuery = { sport: string; fixture: string; selection: string; offset: number; limit: number };
export type PricePoint = { ts: string; odds_dec: number | null; suspended: boolean; group_id: string; sel_id: string;
  group_name?: string; label?: string; side?: string; line?: string; handicap?: string; period?: string;
  firstReceivedAt: string; channel: string };
type ClosingRow = { group_name?: string; side?: string; label?: string; line?: string; handicap?: string;
  sel_id: string; pre_close?: { ts: string; odds_dec: number | null; suspended: boolean }; last?: { ts: string; odds_dec: number | null; suspended: boolean } };
export type ArchiveData = { schemaVersion: number; observedAt: string; generatedAt: string | null; query: ArchiveQuery;
  items?: { id: string; sport: string; home: string; away: string; league: string; kickoff: string | null; receivedAt: string }[];
  fixture?: { id: string; home: string; away: string; league: string }; project?: string;
  points?: PricePoint[]; selections?: { key: string; label: string }[]; total: number; nextOffset: number | null;
  tasks?: { kind: string; checked: number | null; error: string | null; cursor: Record<string, unknown> }[];
  closing?: { receivedAt: string; omittedSelections: number; data: { closed: boolean; pre_close_basis: string; selections: ClosingRow[] } } | null;
  result?: { receivedAt: string; data: { status: string; final_score: string; finished_at: string; note?: string;
    archiveSource?: string; periods?: { name: string; score: string }[] } } | null };
const object = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.length <= 4000;
const date = (v: unknown) => text(v) && Number.isFinite(Date.parse(v));
const integer = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 0;
const priced = (v: unknown) => object(v) && date(v.ts) && (v.suspended === true && v.odds_dec === null || typeof v.odds_dec === 'number' && Number.isFinite(v.odds_dec) && v.odds_dec >= 1);

export function parseArchive(value: unknown, query: ArchiveQuery): ArchiveData {
  if (!object(value) || value.schemaVersion !== 1 || !date(value.observedAt) || !object(value.query) ||
      !Object.keys(query).every(k => value.query && (value.query as Record<string, unknown>)[k] === query[k as keyof ArchiveQuery]) ||
      !integer(value.total) || !(value.nextOffset === null || integer(value.nextOffset) && value.nextOffset > query.offset)) throw Error('Invalid archive scope');
  if (!query.fixture) {
    if (!Array.isArray(value.items) || value.items.length > query.limit || !value.items.every(i => object(i) &&
        ['id', 'sport', 'home', 'away', 'league'].every(k => text(i[k])) && date(i.receivedAt) && (!query.sport || i.sport === query.sport))) throw Error('Invalid archive catalog');
  } else {
    if (!object(value.fixture) || value.fixture.id !== query.fixture || ['home', 'away', 'league'].some(k => !text(value.fixture && (value.fixture as Record<string, unknown>)[k])) ||
        value.project !== query.sport || !Array.isArray(value.points) || value.points.length > query.limit ||
        !value.points.every(p => priced(p) && object(p) && text(p.group_id) && text(p.sel_id) && date(p.firstReceivedAt) && text(p.channel) && typeof p.suspended === 'boolean') ||
        !Array.isArray(value.selections) || value.selections.length > 200 || !value.selections.every(s => object(s) && text(s.key) && text(s.label)) ||
        !Array.isArray(value.tasks) || !value.tasks.every(t => object(t) && text(t.kind) && (t.error === null || text(t.error)) && object(t.cursor))) throw Error('Invalid archive history');
    const closing = value.closing;
    if (closing != null && (!object(closing) || !date(closing.receivedAt) || !object(closing.data) ||
        typeof closing.data.closed !== 'boolean' || !['kickoff', 'prematch-records', 'omitted'].includes(String(closing.data.pre_close_basis)) ||
        !Array.isArray(closing.data.selections) || closing.data.selections.length > 200 ||
        !closing.data.selections.every(r => object(r) && text(r.sel_id) && (r.pre_close == null || priced(r.pre_close)) && (r.last == null || priced(r.last))))) throw Error('Invalid closing data');
    const result = value.result;
    if (result != null && (!object(result) || !date(result.receivedAt) || !object(result.data) ||
        !['finished', 'unknown'].includes(String(result.data.status)) || !text(result.data.final_score) || !date(result.data.finished_at) ||
        (result.data.note != null && !text(result.data.note)) || (result.data.periods != null && (!Array.isArray(result.data.periods) ||
          !result.data.periods.every(p => object(p) && text(p.name) && text(p.score)))))) throw Error('Invalid result data');
  }
  return value as ArchiveData;
}

export function archiveResource(query: ArchiveQuery): PanelResource<ArchiveData> {
  const params = Object.fromEntries(Object.entries(query).map(([k, v]) => [k, String(v)]));
  return { key: `bookmakers:moviodds:archive:v1:${new URLSearchParams(params)}`, title: 'MoviOdds archive',
    cache: { version: 1, maxChars: 600_000, storage: 'indexeddb' }, maxAgeMs: 300_000, staleAgeMs: 86400_000, acceptStale: true,
    // Read receipt controls this historical page cache, never price eligibility.
    // Every point and document retains its separate source/first-received clock.
    updatedAt: v => Date.parse(v.observedAt), parse: v => parseArchive(v, query),
    fetch: ctx => fetchMoviOddsArchive(params, ctx?.signal),
    refreshPolicy: { tier: 'slow', intervalMs: 60000, requestTimeoutMs: 45000, staleAfterMs: 300000 } };
}
