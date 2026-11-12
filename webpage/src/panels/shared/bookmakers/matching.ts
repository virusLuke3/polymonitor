export type MatchedMarket = {
  marketId: string; conditionId: string; title: string; slug: string; type: string;
  metric: string; period: string; line: string | null; handicapTeam: string | null;
  observedAt: string | null; sourceUpdatedAt: string | null; url: string | null;
  settlement: 'unknown'; reason: string; comparisonReady: false;
  outcomes: { tokenId: string; label: string; catalogPrice: number | null }[];
  books: { book: string; provider: string; pairs: { selection: string; tokenId: string }[] }[];
};
export type Match = { state: 'pending' | 'unsupported' | 'linked' | 'review' | 'unmatched' | 'incomplete' | 'unavailable';
  reason: string; checkedAt?: number; firstLinkedAt?: number | null; stale?: boolean; eventId?: string;
  title?: string; pmEventId?: string; markets: MatchedMarket[];
  candidates?: { eventId: string; title: string; reason: string; timeDeltaSeconds: number }[] };

const obj = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const str = (v: unknown): v is string => typeof v === 'string' && v.length <= 2000;
const stamp = (v: unknown) => v === null || str(v) && Number.isFinite(Date.parse(v));
export function validMatch(v: unknown): v is Match {
  if (!obj(v) || !['pending', 'unsupported', 'linked', 'review', 'unmatched', 'incomplete', 'unavailable'].includes(String(v.state)) || !str(v.reason) ||
    v.checkedAt !== undefined && (typeof v.checkedAt !== 'number' || !Number.isFinite(v.checkedAt)) ||
    v.stale !== undefined && typeof v.stale !== 'boolean' || !Array.isArray(v.markets) || v.markets.length > 24) return false;
  if (v.candidates !== undefined && (!Array.isArray(v.candidates) || v.candidates.length > 8 || !v.candidates.every(c => obj(c) && str(c.eventId) && str(c.title) && str(c.reason) && typeof c.timeDeltaSeconds === 'number' && Number.isFinite(c.timeDeltaSeconds)))) return false;
  return v.markets.every(m => obj(m) && ['marketId', 'conditionId', 'title', 'slug', 'type', 'metric', 'period', 'reason'].every(k => str(m[k])) &&
    /^0x[0-9a-fA-F]{64}$/.test(String(m.conditionId)) && (m.line === null || str(m.line)) && (m.handicapTeam === null || str(m.handicapTeam)) &&
    stamp(m.observedAt) && stamp(m.sourceUpdatedAt) && (m.url === null || str(m.url)) && m.settlement === 'unknown' && m.comparisonReady === false &&
    Array.isArray(m.outcomes) && m.outcomes.length === 2 && m.outcomes.every(o => obj(o) && str(o.tokenId) && /^\d+$/.test(o.tokenId) && str(o.label) &&
      (o.catalogPrice === null || typeof o.catalogPrice === 'number' && Number.isFinite(o.catalogPrice) && o.catalogPrice >= 0 && o.catalogPrice <= 1)) &&
    new Set(m.outcomes.map(o => o.tokenId)).size === 2 && Array.isArray(m.books) && m.books.length <= 80 && m.books.every(b => obj(b) && str(b.book) && str(b.provider) &&
      Array.isArray(b.pairs) && b.pairs.length === 2 && b.pairs.every(p => obj(p) && str(p.selection) && str(p.tokenId) &&
        (m.outcomes as MatchedMarket['outcomes']).some(o => o.tokenId === p.tokenId))));
}

export const matchCurrent = (m: Match, now = Date.now()) => !m.stale && m.checkedAt !== undefined && m.checkedAt * 1000 <= now + 60_000 && now - m.checkedAt * 1000 < 600_000;
export const catalogCurrent = (m: MatchedMarket, now = Date.now()) => !!m.observedAt && Date.parse(m.observedAt) <= now + 60_000 && now - Date.parse(m.observedAt) < 120_000;
