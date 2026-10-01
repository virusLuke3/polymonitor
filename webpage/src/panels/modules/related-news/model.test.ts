import { describe, expect, it } from 'vitest';
import { activePayload, intelSnapshot, parseIntelPayload, reconcileReader, resourceId } from './model';

const resource = { marketId: 1, scope: 'market' as const, days: 7 };
const item = (id: string) => ({ id, source: 'Fixture', title: id, sourceKind: 'news_report',
  url: 'https://example.org/article', relation: 'context', content_version: '1' });
const payload = (ids = ['first']) => parseIntelPayload({ scope: 'market', marketId: 1,
  status: 'ready', generatedAt: '2026-10-01T00:00:00Z', items: ids.map(item), window: { days: 7 } }, resource);

describe('Related Intelligence resource contract', () => {
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
  it('updates source health and revisions immediately while new entries wait', () => {
    const previous = { key: 'key', data: payload(), pending: null };
    const latest = payload(['new', 'first']);
    latest.status = 'partial';
    latest.items[1]!.content_version = '2';
    const next = reconcileReader(previous, 'key', latest);
    expect(next.data?.status).toBe('partial');
    expect(next.data?.items.map(i => i.id)).toEqual(['first']);
    expect(next.data?.items[0]?.content_version).toBe('2');
    expect(next.pending?.items.length).toBe(2);
    expect(intelSnapshot(latest).status).toBe('degraded');
  });
  it('shows a fully replaced page immediately instead of leaving all new items pending', () => {
    const next = reconcileReader({ key: 'key', data: payload(), pending: null }, 'key', payload(['new']));
    expect(next.data?.items[0]?.id).toBe('new');
    expect(next.pending).toBeNull();
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
