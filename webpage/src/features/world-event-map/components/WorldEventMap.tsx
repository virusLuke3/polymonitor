import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import type { GeoEvent } from '../domain/types';
import type {
  AviationLensMode,
  AviationRiskSource,
  WorldEventMapState,
} from '../state/mapState';
import type {
  BasemapState,
  MapRenderer,
  MapRendererCallbacks,
  MapCountryTarget,
  MapHoverPosition,
} from '../renderer/MapRenderer';
import { inspectWebGL2Support } from '../renderer/webglSupport';
import { rectIntersectsViewport } from '../renderer/rendererVisibility';
import {
  worldEventLayerById,
  worldEventLayerIdForEvent,
} from '../config/layerRegistry';
import {
  MAP_SEVERITY_STYLES,
  mapSymbolForEvent,
  mapSymbolPalette,
  type MapSymbolKey,
} from '../config/mapSymbols';
import { EventInspector } from './EventInspector';
import { EventList } from './EventList';
import { AviationLens } from './AviationLens';
import { getWeatherBasemapAttribution } from '@/config/weatherBasemapMeta';
import { MapSymbolIcon } from './MapSymbolIcon';
import { useI18n } from '@/services/i18n';

export type WorldEventMapProps = {
  events: GeoEvent[];
  state: WorldEventMapState;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onEventSelect: (eventId: string | null) => void;
  onOpenMarket?: (marketId: number) => void;
  onAviationLensChange?: (lens: AviationLensMode) => void;
  onAviationRiskSourceChange?: (source: AviationRiskSource) => void;
  onAviationClose?: () => void;
  onCountryChange?: (countryCode: string | null) => void;
  height?: number;
};

