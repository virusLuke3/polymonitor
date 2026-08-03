import { geoMercator, geoPath, type GeoProjection } from 'd3-geo';
import type {
  Feature,
  FeatureCollection,
  Geometry,
  MultiPolygon,
  Polygon,
  Position,
} from 'geojson';
import type { GeoEvent } from '../domain/types';
import {
  clampLatitude,
  clampLongitude,
  clampWorldEventZoom,
  type WorldEventMapState,
} from '../state/mapState';
import { eventColor, isHazardEvent, pointRadiusMeters } from './layerFactories/shared';
import { clusterEventPoints } from './layerFactories/eventPointLayer';
import {
  aviationRouteMotionPoints,
  aviationRouteTone,
  aviationSeededFlightPoints,
  selectAviationRenderData,
} from './layerFactories/aviationLayers';
import {
  countryBasemapLabels,
  visibleCountryBasemapLabels,
  type CountryBasemapLabel,
} from './countryBasemapLabels';
import {
  advanceAnimationTime,
  boundedAnimationDelta,
  MAP_ANIMATION_FRAME_INTERVAL_MS,
} from './animationClock';
import type { MapHoverPosition, MapRenderer, MapRendererCallbacks } from './MapRenderer';
import {
  worldEventTooltipModel,
  type WorldEventPickedObject,
} from './hoverTooltip';

const SVG_NS = 'http://www.w3.org/2000/svg';
const LOCAL_BASEMAP_URL = '/map-data/world-countries.geojson';
const LOCAL_BASEMAP_TIMEOUT_MS = 4_000;

function svgElement<K extends keyof SVGElementTagNameMap>(name: K) {
  return document.createElementNS(SVG_NS, name);
}

function cssColor([red, green, blue, alpha]: [number, number, number, number]) {
  return `rgba(${red}, ${green}, ${blue}, ${alpha / 255})`;
}

function eventGeoJson(event: GeoEvent): Geometry | null {
  if (!event.geometry || event.geometry.type === 'Point') return null;
  return normalizePolygonWinding(event.geometry as Geometry);
}

function aviationEntity(event: GeoEvent) {
  return event.category === 'infrastructure'
    ? String(event.properties.mapEntity || '')
    : '';
}

function aircraftMarker(x: number, y: number, angle: number) {
  const aircraft = svgElement('path');
  aircraft.setAttribute('d', 'M 11 0 L 2.5 3.1 L -1.7 10 L -3.8 9.3 L -2.4 2.9 L -10 0 L -2.4 -2.9 L -3.8 -9.3 L -1.7 -10 L 2.5 -3.1 Z');
  aircraft.setAttribute('transform', `translate(${x} ${y}) rotate(${angle})`);
  aircraft.classList.add('wm-world-event-svg-aircraft');
  return aircraft;
}

function ringSignedArea(ring: Position[]) {
  let area = 0;
  for (let index = 0; index < ring.length - 1; index += 1) {
    const current = ring[index]!;
    const next = ring[index + 1]!;
    area += (current[0] || 0) * (next[1] || 0) - (next[0] || 0) * (current[1] || 0);
  }
  return area / 2;
}

function d3Ring(ring: Position[], outer: boolean) {
  const clockwise = ringSignedArea(ring) < 0;
  return clockwise === outer ? ring : [...ring].reverse();
}

export function normalizePolygonWinding(geometry: Geometry): Geometry {
  if (geometry.type === 'Polygon') {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map((ring, index) => d3Ring(ring, index === 0)),
    } satisfies Polygon;
  }
  if (geometry.type === 'MultiPolygon') {
    return {
      ...geometry,
      coordinates: geometry.coordinates.map((polygon) => (
        polygon.map((ring, index) => d3Ring(ring, index === 0))
      )),
    } satisfies MultiPolygon;
  }
  return geometry;
}

function normalizedFeature(feature: Feature): Feature {
  return feature.geometry
    ? { ...feature, geometry: normalizePolygonWinding(feature.geometry) }
    : feature;
}

