import { useEffect, useMemo, useReducer } from 'preact/hooks';
import type { GeoEventSeverity } from '../domain/types';
import type { WorldEventRegion } from '../config/regions';
import {
  defaultWorldEventMapState,
  WORLD_EVENT_MAP_STORAGE_KEY,
  type WorldEventTimeRange,
  type AviationLensMode,
  type AviationRiskSource,
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
    let cancelled = false;
    const persist = () => {
      if (!cancelled) window.localStorage.setItem(WORLD_EVENT_MAP_STORAGE_KEY, JSON.stringify(state));
    };
    const scheduler = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    const hasIdleCallback = typeof scheduler.requestIdleCallback === 'function';
    const handle = hasIdleCallback
      ? scheduler.requestIdleCallback(persist, { timeout: 1_000 })
      : window.setTimeout(persist, 0);
    return () => {
      cancelled = true;
      if (hasIdleCallback && typeof scheduler.cancelIdleCallback === 'function') scheduler.cancelIdleCallback(handle);
      else window.clearTimeout(handle);
    };
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
    setAviationLens: (lens: AviationLensMode) => dispatch({ type: 'set-aviation-lens', lens }),
    setAviationRiskSource: (source: AviationRiskSource) => dispatch({ type: 'set-aviation-risk-source', source }),
    reset: () => dispatch({ type: 'reset' }),
    shareUrl: (baseUrl: string) => serializeWorldEventMapUrl(state, baseUrl),
  }), [state]);
}
