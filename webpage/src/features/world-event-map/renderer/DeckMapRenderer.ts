import { MapboxOverlay } from '@deck.gl/mapbox';
import type { PickingInfo } from '@deck.gl/core';
import maplibregl, {
  type FilterSpecification,
  type Map as MapLibreMap,
  type MapMouseEvent,
} from 'maplibre-gl';
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
  createWorldEventStaticLayerSections,
  type AviationStaticLayerSections,
  type WorldEventStaticLayerSections,
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

const COUNTRY_INTERACTION_SOURCE = 'world-event-country-interaction-source';
const FALLBACK_COUNTRY_SOURCE = 'wm-weather-country-boundaries';
const COUNTRY_INTERACTIVE_LAYER = 'world-event-country-interactive';
const COUNTRY_HOVER_FILL_LAYER = 'world-event-country-hover-fill';
const COUNTRY_HOVER_BORDER_LAYER = 'world-event-country-hover-border';
const EMPTY_COUNTRY_FILTER = ['==', ['get', 'ISO3166-1-Alpha-2'], ''] as FilterSpecification;

export class DeckMapRenderer implements MapRenderer {
  private map: MapLibreMap | null = null;
  private overlay: MapboxOverlay | null = null;
  private callbacks: MapRendererCallbacks | null = null;
  private state: WorldEventMapState | null = null;
  private events: GeoEvent[] = [];
  private fallbackApplied = false;
  private primaryBasemapErrorCount = 0;
  private fallbackTimer: number | null = null;
  private contextRecoveryTimer: number | null = null;
  private contextRecoveryAttempts = 0;
  private overlayMounted = false;
  private paused = false;
  private destroyed = false;
  private applyingCamera = false;
  private reducedMotion = false;
  private animationFrame: number | null = null;
  private lastAnimationTimestamp: number | null = null;
  private pendingAnimationDeltaMs = 0;
  private animationTime = 0;
  private staticLayerSections: WorldEventStaticLayerSections | null = null;
  private deckHoverActive = false;
  private hoveredDeckEventId: string | null = null;
  private hoveredCountryIso2: string | null = null;
  private countryHoverQueryController: CountryHoverQueryController<MapMouseEvent['point']> | null = null;
  /**
   * Aviation has a different invalidation cadence from hazards: route geometry,
   * hubs and live positions are static between data/camera changes, while only
   * the small motion subset changes during an animation frame.
   */
  private aviationLayerSections: AviationStaticLayerSections | null = null;

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

    const overlay = new MapboxOverlay({
      interleaved: true,
      layers: [],
      pickingRadius: 8,
      useDevicePixels: window.devicePixelRatio > 2 ? 2 : true,
      getCursor: ({ isDragging, isHovering }) => {
        if (isDragging) return 'grabbing';
        return isHovering || Boolean(this.hoveredCountryIso2) ? 'pointer' : 'grab';
      },
      getTooltip: (info: PickingInfo<WorldEventPickedObject>) => {
        const html = worldEventTooltipHtml(info.object, info.layer?.id || '');
        return html ? { html } : null;
      },
      onHover: (info: PickingInfo<WorldEventPickedObject>) => {
        const eventId = pickedWorldEvent(info.object)?.id ?? null;
        this.deckHoverActive = Boolean(info.object);
        this.updateMapCursor();
        if (eventId === this.hoveredDeckEventId) return;
        this.hoveredDeckEventId = eventId;
        callbacks.onEventHover(eventId);
      },
      onClick: (info: PickingInfo<WorldEventPickedObject>) => {
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
      },
    });
    this.overlay = overlay;

    map.once('load', () => {
      if (this.destroyed) return;
      if (!this.overlayMounted) {
        map.addControl(overlay as unknown as maplibregl.IControl);
        this.overlayMounted = true;
      }
      this.clearFallbackTimer();
      reinforceWorldEventBasemapLabels(map);
      this.ensureCountryHoverLayers();
      this.emitBasemapState(this.fallbackApplied ? 'local-fallback-ready' : 'primary-ready');
      this.render();
      this.syncAnimationLoop();
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
    if (staticLayersChanged) this.staticLayerSections = null;
    if (aviationLayersChanged) this.aviationLayerSections = null;
    // Hover and aviation-lens changes must not force Supercluster and all
    // static geometry to be rebuilt.  They are high-frequency UI updates.
    this.render(!staticLayersChanged);
    this.syncAnimationLoop();
  }

  setEvents(events: GeoEvent[]) {
    this.events = events;
    this.staticLayerSections = null;
    this.aviationLayerSections = null;
    this.render();
    this.syncAnimationLoop();
  }

  resize() {
    this.map?.resize();
    this.staticLayerSections = null;
    this.aviationLayerSections = null;
    this.render();
  }

  setReducedMotion(reduced: boolean) {
    this.reducedMotion = reduced;
    this.syncAnimationLoop();
    this.render(true);
  }

  pause() {
    this.paused = true;
    this.clearAllHover();
    this.cancelAnimationLoop();
    this.overlay?.setProps({ layers: [] });
  }

  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.resize();
    this.syncAnimationLoop();
  }

