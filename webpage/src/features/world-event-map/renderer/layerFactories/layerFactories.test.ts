import { describe, expect, it } from 'vitest';
import type { Layer } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import { defaultWorldEventMapState } from '../../state/mapState';
import { createWorldEventLayers } from '.';
import { clusterEventPoints } from './eventPointLayer';

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

  it('clusters a 2,000 event fixture within the viewport and retains selection', () => {
    const events = Array.from({ length: 2_000 }, (_, index) => pointEvent(
      `fixture-${index}`,
      -179 + (index % 180) * 2,
      -70 + (index % 70) * 2,
      index % 97 === 0 ? 'critical' : 'watch',
    ));
    const clustered = clusterEventPoints(events, 1.25, 'fixture-1999', [-80, -60, 80, 75]);
    expect(clustered.singles.some((event) => event.id === 'fixture-1999')).toBe(true);
    expect(clustered.clusters.length).toBeGreaterThan(0);
    expect(clustered.singles.length + clustered.clusters.length).toBeLessThan(500);
  });
});
