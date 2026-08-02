import { MapboxOverlay } from '@deck.gl/mapbox';
import type { PickingInfo } from '@deck.gl/core';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
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
  type EventCluster,
  type AviationStaticLayerSections,
  type WorldEventStaticLayerSections,
} from './layerFactories';
import {
  advanceAnimationTime,
  boundedAnimationDelta,
  MAP_ANIMATION_FRAME_INTERVAL_MS,
} from './animationClock';

type PickedObject = GeoEvent | EventCluster | { properties?: { event?: GeoEvent } };

function pickedEvent(object?: PickedObject | null): GeoEvent | null {
  if (!object) return null;
  if ('properties' in object && object.properties?.event) return object.properties.event as GeoEvent;
  if ('kind' in object && object.kind === 'event-cluster') return null;
  return object as GeoEvent;
}

function pickedCluster(object?: PickedObject | null): EventCluster | null {
  return object && 'kind' in object && object.kind === 'event-cluster'
    ? object
    : null;
}

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

    const overlay = new MapboxOverlay({
      interleaved: true,
      layers: [],
      pickingRadius: 8,
      useDevicePixels: window.devicePixelRatio > 2 ? 2 : true,
      onHover: (info: PickingInfo<PickedObject>) => {
        const event = pickedEvent(info.object);
        map.getCanvas().style.cursor = info.object ? 'pointer' : '';
        callbacks.onEventHover(event?.id ?? null);
      },
      onClick: (info: PickingInfo<PickedObject>) => {
        const cluster = pickedCluster(info.object);
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
        callbacks.onEventSelect(pickedEvent(info.object)?.id ?? null);
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
      this.emitBasemapState(this.fallbackApplied ? 'local-fallback-ready' : 'primary-ready');
      this.render();
      this.syncAnimationLoop();
    });
    map.on('style.load', this.handleStyleLoad);
    map.on('moveend', this.handleMoveEnd);
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
    const map = this.map;
    if (map) {
      map.off('style.load', this.handleStyleLoad);
      map.off('moveend', this.handleMoveEnd);
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

  private handleStyleLoad = () => {
    if (!this.map || this.destroyed) return;
    this.clearFallbackTimer();
    reinforceWorldEventBasemapLabels(this.map);
    this.emitBasemapState(this.fallbackApplied ? 'local-fallback-ready' : 'primary-ready');
    this.render();
  };

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
