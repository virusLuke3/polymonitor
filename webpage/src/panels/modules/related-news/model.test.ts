import { describe, expect, it } from 'vitest';
import { activePayload, intelSnapshot, parseIntelPayload, resourceId, INTEL_ITEM_LIMIT, initialIntelScope, intelStatusLabel } from './model';
import type { PanelRuntimeStatus } from '@/panels/types';

const resource = { marketId: 1, scope: 'market' as const, days: 7 };
const item = (id: string) => ({ id, source: 'Fixture', title: id, sourceKind: 'news_report',
  url: 'https://example.org/article', relation: 'context', content_version: '1' });
const payload = (ids = ['first']) => parseIntelPayload({ scope: 'market', marketId: 1,
  status: 'ready', generatedAt: '2026-10-01T00:00:00Z', items: ids.map(item), window: { days: 7 } }, resource);

describe('Related Intelligence resource contract', () => {
  it('defaults to explicit global scope and remembers an explicit market preference', () => {
    expect(initialIntelScope(null)).toBe('global');
    expect(initialIntelScope({ getItem: () => 'market' })).toBe('market');
    expect(initialIntelScope({ getItem: () => { throw new Error('blocked storage'); } })).toBe('global');
  });
  it('separates no coverage, healthy empty, limited candidates and real request failures', () => {
    const status: PanelRuntimeStatus = { phase: 'ready', updatedAt: 1, lastAttemptAt: 1, failureCount: 0, error: null };
    const empty = payload([]);
    expect(intelStatusLabel(intelSnapshot(empty), status)).toBe('NO MATCH');
    empty.marketCoverage = { status: 'unsupported', topic: 'sports', sourceIds: [] };
    expect(intelStatusLabel(intelSnapshot(empty), status)).toBe('NO COVERAGE');
    expect(intelStatusLabel(intelSnapshot(empty), { ...status, phase: 'error', error: '503' })).toBeUndefined();
    const limited = payload(); limited.status = 'partial';
    expect(intelStatusLabel(intelSnapshot(limited), status)).toBe('LIMITED');
    limited.sources = [{ source_id: 'nws', publisher_name: 'NWS', status: 'stale', stale: true }];
    expect(intelStatusLabel(intelSnapshot(limited), status)).toBe('PARTIAL');
    expect(intelStatusLabel(intelSnapshot(limited), { ...status, phase: 'stale' })).toBeUndefined();
  });
  it('separates market, scope and window and rejects mismatched identities', () => {
    const data = payload();
    for (const other of [{ ...resource, marketId: 2 }, { ...resource, days: 30 }, { ...resource, scope: 'global' as const }]) {
      expect(resourceId(other)).not.toBe(resourceId(resource));
      expect(() => parseIntelPayload(data, other)).toThrow();
    }
  });
  it('rejects malformed cards, unsafe URLs, duplicate IDs and invalid dates', () => {
    for (const change of [{ title: {} }, { url: 'javascript:alert(1)' }, { publishedAt: 'bad date' }, { expires_at: 'bad date' }]) {
      expect(() => parseIntelPayload({ ...payload(), items: [{ ...item('x'), ...change }] }, resource)).toThrow();
    }
    const duplicate = parseIntelPayload({ ...payload(), items: [item('x'), item('x')] }, resource);
    expect(duplicate.items).toHaveLength(1);
    expect(duplicate.rejectedItemCount).toBe(1);
  });
  it('accepts the larger page and rejects oversized responses', () => {
    const ids = Array.from({ length: INTEL_ITEM_LIMIT }, (_, index) => `item-${index}`);
    expect(payload(ids).items).toHaveLength(INTEL_ITEM_LIMIT);
    expect(() => payload([...ids, 'overflow'])).toThrow();
    expect(resourceId(resource)).toContain(`:${INTEL_ITEM_LIMIT}`);
  });
  it('removes expired entries without requiring reader acceptance', () => {
    const data = payload();
    data.items[0]!.expires_at = '2026-10-01T00:00:00Z';
    expect(activePayload(data, Date.parse('2026-10-01T00:00:01Z')).items).toEqual([]);
  });
  it('rejects unknown snapshot time/window and isolates one invalid card', () => {
    for (const change of [{ generatedAt: undefined }, { window: undefined }]) {
      expect(() => parseIntelPayload({ ...payload(), ...change }, resource)).toThrow();
    }
    const data = parseIntelPayload({ ...payload(), items: [item('valid'), { ...item('bad'), title: {} }] }, resource);
    expect(data.items.map(value => value.id)).toEqual(['valid']);
    expect(data.status).toBe('partial');
    expect(data.rejectedItemCount).toBe(1);
  });
});
