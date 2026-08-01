import { describe, expect, it } from 'vitest';
import {
  OPENFREEMAP_DARK_STYLE,
  getWeatherMapStyle,
  refreshWorldEventBasemapLabelDensity,
  reinforceWorldEventBasemapLabels,
} from './weatherBasemap';

function createLabelMap(zoom: number) {
  let currentZoom = zoom;
  const updates: Array<[string, string, unknown]> = [];
  const map = {
    getZoom: () => currentZoom,
    getStyle: () => ({ layers: [
      { id: 'place_continent', type: 'symbol', 'source-layer': 'place' },
      { id: 'place_country_major', type: 'symbol', 'source-layer': 'place' },
      { id: 'place_country_minor', type: 'symbol', 'source-layer': 'place' },
      { id: 'place_country_other', type: 'symbol', 'source-layer': 'place' },
      { id: 'place_city_large', type: 'symbol', 'source-layer': 'place' },
      { id: 'place_city', type: 'symbol', 'source-layer': 'place' },
      { id: 'place_town', type: 'symbol', 'source-layer': 'place' },
      { id: 'road-shield', type: 'symbol' },
      { id: 'land', type: 'fill' },
    ] }),
    getLayoutProperty: (id: string) => id === 'road-shield' ? ['get', 'ref'] : ['get', 'name'],
    setLayoutProperty: (id: string, name: string, value: unknown) => updates.push([id, name, value]),
    setPaintProperty: (id: string, name: string, value: unknown) => updates.push([id, name, value]),
  };
  return { map, updates, setZoom: (next: number) => { currentZoom = next; } };
}

describe('World Event Map vector basemap', () => {
  it('uses the label-capable OpenFreeMap dark style as the primary basemap', () => {
    expect(getWeatherMapStyle('dark')).toBe(OPENFREEMAP_DARK_STYLE);
  });

  it('uses provider glyphs but applies a WorldMonitor-style hierarchy at global zoom', () => {
    const { map, updates } = createLabelMap(1.25);
    reinforceWorldEventBasemapLabels(map);
    expect(updates).toEqual(expect.arrayContaining([
      ['place_country_major', 'text-field', ['coalesce', ['get', 'name_en'], ['get', 'name:en'], ['get', 'name:latin'], ['get', 'name']]],
      ['place_country_major', 'text-size', ['interpolate', ['linear'], ['zoom'], 0, 12, 3, 14, 5, 16]],
      ['place_country_major', 'text-halo-width', 1],
      ['place_country_major', 'visibility', 'visible'],
      ['place_city_large', 'visibility', 'visible'],
      ['place_country_minor', 'visibility', 'none'],
      ['place_country_other', 'visibility', 'none'],
      ['place_city', 'visibility', 'none'],
      ['place_town', 'visibility', 'none'],
    ]));
    expect(updates.some(([id]) => id === 'road-shield')).toBe(false);
  });

  it('reveals label detail only after the corresponding zoom threshold', () => {
    const { map, updates, setZoom } = createLabelMap(1.25);
    reinforceWorldEventBasemapLabels(map);
    updates.length = 0;

    setZoom(2.4);
    refreshWorldEventBasemapLabelDensity(map);
    expect(updates).toEqual(expect.arrayContaining([
      ['place_country_minor', 'visibility', 'visible'],
      ['place_country_other', 'visibility', 'none'],
      ['place_city', 'visibility', 'none'],
    ]));

    updates.length = 0;
    setZoom(3.4);
    refreshWorldEventBasemapLabelDensity(map);
    expect(updates).toEqual(expect.arrayContaining([
      ['place_country_other', 'visibility', 'visible'],
      ['place_city', 'visibility', 'visible'],
      ['place_town', 'visibility', 'none'],
    ]));

    updates.length = 0;
    setZoom(4.8);
    refreshWorldEventBasemapLabelDensity(map);
    expect(updates).toEqual(expect.arrayContaining([
      ['place_town', 'visibility', 'visible'],
    ]));
  });
});
