import { describe, expect, it } from 'vitest';
import type { Layer } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import { defaultWorldEventMapState } from '../../state/mapState';
import { createWorldEventLayers } from '.';
import {
  aviationRouteMotionPoints,
  aviationLayerStatsForState,
  createAviationDynamicLayers,
  createAviationStaticLayerSections,
  selectAviationRenderData,
} from './aviationLayers';
import { clusterEventPoints, EventClusterIndex } from './eventPointLayer';

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

const hazardPoint = (id: string, hazardKind: 'earthquake' | 'volcano', lon: number, lat: number): GeoEvent => ({
  ...pointEvent(id, lon, lat),
  category: 'natural-hazard',
  properties: { mapEntity: 'hazard-event' },
  hazardKind,
  lifecycle: 'active',
  coverage: { scope: 'global', label: 'fixture', isComplete: false, gaps: [] },
  severityEvidence: { provider: 'fixture', mappingVersion: 'fixture', reason: 'fixture' },
  revision: { nativeEventId: id },
  metrics: hazardKind === 'earthquake'
    ? { kind: 'earthquake', magnitude: 4.5 }
    : { kind: 'volcano-or-other', statusLabel: 'active' },
} as GeoEvent);

const aviationState = () => {
  const state = defaultWorldEventMapState();
  return {
    ...state,
    activeLayerIds: [...state.activeLayerIds, 'air-routes'],
    aviationLens: 'all' as const,
  };
};

