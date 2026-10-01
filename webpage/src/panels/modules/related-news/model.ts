import type { ContentItem, ContentPayload } from '@/types';

export const INTEL_REFRESH_MS = 30_000;
export const INTEL_STALE_MS = 3 * 60_000;
export type IntelResource = { marketId: number | null; scope: 'market' | 'global'; days: number };
export type IntelPayload = Omit<ContentPayload, 'items'> & {
  generatedAt?: string;
  cacheMode?: string;
  stale?: boolean;
  items: Array<ContentItem & { expires_at?: string | null }>;
};
export type IntelSnapshot = {
  content: IntelPayload;
  generatedAt?: string;
  status: 'ready' | 'degraded' | 'error';
  items: ContentItem[];
};
type ReaderState = { key: string; data: IntelPayload | null; pending: IntelPayload | null };
const record = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const optionalText = (value: unknown) => value == null || typeof value === 'string';
const optionalTime = (value: unknown) => value == null || (typeof value === 'string' && Number.isFinite(Date.parse(value)));
const publicUrl = (value: unknown) => {
  if (typeof value !== 'string') return false;
  try { const url = new URL(value); return url.protocol === 'https:' && !url.username && !url.password; } catch { return false; }
};

export function resourceId({ marketId, scope, days }: IntelResource) {
  return `related-news:${scope}:${scope === 'market' ? marketId : 'all'}:${days}`;
}

export function validScope(payload: ContentPayload, marketId: number | null, scope: 'market' | 'global') {
  return payload.scope === scope && (scope === 'global' ? payload.marketId == null : payload.marketId === marketId);
}

/** Validate before rendering: TypeScript assertions cannot validate an API response. */
export function parseIntelPayload(value: unknown, resource: IntelResource): IntelPayload {
  if (!record(value) || !Array.isArray(value.items) || !validScope(value as ContentPayload, resource.marketId, resource.scope)
    || !['ready', 'partial', 'unavailable'].includes(String(value.status))
    || (value.window != null && (!record(value.window) || value.window.days !== resource.days))
    || (value.sources != null && (!Array.isArray(value.sources) || !value.sources.every(source => record(source)
      && typeof source.source_id === 'string' && typeof source.status === 'string' && optionalText(source.error))))
    || !['generatedAt', 'lastSuccessfulCheckAt'].every(key => optionalTime(value[key]))
    || !['cacheMode', 'empty_reason', 'marketTitle'].every(key => optionalText(value[key]))) {
    throw new Error('Invalid content response or resource identity');
  }
  const ids = new Set<string>();
  for (const item of value.items) {
    if (!record(item) || !['string', 'number'].includes(typeof item.id) || !String(item.id)
      || ids.has(String(item.id)) || typeof item.title !== 'string' || !item.title.trim()
      || typeof item.source !== 'string' || !publicUrl(item.url)
      || !['news_report', 'official_release', 'alert', 'observation'].includes(String(item.sourceKind))
      || !['author', 'summary', 'excerptFull', 'publishedAt', 'expires_at', 'content_version', 'relationReason'].every(key => optionalText(item[key]))
      || !['publishedAt', 'expires_at'].every(key => optionalTime(item[key]))
      || (item.licenseUrl != null && !publicUrl(item.licenseUrl)) || (item.policyUrl != null && !publicUrl(item.policyUrl))
      || (resource.scope === 'market' && !['direct', 'context'].includes(String(item.relation)))) {
      throw new Error('Invalid public content item');
    }
    ids.add(String(item.id));
  }
  return value as IntelPayload;
}

export function fingerprint(payload: ContentPayload) {
  return payload.items.map(item => `${item.id}:${item.content_version}`).join('|');
}

export function activePayload(payload: IntelPayload, now = Date.now()): IntelPayload {
  const items = payload.items.filter(item => !item.expires_at || Date.parse(item.expires_at) > now);
  return items.length === payload.items.length ? payload : { ...payload, items, count: items.length };
}

/** New entries wait for acceptance; removals, revisions and source health take effect immediately. */
export function reconcileReader(previous: ReaderState, key: string, payload: IntelPayload): ReaderState {
  const latest = activePayload(payload);
  if (previous.key !== key || !previous.data) return { key, data: latest, pending: null };
  const byId = new Map(latest.items.map(item => [String(item.id), item]));
  const items = previous.data.items.flatMap(item => { const current = byId.get(String(item.id)); return current ? [current] : []; });
  const data = { ...latest, items, count: items.length };
  const displayed = new Set(items.map(item => String(item.id)));
  const hasNew = latest.items.some(item => !displayed.has(String(item.id)));
  return { key, data, pending: hasNew ? latest : null };
}

export function intelSnapshot(content: IntelPayload): IntelSnapshot {
  return { content, items: content.items, generatedAt: content.generatedAt,
    status: content.status === 'unavailable' ? 'error' : content.status === 'partial' || content.stale ? 'degraded' : 'ready' };
}
