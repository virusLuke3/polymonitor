import { describe, expect, it } from 'vitest';
import type { GeoEvent } from '../../domain/types';
import { countryRiskColor, createCountryRiskLayers, isCountryRiskArea } from './countryRiskLayers';

const countryRisk: GeoEvent = {
  id: 'risk:fixture',
  category: 'country-risk',
  title: 'Country risk evidence',
  severity: 'warning',
  geometry: { type: 'Polygon', coordinates: [[[0, 0], [2, 0], [2, 2], [0, 0]]] },
  locationPrecision: 'country',
  sources: [{ provider: 'fixture' }],
  limitations: [],
  relatedMarketIds: [],
  properties: { mapEntity: 'country-risk-area', evidenceCount: 18 },
};

describe('country risk map layer', () => {
  it('renders verified country evidence as a distinct polygon layer', () => {
    expect(isCountryRiskArea(countryRisk)).toBe(true);
    const layers = createCountryRiskLayers([countryRisk], null, 'country-boundaries') as unknown as Array<{
      id: string;
      props: Record<string, any>;
    }>;
    expect(layers[0]?.id).toBe('world-event-country-risk');
    const feature = layers[0]?.props.data.features[0];
    expect(layers[0]?.props.getFillColor(feature)[3]).toBe(25);
    expect(layers[0]?.props.getLineColor(feature)[3]).toBe(80);
    expect(layers[0]?.props.autoHighlight).toBe(false);
  });

  it('never turns evidence counts into a risk rating', () => {
    const sparse = { ...countryRisk, properties: { ...countryRisk.properties, evidenceCount: 1 } };
    const dense = { ...countryRisk, properties: { ...countryRisk.properties, evidenceCount: 5000 } };
    expect(countryRiskColor(sparse, 76)).toEqual(countryRiskColor(dense, 76));
    expect(countryRiskColor(countryRisk, 76)).toEqual([156, 146, 116, 76]);
  });

  it('places context below borders and labels, with a visible selected outline in pixels', () => {
    const [layer] = createCountryRiskLayers([countryRisk], countryRisk.id, 'country-boundaries') as any[];
    expect(layer.props.beforeId).toBe('country-boundaries');
    expect(layer.props.lineWidthUnits).toBe('pixels');
    const feature = layer.props.data.features[0];
    expect(layer.props.getLineWidth(feature)).toBeGreaterThan(layer.props.lineWidthMinPixels);
  });
});
