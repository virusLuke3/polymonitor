import { EventGeometryCache, isGeometryEvent } from './layerFactories/eventGeometryLayers';
import { MAP_RENDERER_TIMEOUTS, splitViewportBounds } from './MapRenderer';
import { loadMapFonts } from '../config/mapTypography';
import type { ScreenBox } from './layerFactories/eventClusters';
import { mapPresentationCounts } from './eventDisclosure';
import { selectionPanOffset } from './rendererVisibility';
import { eventRepresentativePoint, mapLabelFontFamily } from './layerFactories/shared';
import type { RadarFrame } from '../data/useWeatherRadar';
import { coordinatePositions } from '../domain/countryGeometry';
import { MapLibreOverlay } from '@deck.gl/maplibre';
import type { Deck, Layer, LayersList, PickingInfo } from '@deck.gl/core';
import { TextLayer } from '@deck.gl/layers';
import type { FeatureCollection, Geometry, Position } from 'geojson';
import * as maplibregl from 'maplibre-gl';
import {
  type FilterSpecification,
  type Map as MapLibreMap,
  type MapMouseEvent,
  type MapSourceDataEvent,
} from 'maplibre-gl';
import maplibreWorkerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  getWeatherMapFallbackStyle,
  getWeatherMapStyle,
  resetWorldEventPMTilesArchive,
  reinforceWorldEventBasemapLabels,
} from '@/config/weatherBasemap';
import type { GeoEvent } from '../domain/types';
import { clampWorldEventZoom, WORLD_EVENT_MAP_MAX_ZOOM } from '../state/mapState';
import type { WorldEventMapState } from '../state/mapState';
import type { BasemapState, MapCountryTarget, MapRenderer, MapRendererCallbacks } from './MapRenderer';
import {
  createAviationDynamicLayers,
  createAviationStaticLayerSections,
  createEventInteractionLayers,
  createEventPulseLayers,
  createWorldEventGeometryLayers,
  createWorldEventPointLayers,
  EventClusterIndex,
  hasAnimatedHazardPulse,
  selectEventPulseCandidates,
  type AviationStaticLayerSections,
  type AviationMotionPoint,
  type EventCluster,
} from './layerFactories';
import {
  advanceAnimationTime,
  boundedAnimationDelta,
  MAP_ANIMATION_FRAME_INTERVAL_MS,
} from './animationClock';
import {
  pickedWorldEvent,
  pickedWorldEventCluster,
  worldEventTooltipModel,
  type WorldEventPickedObject,
} from './hoverTooltip';
import {
  createCountryHoverQueryController,
  type CountryHoverQueryController,
} from './countryHoverController';
import { DeferredLatestCommit, scheduleAfterMainThreadYield } from './deferredCommit';
import { MapPerformanceMonitor } from './mapPerformance';
import { MapRenderScheduler, type MapRenderInvalidation } from './renderScheduler';
import { RendererTooltip } from './rendererTooltip';
import {
  countryBasemapLabels,
  countryBasemapLabelName,
  visibleCountryBasemapLabels,
  type CountryBasemapLabel,
} from './countryBasemapLabels';

// MapLibre 6 cannot infer a worker URL after Vite rewrites its module path.
// Bundle the worker and its shared imports, while keeping the renderer lazy.
maplibregl.setWorkerUrl(maplibreWorkerUrl);

const COUNTRY_INTERACTION_SOURCE = 'world-event-country-interaction-source';
const FALLBACK_COUNTRY_SOURCE = 'wm-weather-country-boundaries';
const COUNTRY_INTERACTIVE_LAYER = 'world-event-country-interactive';
const COUNTRY_HOVER_FILL_LAYER = 'world-event-country-hover-fill';
const COUNTRY_HOVER_BORDER_LAYER = 'world-event-country-hover-border';
const EMPTY_COUNTRY_FILTER = ['==', ['get', 'ISO3166-1-Alpha-2'], ''] as FilterSpecification;

type MapPerformanceHarnessHost = HTMLElement & {
  __polymonitorMapCamera?: (center: [number,number], zoom: number) => void;
  __polymonitorIsolateLayer?: () => string | undefined;
  __polymonitorLayerFuses?: () => string[];
  __polymonitorMapPresentation?: (members?: boolean) => ReturnType<EventClusterIndex['diagnostics']>;
  __polymonitorProjectGeoPoint?: (lon: number, lat: number, target?: 'static' | 'aviation') => { x: number; y: number };
};

function geometryPositions(geometry: Geometry | null | undefined): Position[] {
  if (!geometry) return [];
  if (geometry.type === 'GeometryCollection') return geometry.geometries.flatMap(geometryPositions);
  return coordinatePositions(geometry.coordinates);
}

