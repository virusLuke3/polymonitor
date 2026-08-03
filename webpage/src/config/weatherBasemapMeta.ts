export type WeatherMapTheme = 'dark' | 'dark-matter' | 'positron';

export const OPENFREEMAP_DARK_STYLE = 'https://tiles.openfreemap.org/styles/dark';
export const OPENFREEMAP_LIGHT_STYLE = 'https://tiles.openfreemap.org/styles/positron';
export const CARTO_DARK_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json';
export const WORLD_EVENT_PMTILES_URL = (import.meta.env.VITE_PMTILES_URL || '').trim();

export function getWeatherBasemapAttribution() {
  return WORLD_EVENT_PMTILES_URL
    ? '© Protomaps · © OpenStreetMap contributors'
    : '© OpenFreeMap · © OpenStreetMap contributors';
}