export class SvgMapRenderer implements MapRenderer {
  private host: HTMLElement | null = null;
  private svg: SVGSVGElement | null = null;
  private countryLayer: SVGGElement | null = null;
  private countryLabelLayer: SVGGElement | null = null;
  private eventLayer: SVGGElement | null = null;
  private callbacks: MapRendererCallbacks | null = null;
  private state: WorldEventMapState | null = null;
  private events: GeoEvent[] = [];
  private countries: FeatureCollection | null = null;
  private countryLabels: CountryBasemapLabel[] = [];
  private basemapController: AbortController | null = null;
  private basemapTimer: number | null = null;
  private paused = false;
  private reducedMotion = false;
  private animationFrame: number | null = null;
  private hoverFrame: number | null = null;
  private pendingHover: {
    eventId: string | null;
    tooltip: ReturnType<typeof worldEventTooltipModel>;
    position: MapHoverPosition | null;
  } | null = null;
  private lastAnimationTimestamp: number | null = null;
  private pendingAnimationDeltaMs = 0;
  private animationTime = 0;
  private destroyed = false;
  private drag:
    | { pointerId: number; x: number; y: number; center: WorldEventMapState['center'] }
    | null = null;

  async mount(container: HTMLElement, callbacks: MapRendererCallbacks) {
    if (this.svg) return;
    this.host = container;
    this.callbacks = callbacks;
    this.destroyed = false;
    callbacks.onBasemapStateChange('initializing');

    const svg = svgElement('svg');
    svg.classList.add('wm-world-event-svg-map');
    svg.classList.toggle('reduced-motion', this.reducedMotion);
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    const countries = svgElement('g');
    countries.classList.add('wm-world-event-svg-countries');
    const countryLabels = svgElement('g');
    countryLabels.classList.add('wm-world-event-svg-country-labels');
    const events = svgElement('g');
    events.classList.add('wm-world-event-svg-events');
    svg.append(countries, countryLabels, events);
    container.append(svg);
    this.svg = svg;
    this.countryLayer = countries;
    this.countryLabelLayer = countryLabels;
    this.eventLayer = events;

    container.addEventListener('wheel', this.handleWheel, { passive: false });
    container.addEventListener('keydown', this.handleKeyDown);
    container.addEventListener('pointerdown', this.handlePointerDown);
    container.addEventListener('pointermove', this.handlePointerMove);
    container.addEventListener('pointerup', this.handlePointerUp);
    container.addEventListener('pointercancel', this.handlePointerUp);

    this.render();
    this.syncAnimationLoop();
    await this.loadLocalBasemap();
  }

  setState(state: WorldEventMapState) {
    this.state = state;
    this.render();
    this.syncAnimationLoop();
  }

  setEvents(events: GeoEvent[]) {
    this.events = events;
    this.render();
    this.syncAnimationLoop();
  }

  resize() {
    this.render();
  }

  setReducedMotion(reduced: boolean) {
    this.reducedMotion = reduced;
    this.svg?.classList.toggle('reduced-motion', reduced);
    this.syncAnimationLoop();
    this.render();
  }

  pause() {
    this.paused = true;
    this.clearHover();
    this.cancelAnimationLoop();
  }

  resume() {
    if (!this.paused) return;
    this.paused = false;
    this.render();
    this.syncAnimationLoop();
  }

  destroy() {
    this.destroyed = true;
    this.clearHover();
    this.cancelAnimationLoop();
    this.clearBasemapTimer();
    this.basemapController?.abort();
    this.basemapController = null;
    const host = this.host;
    if (host) {
      host.removeEventListener('wheel', this.handleWheel);
      host.removeEventListener('keydown', this.handleKeyDown);
      host.removeEventListener('pointerdown', this.handlePointerDown);
      host.removeEventListener('pointermove', this.handlePointerMove);
      host.removeEventListener('pointerup', this.handlePointerUp);
      host.removeEventListener('pointercancel', this.handlePointerUp);
    }
    this.svg?.remove();
    this.host = null;
    this.svg = null;
    this.countryLayer = null;
    this.countryLabelLayer = null;
    this.eventLayer = null;
    this.countryLabels = [];
    this.callbacks = null;
    this.drag = null;
  }