  destroy() {
    this.destroyed = true;
    this.clearFallbackTimer();
    this.clearContextRecoveryTimer();
    this.cancelAnimationLoop();
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
      map.remove();
    }
    this.map = null;
    this.overlay = null;
    this.staticLayerSections = null;
    this.aviationLayerSections = null;
    this.overlayMounted = false;
    this.countryHoverQueryController = null;
    this.deckHoverActive = false;
    this.hoveredDeckEventId = null;
    this.hoveredCountryIso2 = null;
    this.callbacks = null;
  }

  private render(reuseStaticLayers = false) {
    if (this.paused || !this.overlay || !this.state) return;
    const renderStartedAt = performance.now();
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
    const staticSections = reuseStaticLayers && this.staticLayerSections
      ? this.staticLayerSections
      : createWorldEventStaticLayerSections(this.events, this.state, true, viewport);
    this.staticLayerSections = staticSections;
    const aviationActive = this.state.activeLayerIds.includes('air-routes');
    const aviationSections = aviationActive
      ? this.aviationLayerSections || createAviationStaticLayerSections(this.events, this.state, viewport)
      : null;
    this.aviationLayerSections = aviationSections;
    const layers = [
      ...staticSections.geometry,
      ...(aviationSections?.routeLayers || []),
      ...(aviationSections ? createAviationDynamicLayers(aviationSections.data, this.animationTime) : []),
      ...(aviationSections?.markerLayers || []),
      ...staticSections.points,
    ];
    this.overlay.setProps({
      layers,
    });
    this.map?.triggerRepaint();
    this.reportRenderTiming(renderStartedAt, layers.length, Boolean(aviationSections));
  }

  private handleMoveEnd = () => {
    const map = this.map;
    if (!map || !this.callbacks) return;
    refreshWorldEventBasemapLabelDensity(map);
    this.staticLayerSections = null;
    this.aviationLayerSections = null;
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
    this.countryHoverQueryController?.cancel();
    this.clearAllHover();
  };

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
    this.render();
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
    const hadDeckEventHover = this.hoveredDeckEventId != null;
    this.deckHoverActive = false;
    this.clearCountryHover();
    this.hoveredDeckEventId = null;
    if (hadDeckEventHover) this.callbacks?.onEventHover(null);
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
    this.overlay?.setProps({ layers: [] });
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
    this.render();
    this.syncAnimationLoop();
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

  /** Development-only frame attribution mirroring WorldMonitor's 16 ms guard. */
  private reportRenderTiming(startedAt: number, layerCount: number, aviationActive: boolean) {
    if (!import.meta.env.DEV) return;
    const elapsed = performance.now() - startedAt;
    if (elapsed <= 16) return;
    const aviation = this.aviationLayerSections?.data;
    console.warn(
      `[WorldEventMap] render ${elapsed.toFixed(1)}ms (${layerCount} layers; `
      + `aviation=${aviationActive ? `${aviation?.routeMotionGroups.length ?? 0} runners, ${aviation?.flightMotionGroups.length ?? 0} seeded, ${aviation?.liveAircraft.length ?? 0} live` : 'off'})`,
    );
  }

  private hasAnimatedAviation() {
    const airRoutesActive = this.state?.activeLayerIds.includes('air-routes') === true;
    return airRoutesActive && this.events.some((event) => (
      event.category === 'infrastructure'
      && (event.properties.mapEntity === 'air-route' || event.properties.mapEntity === 'air-flight')
    ));
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
    const delta = boundedAnimationDelta(this.lastAnimationTimestamp, timestamp);
    this.lastAnimationTimestamp = timestamp;
    this.pendingAnimationDeltaMs += delta;
    if (this.pendingAnimationDeltaMs >= MAP_ANIMATION_FRAME_INTERVAL_MS) {
      this.animationTime = advanceAnimationTime(this.animationTime, this.pendingAnimationDeltaMs);
      this.pendingAnimationDeltaMs = 0;
      // A fixed 25 fps budget keeps the route motion legible without tying its
      // cost to a 60/120/144 Hz display. Pending user input still wins.
      if (this.shouldRenderAnimationFrame()) this.render(true);
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
  }

  private shouldRenderAnimationFrame() {
    const scheduling = (globalThis as unknown as {
      navigator?: { scheduling?: { isInputPending?: () => boolean } };
    }).navigator?.scheduling;
    return scheduling?.isInputPending?.() !== true;
  }
}
