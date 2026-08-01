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

  it('uses the provider English field and zoom-density rules without changing its font or rank', () => {
    const updates: Array<[string, string, unknown]> = [];
    reinforceWorldEventBasemapLabels({
      getStyle: () => ({ layers: [
        { id: 'place_country_major', type: 'symbol', 'source-layer': 'place' },
        { id: 'place_town', type: 'symbol', 'source-layer': 'place' },
        { id: 'road-shield', type: 'symbol' },
        { id: 'land', type: 'fill' },
      ] }),
      getLayoutProperty: (id) => id === 'road-shield' ? ['get', 'ref'] : ['get', 'name'],
      setLayoutProperty: (id, name, value) => updates.push([id, name, value]),
      setPaintProperty: (id, name, value) => updates.push([id, name, value]),
    });
    expect(updates).toEqual(expect.arrayContaining([
      ['place_country_major', 'text-field', ['coalesce', ['get', 'name_en'], ['get', 'name:en'], ['get', 'name:latin'], ['get', 'name']]],
      ['place_country_major', 'text-halo-width', 1.35],
      ['place_town', 'text-opacity', ['interpolate', ['linear'], ['zoom'], 0, 0, 3.4, 0, 4.25, 0.72]],
    ]));
    expect(updates.some(([id]) => id === 'road-shield')).toBe(false);
  });
});
