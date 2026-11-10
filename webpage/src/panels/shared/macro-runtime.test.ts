import { describe, expect, it } from 'vitest';
import { macroRefreshPolicy, macroSourceRefreshPolicy, macroSnapshot, projectMacroDisplay } from './macro-runtime';
import { energySnapshot } from './context-snapshots';
import { revalidateRuntimeSnapshots } from '../usePanelRuntime';
import { macroMapSnapshot } from '../modules/polymarket-macro-map/model';
import type { PanelModule } from '../types';
import { readResourceCache, writeResourceCache } from '@/panels/resource-cache';

const id = 'labor-services-inflation-monitor';
const contract = macroSnapshot(id);
const now = Date.now();
const payload = { panelId: id, schemaVersion: 2, status: 'ok', generatedAt: new Date(now).toISOString(),
  items: [{ key: 'payrolls', label: 'Nonfarm payrolls monthly change', value: 159029, change: 29, valueLabel: '29K persons', metadata: { fetchedAt: new Date(now).toISOString() } }] };

describe('macro snapshot and refresh contract', () => {
  it('polls independently with a deadline and a freshness budget longer than the seed cycle', () => {
    expect(macroRefreshPolicy.intervalMs).toBe(30 * 60_000);
    expect(macroRefreshPolicy.batch).toBe(false);
    expect(macroRefreshPolicy.requestTimeoutMs).toBe(45_000);
    expect(contract.maxAgeMs).toBeGreaterThan(30 * 60_000);
  });
  it('keeps six-hour source snapshots fresh across their scheduled cycle and bounds stale retention', () => {
    for (const source of [macroSnapshot('supply-tariff-import-watch', false, 'source'), energySnapshot(6)]) {
      expect(source.maxAgeMs).toBe(9 * 3_600_000);
      expect(source.staleAgeMs).toBe(18 * 3_600_000);
      const sixHoursOld = { status: 'ok', generatedAt: new Date(now - 6 * 3_600_000).toISOString(),
        items: [{ key: 'ppi', value: 1, fetchedAt: new Date(now - 6 * 3_600_000).toISOString() }] };
      const parsed = source.parse(sixHoursOld);
      expect(source.updatedAt(parsed)).toBe(now - 6 * 3_600_000);
      expect(projectMacroDisplay(parsed, now + 12 * 3_600_000)).toMatchObject({ items: [], status: 'expired' });
    }
    expect(macroSourceRefreshPolicy.intervalMs).toBe(5 * 60_000);
    expect(macroSourceRefreshPolicy.requestTimeoutMs).toBe(45_000);
    expect(contract.maxAgeMs).toBe(45 * 60_000);
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
  it('expires individual fetch clocks offline without mistaking an old observation month for stale acquisition', () => {
    const current = { ...payload, items: [
      { key: 'old', date: '2026-01-01', metadata: { fetchedAt: new Date(now - 17 * 3600000).toISOString() } },
      { key: 'new', date: '2026-01-01', metadata: { fetchedAt: new Date(now).toISOString() } },
    ] };
    expect(projectMacroDisplay(current, now)).toBe(current);
    const panel = { id, snapshot: contract } as PanelModule;
    const unmodified = { id: 'unrelated', snapshot: { ...contract, revalidate: undefined, parse: () => { throw Error('Not opt-in'); } } } as unknown as PanelModule;
    const data = { [id]: current, unrelated: current };
    const next = revalidateRuntimeSnapshots([panel, unmodified], data, now + 2 * 3600000);
    expect((next[id] as typeof current).items.map(row => row.key)).toEqual(['new']);
    expect(next.unrelated).toBe(current);
    expect(revalidateRuntimeSnapshots([panel, unmodified], next, now + 2 * 3600000)).toBe(next);
    expect(data[id].items).toHaveLength(2);
  });
  it('clears CPI actuals after 5400 seconds even when the composed snapshot is newly generated', () => {
    const current = { ...payload, events: [{ actual: 0, previous: 2, actualLabel: '0.0%',
      fetchedAt: new Date(now - 5399000).toISOString(), forecast: 3,
      forecastFetchedAt: new Date(now).toISOString() }] };
    expect(projectMacroDisplay(current, now)).toBe(current);
    const projected = projectMacroDisplay(current, now + 1000) as typeof current;
    expect(projected.events[0]?.actual).toBeNull();
    expect(projected.events[0]?.previous).toBeNull();
    expect(projected.events[0]?.forecast).toBe(3);
  });
  it('expires macro-map quote clocks at two hours without refreshing them from projection time', () => {
    const current = { generatedAt: new Date(now).toISOString(), status: 'degraded', items: [
      { eventId: 'old', sourceObservedAt: new Date(now - 7199000).toISOString() },
      { eventId: 'new', sourceObservedAt: new Date(now).toISOString() },
    ] };
    const panel = { id: 'map', snapshot: macroMapSnapshot } as PanelModule;
    const next = revalidateRuntimeSnapshots([panel], { map: current }, now + 1000);
    expect((next.map as typeof current).items.map(row => row.eventId)).toEqual(['new']);
    expect((next.map as typeof current).generatedAt).toBe(current.generatedAt);
  });
});
