import { IconLayer, PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { Layer, LayersList } from '@deck.gl/core';
import type { GeoEvent } from '../../domain/types';
import type {
  AviationLensMode,
  AviationRiskSource,
  WorldEventMapState,
} from '../../state/mapState';
import { MAP_MONO_FONT_FAMILY } from './shared';

const AIRCRAFT_ICON_ATLAS = '/map-icons/aircraft-east.svg';
const AIRCRAFT_ICON_MAPPING = {
  aircraft: { x: 0, y: 0, width: 32, height: 32, anchorX: 16, anchorY: 16, mask: true },
};

type AviationEntity = 'air-route' | 'air-hub' | 'air-flight' | 'live-aircraft';

export type AviationMotionPoint = {
  id: string;
  event: GeoEvent;
  position: [number, number];
  color: [number, number, number, number];
  angle: number;
  size: number;
};

export type AviationRenderData = {
  routes: GeoEvent[];
  hubs: GeoEvent[];
  flights: GeoEvent[];
  liveAircraft: GeoEvent[];
};

export type AviationLayerStats = {
  routes: number;
  visibleRoutes: number;
  hubs: number;
  flights: number;
  liveAircraft: number;
  watchRoutes: number;
  riskSources: Record<AviationRiskSource, number>;
};

function entity(event: GeoEvent): AviationEntity | null {
  if (event.category !== 'infrastructure') return null;
  const value = String(event.properties.mapEntity || '');
  return value === 'air-route'
    || value === 'air-hub'
    || value === 'air-flight'
    || value === 'live-aircraft'
    ? value
    : null;
}

function numberProperty(event: GeoEvent, key: string, fallback = 0) {
  const value = Number(event.properties[key]);
  return Number.isFinite(value) ? value : fallback;
}

function stringProperty(event: GeoEvent, key: string) {
  return String(event.properties[key] || '').trim();
}

function riskSources(event: GeoEvent) {
  return Array.isArray(event.properties.riskSources)
    ? event.properties.riskSources.map(String).filter(Boolean)
    : [];
}

function groupId(event: GeoEvent, key: 'routeId' | 'flightId') {
  return stringProperty(event, key) || event.id;
}

function groupSegments(events: GeoEvent[], key: 'routeId' | 'flightId') {
  const groups = new Map<string, GeoEvent[]>();
  for (const event of events) {
    const id = groupId(event, key);
    const values = groups.get(id) || [];
    values.push(event);
    groups.set(id, values);
  }
  for (const values of groups.values()) {
    values.sort((left, right) => (
      numberProperty(left, 'segmentIndex') - numberProperty(right, 'segmentIndex')
    ));
  }
  return groups;
}

function isWatch(event: GeoEvent) {
  return event.severity !== 'info'
    || numberProperty(event, 'riskScore') >= 35
    || riskSources(event).length > 0
    || stringProperty(event, 'status').toLowerCase() === 'watch';
}

function matchesRiskSource(event: GeoEvent, source: AviationRiskSource) {
  return source === 'all' || riskSources(event).includes(source);
}

function matchesLens(event: GeoEvent, lens: AviationLensMode, source: AviationRiskSource) {
  if (lens === 'trunk') return stringProperty(event, 'layer') === 'trunk';
  if (lens === 'watch') return isWatch(event) && matchesRiskSource(event, source);
  return true;
}

function routePriority(event: GeoEvent) {
  const layer = stringProperty(event, 'layer');
  const layerScore = layer === 'trunk' ? 3 : layer === 'international' ? 2 : 1;
  return (isWatch(event) ? 1_000 : 0)
    + layerScore * 100
    + numberProperty(event, 'trafficScore')
    + numberProperty(event, 'riskScore') * 1.5;
}

function routeBudget(zoom: number, lens: AviationLensMode) {
  if (lens === 'watch') return zoom < 2 ? 90 : 180;
  if (lens === 'trunk') return zoom < 2 ? 120 : 240;
  if (zoom < 1.6) return 160;
  if (zoom < 2.8) return 300;
  return 520;
}

function selectedRouteSegments(
  routes: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>,
) {
  return [...groupSegments(routes, 'routeId').values()]
    .filter((segments) => matchesLens(segments[0]!, state.aviationLens, state.aviationRiskSource))
    .sort((left, right) => routePriority(right[0]!) - routePriority(left[0]!))
    .slice(0, routeBudget(state.zoom, state.aviationLens))
    .flat();
}

export function aviationRouteTone(event: GeoEvent, alpha: number): [number, number, number, number] {
  const risks = riskSources(event);
  if (risks.includes('conflict')) return [255, 96, 76, alpha];
  if (risks.includes('weather')) return [45, 212, 191, alpha];
  if (risks.includes('corridor')) return [238, 199, 71, alpha];
  if (stringProperty(event, 'layer') === 'trunk') return [94, 238, 255, alpha];
  if (stringProperty(event, 'layer') === 'international') return [68, 176, 255, alpha];
  return [98, 126, 156, alpha];
}

function routeWidth(event: GeoEvent, selectedEventId: string | null) {
  if (event.id === selectedEventId) return 2.4;
  const layer = stringProperty(event, 'layer');
  const base = layer === 'trunk' ? 1.25 : layer === 'international' ? 0.9 : 0.55;
  return Math.max(0.5, Math.min(2.2, base + numberProperty(event, 'trafficScore') / 130));
}

function hashUnit(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 0xffffffff;
}

function pointAlongPath(path: [number, number][], progress: number) {
  if (!path.length) return [0, 0] as [number, number];
  if (path.length === 1) return path[0]!;
  const scaled = Math.max(0, Math.min(0.999999, progress)) * (path.length - 1);
  const index = Math.floor(scaled);
  const nextIndex = Math.min(path.length - 1, index + 1);
  const localProgress = scaled - index;
  const current = path[index]!;
  const next = path[nextIndex]!;
  return [
    current[0] + (next[0] - current[0]) * localProgress,
    current[1] + (next[1] - current[1]) * localProgress,
  ] as [number, number];
}

function angleAlongPath(path: [number, number][], progress: number) {
  const current = pointAlongPath(path, progress);
  const next = pointAlongPath(path, Math.min(0.999999, progress + 0.012));
  return (Math.atan2(next[1] - current[1], next[0] - current[0]) * 180) / Math.PI;
}

function motionPointForSegments(
  id: string,
  segments: GeoEvent[],
  progress: number,
  color: [number, number, number, number],
  size: number,
): AviationMotionPoint | null {
  if (!segments.length) return null;
  const segmentProgress = Math.max(0, Math.min(0.999999, progress)) * segments.length;
  const segment = segments[Math.min(segments.length - 1, Math.floor(segmentProgress))]!;
  if (segment.geometry?.type !== 'LineString') return null;
  const localProgress = segmentProgress - Math.floor(segmentProgress);
  return {
    id,
    event: segment,
    position: pointAlongPath(segment.geometry.coordinates, localProgress),
    color,
    angle: angleAlongPath(segment.geometry.coordinates, localProgress),
    size,
  };
}

export function aviationRouteMotionPoints(routes: GeoEvent[], animationTime: number) {
  const points: AviationMotionPoint[] = [];
  for (const [routeId, segments] of groupSegments(routes, 'routeId')) {
    const event = segments[0]!;
    const speed = Math.max(0.012, Math.min(0.08, numberProperty(event, 'speed', 0.028)));
    const progress = (hashUnit(routeId) + animationTime * speed) % 1;
    const point = motionPointForSegments(routeId, segments, progress, aviationRouteTone(event, 230), 11);
    if (point) points.push(point);
  }
  return points;
}

export function aviationSeededFlightPoints(flights: GeoEvent[], animationTime: number) {
  const points: AviationMotionPoint[] = [];
  for (const [flightId, segments] of groupSegments(flights, 'flightId')) {
    const event = segments[0]!;
    const phase = numberProperty(event, 'phase', hashUnit(flightId));
    const speed = Math.max(0.012, Math.min(0.16, numberProperty(event, 'speed', 0.06)));
    const progress = (phase + animationTime * speed) % 1;
    const color = isWatch(event)
      ? [255, 214, 84, 245] as [number, number, number, number]
      : [92, 241, 255, 235] as [number, number, number, number];
    const point = motionPointForSegments(flightId, segments, progress, color, 14);
    if (point) points.push(point);
  }
  return points;
}

export function aviationLayerStats(events: GeoEvent[], visibleRoutes = events): AviationLayerStats {
  const routes = events.filter((event) => entity(event) === 'air-route');
  const routeRepresentatives = [...groupSegments(routes, 'routeId').values()].map((segments) => segments[0]!);
  const visibleRouteCount = groupSegments(
    visibleRoutes.filter((event) => entity(event) === 'air-route'),
    'routeId',
  ).size;
  const risks: Record<AviationRiskSource, number> = {
    all: routeRepresentatives.filter(isWatch).length,
    weather: 0,
    conflict: 0,
    corridor: 0,
  };
  for (const route of routeRepresentatives) {
    for (const source of riskSources(route)) {
      if (source === 'weather' || source === 'conflict' || source === 'corridor') risks[source] += 1;
    }
  }
  return {
    routes: routeRepresentatives.length,
    visibleRoutes: visibleRouteCount,
    hubs: events.filter((event) => entity(event) === 'air-hub').length,
    flights: groupSegments(events.filter((event) => entity(event) === 'air-flight'), 'flightId').size,
    liveAircraft: events.filter((event) => entity(event) === 'live-aircraft').length,
    watchRoutes: routeRepresentatives.filter(isWatch).length,
    riskSources: risks,
  };
}

export function aviationLayerStatsForState(
  events: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>,
) {
  const routes = selectedRouteSegments(
    events.filter((event) => entity(event) === 'air-route'),
    state,
  );
  return aviationLayerStats(events, routes);
}

export function selectAviationRenderData(
  events: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>,
): AviationRenderData {
  const routes = selectedRouteSegments(
    events.filter((event) => entity(event) === 'air-route'),
    state,
  );
  const hubs = events
    .filter((event) => entity(event) === 'air-hub' && matchesLens(event, state.aviationLens, state.aviationRiskSource))
    .sort((left, right) => numberProperty(right, 'routeCount') - numberProperty(left, 'routeCount'))
    .slice(0, state.zoom < 2.2 ? 12 : 30);
  const flights = events.filter(
    (event) => entity(event) === 'air-flight' && matchesLens(event, state.aviationLens, state.aviationRiskSource),
  );
  const liveAircraft = events.filter(
    (event) => entity(event) === 'live-aircraft' && matchesLens(event, state.aviationLens, state.aviationRiskSource),
  );
  return { routes, hubs, flights, liveAircraft };
}

export function createAviationLayers(
  events: GeoEvent[],
  state: WorldEventMapState,
  animationTime = 0,
): LayersList {
  const {
    routes,
    hubs,
    flights,
    liveAircraft,
  } = selectAviationRenderData(events, state);
  const routeRunners = aviationRouteMotionPoints(routes, animationTime);
  const flightPoints = aviationSeededFlightPoints(flights, animationTime);
  const layers: Layer[] = [];

  if (routes.length) {
    layers.push(new PathLayer<GeoEvent>({
      id: 'aviation-route-underlay',
      data: routes,
      getPath: (event) => event.geometry?.type === 'LineString' ? event.geometry.coordinates : [],
      getColor: (event) => aviationRouteTone(event, event.id === state.selectedEventId ? 118 : 34),
      getWidth: (event) => routeWidth(event, state.selectedEventId) + 1.1,
      widthMinPixels: 1,
      widthMaxPixels: 5,
      jointRounded: true,
      capRounded: true,
      pickable: false,
    }));
    layers.push(new PathLayer<GeoEvent>({
      id: 'aviation-route-core',
      data: routes,
      getPath: (event) => event.geometry?.type === 'LineString' ? event.geometry.coordinates : [],
      getColor: (event) => aviationRouteTone(event, event.id === state.selectedEventId ? 235 : 118),
      getWidth: (event) => routeWidth(event, state.selectedEventId),
      widthMinPixels: 0.65,
      widthMaxPixels: 3.5,
      jointRounded: true,
      capRounded: true,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 250, 198, 150],
    }));
  }

  if (routeRunners.length) {
    layers.push(new ScatterplotLayer<AviationMotionPoint>({
      id: 'aviation-route-runners',
      data: routeRunners,
      getPosition: (point) => point.position,
      getRadius: 18_000,
      getFillColor: (point) => point.color,
      getLineColor: [4, 12, 18, 230],
      getLineWidth: 1,
      radiusMinPixels: 1.8,
      radiusMaxPixels: 4.5,
      lineWidthMinPixels: 1,
      stroked: true,
      pickable: false,
    }));
  }

  if (flightPoints.length) {
    layers.push(new IconLayer<AviationMotionPoint>({
      id: 'aviation-seeded-aircraft',
      data: flightPoints,
      iconAtlas: AIRCRAFT_ICON_ATLAS,
      iconMapping: AIRCRAFT_ICON_MAPPING,
      getIcon: () => 'aircraft',
      getPosition: (point) => point.position,
      getSize: (point) => point.size,
      getAngle: (point) => point.angle,
      getColor: (point) => point.color,
      sizeUnits: 'pixels',
      pickable: false,
    }));
  }

  if (liveAircraft.length) {
    layers.push(new IconLayer<GeoEvent>({
      id: 'aviation-live-aircraft',
      data: liveAircraft,
      iconAtlas: AIRCRAFT_ICON_ATLAS,
      iconMapping: AIRCRAFT_ICON_MAPPING,
      getIcon: () => 'aircraft',
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
      getSize: (event) => isWatch(event) ? 15 : 12,
      getAngle: (event) => numberProperty(event, 'heading') - 90,
      getColor: (event) => isWatch(event) ? [255, 214, 84, 245] : [72, 244, 255, 232],
      sizeUnits: 'pixels',
      pickable: true,
      autoHighlight: true,
    }));
  }

  if (hubs.length) {
    layers.push(new ScatterplotLayer<GeoEvent>({
      id: 'aviation-hubs',
      data: hubs,
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
      getRadius: (event) => Math.max(26_000, Math.min(76_000, 18_000 + numberProperty(event, 'routeCount') * 34)),
      getFillColor: (event) => isWatch(event) ? [255, 177, 76, 135] : [24, 211, 238, 112],
      getLineColor: (event) => isWatch(event) ? [255, 220, 130, 230] : [87, 235, 255, 225],
      getLineWidth: 1.5,
      radiusMinPixels: 4,
      radiusMaxPixels: 14,
      lineWidthMinPixels: 1,
      stroked: true,
      pickable: true,
      autoHighlight: true,
    }));
    layers.push(new TextLayer<GeoEvent>({
      id: 'aviation-hub-labels',
      data: hubs.slice(0, state.zoom < 2.2 ? 8 : 18),
      getPosition: (event) => event.geometry?.type === 'Point' ? event.geometry.coordinates : [0, 0],
      getText: (event) => stringProperty(event, 'code'),
      getPixelOffset: [9, 10],
      getSize: 9,
      getColor: [174, 233, 241, 195],
      getTextAnchor: 'start',
      getAlignmentBaseline: 'center',
      fontFamily: MAP_MONO_FONT_FAMILY,
      fontWeight: 900,
      outlineWidth: 3,
      outlineColor: [0, 0, 0, 220],
      pickable: false,
    }));
  }

  return layers;
}
