import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { GeoEvent } from '../domain/types';
import type { WorldEventMapState } from '../state/mapState';
import { DeckMapRenderer } from '../renderer/DeckMapRenderer';
import type { BasemapState, MapRenderer } from '../renderer/MapRenderer';
import { isHazardEvent } from '../renderer/layerFactories';

export type WorldEventMapProps = {
  events: GeoEvent[];
  state: WorldEventMapState;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onEventSelect: (eventId: string | null) => void;
  onEventHover: (eventId: string | null) => void;
  height?: number;
};

function eventMetric(event: GeoEvent) {
  if (!isHazardEvent(event)) return null;
  if (event.metrics.kind === 'earthquake') {
    return `M${event.metrics.magnitude.toFixed(1)} · ${event.metrics.depthKm ?? '--'} km deep`;
  }
  if (event.metrics.kind === 'tropical-cyclone') {
    const wind = event.metrics.maximumWind;
    return wind ? `${wind.value} ${wind.unit} maximum wind` : event.metrics.categoryLabel || null;
  }
  if (event.metrics.kind === 'wildfire') {
    return `${event.metrics.detectionCount ?? '--'} detections`;
  }
  if (event.metrics.kind === 'climate-anomaly') {
    return `${event.metrics.anomaly >= 0 ? '+' : ''}${event.metrics.anomaly} ${event.metrics.unit} anomaly`;
  }
  if (event.metrics.kind === 'volcano-or-other') return event.metrics.statusLabel || null;
  if (event.metrics.kind === 'weather-alert') return event.metrics.providerSeverity || event.metrics.urgency || null;
  return null;
}

export function WorldEventMap({
  events,
  state,
  onCameraChange,
  onEventSelect,
  onEventHover,
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
      <div ref={hostRef} className="wm-weather-deck-basemap ready" aria-label="World event map" />
      {hoveredEvent && !selectedEvent ? (
        <div className="wm-deck-tooltip" role="status">
          <strong>{hoveredEvent.title}</strong>
          <span>{hoveredEvent.locationLabel || hoveredEvent.severity.toUpperCase()}</span>
        </div>
      ) : null}
      {selectedEvent ? (
        <aside className="wm-map-risk-inspector" aria-label={`${selectedEvent.title} details`}>
          <button type="button" className="wm-map-risk-close" onClick={() => onEventSelect(null)}>×</button>
          <span className="wm-map-risk-kicker">{isHazardEvent(selectedEvent) ? selectedEvent.hazardKind : selectedEvent.category}</span>
          <strong>{selectedEvent.title}</strong>
          {eventMetric(selectedEvent) ? <p>{eventMetric(selectedEvent)}</p> : null}
          <div className="wm-map-conflict-body">
            <span>Severity</span>
            <strong>{selectedEvent.severity}</strong>
            <span>Location</span>
            <strong>{selectedEvent.locationLabel || selectedEvent.locationPrecision}</strong>
            <span>Observed</span>
            <strong>{selectedEvent.updatedAt || selectedEvent.occurredAt || '--'}</strong>
          </div>
          {selectedEvent.sources[0]?.url ? (
            <a className="wm-map-risk-link" href={selectedEvent.sources[0].url} target="_blank" rel="noreferrer">
              OPEN SOURCE
            </a>
          ) : null}
        </aside>
      ) : null}
      <div className="wm-weather-deck-legend" aria-hidden="true">
        <span><i className="cool" />INFO</span>
        <span><i className="country" />WATCH</span>
        <span><i className="hot" />WARNING</span>
        <span><i className="ucdp" />CRITICAL</span>
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
