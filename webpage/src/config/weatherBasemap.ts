import type { StyleSpecification } from 'maplibre-gl';

export type WeatherMapTheme = 'dark' | 'dark-matter' | 'positron';

export const OPENFREEMAP_DARK_STYLE = 'https://tiles.openfreemap.org/styles/dark';
export const OPENFREEMAP_LIGHT_STYLE = 'https://tiles.openfreemap.org/styles/positron';
export const CARTO_DARK_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';

export function getWeatherMapStyle(theme: WeatherMapTheme = 'dark') {
  if (theme === 'dark') return CARTO_DARK_STYLE;
  if (theme === 'dark-matter') return CARTO_DARK_STYLE;
  if (theme === 'positron') return OPENFREEMAP_LIGHT_STYLE;
  return CARTO_DARK_STYLE;
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
