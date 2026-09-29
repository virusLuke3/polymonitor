import { addProtocol, type ExpressionSpecification, type StyleSpecification, type SymbolLayerSpecification } from 'maplibre-gl';
import {
  OPENFREEMAP_DARK_STYLE,
  OPENFREEMAP_LIGHT_STYLE,
  CARTO_DARK_STYLE,
  CARTO_LIGHT_STYLE,
  WORLD_EVENT_PMTILES_URL,
  type WeatherMapTheme,
} from './weatherBasemapMeta';

export {
  CARTO_DARK_STYLE,
  CARTO_LIGHT_STYLE,
  OPENFREEMAP_DARK_STYLE,
  OPENFREEMAP_LIGHT_STYLE,
  WORLD_EVENT_PMTILES_URL,
  getWeatherBasemapAttribution,
  type WeatherMapTheme,
} from './weatherBasemapMeta';

let pmtilesRegistered = false;
let pmtilesRegistration: Promise<void> | null = null;

/** Register the exact PMTiles protocol used by WorldMonitor, once per page. */
async function registerWorldEventPMTilesProtocol() {
  if (pmtilesRegistered) return;
  pmtilesRegistration ??= (async () => {
    const { Protocol } = await import('pmtiles');
    if (pmtilesRegistered) return;
    const protocol = new Protocol();
    addProtocol('pmtiles', protocol.tile);
    pmtilesRegistered = true;
  })().catch((error) => {
    pmtilesRegistration = null;
    throw error;
  });
  await pmtilesRegistration;
}

/**
 * Build WorldMonitor's black Protomaps style from ranked vector-tile features.
 * Country/city disclosure, collision, font weight, boundaries and halos all
 * remain owned by the provider style instead of being re-created after load.
 */
