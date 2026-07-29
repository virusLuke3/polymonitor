import { describe, expect, it } from 'vitest';
import type { Layer } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import { defaultWorldEventMapState } from '../../state/mapState';
import { createWorldEventLayers } from '.';

const pointEvent = (id: string, lon: number, lat: number, severity: GeoEvent['severity'] = 'watch'): GeoEvent => ({
  id,
  category: 'conflict',
  title: id,
  severity,
  geometry: { type: 'Point', coordinates: [lon, lat] },
  locationPrecision: 'exact',
  sources: [{ provider: 'fixture', nativeId: id }],
  limitations: [],
  relatedMarketIds: [],
  properties: {},
});

describe('world event layer factories', () => {
  it('uses stable layer ids and clusters dense global points', () => {
    const state = defaultWorldEventMapState();
    const layers = createWorldEventLayers([
      pointEvent('a', 10, 10),
      pointEvent('b', 10.2, 10.1),
      pointEvent('c', 10.3, 10.2, 'critical'),
    ], state);
    expect((layers as Layer[]).map((layer) => layer.id)).toEqual([
      'world-event-clusters',
      'world-event-cluster-counts',
    ]);
  });

  it('keeps the selected event outside a cluster', () => {
    const state = { ...defaultWorldEventMapState(), selectedEventId: 'a' };
    const layers = createWorldEventLayers([
      pointEvent('a', 10, 10),
      pointEvent('b', 10.2, 10.1),
      pointEvent('c', 10.3, 10.2),
    ], state);
    expect((layers as Layer[]).some((layer) => layer.id === 'world-event-points')).toBe(true);
  });

  it('creates polygon and line layers without accessing the DOM', () => {
    const area: GeoEvent = {
      ...pointEvent('area', 0, 0),
      category: 'natural-hazard',
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] },
    };
    const line: GeoEvent = {
      ...pointEvent('line', 0, 0),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] },
    };
    expect((createWorldEventLayers([area, line], defaultWorldEventMapState()) as Layer[]).map((layer) => layer.id))
      .toEqual(['world-event-areas', 'world-event-paths']);
  });
});
