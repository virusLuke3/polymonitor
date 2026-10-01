import type { RendererViewport } from '../renderer/MapRenderer';
import type { AviationPhase } from '../data/useAviationViewport';
import type { ClusterSelection, ScreenBox } from '../renderer/layerFactories/eventClusters';
import { observeMapOcclusion } from '../renderer/mapOcclusion';
import type { MapPresentationCounts } from '../renderer/eventDisclosure';
import { useWeatherRadar } from '../data/useWeatherRadar';
import { mapText } from '@/locales/map';
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
  HAZARD_SEVERITY_COLORS,
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
  onViewportChange?: (viewport: RendererViewport) => void;
  aviationStatus?: {phase: AviationPhase; error: string | null; payload: import('@/types').AviationViewportPayload | null};
  onRendererKindChange?: (kind: 'webgl' | 'svg') => void;
  events: GeoEvent[];
  state: WorldEventMapState;
  onCameraChange: (camera: Pick<WorldEventMapState, 'center' | 'zoom'>) => void;
  onEventSelect: (eventId: string | null) => void;
  onOpenMarket?: (marketId: number) => void;
  onAviationLensChange?: (lens: AviationLensMode) => void;
  onAviationRiskSourceChange?: (source: AviationRiskSource) => void;
  onAviationClose?: () => void;
  onCountryChange?: (countryCode: string | null) => void;
  onWeatherPreset?: () => void;
};