  private async loadLocalBasemap() {
    this.basemapController = new AbortController();
    this.basemapTimer = window.setTimeout(
      () => this.basemapController?.abort(),
      LOCAL_BASEMAP_TIMEOUT_MS,
    );
    try {
      const response = await fetch(LOCAL_BASEMAP_URL, {
        headers: { Accept: 'application/geo+json, application/json' },
        signal: this.basemapController.signal,
      });
      if (!response.ok) throw new Error(`Local basemap returned HTTP ${response.status}.`);
      const payload = await response.json() as FeatureCollection;
      if (payload?.type !== 'FeatureCollection' || !Array.isArray(payload.features)) {
        throw new Error('Local basemap is not a GeoJSON FeatureCollection.');
      }
      if (this.destroyed) return;
      this.countries = {
        ...payload,
        features: payload.features.map(normalizedFeature),
      };
      this.countryLabels = countryBasemapLabels(this.countries);
      this.render();
      this.callbacks?.onBasemapStateChange('renderer-fallback-ready');
    } catch (error) {
      if (this.destroyed) return;
      const message = this.basemapController.signal.aborted
        ? `Local SVG basemap timed out after ${LOCAL_BASEMAP_TIMEOUT_MS / 1000}s.`
        : error instanceof Error ? error.message : String(error);
      this.callbacks?.onError(new Error(message));
      // Real events remain selectable even if the decorative country geometry fails.
      this.callbacks?.onBasemapStateChange('renderer-fallback-ready');
    } finally {
      this.clearBasemapTimer();
      this.basemapController = null;
    }
  }

  private projection(width: number, height: number): GeoProjection {
    const state = this.state;
    const center = state?.center || { lon: 20, lat: 24 };
    const zoom = state?.zoom ?? 1.25;
    return geoMercator()
      .center([center.lon, center.lat])
      .scale((512 / (2 * Math.PI)) * Math.pow(2, zoom))
      .translate([width / 2, height / 2]);
  }

