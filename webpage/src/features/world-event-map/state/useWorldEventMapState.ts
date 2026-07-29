import { useEffect, useMemo, useReducer } from 'preact/hooks';
import type { GeoEventSeverity } from '../domain/types';
import type { WorldEventRegion } from '../config/regions';
import {
  defaultWorldEventMapState,
  WORLD_EVENT_MAP_STORAGE_KEY,
  type WorldEventTimeRange,
} from './mapState';
import { worldEventMapReducer } from './mapReducer';
import {
  parseWorldEventMapState,
  readStoredWorldEventMapState,
  serializeWorldEventMapUrl,
} from './urlState';

function initialState() {
  const defaults = defaultWorldEventMapState();
  if (typeof window === 'undefined') return defaults;
  const stored = readStoredWorldEventMapState(window.localStorage.getItem(WORLD_EVENT_MAP_STORAGE_KEY), defaults);
  return parseWorldEventMapState(window.location.search, stored);
}

export function useWorldEventMapState() {
  const [state, dispatch] = useReducer(worldEventMapReducer, undefined, initialState);
  useEffect(() => {
    if (typeof window === 'undefined') return;
    window.localStorage.setItem(WORLD_EVENT_MAP_STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  return useMemo(() => ({
    state,
    setCamera: (center: { lon: number; lat: number }, zoom: number) => dispatch({ type: 'set-camera', center, zoom }),
    setZoom: (zoom: number) => dispatch({ type: 'set-zoom', zoom }),
    setRegion: (region: WorldEventRegion) => dispatch({ type: 'set-region', region }),
    toggleLayer: (layerId: string) => dispatch({ type: 'toggle-layer', layerId }),
    setTimeRange: (timeRange: WorldEventTimeRange) => dispatch({ type: 'set-time-range', timeRange }),
    setSeverities: (severities: GeoEventSeverity[]) => dispatch({ type: 'set-severities', severities }),
    selectEvent: (eventId: string | null) => dispatch({ type: 'select-event', eventId }),
    hoverEvent: (eventId: string | null) => dispatch({ type: 'hover-event', eventId }),
    reset: () => dispatch({ type: 'reset' }),
    shareUrl: (baseUrl: string) => serializeWorldEventMapUrl(state, baseUrl),
  }), [state]);
}