export function WorldEventMap({
  events,
  state,
  onCameraChange,
  onEventSelect,
  onOpenMarket,
  onAviationLensChange,
  onAviationRiskSourceChange,
  onAviationClose,
  onCountryChange,
  height = 620,
}: WorldEventMapProps) {
  const { locale } = useI18n();
  const languageRef = useRef(locale);
  languageRef.current = locale;
  const hostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<MapRenderer | null>(null);
  const stateRef = useRef(state);
  const eventsRef = useRef(events);
  const callbackRef = useRef({ onCameraChange, onEventSelect });
  const [basemapState, setBasemapState] = useState<BasemapState>('idle');
  const [rendererKind, setRendererKind] = useState<'webgl' | 'svg'>('webgl');
  const [rendererError, setRendererError] = useState<string | null>(null);
  const [rendererLayerError, setRendererLayerError] = useState<string | null>(null);
  const [countryTarget, setCountryTarget] = useState<{
    country: MapCountryTarget;
    position?: MapHoverPosition;
    context: boolean;
  } | null>(null);
  const selectedEvent = useMemo(
    () => events.find((event) => event.id === state.selectedEventId) || null,
    [events, state.selectedEventId],
  );
  const legendItems = useMemo(
    () => {
      const activeLayerIds = new Set(state.activeLayerIds);
      const populatedLayerIds = new Set<string>();
      const visibleSymbols = new Set<MapSymbolKey>();
      for (const event of events) {
        const layerId = worldEventLayerIdForEvent(event);
        const layer = layerId ? worldEventLayerById(layerId) : null;
        if (!layerId || !layer || !activeLayerIds.has(layerId) || state.zoom < layer.minZoom) continue;
        populatedLayerIds.add(layerId);
        visibleSymbols.add(mapSymbolForEvent(event));
        if (event.category === 'infrastructure' && Array.isArray(event.properties.riskSources)) {
          const sources = event.properties.riskSources.map(String);
          if (sources.includes('weather')) visibleSymbols.add('weather-exposure');
          if (sources.includes('conflict')) visibleSymbols.add('conflict-exposure');
        }
      }
      const seen = new Set<string>();
      return state.activeLayerIds
        .map(worldEventLayerById)
        .filter((layer): layer is NonNullable<typeof layer> => (
          layer != null && populatedLayerIds.has(layer.id) && state.zoom >= layer.minZoom
        ))
        .flatMap((layer) => layer.legend)
        .filter((item) => visibleSymbols.has(item.symbol))
        .filter((item) => {
          const key = `${item.symbol}:${item.label}`;
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        })
        .map((item) => ({
          ...item,
          color: mapSymbolPalette(item.symbol).primary,
        }));
    },
    [events, state.activeLayerIds, state.zoom],
  );
  const legendContext = useMemo(() => ({
    observed: events.some((event) => {
      if (event.properties.observed === true || String(event.properties.observationType || '')) return true;
      const geometries = event.properties.geometries;
      return Boolean(geometries && typeof geometries === 'object' && 'observedTrack' in geometries);
    }),
    forecast: events.some((event) => {
      const geometries = event.properties.geometries;
      return Boolean(geometries && typeof geometries === 'object' && (
        'forecastTrack' in geometries || 'forecastCone' in geometries
      ));
    }),
    stale: events.some((event) => event.sources.some((source) => (
      String(source.freshness || '').toLowerCase().includes('stale') || source.status === 'degraded'
    ))),
    coverageGap: events.some((event) => {
      const coverage = (event as GeoEvent & { coverage?: { isComplete?: boolean } }).coverage;
      return coverage?.isComplete === false;
    }),
  }), [events]);

  callbackRef.current = { onCameraChange, onEventSelect };
  stateRef.current = state;
  eventsRef.current = events;

  useEffect(() => {
    const host = hostRef.current;
    if (!host || rendererRef.current) return;
    if (typeof performance !== 'undefined'
      && performance.getEntriesByName('polymonitor:map:first-shell').length === 0) {
      performance.mark('polymonitor:map:first-shell');
    }
    let disposed = false;
    const hostIntersectsViewport = () => rectIntersectsViewport(
      host.getBoundingClientRect(),
      window.innerWidth,
      window.innerHeight,
    );
    let inViewport = typeof IntersectionObserver === 'undefined' || hostIntersectsViewport();
    let installFrame: number | null = null;
    let secondInstallFrame: number | null = null;
    let rendererInstallStarted = false;
    let interactionReady = false;
    let idleReady = false;
    let forceReady = false;
    let idleHandle: number | null = null;
    let forceTimer: number | null = null;
    const motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');

    const updatePauseState = () => {
      const renderer = rendererRef.current;
      if (!renderer) return;
      if (document.hidden || !inViewport) renderer.pause();
      else renderer.resume();
    };

    let rendererGeneration = 0;
    let preferredLoadGeneration = 0;
    let slowLoadTimer: number | null = null;
    let rendererDeadline: number | null = null;
    const clearRendererDeadline = () => {
      if (rendererDeadline != null) window.clearTimeout(rendererDeadline);
      rendererDeadline = null;
    };
    const installRenderer = async (
      kind: 'webgl' | 'svg', reason?: Error, loadedRenderer?: new () => MapRenderer,
    ): Promise<void> => {
      if (disposed) return;
      const generation = ++rendererGeneration;
      const isCurrent = () => !disposed && generation === rendererGeneration;
      clearRendererDeadline();
      rendererRef.current?.destroy();
      rendererRef.current = null;
      delete host.dataset.mapRendererReady;
      setRendererKind(kind);
      setRendererLayerError(null);
      setRendererError(reason?.message ?? null);

      const fail = (error: unknown) => {
        if (!isCurrent()) return;
        const failure = error instanceof Error ? error : new Error(String(error));
        clearRendererDeadline();
        if (kind === 'webgl') {
          void installRenderer('svg', failure);
        } else {
          // Invalidate even a pending import/mount, so a late result cannot
          // resurrect a renderer after its deadline or overwrite the fallback.
          ++rendererGeneration;
          rendererRef.current?.destroy();
          rendererRef.current = null;
          setBasemapState('failed');
          setRendererError(failure.message);
        }
      };
      const callbacks: MapRendererCallbacks = {
        onCameraChange: (camera) => { if (isCurrent()) callbackRef.current.onCameraChange(camera); },
        onEventSelect: (eventId) => { if (isCurrent()) callbackRef.current.onEventSelect(eventId); },
        onCountrySelect: (country, position) => {
          if (isCurrent()) setCountryTarget(country ? { country, position, context: false } : null);
        },
        onCountryContextMenu: (country, position) => {
          if (isCurrent()) setCountryTarget({ country, position, context: true });
        },
        onBasemapStateChange: (nextState) => { if (isCurrent()) setBasemapState(nextState); },
        onRendererFallbackRequested: fail,
        onLayerDegraded: (layerId, error) => {
          if (isCurrent()) setRendererLayerError(`${layerId}: ${error.message}`);
        },
        onError: (error) => { if (isCurrent()) setRendererError(error.message); },
      };
      // Bound actual initialization. A slow preferred-module download is
      // handled separately, without permanently rejecting a capable desktop.
      rendererDeadline = window.setTimeout(() => fail(new Error(
        `${kind === 'webgl' ? 'WebGL' : 'SVG'} map renderer loading timed out.`,
      )), 12_000);
      try {
        const Renderer = loadedRenderer ?? (await import('../renderer/SvgMapRenderer')).SvgMapRenderer;
        if (!isCurrent()) return;
        const renderer: MapRenderer = new Renderer();
        rendererRef.current = renderer;
        renderer.setLanguage?.(languageRef.current);
        renderer.setReducedMotion(motionQuery.matches);
        renderer.setState(stateRef.current);
        renderer.setEvents(eventsRef.current);
        await renderer.mount(host, callbacks);
        if (!isCurrent()) return;
        clearRendererDeadline();
        host.dataset.mapRendererReady = kind;
        updatePauseState();
      } catch (error) {
        fail(error);
      }
    };

    const loadPreferredRenderer = async () => {
      const generation = ++preferredLoadGeneration;
      const isCurrent = () => !disposed && generation === preferredLoadGeneration;
      // SVG is a temporary usable surface while the same download continues.
      // Once it arrives, rehydrate WebGL from the latest camera/events. There
      // is one promotion attempt, never a context-recreation/retry loop.
      slowLoadTimer = window.setTimeout(() => {
        slowLoadTimer = null;
        if (isCurrent()) void installRenderer('svg', new Error(
          'The detailed map is still downloading. It will replace this temporary map when ready.',
        ));
      }, 6_000);
      try {
        const { DeckMapRenderer } = await import('../renderer/DeckMapRenderer');
        if (!isCurrent()) return;
        if (slowLoadTimer != null) window.clearTimeout(slowLoadTimer);
        slowLoadTimer = null;
        await installRenderer('webgl', undefined, DeckMapRenderer);
      } catch (error) {
        if (!isCurrent()) return;
        if (slowLoadTimer != null) window.clearTimeout(slowLoadTimer);
        slowLoadTimer = null;
        void installRenderer('svg', error instanceof Error ? error : new Error(String(error)));
      }
    };

    // Deterministic browser harness for the same fallback path used by real
    // WebGL failures. Browser/driver implementations differ in whether
    // WEBGL_lose_context auto-restores, so relying on that extension alone
    // makes the renderer-switch regression test nondeterministic. This hook is
    // unavailable during normal use and does not bypass renderer cleanup.
    const performanceHarnessEnabled = new URLSearchParams(window.location.search).get('mapPerf') === '1';
    const handleHarnessRendererFailure = () => {
      if (!performanceHarnessEnabled || disposed) return;
      ++preferredLoadGeneration;
      if (slowLoadTimer != null) window.clearTimeout(slowLoadTimer);
      slowLoadTimer = null;
      void installRenderer('svg', new Error('Simulated WebGL renderer failure from the deterministic map harness.'));
    };
    if (performanceHarnessEnabled) {
      host.addEventListener('polymonitor:map-renderer-failure', handleHarnessRendererFailure);
    }

    const scheduleRendererInstall = () => {
      if (disposed || rendererInstallStarted || installFrame != null || document.hidden || !inViewport
        || (!interactionReady && !idleReady && !forceReady)) return;
      // Let the lightweight map shell and surrounding controls paint first.
      // The renderer chunk and WebGL context are only installed for a visible
      // map, avoiding work for off-screen/hidden workspaces.
      installFrame = window.requestAnimationFrame(() => {
        installFrame = null;
        secondInstallFrame = window.requestAnimationFrame(() => {
          secondInstallFrame = null;
          if (disposed || rendererInstallStarted || document.hidden || !inViewport) return;
          rendererInstallStarted = true;
          const compactDevice = window.matchMedia('(max-width: 720px)').matches
            || Boolean((navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData);
          const support = inspectWebGL2Support({
            allowSoftware: new URLSearchParams(window.location.search).get('mapPerf') === '1',
          });
          if (support.supported && !compactDevice) void loadPreferredRenderer();
          else void installRenderer('svg', new Error(compactDevice
            ? 'Compact devices start with the lightweight SVG renderer.'
            : support.reason || 'WebGL2 is unavailable.'));
        });
      });
    };

    const markInteractionReady = () => {
      interactionReady = true;
      scheduleRendererInstall();
    };

    const observer = new ResizeObserver(() => {
      rendererRef.current?.resize();
      if (!rendererInstallStarted && !inViewport) {
        inViewport = hostIntersectsViewport();
        if (inViewport) scheduleRendererInstall();
      }
    });
    observer.observe(host);
    const intersectionObserver = typeof IntersectionObserver === 'undefined'
      ? null
      : new IntersectionObserver((entries) => {
        inViewport = entries.some((entry) => entry.isIntersecting && entry.intersectionRatio >= 0.15);
        updatePauseState();
        if (inViewport) scheduleRendererInstall();
      }, { threshold: [0, 0.15] });
    intersectionObserver?.observe(host);
    const handleVisibility = () => {
      updatePauseState();
      if (!document.hidden) scheduleRendererInstall();
    };
    const handleMotionPreference = () => {
      rendererRef.current?.setReducedMotion(motionQuery.matches);
    };
    document.addEventListener('visibilitychange', handleVisibility);
    motionQuery.addEventListener('change', handleMotionPreference);
    host.addEventListener('pointerdown', markInteractionReady, { once: true });
    host.addEventListener('wheel', markInteractionReady, { once: true });
    host.addEventListener('keydown', markInteractionReady, { once: true });
    const scheduler = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (handle: number) => void;
    };
    if (typeof scheduler.requestIdleCallback === 'function') {
      idleHandle = scheduler.requestIdleCallback(() => {
        idleHandle = null;
        idleReady = true;
        scheduleRendererInstall();
      }, { timeout: 1_500 });
    } else {
      idleHandle = window.setTimeout(() => {
        idleHandle = null;
        idleReady = true;
        scheduleRendererInstall();
      }, 350);
    }
    forceTimer = window.setTimeout(() => {
      forceTimer = null;
      forceReady = true;
      scheduleRendererInstall();
    }, 2_500);
    return () => {
      disposed = true;
      ++rendererGeneration;
      ++preferredLoadGeneration;
      if (slowLoadTimer != null) window.clearTimeout(slowLoadTimer);
      clearRendererDeadline();
      if (installFrame != null) window.cancelAnimationFrame(installFrame);
      if (secondInstallFrame != null) window.cancelAnimationFrame(secondInstallFrame);
      if (idleHandle != null) {
        if (typeof scheduler.cancelIdleCallback === 'function') scheduler.cancelIdleCallback(idleHandle);
        else window.clearTimeout(idleHandle);
      }
      if (forceTimer != null) window.clearTimeout(forceTimer);
      document.removeEventListener('visibilitychange', handleVisibility);
      motionQuery.removeEventListener('change', handleMotionPreference);
      host.removeEventListener('pointerdown', markInteractionReady);
      host.removeEventListener('wheel', markInteractionReady);
      host.removeEventListener('keydown', markInteractionReady);
      host.removeEventListener('polymonitor:map-renderer-failure', handleHarnessRendererFailure);
      observer.disconnect();
      intersectionObserver?.disconnect();
      delete host.dataset.mapRendererReady;
      rendererRef.current?.destroy();
      rendererRef.current = null;
    };
    // Renderer lifetime follows the host only; state and events use the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => rendererRef.current?.setState(state), [state]);
  useEffect(() => rendererRef.current?.setEvents(events), [events]);
  useEffect(() => rendererRef.current?.setLanguage?.(locale), [locale]);

  return (
    <div
      className={`wm-weather-deck-map map-ready ${events.length ? 'has-screen-points' : 'no-screen-points'} map-state-${basemapState}`}
      style={{ height: `${height}px` }}
    >
      <div
        ref={hostRef}
        className="wm-weather-deck-basemap ready"
        data-map-basemap-state={basemapState}
        data-map-renderer-reason={rendererError || undefined}
        role="application"
        tabIndex={0}
        aria-label="World event map. Use pointer or keyboard controls to explore active real-world events."
      />
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
      {countryTarget ? (
        <div
          className={`wm-country-context-card ${countryTarget.context ? 'is-context' : ''}`}
          style={countryTarget.position ? {
            left: `${Math.max(12, countryTarget.position.x + 12)}px`,
            top: `${Math.max(12, countryTarget.position.y + 12)}px`,
          } : undefined}
          role="dialog"
          aria-label={`${countryTarget.country.name} map actions`}
        >
          <strong>{countryTarget.country.name}</strong>
          <span>{countryTarget.country.iso2}</span>
          <div>
            <button type="button" onClick={() => {
              rendererRef.current?.fitCountry(countryTarget.country);
              setCountryTarget(null);
            }}>Fit country</button>
            <button type="button" onClick={() => {
              onCountryChange?.(countryTarget.country.iso2);
              setCountryTarget(null);
            }}>Filter events</button>
            <button type="button" aria-label="Close country actions" onClick={() => setCountryTarget(null)}>×</button>
          </div>
        </div>
      ) : null}
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
      <div
        className="wm-weather-deck-legend"
        aria-label="Visible event types. Symbol shape identifies event type; color identifies severity."
      >
        <span className="wm-map-legend-group" aria-label="Visible event types">
          {legendItems.map((item) => (
            <span key={`${item.symbol}:${item.label}`}>
            <MapSymbolIcon symbol={item.symbol} color={item.color} size={15} />
            {item.label.toUpperCase()}
            </span>
          ))}
        </span>
        <span className="wm-map-legend-severity" aria-label="Severity colors">
          {state.severities.map((severity) => (
            <b key={severity} style={{ color: MAP_SEVERITY_STYLES[severity].color }}>
              <i />{severity.toUpperCase()}
            </b>
          ))}
        </span>
        <span className="wm-map-legend-context" aria-label="Observation and coverage states">
          {legendContext.observed ? <b><i className="is-observed" />OBSERVED</b> : null}
          {legendContext.forecast ? <b><i className="is-forecast" />FORECAST</b> : null}
          {legendContext.stale ? <b><i className="is-stale" />STALE</b> : null}
          {legendContext.coverageGap ? <b><i className="is-coverage" />COVERAGE GAP</b> : null}
        </span>
      </div>
      <div className="wm-weather-deck-status" title={rendererError || undefined}>
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
          ? getWeatherBasemapAttribution(state.basemapProvider)
          : 'LOCAL COUNTRY GEOMETRY · EVENT SOURCES IN INSPECTOR'}
      </div>
      {rendererError && basemapState === 'failed' ? (
        <div className="wm-banner error" role="alert">{rendererError}</div>
      ) : null}
      {rendererLayerError ? (
        <div className="wm-banner notice" role="status">MAP DEGRADED · ISOLATED {rendererLayerError}</div>
      ) : null}
    </div>
  );
}
