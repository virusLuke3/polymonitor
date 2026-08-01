import type { StyleSpecification } from 'maplibre-gl';

export type WeatherMapTheme = 'dark' | 'dark-matter' | 'positron';

export const OPENFREEMAP_DARK_STYLE = 'https://tiles.openfreemap.org/styles/dark';
export const OPENFREEMAP_LIGHT_STYLE = 'https://tiles.openfreemap.org/styles/positron';
export const CARTO_DARK_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

export function getWeatherMapStyle(theme: WeatherMapTheme = 'dark') {
  // OpenFreeMap's vector style includes ranked country and city label layers.
  // The local GeoJSON fallback deliberately does not pretend to be a full vector
  // basemap, so the primary path must remain a label-capable style.
  if (theme === 'dark') return OPENFREEMAP_DARK_STYLE;
  if (theme === 'dark-matter') return OPENFREEMAP_DARK_STYLE;
  if (theme === 'positron') return OPENFREEMAP_LIGHT_STYLE;
  return OPENFREEMAP_DARK_STYLE;
}

type LabelCapableMap = {
  getZoom: () => number;
  getStyle: () => { layers?: Array<{ id: string; type?: string; 'source-layer'?: string }> };
  getLayoutProperty: (layerId: string, name: 'text-field') => unknown;
  setLayoutProperty: (
    layerId: string,
    name: 'text-field' | 'text-size' | 'visibility',
    value: unknown,
  ) => void;
  setPaintProperty: (
    layerId: string,
    name: 'text-color' | 'text-halo-color' | 'text-halo-width' | 'text-halo-blur' | 'text-opacity',
    value: unknown,
  ) => void;
};

function hasNameField(field: unknown) {
  return JSON.stringify(field || '').toLowerCase().includes('name');
}

const ENGLISH_NAME_EXPRESSION = [
  'coalesce',
  ['get', 'name_en'],
  ['get', 'name:en'],
  ['get', 'name:latin'],
  ['get', 'name'],
];

type LabelKind =
  | 'continent'
  | 'country-major'
  | 'country-minor'
  | 'country-other'
  | 'city-major'
  | 'city'
  | 'state'
  | 'locality'
  | 'context';

type LabelDensity = 'global' | 'regional' | 'area' | 'detail';

const labelDensityByMap = new WeakMap<LabelCapableMap, LabelDensity>();

function labelKind(layer: { id: string; 'source-layer'?: string }): LabelKind {
  const identity = `${layer.id} ${layer['source-layer'] || ''}`.toLowerCase();
  if (identity.includes('place_continent')) return 'continent';
  if (identity.includes('place_country_other')) return 'country-other';
  if (identity.includes('place_country_major')) return 'country-major';
  if (identity.includes('place_country')) return 'country-minor';
  if (identity.includes('place_city_large')) return 'city-major';
  if (identity.includes('place_city')) return 'city';
  if (identity.includes('place_state')) return 'state';
  if (/place_(town|village|suburb|other)/.test(identity)) return 'locality';
  return 'context';
}

function labelDensity(zoom: number): LabelDensity {
  if (zoom < 1.85) return 'global';
  if (zoom < 3.1) return 'regional';
  if (zoom < 4.5) return 'area';
  return 'detail';
}

function labelVisible(kind: LabelKind, density: LabelDensity) {
  if (kind === 'continent' || kind === 'country-major' || kind === 'city-major') return true;
  if (density === 'global') return false;
  if (kind === 'country-minor') return true;
  if (density === 'regional') return false;
  if (kind === 'country-other' || kind === 'city' || kind === 'state') return true;
  if (density === 'area') return false;
  return true;
}

function labelOpacity(kind: LabelKind) {
  if (kind === 'continent') return 0.82;
  if (kind === 'country-major' || kind === 'city-major') return 0.96;
  if (kind === 'country-minor') return 0.9;
  if (kind === 'country-other') return 0.86;
  if (kind === 'city') return 0.9;
  if (kind === 'state') return 0.84;
  if (kind === 'locality') return 0.78;
  return 0.7;
}

function labelColor(kind: LabelKind) {
  if (kind === 'country-major' || kind === 'city-major') return '#d4dfe3';
  if (kind === 'country-minor') return '#bcc9ce';
  if (kind === 'continent') return '#aebfc6';
  return '#aab9bf';
}

