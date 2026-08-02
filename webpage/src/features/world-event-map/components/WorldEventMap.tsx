import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { GeoEvent } from '../domain/types';
import type {
  AviationLensMode,
  AviationRiskSource,
  WorldEventMapState,
} from '../state/mapState';
import { DeckMapRenderer } from '../renderer/DeckMapRenderer';
import { SvgMapRenderer } from '../renderer/SvgMapRenderer';
import type {
  BasemapState,
  MapHoverPosition,
  MapRenderer,
  MapRendererCallbacks,
} from '../renderer/MapRenderer';
import { inspectWebGL2Support } from '../renderer/webglSupport';
import { worldEventLayerById } from '../config/layerRegistry';
import { EventInspector } from './EventInspector';
import { EventList } from './EventList';
import { AviationLens } from './AviationLens';
import { getWeatherBasemapAttribution } from '@/config/weatherBasemap';

export type WorldEventMapProps = {
  events: GeoEvent[];
  state: WorldEventMapState;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onEventSelect: (eventId: string | null) => void;
  onEventHover: (eventId: string | null) => void;
  onOpenMarket?: (marketId: number) => void;
  onAviationLensChange?: (lens: AviationLensMode) => void;
  onAviationRiskSourceChange?: (source: AviationRiskSource) => void;
  onAviationClose?: () => void;
  height?: number;
};

export function WorldEventMap({
  events,
  state,
  onCameraChange,
  onEventSelect,
  onEventHover,
  onOpenMarket,
  onAviationLensChange,
  onAviationRiskSourceChange,
  onAviationClose,
  height = 620,
}: WorldEventMapProps) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<MapRenderer | null>(null);
  const stateRef = useRef(state);
  const eventsRef = useRef(events);
  const callbackRef = useRef({ onCameraChange, onEventSelect, onEventHover });
  const [basemapState, setBasemapState] = useState<BasemapState>('idle');
  const [rendererKind, setRendererKind] = useState<'webgl' | 'svg'>('webgl');
  const [rendererError, setRendererError] = useState<string | null>(null);
  const [hoverPosition, setHoverPosition] = useState<MapHoverPosition | null>(null);
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
  stateRef.current = state;
  eventsRef.current = events;

  useEffect(() => {
    const host = hostRef.current;
    if (!host || rendererRef.current) return;
    let disposed = false;
    let inViewport = true;
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

    const updatePauseState = () => {
      const renderer = rendererRef.current;
      if (!renderer) return;
      if (document.hidden || !inViewport) renderer.pause();
      else renderer.resume();
    };

    let installRenderer: (kind: 'webgl' | 'svg', reason?: Error) => Promise<void>;
    const callbacks: MapRendererCallbacks = {
      onCameraChange: (camera) => callbackRef.current.onCameraChange(camera),
      onEventSelect: (eventId) => callbackRef.current.onEventSelect(eventId),
      onEventHover: (eventId, position) => {
        callbackRef.current.onEventHover(eventId);
        setHoverPosition(eventId ? position || null : null);
      },
      onBasemapStateChange: (nextState) => {
        if (!disposed) setBasemapState(nextState);
      },
      onRendererFallbackRequested: (error) => {
        if (disposed) return;
        setRendererError(error.message);
        void installRenderer('svg', error);
      },
      onError: (error) => setRendererError(error.message),
    };

    installRenderer = async (kind, reason) => {
      if (disposed) return;
      rendererRef.current?.destroy();
      const renderer: MapRenderer = kind === 'webgl'
        ? new DeckMapRenderer()
        : new SvgMapRenderer();
      rendererRef.current = renderer;
      setRendererKind(kind);
      if (reason) setRendererError(reason.message);
      renderer.setReducedMotion(motionQuery.matches);
      renderer.setState(stateRef.current);
      renderer.setEvents(eventsRef.current);
      try {
        await renderer.mount(host, callbacks);
        updatePauseState();
      } catch (error) {
        if (disposed || rendererRef.current !== renderer) return;
        const failure = error instanceof Error ? error : new Error(String(error));
        if (kind === 'webgl') {
          await installRenderer('svg', failure);
          return;
        }
        setBasemapState('failed');
        setRendererError(failure.message);
      }
    };

    const support = inspectWebGL2Support();
    if (support.supported) void installRenderer('webgl');
    else void installRenderer('svg', new Error(support.reason || 'WebGL2 is unavailable.'));

    const observer = new ResizeObserver(() => rendererRef.current?.resize());
    observer.observe(host);
    const intersectionObserver = new IntersectionObserver((entries) => {
      inViewport = entries.some((entry) => entry.isIntersecting && entry.intersectionRatio > 0);
      updatePauseState();
    }, { threshold: [0, 0.01] });
    intersectionObserver.observe(host);
    const handleVisibility = () => updatePauseState();
    const handleMotionPreference = () => {
      rendererRef.current?.setReducedMotion(motionQuery.matches);
    };
    document.addEventListener('visibilitychange', handleVisibility);
    motionQuery.addEventListener('change', handleMotionPreference);
    return () => {
      disposed = true;
      document.removeEventListener('visibilitychange', handleVisibility);
      motionQuery.removeEventListener('change', handleMotionPreference);
      observer.disconnect();
      intersectionObserver.disconnect();
      rendererRef.current?.destroy();
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
        aria-label="World event map. Use pointer or keyboard controls to explore active real-world events."
      />
      {rendererKind === 'svg' && hoveredEvent && !selectedEvent && hoverPosition ? (
        <div
          className="wm-weather-deck-tooltip wm-world-event-svg-tooltip"
          role="status"
          style={{ left: `${hoverPosition.x}px`, top: `${hoverPosition.y}px` }}
        >
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
      <EventList
        events={events}
        selectedEventId={state.selectedEventId}
        onSelect={onEventSelect}
      />
      {state.activeLayerIds.includes('air-routes')
        && onAviationLensChange
        && onAviationRiskSourceChange
        && onAviationClose ? (
          <AviationLens
            events={events}
            state={state}
            onLensChange={onAviationLensChange}
            onRiskSourceChange={onAviationRiskSourceChange}
            onClose={onAviationClose}
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
        {rendererKind === 'svg'
          ? 'SVG FALLBACK'
          : basemapState === 'local-fallback-ready'
            ? 'LOCAL BASEMAP'
            : basemapState === 'primary-ready'
              ? 'PRIMARY BASEMAP'
              : basemapState.replace(/-/g, ' ').toUpperCase()}
      </div>
      <div className="wm-world-event-attribution">
        {rendererKind === 'webgl' && basemapState === 'primary-ready'
          ? getWeatherBasemapAttribution()
          : 'LOCAL COUNTRY GEOMETRY · EVENT SOURCES IN INSPECTOR'}
      </div>
      {rendererError && basemapState === 'failed' ? (
        <div className="wm-banner error" role="alert">{rendererError}</div>
      ) : null}
    </div>
  );
}
