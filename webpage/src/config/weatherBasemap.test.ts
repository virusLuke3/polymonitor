import { describe, expect, it } from 'vitest';
import {
  OPENFREEMAP_DARK_STYLE,
  getWeatherMapStyle,
  reinforceWorldEventBasemapLabels,
} from './weatherBasemap';

describe('World Event Map vector basemap', () => {
  it('uses the label-capable OpenFreeMap dark style as the primary basemap', () => {
    expect(getWeatherMapStyle('dark')).toBe(OPENFREEMAP_DARK_STYLE);
  });

  it('adds a halo to provider-owned place labels without changing their font or rank', () => {
    const updates: Array<[string, string, unknown]> = [];
    reinforceWorldEventBasemapLabels({
      getStyle: () => ({ layers: [
        { id: 'country-name', type: 'symbol' },
        { id: 'road-shield', type: 'symbol' },
        { id: 'land', type: 'fill' },
      ] }),
      getLayoutProperty: (id) => id === 'country-name' ? ['get', 'name'] : ['get', 'ref'],
      setPaintProperty: (id, name, value) => updates.push([id, name, value]),
    });
    expect(updates).toEqual([
      ['country-name', 'text-halo-color', '#070a0c'],
      ['country-name', 'text-halo-width', 1.15],
    ]);
  });
});
