import { describe, expect, it } from 'vitest';
import { readResourceCache, writeResourceCache, type ResourceCacheContract } from './resource-cache';
import { parseIntelPayload, type IntelPayload } from './modules/related-news/model';

const now = Date.parse('2026-10-01T12:00:00Z');
const contract: ResourceCacheContract<IntelPayload> = {
  key: 'related-news:global:all:7', maxAgeMs: 300_000, cache: { version: 1 },
  parse: value => parseIntelPayload(value, { marketId: null, scope: 'global', days: 7 }),
  updatedAt: value => value.generatedAt ? Date.parse(value.generatedAt) : null,
};
const payload = { scope: 'global', marketId: null, status: 'ready', items: [],
  generatedAt: new Date(now).toISOString(), window: { days: 7 } };
function storage() {
  const values = new Map<string, string>();
  return { get length() { return values.size; }, key: (i: number) => [...values.keys()][i] ?? null,
    getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); }, clear: () => values.clear() };
}

describe('public panel snapshot recovery', () => {
  it('hydrates a validated snapshot immediately without extending its source lifetime', () => {
    const cache = storage();
    writeResourceCache(contract, payload, cache, now);
    expect(readResourceCache(contract, cache, now + 299_999)?.generatedAt).toBe(payload.generatedAt);
    writeResourceCache(contract, payload, cache, now + 299_999);
    expect(readResourceCache(contract, cache, now + 300_000)).toBeNull();
  });
  it('rejects another scope, window, schema version and corrupted storage', () => {
    const cache = storage();
    const key = 'polymonitor:panel-resource:' + contract.key;
    for (const value of [{ ...payload, scope: 'market', marketId: 1 }, { ...payload, window: { days: 30 } },
      { ...payload, items: [{ title: {} }] }]) {
      cache.setItem(key, JSON.stringify({ version: 1, value }));
      expect(readResourceCache(contract, cache, now)).toBeNull();
    }
    cache.setItem(key, JSON.stringify({ version: 0, value: payload }));
    expect(readResourceCache(contract, cache, now)).toBeNull();
    cache.setItem(key, 'broken json');
    expect(readResourceCache(contract, cache, now)).toBeNull();
    expect(cache.getItem(key)).toBeNull();
  });
  it('does not reuse a snapshot with missing or implausibly future source time', () => {
    const cache = storage();
    for (const generatedAt of [undefined, new Date(now + 61_000).toISOString()]) {
      writeResourceCache(contract, { ...payload, generatedAt }, cache, now);
      expect(readResourceCache(contract, cache, now)).toBeNull();
    }
  });
  it('isolates public resource keys, bounds storage and survives storage failure', () => {
    const cache = storage();
    cache.setItem('user-preference', 'keep');
    for (let i = 0; i < 20; i++) writeResourceCache({ ...contract, key: `resource:${i}` }, payload, cache, now);
    expect(cache.length).toBe(9);
    expect(cache.getItem('user-preference')).toBe('keep');
    expect(readResourceCache({ ...contract, key: 'another-market' }, cache, now)).toBeNull();
    const blocked = { ...cache, getItem: () => { throw new Error('disabled'); }, setItem: () => { throw new Error('quota'); } };
    expect(readResourceCache(contract, blocked, now)).toBeNull();
    expect(() => writeResourceCache(contract, payload, blocked, now)).not.toThrow();
  });
  it('preserves the last persisted snapshot if a replacement exceeds storage quota', () => {
    const cache = storage();
    writeResourceCache(contract, payload, cache, now);
    const quota = { ...cache, setItem: () => { throw new Error('quota exceeded'); } };
    writeResourceCache(contract, { ...payload, generatedAt: new Date(now + 10_000).toISOString() }, quota, now + 10_000);
    expect(readResourceCache(contract, cache, now + 10_000)?.generatedAt).toBe(payload.generatedAt);
  });
});
