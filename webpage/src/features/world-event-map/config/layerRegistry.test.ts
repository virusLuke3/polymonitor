import { describe, expect, it } from 'vitest';
import {
  WORLD_EVENT_LAYER_REGISTRY,
  eventMatchesWorldEventLayers,
  selectableWorldEventLayers,
  worldEventLayerIdForEvent,
  worldEventLayerById,
} from './layerRegistry';
import type { HazardEvent } from '../domain/types';

describe('World Event Map layer registry', () => {
  it('is the single source of selectable product layers', () => {
    expect(selectableWorldEventLayers().map((layer) => layer.id)).toEqual([
      'weather-alerts',
      'earthquakes-volcanoes',
      'wildfires',
      'extreme-temperature',
      'climate-anomalies',
      'air-routes',
      'intel-hotspots',
      'ucdp',
      'sanctions-country-risk',
    ]);
    expect(selectableWorldEventLayers().filter((layer) => layer.defaultEnabled).map((layer) => layer.id)).toEqual([
      'weather-alerts',
      'earthquakes-volcanoes',
      'wildfires',
      'extreme-temperature',
      'climate-anomalies',
      'air-routes',
    ]);
  });

  it('exposes evidence-gated country layers as real optional controls', () => {
    expect(worldEventLayerById('intel-hotspots')?.selectable).toBe(true);
    expect(worldEventLayerById('sanctions-country-risk')?.selectable).toBe(true);
    expect(worldEventLayerById('intel-hotspots')?.defaultEnabled).toBe(false);
    expect(worldEventLayerById('sanctions-country-risk')?.defaultEnabled).toBe(false);
  });

  it('declares source, legend and limitations for every layer', () => {
    for (const layer of WORLD_EVENT_LAYER_REGISTRY) {
      expect(layer.sourceKeys.length).toBeGreaterThan(0);
      expect(layer.explanation.sources.length).toBeGreaterThan(0);
      expect(layer.explanation.limitations.length).toBeGreaterThan(0);
    }
  });

  it('maps hazards by hazard kind instead of the broad natural-hazard category', () => {
    const event = {
      id: 'earthquake:usgs:test',
      category: 'natural-hazard',
      title: 'M5.0 earthquake',
      severity: 'warning',
      locationPrecision: 'exact',
      sources: [{ provider: 'USGS' }],
      limitations: [],
      relatedMarketIds: [],
      properties: {},
      hazardKind: 'earthquake',
      lifecycle: 'observed',
      coverage: { scope: 'global', label: 'USGS', isComplete: false, gaps: [] },
      severityEvidence: { provider: 'USGS', mappingVersion: 'v1', reason: 'magnitude' },
      revision: { nativeEventId: 'test' },
      metrics: { kind: 'earthquake', magnitude: 5 },
    } satisfies HazardEvent;
    expect(worldEventLayerIdForEvent(event)).toBe('earthquakes-volcanoes');
    expect(eventMatchesWorldEventLayers(event, ['earthquakes-volcanoes'])).toBe(true);
    expect(eventMatchesWorldEventLayers(event, ['weather-alerts'])).toBe(false);
  });
});
