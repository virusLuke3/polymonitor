import { describe, expect, it } from 'vitest';
import { marketCatalogResource, marketDetailResource, marketChartResource } from './resources';
import { readResourceCacheEntry, writeResourceCache, type PanelSnapshotContract } from '@/panels/resource-cache';
import { parseRuntimeSnapshot } from '@/panels/runtime-store';
import type { PanelModule } from '@/panels/types';

const generatedAt = new Date().toISOString();
const market = { id: 42, title: 'Market', slug: 'market', tags: [] };

describe('market context shares the public resource owner', () => {
  it('isolates catalog sort/page/limit and rejects failed semantic verification', () => {
    const contract = marketCatalogResource('volume');
    const value = { generatedAt, sort: 'volume', items: [market], pagination: { page: 1, pageSize: 50 } };
    expect(contract.parse(value)).toEqual(value);
    for (const patch of [{ sort: 'active' }, { pagination: { page: 2, pageSize: 50 } }, { pagination: { page: 1, pageSize: 80 } },
      { items: [{ ...market, outcomeSemanticsStatus: 'semantics_query_failed' }] }]) {
      expect(() => contract.parse({ ...value, ...patch })).toThrow();
    }
    expect(marketCatalogResource('active').key).not.toBe(contract.key);
  });
  it('cannot restore live fields from metadata and enforces market identity', () => {
    const contract = marketDetailResource(42, () => {});
    const value = { generatedAt, market, identity: { localMarketId: 42 }, trades: [{ marketId: 42 }],
      lob: { marketId: 42 }, chart: { marketId: 42 }, oracle: { marketId: 42 } };
    expect(contract.parse(value)).toMatchObject({ market, lob: null, chart: null, oracle: null, trades: [] });
    expect(() => contract.parse({ ...value, identity: { localMarketId: 43 } })).toThrow();
    expect(() => contract.parse({ ...value, focusStatus: 'warming' })).toThrow();
  });
  it('accepts stale navigation context after a refresh boundary but rejects the hard retention boundary', () => {
    const contract = marketCatalogResource('volume');
    const panel: PanelModule = { id: 'catalog', title: 'Catalog', eyebrow: 'Test', description: 'Catalog fixture', snapshot: contract as PanelSnapshotContract<unknown> };
    const value = { items: [market], pagination: { page: 1, pageSize: 50 }, sort: 'volume' };
    const retained = { ...value, generatedAt: new Date(Date.now() - 6 * 60_000).toISOString() };
    expect(parseRuntimeSnapshot(panel, retained)).toEqual(retained);
    expect(() => parseRuntimeSnapshot(panel, { ...value, generatedAt: new Date(Date.now() - 15 * 60_000).toISOString() })).toThrow('overdue');
  });
  it('isolates history market/range and rejects malformed points', () => {
    const contract = marketChartResource(42, '1d');
    const value = { generatedAt, marketId: 42, range: '1d', points: [{ timestamp: generatedAt, yesPrice: '0.5' }] };
    expect(contract.parse(value)).toEqual(value);
    expect(contract.cache?.storage).toBe('indexeddb');
    for (const patch of [{ marketId: 43 }, { range: '1w' }, { points: [{ timestamp: 'invalid', yesPrice: '0.5' }] },
      { points: [{ timestamp: generatedAt, yesPrice: {} }] }, { historyStatus: 'unavailable' }]) expect(() => contract.parse({ ...value, ...patch })).toThrow();
    expect(marketChartResource(42, '1w').key).not.toBe(contract.key);
  });
  it('retains the original source/check clocks and expires metadata without renewing them', () => {
    const contract = marketDetailResource(42, () => {}), values = new Map<string, string>();
    const storage = { get length() { return values.size; }, key: (i: number) => [...values.keys()][i] ?? null,
      getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, v: string) => { values.set(key, v); },
      removeItem: (key: string) => { values.delete(key); }, clear: () => values.clear() };
    const now = Date.parse(generatedAt);
    writeResourceCache(contract, { generatedAt, market }, storage, now + 1000);
    expect(readResourceCacheEntry(contract, storage, now + 120_000)).toMatchObject({ checkedAt: now + 1000, value: { generatedAt } });
    expect(readResourceCacheEntry(contract, storage, now + 300_001)).toBeNull();
  });
});
