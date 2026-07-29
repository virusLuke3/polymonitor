import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { GeoEvent } from '../domain/types';
import type { WorldEventMapState } from '../state/mapState';
import { DeckMapRenderer } from '../renderer/DeckMapRenderer';
import type { BasemapState, MapRenderer } from '../renderer/MapRenderer';
import { worldEventLayerById } from '../config/layerRegistry';
import { EventInspector } from './EventInspector';

export type WorldEventMapProps = {
  events: GeoEvent[];
  state: WorldEventMapState;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onEventSelect: (eventId: string | null) => void;
  onEventHover: (eventId: string | null) => void;
  onOpenMarket?: (marketId: number) => void;
  height?: number;
};

export function WorldEventMap({
  events,
  state,
  onCameraChange,
  onEventSelect,
  onEventHover,
  onOpenMarket,
  height = 620,
}: WorldEventMapProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<MapRenderer | null>(null);
  const callbackRef = useRef({ onCameraChange, onEventSelect, onEventHover });
  const [basemapState, setBasemapState] = useState<BasemapState>('idle');
  const [rendererError, setRendererError] = useState<string | null>(null);
  const selectedEvent = useMemo(
    () => events.find((event) => event.id === state.selectedEventId) || null,
    [events, state.selectedEventId],
  );
  const hoveredEvent = useMemo(
    () => events.find((event) => event.id === state.hoveredEventId) || null,
    [events, state.hoveredEventId],
  );
  const legendItems = useMemo(
    () => state.activeLayerIds.flatMap((layerId) => worldEventLayerById(layerId)?.legend || []),
    [state.activeLayerIds],
  );

  callbackRef.current = { onCameraChange, onEventSelect, onEventHover };

  useEffect(() => {
    const host = hostRef.current;
    if (!host || rendererRef.current) return;
    const renderer = new DeckMapRenderer();
    rendererRef.current = renderer;
    renderer.setState(state);
    renderer.setEvents(events);
    void renderer.mount(host, {
      onCameraChange: (camera) => callbackRef.current.onCameraChange(camera),
      onEventSelect: (eventId) => callbackRef.current.onEventSelect(eventId),
      onEventHover: (eventId) => callbackRef.current.onEventHover(eventId),
      onBasemapStateChange: setBasemapState,
      onError: (error) => setRendererError(error.message),
    });
    const observer = new ResizeObserver(() => renderer.resize());
    observer.observe(host);
    const handleVisibility = () => {
      if (document.hidden) renderer.pause();
      else renderer.resume();
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      observer.disconnect();
      renderer.destroy();
      rendererRef.current = null;
    };
    // Renderer lifetime follows the host only; state and events use the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => rendererRef.current?.setState(state), [state]);
  useEffect(() => rendererRef.current?.setEvents(events), [events]);

  return (
    <div
      className={`wm-weather-deck-map map-ready ${events.length ? 'has-screen-points' : 'no-screen-points'} map-state-${basemapState}`}
      style={{ height: `${height}px` }}
    >
      <div
        ref={hostRef}
        className="wm-weather-deck-basemap ready"
        role="application"
        tabIndex={0}
        aria-label="World event map. Use pointer or keyboard controls to explore active hazard events."
      />
      {hoveredEvent && !selectedEvent ? (
        <div className="wm-deck-tooltip" role="status">
          <strong>{hoveredEvent.title}</strong>
          <span>{hoveredEvent.locationLabel || hoveredEvent.severity.toUpperCase()}</span>
        </div>
      ) : null}
      {selectedEvent ? (
        <EventInspector
          key={selectedEvent.id}
          event={selectedEvent}
          onClose={() => onEventSelect(null)}
          onOpenMarket={onOpenMarket}
          returnFocusTarget={hostRef.current}
        />
      ) : null}
      <div className="wm-weather-deck-legend" aria-label="Active hazard legend">
        {legendItems.map((item) => (
          <span key={`${item.label}:${item.color}`}>
            <i style={{ background: item.color }} />
            {item.label.toUpperCase()}
          </span>
        ))}
      </div>
      <div className="wm-weather-deck-status">
        {basemapState === 'local-fallback-ready' ? 'LOCAL BASEMAP' : basemapState.replace(/-/g, ' ').toUpperCase()}
      </div>
      {rendererError && basemapState === 'failed' ? (
        <div className="wm-banner error" role="alert">{rendererError}</div>
      ) : null}
    </div>
  );
}
