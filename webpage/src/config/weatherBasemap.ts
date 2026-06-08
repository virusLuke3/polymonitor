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
  return theme === 'positron' ? OPENFREEMAP_LIGHT_STYLE : OPENFREEMAP_DARK_STYLE;
}