  private render() {
    if (this.paused || !this.svg || !this.countryLayer || !this.countryLabelLayer || !this.eventLayer || !this.host) return;
    const width = Math.max(1, this.host.clientWidth || 1_200);
    const height = Math.max(1, this.host.clientHeight || 620);
    this.svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
    const projection = this.projection(width, height);
    const path = geoPath(projection);

    this.countryLayer.replaceChildren();
    for (const feature of this.countries?.features || []) {
      const data = path(feature);
      if (!data) continue;
      const country = svgElement('path');
      country.setAttribute('d', data);
      this.countryLayer.append(country);
    }

    this.countryLabelLayer.replaceChildren();
    const occupiedCountryLabels: Array<{ left: number; top: number; right: number; bottom: number }> = [];
    const labelSize = (this.state?.zoom || 1.5) < 2.4 ? 11 : 12;
    for (const label of visibleCountryBasemapLabels(this.countryLabels, this.state?.zoom || 1.5)) {
      const position = projection(label.coordinates);
      if (!position) continue;
      const [x, y] = position;
      const halfWidth = Math.max(24, label.name.length * labelSize * 0.29);
      const box = { left: x - halfWidth, top: y - labelSize, right: x + halfWidth, bottom: y + labelSize };
      if (x < -halfWidth || x > width + halfWidth || y < -labelSize || y > height + labelSize) continue;
      if (occupiedCountryLabels.some((other) => (
        box.left < other.right && box.right > other.left && box.top < other.bottom && box.bottom > other.top
      ))) continue;
      const text = svgElement('text');
      text.classList.add('wm-world-event-svg-country-label');
      text.setAttribute('x', String(x));
      text.setAttribute('y', String(y));
      text.setAttribute('font-size', String(labelSize));
      text.textContent = label.name;
      this.countryLabelLayer.append(text);
      occupiedCountryLabels.push(box);
    }

    this.eventLayer.replaceChildren();
    const state = this.state;
    const selectedId = this.state?.selectedEventId;
    const aviation = state
      ? selectAviationRenderData(this.events, state)
      : { routes: [], hubs: [], flights: [], liveAircraft: [] };
    const visibleAviationIds = new Set([
      ...aviation.routes,
      ...aviation.hubs,
      ...aviation.liveAircraft,
    ].map((event) => event.id));
    const renderEvents = this.events.filter((event) => {
      const entity = aviationEntity(event);
      if (!entity) return true;
      if (entity === 'air-flight') return false;
      return visibleAviationIds.has(event.id);
    });
    const pointEvents = renderEvents.filter((event) => (
      event.geometry?.type === 'Point' && !aviationEntity(event)
    ));
    const { singles, clusters } = clusterEventPoints(
      pointEvents,
      this.state?.zoom ?? 1.25,
      selectedId || null,
    );
    for (const event of renderEvents) {
      if (!event.geometry || event.geometry.type === 'Point') continue;
      const geometry = eventGeoJson(event);
      if (!geometry) continue;
      const data = path(geometry);
      if (!data) continue;
      const shape = svgElement('path');
      shape.setAttribute('d', data);
      shape.classList.add('wm-world-event-svg-shape');
      this.decorateEventElement(shape, event, event.id === selectedId);
      if (event.geometry.type === 'LineString') {
        shape.setAttribute('fill', 'none');
        if (aviationEntity(event) === 'air-route') {
          shape.classList.add('wm-world-event-svg-air-route');
          shape.setAttribute('stroke', cssColor(aviationRouteTone(
            event,
            event.id === selectedId ? 238 : 126,
          )));
          shape.setAttribute('stroke-width', event.id === selectedId ? '2.2' : '0.85');
        }
      }
      this.eventLayer.append(shape);
    }
    for (const cluster of clusters) {
      const position = projection(cluster.coordinates);
      if (!position) continue;
      const [x, y] = position;
      if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;
      const group = svgElement('g');
      group.classList.add('wm-world-event-svg-cluster');
      group.setAttribute('role', 'button');
      group.setAttribute('tabindex', '0');
      group.setAttribute('aria-label', `${cluster.count} mapped events. Zoom in to expand.`);
      const title = svgElement('title');
      title.textContent = `${cluster.count} mapped events · ${cluster.severity.toUpperCase()} · click to expand`;
      const point = svgElement('circle');
      point.setAttribute('cx', String(x));
      point.setAttribute('cy', String(y));
      point.setAttribute('r', String(Math.min(24, Math.max(10, 7 + Math.log2(cluster.count + 1) * 2.4))));
      point.setAttribute('fill', cssColor(cluster.color));
      const label = svgElement('text');
      label.setAttribute('x', String(x));
      label.setAttribute('y', String(y));
      label.textContent = String(cluster.count);
      const expand = () => this.callbacks?.onCameraChange({
        center: { lon: cluster.coordinates[0], lat: cluster.coordinates[1] },
        zoom: clampWorldEventZoom(cluster.expansionZoom),
      });
      const showClusterTooltip = (pointerEvent: PointerEvent) => {
        this.queueHoverTooltip(cluster, pointerEvent, 'world-event-clusters');
      };
      group.addEventListener('pointerenter', showClusterTooltip);
      group.addEventListener('pointermove', showClusterTooltip);
      group.addEventListener('pointerleave', this.clearHover);
      group.addEventListener('pointerdown', (pointerEvent) => pointerEvent.stopPropagation());
      group.addEventListener('click', expand);
      group.addEventListener('keydown', (keyboardEvent) => {
        if (keyboardEvent.key !== 'Enter' && keyboardEvent.key !== ' ') return;
        keyboardEvent.preventDefault();
        expand();
      });
      group.append(title, point, label);
      this.eventLayer.append(group);
    }
    for (const event of singles) {
      if (event.geometry?.type !== 'Point') continue;
      const position = projection(event.geometry.coordinates);
      if (!position) continue;
      const [x, y] = position;
      if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;
      const point = svgElement('circle');
      const radius = Math.max(
        4,
        Math.min(14, Math.log2(Math.max(2, pointRadiusMeters(event) / 1_000)) * 1.8),
      );
      point.setAttribute('cx', String(x));
      point.setAttribute('cy', String(y));
      point.setAttribute('r', String(event.id === selectedId ? radius + 2 : radius));
      point.classList.add('wm-world-event-svg-point');
      this.decorateEventElement(point, event, event.id === selectedId);
      this.eventLayer.append(point);
    }
    for (const event of [...aviation.hubs, ...aviation.liveAircraft]) {
      if (event.geometry?.type !== 'Point') continue;
      const position = projection(event.geometry.coordinates);
      if (!position) continue;
      const [x, y] = position;
      if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;
      if (aviationEntity(event) === 'live-aircraft') {
        const aircraft = aircraftMarker(x, y, Number(event.properties.heading || 0) - 90);
        this.decorateEventElement(aircraft, event, event.id === selectedId);
        this.eventLayer.append(aircraft);
        continue;
      }
      const hub = svgElement('circle');
      hub.setAttribute('cx', String(x));
      hub.setAttribute('cy', String(y));
      hub.setAttribute('r', event.id === selectedId ? '5.5' : '3.5');
      hub.classList.add('wm-world-event-svg-air-hub');
      this.decorateEventElement(hub, event, event.id === selectedId);
      this.eventLayer.append(hub);
    }
    for (const runner of aviationRouteMotionPoints(aviation.routes, this.animationTime)) {
      const position = projection(runner.position);
      if (!position) continue;
      const [x, y] = position;
      if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;
      const mote = svgElement('circle');
      mote.classList.add('wm-world-event-svg-route-runner');
      mote.setAttribute('cx', String(x));
      mote.setAttribute('cy', String(y));
      mote.setAttribute('r', '2.4');
      mote.setAttribute('fill', cssColor(runner.color));
      this.eventLayer.append(mote);
    }
    for (const flight of aviationSeededFlightPoints(aviation.flights, this.animationTime)) {
      const position = projection(flight.position);
      if (!position) continue;
      const [x, y] = position;
      if (x < -40 || x > width + 40 || y < -40 || y > height + 40) continue;
      const aircraft = aircraftMarker(x, y, flight.angle);
      this.decorateEventElement(aircraft, flight.event, flight.event.id === selectedId);
      this.eventLayer.append(aircraft);
    }
  }

