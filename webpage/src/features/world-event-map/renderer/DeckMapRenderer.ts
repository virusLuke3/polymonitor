import { MapboxOverlay } from '@deck.gl/mapbox';
import type { Layer, LayersList, PickingInfo } from '@deck.gl/core';
import maplibregl, {
  type FilterSpecification,
  type Map as MapLibreMap,
  type MapMouseEvent,
} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {
  getWeatherMapFallbackStyle,
  getWeatherMapStyle,
  refreshWorldEventBasemapLabelDensity,
  reinforceWorldEventBasemapLabels,
} from '@/config/weatherBasemap';
import type { GeoEvent } from '../domain/types';
import type { WorldEventMapState } from '../state/mapState';
import type { BasemapState, MapRenderer, MapRendererCallbacks } from './MapRenderer';
import {
  createAviationDynamicLayers,
  createAviationStaticLayerSections,
  createEventInteractionLayers,
  createEventPulseLayers,
  createWorldEventGeometryLayers,
  createWorldEventPointLayers,
  EventClusterIndex,
  HAZARD_PULSE_INTERVAL_MS,
  hasAnimatedHazardPulse,
  selectEventPulseCandidates,
  type AviationStaticLayerSections,
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
  worldEventTooltipHtml,
  type WorldEventPickedObject,
} from './hoverTooltip';
import {
  createCountryHoverQueryController,
  type CountryHoverQueryController,
} from './countryHoverController';
import { DeferredLatestCommit, scheduleAfterMainThreadYield } from './deferredCommit';
import { MapPerformanceMonitor } from './mapPerformance';
import { MapRenderScheduler, type MapRenderInvalidation } from './renderScheduler';

const COUNTRY_INTERACTION_SOURCE = 'world-event-country-interaction-source';
const FALLBACK_COUNTRY_SOURCE = 'wm-weather-country-boundaries';
const COUNTRY_INTERACTIVE_LAYER = 'world-event-country-interactive';
const COUNTRY_HOVER_FILL_LAYER = 'world-event-country-hover-fill';
const COUNTRY_HOVER_BORDER_LAYER = 'world-event-country-hover-border';
const EMPTY_COUNTRY_FILTER = ['==', ['get', 'ISO3166-1-Alpha-2'], ''] as FilterSpecification;

