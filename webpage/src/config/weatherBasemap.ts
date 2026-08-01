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
  getStyle: () => { layers?: Array<{ id: string; type?: string }> };
  getLayoutProperty: (layerId: string, name: 'text-field') => unknown;
  setPaintProperty: (layerId: string, name: 'text-halo-color' | 'text-halo-width', value: unknown) => void;
};

function hasNameField(field: unknown) {
  return JSON.stringify(field || '').toLowerCase().includes('name');
}

/**
 * Keep vector labels readable over the dark event layers without replacing the
 * provider's font, rank, language, or zoom rules. This follows WorldMonitor's
 * style-load label treatment while leaving the vector basemap authoritative.
 */
export function reinforceWorldEventBasemapLabels(map: LabelCapableMap) {
  for (const layer of map.getStyle().layers || []) {
    if (layer.type !== 'symbol') continue;
    try {
      if (!hasNameField(map.getLayoutProperty(layer.id, 'text-field'))) continue;
      map.setPaintProperty(layer.id, 'text-halo-color', '#070a0c');
      map.setPaintProperty(layer.id, 'text-halo-width', 1.15);
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