  private decorateEventElement(element: SVGElement, event: GeoEvent, selected: boolean) {
    const color = cssColor(eventColor(event, selected ? 250 : 205));
    element.setAttribute('fill', color);
    element.setAttribute('stroke', selected ? '#fffade' : color);
    element.setAttribute('stroke-width', selected ? '2.5' : '1.2');
    element.setAttribute('role', 'button');
    element.setAttribute('tabindex', '0');
    element.setAttribute('aria-label', `${event.title}. ${event.severity} severity.`);
    element.dataset.eventId = event.id;
    element.classList.add(`severity-${event.severity}`);
    if (selected) element.classList.add('is-selected');
    if (isHazardEvent(event)) element.classList.add(`hazard-${event.hazardKind}`);
    const title = svgElement('title');
    title.textContent = `${event.title} · ${event.locationLabel || event.severity}`;
    element.append(title);
    const showEventTooltip = (pointerEvent: PointerEvent) => {
      this.queueHoverTooltip(event, pointerEvent, '', event.id);
    };
    element.addEventListener('pointerenter', showEventTooltip);
    element.addEventListener('pointermove', showEventTooltip);
    element.addEventListener('pointerleave', this.clearHover);
    element.addEventListener('pointerdown', (pointerEvent) => pointerEvent.stopPropagation());
    element.addEventListener('click', (pointerEvent) => {
      pointerEvent.stopPropagation();
      this.callbacks?.onEventSelect(event.id);
    });
    element.addEventListener('keydown', (keyboardEvent) => {
      if (keyboardEvent.key !== 'Enter' && keyboardEvent.key !== ' ') return;
      keyboardEvent.preventDefault();
      this.callbacks?.onEventSelect(event.id);
    });
  }

  private handleWheel = (event: WheelEvent) => {
    if (!this.state || !this.callbacks) return;
    event.preventDefault();
    const delta = event.deltaY > 0 ? -0.35 : 0.35;
    this.callbacks.onCameraChange({
      center: this.state.center,
      zoom: clampWorldEventZoom(this.state.zoom + delta),
    });
  };

  private handleKeyDown = (event: KeyboardEvent) => {
    if (!this.state || !this.callbacks) return;
    const degreesPerStep = 18 / Math.pow(2, Math.max(0, this.state.zoom - 1));
    let { lon, lat } = this.state.center;
    let zoom = this.state.zoom;
    if (event.key === '+' || event.key === '=') zoom = clampWorldEventZoom(zoom + 0.5);
    else if (event.key === '-') zoom = clampWorldEventZoom(zoom - 0.5);
    else if (event.key === 'ArrowLeft') lon -= degreesPerStep;
    else if (event.key === 'ArrowRight') lon += degreesPerStep;
    else if (event.key === 'ArrowUp') lat += degreesPerStep / 2;
    else if (event.key === 'ArrowDown') lat -= degreesPerStep / 2;
    else return;
    event.preventDefault();
    this.callbacks.onCameraChange({
      center: { lon: clampLongitude(lon), lat: clampLatitude(lat) },
      zoom,
    });
  };