export function resolveWorldEventPMTilesUrl(
  url: string,
  origin = typeof window !== 'undefined' ? window.location.origin : '',
) {
  if (/^https?:\/\//i.test(url) || !origin) return url;
  return new URL(url, origin).href;
}

export async function buildWorldEventPMTilesStyle(url: string, language: 'en' | 'zh' = 'en', theme: WeatherMapTheme = 'dark'): Promise<StyleSpecification> {
  const { layers, namedFlavor } = await import('@protomaps/basemaps');
  const archiveUrl = resolveWorldEventPMTilesUrl(url);
  const rankedLayers = layers('basemap', namedFlavor(theme === 'positron' ? 'light' : 'black'), { lang: language }) as StyleSpecification['layers'];
  // Preserve provider order, rank, collision and zoom rules. Alignment changes
  // paint only; localization below never introduces another label hierarchy.
  const tunedLayers = rankedLayers.map((layer) => {
    if (theme === 'positron') return layer;
    if (layer.id === 'background') return { ...layer, paint: { ...layer.paint, 'background-color': '#1b1b1d' } };
    if (layer.id === 'earth') return { ...layer, paint: { ...layer.paint, 'fill-color': '#0c0c0c' } };
    if (layer.id === 'water') return { ...layer, paint: { ...layer.paint, 'fill-color': '#1b1b1d' } };
    if (layer.type === 'line' && layer.id.startsWith('boundaries')) {
      return { ...layer, paint: { ...layer.paint, 'line-color': layer.id === 'boundaries_country' ? '#35383b' : '#292d30' } };
    }
    if (layer.type === 'symbol' && layer['source-layer'] === 'places') {
      return { ...layer, paint: { ...layer.paint,
        'text-color': layer.id === 'places_country' ? '#a3a8ad' : '#858d95',
        'text-halo-color': '#0c0c0c', 'text-halo-width': 0.6, 'text-halo-blur': 0.1,
      } };
    }
    return layer;
  }) as StyleSpecification['layers'];
  return {
    version: 8,
    glyphs: 'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf',
    sprite: `https://protomaps.github.io/basemaps-assets/sprites/v4/${theme === 'positron' ? 'light' : 'dark'}`,
    sources: {
      basemap: {
        type: 'vector',
        url: `pmtiles://${archiveUrl}`,
        attribution: '<a href="https://protomaps.com">Protomaps</a> | <a href="https://openstreetmap.org/copyright">OpenStreetMap</a>',
      },
    },
    layers: tunedLayers,
  };
}

export type WeatherBasemapProvider = 'auto' | 'pmtiles' | 'openfreemap' | 'carto';

export async function getWeatherMapStyle(
  theme: WeatherMapTheme = 'dark',
  provider: WeatherBasemapProvider = 'auto',
  language: 'en' | 'zh' = 'en',
): Promise<StyleSpecification | string> {
  const resolvedProvider = provider === 'auto'
    ? (theme !== 'positron' && WORLD_EVENT_PMTILES_URL ? 'pmtiles' : 'openfreemap')
    : provider;
  if (resolvedProvider === 'pmtiles' && WORLD_EVENT_PMTILES_URL) {
    await registerWorldEventPMTilesProtocol();
    return buildWorldEventPMTilesStyle(WORLD_EVENT_PMTILES_URL, language, theme);
  }
  if (resolvedProvider === 'carto') return theme === 'positron' ? CARTO_LIGHT_STYLE : CARTO_DARK_STYLE;
  return theme === 'positron' ? OPENFREEMAP_LIGHT_STYLE : OPENFREEMAP_DARK_STYLE;
}


type LabelCapableMap = {
  getZoom: () => number;
  getStyle: () => {
    sources?: Record<string, unknown>;
    layers?: Array<{ id: string; type?: string; source?: string; 'source-layer'?: string }>;
  };
  getLayoutProperty: (layerId: string, name: 'text-field') => unknown;
  setLayoutProperty: <K extends 'text-field' | 'text-size' | 'visibility'>(
    layerId: string,
    name: K,
    value: NonNullable<SymbolLayerSpecification['layout']>[K],
  ) => void;
  setPaintProperty: <K extends 'text-color' | 'text-halo-color' | 'text-halo-width' | 'text-halo-blur' | 'text-opacity'>(
    layerId: string,
    name: K,
    value: NonNullable<SymbolLayerSpecification['paint']>[K],
  ) => void;
};

function usesProtomapsStyle(map: LabelCapableMap) {
  const style = map.getStyle();
  return Boolean(style.sources?.basemap)
    || (style.layers || []).some((layer) => layer.source === 'basemap' && layer['source-layer'] === 'places');
}

function hasNameField(field: unknown) {
  return JSON.stringify(field || '').toLowerCase().includes('name');
}

const ENGLISH_NAME_EXPRESSION: ExpressionSpecification = [
  'coalesce',
  ['get', 'name_en'],
  ['get', 'name:en'],
  ['get', 'name:latin'],
  ['get', 'name'],
];

const PROTOMAPS_ENGLISH_NAME_EXPRESSION: ExpressionSpecification = [
  'coalesce',
  ['get', 'name:en'],
  ['get', 'name'],
];

// Match the source fields used by WorldMonitor: Protomaps has zh-Hans,
// CARTO has zh, and OpenFreeMap may expose both. Never translate coordinates.
function localizedNameExpression(language: 'en' | 'zh', protomaps: boolean): ExpressionSpecification {
  const english = protomaps ? PROTOMAPS_ENGLISH_NAME_EXPRESSION : ENGLISH_NAME_EXPRESSION;
  return language === 'en' ? english : [
    'coalesce', ['get', 'name:zh-Hans'], ['get', 'name:zh'], ['get', 'name_zh'], english,
  ];
}

/** Language changes leave provider rank, size, collision and styling intact. */
export function reinforceWorldEventBasemapLabels(map: LabelCapableMap, language: 'en' | 'zh' = 'en') {
  const protomaps = usesProtomapsStyle(map);
  for (const layer of map.getStyle().layers || []) {
    if (layer.type !== 'symbol') continue;
    try {
      if (hasNameField(map.getLayoutProperty(layer.id, 'text-field'))) {
        map.setLayoutProperty(layer.id, 'text-field', localizedNameExpression(language, protomaps));
      }
    } catch {
      // A style may replace the symbol layer during load.
    }
  }
}

export function getWeatherMapFallbackStyle(theme: WeatherMapTheme = 'dark') {
  const light = theme === 'positron';
  const background = light ? '#dce5e8' : '#1b1b1d';
  const land = light ? '#f4f1e9' : '#0c0c0c';
  const border = light ? '#7d8a90' : '#35383b';

  return {
    version: 8,
    glyphs: 'https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf',
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
        paint: { 'fill-color': land, 'fill-opacity': 1 },
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
      {
        id: 'wm-local-country-labels',
        type: 'symbol',
        source: 'wm-weather-country-boundaries',
        layout: {
          'text-field': ['coalesce', ['get', 'name:en'], ['get', 'name']],
          'text-font': ['Noto Sans Medium'],
          'text-size': ['interpolate', ['linear'], ['zoom'], 0, 13, 3, 15, 5, 17],
          'text-padding': 8,
          'text-max-width': 8,
          'text-letter-spacing': 0.035,
          'text-allow-overlap': false,
          'text-ignore-placement': false,
        },
        paint: {
          'text-color': light ? '#4a5459' : '#aeb7ba',
          'text-halo-color': light ? '#eef3f4' : '#1b1b1d',
          'text-halo-width': 1.25,
          'text-halo-blur': 0.15,
          'text-opacity': 0.94,
        },
      },
    ],
  } satisfies StyleSpecification;
}
