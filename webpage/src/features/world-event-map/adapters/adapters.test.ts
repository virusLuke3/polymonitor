import { describe, expect, it } from 'vitest';
import { adaptBreakingEventPayload } from './breakingEventAdapter';
import { adaptGeoShockPayload } from './geoShockAdapter';
import { adaptTransportDisruptions } from './transportDisruptionAdapter';
import { adaptTransportReference } from './transportReferenceAdapter';

describe('World Event Map adapters', () => {
  it('normalizes UCDP data into stable canonical conflict events', () => {
    const result = adaptGeoShockPayload({
      source: 'UCDP',
      status: 'ok',
      items: [{
        id: '123',
        headline: 'Conflict fixture',
        country: 'Ukraine',
        latitude: '49.0',
        longitude: '32.0',
        violenceType: 1,
        deathsBest: 4,
        occurredAt: '2026-07-28T00:00:00Z',
      }],
    });
    expect(result.rejected).toHaveLength(0);
    expect(result.events).toEqual([
      expect.objectContaining({
        id: 'UCDP:123',
        category: 'conflict',
        geometry: { type: 'Point', coordinates: [32, 49] },
        locationPrecision: 'exact',
        properties: expect.objectContaining({ deathsBest: 4, violenceType: '1' }),
      }),
    ]);
  });

  it('keeps country-level records non-spatial instead of inventing a coordinate', () => {
    const result = adaptGeoShockPayload({
      source: 'UCDP',
      items: [{ id: 'country-only', country: 'Sudan', headline: 'Country-level fixture' }],
    });
    expect(result.events[0]).toMatchObject({
      locationPrecision: 'country',
      geometry: undefined,
    });
  });

  it('rejects records without provider-native identity', () => {
    const result = adaptGeoShockPayload({
      source: 'UCDP',
      items: [{ headline: 'No id', latitude: 1, longitude: 2 }],
    });
    expect(result.events).toHaveLength(0);
    expect(result.rejected[0]?.code).toBe('missing-stable-id');
  });

  it('does not turn breaking-news country labels into fake markers', () => {
    const result = adaptBreakingEventPayload({
      source: 'Breaking Radar',
      items: [{
        id: 'news-1',
        title: 'Verified country-level event',
        country: 'Japan',
        severity: 'watch',
        relatedPolymarketMarketIds: [42],
      }],
    });
    expect(result.events[0]).toMatchObject({
      category: 'intel',
      locationPrecision: 'country',
      relatedMarketIds: ['42'],
    });
    expect(result.events[0]?.geometry).toBeUndefined();
  });

  it('only emits transport disruptions at watch severity or above', () => {
    const result = adaptTransportDisruptions({
      source: 'Transport',
      items: [
        { id: 'normal', title: 'Normal route', severity: 'normal' },
        {
          id: 'closure',
          title: 'Airport closure',
          severity: 'alert',
          evidence: { lon: 103.99, lat: 1.36 },
        },
      ],
    });
    expect(result.events).toHaveLength(1);
    expect(result.events[0]).toMatchObject({
      id: 'Transport:closure',
      category: 'transport-disruption',
      geometry: { type: 'Point', coordinates: [103.99, 1.36] },
    });
  });

  it('normalizes optional route topology into canonical reference geometry', () => {
    const result = adaptTransportReference({
      source: 'OpenFlights',
      aviation: {
        routes: [{
          id: 'SIN-LHR',
          fromCode: 'SIN',
          toCode: 'LHR',
          fromLon: 103.99,
          fromLat: 1.36,
          toLon: -0.45,
          toLat: 51.47,
          layer: 'trunk',
        }],
        hubs: [{ code: 'SIN', lon: 103.99, lat: 1.36 }],
      },
      items: [],
    });
    expect(result.rejected).toHaveLength(0);
    expect(result.events.map((item) => item.properties.mapEntity)).toEqual(['air-route', 'air-hub']);
    expect(result.events[0]?.geometry).toEqual({
      type: 'LineString',
      coordinates: [[103.99, 1.36], [-0.45, 51.47]],
    });
  });
});
