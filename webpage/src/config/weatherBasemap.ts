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
  getStyle: () => { layers?: Array<{ id: string; type?: string; 'source-layer'?: string }> };
  getLayoutProperty: (layerId: string, name: 'text-field') => unknown;
  setLayoutProperty: (layerId: string, name: 'text-field', value: unknown) => void;
  setPaintProperty: (
    layerId: string,
    name: 'text-color' | 'text-halo-color' | 'text-halo-width' | 'text-opacity',
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

type LabelKind = 'country-major' | 'country-minor' | 'city-major' | 'city' | 'locality' | 'context';

function labelKind(layer: { id: string; 'source-layer'?: string }): LabelKind {
  const identity = `${layer.id} ${layer['source-layer'] || ''}`.toLowerCase();
  if (identity.includes('place_country_major')) return 'country-major';
  if (identity.includes('place_country')) return 'country-minor';
  if (identity.includes('place_city_large')) return 'city-major';
  if (identity.includes('place_city') || identity.includes('place_state')) return 'city';
  if (/place_(town|village|suburb|other)/.test(identity)) return 'locality';
  return 'context';
}

function labelOpacity(kind: LabelKind): unknown {
  // OpenFreeMap supplies the glyphs, rank and collision handling.  These
  // thresholds only remove low-value detail from the global intelligence view.
  if (kind === 'country-major') return ['interpolate', ['linear'], ['zoom'], 0, 0.72, 1.5, 0.9];
  if (kind === 'country-minor') return ['interpolate', ['linear'], ['zoom'], 0, 0.18, 1.3, 0.66, 2.1, 0.88];
  if (kind === 'city-major') return ['interpolate', ['linear'], ['zoom'], 0, 0, 1.35, 0.72, 2.15, 0.9];
  if (kind === 'city') return ['interpolate', ['linear'], ['zoom'], 0, 0, 2.1, 0, 2.8, 0.78];
  if (kind === 'locality') return ['interpolate', ['linear'], ['zoom'], 0, 0, 3.4, 0, 4.25, 0.72];
  return ['interpolate', ['linear'], ['zoom'], 0, 0, 3.1, 0, 4, 0.56];
}

function labelColor(kind: LabelKind) {
  if (kind === 'country-major') return '#c4d0d5';
  if (kind === 'country-minor') return '#aab8bd';
  if (kind === 'city-major') return '#d2dade';
  return '#aab5ba';
}

/**
 * WorldMonitor localizes each provider-owned place layer after a style load.
 * OpenFreeMap exposes `name_en` (not just OSM's `name:en`), and its default
 * expression deliberately emits a second non-Latin line.  Retaining that
 * expression made the global map crowded and inconsistent.  Keep the provider
 * font, rank and collision behavior, but use its English field and suppress
 * low-value locality labels at global zoom.
 */
export function reinforceWorldEventBasemapLabels(map: LabelCapableMap) {
  for (const layer of map.getStyle().layers || []) {
    if (layer.type !== 'symbol') continue;
    try {
      if (!hasNameField(map.getLayoutProperty(layer.id, 'text-field'))) continue;
      const kind = labelKind(layer);
      map.setLayoutProperty(layer.id, 'text-field', ENGLISH_NAME_EXPRESSION);
      map.setPaintProperty(layer.id, 'text-color', labelColor(kind));
      map.setPaintProperty(layer.id, 'text-halo-color', '#070a0c');
      map.setPaintProperty(layer.id, 'text-halo-width', kind.startsWith('country') ? 1.35 : 1.15);
      map.setPaintProperty(layer.id, 'text-opacity', labelOpacity(kind));
    } catch {
      // Styles can swap while MapLibre is tearing down a layer. The provider
      // defaults remain usable if a single label layer cannot be adjusted.
    }
  }
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
