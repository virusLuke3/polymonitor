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

export interface MapRendererCallbacks {
  onPresentationChange?: (counts: MapPresentationCounts) => void;
  onRadarStateChange?: (status: 'off' | 'loading' | 'ready' | 'error') => void;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onClusterSelect?: (selection: ClusterSelection) => void;
  onEventSelect: (eventId: string | null) => void;
  onCountrySelect: (country: MapCountryTarget | null, position?: MapHoverPosition) => void;
  onCountryContextMenu: (country: MapCountryTarget, position: MapHoverPosition) => void;
  onBasemapStateChange: (state: BasemapState) => void;
  onRendererFallbackRequested: (error: Error) => void;
  onLayerDegraded?: (layerId: string, error: Error) => void;
  onError: (error: Error) => void;
}

export interface MapRenderer {
  mount(container: HTMLElement, callbacks: MapRendererCallbacks): Promise<void>;
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