function countryTarget(feature: { properties?: Record<string, unknown> | null; geometry?: Geometry | null } | undefined) {
  const iso2 = String(feature?.properties?.['ISO3166-1-Alpha-2'] || '').toUpperCase();
  const name = String(feature?.properties?.['name:en'] || feature?.properties?.name || iso2);
  const positions = geometryPositions(feature?.geometry);
  if (!iso2 || !positions.length) return null;
  const lons = positions.map((position) => Number(position[0])).filter(Number.isFinite);
  const lats = positions.map((position) => Number(position[1])).filter(Number.isFinite);
  if (!lons.length || !lats.length) return null;
  return {
    iso2,
    name,
    bounds: [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
  } satisfies MapCountryTarget;
}

function isAviationEvent(event: GeoEvent) {
  if (event.category !== 'infrastructure') return false;
  const entity = String(event.properties.mapEntity || '');
  return entity === 'air-route'
    || entity === 'air-hub'
    || entity === 'air-flight'
    || entity === 'live-aircraft';
}

function sameEventReferences(
  previous: readonly GeoEvent[],
  next: readonly GeoEvent[],
  predicate: (event: GeoEvent) => boolean,
) {
  let previousIndex = 0;
  let nextIndex = 0;
  while (true) {
    while (previousIndex < previous.length && !predicate(previous[previousIndex]!)) previousIndex += 1;
    while (nextIndex < next.length && !predicate(next[nextIndex]!)) nextIndex += 1;
    const previousEvent = previous[previousIndex];
    const nextEvent = next[nextIndex];
    if (!previousEvent || !nextEvent) return previousEvent === nextEvent;
    if (previousEvent !== nextEvent) return false;
    previousIndex += 1;
    nextIndex += 1;
  }
}

export class DeckMapRenderer implements MapRenderer {
  private radarFrame: RadarFrame | null = null;
  private radarAppliedUrl = '';

  setRadar(frame: RadarFrame | null) {
    const changed = frame?.tiles !== this.radarFrame?.tiles;
    const refreshed = frame !== this.radarFrame && this.radarFailed;
    this.radarFrame = frame;
    if (changed || refreshed) {
      this.radarRetryCount = 0;
      if (Date.now() >= this.radarBlockedUntil && this.radarRetryTimer != null) {
        window.clearTimeout(this.radarRetryTimer); this.radarRetryTimer = null;
      }
    }
    this.applyRadar();
  }

  private radarActiveBank = '';
  private radarPending: { bank: string; frame: RadarFrame } | null = null;
  private radarRetryTimer: number | null = null;
  private radarRetryCount = 0;
  private radarBlockedUntil = 0;
  private radarFailed = false;
  private removeRadarBank(bank: string) {
    const map = this.map; if (!map) return;
    for (const id of [bank, `${bank}-coverage`]) {
      if (map.getLayer(id)) map.removeLayer(id);
      if (map.getSource(id)) map.removeSource(id);
    }
  }
  private applyRadar = () => {
    const map = this.map;
    if (!map || this.destroyed) return;
    if (!this.radarFrame || this.paused) {
      this.removeRadarBank('weather-radar'); this.removeRadarBank('weather-radar-next');
      this.radarPending = null; this.radarActiveBank = ''; this.radarAppliedUrl = '';
      if (this.radarRetryTimer != null) window.clearTimeout(this.radarRetryTimer); this.radarRetryTimer = null;
      this.callbacks?.onRadarStateChange?.('off', null); return;
    }
    if (Date.now() < this.radarBlockedUntil || this.radarRetryTimer != null) return;
    // isStyleLoaded also waits for unrelated sources. Aviation animation can
    // keep `idle` from firing indefinitely. A parsed style permits addSource;
    // handleStyleLoad already retries this when the style itself is pending.
    if (!map.getStyle()?.layers) return;
    const frame = this.radarFrame;
    if ((!this.radarFailed && this.radarAppliedUrl === frame.tiles) || this.radarPending?.frame.tiles === frame.tiles) return;
    if (this.radarPending) this.removeRadarBank(this.radarPending.bank);
    const bank = this.radarActiveBank === 'weather-radar' ? 'weather-radar-next' : 'weather-radar';
    this.removeRadarBank(bank); this.radarPending = { bank, frame };
    const before = map.getStyle().layers.find(layer => layer.type === 'symbol' || layer.id.includes('boundar'))?.id;
    for (const [id,url] of [[bank,frame.tiles],[`${bank}-coverage`,frame.coverageTiles]]) {
      map.addSource(id!, { type:'raster', tiles:[url!],tileSize:256,minzoom:0,maxzoom:7,attribution:'© RainViewer' });
      map.addLayer({id:id!,type:'raster',source:id!,paint:{'raster-opacity':0,'raster-fade-duration':200}},before);
    }
    this.callbacks?.onRadarStateChange?.('loading');
  };
  private commitRadarIfReady() {
    const pending = this.radarPending, map = this.map;
    if (!pending || !map || !map.isSourceLoaded(pending.bank) || !map.isSourceLoaded(`${pending.bank}-coverage`)) return;
    const old = this.radarActiveBank;
    this.radarActiveBank = pending.bank; this.radarAppliedUrl = pending.frame.tiles; this.radarPending = null;
    map.setPaintProperty(pending.bank,'raster-opacity',0.6);
    map.setPaintProperty(`${pending.bank}-coverage`,'raster-opacity',0.16);
    if (old && old !== pending.bank) this.removeRadarBank(old);
    this.radarRetryCount = 0; this.radarFailed = false;
    if (this.radarRetryTimer != null) window.clearTimeout(this.radarRetryTimer); this.radarRetryTimer = null;
    this.callbacks?.onRadarStateChange?.('ready',pending.frame);
  }

  private map: MapLibreMap | null = null;
  private overlay: MapLibreOverlay | null = null;
  private aviationOverlay: MapLibreOverlay | null = null;
  private callbacks: MapRendererCallbacks | null = null;
  private state: WorldEventMapState | null = null;
  private language: 'en' | 'zh' = 'en';
  private mapFontsReady = false;
  private events: GeoEvent[] = [];
  private fallbackApplied = false;
  private primaryHasContent = false;
  private primarySourceIds = new Set(['basemap']);
  private readonly missingBaseTiles = new Map<string, {x: number; y: number; z: number}>();
  private missingTileRetryTimer: number | null = null;
  private missingTileAttempts = 0;
  private readinessCancel: (() => void) | null = null;

  verifyReady(): Promise<boolean> {
    return new Promise(resolve => {
      let frame = false;
      let timer: number | undefined;
      const deadline = performance.now() + MAP_RENDERER_TIMEOUTS.frameVerification;
      const painted = () => { frame = true; };
      const finish = (ok: boolean) => {
        window.clearTimeout(timer); this.map?.off('render', painted);
        this.readinessCancel = null; resolve(ok);
      };
      this.readinessCancel = () => finish(false);
      const check = () => {
        if (this.destroyed) { finish(false); return; }
        if (frame && this.warmOverlayPicking(this.overlay)) { finish(true); return; }
        if (performance.now() >= deadline) { finish(false); return; }
        this.map?.triggerRepaint(); timer = window.setTimeout(check, 32);
      };
      this.map?.on('render', painted); check();
    });
  }
  private fallbackTimer: number | null = null;
  private primaryMetadataReady = false;
  private fallbackSourceTimer: number | null = null;
  private fallbackCountryLabels: CountryBasemapLabel[] = [];
  private fallbackCountryLabelsLoading: Promise<void> | null = null;
  private primaryRecoveryTimer: number | null = null;
  private primaryRecoveryAttempts = 0;
  private contextRecoveryTimer: number | null = null;
  private contextRecoveryAttempts = 0;
  private contextStableTimer: number | null = null;
  private overlayMounted = false;
  private aviationOverlayMounted = false;
  private aviationOverlayViewSync: (() => void) | null = null;
  private aviationOverlayViewSyncPaused = false;
  private aviationDeckSuspended = false;
  private paused = false;
  private destroyed = false;
  private applyingCamera = false;
  private reducedMotion = false;
  private animationFrame: number | null = null;
  private animationResumeTimer: number | null = null;
  private lastAnimationTimestamp: number | null = null;
  private pendingAnimationDeltaMs = 0;
  private animationTime = 0;
  private pointLayers: LayersList | null = null;
  private geometryLayers: LayersList = [];
  private readonly geometryCache = new EventGeometryCache();
  private geometryGeneration = 0;
  private geometryNeedsCommit = true;
  private occupiedScreenBoxes: ScreenBox[] = [];
  private basemapLabelBoxes: ScreenBox[] | null = null;
  private labelWidths = new Map<string, number>();
  private eventsById = new Map<string, GeoEvent>();
  private interactionCache: { selected: GeoEvent | null; hovered: GeoEvent | null;
    cluster: EventCluster | null; layers: LayersList } | null = null;
  private readonly labelMeasureContext = typeof document === 'undefined' ? null : document.createElement('canvas').getContext('2d');
  private readonly clusterIndex = new EventClusterIndex();
  private readonly renderScheduler: MapRenderScheduler;
  private readonly heavyGeometryCommit: DeferredLatestCommit<{
    events: GeoEvent[];
    selectedEventId: string | null;
    zoom: number;
    beforeId?: string;
    viewport?: [number, number, number, number];
    generation: number;
  }>;
  private readonly aviationLayerCommit: DeferredLatestCommit<LayersList>;
  private readonly performanceMonitor = new MapPerformanceMonitor();
  private deckHoverActive = false;
  private hoveredDeckEventId: string | null = null;
  private hoveredDeckCluster: EventCluster | null = null;
  private staticDeckHoverActive = false;
  private aviationDeckHoverActive = false;
  private hoveredCountryIso2: string | null = null;
  private countryPointer: MapMouseEvent["point"] | null = null;
  private countryHoverQueryController: CountryHoverQueryController<MapMouseEvent['point']> | null = null;
  private interacting = false;
  private mapDragging = false;
  private animationIntervalMs = MAP_ANIMATION_FRAME_INTERVAL_MS;
  private animationRecoveryFrames = 0;
  private cancelPickingWarmup: (() => void) | null = null;
  private pickingWarmupStage: 0 | 1 | 2 = 0;
  private initializedEventSources = new Set<string>();
  private observedEventIds = new Set<string>();
  private hazardPulseTime = Date.now();
  private readonly eventFirstSeenAt = new Map<string, number>();
  private receivedInitialEventSnapshot = false;
  private pulseEvents: GeoEvent[] = [];
  private aviationMotionAvailable = false;
  private pulseWasActive = false;
  /**
   * Aviation has a different invalidation cadence from hazards: route geometry,
   * hubs and live positions are static between data/camera changes, while only
   * the small motion subset changes during an animation frame.
   */
  private aviationLayerSections: AviationStaticLayerSections | null = null;
  private aviationDynamicLayers: LayersList | null = null;
  private seededAircraftPickPoints: AviationMotionPoint[] = [];
  private manualAviationEvent: GeoEvent | null = null;
  private manualAviationTooltip: RendererTooltip | null = null;
  private basemapStyleGeneration = 0;
  private readonly quarantinedLayerIds = new Set<string>();
  private readonly quarantinedLayerData = new Map<string, string>();
  private eventVersion = 0;
  private readonly inputFingerprints = new Map<string, {version: string; value: string}>();
  private performanceHarnessHost: MapPerformanceHarnessHost | null = null;

  constructor() {
    const requestFrame = (callback: FrameRequestCallback) => typeof requestAnimationFrame === 'function'
      ? requestAnimationFrame(callback)
      : setTimeout(() => callback(performance.now()), 0) as unknown as number;
    const cancelFrame = (handle: number) => typeof cancelAnimationFrame === 'function'
      ? cancelAnimationFrame(handle)
      : clearTimeout(handle);
    this.renderScheduler = new MapRenderScheduler(
      requestFrame,
      cancelFrame,
      (invalidation) => this.flushRender(invalidation),
    );
    this.heavyGeometryCommit = new DeferredLatestCommit(
      scheduleAfterMainThreadYield,
      ({ events, selectedEventId, zoom, beforeId, viewport, generation }) => {
        if (this.destroyed || this.paused || generation !== this.geometryGeneration) return;
        this.geometryLayers = this.performanceMonitor.measure(
          'js-build',
          () => createWorldEventGeometryLayers(events, selectedEventId, zoom, beforeId, viewport, this.geometryCache),
        );
        this.geometryNeedsCommit = false;
        // A concurrent aircraft tick may share this RAF. Mark the static
        // commit explicitly so that tick cannot bypass freshly built geometry.
        this.requestRender({ interaction: true });
      },
    );
    this.aviationLayerCommit = new DeferredLatestCommit(
      scheduleAfterMainThreadYield,
      (layers) => {
        if (this.destroyed || this.paused || this.interacting || !layers.length) return;
        const overlay = this.ensureAviationOverlay();
        if (!overlay) return;
        this.resumeAviationOverlayViewSync();
        this.performanceMonitor.measure('dynamic-commit', () => {
          overlay.setProps({ layers });
        });
        this.resumeAviationDeckLoop();
      },
    );
  }

  setLanguage(language: 'en' | 'zh') {
    if (this.language === language) return;
    this.language = language;
    this.labelWidths.clear();
    this.basemapLabelBoxes = null;
    if (this.map) reinforceWorldEventBasemapLabels(this.map, language);
    this.requestRender({ points: true });
  }

  async mount(container: HTMLElement, callbacks: MapRendererCallbacks) {
    if (this.map) return;
    this.destroyed = false;
    this.callbacks = callbacks;
    this.manualAviationTooltip = new RendererTooltip(container);
    this.emitBasemapState('initializing');
    const state = this.state;
    const primaryStyle = await getWeatherMapStyle(
      state?.basemapTheme ?? 'dark',
      state?.basemapProvider ?? 'auto',
      this.language,
    );
    if (this.destroyed) return;
    // Fonts affect text layout, not the ability to fetch/paint the basemap.
    // Keep this continuation alive for late fonts without blocking MapLibre.
    void loadMapFonts().then(() => {
      if (this.destroyed) return;
      this.mapFontsReady = true;
      this.labelWidths.clear();
      this.basemapLabelBoxes = null;
      this.pointLayers = null;
      this.aviationLayerSections = null;
      this.requestRender({ points: true, aviation: true, dynamic: true });
    });
    const map = new maplibregl.Map({
      container,
      style: primaryStyle,
      center: state ? [state.center.lon, state.center.lat] : [20, 24],
      zoom: state?.zoom ?? 1.25,
      renderWorldCopies: false,
      // Native single-world constraints keep the viewport inside the world on
      // restore, zoom-out, pan and resize (the same policy as WorldMonitor).
      minZoom: -1,
      maxZoom: WORLD_EVENT_MAP_MAX_ZOOM,
      attributionControl: false,
      interactive: true,
      pitchWithRotate: false,
      dragRotate: false,
      touchPitch: false,
      canvasContextAttributes: { powerPreference: 'high-performance' },
    });
    this.map = map;
    if (new URLSearchParams(window.location.search).get('mapPerf') === '1') {
      this.performanceHarnessHost = container as MapPerformanceHarnessHost;
      this.performanceHarnessHost.__polymonitorMapCamera = (center, zoom) => map.jumpTo({center, zoom});
      this.performanceHarnessHost.__polymonitorMapPresentation = members => this.clusterIndex.diagnostics(members);
      this.performanceHarnessHost.__polymonitorLayerFuses = () => [...this.quarantinedLayerIds];
      this.performanceHarnessHost.__polymonitorIsolateLayer = () => {
        const layer = (this.pointLayers as Layer[] | null)?.find(item => item?.id && item.props?.pickable);
        if (layer) this.handleDeckLayerError(new Error('Controlled layer error from mapPerf harness'), layer);
        return layer?.id;
      };
      this.performanceHarnessHost.__polymonitorProjectGeoPoint = (lon, lat, target) => {
        if (target) {
          const overlay = target === 'static' ? this.overlay : this.aviationOverlay;
          const deck = (overlay as unknown as { _deck?: Deck } | null)?._deck;
          const viewport = deck?.getViewports().find(view => view.id === 'maplibre');
          if (!viewport) throw new Error(`${target} overlay viewport is not ready`);
          const [x, y] = viewport.project([lon, lat]);
          return { x: x!, y: y! };
        }
        const point = map.project([lon, lat]);
        return { x: point.x, y: point.y };
      };
    }
    this.countryHoverQueryController = createCountryHoverQueryController(
      (callback) => window.requestAnimationFrame(callback),
      (handle) => window.cancelAnimationFrame(handle),
      (point) => this.runCountryHoverQuery(point),
    );

    const getTooltip = (info: PickingInfo<WorldEventPickedObject>) => {
      if (this.manualAviationEvent) return null;
      this.manualAviationTooltip?.show(worldEventTooltipModel(info.object, info.layer?.id || '', this.language), { x: info.x, y: info.y });
      return null;
    };
    const getCursor = ({ isDragging, isHovering }: { isDragging: boolean; isHovering: boolean }) => {
      if (isDragging) return 'grabbing';
      return isHovering || Boolean(this.hoveredCountryIso2) ? 'pointer' : 'grab';
    };
    const onClick = (info: PickingInfo<WorldEventPickedObject>) => {
        const candidates = this.clusterIndex.hitSelection({ x: info.x, y: info.y }, coordinate => map.project(coordinate), matchMedia('(pointer: coarse)').matches);
        if (candidates) { callbacks.onClusterSelect?.(candidates); return; }
        const cluster = pickedWorldEventCluster(info.object);
        if (cluster) {
          const [west, south, east, north] = cluster.bounds;
          const expansion = clampWorldEventZoom(cluster.expansionZoom);
          if (cluster.mixed || (west === east && south === north) || expansion <= map.getZoom() || map.getZoom() >= WORLD_EVENT_MAP_MAX_ZOOM) {
            callbacks.onClusterSelect?.(this.clusterIndex.selection(cluster));
          } else {
            map.fitBounds([[west, south], [east, north]], {
              padding: 70, maxZoom: expansion, duration: this.reducedMotion ? 0 : 350,
            });
          }
          return;
        }
        const picked = pickedWorldEvent(info.object);
        callbacks.onEventSelect(picked?.id ?? this.manualAviationEvent?.id ?? null);
    };
    const overlay = new MapLibreOverlay({
      interleaved: true,
      layers: [],
      pickingRadius: typeof matchMedia !== 'undefined' && matchMedia('(pointer: coarse)').matches ? 20 : 11,
      useDevicePixels: true,
      getCursor,
      getTooltip,
      onHover: (info: PickingInfo<WorldEventPickedObject>) => this.handleDeckHover('static', info),
      onClick,
      onError: (error: Error, layer?: Layer) => this.handleDeckLayerError(error, layer),
    });
    this.overlay = overlay;
    // Like WorldMonitor, attach Deck with the map, before optional radar and
    // country sources can delay MapLibre's aggregate `load` event. A cached
    // basemap may report ready first; its picking check must find a mounted
    // overlay rather than incorrectly demoting that healthy map to SVG.
    this.mountOverlaysIfNeeded();

    map.once('load', () => {
      if (this.destroyed) return;
      this.mountOverlaysIfNeeded();
      this.emitViewport();
      reinforceWorldEventBasemapLabels(map, this.language);
      this.ensureCountryHoverLayers();
      if (this.fallbackApplied) {
        if (!this.markLocalFallbackReadyIfLoaded()) this.scheduleFallbackSourceTimeout();
      } else {
        this.markPrimaryReady();
      }
      this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
      this.syncAnimationLoop();
      });
    map.on('style.load', this.handleStyleLoad);
    map.on('sourcedata', this.handleSourceData);
    map.on('idle', this.handleBasemapIdle);
    map.on('moveend', this.handleMoveEnd);
    map.on('movestart', this.handleMoveStart);
    map.on('mousemove', this.handleCountryHoverMove);
    map.on('click', this.handleManualAviationClick);
    map.on('click', this.handleCountryClick);
    map.on('contextmenu', this.handleCountryContextMenu);
    map.on('mouseout', this.handleCountryHoverLeave);
    map.on('error', this.handleMapError);
    map.getCanvas().addEventListener('webglcontextlost', this.handleContextLost);
    map.getCanvas().addEventListener('webglcontextrestored', this.handleContextRestored);
    map.getCanvas().addEventListener('mousedown', this.handlePointerDown, { capture: true });
    window.addEventListener('mouseup', this.handlePointerUp, { capture: true });

    // Camera fitting only needs the container, not loaded tiles or optional
    // radar/country sources. Their pending requests can hold `load` indefinitely.
    if (this.state?.fitWorld) this.fitWorld();
    else this.handleMoveEnd(); // Publish any constraint applied to an old URL camera.

    this.schedulePrimaryDeadline();
  }

  setState(state: WorldEventMapState) {
    const previous = this.state;
    this.state = state;
    if (previous && (previous.basemapProvider !== state.basemapProvider
      || previous.basemapTheme !== state.basemapTheme)) {
      void this.replaceBasemapStyle(state);
    }
    if (!previous || previous.selectedEventId !== state.selectedEventId) {
      this.pulseEvents = selectEventPulseCandidates(this.events, state.selectedEventId);
    }
    const map = this.map;
    if (map && !state.fitWorld && (!previous
      || Math.abs(previous.center.lon - state.center.lon) > 0.0001
      || Math.abs(previous.center.lat - state.center.lat) > 0.0001
      || Math.abs(previous.zoom - state.zoom) > 0.001)) {
      const current = map.getCenter();
      if (Math.abs(current.lng - state.center.lon) > 0.0001
        || Math.abs(current.lat - state.center.lat) > 0.0001
        || Math.abs(map.getZoom() - state.zoom) > 0.001) {
        this.applyingCamera = true;
        map.easeTo({
          center: [state.center.lon, state.center.lat],
          zoom: state.zoom,
          duration: this.reducedMotion ? 0 : 260,
          essential: false,
        });
      }
    }
    if (map && state.fitWorld && !previous?.fitWorld) this.fitWorld();
    if (map && state.selectedEventId && previous?.selectedEventId !== state.selectedEventId) {
      const event = this.events.find(item => item.id === state.selectedEventId);
      const coordinate = event ? eventRepresentativePoint(event) : null;
      const host = map.getContainer?.();
      if (coordinate && host) {
        const { x: dx, y: dy } = selectionPanOffset(host, map.project(coordinate), this.occupiedScreenBoxes);
        if (Math.abs(dx) > 1 || Math.abs(dy) > 1) map.panBy([dx, dy], { duration: this.reducedMotion ? 0 : 280 });
      }
    }
    const staticLayersChanged = !previous
      || previous.presentationMode !== state.presentationMode
      || previous.zoom !== state.zoom
      || previous.selectedEventId !== state.selectedEventId
      || previous.timeRange !== state.timeRange
      || previous.severities.join(',') !== state.severities.join(',')
      || previous.activeLayerIds.join(',') !== state.activeLayerIds.join(',');
    const aviationLayersChanged = !previous
      || previous.zoom !== state.zoom
      || previous.selectedEventId !== state.selectedEventId
      || previous.activeLayerIds.join(',') !== state.activeLayerIds.join(',')
      || previous.aviationLens !== state.aviationLens
      || previous.aviationRiskSource !== state.aviationRiskSource;
    if (staticLayersChanged) this.pointLayers = null;
    if (aviationLayersChanged) this.aviationLayerSections = null;
    if (aviationLayersChanged) this.aviationDynamicLayers = null;
    const geometryChanged = !previous
      || previous.zoom !== state.zoom
      || previous.selectedEventId !== state.selectedEventId
      || previous.timeRange !== state.timeRange
      || previous.severities.join(',') !== state.severities.join(',')
      || previous.activeLayerIds.join(',') !== state.activeLayerIds.join(',');
    if (geometryChanged) this.invalidateGeometry();
    this.requestRender({
      points: staticLayersChanged,
      aviation: aviationLayersChanged,
      geometry: geometryChanged,
      dynamic: aviationLayersChanged,
      pulse: previous?.selectedEventId !== state.selectedEventId,
      interaction: previous?.selectedEventId !== state.selectedEventId,
    });
    this.syncAnimationLoop();
  }

  setEvents(events: GeoEvent[]) {
    if (events === this.events) return;
    const previousEvents = this.events;
    const nonAviationChanged = !sameEventReferences(previousEvents, events, (event) => !isAviationEvent(event));
    const aviationChanged = !sameEventReferences(previousEvents, events, isAviationEvent);
    const geometryChanged = !sameEventReferences(previousEvents, events, isGeometryEvent);
    if (!nonAviationChanged && !aviationChanged) {
      this.events = events;
      return;
    }
    const previousIds = new Set(previousEvents.map((event) => event.id));
    const now = Date.now();
    if (this.receivedInitialEventSnapshot) {
      for (const event of events) {
        const occurred = Date.parse(event.occurredAt || event.updatedAt || '');
        if (event.sources.some(source => this.initializedEventSources.has(source.provider))
          && !previousIds.has(event.id) && !this.observedEventIds.has(event.id)
          && occurred <= now && now - occurred <= 6_000) this.eventFirstSeenAt.set(event.id, now);
      }
    } else if (events.length > 0) {
      this.receivedInitialEventSnapshot = true;
    }
    events.forEach(event => { this.observedEventIds.add(event.id); event.sources.forEach(source => this.initializedEventSources.add(source.provider)); });
    const nextIds = new Set(events.map((event) => event.id));
    for (const eventId of this.eventFirstSeenAt.keys()) {
      if (!nextIds.has(eventId)) this.eventFirstSeenAt.delete(eventId);
    }
    this.events = events;
    this.eventsById = new Map(events.map(event => [event.id, event]));
    this.aviationMotionAvailable = events.some(event => event.category === 'infrastructure'
      && (event.properties.mapEntity === 'air-route' || event.properties.mapEntity === 'air-flight'));
    this.eventVersion++;
    this.clusterIndex.update(events);
    if (nonAviationChanged) {
      this.pulseEvents = selectEventPulseCandidates(events, this.state?.selectedEventId || null);
      this.pointLayers = null;
      if (geometryChanged) this.invalidateGeometry();
    }
    if (aviationChanged) {
      this.aviationLayerSections = null;
      this.aviationDynamicLayers = null;
    }
    this.requestRender({
      points: nonAviationChanged,
      aviation: aviationChanged,
      geometry: geometryChanged,
      dynamic: aviationChanged,
      pulse: nonAviationChanged,
      interaction: true,
    });
    this.syncAnimationLoop();
  }

  private viewportRevision = 0;
  private emitViewport() {
    const map = this.map; if (!map || this.destroyed) return;
    const b = map.getBounds(), c = map.getCenter(), host = map.getContainer();
    this.callbacks?.onViewportChange?.({ revision: ++this.viewportRevision,
      bounds: splitViewportBounds(b.getWest(), b.getSouth(), b.getEast(), b.getNorth()),
      center: [c.lng, c.lat], zoom: map.getZoom(), widthCssPx: host.clientWidth, heightCssPx: host.clientHeight });
  }
  resize() { this.basemapLabelBoxes = null; this.map?.resize(); this.emitViewport(); }

  setReducedMotion(reduced: boolean) {
    this.reducedMotion = reduced;
    this.syncAnimationLoop();
    this.requestRender({ dynamic: true, pulse: true });
  }

  private fitWorld() {
    this.fittingWorld = true;
    // Start from the populated world; native constraints enlarge/clamp this
    // camera to cover the canvas rather than expose space outside the world.
    this.map?.fitBounds([[-180, -56], [180, 72]], { padding: 24, maxZoom: 3, duration: this.reducedMotion ? 0 : 350 });
  }

  setOcclusions(boxes: ScreenBox[]) {
    this.occupiedScreenBoxes = boxes;
    this.manualAviationTooltip?.setOcclusions(boxes);
    this.pointLayers = null;
    this.renderScheduler.request({ points: true });
    const event = this.events.find(e => e.id === this.state?.selectedEventId);
    const coordinate = event && eventRepresentativePoint(event);
    if (coordinate && this.map && !this.interacting) {
      const offset = selectionPanOffset(this.map.getContainer(), this.map.project(coordinate), boxes);
      if (Math.abs(offset.x) > 1 || Math.abs(offset.y) > 1) this.map.panBy([offset.x, offset.y], { duration: this.reducedMotion ? 0 : 180 });
    }
  }
  setHoveredEvent(eventId: string | null) {
    this.hoveredDeckEventId = eventId;
    this.renderScheduler.request({ interaction: true });
  }

  fitCountry(country: MapCountryTarget) {
    this.map?.fitBounds(country.bounds, {
      padding: 64,
      maxZoom: 5.5,
      duration: this.reducedMotion ? 0 : 480,
    });
  }

  pause() {
    if (this.paused) return;
    this.paused = true;
    this.applyRadar();
    this.clearAllHover();
    this.cancelAnimationLoop();
    this.cancelAnimationResume();
    this.cancelPickingWarmup?.();
    this.cancelPickingWarmup = null;
    this.cancelStagedAviationCommit();
    this.renderScheduler.cancel();
    this.heavyGeometryCommit.cancel();
    this.geometryNeedsCommit = true;
    // Removing layers finalizes their instances. Keep the last committed
    // scene attached while clocks/commits are suspended, as WorldMonitor does.
    // In particular, cached geometry must survive until its yielded rebuild.
    this.pauseAviationOverlayViewSync();
  }

  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.applyRadar();
    this.scheduleMissingTileRecovery();
    this.resize();
    this.resumeAviationOverlayViewSync();
    this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
    this.syncAnimationLoop();
  }

  destroy() {
    this.interactionCache = null;
    this.labelWidths.clear();
    this.destroyed = true;
    this.readinessCancel?.();
    if (this.missingTileRetryTimer != null) window.clearTimeout(this.missingTileRetryTimer);
    this.basemapStyleGeneration += 1;
    this.clearFallbackTimer();
    this.clearFallbackSourceTimer();
    if (this.radarRetryTimer != null) window.clearTimeout(this.radarRetryTimer);
    if (this.primaryRecoveryTimer != null) window.clearTimeout(this.primaryRecoveryTimer);
    this.clearContextRecoveryTimer();
    this.cancelAnimationLoop();
    this.cancelAnimationResume();
    this.cancelPickingWarmup?.();
    this.cancelPickingWarmup = null;
    this.cancelStagedAviationCommit();
    this.renderScheduler.cancel();
    this.heavyGeometryCommit.cancel();
    this.performanceMonitor.destroy();
    this.manualAviationTooltip?.destroy();
    this.manualAviationTooltip = null;
    this.countryHoverQueryController?.cancel();
    this.clearAllHover();
    if (this.performanceHarnessHost) {
      delete this.performanceHarnessHost.__polymonitorMapCamera;
      delete this.performanceHarnessHost.__polymonitorProjectGeoPoint;
      delete this.performanceHarnessHost.__polymonitorMapPresentation;
      delete this.performanceHarnessHost.__polymonitorIsolateLayer;
      delete this.performanceHarnessHost.__polymonitorLayerFuses;
      this.performanceHarnessHost = null;
    }
    const map = this.map;
    if (map) {
      map.off('style.load', this.handleStyleLoad);
      map.off('sourcedata', this.handleSourceData);
      map.off('idle', this.handleBasemapIdle);
      map.off('moveend', this.handleMoveEnd);
      map.off('movestart', this.handleMoveStart);
      map.off('mousemove', this.handleCountryHoverMove);
      map.off('click', this.handleManualAviationClick);
      map.off('click', this.handleCountryClick);
      map.off('contextmenu', this.handleCountryContextMenu);
      map.off('mouseout', this.handleCountryHoverLeave);
      map.off('error', this.handleMapError);
      map.getCanvas().removeEventListener('webglcontextlost', this.handleContextLost);
      map.getCanvas().removeEventListener('webglcontextrestored', this.handleContextRestored);
      map.getCanvas().removeEventListener('mousedown', this.handlePointerDown, { capture: true });
      window.removeEventListener('mouseup', this.handlePointerUp, { capture: true });
      if (this.overlay) {
        try {
          map.removeControl(this.overlay);
        } catch {
          // MapLibre may already be tearing the style down.
        }
      }
      if (this.aviationOverlay) {
        if (this.aviationOverlayViewSync) {
          map.off('render', this.aviationOverlayViewSync);
        }
        try {
          map.removeControl(this.aviationOverlay);
        } catch {
          // MapLibre may already be tearing the style down.
        }
      }
      map.remove();
    }
    this.map = null;
    this.overlay = null;
    this.aviationOverlay = null;
    this.pointLayers = null;
    this.geometryLayers = [];
    this.geometryCache.clear();
    this.eventsById.clear();
    this.aviationLayerSections = null;
    this.aviationDynamicLayers = null;
    this.seededAircraftPickPoints = [];
    this.manualAviationEvent = null;
    this.fallbackCountryLabels = [];
    this.fallbackCountryLabelsLoading = null;
    this.overlayMounted = false;
    this.aviationOverlayMounted = false;
    this.aviationOverlayViewSync = null;
    this.aviationOverlayViewSyncPaused = false;
    this.countryHoverQueryController = null;
    this.staticDeckHoverActive = false;
    this.aviationDeckHoverActive = false;
    this.deckHoverActive = false;
    this.hoveredDeckEventId = null;
    this.hoveredCountryIso2 = null;
    this.callbacks = null;
    this.quarantinedLayerIds.clear();
    if (this.contextStableTimer != null) window.clearTimeout(this.contextStableTimer);
  }

  private requestRender(invalidation: Partial<MapRenderInvalidation> = {}) {
    // Interaction start clears hover state. That cleanup used to enqueue a
    // fresh dynamic deck commit after beginMapInteraction() had cancelled the
    // pending frame, so the supposedly paused aviation canvas still paid a
    // full GPU draw on the first drag frame. All invalidated caches remain on
    // the renderer and are committed once pointerup/moveend resumes it.
    if (this.destroyed || this.paused || this.interacting || !this.overlay || !this.state) return;
    this.renderScheduler.request(invalidation);
  }

  private invalidateGeometry() {
    this.geometryGeneration += 1;
    this.geometryNeedsCommit = true;
  }

  private flushRender(invalidation: MapRenderInvalidation) {
    if (this.paused || !this.overlay || !this.state) return;
    if (invalidation.dynamic && !invalidation.points && !invalidation.geometry
      && !invalidation.aviation && !invalidation.pulse && !invalidation.interaction
      && this.aviationLayerSections && this.aviationOverlay) {
      const layers = this.performanceMonitor.measure('dynamic-build', () => createAviationDynamicLayers(
        this.aviationLayerSections!.data, this.animationTime, this.state!.zoom,
        this.state!.selectedEventId, this.hoveredDeckEventId,
      )).filter((layer): layer is Layer => Boolean(layer) && !Array.isArray(layer))
        .filter(layer => (this.mapFontsReady || !(layer instanceof TextLayer)) && this.acceptLayerVersion(layer));
      this.aviationDynamicLayers = layers;
      const aircraft = layers.find(layer => layer.id === 'aviation-seeded-aircraft');
      this.seededAircraftPickPoints = Array.isArray(aircraft?.props.data) ? aircraft.props.data as AviationMotionPoint[] : [];
      this.performanceMonitor.measure('dynamic-commit', () => this.aviationOverlay!.setProps({ layers }));
      return;
    }
    const bounds = this.map?.getBounds();
    const viewport: [number, number, number, number] | undefined = bounds
      ? bounds.getWest() <= bounds.getEast()
        ? [
            Math.max(-180, bounds.getWest() - 8),
            Math.max(-85, bounds.getSouth() - 5),
            Math.min(180, bounds.getEast() + 8),
            Math.min(85, bounds.getNorth() + 5),
          ]
        : [-180, -85, 180, 85]
      : undefined;
    if ((invalidation.points || !this.pointLayers)) {
      const map = this.map;
      const project = map
        ? (position: [number, number]) => {
            const point = map.project(position);
            return Number.isFinite(point.x) && Number.isFinite(point.y) ? { x: point.x, y: point.y } : null;
          }
        : undefined;
      const occupiedScreenBoxes = [...this.occupiedScreenBoxes];
      const measureContext = this.labelMeasureContext;
      const measureLabel = (text: string, size: number) => {
        if (!measureContext) return 220;
        const font = `500 ${size}px ${mapLabelFontFamily()}`;
        const key = `${font}:${text}`;
        const previous = this.labelWidths.get(key);
        if (previous != null) return previous;
        measureContext.font = font;
        const width = measureContext.measureText(text).width;
        if (this.labelWidths.size >= 2048) this.labelWidths.delete(this.labelWidths.keys().next().value!);
        this.labelWidths.set(key, width);
        return width;
      };
      const host = map?.getContainer?.();
      if (map && this.basemapLabelBoxes == null) {
        const labelStarted = performance.now();
        const boxes: ScreenBox[] = [];
        try {
          const symbolLayerIds = (map.getStyle()?.layers || [])
            .filter((layer) => layer.type === 'symbol')
            .map((layer) => layer.id);
          const visibleLabels = symbolLayerIds.length
            ? map.queryRenderedFeatures(undefined, { layers: symbolLayerIds })
            : [];
          for (const feature of visibleLabels.slice(0, 500)) {
            if (feature.geometry?.type !== 'Point') continue;
            const coordinates = feature.geometry.coordinates as [number, number];
            const screen = project?.(coordinates);
            if (!screen) continue;
            const properties = feature.properties || {};
            const evaluated = (map as unknown as { style?: { getLayer: (id: string) => { getValueAndResolveTokens?: (name: string, feature: unknown, canonical: unknown, images: string[]) => unknown; layout?: {get: (name: string) => {evaluate?: (feature: unknown, state: object) => unknown}} } } }).style?.getLayer(feature.layer.id);
            const formatted = evaluated?.getValueAndResolveTokens?.('text-field', feature, undefined, []);
            const text = formatted != null ? String(formatted) : String(this.language === 'zh' ? properties['name:zh'] || properties.name_zh || properties['name:zh-Hans'] || properties.name || properties.name_en || '' : properties.name_en || properties['name:en'] || properties.name || properties.name_int || '');
            if (!text) continue;
            const size = Number(evaluated?.layout?.get('text-size')?.evaluate?.(feature, {}) ?? map.getLayoutProperty(feature.layer.id, 'text-size'));
            const fontSize = Number.isFinite(size) ? size : feature.layer.id.includes('country') ? 13 : 11;
            const width = measureLabel(text, fontSize);
            boxes.push([
              screen.x - width / 2, screen.y - fontSize / 2 - 3, screen.x + width / 2, screen.y + fontSize / 2 + 3,
            ]);
          }
          this.basemapLabelBoxes = boxes;
        } catch {
          // A basemap may be mid-style-reload; event labels are recomputed on
          // the next style/data render without blocking the map.
        }
        this.performanceMonitor.record('label-layout', performance.now() - labelStarted);
      }
      occupiedScreenBoxes.push(...(this.basemapLabelBoxes || []));
      this.pointLayers = this.performanceMonitor.measure(
        'js-build',
        () => createWorldEventPointLayers(
          this.events,
          this.state!,
          viewport,
          this.clusterIndex,
          project,
          occupiedScreenBoxes,
          measureLabel,
          host ? [host.clientWidth, host.clientHeight] : undefined,
        ),
      );
    }
    if (invalidation.points && bounds) {
      const actualViewport: [number, number, number, number] = [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()];
      this.callbacks?.onPresentationChange?.(mapPresentationCounts(this.events,
        this.clusterIndex.lastPresentation || this.clusterIndex.query(this.state.zoom, this.state.selectedEventId, viewport), actualViewport, this.state.zoom));
    }
    if (invalidation.geometry || this.geometryNeedsCommit) {
      this.heavyGeometryCommit.stage({
        events: this.events,
        selectedEventId: this.state.selectedEventId,
        zoom: this.state.zoom,
        beforeId: this.map?.getStyle()?.layers?.find((layer) => layer.id.startsWith('boundaries') || layer.type === 'symbol')?.id,
        viewport,
        generation: this.geometryGeneration,
      });
    }
    const aviationActive = this.state.activeLayerIds.includes('air-routes');
    if (!aviationActive) this.aviationLayerSections = null;
    else if (invalidation.aviation || !this.aviationLayerSections) {
      this.aviationLayerSections = this.performanceMonitor.measure(
        'js-build',
        () => createAviationStaticLayerSections(this.events, this.state!, viewport),
      );
    }
    const aviationSections = this.aviationLayerSections;
    const onlyDynamic = (invalidation.dynamic || invalidation.pulse || invalidation.interaction)
      && !invalidation.points
      && !invalidation.aviation
      && !invalidation.geometry;
    const aviationDynamicChanged = invalidation.aviation
      || invalidation.dynamic
      || invalidation.pulse
      || invalidation.interaction
      || this.aviationDynamicLayers == null;
    if (aviationDynamicChanged) {
      this.aviationDynamicLayers = aviationSections
        ? this.performanceMonitor.measure(
          onlyDynamic ? 'dynamic-build' : 'js-build',
          () => createAviationDynamicLayers(
            aviationSections.data,
            this.animationTime,
            this.state!.zoom,
            this.state!.selectedEventId,
            this.hoveredDeckEventId,
          ),
        )
        : [];
    }
    const aviationDynamicLayers = this.aviationDynamicLayers || [];
    const pointLayerList = (this.pointLayers || []).filter(
      (layer): layer is Layer => Boolean(layer) && !Array.isArray(layer),
    ).filter((layer) => this.acceptLayerVersion(layer));
    const aviationDynamicLayerList = aviationDynamicLayers.filter(
      (layer): layer is Layer => Boolean(layer) && !Array.isArray(layer),
    ).filter((layer) => this.acceptLayerVersion(layer));
    const pointLabels = pointLayerList.filter((layer) => (
      layer?.id === 'world-event-labels' || layer?.id === 'world-event-cluster-counts'
    ));
    const pointBaseLayers = pointLayerList.filter((layer) => !pointLabels.includes(layer));
    const routeRunnerLayers = aviationDynamicLayerList.filter((layer) => layer.id === 'aviation-route-runners');
    const seededAircraftLayers = aviationDynamicLayerList.filter((layer) => layer.id === 'aviation-seeded-aircraft');
    const seededAircraftLayer = seededAircraftLayers[0];
    this.seededAircraftPickPoints = Array.isArray(seededAircraftLayer?.props.data)
      ? seededAircraftLayer.props.data as AviationMotionPoint[]
      : [];
    const seededInteractionLayers = aviationDynamicLayerList.filter((layer) => (
      layer.id.startsWith('aviation-seeded-hover-') || layer.id.startsWith('aviation-seeded-selected-')
    ));
    const aviationCountLabels = this.mapFontsReady ? aviationDynamicLayerList.filter((layer) => layer.id.endsWith('-counts')) : [];
    const pulseLayers = this.reducedMotion
      ? []
      : createEventPulseLayers({
        events: this.pulseEvents,
        selectedEventId: this.state.selectedEventId,
        firstSeenAt: this.eventFirstSeenAt,
        pulseTime: this.hazardPulseTime,
        zoom: this.state.zoom,
      });
    const interaction = this.interactionCache;
    const selected = this.eventsById.get(this.state.selectedEventId || '') || null;
    const hovered = this.eventsById.get(this.hoveredDeckEventId || '') || null;
    if (!interaction || interaction.selected !== selected
      || interaction.hovered !== hovered || interaction.cluster !== this.hoveredDeckCluster) {
      this.interactionCache = { selected, hovered, cluster: this.hoveredDeckCluster,
        layers: createEventInteractionLayers([selected, hovered].filter((event): event is GeoEvent => Boolean(event)), this.state.selectedEventId,
          this.hoveredDeckEventId, this.hoveredDeckCluster) };
    }
    const interactionLayers = this.interactionCache!.layers;
    const staticBaseLayers = [
      ...this.geometryLayers.filter(
        (layer): layer is Layer => Boolean(layer) && !Array.isArray(layer),
      ).filter((layer) => this.acceptLayerVersion(layer)),
      ...(aviationSections?.routeLayers || []),
      ...pointBaseLayers,
      // Keep genuinely static aviation objects and text out of the animation
      // canvas. Drawing hubs, live snapshots and every label at 25 fps made a
      // small runner update repaint hundreds of unchanged glyphs.
      ...(aviationSections?.hubLayers || []),
      ...(aviationSections?.aircraftLayers || []),
    ];
    // Do not initialize deck's font atlas with a temporary browser fallback:
    // its atlas cache would otherwise survive the later font download.
    const staticLabelLayers = (this.mapFontsReady ? [
      ...this.createFallbackCountryLabelLayers(),
      ...pointLabels,
      ...(aviationSections?.labelLayers || []),
    ] : []).filter((layer): layer is Layer => Boolean(layer) && !Array.isArray(layer))
      .filter((layer) => this.acceptLayerVersion(layer));
    const aviationMotionLayers = [
      ...routeRunnerLayers,
      ...seededAircraftLayers,
      ...seededInteractionLayers,
      ...aviationCountLabels,
    ];
    const staticCompleteLayers = [
      ...staticBaseLayers,
      ...pulseLayers,
      ...interactionLayers,
      ...staticLabelLayers,
    ];
    if (!onlyDynamic) {
      // Commit each static layer instance exactly once. The former two-step
      // base/label path first removed the previous label layers (which makes
      // deck.gl finalize them) and then reinserted the same cached instances
      // after yielding. Layer._initialize correctly rejects that finalized
      // instance reuse, leaving cluster counts and aviation labels missing.
      // Heavy polygon work still uses the independent latest-only yielded
      // geometry commit above; static labels are small enough for one atomic
      // deck commit and must remain attached across updates.
      this.suspendAviationDeckLoop();
      this.performanceMonitor.measure('deck-commit', () => {
        this.overlay?.setProps({ layers: staticCompleteLayers });
      });
    } else if (invalidation.pulse || invalidation.interaction) {
      // Hazard pulses and hover state belong to the static renderer. Aircraft
      // ticks therefore no longer repaint the labelled map canvas.
      this.performanceMonitor.measure('deck-commit', () => {
        this.overlay?.setProps({ layers: staticCompleteLayers });
      });
    }
    if (aviationActive && aviationMotionLayers.length) {
      this.ensureAviationOverlay();
      if (onlyDynamic && !invalidation.pulse && !invalidation.interaction && this.aviationOverlay) {
        this.performanceMonitor.measure('dynamic-commit', () => {
          this.aviationOverlay?.setProps({ layers: aviationMotionLayers });
        });
      } else {
        // WorldMonitor-style latest commit: yield once, discard superseded
        // payloads, and never sleep for a fixed 900ms.
        this.aviationLayerCommit.stage(aviationMotionLayers);
      }
    } else {
      this.removeAviationOverlay();
    }
    if (!onlyDynamic) {
      this.map?.triggerRepaint();
      this.schedulePickingWarmup();
    }
  }

  /**
   * deck.gl compiles its picking passes on first use. Paying that cost on the
   * user's first hover or drag creates a visible one-off stall, so warm the two
   * canvases in separate yielded tasks after their first real layer commit.
   */
  private schedulePickingWarmup() {
    if (this.pickingWarmupStage === 2 || this.cancelPickingWarmup || this.interacting
      || this.paused || this.destroyed || !this.overlay) return;
    this.cancelPickingWarmup = scheduleAfterMainThreadYield(() => {
      this.cancelPickingWarmup = null;
      if (this.interacting || this.paused || this.destroyed) return;
      if (this.warmOverlayPicking(this.overlay)) {
        // The motion overlay is deliberately non-pickable; animated aircraft
        // use the renderer's bounded CPU hit test. Warming a second GPU picking
        // pass only wakes both Deck loops during first paint.
        this.pickingWarmupStage = 2;
      } else {
        // A context may still be initializing. A later static commit retries.
        return;
      }
    });
  }

  private warmOverlayPicking(overlay: MapLibreOverlay | null) {
    if (!overlay) return false;
    const deck = (overlay as unknown as { _deck?: { isInitialized?: boolean } })._deck;
    const canvas = overlay.getCanvas();
    if (!deck?.isInitialized || !canvas?.clientWidth || !canvas.clientHeight) return false;
    try {
      overlay.pickObject({
        x: Math.round(canvas.clientWidth / 2),
        y: Math.round(canvas.clientHeight / 2),
        radius: 1,
      });
      return true;
    } catch {
      return false;
    }
  }

  private fittingWorld = false;
  private handleMoveEnd = () => {
    const map = this.map;
    if (!map || !this.callbacks) return;
    // Initial resize emits moveend before load; it must not consume the fit
    // request and persist the constructor's provisional camera.
    if (this.state?.fitWorld && !this.fittingWorld) return;
    this.fittingWorld = false;
    this.basemapLabelBoxes = null;
    this.emitViewport();
    const zoomChanged = Math.abs(map.getZoom() - (this.state?.zoom ?? map.getZoom())) > 0.001;
    this.mapDragging = false;
    this.interacting = false;
    if (!zoomChanged) this.resumeAviationOverlayViewSync();
    this.pointLayers = null;
    if (zoomChanged) {
      this.aviationLayerSections = null;
      this.aviationDynamicLayers = null;
    }
    this.invalidateGeometry();
    this.requestRender({ points: true, aviation: zoomChanged, geometry: true, dynamic: zoomChanged });
    this.scheduleAnimationResume();
    const center = map.getCenter();
    const camera = { center: { lon: center.lng, lat: center.lat }, zoom: map.getZoom() };
    if (this.applyingCamera) {
      this.applyingCamera = false;
      const state = this.state;
      if (state
        && Math.abs(state.center.lon - camera.center.lon) < 0.0001
        && Math.abs(state.center.lat - camera.center.lat) < 0.0001
        && Math.abs(state.zoom - camera.zoom) < 0.001) return;
    }
    this.callbacks.onCameraChange(camera);
  };

  private handleMoveStart = () => {
    this.mapDragging = true;
    this.clearAllHover();
    this.beginMapInteraction();
  };

  private handlePointerDown = () => {
    this.beginMapInteraction();
  };

  private handlePointerUp = () => {
    window.requestAnimationFrame(() => {
      if (this.destroyed || this.paused || this.mapDragging || !this.interacting) return;
      this.interacting = false;
      this.resumeAviationOverlayViewSync();
      this.requestRender({ dynamic: true, pulse: true, interaction: true });
      this.syncAnimationLoop();
      });
  };

  private beginMapInteraction() {
    if (this.interacting || this.destroyed || this.paused) return;
    this.interacting = true;
    this.cancelAnimationLoop();
    this.cancelAnimationResume();
    // Stop advancing aircraft during interaction, but keep their last observed
    // positions attached to the moving camera. The native view sync redraws
    // only when MapLibre renders; there is no independent motion loop.
    this.renderScheduler.cancel();
    this.cancelStagedAviationCommit();
    this.pauseAviationOverlayViewSync();
    this.countryHoverQueryController?.cancel();
    // Preserve the picked entity across mousedown -> click. Clearing it here
    // races Deck picking and lets the underlying country steal the click.
    // A genuine MapLibre move starts by clearing hover in handleMoveStart.
  }

  private handleDeckHover(
    source: 'static' | 'aviation',
    info: PickingInfo<WorldEventPickedObject>,
  ) {
    const previousHoveredEventId = this.hoveredDeckEventId;
    const previousHoveredClusterId = this.hoveredDeckCluster?.id || null;
    if (source === 'static') this.staticDeckHoverActive = Boolean(info.object);
    else this.aviationDeckHoverActive = Boolean(info.object);
    this.deckHoverActive = this.staticDeckHoverActive || this.aviationDeckHoverActive;
    const pickedId = pickedWorldEvent(info.object)?.id || null;
    const pickedCluster = pickedWorldEventCluster(info.object);
    if (pickedCluster) this.hoveredDeckCluster = pickedCluster;
    else if (source === 'static' ? !this.aviationDeckHoverActive : !this.staticDeckHoverActive) {
      this.hoveredDeckCluster = null;
    }
    if (pickedId) this.hoveredDeckEventId = pickedId;
    else if (source === 'static' ? !this.aviationDeckHoverActive : !this.staticDeckHoverActive) {
      this.hoveredDeckEventId = null;
    }
    if (previousHoveredEventId !== this.hoveredDeckEventId
      || previousHoveredClusterId !== (this.hoveredDeckCluster?.id || null)) {
      this.requestRender({ interaction: true });
    }
    this.updateMapCursor();
  }

  private handleCountryHoverMove = (event: MapMouseEvent) => {
    if (this.destroyed || this.paused) return;
    // A static Deck picking readback and an aviation Deck draw in the same RAF
    // serialize on the GPU. Freeze the motion loop while the pointer is active
    // and restart it shortly after pointer traffic becomes idle.
    this.suspendAviationDeckLoop();
    this.cancelAnimationLoop();
    this.scheduleAnimationResume(120);
    this.handleManualAviationHover(event);
    this.countryPointer = event.point;
    this.countryHoverQueryController?.queue(event.point);
  };

  private handleManualAviationHover(event: MapMouseEvent) {
    const map = this.map;
    if (!map || this.interacting || !this.seededAircraftPickPoints.length) {
      this.clearManualAviationHover();
      return;
    }
    let nearest: AviationMotionPoint | null = null;
    let nearestDistance = 12 * 12;
    for (const point of this.seededAircraftPickPoints) {
      const screen = map.project(point.position);
      const dx = screen.x - event.point.x;
      const dy = screen.y - event.point.y;
      const distance = dx * dx + dy * dy;
      if (distance <= nearestDistance) {
        nearest = point;
        nearestDistance = distance;
      }
    }
    if (!nearest) {
      this.clearManualAviationHover();
      return;
    }
    const changed = this.manualAviationEvent?.id !== nearest.event.id;
    this.manualAviationEvent = nearest.event;
    this.aviationDeckHoverActive = true;
    this.deckHoverActive = true;
    this.hoveredDeckEventId = nearest.event.id;
    this.manualAviationTooltip?.show(
      worldEventTooltipModel(nearest.event, 'aviation-seeded-aircraft'),
      { x: event.point.x + 14, y: event.point.y + 14 },
    );
    if (changed) this.requestRender({ interaction: true });
    this.updateMapCursor();
  }

  private handleManualAviationClick = () => {
    if (this.manualAviationEvent) this.callbacks?.onEventSelect(this.manualAviationEvent.id);
  };

  private countryAtPoint(point: MapMouseEvent['point']) {
    const map = this.map;
    if (!map?.getLayer(COUNTRY_INTERACTIVE_LAYER)) return null;
    try {
      const feature = map.queryRenderedFeatures(point, { layers: [COUNTRY_INTERACTIVE_LAYER] })[0];
      return countryTarget(feature as unknown as { properties?: Record<string, unknown>; geometry?: Geometry });
    } catch {
      return null;
    }
  }

  private handleCountryClick = (event: MapMouseEvent) => {
    // MapLibre emits `click` only when its drag tolerance was not exceeded.
    // `mousedown` deliberately marks the renderer as interacting before that
    // click, so checking `this.interacting` here made every genuine country
    // click impossible. Deck/manual aviation ownership is still respected.
    if (this.deckHoverActive || this.manualAviationEvent) return;
    // A fast click (or touch) can precede the next hover frame. Query the actual
    // click position instead of letting the country underneath claim it too.
    try {
      if (this.overlay?.pickObject({ x: event.point.x, y: event.point.y, radius: 8 })?.object) return;
    } catch {
      // Picking is unavailable during context teardown; do not guess a country.
      return;
    }
    const country = this.countryAtPoint(event.point);
    this.callbacks?.onCountrySelect(country, country ? { x: event.point.x, y: event.point.y } : undefined);
  };

  private handleCountryContextMenu = (event: MapMouseEvent) => {
    const country = this.countryAtPoint(event.point);
    if (!country) return;
    event.preventDefault();
    this.callbacks?.onCountryContextMenu(country, { x: event.point.x, y: event.point.y });
  };

  private clearManualAviationHover() {
    if (!this.manualAviationEvent) return;
    const previousId = this.manualAviationEvent.id;
    this.manualAviationEvent = null;
    this.manualAviationTooltip?.clear();
    this.aviationDeckHoverActive = false;
    this.deckHoverActive = this.staticDeckHoverActive;
    if (this.hoveredDeckEventId === previousId && !this.staticDeckHoverActive) {
      this.hoveredDeckEventId = null;
      this.requestRender({ interaction: true });
    }
    this.updateMapCursor();
  }

  private handleCountryHoverLeave = () => {
    this.countryHoverQueryController?.cancel();
    this.clearAllHover();
  };

  private handleStyleLoad = () => {
    this.interactionCache = null;
    this.basemapLabelBoxes = null;
    this.geometryCache.clear();
    if (!this.map || this.destroyed) return;
    // Providers choose their own source IDs (PMTiles uses basemap, whereas
    // OpenFreeMap/CARTO do not). Capture the base style before adding optional
    // country/radar sources so those cannot falsely satisfy map readiness.
    if (!this.fallbackApplied) this.primarySourceIds = new Set(Object.keys(this.map.getStyle().sources || {}));
    if (typeof performance !== 'undefined'
      && performance.getEntriesByName('polymonitor:map:style-ready').length === 0) {
      performance.mark('polymonitor:map:style-ready');
    }
    reinforceWorldEventBasemapLabels(this.map, this.language);
    this.ensureCountryHoverLayers();
    this.radarAppliedUrl = ''; this.radarActiveBank = ''; this.radarPending = null; this.applyRadar();
    if (this.fallbackApplied) this.markLocalFallbackReadyIfLoaded();
    this.invalidateGeometry();
    this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
  };

  private handleSourceData = (event: MapSourceDataEvent) => {
    if (this.primarySourceIds.has(event.sourceId) && event.sourceDataType === 'content') this.basemapLabelBoxes = null;
    if (!this.fallbackApplied && this.primarySourceIds.has(event.sourceId)) {
      if (event.sourceDataType === 'metadata') this.primaryMetadataReady = true;
      // MapLibre considers an errored tile "loaded" too. Metadata/load/idle
      // alone therefore cannot prove that a vector basemap actually painted.
      const tile = (event as MapSourceDataEvent & { tile?: { state?: string; tileID?: {canonical?: {x: number; y: number; z: number}} } }).tile;
      const source = this.map?.getStyle().sources?.[event.sourceId];
      const geoJsonLoaded = source?.type === 'geojson' && event.sourceDataType === 'content' && event.isSourceLoaded;
      if (tile?.state === 'loaded' || geoJsonLoaded) {
        this.primaryHasContent = true;
        const id = tile.tileID?.canonical;
        if (id) this.missingBaseTiles.delete(`${id.z}/${id.x}/${id.y}`);
        if (!this.missingBaseTiles.size) this.callbacks?.onBasemapIssueChange?.(null);
      }
      this.markPrimaryReady();
    }
    if (event.sourceId?.startsWith('weather-radar') && event.isSourceLoaded) this.commitRadarIfReady();
    if (!this.fallbackApplied || event.sourceId !== FALLBACK_COUNTRY_SOURCE) return;
    if (!this.markLocalFallbackReadyIfLoaded()) return;
    this.mountOverlaysIfNeeded();
    this.ensureCountryHoverLayers();
    this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
  };

  private handleBasemapIdle = () => {
    if (this.basemapLabelBoxes == null && !this.paused && !this.interacting) this.requestRender({ points: true });
    // Country GeoJSON may arrive after the pointer stops moving. Re-query
    // once the newly loaded style/source has actually painted.
    if (this.countryPointer && !this.paused && !this.interacting) this.countryHoverQueryController?.queue(this.countryPointer);
    if (!this.map || this.destroyed || this.fallbackApplied || this.fallbackTimer == null) return;
    // `load` only fires for the first style. A user-selected replacement must
    // also cancel its deadline once its sources/tiles have finished loading.
    if (!this.map.isStyleLoaded() || !this.map.areTilesLoaded()) return;
    this.markPrimaryReady();
  };

  private markPrimaryReady() {
    if (!this.primaryHasContent || this.fallbackApplied || !this.map || this.destroyed) return;
    this.clearFallbackTimer();
    if (performance.getEntriesByName('polymonitor:map:first-basemap').length === 0) performance.mark('polymonitor:map:first-basemap');
    this.emitBasemapState('primary-ready');
  }

  private schedulePrimaryDeadline(allowMetadataGrace = true) {
    this.clearFallbackTimer();
    this.fallbackTimer = window.setTimeout(() => {
      this.fallbackTimer = null;
      if (!this.map || this.fallbackApplied || this.destroyed) return;
      if (this.primaryHasContent) { this.markPrimaryReady(); return; }
      // A cold archive can spend most of the first budget acquiring its index.
      // Give its actual vector tiles one additional budget, never optional
      // radar/country data, and never mark metadata alone as a painted map.
      if (allowMetadataGrace && this.primaryMetadataReady) {
        this.schedulePrimaryDeadline(false); return;
      }
      this.applyLocalFallback(new Error('Primary basemap did not paint within its bounded loading deadline.'));
    }, MAP_RENDERER_TIMEOUTS.primary);
  }

  private mountOverlaysIfNeeded() {
    const map = this.map;
    if (!map || this.destroyed) return;
    if (this.overlay && !this.overlayMounted) {
      map.addControl(this.overlay);
      this.overlayMounted = true;
    }
  }

  private ensureAviationOverlay() {
    const map = this.map;
    if (!map || this.destroyed || this.paused || this.interacting) return null;
    if (!this.aviationOverlay) {
      this.aviationOverlay = new MapLibreOverlay({
        interleaved: false,
        layers: [],
        // Only moving aircraft and 2-4px route runners use this canvas. The
        // labelled basemap and all static objects keep their full DPR.
        useDevicePixels: Math.min(2, window.devicePixelRatio),
        onError: (error: Error, layer?: Layer) => this.handleDeckLayerError(error, layer),
      });
      this.aviationDeckSuspended = false;
    }
    if (!this.aviationOverlayMounted) {
      map.addControl(this.aviationOverlay);
      this.aviationOverlayMounted = true;
      const nativeViewSync = (this.aviationOverlay as unknown as {
        _updateViewState?: () => void;
      })._updateViewState || null;
      if (nativeViewSync) {
        map.off('render', nativeViewSync);
        this.aviationOverlayViewSync = () => {
          // Follow camera movement even while the motion clock is stopped.
          if (!this.paused && !this.destroyed) nativeViewSync();
        };
        map.on('render', this.aviationOverlayViewSync);
      }
    }
    return this.aviationOverlay;
  }

  private removeAviationOverlay() {
    this.aviationLayerCommit.cancel();
    this.cancelAnimationLoop();
    this.seededAircraftPickPoints = [];
    this.clearManualAviationHover();
    const overlay = this.aviationOverlay;
    const map = this.map;
    if (map && this.aviationOverlayViewSync) map.off('render', this.aviationOverlayViewSync);
    if (overlay) overlay.setProps({ layers: [] });
    if (map && overlay && this.aviationOverlayMounted) {
      try {
        map.removeControl(overlay);
      } catch {
        // MapLibre may already be replacing its style or tearing down.
      }
    }
    this.aviationOverlay = null;
    this.aviationOverlayMounted = false;
    this.aviationOverlayViewSync = null;
    this.aviationOverlayViewSyncPaused = false;
    this.aviationDeckSuspended = false;
  }

  private pauseAviationOverlayViewSync() {
    this.aviationOverlayViewSyncPaused = true;
    this.suspendAviationDeckLoop();
    const canvas = this.aviationOverlay?.getCanvas();
    if (canvas) canvas.style.visibility = '';
  }

  private cancelStagedAviationCommit() {
    this.aviationLayerCommit.cancel();
  }

  private resumeAviationOverlayViewSync() {
    const sync = this.aviationOverlayViewSync;
    if (sync && this.aviationOverlayViewSyncPaused) {
      this.aviationOverlayViewSyncPaused = false;
      this.resumeAviationDeckLoop();
      sync();
    }
    const canvas = this.aviationOverlay?.getCanvas();
    if (canvas) canvas.style.visibility = '';
  }

  private suspendAviationDeckLoop() {
    if (this.aviationDeckSuspended) return;
    const deck = (this.aviationOverlay as unknown as {
      _deck?: { animationLoop?: { stop?: () => void } };
    } | null)?._deck;
    deck?.animationLoop?.stop?.();
    this.aviationDeckSuspended = true;
  }

  private resumeAviationDeckLoop() {
    if (!this.aviationDeckSuspended || this.destroyed || this.paused || this.interacting) return;
    const deck = (this.aviationOverlay as unknown as {
      _deck?: { animationLoop?: { start?: () => void } };
    } | null)?._deck;
    deck?.animationLoop?.start?.();
    this.aviationDeckSuspended = false;
  }

  private markLocalFallbackReadyIfLoaded() {
    const map = this.map;
    if (!map || !this.fallbackApplied || this.destroyed) return false;
    try {
      if (!map.getSource(FALLBACK_COUNTRY_SOURCE)
        || !map.isSourceLoaded(FALLBACK_COUNTRY_SOURCE)) return false;
    } catch {
      return false;
    }
    this.clearFallbackTimer();
    this.clearFallbackSourceTimer();
    this.ensureFallbackCountryLabels();
    this.emitBasemapState('local-fallback-ready');
    return true;
  }

  private ensureFallbackCountryLabels() {
    if (this.fallbackCountryLabels.length || this.fallbackCountryLabelsLoading || this.destroyed) return;
    this.fallbackCountryLabelsLoading = fetch('/map-data/world-countries.geojson')
      .then(async (response) => {
        if (!response.ok) throw new Error(`Country label geometry returned HTTP ${response.status}`);
        return response.json() as Promise<FeatureCollection>;
      })
      .then((countries) => {
        if (this.destroyed) return;
        this.fallbackCountryLabels = countryBasemapLabels(countries);
        this.requestRender({ points: true });
      })
      .catch((error) => {
        if (!this.destroyed) this.callbacks?.onError(
          error instanceof Error ? error : new Error(String(error)),
        );
      })
      .finally(() => {
        this.fallbackCountryLabelsLoading = null;
      });
  }

  private createFallbackCountryLabelLayers(): LayersList {
    if (!this.fallbackApplied || !this.fallbackCountryLabels.length || !this.state) return [];
    const zoom = this.state.zoom;
    return [new TextLayer<CountryBasemapLabel>({
      id: 'world-event-fallback-country-labels',
      data: visibleCountryBasemapLabels(this.fallbackCountryLabels, zoom),
      pickable: false,
      billboard: true,
      characterSet: 'auto',
      fontFamily: mapLabelFontFamily(),
      fontWeight: 700,
      sizeUnits: 'pixels',
      getPosition: (label) => label.coordinates,
      getText: (label) => countryBasemapLabelName(label, this.language).toUpperCase(),
      getSize: zoom < 2.4 ? 10 : zoom < 4 ? 11 : 12,
      getColor: [134, 146, 151, 205],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
      parameters: { depthWriteEnabled: false },
    })];
  }

  private ensureCountryHoverLayers() {
    const map = this.map;
    if (!map || this.destroyed) return;
    try {
      const sourceId = map.getSource(FALLBACK_COUNTRY_SOURCE)
        ? FALLBACK_COUNTRY_SOURCE
        : COUNTRY_INTERACTION_SOURCE;
      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, {
          type: 'geojson',
          data: '/map-data/world-countries.geojson',
        });
      }
      const beforeId = map.getStyle()?.layers?.find((layer) => layer.type === 'symbol')?.id;
      if (!map.getLayer(COUNTRY_INTERACTIVE_LAYER)) {
        map.addLayer({
          id: COUNTRY_INTERACTIVE_LAYER,
          type: 'fill',
          source: sourceId,
          paint: { 'fill-color': '#ffffff', 'fill-opacity': 0 },
        }, beforeId);
      }
      if (!map.getLayer(COUNTRY_HOVER_FILL_LAYER)) {
        map.addLayer({
          id: COUNTRY_HOVER_FILL_LAYER,
          type: 'fill',
          source: sourceId,
          paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.025 },
          filter: EMPTY_COUNTRY_FILTER,
        }, beforeId);
      }
      if (!map.getLayer(COUNTRY_HOVER_BORDER_LAYER)) {
        map.addLayer({
          id: COUNTRY_HOVER_BORDER_LAYER,
          type: 'line',
          source: sourceId,
          paint: {
            'line-color': '#d8f7ff',
            'line-width': 0.7,
            'line-opacity': 0.3,
          },
          filter: EMPTY_COUNTRY_FILTER,
        }, beforeId);
      }
    } catch {
      // Style replacement can race the async local country source load.
    }
  }

  private runCountryHoverQuery(point: MapMouseEvent['point']) {
    const map = this.map;
    if (!map?.getLayer(COUNTRY_INTERACTIVE_LAYER)) return;
    try {
      const feature = map.queryRenderedFeatures(point, { layers: [COUNTRY_INTERACTIVE_LAYER] })[0];
      const iso2 = String(feature?.properties?.['ISO3166-1-Alpha-2'] || '');
      if (iso2 === this.hoveredCountryIso2) return;
      this.hoveredCountryIso2 = iso2 || null;
      const filter = iso2
        ? ['==', ['get', 'ISO3166-1-Alpha-2'], iso2] as FilterSpecification
        : EMPTY_COUNTRY_FILTER;
      map.setFilter(COUNTRY_HOVER_FILL_LAYER, filter);
      map.setFilter(COUNTRY_HOVER_BORDER_LAYER, filter);
      this.updateMapCursor();
    } catch {
      // The style may be changing between pointer sampling and feature query.
    }
  }

  private clearCountryHover() {
    this.hoveredCountryIso2 = null;
    const map = this.map;
    if (map?.getLayer(COUNTRY_HOVER_FILL_LAYER)) {
      try {
        map.setFilter(COUNTRY_HOVER_FILL_LAYER, EMPTY_COUNTRY_FILTER);
        map.setFilter(COUNTRY_HOVER_BORDER_LAYER, EMPTY_COUNTRY_FILTER);
      } catch {
        // The style may already be tearing down.
      }
    }
    this.updateMapCursor();
  }

  private clearAllHover() {
    this.countryPointer = null;
    const hadEventHover = this.hoveredDeckEventId != null;
    const hadClusterHover = this.hoveredDeckCluster != null;
    this.staticDeckHoverActive = false;
    this.aviationDeckHoverActive = false;
    this.deckHoverActive = false;
    this.manualAviationEvent = null;
    this.manualAviationTooltip?.clear();
    this.clearCountryHover();
    this.hoveredDeckEventId = null;
    this.hoveredDeckCluster = null;
    if (hadEventHover || hadClusterHover) this.requestRender({ interaction: true });
  }

  private updateMapCursor() {
    const canvas = this.map?.getCanvas();
    canvas?.classList.toggle(
      'wm-map-hover-target',
      this.deckHoverActive || Boolean(this.hoveredCountryIso2),
    );
  }

  private scheduleMissingTileRecovery() {
    if (this.missingTileRetryTimer != null || this.missingTileAttempts >= 2 || this.destroyed || this.paused
      || this.fallbackApplied || !this.missingBaseTiles.size) return;
    this.missingTileRetryTimer = window.setTimeout(() => {
      this.missingTileRetryTimer = null;
      if (this.destroyed || this.paused || this.fallbackApplied || !this.missingBaseTiles.size) return;
      this.missingTileAttempts++;
      void resetWorldEventPMTilesArchive().then(() => {
        if (!this.destroyed && !this.paused && !this.fallbackApplied) this.map?.refreshTiles('basemap', [...this.missingBaseTiles.values()]);
      }).catch(error => this.callbacks?.onBasemapIssueChange?.(String(error)));
    }, 30_000 * (this.missingTileAttempts + 1));
  }

  private handleMapError = (event: { sourceId?: string; tile?: { tileID?: {canonical?: {x: number; y: number; z: number}} }; error?: { message?: string; status?: number; headers?: Headers }; message?: string }) => {
    const message = event.error?.message || event.message || 'Unknown MapLibre error';
    if (event.sourceId?.startsWith('weather-radar') || /rainviewer/i.test(message)) {
      if (this.radarPending) { this.removeRadarBank(this.radarPending.bank); this.radarPending = null; }
      this.radarFailed = true;
      this.callbacks?.onRadarStateChange?.('error');
      const status = event.error?.status || 0;
      // MapLibre currently omits response headers from AJAXError. When absent,
      // rate limits use a conservative five-minute floor, never a fast retry.
      const header = event.error?.headers?.get('Retry-After');
      const advised = header ? (Number.isFinite(Number(header)) ? Number(header) * 1000 : Date.parse(header) - Date.now()) : 0;
      if ([401, 403, 429].includes(status)) {
        this.radarBlockedUntil = Date.now() + Math.max(300_000, advised || 0);
        if (this.radarRetryTimer != null) window.clearTimeout(this.radarRetryTimer);
        this.radarRetryTimer = null;
      }
      if ([401, 403].includes(status)) return;
      if (this.radarRetryTimer == null && this.radarRetryCount < 3 && !this.paused && this.radarFrame) {
        const delay = Math.max([5_000, 15_000, 45_000][this.radarRetryCount++]!, advised || 0, this.radarBlockedUntil - Date.now());
        this.radarRetryTimer = window.setTimeout(() => { this.radarRetryTimer = null; this.applyRadar(); }, delay);
      }
      return;
    }
    if (!this.fallbackApplied && /fetch|ajax|cors|network|bad response|403|forbidden|tile|style/i.test(message)) {
      const tile = event.tile?.tileID?.canonical;
      if (tile && event.sourceId === 'basemap') {
        if (!this.missingBaseTiles.size) this.missingTileAttempts = 0;
        this.missingBaseTiles.set(`${tile.z}/${tile.x}/${tile.y}`, tile);
        this.callbacks?.onBasemapIssueChange?.(`Missing base tiles: ${this.missingBaseTiles.size} · ${message}`);
        this.scheduleMissingTileRecovery();
        return; // This is a leaf/source issue, not a renderer failure.
      }
      // MapLibre emits transient tile/glyph errors before the first `load`
      // event as well as after it. Counting two resource errors as a fatal
      // style failure made a healthy same-origin PMTiles basemap downgrade
      // immediately on a cold Cloudflare range request. Keep retryable errors
      // visible to diagnostics and let the bounded readiness timer make the
      // only initial fallback decision.
      this.callbacks?.onError(new Error(message));
      return;
    }
    if (this.fallbackApplied && /fetch|ajax|cors|network|404|tile|source/i.test(message)) {
      this.requestRendererFallback(new Error(`Local basemap failed: ${message}`));
      return;
    }
    this.callbacks?.onError(new Error(message));
  };

  private handleContextLost = (event: Event) => {
    event.preventDefault();
    if (this.contextStableTimer != null) window.clearTimeout(this.contextStableTimer);
    this.contextStableTimer = null;
    this.paused = true;
    this.cancelAnimationLoop();
    this.cancelAnimationResume();
    this.cancelPickingWarmup?.();
    this.cancelPickingWarmup = null;
    this.cancelStagedAviationCommit();
    this.pickingWarmupStage = 0;
    this.renderScheduler.cancel();
    this.heavyGeometryCommit.cancel();
    this.geometryNeedsCommit = true;
    this.overlay?.setProps({ layers: [] });
    this.aviationOverlay?.setProps({ layers: [] });
    // Context loss really releases GPU layers, unlike a visibility pause.
    // Drop every cached instance so the recovery commit cannot reinsert it.
    this.geometryLayers = [];
    this.geometryCache.clear();
    this.interactionCache = null;
    this.pointLayers = null;
    this.aviationLayerSections = null;
    this.emitBasemapState('initializing');
    this.callbacks?.onError(new Error('WebGL context lost. Waiting for one bounded recovery attempt.'));
    this.clearContextRecoveryTimer();
    this.contextRecoveryTimer = window.setTimeout(() => {
      this.contextRecoveryTimer = null;
      this.requestRendererFallback(new Error('WebGL context did not recover within 4 seconds.'));
    }, 4_000);
  };

  private handleContextRestored = () => {
    this.clearContextRecoveryTimer();
    this.contextRecoveryAttempts += 1;
    if (this.contextRecoveryAttempts > 1) {
      this.requestRendererFallback(new Error('WebGL context was lost more than once.'));
      return;
    }
    this.paused = false;
    // A restored context is accepted only after a real frame AND picking.
    const recovered = () => {
      this.clearContextRecoveryTimer();
      this.emitBasemapState(this.fallbackApplied ? 'local-fallback-ready' : 'primary-ready');
      if (this.contextStableTimer != null) window.clearTimeout(this.contextStableTimer);
      this.contextStableTimer = window.setTimeout(() => { this.contextRecoveryAttempts = 0; this.contextStableTimer = null; }, 60_000);
    };
    this.map?.once('render', () => {
      if (this.destroyed) return;
      if (!this.warmOverlayPicking(this.overlay)) {
        this.contextRecoveryTimer = window.setTimeout(() => {
          if (!this.warmOverlayPicking(this.overlay)) this.requestRendererFallback(new Error('Restored context did not regain picking.'));
          else recovered();
        }, 1_000);
      } else recovered();
    });
    this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
    this.syncAnimationLoop();
  };

  private applyLocalFallback(error: Error) {
    if (!this.map || this.fallbackApplied || this.destroyed) return;
    this.fallbackApplied = true;
    this.clearFallbackTimer();
    this.emitBasemapState('initializing');
    this.callbacks?.onError(error);
    try {
      this.map.setStyle(getWeatherMapFallbackStyle(this.state?.basemapTheme ?? 'dark'), { diff: false });
      this.scheduleFallbackSourceTimeout();
      this.schedulePrimaryRecovery();
    } catch (caught) {
      this.requestRendererFallback(caught instanceof Error ? caught : new Error(String(caught)));
    }
  }

  private schedulePrimaryRecovery() {
    if (this.destroyed || this.primaryRecoveryTimer != null || this.primaryRecoveryAttempts >= 2) return;
    this.primaryRecoveryTimer = window.setTimeout(() => {
      this.primaryRecoveryTimer = null;
      if (this.destroyed || !this.state || !this.fallbackApplied) return;
      if (this.paused || document.hidden) { this.schedulePrimaryRecovery(); return; }
      this.primaryRecoveryAttempts++;
      void (async () => {
        if (this.state?.basemapProvider === 'pmtiles' || this.state?.basemapProvider === 'auto') await resetWorldEventPMTilesArchive();
        if (!this.destroyed && this.state) await this.replaceBasemapStyle(this.state);
      })().catch(error => this.callbacks?.onError(error instanceof Error ? error : new Error(String(error))));
    }, this.primaryRecoveryAttempts === 0 ? 30_000 : 120_000);
  }

  private async replaceBasemapStyle(state: WorldEventMapState) {
    const map = this.map;
    if (!map || this.destroyed) return;
    const generation = ++this.basemapStyleGeneration;
    this.fallbackApplied = false;
    this.primaryHasContent = false;
    this.primaryMetadataReady = false;
    this.missingBaseTiles.clear(); this.missingTileAttempts = 0;
    this.callbacks?.onBasemapIssueChange?.(null);
    this.clearFallbackTimer();
    this.clearFallbackSourceTimer();
    this.emitBasemapState('initializing');
    try {
      const style = await getWeatherMapStyle(state.basemapTheme, state.basemapProvider, this.language);
      if (this.destroyed || generation !== this.basemapStyleGeneration || map !== this.map) return;
      map.setStyle(style, { diff: false });
      this.schedulePrimaryDeadline();
    } catch (error) {
      if (this.destroyed || generation !== this.basemapStyleGeneration) return;
      this.applyLocalFallback(error instanceof Error ? error : new Error(String(error)));
    }
  }

  private acceptLayerVersion(layer: Layer): boolean {
    if (!this.quarantinedLayerIds.has(layer.id)) return true;
    if (this.quarantinedLayerData.get(layer.id) === this.layerInputFingerprint(layer)) return false;
    this.quarantinedLayerIds.delete(layer.id); this.quarantinedLayerData.delete(layer.id);
    this.callbacks?.onLayerRecovered?.(layer.id);
    return true;
  }

  private layerInputFingerprint(layer: Layer): string {
    // Camera-dependent cluster data is NOT a new source version. Otherwise
    // zooming immediately re-enables the same toxic input. Compute only while
    // quarantined, once per validated event/style version.
    if (!this.events.length) return JSON.stringify(layer.props?.data ?? null);
    const group = layer.id.startsWith('aviation-') ? 'aviation' : 'events';
    const version = `${this.eventVersion}:${this.basemapStyleGeneration}`;
    const cached = this.inputFingerprints.get(group);
    if (cached?.version === version) return cached.value;
    const value = JSON.stringify([this.basemapStyleGeneration,
      this.events.filter(event => isAviationEvent(event) === (group === 'aviation'))]);
    this.inputFingerprints.set(group, {version, value}); return value;
  }

  private handleDeckLayerError(error: Error, layer?: Layer) {
    const layerId = layer?.id;
    if (!layerId) {
      this.callbacks?.onError(error);
      return;
    }
    if (this.quarantinedLayerIds.has(layerId)) return;
    this.quarantinedLayerIds.add(layerId);
    this.interactionCache = null;
    this.geometryCache.clear();
    this.quarantinedLayerData.set(layerId, this.layerInputFingerprint(layer!));
    this.callbacks?.onLayerDegraded?.(layerId, error);
    this.callbacks?.onError(new Error(`Map layer ${layerId} was isolated after a render error: ${error.message}`));
    if (layerId.startsWith('aviation-')) {
      this.aviationLayerSections = null;
      this.aviationDynamicLayers = null;
      this.requestRender({ aviation: true, dynamic: true });
      return;
    }
    this.pointLayers = null;
    this.invalidateGeometry();
    this.requestRender({ points: true, geometry: true, interaction: true });
  }

  private requestRendererFallback(error: Error) {
    if (this.destroyed) return;
    this.clearFallbackSourceTimer();
    this.clearContextRecoveryTimer();
    this.emitBasemapState('renderer-fallback-ready');
    this.callbacks?.onRendererFallbackRequested(error);
  }

  private emitBasemapState(state: BasemapState) {
    this.callbacks?.onBasemapStateChange(state);
  }

  private clearFallbackTimer() {
    if (this.fallbackTimer != null) {
      window.clearTimeout(this.fallbackTimer);
      this.fallbackTimer = null;
    }
  }

  private scheduleAnimationResume(delayMs = 500) {
    this.cancelAnimationResume();
    this.animationResumeTimer = window.setTimeout(() => {
      this.animationResumeTimer = null;
      if (!this.destroyed && !this.paused && !this.interacting) {
        this.resumeAviationDeckLoop();
        this.syncAnimationLoop();
      }
    }, delayMs);
  }

  private cancelAnimationResume() {
    if (this.animationResumeTimer != null) {
      window.clearTimeout(this.animationResumeTimer);
      this.animationResumeTimer = null;
    }
  }

  private scheduleFallbackSourceTimeout() {
    if (this.fallbackSourceTimer != null || this.destroyed) return;
    this.fallbackSourceTimer = window.setTimeout(() => {
      this.fallbackSourceTimer = null;
      if (this.markLocalFallbackReadyIfLoaded()) return;
      this.requestRendererFallback(new Error(
        'Local country geometry did not become renderable within 6 seconds.',
      ));
    }, MAP_RENDERER_TIMEOUTS.localGeometry);
  }

  private clearFallbackSourceTimer() {
    if (this.fallbackSourceTimer != null) {
      window.clearTimeout(this.fallbackSourceTimer);
      this.fallbackSourceTimer = null;
    }
  }

  private clearContextRecoveryTimer() {
    if (this.contextRecoveryTimer != null) {
      window.clearTimeout(this.contextRecoveryTimer);
      this.contextRecoveryTimer = null;
    }
  }

  private updateAdaptiveAnimationBudget(frameCostMs: number) {
    if (frameCostMs > 24) {
      this.animationIntervalMs = 80;
      this.animationRecoveryFrames = 0;
      return;
    }
    if (this.animationIntervalMs <= MAP_ANIMATION_FRAME_INTERVAL_MS) return;
    this.animationRecoveryFrames += 1;
    if (this.animationRecoveryFrames >= 60) {
      this.animationIntervalMs = MAP_ANIMATION_FRAME_INTERVAL_MS;
      this.animationRecoveryFrames = 0;
    }
  }

  private hasAnimatedAviation() {
    return this.state?.activeLayerIds.includes('air-routes') === true && this.aviationMotionAvailable;
  }

  private hasAnimation() {
    return this.hasAnimatedAviation() || hasAnimatedHazardPulse(this.pulseEvents,
      this.state?.selectedEventId || null, this.eventFirstSeenAt, Date.now(), this.state?.zoom ?? 0);
  }

  private syncAnimationLoop() {
    if (this.destroyed || this.paused || this.interacting || this.reducedMotion || !this.hasAnimation()) {
      this.cancelAnimationLoop();
      return;
    }
    if (this.animationFrame != null) return;
    this.animationFrame = window.requestAnimationFrame(this.handleAnimationFrame);
  }

  private handleAnimationFrame = (timestamp: number) => {
    this.animationFrame = null;
    if (this.destroyed || this.paused || this.reducedMotion) return;
    if (!this.hasAnimation()) { this.hazardPulseTime = Date.now(); this.requestRender({ pulse: true }); return; }
    const actualFrameDelay = this.lastAnimationTimestamp == null
      ? 0
      : Math.max(0, timestamp - this.lastAnimationTimestamp);
    if (actualFrameDelay > 0) this.updateAdaptiveAnimationBudget(actualFrameDelay);
    const delta = boundedAnimationDelta(this.lastAnimationTimestamp, timestamp);
    this.lastAnimationTimestamp = timestamp;
    this.pendingAnimationDeltaMs += delta;
    if (this.pendingAnimationDeltaMs >= this.animationIntervalMs && this.shouldRenderAnimationFrame()) {
      this.animationTime = advanceAnimationTime(this.animationTime, this.pendingAnimationDeltaMs);
      this.pendingAnimationDeltaMs = 0;
      this.hazardPulseTime = Date.now();
      const pulseActive = hasAnimatedHazardPulse(this.pulseEvents,
        this.state?.selectedEventId || null, this.eventFirstSeenAt, this.hazardPulseTime, this.state?.zoom ?? 0);
      // Submit one final empty pulse layer when a pulse expires, then leave the
      // static map alone while aircraft continue moving on their own canvas.
      this.requestRender({ dynamic: this.hasAnimatedAviation(), pulse: pulseActive || this.pulseWasActive });
      this.pulseWasActive = pulseActive;
    } else {
      this.pendingAnimationDeltaMs = Math.min(this.pendingAnimationDeltaMs, 160);
    }
    this.animationFrame = window.requestAnimationFrame(this.handleAnimationFrame);
  };

  private cancelAnimationLoop() {
    if (this.animationFrame != null) {
      window.cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }
    this.lastAnimationTimestamp = null;
    this.pendingAnimationDeltaMs = 0;
    this.animationRecoveryFrames = 0;
  }

  private shouldRenderAnimationFrame() {
    const scheduling = (globalThis as unknown as {
      navigator?: { scheduling?: { isInputPending?: () => boolean } };
    }).navigator?.scheduling;
    return !this.interacting && scheduling?.isInputPending?.() !== true;
  }
}
