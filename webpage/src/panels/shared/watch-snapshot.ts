import type { RuntimeTechPanelPayload } from '@/types';
import type { PanelSnapshotContract } from '../resource-cache';
import { RuntimeResponseError } from '../runtime-store';

const record = (value: unknown): Record<string, unknown> => value != null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const strings = ['id', 'label', 'symbol', 'title', 'summary', 'source', 'publishedAt', 'metricLabel', 'metricUnit', 'secondaryLabel', 'changeLabel', 'tone', 'company', 'institution', 'analyst', 'rating', 'targetPriceLabel', 'previousTargetPriceLabel', 'reportPageLabel', 'category'];
const numbers = ['metric', 'secondary', 'change', 'rank', 'marketCap', 'price'];
const numeric = (value: unknown) => (typeof value === 'number' || typeof value === 'string' && value.trim() !== '') && Number.isFinite(Number(value)) ? value as number | string : null;
const failed = (value: unknown) => /error|failed|unavailable|stale|degraded|partial|missing|timeout|unknown/i.test(String(value || ''));

export function parseWatchSnapshot(value: unknown, panelId: string, limit: number): RuntimeTechPanelPayload {
  const raw = record(value);
  if (raw.panelId !== panelId) throw new RuntimeResponseError('Snapshot belongs to a different panel', false);
  if (['error', 'failed', 'unavailable'].includes(String(raw.status))) throw new RuntimeResponseError('Watch source is unavailable');
  if (typeof raw.generatedAt !== 'string' || !Number.isFinite(Date.parse(raw.generatedAt)) || !Array.isArray(raw.items)) throw new RuntimeResponseError('Invalid watch snapshot');
  const items = raw.items.slice(0, limit).flatMap(entry => {
    const row = record(entry);
    if (![row.id, row.label, row.title, row.symbol].some(value => typeof value === 'string' && value.trim())) return [];
    const clean: Record<string, unknown> = {};
    strings.forEach(key => { clean[key] = typeof row[key] === 'string' ? row[key] : null; });
    numbers.forEach(key => { clean[key] = numeric(row[key]); });
    clean.url = typeof row.url === 'string' && /^https?:\/\//i.test(row.url) ? row.url : null;
    clean.tags = Array.isArray(row.tags) ? row.tags.filter(tag => typeof tag === 'string').slice(0, 12) : [];
    clean.points = Array.isArray(row.points) ? row.points.flatMap(entry => {
      const point = record(entry);
      return typeof point.timestamp === 'string' && Number.isFinite(Date.parse(point.timestamp)) && numeric(point.value) != null ? [{ timestamp: point.timestamp, value: numeric(point.value) }] : [];
    }).slice(-48) : [];
    return [clean];
  });
  const rejected = Math.min(raw.items.length, limit) - items.length;
  if (raw.items.length && !items.length) throw new RuntimeResponseError('No valid watch items');
  const sources = Object.fromEntries(Object.entries(record(raw.sources)).map(([key, value]) => [key, typeof value === 'string' ? value : 'unknown']));
  const summary: Record<string, unknown> = { ...record(raw.summary), count: items.length, validationRejected: rejected };
  for (const key of ['watchlist', 'categories', 'metrics']) {
    if (key in summary) summary[key] = Array.isArray(summary[key]) ? summary[key].filter(value => Object.keys(record(value)).length).map(value => {
      const row = record(value);
      return Object.fromEntries(Object.entries(row).filter(([, value]) => value == null || ['string', 'boolean'].includes(typeof value) || typeof value === 'number' && Number.isFinite(value)));
    }) : [];
  }
  const headline = record(raw.headline);
  return {
    panelId, generatedAt: raw.generatedAt, title: typeof raw.title === 'string' ? raw.title : panelId,
    status: raw.status === 'stale' ? 'stale' : rejected || Object.values(sources).some(failed) ? 'degraded' : typeof raw.status === 'string' ? raw.status : items.length ? 'ok' : 'empty',
    cacheMode: typeof raw.cacheMode === 'string' ? raw.cacheMode : null, sources, summary,
    headline: { label: typeof headline.label === 'string' ? headline.label : null, score: numeric(headline.score), previousScore: numeric(headline.previousScore), delta: numeric(headline.delta), regime: typeof headline.regime === 'string' ? headline.regime : null, tone: typeof headline.tone === 'string' ? headline.tone : null },
    items,
  } as RuntimeTechPanelPayload;
}

export function watchSnapshot(family: 'finance' | 'tech', panelId: string, limit: number): PanelSnapshotContract<unknown> {
  return {
    key: `${family}:${panelId}:limit:${limit}:v1`, maxAgeMs: 15 * 60_000, staleAgeMs: 30 * 60_000,
    acceptStale: true, cache: { version: 1, maxChars: 128_000 },
    parse: value => parseWatchSnapshot(value, panelId, limit),
    updatedAt: value => { const generatedAt = record(value).generatedAt; return typeof generatedAt === 'string' ? Date.parse(generatedAt) : null; },
  };
}
