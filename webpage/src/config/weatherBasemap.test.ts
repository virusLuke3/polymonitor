import { describe, expect, it } from 'vitest';
import {
  OPENFREEMAP_DARK_STYLE,
  mapBasemapFonts,
  buildWorldEventPMTilesStyle,
  getWeatherMapFallbackStyle,
  getWeatherMapStyle,
  reinforceWorldEventBasemapLabels,
  resolveWorldEventPMTilesUrl,
} from './weatherBasemap';

function createLabelMap(zoom: number) {
  let currentZoom = zoom;
  const updates: Array<[string, string, unknown]> = [];
  const map = {
    getZoom: () => currentZoom,
    getStyle: () => ({ sources: {}, layers: [
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
  it('localizes primary labels without replacing provider rank or styling', () => {
    const { map, updates } = createLabelMap(2);
    reinforceWorldEventBasemapLabels(map, 'zh');
    expect(updates).toContainEqual(['place_country_major', 'text-field', [
      'coalesce', ['get', 'name:zh-Hans'], ['get', 'name:zh'], ['get', 'name_zh'],
      ['coalesce', ['get', 'name_en'], ['get', 'name:en'], ['get', 'name:latin'], ['get', 'name']],
    ]]);
    expect(updates.some(([id]) => id === 'road-shield')).toBe(false);
    updates.length = 0;
    reinforceWorldEventBasemapLabels(map, 'en');
    expect(JSON.stringify(updates)).not.toContain('name:zh');
  });
  it('resolves a same-origin PMTiles route before handing it to the protocol', () => {
    expect(resolveWorldEventPMTilesUrl('/map-tiles/planet.pmtiles', 'https://polymonitor.club'))
      .toBe('https://polymonitor.club/map-tiles/planet.pmtiles');
    expect(resolveWorldEventPMTilesUrl('https://maps.example.test/planet.pmtiles', 'https://polymonitor.club'))
      .toBe('https://maps.example.test/planet.pmtiles');
  });

  it('keeps readable country labels in the local GeoJSON fallback', () => {
    const style = getWeatherMapFallbackStyle('dark');
    const labels = style.layers.find((layer) => layer.id === 'wm-local-country-labels');
    expect(style).not.toHaveProperty('glyphs');
    expect(labels).toMatchObject({
      type: 'symbol',
      source: 'wm-weather-country-boundaries',
      layout: {
        'text-size': ['interpolate', ['linear'], ['zoom'], 0, 13, 3, 15, 5, 17],
      },
      paint: {
        'text-color': '#aeb7ba',
        'text-halo-width': 1.25,
        'text-opacity': 0.94,
      },
    });
  });

  it('uses the zero-config OpenFreeMap style outside the production PMTiles build', async () => {
    expect(await getWeatherMapStyle('dark')).toBe(OPENFREEMAP_DARK_STYLE);
  });

  it('preserves every provider layer, rank and layout while applying one paint palette', async () => {
    const { layers, namedFlavor } = await import('@protomaps/basemaps');
    const original = layers('basemap', namedFlavor('black'), { lang: 'en' });
    const style = await buildWorldEventPMTilesStyle('https://maps.example.test/planet.pmtiles');
    expect(style.layers.map(layer => layer.id)).toEqual(original.map(layer => layer.id));
    for (const [index, layer] of original.entries()) {
      const actual = style.layers[index] as any;
      expect(actual.layout).toEqual(layer.type === 'symbol' ? { ...layer.layout, 'text-font': mapBasemapFonts('en') } : (layer as any).layout);
      for (const key of ['filter', 'minzoom', 'maxzoom']) expect(actual[key]).toEqual((layer as any)[key]);
    }
    expect(style.sources.basemap).toMatchObject({ url: 'pmtiles://https://maps.example.test/planet.pmtiles' });
    expect(style.layers.find(layer => layer.id === 'water')?.paint).toMatchObject({ 'fill-color': '#1b1b1d' });
  });

  it('localizes Protomaps labels without overwriting its visual hierarchy', () => {
    const updates: Array<[string, string, unknown]> = [];
    const map = {
      getZoom: () => 1.25,
      getStyle: () => ({
        sources: { basemap: { type: 'vector' } },
        layers: [{ id: 'places_country', type: 'symbol', source: 'basemap', 'source-layer': 'places' }],
      }),
      getLayoutProperty: () => ['get', 'name'],
      setLayoutProperty: (id: string, name: string, value: unknown) => updates.push([id, name, value]),
      setPaintProperty: (id: string, name: string, value: unknown) => updates.push([id, name, value]),
    };
    reinforceWorldEventBasemapLabels(map);
    expect(updates).toEqual([
      ['places_country', 'text-field', ['coalesce', ['get', 'name:en'], ['get', 'name']]],
      ['places_country', 'text-font', mapBasemapFonts('en')],
    ]);
  });

  it('localization never overwrites provider zoom disclosure, size or paint', () => {
    const { map, updates } = createLabelMap(1.25);
    reinforceWorldEventBasemapLabels(map);
    expect(updates.length).toBeGreaterThan(0);
    expect(updates.every(([, property]) => property === 'text-field' || property === 'text-font')).toBe(true);
  });
});
