import { describe, expect, it } from 'vitest';
import { macroRefreshPolicy, macroSnapshot } from './macro-runtime';
import { readResourceCache, writeResourceCache } from '@/panels/resource-cache';

const id = 'labor-services-inflation-monitor';
const contract = macroSnapshot(id);
const now = Date.now();
const payload = { panelId: id, schemaVersion: 2, status: 'ok', generatedAt: new Date(now).toISOString(),
  items: [{ key: 'payrolls', label: 'Nonfarm payrolls monthly change', value: 159029, change: 29, valueLabel: '29K persons' }] };

describe('macro snapshot and refresh contract', () => {
  it('polls independently with a deadline and a freshness budget longer than the seed cycle', () => {
    expect(macroRefreshPolicy.intervalMs).toBe(30_000);
    expect(macroRefreshPolicy.batch).toBe(false);
    expect(macroRefreshPolicy.requestTimeoutMs).toBe(12_000);
    expect(contract.maxAgeMs).toBeGreaterThan(30 * 60_000);
  });
  it('rejects wrong families, malformed rows and missing collection clocks', () => {
    expect(contract.parse(payload)).toEqual(payload);
    for (const change of [{ panelId: 'other' }, { schemaVersion: 1 }, { generatedAt: null },
      { items: [null] }, { items: [{ value: Infinity }] }, { status: null }]) {
      expect(() => contract.parse({ ...payload, ...change })).toThrow();
    }
  });
  it('restores the public snapshot immediately and expires it within a bounded recovery window', () => {
    const values = new Map<string, string>();
    const storage = { get length() { return values.size; }, key: (i: number) => [...values.keys()][i] ?? null,
      getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key), clear: () => values.clear() } as Storage;
    writeResourceCache(contract, payload, storage, now);
    expect(readResourceCache(contract, storage, now + 60_000)).toEqual(payload);
    expect(readResourceCache(contract, storage, now + 24 * 60 * 60_000 + 1)).toBeNull();
  });
  it('validates the independent sanctions sample without changing the existing conflict contract', () => {
    const geo = macroSnapshot('geo-sanctions-shock', true);
    const raw = { status: 'ok', generatedAt: payload.generatedAt, items: [{ id: 'conflict-1', kind: 'conflict' }],
      sanctionsItems: [{ id: 'ofac-1', kind: 'sanction', headline: 'List entry' }] };
    expect(geo.parse(raw)).toEqual(raw);
    expect(() => geo.parse({ ...raw, sanctionsItems: [null] })).toThrow();
    expect(() => geo.parse({ ...raw, sanctionsItems: 'broken' })).toThrow();
  });
});
