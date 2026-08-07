import { describe, expect, it } from 'vitest';
import {
  OPENFREEMAP_DARK_STYLE,
  buildWorldEventPMTilesStyle,
  getWeatherMapStyle,
  refreshWorldEventBasemapLabelDensity,
  reinforceWorldEventBasemapLabels,
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
  it('uses the zero-config OpenFreeMap style outside the production PMTiles build', async () => {
    expect(await getWeatherMapStyle('dark')).toBe(OPENFREEMAP_DARK_STYLE);
  });

  it('builds the same ranked Protomaps black style used by WorldMonitor', async () => {
    const style = await buildWorldEventPMTilesStyle('https://maps.example.test/planet.pmtiles');
    expect(style.sources?.basemap).toMatchObject({
      type: 'vector',
      url: 'pmtiles://https://maps.example.test/planet.pmtiles',
    });
    const countryLabels = style.layers?.find((layer) => layer.id === 'places_country');
    const globalCountryLabels = style.layers?.find((layer) => layer.id === 'places_country_global');
    const localityLabels = style.layers?.find((layer) => layer.id === 'places_locality');
    const regionalLocalityLabels = style.layers?.find((layer) => layer.id === 'places_locality_regional');
    const globalLocalityLabels = style.layers?.find((layer) => layer.id === 'places_locality_global');
    const countryBoundaries = style.layers?.find((layer) => layer.id === 'boundaries_country');
    const detailBoundaries = style.layers?.find((layer) => layer.id === 'boundaries');
    expect(countryLabels).toMatchObject({ type: 'symbol', 'source-layer': 'places', minzoom: 2.6 });
    expect(globalCountryLabels).toMatchObject({
      type: 'symbol',
      'source-layer': 'places',
      maxzoom: 2.6,
      filter: ['all', ['==', 'kind', 'country'], ['>=', 'population_rank', 9]],
    });
    expect(globalLocalityLabels).toMatchObject({
      type: 'symbol',
      'source-layer': 'places',
      maxzoom: 2.6,
      filter: ['all', ['==', 'kind', 'locality'], ['>=', 'population_rank', 11]],
    });
    expect(JSON.stringify(countryLabels?.layout)).toContain('population_rank');
    expect(localityLabels).toMatchObject({ type: 'symbol', 'source-layer': 'places', minzoom: 4.5 });
    expect(regionalLocalityLabels).toMatchObject({
      type: 'symbol',
      'source-layer': 'places',
      minzoom: 2.6,
      maxzoom: 4.5,
      filter: ['all', ['==', 'kind', 'locality'], ['>=', 'population_rank', 11]],
    });
    expect(JSON.stringify(localityLabels?.layout)).toContain('population_rank');
    expect(countryBoundaries).toMatchObject({ type: 'line', 'source-layer': 'boundaries', filter: ['<=', 'kind_detail', 2] });
    expect(detailBoundaries).toMatchObject({ type: 'line', 'source-layer': 'boundaries', minzoom: 5 });
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
    refreshWorldEventBasemapLabelDensity(map);
    expect(updates).toEqual([
      ['places_country', 'text-field', ['coalesce', ['get', 'name:en'], ['get', 'name']]],
    ]);
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
