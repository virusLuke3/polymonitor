import type { PanelSnapshotContract } from '@/panels/resource-cache';
import type { RuntimePolymarketMacroMapPayload } from '@/types';

export function projectMacroMapDisplay(value: unknown, now = Date.now()): unknown {
  const payload = value as RuntimePolymarketMacroMapPayload | null;
  if (!payload || !Array.isArray(payload.items)) return value;
  const items = payload.items.filter(item => {
    const observed = Date.parse(item.sourceObservedAt || '');
    return Number.isFinite(observed) && now - observed >= -60000 && now - observed < 7200000;
  });
  if (items.length === payload.items.length) return value;
  return { ...payload, items, status: items.length ? 'degraded' : 'expired',
    summary: { ...payload.summary, activeCount: items.length, topCatalyst: null },
    coverage: { ...payload.coverage, displayedEventCount: items.length } };
}

export const macroMapSnapshot: PanelSnapshotContract<unknown> = {
  key: 'macro:polymarket-macro-map:outcomes:v2', maxAgeMs: 180000, staleAgeMs: 7200000,
  acceptStale: true, cache: { version: 2, maxChars: 256000 },
  revalidate: projectMacroMapDisplay,
  parse(value) {
    const payload = value as RuntimePolymarketMacroMapPayload | null;
    if (!payload || !Array.isArray(payload.items) || typeof payload.status !== 'string'
        || payload.items.some(item => !item || typeof item !== 'object')) throw new Error('Invalid macro catalog snapshot');
    return projectMacroMapDisplay(payload);
  },
  updatedAt(value) {
    const observed = Date.parse((value as RuntimePolymarketMacroMapPayload).generatedAt || '');
    return Number.isFinite(observed) ? observed : null;
  },
  shouldPersist: value => Boolean((value as RuntimePolymarketMacroMapPayload).items?.length),
};
