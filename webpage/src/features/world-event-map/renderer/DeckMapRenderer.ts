import { MapboxOverlay } from '@deck.gl/mapbox';
import type { PickingInfo } from '@deck.gl/core';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { getWeatherMapFallbackStyle, getWeatherMapStyle } from '@/config/weatherBasemap';
import type { GeoEvent } from '../domain/types';
import type { WorldEventMapState } from '../state/mapState';
import type { BasemapState, MapRenderer, MapRendererCallbacks } from './MapRenderer';
import { createWorldEventLayers, type EventCluster } from './layerFactories';

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
  private fallbackTimer: number | null = null;
  private contextRecoveryTimer: number | null = null;
  private contextRecoveryAttempts = 0;
  private overlayMounted = false;
  private paused = false;
  private destroyed = false;
  private applyingCamera = false;
  private reducedMotion = false;
  private animationFrame: number | null = null;
  private animationStartedAt = 0;
  private lastAnimationRenderAt = 0;
  private animationTime = 0;

  async mount(container: HTMLElement, callbacks: MapRendererCallbacks) {
    if (this.map) return;
    this.destroyed = false;
    this.callbacks = callbacks;
    this.emitBasemapState('initializing');
    const state = this.state;
    const map = new maplibregl.Map({
      container,
      style: getWeatherMapStyle('dark'),
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
      this.applyLocalFallback(new Error('Primary basemap did not become ready within 2.5 seconds.'));
    }, 2_500);
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
    this.render();
    this.syncAnimationLoop();
  }

  setEvents(events: GeoEvent[]) {
    this.events = events;
    this.render();
    this.syncAnimationLoop();
  }

  resize() {
    this.map?.resize();
    this.render();
  }

  setReducedMotion(reduced: boolean) {
    this.reducedMotion = reduced;
    this.syncAnimationLoop();
    this.render();
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
    this.overlayMounted = false;
    this.callbacks = null;
  }

  private render() {
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
    this.overlay.setProps({
      layers: createWorldEventLayers(
        this.events,
        this.state,
        true,
        viewport,
        this.animationTime,
        !this.reducedMotion,
      ),
    });
    this.map?.triggerRepaint();
  }

  private handleMoveEnd = () => {
    const map = this.map;
    if (!map || !this.callbacks) return;
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
    this.emitBasemapState(this.fallbackApplied ? 'local-fallback-ready' : 'primary-ready');
    this.render();
  };

  private handleMapError = (event: { error?: Error; message?: string }) => {
    const message = event.error?.message || event.message || 'Unknown MapLibre error';
    if (!this.fallbackApplied && /fetch|ajax|cors|network|403|forbidden|tile|style/i.test(message)) {
      this.applyLocalFallback(new Error(message));
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

  private hasAnimatedEvents() {
    return this.events.some((event) => (
      (event.category === 'infrastructure'
        && (event.properties.mapEntity === 'air-route' || event.properties.mapEntity === 'air-flight'))
      || ((event.category === 'natural-hazard' || event.category === 'weather')
        && (event.severity === 'warning' || event.severity === 'critical'))
    ));
  }

  private syncAnimationLoop() {
    if (this.destroyed || this.paused || this.reducedMotion || !this.hasAnimatedEvents()) {
      this.cancelAnimationLoop();
      return;
    }
    if (this.animationFrame != null) return;
    this.animationStartedAt = performance.now() - this.animationTime * 1_000;
    this.animationFrame = window.requestAnimationFrame(this.handleAnimationFrame);
  }

  private handleAnimationFrame = (timestamp: number) => {
    this.animationFrame = null;
    if (this.destroyed || this.paused || this.reducedMotion || !this.hasAnimatedEvents()) return;
    if (timestamp - this.lastAnimationRenderAt >= 40) {
      this.animationTime = Math.max(0, (timestamp - this.animationStartedAt) / 1_000);
      this.lastAnimationRenderAt = timestamp;
      this.render();
    }
    this.animationFrame = window.requestAnimationFrame(this.handleAnimationFrame);
  };

  private cancelAnimationLoop() {
    if (this.animationFrame != null) {
      window.cancelAnimationFrame(this.animationFrame);
      this.animationFrame = null;
    }
  }
}