  private handlePointerDown = (event: PointerEvent) => {
    if (!this.state || event.button !== 0) return;
    this.clearHover();
    this.drag = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      center: { ...this.state.center },
    };
    this.host?.setPointerCapture(event.pointerId);
  };

  private handlePointerMove = (event: PointerEvent) => {
    if (!this.drag || event.pointerId !== this.drag.pointerId || !this.state || !this.callbacks) return;
    const degreesPerPixel = 360 / (512 * Math.pow(2, this.state.zoom));
    this.callbacks.onCameraChange({
      center: {
        lon: clampLongitude(this.drag.center.lon - (event.clientX - this.drag.x) * degreesPerPixel),
        lat: clampLatitude(this.drag.center.lat + (event.clientY - this.drag.y) * degreesPerPixel),
      },
      zoom: this.state.zoom,
    });
  };

  private handlePointerUp = (event: PointerEvent) => {
    if (!this.drag || event.pointerId !== this.drag.pointerId) return;
    this.host?.releasePointerCapture(event.pointerId);
    this.drag = null;
  };

  private clearBasemapTimer() {
    if (this.basemapTimer == null) return;
    window.clearTimeout(this.basemapTimer);
    this.basemapTimer = null;
  }

  private pointerPosition(pointerEvent: PointerEvent) {
    const bounds = this.svg?.getBoundingClientRect();
    return bounds ? {
      x: Math.max(12, Math.min(bounds.width - 12, pointerEvent.clientX - bounds.left + 14)),
      y: Math.max(12, Math.min(bounds.height - 12, pointerEvent.clientY - bounds.top + 14)),
    } : null;
  }

  private queueHoverTooltip(
    object: WorldEventPickedObject,
    pointerEvent: PointerEvent,
    layerId = '',
    eventId: string | null = null,
  ) {
    this.pendingHover = {
      eventId,
      tooltip: worldEventTooltipModel(object, layerId),
      position: this.pointerPosition(pointerEvent),
    };
    if (this.hoverFrame != null) return;
    this.hoverFrame = window.requestAnimationFrame(() => {
      this.hoverFrame = null;
      const pending = this.pendingHover;
      this.pendingHover = null;
      if (!pending) return;
      this.callbacks?.onEventHover(pending.eventId, pending.position);
      this.callbacks?.onHoverTooltip(pending.tooltip, pending.position);
    });
  }

  private clearHover = () => {
    if (this.hoverFrame != null) window.cancelAnimationFrame(this.hoverFrame);
    this.hoverFrame = null;
    this.pendingHover = null;
    this.callbacks?.onEventHover(null);
    this.callbacks?.onHoverTooltip(null);
  };

  private hasAnimatedAviation() {
    return this.state?.activeLayerIds.includes('air-routes') === true
      && this.events.some((event) => (
        aviationEntity(event) === 'air-route' || aviationEntity(event) === 'air-flight'
      ));
  }

  private syncAnimationLoop() {
    if (!this.svg || this.destroyed || this.paused || this.reducedMotion || !this.hasAnimatedAviation()) {
      this.cancelAnimationLoop();
      return;
    }
    if (this.animationFrame != null) return;
    this.animationFrame = window.requestAnimationFrame(this.handleAnimationFrame);
  }

  private handleAnimationFrame = (timestamp: number) => {
    this.animationFrame = null;
    if (this.destroyed || this.paused || this.reducedMotion || !this.hasAnimatedAviation()) return;
    this.pendingAnimationDeltaMs += boundedAnimationDelta(this.lastAnimationTimestamp, timestamp);
    this.lastAnimationTimestamp = timestamp;
    if (this.pendingAnimationDeltaMs >= MAP_ANIMATION_FRAME_INTERVAL_MS) {
      this.animationTime = advanceAnimationTime(this.animationTime, this.pendingAnimationDeltaMs);
      this.pendingAnimationDeltaMs = 0;
      this.render();
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
}
