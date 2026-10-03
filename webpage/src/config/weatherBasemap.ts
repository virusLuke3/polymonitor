import { addProtocol, type ExpressionSpecification, type StyleSpecification, type SymbolLayerSpecification } from 'maplibre-gl';
import { Protocol, PMTiles } from 'pmtiles';
import { layers, namedFlavor } from '@protomaps/basemaps';
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
let pmtilesProtocol: import('pmtiles').Protocol | null = null;

/** Register the exact PMTiles protocol used by WorldMonitor, once per page. */
async function registerWorldEventPMTilesProtocol() {
  if (pmtilesRegistered) return;
  pmtilesRegistration ??= (async () => {
    if (pmtilesRegistered) return;
    const protocol = new Protocol();
    if (WORLD_EVENT_PMTILES_URL) {
      const archive = new PMTiles(resolveWorldEventPMTilesUrl(WORLD_EVENT_PMTILES_URL));
      protocol.add(archive);
      // Header/root directory download overlaps style preparation and WebGL
      // construction; MapLibre reuses this same archive/cache, not a raw fetch.
      if (typeof window !== 'undefined') void archive.getHeader().catch(() => undefined);
    }
    pmtilesProtocol = protocol;
    addProtocol('pmtiles', protocol.tile);
    pmtilesRegistered = true;
  })().catch((error) => {
    pmtilesRegistration = null;
    throw error;
  });
  await pmtilesRegistration;
}

/** Only a bounded recovery probe resets the archive's rejected header promise. */
export async function resetWorldEventPMTilesArchive() {
  if (!WORLD_EVENT_PMTILES_URL) return;
  await registerWorldEventPMTilesProtocol();
  pmtilesProtocol?.add(new PMTiles(resolveWorldEventPMTilesUrl(WORLD_EVENT_PMTILES_URL)));
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

/** Local proportional fonts, preserving provider Regular/Medium/Bold/Italic roles. */
export function mapBasemapFonts(_language: 'en' | 'zh', original?: unknown): NonNullable<SymbolLayerSpecification['layout']>['text-font'] {
  if (Array.isArray(original) && !original.some(value => typeof value === 'string' && /Noto Sans|Polymonitor Map Sans/.test(value))) {
    return original.map(value => Array.isArray(value) ? mapBasemapFonts(_language, value) : value) as NonNullable<SymbolLayerSpecification['layout']>['text-font'];
  }
  const fonts = JSON.stringify(original || '');
  const role = /Bold/i.test(fonts) ? 'Bold' : /Medium/i.test(fonts) ? 'Medium' : /Italic/i.test(fonts) ? 'Italic' : 'Regular';
  return [`Polymonitor Map Sans ${role}`, 'Noto Sans SC Variable', 'sans-serif'];
}

export async function buildWorldEventPMTilesStyle(url: string, language: 'en' | 'zh' = 'en', theme: WeatherMapTheme = 'dark'): Promise<StyleSpecification> {
  const archiveUrl = resolveWorldEventPMTilesUrl(url);
  const rankedLayers = layers('basemap', namedFlavor(theme === 'positron' ? 'light' : 'black'), { lang: language }) as StyleSpecification['layers'];
  // Use the WorldMonitor provider palette, boundaries and collision rules.
  // Only the bundled proportional font and language are product-specific.
  const tunedLayers = rankedLayers.map((originalLayer) => {
    const layer = originalLayer.type === 'symbol'
      ? { ...originalLayer, layout: { ...originalLayer.layout, 'text-font': mapBasemapFonts(language, originalLayer.layout?.['text-font']) } }
      : originalLayer;

    return layer;
  }) as StyleSpecification['layers'];
  return {
    version: 8,
    // MapLibre 6 requires absolute sprite URLs even for same-origin assets.
    sprite: resolveWorldEventPMTilesUrl(`/map-assets/protomaps-sprites-v4/${theme === 'positron' ? 'light' : 'dark'}`),
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
    ? (WORLD_EVENT_PMTILES_URL ? 'pmtiles' : 'openfreemap')
    : provider;
  if (resolvedProvider === 'pmtiles' && WORLD_EVENT_PMTILES_URL) {
    const [, style] = await Promise.all([
      registerWorldEventPMTilesProtocol(),
      buildWorldEventPMTilesStyle(WORLD_EVENT_PMTILES_URL, language, theme),
    ]);
    return style;
  }
  if (resolvedProvider === 'carto') return theme === 'positron' ? CARTO_LIGHT_STYLE : CARTO_DARK_STYLE;
  return theme === 'positron' ? OPENFREEMAP_LIGHT_STYLE : OPENFREEMAP_DARK_STYLE;
}


type LabelCapableMap = {
  getZoom: () => number;
  getStyle: () => {
    glyphs?: string | null;
    sources?: Record<string, unknown>;
    layers?: Array<{ id: string; type?: string; source?: string; 'source-layer'?: string }>;
  };
  setGlyphs?: (url: string | null) => unknown;
  getLayoutProperty: (layerId: string, name: 'text-field' | 'text-font') => unknown;
  setLayoutProperty: <K extends 'text-field' | 'text-size' | 'visibility' | 'text-font'>(
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
  // MapLibre 6 renders local SDF glyphs when glyphs is unset. This reuses
  // the actual bundled page fonts, including CJK, without another font CDN.
  if (map.getStyle().glyphs) map.setGlyphs?.(null);
  for (const layer of map.getStyle().layers || []) {
    if (layer.type !== 'symbol') continue;
    try {
      if (hasNameField(map.getLayoutProperty(layer.id, 'text-field'))) {
        map.setLayoutProperty(layer.id, 'text-field', localizedNameExpression(language, protomaps));
        map.setLayoutProperty(layer.id, 'text-font', mapBasemapFonts(language, map.getLayoutProperty(layer.id, 'text-font')));
      }
    } catch {
      // A style may replace the symbol layer during load.
    }
  }
}

export function getWeatherMapFallbackStyle(theme: WeatherMapTheme = 'dark') {
  const light = theme === 'positron';
  const background = light ? '#dce5e8' : '#333333';
  const land = light ? '#f4f1e9' : '#141414';
  const border = light ? '#7d8a90' : '#35383b';

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
      // Country labels are drawn once at their verified geometry anchors by
      // DeckMapRenderer. Polygon symbol placement repeats names on each
      // clipped GeoJSON tile at city zooms, so it must not label this source.
    ],
  } satisfies StyleSpecification;
}
