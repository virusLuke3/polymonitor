import type { GeoEvent, GeoEventSeverity, HazardKind } from '../domain/types';

export const MAP_SYMBOL_SIZE = 48;

/**
 * Polymonitor's own compact signal alphabet.
 *
 * The silhouettes deliberately avoid WorldMonitor's generic square/diamond/
 * triangle/hexagon set. Every consumer (deck.gl, SVG fallback, legend and
 * layer panel) reads these same paths so a hazard never changes identity when
 * the renderer changes.
 */
export const MAP_SYMBOL_DEFINITIONS = {
  signal: {
    label: 'Mapped event',
    paths: ['M24 3 45 24 24 45 3 24Zm0 11a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 6a4 4 0 1 1 0 8 4 4 0 0 1 0-8Z'],
  },
  storm: {
    label: 'Severe storm',
    paths: ['M13 31C7.5 31 4 27.6 4 23.2c0-4.1 3.1-7.5 7.2-7.9C13.2 9.9 18 6 24 6c7.2 0 13.1 5.5 13.8 12.5 3.8.8 6.2 3.6 6.2 7.1 0 4.3-3.5 7.4-8.4 7.4H31l4-7H24l-4 10h6l-4 9 13-14Z'],
  },
  tornado: {
    label: 'Tornado',
    paths: ['M5 7h38l-4.5 7H9.5Zm5.5 11h27L33 25H15Zm7 11h14l-3.8 6H21.3Zm5.2 10h7.1L26 46Z'],
  },
  cyclone: {
    label: 'Tropical cyclone',
    paths: ['M24 4C13 4 4 13 4 24h10c0-5.5 4.5-10 10-10 3.4 0 6.3 1.7 8.1 4.2C30.9 11.7 27.7 7 24 4Zm0 40c11 0 20-9 20-20H34c0 5.5-4.5 10-10 10-3.4 0-6.3-1.7-8.1-4.2C17.1 36.3 20.3 41 24 44Zm0-25a5 5 0 1 0 0 10 5 5 0 0 0 0-10Z'],
  },
  flood: {
    label: 'Flood',
    paths: ['M4 15c5.2-5.3 10.4-5.3 15.6 0s10.4 5.3 15.6 0S44 9.7 44 9.7v7.8c-5.2 5.3-10.4 5.3-15.6 0s-10.4-5.3-15.6 0S4 22.8 4 22.8Zm0 16c5.2-5.3 10.4-5.3 15.6 0s10.4 5.3 15.6 0S44 25.7 44 25.7v7.8c-5.2 5.3-10.4 5.3-15.6 0s-10.4-5.3-15.6 0S4 38.8 4 38.8Z'],
  },
  tsunami: {
    label: 'Tsunami',
    paths: ['M4 39c8.8-2.2 11.4-8.4 14.1-14.8C21 17.4 25 10 37.5 6c-1.2 4.6-4.8 7.2-9.5 9.3 6.5-.3 11.5 2.5 15.8 8.7-6.2-1.3-10.3.2-12.2 4.6-2.2 5.1 1.5 9 8.4 11.4H27.2c-4.3-3-6.3-6.6-5.3-10.5-3.2 5.2-8.1 8.8-17.9 9.5Z'],
  },
  earthquake: {
    label: 'Earthquake',
    paths: ['M5 8h16l-2.8 11.5 6 5-6.2 15.5H5Zm38 0H27l2.8 11.5-6 5L30 40h13Z'],
  },
  volcano: {
    label: 'Volcano',
    paths: ['M4 42 17.5 16l6.5 7 6.5-11L44 42H30l-6-8-5 8Zm17-32 3-7 3 7-3 5Zm10 3 7-5-3 8-6 2ZM10 13 3 8l3 8 6 2Z'],
  },
  wildfire: {
    label: 'Wildfire',
    paths: ['M27 3c2 8-2.2 11.2-5.2 15.2-2.4 3.1-3.7 6.5-1.4 10.2.5-5.4 3.9-7.4 7.5-10.5 6.8 4.7 11.1 10.4 11.1 17.1 0 7.2-6.3 12-15 12S9 42.3 9 33.5c0-7.7 5.7-13.3 10.3-18.1C23 11.6 25.6 8.1 27 3Zm-2 26c-4.7 4.1-6.6 7-5.7 10.1.6 2 2.4 3.3 4.7 3.3 3.1 0 5.4-2.1 5.4-5.1 0-2.7-1.6-5.4-4.4-8.3Z'],
  },
  'fire-detection': {
    label: 'Satellite fire detection',
    paths: ['M4 4h13v5H9v8H4Zm27 0h13v13h-5V9h-8ZM4 31h5v8h8v5H4Zm35 0h5v13H31v-5h8ZM25 12c1.5 5-1.6 7.4-3.7 10.2-1.6 2.1-2.4 4.3-.9 6.8.8-3.6 3.2-5.2 5.7-7.2 4.6 3.2 7.2 7 7.2 11.5 0 5-4.3 8.4-10.1 8.4S13 38.4 13 32.4c0-5.2 3.9-9 7-12.3 2.5-2.6 4.2-5 5-8.1Z'],
  },
  heat: {
    label: 'Extreme heat',
    paths: ['M21 2h6v9h-6Zm0 35h6v9h-6ZM2 21h9v6H2Zm35 0h9v6h-9ZM7.7 11.9l4.2-4.2 6.4 6.4-4.2 4.2Zm22 22 4.2-4.2 6.4 6.4-4.2 4.2Zm0-19.8 6.4-6.4 4.2 4.2-6.4 6.4Zm-22 22 6.4-6.4 4.2 4.2-6.4 6.4ZM24 14a10 10 0 1 0 0 20 10 10 0 0 0 0-20Z'],
  },
  cold: {
    label: 'Extreme cold',
    paths: ['M21 3h6v10.6l6.8-6.8 4.2 4.2-7.5 7.5H45v6H33.8l8.2 8.2-4.2 4.2L27 26.1V45h-6V26.1L10.2 36.9 6 32.7l8.2-8.2H3v-6h14.5L10 11l4.2-4.2 6.8 6.8Z'],
  },
  anomaly: {
    label: 'Weather anomaly',
    paths: ['M3 12h8l5 8 7-16 8 25 5-11h9v7h-5l-10 21-8-24-5 11-10-14H3Zm0 27h12v6H3Z'],
  },
  intel: {
    label: 'Intelligence hotspot',
    paths: ['M24 2 29 18 46 24 29 30 24 46 19 30 2 24 19 18Zm0 17a5 5 0 1 0 0 10 5 5 0 0 0 0-10Z'],
  },
  'conflict-state': {
    label: 'State-based conflict',
    paths: ['M6 7h13l5 8 5-8h13v13l-8 4 8 4v13H29l-5-8-5 8H6V28l8-4-8-4Zm15 12v10h6V19Z'],
  },
  'conflict-nonstate': {
    label: 'Non-state conflict',
    paths: ['M24 3 44 15v18L24 45 4 33V15Zm0 9-11 6.5v11L24 36l11-6.5v-11Z'],
  },
  'conflict-one-sided': {
    label: 'One-sided violence',
    paths: ['M5 7h16l22 17-22 17H5l18-17Zm18 13v8h13Z'],
  },
  'country-risk': {
    label: 'Country risk',
    paths: ['M24 3 42 10v13c0 11.4-7.1 18.5-18 23C13.1 41.5 6 34.4 6 23V10Zm0 10-9 3v7c0 6.7 3.5 11.2 9 14 5.5-2.8 9-7.3 9-14v-7Z'],
  },
  'air-route': {
    label: 'Air corridor',
    paths: ['M5 35a5 5 0 1 0 0 10 5 5 0 0 0 0-10Zm38-32a5 5 0 1 0 0 10 5 5 0 0 0 0-10ZM9 38c8.2-1.9 13.6-5.8 18.2-11.5C31.4 21.3 35 15 41 10l-4-4c-6.6 5.5-10.6 12.4-14.7 17.5C18.1 28.7 13.5 32 7.5 33.5Z'],
  },
  'weather-exposure': {
    label: 'Weather-exposed corridor',
    paths: ['M4 33c6-5 12-5 18 0s12 5 18 0l4 6c-8.7 7-17.3 7-26 0-3.3-2.7-6.7-2.7-10 0ZM12 22c-4 0-7-2.8-7-6.5S8 9 12 9c2-5 6.5-7 11-7 6 0 11 4.5 11.8 10 5 .2 8.2 3.2 8.2 7 0 1-.2 2-.6 3Z'],
  },
  'conflict-exposure': {
    label: 'Conflict-exposed corridor',
    paths: ['M21 3h6v12l8.5-8.5 4 4L31 19h12v6H31l8.5 8.5-4 4L27 29v16h-6V29l-8.5 8.5-4-4L17 25H5v-6h12L8.5 10.5l4-4L21 15Z'],
  },
  aircraft: {
    label: 'Aircraft',
    paths: ['M24 3 28 17 43 25v5l-15-4 1 11 6 5v3l-11-3-11 3v-3l6-5 1-11-15 4v-5l15-8Z'],
  },
} as const;