export class DeckMapRenderer implements MapRenderer {
  private map: MapLibreMap | null = null;
  private overlay: MapboxOverlay | null = null;
  private aviationOverlay: MapboxOverlay | null = null;
  private callbacks: MapRendererCallbacks | null = null;
  private state: WorldEventMapState | null = null;
  private events: GeoEvent[] = [];
  private fallbackApplied = false;
  private primaryBasemapErrorCount = 0;
  private fallbackTimer: number | null = null;
  private contextRecoveryTimer: number | null = null;
  private contextRecoveryAttempts = 0;
  private overlayMounted = false;
  private aviationOverlayMounted = false;
  private paused = false;
  private destroyed = false;
  private applyingCamera = false;
  private reducedMotion = false;
  private animationFrame: number | null = null;
  private lastAnimationTimestamp: number | null = null;
  private pendingAnimationDeltaMs = 0;
  private animationTime = 0;
  private pointLayers: LayersList | null = null;
  private geometryLayers: LayersList = [];
  private geometryGeneration = 0;
  private geometryNeedsCommit = true;
  private readonly clusterIndex = new EventClusterIndex();
  private readonly renderScheduler: MapRenderScheduler;
  private readonly heavyGeometryCommit: DeferredLatestCommit<{
    events: GeoEvent[];
    selectedEventId: string | null;
    generation: number;
  }>;
  private readonly performanceMonitor = new MapPerformanceMonitor();
  private deckHoverActive = false;
  private hoveredDeckEventId: string | null = null;
  private hoveredDeckCluster: EventCluster | null = null;
  private staticDeckHoverActive = false;
  private aviationDeckHoverActive = false;
  private hoveredCountryIso2: string | null = null;
  private countryHoverQueryController: CountryHoverQueryController<MapMouseEvent['point']> | null = null;
  private interacting = false;
  private animationIntervalMs = MAP_ANIMATION_FRAME_INTERVAL_MS;
  private animationRecoveryFrames = 0;
  private hazardPulseTimer: number | null = null;
  private hazardPulseTime = Date.now();
  private readonly eventFirstSeenAt = new Map<string, number>();
  private receivedInitialEventSnapshot = false;
  private pulseEvents: GeoEvent[] = [];
  /**
   * Aviation has a different invalidation cadence from hazards: route geometry,
   * hubs and live positions are static between data/camera changes, while only
   * the small motion subset changes during an animation frame.
   */
  private aviationLayerSections: AviationStaticLayerSections | null = null;

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
      ({ events, selectedEventId, generation }) => {
        if (this.destroyed || this.paused || generation !== this.geometryGeneration) return;
        this.geometryLayers = this.performanceMonitor.measure(
          'js-build',
          () => createWorldEventGeometryLayers(events, selectedEventId),
        );
        this.geometryNeedsCommit = false;
        this.requestRender();
      },
    );
  }

  async mount(container: HTMLElement, callbacks: MapRendererCallbacks) {
    if (this.map) return;
    this.destroyed = false;
    this.callbacks = callbacks;
    this.emitBasemapState('initializing');
    const state = this.state;
    const primaryStyle = await getWeatherMapStyle('dark');
    if (this.destroyed) return;
    const map = new maplibregl.Map({
      container,
      style: primaryStyle,
      center: state ? [state.center.lon, state.center.lat] : [20, 24],
      zoom: state?.zoom ?? 1.25,
      renderWorldCopies: false,
      attributionControl: false,
      interactive: true,
      pitchWithRotate: false,
      dragRotate: false,
      touchPitch: false,
      canvasContextAttributes: { powerPreference: 'high-performance' },
    });
    this.map = map;
    this.countryHoverQueryController = createCountryHoverQueryController(
      (callback) => window.requestAnimationFrame(callback),
      (handle) => window.cancelAnimationFrame(handle),
      (point) => this.runCountryHoverQuery(point),
    );

    const getTooltip = (info: PickingInfo<WorldEventPickedObject>) => {
      const html = worldEventTooltipHtml(info.object, info.layer?.id || '');
      return html ? { html } : null;
    };
    const getCursor = ({ isDragging, isHovering }: { isDragging: boolean; isHovering: boolean }) => {
      if (isDragging) return 'grabbing';
      return isHovering || Boolean(this.hoveredCountryIso2) ? 'pointer' : 'grab';
    };
    const onClick = (info: PickingInfo<WorldEventPickedObject>) => {
        const cluster = pickedWorldEventCluster(info.object);
        if (cluster) {
          const [west, south, east, north] = cluster.bounds;
          if (west === east && south === north) {
            map.easeTo({
              center: cluster.coordinates,
              zoom: Math.min(6, cluster.expansionZoom || map.getZoom() + 1.5),
              duration: this.reducedMotion ? 0 : 420,
            });
          } else {
            map.fitBounds(
              [[west, south], [east, north]],
              { padding: 70, maxZoom: 6, duration: this.reducedMotion ? 0 : 480 },
            );
          }
          return;
        }
        callbacks.onEventSelect(pickedWorldEvent(info.object)?.id ?? null);
    };
    const overlay = new MapboxOverlay({
      interleaved: true,
      layers: [],
      pickingRadius: 8,
      useDevicePixels: window.devicePixelRatio > 2 ? 2 : true,
      getCursor,
      getTooltip,
      onHover: (info: PickingInfo<WorldEventPickedObject>) => this.handleDeckHover('static', info),
      onClick,
    });
    const aviationOverlay = new MapboxOverlay({
      interleaved: false,
      layers: [],
      pickingRadius: 8,
      // The motion canvas contains only small aircraft and route runners. A
      // bounded pixel ratio keeps its full-canvas clear/draw below the frame
      // budget without reducing the labelled basemap or static event detail.
      useDevicePixels: Math.min(1.25, Math.max(0.75, window.devicePixelRatio * 0.75)),
      getCursor,
      getTooltip,
      onHover: (info: PickingInfo<WorldEventPickedObject>) => this.handleDeckHover('aviation', info),
      onClick,
    });
    this.overlay = overlay;
    this.aviationOverlay = aviationOverlay;

    map.once('load', () => {
      if (this.destroyed) return;
      if (!this.overlayMounted) {
        map.addControl(overlay as unknown as maplibregl.IControl);
        this.overlayMounted = true;
      }
      if (!this.aviationOverlayMounted) {
        map.addControl(aviationOverlay as unknown as maplibregl.IControl);
        this.aviationOverlayMounted = true;
      }
      this.clearFallbackTimer();
      reinforceWorldEventBasemapLabels(map);
      this.ensureCountryHoverLayers();
      this.emitBasemapState(this.fallbackApplied ? 'local-fallback-ready' : 'primary-ready');
      this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
      this.syncAnimationLoop();
      this.syncHazardPulseLoop();
    });
    map.on('style.load', this.handleStyleLoad);
    map.on('moveend', this.handleMoveEnd);
    map.on('movestart', this.handleMoveStart);
    map.on('mousemove', this.handleCountryHoverMove);
    map.on('mouseout', this.handleCountryHoverLeave);
    map.on('error', this.handleMapError);
    map.getCanvas().addEventListener('webglcontextlost', this.handleContextLost);
    map.getCanvas().addEventListener('webglcontextrestored', this.handleContextRestored);

    this.fallbackTimer = window.setTimeout(() => {
      if (!this.map || this.fallbackApplied || this.destroyed) return;
      this.applyLocalFallback(new Error('Primary basemap did not become ready within 10 seconds.'));
    }, 10_000);
  }

  setState(state: WorldEventMapState) {
    const previous = this.state;
    this.state = state;
    if (!previous || previous.selectedEventId !== state.selectedEventId) {
      this.pulseEvents = selectEventPulseCandidates(this.events, state.selectedEventId);
    }
    const map = this.map;
    if (map && (!previous
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
          essential: true,
        });
      }
    }
    const staticLayersChanged = !previous
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
    const geometryChanged = !previous
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
    this.syncHazardPulseLoop();
  }

  setEvents(events: GeoEvent[]) {
    if (events === this.events) return;
    const previousIds = new Set(this.events.map((event) => event.id));
    const now = Date.now();
    if (this.receivedInitialEventSnapshot) {
      for (const event of events) {
        if (!previousIds.has(event.id)) this.eventFirstSeenAt.set(event.id, now);
      }
    } else if (events.length > 0) {
      this.receivedInitialEventSnapshot = true;
    }
    const nextIds = new Set(events.map((event) => event.id));
    for (const eventId of this.eventFirstSeenAt.keys()) {
      if (!nextIds.has(eventId)) this.eventFirstSeenAt.delete(eventId);
    }
    this.events = events;
    this.pulseEvents = selectEventPulseCandidates(events, this.state?.selectedEventId || null);
    this.clusterIndex.update(events);
    this.pointLayers = null;
    this.aviationLayerSections = null;
    this.invalidateGeometry();
    this.requestRender({
      points: true,
      aviation: true,
      geometry: true,
      dynamic: true,
      pulse: true,
      interaction: true,
    });
    this.syncAnimationLoop();
    this.syncHazardPulseLoop();
  }

  resize() {
    this.map?.resize();
  }

  setReducedMotion(reduced: boolean) {
    this.reducedMotion = reduced;
    this.syncAnimationLoop();
    this.syncHazardPulseLoop();
    this.requestRender({ dynamic: true, pulse: true });
  }

  pause() {
    this.paused = true;
    this.clearAllHover();
    this.cancelAnimationLoop();
    this.cancelHazardPulseLoop();
    this.renderScheduler.cancel();
    this.heavyGeometryCommit.cancel();
    this.geometryNeedsCommit = true;
    this.overlay?.setProps({ layers: [] });
    this.aviationOverlay?.setProps({ layers: [] });
  }

  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.resize();
    this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
    this.syncAnimationLoop();
    this.syncHazardPulseLoop();
  }

  destroy() {
    this.destroyed = true;
    this.clearFallbackTimer();
    this.clearContextRecoveryTimer();
    this.cancelAnimationLoop();
    this.cancelHazardPulseLoop();
    this.renderScheduler.cancel();
    this.heavyGeometryCommit.cancel();
    this.performanceMonitor.destroy();
    this.countryHoverQueryController?.cancel();
    this.clearAllHover();
    const map = this.map;
    if (map) {
      map.off('style.load', this.handleStyleLoad);
      map.off('moveend', this.handleMoveEnd);
      map.off('movestart', this.handleMoveStart);
      map.off('mousemove', this.handleCountryHoverMove);
      map.off('mouseout', this.handleCountryHoverLeave);
      map.off('error', this.handleMapError);
      map.getCanvas().removeEventListener('webglcontextlost', this.handleContextLost);
      map.getCanvas().removeEventListener('webglcontextrestored', this.handleContextRestored);
      if (this.overlay) {
        try {
          map.removeControl(this.overlay as unknown as maplibregl.IControl);
        } catch {
          // MapLibre may already be tearing the style down.
        }
      }
      if (this.aviationOverlay) {
        try {
          map.removeControl(this.aviationOverlay as unknown as maplibregl.IControl);
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
    this.aviationLayerSections = null;
    this.overlayMounted = false;
    this.aviationOverlayMounted = false;
    this.countryHoverQueryController = null;
    this.staticDeckHoverActive = false;
    this.aviationDeckHoverActive = false;
    this.deckHoverActive = false;
    this.hoveredDeckEventId = null;
    this.hoveredCountryIso2 = null;
    this.callbacks = null;
  }

  private requestRender(invalidation: Partial<MapRenderInvalidation> = {}) {
    if (this.destroyed || this.paused || !this.overlay || !this.aviationOverlay || !this.state) return;
    this.renderScheduler.request(invalidation);
  }

  private invalidateGeometry() {
    this.geometryGeneration += 1;
    this.geometryNeedsCommit = true;
  }

  private flushRender(invalidation: MapRenderInvalidation) {
    if (this.paused || !this.overlay || !this.state) return;
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
      this.pointLayers = this.performanceMonitor.measure(
        'js-build',
        () => createWorldEventPointLayers(this.events, this.state!, viewport, this.clusterIndex),
      );
    }
    if (invalidation.geometry || this.geometryNeedsCommit) {
      this.heavyGeometryCommit.stage({
        events: this.events,
        selectedEventId: this.state.selectedEventId,
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
    const aviationDynamicLayers = aviationSections
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
    const pointLayerList = (this.pointLayers || []).filter(
      (layer): layer is Layer => Boolean(layer) && !Array.isArray(layer),
    );
    const aviationDynamicLayerList = aviationDynamicLayers.filter(
      (layer): layer is Layer => Boolean(layer) && !Array.isArray(layer),
    );
    const pointLabels = pointLayerList.filter((layer) => (
      layer?.id === 'world-event-labels' || layer?.id === 'world-event-cluster-counts'
    ));
    const pointBaseLayers = pointLayerList.filter((layer) => !pointLabels.includes(layer));
    const routeRunnerLayers = aviationDynamicLayerList.filter((layer) => layer.id === 'aviation-route-runners');
    const seededAircraftLayers = aviationDynamicLayerList.filter((layer) => layer.id === 'aviation-seeded-aircraft');
    const seededInteractionLayers = aviationDynamicLayerList.filter((layer) => (
      layer.id.startsWith('aviation-seeded-hover-') || layer.id.startsWith('aviation-seeded-selected-')
    ));
    const aviationCountLabels = aviationDynamicLayerList.filter((layer) => layer.id.endsWith('-counts'));
    const pulseLayers = this.reducedMotion
      ? []
      : createEventPulseLayers({
        events: this.pulseEvents,
        selectedEventId: this.state.selectedEventId,
        firstSeenAt: this.eventFirstSeenAt,
        pulseTime: this.hazardPulseTime,
      });
    const interactionLayers = createEventInteractionLayers(
      this.events,
      this.state.selectedEventId,
      this.hoveredDeckEventId,
      this.hoveredDeckCluster,
    );
    const staticLayers = [
      ...this.geometryLayers,
      ...(aviationSections?.routeLayers || []),
      ...pointBaseLayers,
    ];
    const dynamicLayers = [
      ...routeRunnerLayers,
      ...(aviationSections?.hubLayers || []),
      ...seededAircraftLayers,
      ...(aviationSections?.aircraftLayers || []),
      ...pulseLayers,
      ...interactionLayers,
      ...seededInteractionLayers,
      ...(aviationSections?.labelLayers || []),
      ...aviationCountLabels,
      ...pointLabels,
    ];
    this.performanceMonitor.measure(onlyDynamic ? 'dynamic-commit' : 'deck-commit', () => {
      if (!onlyDynamic) this.overlay?.setProps({ layers: staticLayers });
      this.aviationOverlay?.setProps({ layers: dynamicLayers });
    });
    if (!onlyDynamic) this.map?.triggerRepaint();
  }

  private handleMoveEnd = () => {
    const map = this.map;
    if (!map || !this.callbacks) return;
    refreshWorldEventBasemapLabelDensity(map);
    this.interacting = false;
    this.pointLayers = null;
    this.aviationLayerSections = null;
    this.requestRender({ points: true, aviation: true, dynamic: true });
    this.syncAnimationLoop();
    this.syncHazardPulseLoop();
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
    this.interacting = true;
    this.cancelAnimationLoop();
    this.cancelHazardPulseLoop();
    this.countryHoverQueryController?.cancel();
    this.clearAllHover();
  };

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
    this.countryHoverQueryController?.queue(event.point);
  };

  private handleCountryHoverLeave = () => {
    this.countryHoverQueryController?.cancel();
    this.clearAllHover();
  };

  private handleStyleLoad = () => {
    if (!this.map || this.destroyed) return;
    this.clearFallbackTimer();
    reinforceWorldEventBasemapLabels(this.map);
    this.ensureCountryHoverLayers();
    this.emitBasemapState(this.fallbackApplied ? 'local-fallback-ready' : 'primary-ready');
    this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
  };

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
      const beforeId = map.getStyle().layers?.find((layer) => layer.type === 'symbol')?.id;
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
          paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.055 },
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
            'line-width': 1.35,
            'line-opacity': 0.56,
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
    const hadEventHover = this.hoveredDeckEventId != null;
    const hadClusterHover = this.hoveredDeckCluster != null;
    this.staticDeckHoverActive = false;
    this.aviationDeckHoverActive = false;
    this.deckHoverActive = false;
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

  private handleMapError = (event: { error?: Error; message?: string }) => {
    const message = event.error?.message || event.message || 'Unknown MapLibre error';
    if (!this.fallbackApplied && /fetch|ajax|cors|network|403|forbidden|tile|style/i.test(message)) {
      this.primaryBasemapErrorCount += 1;
      if (this.primaryBasemapErrorCount >= 2) this.applyLocalFallback(new Error(message));
      return;
    }
    this.callbacks?.onError(new Error(message));
  };

  private handleContextLost = (event: Event) => {
    event.preventDefault();
    this.paused = true;
    this.cancelAnimationLoop();
    this.cancelHazardPulseLoop();
    this.renderScheduler.cancel();
    this.heavyGeometryCommit.cancel();
    this.geometryNeedsCommit = true;
    this.overlay?.setProps({ layers: [] });
    this.aviationOverlay?.setProps({ layers: [] });
    this.emitBasemapState('renderer-fallback-ready');
    this.callbacks?.onError(new Error('WebGL context lost. Waiting for one bounded recovery attempt.'));
    this.clearContextRecoveryTimer();
    this.contextRecoveryTimer = window.setTimeout(() => {
      this.contextRecoveryTimer = null;
      this.requestRendererFallback(new Error('WebGL context did not recover within 1.5 seconds.'));
    }, 1_500);
  };

  private handleContextRestored = () => {
    this.clearContextRecoveryTimer();
    this.contextRecoveryAttempts += 1;
    if (this.contextRecoveryAttempts > 1) {
      this.requestRendererFallback(new Error('WebGL context was lost more than once.'));
      return;
    }
    this.paused = false;
    this.emitBasemapState(this.fallbackApplied ? 'local-fallback-ready' : 'primary-ready');
    this.requestRender({ points: true, aviation: true, geometry: true, dynamic: true });
    this.syncAnimationLoop();
    this.syncHazardPulseLoop();
  };

  private applyLocalFallback(error: Error) {
    if (!this.map || this.fallbackApplied || this.destroyed) return;
    this.fallbackApplied = true;
    this.clearFallbackTimer();
    this.callbacks?.onError(error);
    try {
      this.map.setStyle(getWeatherMapFallbackStyle('dark'), { diff: false });
    } catch (caught) {
      this.requestRendererFallback(caught instanceof Error ? caught : new Error(String(caught)));
    }
  }

  private requestRendererFallback(error: Error) {
    if (this.destroyed) return;
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
    if (this.animationRecoveryFrames >= 600) {
      this.animationIntervalMs = MAP_ANIMATION_FRAME_INTERVAL_MS;
      this.animationRecoveryFrames = 0;
    }
  }

  private hasAnimatedAviation() {
    const airRoutesActive = this.state?.activeLayerIds.includes('air-routes') === true;
    return airRoutesActive && this.events.some((event) => (
      event.category === 'infrastructure'
      && (event.properties.mapEntity === 'air-route' || event.properties.mapEntity === 'air-flight')
    ));
  }

  private syncHazardPulseLoop() {
    const shouldPulse = !this.destroyed
      && !this.paused
      && !this.interacting
      && !this.reducedMotion
      && Boolean(this.overlay)
      && Boolean(this.aviationOverlay)
      && hasAnimatedHazardPulse(
        this.pulseEvents,
        this.state?.selectedEventId || null,
        this.eventFirstSeenAt,
      );
    if (!shouldPulse) {
      this.cancelHazardPulseLoop();
      return;
    }
    if (this.hazardPulseTimer != null) return;
    this.hazardPulseTimer = window.setInterval(() => {
      if (
        this.destroyed
        || this.paused
        || this.interacting
        || this.reducedMotion
        || !hasAnimatedHazardPulse(
          this.pulseEvents,
          this.state?.selectedEventId || null,
          this.eventFirstSeenAt,
        )
      ) {
        this.cancelHazardPulseLoop();
        return;
      }
      this.hazardPulseTime = Date.now();
      if (this.shouldRenderAnimationFrame()) this.requestRender({ pulse: true });
    }, HAZARD_PULSE_INTERVAL_MS);
  }

  private cancelHazardPulseLoop() {
    if (this.hazardPulseTimer != null) {
      window.clearInterval(this.hazardPulseTimer);
      this.hazardPulseTimer = null;
    }
  }

  private syncAnimationLoop() {
    if (this.destroyed || this.paused || this.reducedMotion || !this.hasAnimatedAviation()) {
      this.cancelAnimationLoop();
      return;
    }
    if (this.animationFrame != null) return;
    this.animationFrame = window.requestAnimationFrame(this.handleAnimationFrame);
  }

  private handleAnimationFrame = (timestamp: number) => {
    this.animationFrame = null;
    if (this.destroyed || this.paused || this.reducedMotion || !this.hasAnimatedAviation()) return;
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
      this.requestRender({ dynamic: true });
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
