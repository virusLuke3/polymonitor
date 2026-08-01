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
    const layers = createCountryRiskLayers([countryRisk], null) as unknown as Array<{ id: string }>;
    expect(layers[0]?.id).toBe('world-event-country-risk');
  });

  it('uses a warm risk scale instead of a natural-hazard color', () => {
    expect(countryRiskColor(countryRisk, 76)).toEqual([244, 112, 48, 76]);
    expect(countryRiskColor({ ...countryRisk, severity: 'critical' }, 255)).toEqual([225, 61, 49, 255]);
  });
});