describe('world event layer factories', () => {
  it('uses stable layer ids and clusters dense global points', () => {
    const state = defaultWorldEventMapState();
    const layers = createWorldEventLayers([
      pointEvent('a', 10, 10),
      pointEvent('b', 10.2, 10.1),
      pointEvent('c', 10.3, 10.2, 'critical'),
    ], state);
    expect((layers as Layer[]).map((layer) => layer.id)).toEqual([
      'world-event-cluster-halos',
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

  it('keeps earthquakes and volcanoes individually visible at world zoom like WorldMonitor', () => {
    const events = [
      hazardPoint('eq:a', 'earthquake', 10, 10),
      hazardPoint('eq:b', 'earthquake', 10.1, 10.1),
      hazardPoint('eq:c', 'earthquake', 10.2, 10.2),
      hazardPoint('vo:a', 'volcano', 11, 11),
    ];
    const clustered = clusterEventPoints(events, 1.25, null);
    expect(clustered.clusters).toHaveLength(0);
    expect(clustered.singles.map((event) => event.id)).toEqual(['eq:a', 'eq:b', 'eq:c', 'vo:a']);
  });

  it('does not combine different conflict types into one generic cluster', () => {
    const events = [
      { ...pointEvent('state:1', 10, 10), properties: { violenceType: '1' } },
      { ...pointEvent('state:2', 10.1, 10.1), properties: { violenceType: '1' } },
      { ...pointEvent('state:3', 10.2, 10.2), properties: { violenceType: '1' } },
      { ...pointEvent('nonstate:1', 10, 10), properties: { violenceType: '2' } },
      { ...pointEvent('nonstate:2', 10.1, 10.1), properties: { violenceType: '2' } },
      { ...pointEvent('nonstate:3', 10.2, 10.2), properties: { violenceType: '2' } },
    ];
    const clustered = clusterEventPoints(events, 1.25, null);
    expect(clustered.clusters.map((cluster) => cluster.label).sort()).toEqual([
      'non-state conflict',
      'state-based conflict',
    ]);
  });

  it('reuses persistent Supercluster indexes across viewport and selection changes', () => {
    const events = Array.from({ length: 240 }, (_, index) => pointEvent(
      `persistent:${index}`,
      10 + (index % 20) * 0.01,
      10 + Math.floor(index / 20) * 0.01,
      index === 239 ? 'critical' : 'watch',
    ));
    const index = new EventClusterIndex();
    index.update(events);
    const first = index.query(1.25, null, [9, 9, 12, 12]);
    const selected = index.query(2.1, 'persistent:239', [9.5, 9.5, 11.5, 11.5]);
    index.update(events);

    expect(index.buildCount).toBe(1);
    expect(first.clusters[0]?.eventIds.length).toBeLessThanOrEqual(200);
    expect(first.clusters[0]?.count).toBe(240);
    expect(selected.singles.some((event) => event.id === 'persistent:239')).toBe(true);
    expect(index.buildCount).toBe(1);

    index.update([...events]);
    expect(index.buildCount).toBe(2);
  });

  it('keeps warning events as persistent priority rings rather than forcing a global RAF loop', () => {
    const warning = pointEvent('warning', 10, 10, 'warning');
    const layers = createWorldEventLayers(
      [warning],
      defaultWorldEventMapState(),
      true,
      undefined,
      1.5,
    ) as Layer[];
    expect(layers.some((layer) => layer.id === 'world-event-priority-rings')).toBe(true);
    expect(layers.some((layer) => layer.id === 'world-event-pulses')).toBe(false);
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
      .toEqual(['world-event-context-areas', 'world-event-paths']);
  });

  it('renders aviation reference arcs, route runners, aircraft and hubs as a dedicated lens', () => {
    const state = aviationState();
    const route: GeoEvent = {
      ...pointEvent('route:0', 0, 0),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[0, 0], [4, 3], [8, 4]] },
      properties: {
        mapEntity: 'air-route',
        routeId: 'route',
        layer: 'trunk',
        trafficScore: 90,
      },
    };
    const hub: GeoEvent = {
      ...pointEvent('hub', 0, 0),
      category: 'infrastructure',
      properties: { mapEntity: 'air-hub', code: 'HUB', routeCount: 100 },
    };
    expect((createWorldEventLayers([route, hub], state, true, undefined, 5) as Layer[]).map((layer) => layer.id))
      .toEqual([
        'aviation-route-underlay',
        'aviation-route-core',
        'aviation-route-runners',
        'aviation-hubs',
        'aviation-hub-labels',
      ]);
    const atStart = aviationRouteMotionPoints([route], 0)[0]?.position;
    const afterMotion = aviationRouteMotionPoints([route], 8)[0]?.position;
    expect(afterMotion).not.toEqual(atStart);
  });

  it('keeps geometry below aviation and points in the final compositing order', () => {
    const state = defaultWorldEventMapState();
    const area: GeoEvent = {
      ...pointEvent('risk-area', 0, 0),
      category: 'country-risk',
      geometry: { type: 'Polygon', coordinates: [[[0, 0], [2, 0], [2, 2], [0, 0]]] },
      properties: { mapEntity: 'country-risk-area', evidenceCount: 18 },
    };
    const route: GeoEvent = {
      ...pointEvent('route:above-area', 0, 0),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[0, 0], [3, 3]] },
      properties: { mapEntity: 'air-route', routeId: 'above-area', layer: 'trunk' },
    };
    const enabled = { ...aviationState(), activeLayerIds: [...state.activeLayerIds, 'air-routes'] };
    const ids = (createWorldEventLayers([area, route], enabled) as Layer[]).map((layer) => layer.id);
    expect(ids.indexOf('world-event-country-risk')).toBeLessThan(ids.indexOf('aviation-route-core'));
  });

  it('uses an icon layer instead of a font glyph for animated aircraft', () => {
    const state = aviationState();
    const flight: GeoEvent = {
      ...pointEvent('flight:0', 0, 0),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[0, 0], [4, 3]] },
      properties: { mapEntity: 'air-flight', flightId: 'flight', phase: 0.1, speed: 0.06 },
    };
    const layers = createWorldEventLayers([flight], state, true, undefined, 5) as Layer[];
    const aircraftLayer = layers.find((layer) => layer.id === 'aviation-seeded-aircraft');
    expect(aircraftLayer?.constructor.name).toBe('IconLayer');
    expect(aircraftLayer?.props.pickable).toBe(true);
    const picked = (aircraftLayer?.props.data as Array<{ event?: GeoEvent }>)[0];
    expect(picked?.event?.id).toBe('flight:0');
  });

  it('shares the bounded aviation selection with the WebGL and SVG renderers', () => {
    const routes = Array.from({ length: 220 }, (_, index): GeoEvent => ({
      ...pointEvent(`route:${index}`, 0, 0, 'info'),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[0, 0], [index / 10, 4]] },
      properties: {
        mapEntity: 'air-route',
        routeId: `route-${index}`,
        layer: index < 12 ? 'trunk' : 'international',
        trafficScore: 220 - index,
      },
    }));
    const selected = selectAviationRenderData(routes, aviationState());

    expect(selected.routes).toHaveLength(120);
    expect(new Set(selected.routes.map((route) => route.properties.routeId)).size).toBe(120);
  });

  it('precomputes a bounded world-view aviation generation outside the animation frame', () => {
    const routes = Array.from({ length: 180 }, (_, index): GeoEvent => ({
      ...pointEvent(`route:${index}`, 0, 0, 'info'),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[-70 + index / 10, 0], [-68 + index / 10, 5]] },
      properties: { mapEntity: 'air-route', routeId: `route-${index}`, layer: 'international', trafficScore: 180 - index },
    }));
    const flights = Array.from({ length: 80 }, (_, index): GeoEvent => ({
      ...pointEvent(`flight:${index}`, 0, 0, 'info'),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[-30 + index / 10, -3], [-28 + index / 10, 4]] },
      properties: { mapEntity: 'air-flight', flightId: `flight-${index}`, layer: 'international', phase: index / 100 },
    }));
    const live = Array.from({ length: 40 }, (_, index): GeoEvent => ({
      ...pointEvent(`live:${index}`, -20 + index, 8, 'info'),
      category: 'infrastructure',
      properties: { mapEntity: 'live-aircraft', heading: 90 },
    }));
    const selected = selectAviationRenderData([...routes, ...flights, ...live], aviationState());

    expect(selected.routes).toHaveLength(120);
    expect(selected.routeMotionGroups).toHaveLength(48);
    expect(selected.flights).toHaveLength(30);
    expect(selected.flightMotionGroups).toHaveLength(30);
    expect(selected.liveAircraft).toHaveLength(24);
    expect(aviationLayerStatsForState([...routes, ...flights, ...live], aviationState()))
      .toMatchObject({
        visibleRoutes: 120,
        visibleFlights: 30,
        visibleLiveAircraft: 24,
      });

    const staticSections = createAviationStaticLayerSections(
      [...routes, ...flights, ...live],
      aviationState(),
    );
    const dynamicLayers = createAviationDynamicLayers(staticSections.data, 1) as Layer[];
    expect((staticSections.routeLayers as Layer[]).map((layer) => layer.id)).toEqual([
      'aviation-route-underlay',
      'aviation-route-core',
    ]);
    expect(dynamicLayers.map((layer) => layer.id)).toEqual([
      'aviation-route-runners',
      'aviation-seeded-aircraft',
    ]);
  });

  it('fills the trunk world budget without dropping untagged hubs or live aircraft', () => {
    const routes = Array.from({ length: 360 }, (_, index): GeoEvent => ({
      ...pointEvent(`route:${index}`, 0, 0, 'info'),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[-80 + index, 0], [-79 + index, 5]] },
      properties: {
        mapEntity: 'air-route',
        routeId: `route-${index}`,
        fromCode: `H${String(index).padStart(2, '0')}`,
        toCode: `H${String(index + 1).padStart(2, '0')}`,
        layer: index < 18 ? 'trunk' : 'international',
        trafficScore: 360 - index,
      },
    }));
    const flights = Array.from({ length: 140 }, (_, index): GeoEvent => ({
      ...pointEvent(`flight:${index}`, 0, 0, 'info'),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[-40 + index, -3], [-39 + index, 4]] },
      properties: {
        mapEntity: 'air-flight',
        flightId: `flight-${index}`,
        layer: index < 18 ? 'trunk' : 'international',
        trafficScore: 140 - index,
      },
    }));
    const hubs = Array.from({ length: 24 }, (_, index): GeoEvent => ({
      ...pointEvent(`hub:${index}`, index, 8, 'info'),
      category: 'infrastructure',
      properties: {
        mapEntity: 'air-hub',
        code: `H${String(index).padStart(2, '0')}`,
        routeCount: index,
      },
    }));
    const live = Array.from({ length: 61 }, (_, index): GeoEvent => ({
      ...pointEvent(`live:${index}`, index, 12, 'info'),
      category: 'infrastructure',
      properties: { mapEntity: 'live-aircraft', velocity: 300 - index },
    }));
    const selected = selectAviationRenderData(
      [...routes, ...flights, ...hubs, ...live],
      { ...aviationState(), aviationLens: 'trunk' },
    );

    expect(new Set(selected.routes.map((route) => route.properties.routeId)).size).toBe(86);
    expect(selected.routes.filter((route) => route.properties.layer === 'trunk')).toHaveLength(18);
    expect(selected.hubs).toHaveLength(12);
    expect(selected.hubs.every((hub) => Number(String(hub.properties.code).slice(1)) <= 18)).toBe(true);
    expect(selected.flightMotionGroups).toHaveLength(22);
    expect(selected.flightMotionGroups.filter((group) => group.event.properties.layer === 'trunk')).toHaveLength(18);
    expect(selected.liveAircraft).toHaveLength(17);

    const watch = selectAviationRenderData(
      [...routes, ...flights, ...hubs, ...live],
      { ...aviationState(), aviationLens: 'watch', aviationRiskSource: 'weather' },
    );
    expect(watch).toMatchObject({ routes: [], hubs: [], flights: [], liveAircraft: [] });
  });

  it('culls aviation paths and aircraft to a padded local viewport without hiding world-view data', () => {
    const nearRoute: GeoEvent = {
      ...pointEvent('near-route', 0, 0, 'info'),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[0, 0], [10, 5]] },
      properties: { mapEntity: 'air-route', routeId: 'near', layer: 'international' },
    };
    const distantRoute: GeoEvent = {
      ...pointEvent('distant-route', 0, 0, 'info'),
      category: 'infrastructure',
      geometry: { type: 'LineString', coordinates: [[120, 0], [130, 5]] },
      properties: { mapEntity: 'air-route', routeId: 'distant', layer: 'international' },
    };
    const nearAircraft: GeoEvent = {
      ...pointEvent('near-aircraft', 2, 2, 'info'),
      category: 'infrastructure',
      properties: { mapEntity: 'live-aircraft' },
    };
    const distantAircraft: GeoEvent = {
      ...pointEvent('distant-aircraft', 130, 2, 'info'),
      category: 'infrastructure',
      properties: { mapEntity: 'live-aircraft' },
    };
    const selected = selectAviationRenderData(
      [nearRoute, distantRoute, nearAircraft, distantAircraft],
      { ...aviationState(), zoom: 3 },
      [-20, -20, 20, 20],
    );

    expect(selected.routes.map((event) => event.properties.routeId)).toEqual(['near']);
    expect(selected.liveAircraft.map((event) => event.id)).toEqual(['near-aircraft']);
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