export type MapSymbolKey = keyof typeof MAP_SYMBOL_DEFINITIONS;

export const MAP_SEVERITY_STYLES: Record<GeoEventSeverity, {
  color: string;
  rgba: [number, number, number, number];
  lineWidth: number;
}> = {
  info: { color: '#55c4e0', rgba: [85, 196, 224, 190], lineWidth: 1 },
  watch: { color: '#eec747', rgba: [238, 199, 71, 215], lineWidth: 1.25 },
  warning: { color: '#ff9135', rgba: [255, 145, 53, 230], lineWidth: 1.65 },
  critical: { color: '#ff4c46', rgba: [255, 76, 70, 245], lineWidth: 2.1 },
};

const HAZARD_SYMBOLS: Record<HazardKind, MapSymbolKey> = {
  'severe-storm': 'storm',
  tornado: 'tornado',
  'tropical-cyclone': 'cyclone',
  flood: 'flood',
  tsunami: 'tsunami',
  earthquake: 'earthquake',
  volcano: 'volcano',
  wildfire: 'wildfire',
  'fire-detection': 'fire-detection',
  'extreme-heat': 'heat',
  'extreme-cold': 'cold',
  'temperature-anomaly': 'anomaly',
  'precipitation-anomaly': 'anomaly',
  'other-weather-anomaly': 'anomaly',
};

