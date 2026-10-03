import { describe, expect, it, vi } from 'vitest';
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

  it('leaves fallback labels to the anchored renderer instead of labelling every polygon tile', () => {
    for (const theme of ['dark', 'positron'] as const) {
      const style = getWeatherMapFallbackStyle(theme);
      expect(style).not.toHaveProperty('glyphs');
      expect(style.layers.map(layer => layer.type)).toEqual(['background', 'fill', 'line']);
      expect(style.sources['wm-weather-country-boundaries'].data).toBe('/map-data/world-countries.geojson');
    }
  });

  it('uses the zero-config OpenFreeMap style outside the production PMTiles build', async () => {
    expect(await getWeatherMapStyle('dark')).toBe(OPENFREEMAP_DARK_STYLE);
  });

  it('keeps automatic light and dark themes on the configured same-origin archive', async () => {
    vi.stubEnv('VITE_PMTILES_URL', '/map-tiles/planet.pmtiles');
    vi.resetModules();
    try {
      const { getWeatherMapStyle: configuredStyle } = await import('./weatherBasemap');
      for (const theme of ['dark', 'positron'] as const) {
        const style = await configuredStyle(theme, 'auto', 'zh');
        expect(typeof style).toBe('object');
        expect((style as any).sources.basemap.url).toContain('/map-tiles/planet.pmtiles');
        expect((style as any).layers.some((layer: any) => layer['source-layer'] === 'places')).toBe(true);
      }
      expect(await configuredStyle('dark', 'openfreemap')).toBe(OPENFREEMAP_DARK_STYLE);
    } finally {
      vi.unstubAllEnvs();
      vi.resetModules();
    }
  });

  it('preserves every provider layer, rank and layout and provider paint while applying bundled fonts', async () => {
    const { layers, namedFlavor } = await import('@protomaps/basemaps');
    const original = layers('basemap', namedFlavor('black'), { lang: 'en' });
    const style = await buildWorldEventPMTilesStyle('https://maps.example.test/planet.pmtiles');
    expect(style.layers.map(layer => layer.id)).toEqual(original.map(layer => layer.id));
    for (const [index, layer] of original.entries()) {
      const actual = style.layers[index] as any;
      expect(actual.paint).toEqual(layer.paint);
      expect(actual.layout).toEqual(layer.type === 'symbol' ? { ...layer.layout, 'text-font': mapBasemapFonts('en', layer.layout?.['text-font']) } : (layer as any).layout);
      for (const key of ['filter', 'minzoom', 'maxzoom']) expect(actual[key]).toEqual((layer as any)[key]);
    }
    expect(style.sources.basemap).toMatchObject({ url: 'pmtiles://https://maps.example.test/planet.pmtiles' });
    expect(style.layers.find(layer => layer.id === 'water')?.paint).toEqual(original.find(layer => layer.id === 'water')?.paint);
  });

  it('localizes Protomaps labels without overwriting its visual hierarchy', () => {
    const updates: Array<[string, string, unknown]> = [];
    const map = {
      getZoom: () => 1.25,
      getStyle: () => ({
        sources: { basemap: { type: 'vector' } },
        layers: [{ id: 'places_country', type: 'symbol', source: 'basemap', 'source-layer': 'places' }],
      }),
      getLayoutProperty: (_id: string, name: string) => name === 'text-font' ? ['Noto Sans Regular'] : ['get', 'name'],
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

it('retains the provider boundary paint instead of dimming ordinary countries below context evidence', async () => {
  const { layers, namedFlavor } = await import('@protomaps/basemaps');
  const original = layers('basemap', namedFlavor('black'), { lang: 'en' });
  const actual = await buildWorldEventPMTilesStyle('https://example.test/planet.pmtiles');
  const borders = original.filter(layer => layer.id.startsWith('boundaries'));
  expect(borders.length).toBeGreaterThan(0);
  for (const border of borders) {
    expect(actual.layers.find(layer => layer.id === border.id)?.paint).toEqual(border.paint);
  }
});

it('ships complete native-resolution sprite atlases on the application origin', async () => {
  const {readFileSync}=await import('node:fs');
  for(const theme of ['dark','light']) {
    const style=await buildWorldEventPMTilesStyle('/map-tiles/planet.pmtiles','en',theme==='light'?'positron':'dark');
    expect(style.sprite).toBe(`/map-assets/protomaps-sprites-v4/${theme}`);
    for(const scale of ['', '@2x']) {
      const root=`../../public/map-assets/protomaps-sprites-v4/${theme}${scale}`;
      const atlas=JSON.parse(readFileSync(new URL(root+'.json',import.meta.url),'utf8'));
      const png=readFileSync(new URL(root+'.png',import.meta.url));
      expect(png.subarray(0,8).toString('hex')).toBe('89504e470d0a1a0a');
      const width=png.readUInt32BE(16),height=png.readUInt32BE(20);
      expect(Object.keys(atlas).length).toBeGreaterThan(0);
      for(const icon of Object.values(atlas) as Array<{x:number;y:number;width:number;height:number;pixelRatio:number}>) {
        expect(icon.pixelRatio).toBe(scale?2:1);
        expect(icon.x+icon.width).toBeLessThanOrEqual(width);
        expect(icon.y+icon.height).toBeLessThanOrEqual(height);
      }
    }
  }
});
