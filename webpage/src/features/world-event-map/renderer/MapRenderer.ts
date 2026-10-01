import type { ScreenBox, ClusterSelection } from './layerFactories/eventClusters';
import type { MapPresentationCounts } from './eventDisclosure';
import type { RadarFrame } from '../data/useWeatherRadar';
import type { GeoEvent } from '../domain/types';
import type { WorldEventMapState } from '../state/mapState';

export type BasemapState =
  | 'idle'
  | 'initializing'
  | 'primary-ready'
  | 'local-fallback-ready'
  | 'renderer-fallback-ready'
  | 'failed';

export type MapHoverPosition = { x: number; y: number };
export type MapCountryTarget = {
  iso2: string;
  name: string;
  bounds: [[number, number], [number, number]];
};

export type RendererViewport = {
  revision: number;
  bounds: Array<[number, number, number, number]>;
  center: [number, number]; zoom: number; widthCssPx: number; heightCssPx: number;
};

/** Normalize actual unwrapped renderer bounds. Preserve both date-line halves. */
export function splitViewportBounds(west: number, south: number, east: number, north: number): RendererViewport['bounds'] {
  if (![west, south, east, north].every(Number.isFinite) || north <= south) return [];
  while (east < west) east += 360;
  south = Math.max(-85, south); north = Math.min(85, north);
  if (east - west >= 360) return [[-180, south, 180, north]];
  const width = east - west;
  west = ((west + 180) % 360 + 360) % 360 - 180; east = west + width;
  return east <= 180 ? [[west, south, east, north]] : [[west, south, 180, north], [-180, south, east - 360, north]];
}

export interface MapRendererCallbacks {
  onViewportChange?: (viewport: RendererViewport) => void;
  onLayerRecovered?: (layerId: string) => void;
  onPresentationChange?: (counts: MapPresentationCounts) => void;
  onRadarStateChange?: (status: 'off' | 'loading' | 'ready' | 'error', frame?: RadarFrame | null) => void;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onClusterSelect?: (selection: ClusterSelection) => void;
  onEventSelect: (eventId: string | null) => void;
  onCountrySelect: (country: MapCountryTarget | null, position?: MapHoverPosition) => void;
  onCountryContextMenu: (country: MapCountryTarget, position: MapHoverPosition) => void;
  onBasemapStateChange: (state: BasemapState) => void;
  onBasemapIssueChange?: (message: string | null) => void;
  onRendererFallbackRequested: (error: Error) => void;
  onLayerDegraded?: (layerId: string, error: Error) => void;
  onError: (error: Error) => void;
}

export interface MapRenderer {
  mount(container: HTMLElement, callbacks: MapRendererCallbacks): Promise<void>;
  verifyReady?(): Promise<boolean>;
  setState(state: WorldEventMapState): void;
  setEvents(events: GeoEvent[]): void;
  setRadar?(frame: RadarFrame | null): void;
  resize(): void;
  setOcclusions?(boxes: ScreenBox[]): void;
  setHoveredEvent?(eventId: string | null): void;
  setReducedMotion(reduced: boolean): void;
  setLanguage?(language: 'en' | 'zh'): void;
  fitCountry(country: MapCountryTarget): void;
  pause(): void;
  resume(): void;
  destroy(): void;
}