export function mapSymbolForEvent(event: GeoEvent): MapSymbolKey {
  if ((event.category === 'weather' || event.category === 'natural-hazard') && 'hazardKind' in event) {
    return HAZARD_SYMBOLS[event.hazardKind as HazardKind] || 'signal';
  }
  if (event.category === 'conflict' || event.category === 'unrest') {
    const violenceType = String(event.properties.violenceType || '');
    if (violenceType === '1') return 'conflict-state';
    if (violenceType === '2') return 'conflict-nonstate';
    if (violenceType === '3') return 'conflict-one-sided';
    return 'conflict-state';
  }
  if (event.category === 'intel') return 'intel';
  if (event.category === 'country-risk' || event.category === 'sanctions') return 'country-risk';
  if (event.category === 'infrastructure') {
    const entity = String(event.properties.mapEntity || '');
    if (entity === 'live-aircraft' || entity === 'air-flight') return 'aircraft';
    return 'air-route';
  }
  return 'signal';
}

const atlasKeys = Object.keys(MAP_SYMBOL_DEFINITIONS) as MapSymbolKey[];

export const MAP_SYMBOL_ICON_MAPPING = Object.fromEntries(atlasKeys.map((key, index) => [key, {
  x: index * MAP_SYMBOL_SIZE,
  y: 0,
  width: MAP_SYMBOL_SIZE,
  height: MAP_SYMBOL_SIZE,
  anchorX: MAP_SYMBOL_SIZE / 2,
  anchorY: MAP_SYMBOL_SIZE / 2,
  mask: true,
}])) as Record<MapSymbolKey, {
  x: number;
  y: number;
  width: number;
  height: number;
  anchorX: number;
  anchorY: number;
  mask: true;
}>;

function svgAtlas() {
  const width = atlasKeys.length * MAP_SYMBOL_SIZE;
  const content = atlasKeys.map((key, index) => (
    MAP_SYMBOL_DEFINITIONS[key].paths.map((path) => (
      `<path transform="translate(${index * MAP_SYMBOL_SIZE} 0)" d="${path}" fill="white" fill-rule="evenodd"/>`
    )).join('')
  )).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${MAP_SYMBOL_SIZE}" viewBox="0 0 ${width} ${MAP_SYMBOL_SIZE}">${content}</svg>`;
}

export const MAP_SYMBOL_ATLAS = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgAtlas())}`;

export function mapSymbolPaths(symbol: MapSymbolKey) {
  return MAP_SYMBOL_DEFINITIONS[symbol].paths;
}

export function isMapSymbolKey(value: string): value is MapSymbolKey {
  return value in MAP_SYMBOL_DEFINITIONS;
}