export function WorldEventMap({
  onViewportChange,
  aviationStatus,
  onRendererKindChange,
  events,
  state,
  onCameraChange,
  onEventSelect,
  onOpenMarket,
  onAviationLensChange,
  onAviationRiskSourceChange,
  onAviationClose,
  onCountryChange,
  onWeatherPreset,
}: WorldEventMapProps) {
  const { locale } = useI18n();
  const mt = (text: string) => mapText(locale, text);
  const [presentation, setPresentation] = useState<MapPresentationCounts | null>(null);
  const [expanded, setExpanded] = useState(false);
  const legendToggleRef = useRef<HTMLButtonElement>(null);
  const focusToggleRef = useRef<HTMLButtonElement>(null);
  const [legendOpen, setLegendOpen] = useState(false);
  const [rendererKind, setRendererKind] = useState<'webgl' | 'svg'>(() => new URLSearchParams(window.location.search).get('renderer') === 'svg' ? 'svg' : 'webgl');
  const [mapVisible, setMapVisible] = useState(true);
  const radar = useWeatherRadar(mapVisible && rendererKind === 'webgl' && state.activeLayerIds.includes('weather-radar'));
  const radarRef = useRef(radar); radarRef.current = radar;
  const [committedRadarFrame, setCommittedRadarFrame] = useState<import('../data/useWeatherRadar').RadarFrame | null>(null);
  const [radarTiles, setRadarTiles] = useState<'off' | 'loading' | 'ready' | 'error'>('off');
  const [clusterSelection, setClusterSelection] = useState<ClusterSelection | null>(null);
  const languageRef = useRef(locale);
  languageRef.current = locale;
  const occlusionsRef = useRef<ScreenBox[]>([]);
  const hostRef = useRef<HTMLDivElement | null>(null);
  const rendererRef = useRef<MapRenderer | null>(null);
  const stateRef = useRef(state);
  const eventsRef = useRef(events);
  const callbackRef = useRef({ onViewportChange, onCameraChange, onEventSelect, onRendererKindChange });
  const [basemapState, setBasemapState] = useState<BasemapState>('idle');
  const [rendererError, setRendererError] = useState<string | null>(null);
  const [rendererLayerError, setRendererLayerError] = useState<string | null>(null);
  const [basemapIssue, setBasemapIssue] = useState<string | null>(null);
  const retryRendererRef = useRef<(() => void) | null>(null);
  const [countryTarget, setCountryTarget] = useState<{
    country: MapCountryTarget;
    position?: MapHoverPosition;
    context: boolean;
  } | null>(null);
  const retainedSelection = useRef<GeoEvent | null>(null);
  const [listRequest, setListRequest] = useState<{ eventId: string } | null>(null);
  const currentSelection = events.find(event => event.id === state.selectedEventId);
  if (!state.selectedEventId) retainedSelection.current = null;
  else if (currentSelection) retainedSelection.current = currentSelection;
  const selectedEvent = currentSelection || (retainedSelection.current?.id === state.selectedEventId ? retainedSelection.current : null);
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const occlusion = observeMapOcclusion(host, boxes => { occlusionsRef.current = boxes; rendererRef.current?.setOcclusions?.(boxes); });
    return () => occlusion.destroy();
  }, [rendererKind]);
  useEffect(() => {
    const stage = hostRef.current?.closest('.wm-map-stage');
    stage?.classList.toggle('is-map-focused', expanded);
    rendererRef.current?.resize();
    return () => stage?.classList.remove('is-map-focused');
  }, [expanded]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      const radar = hostRef.current?.parentElement?.querySelector<HTMLDetailsElement>('.wm-map-radar-status[open]');
      if (legendOpen) { event.preventDefault(); event.stopImmediatePropagation(); setLegendOpen(false); legendToggleRef.current?.focus(); }
      else if (radar) { event.preventDefault(); event.stopImmediatePropagation(); radar.open = false; radar.querySelector('summary')?.focus(); }
      else if (expanded && !selectedEvent && !hostRef.current?.parentElement?.querySelector('.wm-world-event-list.is-open')) {
        event.preventDefault(); setExpanded(false); focusToggleRef.current?.focus();
      }
    };
    document.addEventListener('keydown', close, true);
    return () => document.removeEventListener('keydown', close, true);
  }, [legendOpen, expanded, selectedEvent]);
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

  useEffect(() => {
    rendererRef.current?.setRadar?.(radar.status === 'off' ? null : radar.frame);
  }, [radar.frame, radar.status]);

  callbackRef.current = { onViewportChange, onCameraChange, onEventSelect, onRendererKindChange };
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
      setMapVisible(!document.hidden && inViewport);
      const renderer = rendererRef.current;
      if (!renderer) return;
      if (document.hidden || !inViewport) renderer.pause();
      else renderer.resume();
    };

    let rendererGeneration = 0;
    let committedGeneration = 0;
    let candidate: MapRenderer | null = null;
    let cancelCandidateReadiness: (() => void) | null = null;
    let preferredLoading = false;
    let candidateHost: HTMLDivElement | null = null;
    let recoveryTimer: number | null = null;
    let stableTimer: number | null = null;
    let recoveryAttempts = 0;
    let episodeStarted = 0;
    const lightweight = new URLSearchParams(window.location.search).get('renderer') === 'svg';
    const support = inspectWebGL2Support({ allowSoftware: new URLSearchParams(window.location.search).get('mapPerf') === '1' });
    const scheduleRecovery = () => {
      if (disposed || lightweight || !support.supported || recoveryTimer != null || recoveryAttempts >= 2) return;
      if (!episodeStarted) episodeStarted = Date.now();
      recoveryTimer = window.setTimeout(() => {
        recoveryTimer = null;
        if (disposed || document.hidden || !inViewport) { scheduleRecovery(); return; }
        recoveryAttempts++;
        void loadPreferredRenderer();
      }, recoveryAttempts === 0 ? 30_000 : 120_000);
    };
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
      if (kind === 'svg' && stableTimer != null) { window.clearTimeout(stableTimer); stableTimer = null; }
      const isCurrent = () => !disposed && (generation === rendererGeneration || generation === committedGeneration);
      clearRendererDeadline();
      cancelCandidateReadiness?.(); cancelCandidateReadiness = null;
      candidate?.destroy(); candidate = null; candidateHost?.remove(); candidateHost = null;
      const previous = rendererRef.current;
      let failed = false;
      let readyResolve: ((ready: boolean) => void) | null = null;
      const ready = new Promise<boolean>(resolve => { readyResolve = resolve; });
      cancelCandidateReadiness = () => readyResolve?.(false);
      const staging = document.createElement('div');
      staging.style.cssText = 'position:absolute;inset:0;visibility:hidden;pointer-events:none';
      host.append(staging); candidateHost = staging;
      setRendererLayerError(null);
      setRendererError(reason?.message ?? null);

      const fail = (error: unknown) => {
        if (!isCurrent() || failed) return;
        failed = true; readyResolve?.(false);
        const failure = error instanceof Error ? error : new Error(String(error));
        clearRendererDeadline();
        candidate?.destroy(); candidate = null; candidateHost?.remove(); candidateHost = null;
        if (stableTimer != null) window.clearTimeout(stableTimer); stableTimer = null;
        if (previous) { ++rendererGeneration; setRendererError(failure.message); scheduleRecovery(); return; }
        if (kind === 'webgl') {
          void installRenderer('svg', failure);
        } else {
          // A failed mount must not resurrect after its deadline or overwrite
          // a newer renderer. Slow module downloads are handled separately.
          ++rendererGeneration;
          rendererRef.current?.destroy();
          rendererRef.current = null;
          setBasemapState('failed');
          setRendererError(failure.message);
        }
      };
      const callbacks: MapRendererCallbacks = {
        onBasemapIssueChange: message => { if (isCurrent()) setBasemapIssue(message); },
        onViewportChange: viewport => { if(isCurrent()) callbackRef.current.onViewportChange?.(viewport); },
        onLayerRecovered: () => { if(isCurrent()) setRendererLayerError(null); },
        onPresentationChange: counts => { if (isCurrent()) setPresentation(counts); },
        onRadarStateChange: (status, frame) => { if (isCurrent()) { setRadarTiles(status); if (frame !== undefined) setCommittedRadarFrame(frame); } },
        onCameraChange: (camera) => { if (isCurrent()) callbackRef.current.onCameraChange(camera); },
        onClusterSelect: (ids) => { if (isCurrent()) setClusterSelection(ids); },
        onEventSelect: (eventId) => { if (isCurrent()) callbackRef.current.onEventSelect(eventId); },
        onCountrySelect: (country, position) => {
          if (isCurrent()) setCountryTarget(country ? { country, position, context: false } : null);
        },
        onCountryContextMenu: (country, position) => {
          if (isCurrent()) setCountryTarget({ country, position, context: true });
        },
        onBasemapStateChange: (nextState) => { if (isCurrent() && !failed) { if (nextState.endsWith('-ready')) { readyResolve?.(true); setRendererError(null); } setBasemapState(nextState); } },
        onRendererFallbackRequested: fail,
        onLayerDegraded: (layerId, error) => {
          if (isCurrent()) setRendererLayerError(`${layerId}: ${error.message}`);
        },
        onError: (error) => { if (isCurrent()) setRendererError(error.message); },
      };
      try {
        if (!loadedRenderer) {
          // Report a stalled SVG download, but let the same import recover.
          // Download latency is not a failed renderer mount. Generation checks
          // still prevent late installation after unmount or WebGL promotion.
          rendererDeadline = window.setTimeout(() => {
            if (!isCurrent()) return;
            setBasemapState('failed');
            setRendererError('The lightweight map is still downloading. It will appear when ready.');
          }, 12_000);
        }
        const Renderer = loadedRenderer ?? (await import('../renderer/SvgMapRenderer')).SvgMapRenderer;
        if (!isCurrent()) return;
        clearRendererDeadline();
        setRendererError(reason?.message ?? null);
        // Keep the existing deadline for actual initialization.
        rendererDeadline = window.setTimeout(() => fail(new Error(
          `${kind === 'webgl' ? 'WebGL' : 'SVG'} map renderer loading timed out.`,
        )), 12_000);
        const renderer: MapRenderer = new Renderer();
        candidate = renderer;
        renderer.setLanguage?.(languageRef.current);
        renderer.setReducedMotion(motionQuery.matches);
        renderer.setState(stateRef.current);
        renderer.setEvents(eventsRef.current);
        renderer.setRadar?.(radarRef.current.status === 'off' ? null : radarRef.current.frame);
        await renderer.mount(staging, callbacks);
        const usable = await ready;
        if (!usable || failed || !isCurrent()) { renderer.destroy(); staging.remove(); return; }
        if (renderer.verifyReady && !await renderer.verifyReady()) {
          fail(new Error('Map candidate did not paint a frame with working picking.')); return;
        }
        if (failed || !isCurrent()) { renderer.destroy(); staging.remove(); return; }
        previous?.destroy();
        committedGeneration = generation;
        rendererRef.current = renderer; candidate = null; candidateHost = null; cancelCandidateReadiness = null;
        staging.style.visibility = ''; staging.style.pointerEvents = '';
        setRendererKind(kind); callbackRef.current.onRendererKindChange?.(kind);
        renderer.setState(stateRef.current); renderer.setEvents(eventsRef.current);
        // Manifest updates can arrive while this candidate is still staging.
        // Effects only target the committed renderer; hydrate the latest frame
        // at handover just as we do for camera and events.
        renderer.setRadar?.(radarRef.current.status === 'off' ? null : radarRef.current.frame);
        if (kind === 'svg') scheduleRecovery();
        else {
          if (recoveryTimer != null) window.clearTimeout(recoveryTimer); recoveryTimer = null;
          if (stableTimer != null) window.clearTimeout(stableTimer);
          stableTimer = window.setTimeout(() => { recoveryAttempts = 0; episodeStarted = 0; stableTimer = null; }, 60_000);
        }
        clearRendererDeadline();
        renderer.setOcclusions?.(occlusionsRef.current);
        host.dataset.mapRendererReady = kind;
        if (new URLSearchParams(window.location.search).get('mapPerf') === '1') {
          for (const key of ['__polymonitorProjectGeoPoint', '__polymonitorMapCamera', '__polymonitorMapPresentation', '__polymonitorIsolateLayer', '__polymonitorLayerFuses']) {
            const testHost = host as unknown as Record<string, unknown>, stagedHost = staging as unknown as Record<string, unknown>;
            testHost[key] = stagedHost[key];
          }
        }
        updatePauseState();
      } catch (error) {
        fail(error);
      }
    };

    const loadPreferredRenderer = async () => {
      if (preferredLoading || disposed) return;
      preferredLoading = true;
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
      } finally { preferredLoading = false; }
    };
    retryRendererRef.current = () => {
      if (lightweight || !support.supported || preferredLoading || host.dataset.mapRendererReady === 'webgl') return;
      if (recoveryAttempts >= 2 && Date.now() - episodeStarted < 300_000) {
        setRendererError('The recovery budget is exhausted. Try again after five minutes.'); return;
      }
      if (Date.now() - episodeStarted >= 300_000) { recoveryAttempts = 0; episodeStarted = Date.now(); }
      if (recoveryTimer != null) window.clearTimeout(recoveryTimer); recoveryTimer = null;
      recoveryAttempts++; void loadPreferredRenderer();
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
          if (support.supported && !lightweight) void loadPreferredRenderer();
          else void installRenderer('svg', new Error(lightweight
            ? 'Lightweight SVG renderer explicitly selected.'
            : support.reason || 'WebGL2 is unavailable.'));
        });
      });
    };

    const markInteractionReady = () => {
      interactionReady = true;
      scheduleRendererInstall();
    };

    const observer = new ResizeObserver(() => {
      measureHeight();
      rendererRef.current?.resize();
      if (!rendererInstallStarted && !inViewport) {
        inViewport = hostIntersectsViewport();
        if (inViewport) scheduleRendererInstall();
      }
    });
    const stage = host.closest<HTMLElement>('.wm-map-stage');
    const measureHeight = () => {
      if (!stage || stage.classList.contains('is-map-focused')) return;
      const available = Math.max(260, window.innerHeight - stage.getBoundingClientRect().top - 16);
      const target = window.innerWidth <= 720 ? Math.min(640, Math.max(300, available))
        : Math.min(available, Math.max(560, Math.min(1000, stage.clientWidth / 2.1)));
      stage.style.setProperty('--wm-map-height', `${Math.round(target)}px`);
    };
    measureHeight();
    window.addEventListener('resize', measureHeight);
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
      retryRendererRef.current = null;
      ++rendererGeneration;
      ++preferredLoadGeneration;
      if (slowLoadTimer != null) window.clearTimeout(slowLoadTimer);
      clearRendererDeadline();
      if (recoveryTimer != null) window.clearTimeout(recoveryTimer);
      if (stableTimer != null) window.clearTimeout(stableTimer);
      cancelCandidateReadiness?.(); cancelCandidateReadiness = null;
      candidate?.destroy(); candidateHost?.remove();
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
      window.removeEventListener('resize', measureHeight);
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
      style={{ '--wm-map-ocean': state.basemapTheme === 'positron' ? '#e6e9eb' : '#333333' }}
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
      <button ref={focusToggleRef} type="button" className="wm-map-focus-toggle" aria-pressed={expanded}
        onClick={() => setExpanded(value => !value)} aria-label={locale === 'zh' ? '展开或收起地图' : 'Expand or restore map'}><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d={expanded ? 'M3 9h6V3m12 6h-6V3M3 15h6v6m12-6h-6v6' : 'M9 3H3v6m12-6h6v6M3 15v6h6m6 0h6v-6'} /></svg></button>
      {selectedEvent ? (
        <EventInspector
          key={selectedEvent.id}
          event={selectedEvent}
          outsideFilters={!currentSelection}
          onClose={() => onEventSelect(null)}
          onBackToEvents={() => { setListRequest({ eventId: selectedEvent.id }); onEventSelect(null); }}
          onOpenMarket={onOpenMarket}
          returnFocusTarget={hostRef.current}
        />
      ) : null}
      <EventList
        openRequest={listRequest}
        presentation={presentation}
        detailVisible={Boolean(selectedEvent)}
        onCloseDetails={() => onEventSelect(null)}
        onHover={id => rendererRef.current?.setHoveredEvent?.(id)}
        events={events}
        clusterSelection={clusterSelection}
        onClearCluster={() => setClusterSelection(null)}
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
            }}>{mt('Fit country')}</button>
            <button type="button" onClick={() => {
              onCountryChange?.(countryTarget.country.iso2);
              setCountryTarget(null);
            }}>{mt('Filter events')}</button>
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
            status={aviationStatus}
            state={state}
            onLensChange={onAviationLensChange}
            onRiskSourceChange={onAviationRiskSourceChange}
            onClose={onAviationClose}
            onZoomToAircraft={() => onCameraChange({ center: state.center, zoom: Math.min(12, Math.max(2.5, state.zoom + 1)) })}
          />
        ) : null}
      <details className="wm-map-radar-status">
        <summary>{locale === 'zh' ? '雷达' : 'Radar'} · {!state.activeLayerIds.includes('weather-radar') ? mt('Off')
          : rendererKind === 'svg' ? (locale === 'zh' ? 'SVG 不支持' : 'Unavailable in SVG')
          : committedRadarFrame ? `${new Date(committedRadarFrame.time * 1000).toISOString().slice(11, 16)} UTC${radar.status === 'stale' ? ' · stale' : radarTiles === 'error' ? ' · error' : radarTiles === 'loading' ? ' · loading' : ''}` : radar.status}</summary>
        <div>
          <a href="https://www.rainviewer.com/" target="_blank" rel="noreferrer">© RainViewer</a>
          <span>{locale === 'zh' ? '最新雷达合成帧' : 'Latest radar composite'} · {committedRadarFrame ? new Date(committedRadarFrame.time * 1000).toISOString().replace('T', ' ').replace('.000Z', ' UTC') : '—'}</span>
          <span>{locale === 'zh' ? '清单 / 瓦片' : 'Manifest / tiles'}: {radar.status} / {rendererKind === 'svg' ? 'unavailable (SVG)' : radarTiles}</span>
          <span>{locale === 'zh' ? '覆盖不完整；透明不代表无降水。灰暗遮罩表示无雷达覆盖。' : 'Partial coverage; transparent does not mean dry. Shaded areas lack radar coverage.'}</span>
          {radar.error ? <span>{radar.error}</span> : null}
          <span>{rendererKind === 'svg' ? 'SVG FALLBACK' : basemapState.replace(/-/g, ' ').toUpperCase()}</span>
          {onWeatherPreset ? <button type="button" onClick={onWeatherPreset}>{locale === 'zh' ? '启用天气视图' : 'Enable weather view'}</button> : null}
        </div>
      </details>
      <button ref={legendToggleRef} type="button" className="wm-map-legend-toggle" aria-controls="wm-map-legend" aria-expanded={legendOpen} onClick={() => setLegendOpen(value => !value)}>{mt('Legend')}</button>
      <div
        id="wm-map-legend"
        onWheel={event => event.stopPropagation()}
        className={`wm-weather-deck-legend ${legendOpen ? 'is-open' : ''}`}
        aria-label="Visible event types. Symbol shape identifies event type; color identifies severity."
      >
        <h3>{locale === 'zh' ? '事件类型' : 'Event types'}</h3>
        <span className="wm-map-legend-group" aria-label="Visible event types">
          {legendItems.map((item) => (
            <span key={`${item.symbol}:${item.label}`}>
            <MapSymbolIcon symbol={item.symbol} color="#c2c8cd" size={15} framed={false} />
            {mt(item.label)}
            </span>
          ))}
        </span>
        <h3>{locale === 'zh' ? '灾害等级' : 'Severity'}</h3>
        <span className="wm-map-legend-severity" aria-label="Severity colors">
          {state.severities.map((severity) => (
            <b key={severity} style={{ color: `rgb(${HAZARD_SEVERITY_COLORS[severity].slice(0, 3).join(",")})` }}>
              <i />{mt(severity)}
            </b>
          ))}
        </span>
        <h3>{locale === 'zh' ? '观测、预测与数据状态' : 'Observation, forecast and data'}</h3>
        <span className="wm-map-legend-context" aria-label="Observation and coverage states">
          {legendContext.observed ? <b><i className="is-observed" />{mt('Observed')}</b> : null}
          {legendContext.forecast ? <b><i className="is-forecast" />{mt('Forecast')}</b> : null}
          {legendContext.stale ? <b><i className="is-stale" />{mt('Stale')}</b> : null}
          {legendContext.coverageGap ? <b><i className="is-coverage" />{mt('Coverage gap')}</b> : null}
        </span>
      </div>
      <div className="wm-weather-deck-status" hidden={basemapState === 'primary-ready' && !basemapIssue} title={basemapIssue || rendererError || undefined}>
        {rendererKind === 'svg'
          ? 'SVG FALLBACK'
          : basemapState === 'local-fallback-ready'
            ? 'LOCAL BASEMAP'
            : basemapState === 'primary-ready'
              ? basemapIssue ? (locale === 'zh' ? '底图部分缺失' : 'PARTIAL BASEMAP') : 'PRIMARY BASEMAP'
              : basemapState.replace(/-/g, ' ').toUpperCase()}
      {rendererKind === 'svg' && new URLSearchParams(window.location.search).get('renderer') !== 'svg' ? (
        <button className="wm-map-renderer-retry" type="button" onClick={() => retryRendererRef.current?.()} title={rendererError || undefined}>
          {locale === 'zh' ? '重试详细地图' : 'Retry detailed map'}
        </button>
      ) : null}
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
