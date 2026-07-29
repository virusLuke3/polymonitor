import { describe, expect, it } from 'vitest';
import { worldEventMapReducer } from './mapReducer';
import { defaultWorldEventMapState } from './mapState';
import { filterWorldEventMapEvents } from './selectors';
import {
  parseWorldEventMapState,
  readStoredWorldEventMapState,
  serializeWorldEventMapUrl,
} from './urlState';
import type { GeoEvent } from '../domain/types';

describe('World Event Map state', () => {
  it('applies URL state after stored state and round-trips canonical fields', () => {
    const stored = readStoredWorldEventMapState(JSON.stringify({
      region: 'asia',
      center: { lon: 100, lat: 20 },
      zoom: 3,
      activeLayerIds: ['air-routes'],
      timeRange: '7d',
      severities: ['critical'],
    }));
    const fromUrl = parseWorldEventMapState(
      '?region=eu&center=11.5,48.2&zoom=4.25&layers=ucdp&time=24h&severity=warning,critical&event=UCDP%3A1',
      stored,
    );
    expect(fromUrl).toMatchObject({
      region: 'eu',
      center: { lon: 11.5, lat: 48.2 },
      zoom: 4.25,
      activeLayerIds: ['ucdp'],
      timeRange: '24h',
      severities: ['warning', 'critical'],
      selectedEventId: 'UCDP:1',
    });
    const serialized = serializeWorldEventMapUrl(fromUrl, 'https://example.test/?view=2d');
    expect(parseWorldEventMapState(new URL(serialized).search)).toMatchObject(fromUrl);
    expect(new URL(serialized).searchParams.get('view')).toBe('2d');
  });

  it('ignores unknown layers, regions and malformed coordinates', () => {
    const defaults = defaultWorldEventMapState();
    const parsed = parseWorldEventMapState(
      '?region=moon&center=999,999&layers=fake&time=forever&severity=catastrophic',
      defaults,
    );
    expect(parsed).toMatchObject({
      region: defaults.region,
      center: defaults.center,
      activeLayerIds: defaults.activeLayerIds,
      timeRange: defaults.timeRange,
      severities: defaults.severities,
    });
  });

  it('region actions update the real camera and reset affects only map state', () => {
    const initial = defaultWorldEventMapState();
    const asia = worldEventMapReducer(initial, { type: 'set-region', region: 'asia' });
    expect(asia).toMatchObject({ region: 'asia', center: { lon: 101, lat: 29 }, zoom: 2.35 });
    const withRoutes = worldEventMapReducer(asia, { type: 'toggle-layer', layerId: 'air-routes' });
    expect(withRoutes.activeLayerIds).toContain('air-routes');
    expect(worldEventMapReducer(withRoutes, { type: 'reset' })).toEqual(defaultWorldEventMapState());
  });

  it('filters by severity and a deterministic time window', () => {
    const now = Date.parse('2026-07-29T12:00:00Z');
    const base: GeoEvent = {
      id: 'fixture:1',
      category: 'conflict',
      title: 'Fixture',
      severity: 'warning',
      occurredAt: '2026-07-29T11:30:00Z',
      locationPrecision: 'unknown',
      sources: [{ provider: 'fixture' }],
      limitations: [],
      relatedMarketIds: [],
      properties: {},
    };
    expect(filterWorldEventMapEvents(
      [base, { ...base, id: 'fixture:2', severity: 'info' }],
      { timeRange: '1h', severities: ['warning'] },
      now,
    ).map((event) => event.id)).toEqual(['fixture:1']);
    expect(filterWorldEventMapEvents(
      [{ ...base, occurredAt: '2026-07-29T08:00:00Z' }],
      { timeRange: '1h', severities: ['warning'] },
      now,
    )).toHaveLength(0);
  });
});
