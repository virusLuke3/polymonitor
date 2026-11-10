import { describe, expect, it } from 'vitest';
import { PANEL_MODULES } from './registry';
import { publicListSnapshot, records } from './public-snapshot';
import { readResourceCacheEntry, writeResourceCache } from './resource-cache';
import { mediaSnapshot, newsSnapshot, transmissionSnapshot } from './shared/context-snapshots';
import { weatherSnapshot, projectWeatherSnapshot } from './shared/weather/snapshot';
import { insightSnapshot } from './shared/market-insights/data';
import { cryptoStrategyResource, cryptoHistoryResource, cryptoReferenceResource } from './shared/crypto-strategy/resource';
import { orderBookResource } from '@/features/market-focus/orderBookResource';
import { weatherQuoteResource } from './shared/weather/useLiveWeatherQuoteBins';

const now = Date.now(), generatedAt = new Date(now).toISOString();
const storage = () => {
  const values = new Map<string, string>();
  return { get length() { return values.size; }, key: (i: number) => [...values.keys()][i] ?? null,
    getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, v: string) => { values.set(key, v); },
    removeItem: (key: string) => { values.delete(key); }, clear: () => values.clear() };
};

describe('resource-wide persistence policy', () => {
  it('covers every registered owner, and shared views do not allocate copies', () => {
    for (const panel of PANEL_MODULES) {
      if (panel.fetchData) expect(panel.snapshot?.cache, panel.id).toBeDefined();
      if (panel.dataSourceId) {
        expect(panel.snapshot, panel.id).toBeUndefined();
        expect(PANEL_MODULES.find(owner => owner.id === panel.dataSourceId)?.snapshot?.cache).toBeTruthy();
      }
    }
  });
  it('supports a new public owner without adding its ID to a cache allowlist', () => {
    const contract = publicListSnapshot({ id: 'new-public-owner', limit: 2, maxAgeMs: 60_000, staleAgeMs: 120_000,
      validate: value => records(value.items) });
    const cache = storage();
    writeResourceCache(contract, { generatedAt, status: 'ok', items: [{ title: 'one' }, { title: 'two' }, { title: 'three' }] }, cache, now);
    expect(readResourceCacheEntry(contract, cache, now + 1000)).toMatchObject({ checkedAt: now, value: { items: [{ title: 'one' }, { title: 'two' }] } });
    expect(readResourceCacheEntry({ ...contract, key: contract.key + ':different-parameters' }, cache, now)).toBeNull();
  });
  it('keeps current contract and book eligibility out of persistent storage', () => {
    expect(cryptoStrategyResource.cache?.storage).toBe('indexeddb');
    expect(cryptoHistoryResource.cache?.storage).toBe('indexeddb');
    for (const contract of [cryptoReferenceResource, orderBookResource(1, 'yes', 'no'), weatherQuoteResource([])]) {
      expect(contract.cache).toBeNull();
      expect(readResourceCacheEntry(contract as any, storage())).toBeNull();
    }
  });
});

describe('public context restore validation', () => {
  it.each([mediaSnapshot('market-tv-wire', 60), newsSnapshot('weather-news', 24)])('rejects wrong identities, failed and malformed snapshots', contract => {
    for (const payload of [
      { generatedAt, panelId: 'wrong', items: [] }, { generatedAt, status: 'warming', items: [] },
      { generatedAt, items: 'invalid' }, { generatedAt, items: [{ id: 'x', title: {} }] },
    ]) expect(() => contract.parse(payload)).toThrow();
  });
  it('accepts healthy empty media directories and validates nested playback sources', () => {
    const contract = mediaSnapshot('market-tv-wire', 60);
    expect(contract.parse({ generatedAt, status: 'empty', items: [] })).toMatchObject({ items: [] });
    expect(() => contract.parse({ generatedAt, items: [{ id: 'tv', playbackSources: [{ kind: 'shell' }] }] })).toThrow();
  });
  it('validates nested transmissions while allowing numeric linked-market identities', () => {
    const contract = transmissionSnapshot(8);
    const payload = { generatedAt, commodities: [], transmissions: [{ id: 'oil', linkedMarkets: [{ id: 42, title: 'Oil' }] }] };
    expect(contract.parse(payload)).toMatchObject(payload);
    expect(() => contract.parse({ ...payload, transmissions: [{ winners: 'invalid' }] })).toThrow();
  });
  it('restores forecasts but expires catalog selections on their own original clocks', () => {
    const value = { generatedAt, items: [{ cityId: 'london', timezone: 'Europe/London', forecastFetchedAt: generatedAt,
      marketFetchedAt: new Date(now - 901_000).toISOString(), marketDate: '2099-01-01', eventSlug: 'old',
      bins: [{ label: '20', yesTokenId: 'token' }], markets: [{ marketDate: '2099-01-01', bins: [] }], hourly: [], daily: [] }] };
    const contract = weatherSnapshot(60);
    expect(contract.cache?.storage).toBe('indexeddb');
    const result = contract.parse(value) as typeof value;
    expect(result.generatedAt).toBe(generatedAt);
    expect(result.items[0]).toMatchObject({ cityId: 'london', forecastFetchedAt: generatedAt, bins: [], markets: [], marketDate: null });
    expect(projectWeatherSnapshot(result, now)).toBe(result);
    expect(() => contract.parse({ ...value, items: [{ ...value.items[0], hourly: {} }] })).toThrow();
  });
  it('isolates insight lenses and respects their generation and expiry clocks', () => {
    const contract = insightSnapshot('overview');
    const value = { lens: 'overview', status: 'live', brief: 'ok', generatedAt,
      snapshotGeneratedAt: new Date(now - 1000).toISOString(), focus: [], themes: [], specialMarkets: [], watchlist: [] };
    expect(contract.updatedAt(contract.parse(value))).toBe(now - 1000);
    expect(() => contract.parse({ ...value, lens: 'trend' })).toThrow();
    expect(() => contract.parse({ ...value, snapshotExpiresAt: new Date(now - 1).toISOString() })).toThrow();
  });
  it('a fresh catalog publication cannot renew an expired forecast or erase a current observation', () => {
    const forecastFetchedAt = new Date(now - 12 * 3_600_000).toISOString();
    const value = { generatedAt, items: [{ cityId: 'london', timezone: 'Europe/London', forecastFetchedAt,
      marketFetchedAt: generatedAt, currentTemp: 18, metarTemp: 19,
      marketDate: '2099-01-01', eventSlug: 'current', bins: [{ label: '20', yesTokenId: 'token' }],
      forecastHigh: 20, marketForecastHigh: 20, hourly: [{ time: generatedAt, temp: 18 }], daily: [] }] };
    const retained = weatherSnapshot(60).parse(value) as typeof value;
    expect(retained.items[0].hourly).toEqual(value.items[0].hourly);
    const expired = weatherSnapshot(60).parse({ ...value, items: [{ ...value.items[0],
      forecastFetchedAt: new Date(now - 25 * 3_600_000).toISOString() }] });
    expect(expired).toMatchObject({ generatedAt, status: 'degraded', items: [{
      forecastHigh: null, marketForecastHigh: null, hourly: [], daily: [], currentTemp: 18, metarTemp: 19,
      eventSlug: 'current', bins: [{ yesTokenId: 'token' }],
    }] });
    expect(projectWeatherSnapshot(expired, now)).toBe(expired);
  });
});
