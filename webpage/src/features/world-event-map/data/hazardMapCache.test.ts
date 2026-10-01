import { afterEach, describe, expect, it, vi } from 'vitest';
import type { HazardMapResponse } from '../domain/types';
import {
  hazardMapGeometryZoom,
  readHazardMapSnapshot,
  writeHazardMapSnapshot,
} from './hazardMapCache';

describe('hazard map last-good cache', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('falls back to localStorage when IndexedDB is unavailable', async () => {
    const values = new Map<string, string>();
    vi.stubGlobal('indexedDB', undefined);
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) || null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    const payload = {
      schemaVersion: 'natural-hazards-map.v1',
      generatedAt: '2026-08-16T00:00:00Z',
      events: [],
      sources: [{key: "usgs", fetchedAt: new Date().toISOString(), status: "ok", coverage: {scope: "global", label: "Controlled cache fixture", isComplete: false, gaps: []}}],
      isPartial: false,
      errors: [],
      counts: { events: 0, byHazardKind: {} },
    } as HazardMapResponse;

    await writeHazardMapSnapshot('usgs', 2, payload);
    const restored = await readHazardMapSnapshot('usgs', 2);

    expect(restored?.source).toBe('usgs');
    expect(restored?.payload).toEqual(payload);
    expect(restored?.storedAt).toBeTypeOf('number');
  });

  it('keeps geometry tiers independent and falls back to the global snapshot', async () => {
    const values = new Map<string, string>();
    vi.stubGlobal('indexedDB', undefined);
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => values.get(key) || null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    const payload = {
      schemaVersion: 'natural-hazards-map.v1',
      generatedAt: '2026-08-16T00:00:00Z',
      events: [],
      sources: [{key: "nws", fetchedAt: new Date().toISOString(), status: "ok", coverage: {scope: "global", label: "Controlled cache fixture", isComplete: false, gaps: []}}],
      isPartial: false,
      errors: [],
      counts: { events: 0, byHazardKind: {} },
    } as HazardMapResponse;

    await writeHazardMapSnapshot('nws', 2, payload);

    expect((await readHazardMapSnapshot('nws', 4))?.geometryZoom).toBe(2);
    expect(hazardMapGeometryZoom(1.5)).toBe(2);
    expect(hazardMapGeometryZoom(3.5)).toBe(4);
    expect(hazardMapGeometryZoom(7)).toBe(6);
  });
});

it('rejects source-specific expired snapshots regardless of recent cache receipt', async () => {
  const {hazardSnapshotRetainable}=await import('./hazardMapCache');
  const now=Date.parse('2026-10-01T01:00:00Z');
  const response={sources:[{key:'nws',fetchedAt:'2026-10-01T00:44:59Z'}]} as HazardMapResponse;
  expect(hazardSnapshotRetainable('nws',response,now)).toBe(false);
  expect(hazardSnapshotRetainable('nws',{sources:[{key:'nws',fetchedAt:'2026-10-01T00:59:00Z'}]} as HazardMapResponse,now)).toBe(true);
});

it('uses the source receipt deadline rather than a new browser cache write time', async()=>{
  const {hazardSnapshotExpiresAt}=await import('./hazardMapCache');
  const stamp='2026-10-01T00:00:00Z';const payload={sources:[{key:'nws',fetchedAt:stamp}]} as HazardMapResponse;
  expect(hazardSnapshotExpiresAt('nws',payload)).toBe(Date.parse(stamp)+900_000);
  expect(hazardSnapshotExpiresAt('usgs',payload)).toBeNull();
});
