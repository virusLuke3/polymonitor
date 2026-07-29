import { describe, expect, it } from 'vitest';
import {
  WORLD_EVENT_LAYER_REGISTRY,
  selectableWorldEventLayers,
  worldEventLayerById,
} from './layerRegistry';

describe('World Event Map layer registry', () => {
  it('is the single source of selectable product layers', () => {
    expect(selectableWorldEventLayers().map((layer) => layer.id)).toEqual(['ucdp', 'air-routes']);
    expect(selectableWorldEventLayers().filter((layer) => layer.defaultEnabled).map((layer) => layer.id)).toEqual(['ucdp']);
  });

  it('keeps incomplete country/intel rendering registered but unavailable', () => {
    expect(worldEventLayerById('intel-hotspots')?.selectable).toBe(false);
    expect(worldEventLayerById('sanctions-country-risk')?.selectable).toBe(false);
  });

  it('declares source, legend and limitations for every layer', () => {
    for (const layer of WORLD_EVENT_LAYER_REGISTRY) {
      expect(layer.sourceKeys.length).toBeGreaterThan(0);
      expect(layer.explanation.sources.length).toBeGreaterThan(0);
      expect(layer.explanation.limitations.length).toBeGreaterThan(0);
    }
  });
});
