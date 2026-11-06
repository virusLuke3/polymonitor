import { publicSource } from '@/config/publicSources';
export type WeatherMapTheme = 'dark' | 'dark-matter' | 'positron';

export const OPENFREEMAP_DARK_STYLE = publicSource('VITE_PUBLIC_OPENFREEMAP_DARK_STYLE');
export const OPENFREEMAP_LIGHT_STYLE = publicSource('VITE_PUBLIC_OPENFREEMAP_LIGHT_STYLE');
export const CARTO_DARK_STYLE = publicSource('VITE_PUBLIC_CARTO_DARK_STYLE');
export const CARTO_LIGHT_STYLE = publicSource('VITE_PUBLIC_CARTO_LIGHT_STYLE');
export const WORLD_EVENT_PMTILES_URL = (import.meta.env.VITE_PMTILES_URL || '').trim();

export function getWeatherBasemapAttribution(provider: 'auto' | 'pmtiles' | 'openfreemap' | 'carto' = 'auto') {
  const resolved = provider === 'auto' ? (WORLD_EVENT_PMTILES_URL ? 'pmtiles' : 'openfreemap') : provider;
  if (resolved === 'pmtiles') return '© Protomaps · © OpenStreetMap contributors';
  if (resolved === 'carto') return '© CARTO · © OpenStreetMap contributors';
  return '© OpenFreeMap · © OpenStreetMap contributors';
}