function labelSize(kind: LabelKind): unknown | null {
  if (kind === 'country-major') return ['interpolate', ['linear'], ['zoom'], 0, 12, 3, 14, 5, 16];
  if (kind === 'country-minor') return ['interpolate', ['linear'], ['zoom'], 1.85, 11, 4, 13, 6, 14];
  if (kind === 'city-major') return ['interpolate', ['linear'], ['zoom'], 0, 12, 3, 14, 6, 16];
  if (kind === 'city') return ['interpolate', ['linear'], ['zoom'], 3.1, 11, 5, 13, 7, 15];
  return null;
}

function labelHaloWidth(kind: LabelKind) {
  return kind === 'continent' || kind === 'context' ? 0.8 : 1;
}

/**
 * WorldMonitor's PMTiles style treats country and city rank as a real visual
 * hierarchy: low zoom exposes only global context, then progressively adds
 * country and locality detail. OpenFreeMap ships all country symbol layers from
 * zoom 0, so opacity alone leaves every minor country in the global view. Keep
 * the provider's glyphs and collision engine, but add an explicit equivalent
 * disclosure policy for its known place-layer taxonomy.
 */
export function reinforceWorldEventBasemapLabels(map: LabelCapableMap) {
  labelDensityByMap.delete(map);
  for (const layer of map.getStyle().layers || []) {
    if (layer.type !== 'symbol') continue;
    try {
      if (!hasNameField(map.getLayoutProperty(layer.id, 'text-field'))) continue;
      const kind = labelKind(layer);
      map.setLayoutProperty(layer.id, 'text-field', ENGLISH_NAME_EXPRESSION);
      const size = labelSize(kind);
      if (size) map.setLayoutProperty(layer.id, 'text-size', size);
      map.setPaintProperty(layer.id, 'text-color', labelColor(kind));
      map.setPaintProperty(layer.id, 'text-halo-color', '#05080a');
      map.setPaintProperty(layer.id, 'text-halo-width', labelHaloWidth(kind));
      map.setPaintProperty(layer.id, 'text-halo-blur', 0);
      map.setPaintProperty(layer.id, 'text-opacity', labelOpacity(kind));
    } catch {
      // Styles can swap while MapLibre is tearing down a layer. The provider
      // defaults remain usable if a single label layer cannot be adjusted.
    }
  }
  refreshWorldEventBasemapLabelDensity(map);
}

/** Re-evaluate label disclosure after a completed camera move without touching glyphs. */
export function refreshWorldEventBasemapLabelDensity(map: LabelCapableMap) {
  const density = labelDensity(map.getZoom());
  if (labelDensityByMap.get(map) === density) return;

  for (const layer of map.getStyle().layers || []) {
    if (layer.type !== 'symbol') continue;
    try {
      if (!hasNameField(map.getLayoutProperty(layer.id, 'text-field'))) continue;
      map.setLayoutProperty(layer.id, 'visibility', labelVisible(labelKind(layer), density) ? 'visible' : 'none');
    } catch {
      // A style can be replaced between getStyle() and setLayoutProperty().
    }
  }
  labelDensityByMap.set(map, density);
}

export function getWeatherMapFallbackStyle(theme: WeatherMapTheme = 'dark') {
  const light = theme === 'positron';
  const background = light ? '#dce5e8' : '#070a0c';
  const land = light ? '#f4f1e9' : '#1c252a';
  const border = light ? '#7d8a90' : '#69767d';

  return {
    version: 8,
    sources: {
      'wm-weather-country-boundaries': {
        type: 'geojson',
        data: '/map-data/world-countries.geojson',
      },
    },
    layers: [
      {
        id: 'wm-local-background',
        type: 'background',
        paint: { 'background-color': background },
      },
      {
        id: 'wm-local-land',
        type: 'fill',
        source: 'wm-weather-country-boundaries',
        paint: {
          'fill-color': land,
          'fill-opacity': 1,
        },
      },
      {
        id: 'wm-local-country-border',
        type: 'line',
        source: 'wm-weather-country-boundaries',
        paint: {
          'line-color': border,
          'line-opacity': light ? 0.72 : 0.82,
          'line-width': ['interpolate', ['linear'], ['zoom'], 0, 0.45, 4, 0.9, 7, 1.4],
        },
      },
    ],
  } satisfies StyleSpecification;
}
