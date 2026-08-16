import { afterEach, describe, expect, it, vi } from 'vitest';
import type { HazardMapResponse } from '../domain/types';
import { readHazardMapSnapshot, writeHazardMapSnapshot } from './hazardMapCache';

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
      sources: [],
      isPartial: false,
      errors: [],
      counts: { events: 0, byHazardKind: {} },
    } as HazardMapResponse;

    await writeHazardMapSnapshot('usgs', payload);
    const restored = await readHazardMapSnapshot('usgs');

    expect(restored?.source).toBe('usgs');
    expect(restored?.payload).toEqual(payload);
    expect(restored?.storedAt).toBeTypeOf('number');
  });
});
