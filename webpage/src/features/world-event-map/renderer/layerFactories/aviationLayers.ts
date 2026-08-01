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

/** [west, south, east, north], in WGS84 degrees. */
export type AviationViewport = [number, number, number, number];

export type AviationMotionPoint = {
  id: string;
  event: GeoEvent;
  position: [number, number];
  color: [number, number, number, number];
  angle: number;
  size: number;
};

/** A stable path grouping prepared outside the animation frame. */
export type AviationMotionGroup = {
  id: string;
  event: GeoEvent;
  segments: GeoEvent[];
};

/**
 * The selected, zoom-budgeted aviation data. The renderer owns this object for
 * the whole static render generation; animation must only read it, never
 * filter/group/sort the full event payload again.
 */
export type AviationRenderData = {
  routes: GeoEvent[];
  hubs: GeoEvent[];
  flights: GeoEvent[];
  liveAircraft: GeoEvent[];
  routeMotionGroups: AviationMotionGroup[];
  flightMotionGroups: AviationMotionGroup[];
};

export type AviationStaticLayerSections = {
  routeLayers: LayersList;
  markerLayers: LayersList;
  data: AviationRenderData;
};

export type AviationLayerStats = {
  routes: number;
  visibleRoutes: number;
  hubs: number;
  visibleHubs: number;
  flights: number;
  visibleFlights: number;
  liveAircraft: number;
  visibleLiveAircraft: number;
  watchRoutes: number;
  riskSources: Record<AviationRiskSource, number>;
};

type AviationBudget = {
  routes: number;
  routeRunners: number;
  seededAircraft: number;
  liveAircraft: number;
  hubs: number;
  hubLabels: number;
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

function groupSegments(events: readonly GeoEvent[], key: 'routeId' | 'flightId'): AviationMotionGroup[] {
  const groups = new Map<string, GeoEvent[]>();
  for (const event of events) {
    const id = groupId(event, key);
    const values = groups.get(id) || [];
    values.push(event);
    groups.set(id, values);
  }
  return [...groups.entries()].map(([id, segments]) => {
    segments.sort((left, right) => (
      numberProperty(left, 'segmentIndex') - numberProperty(right, 'segmentIndex')
    ));
    return { id, event: segments[0]!, segments };
  });
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

function aircraftPriority(event: GeoEvent) {
  return (isWatch(event) ? 1_000 : 0)
    + routePriority(event)
    + numberProperty(event, 'velocity') / 10;
}

/**
 * World-view traffic needs context, not a full flight board. Detail expands
 * predictably with zoom; route topology remains visible at every level while
 * individual aircraft only become dense once the user has zoomed in.
 */
function aviationBudget(zoom: number, lens: AviationLensMode): AviationBudget {
  const lensScale = lens === 'watch' ? 0.8 : lens === 'trunk' ? 0.72 : 1;
  const scale = (value: number, minimum: number) => Math.max(minimum, Math.round(value * lensScale));
  if (zoom < 1.6) {
    return {
      routes: scale(120, 64), routeRunners: scale(48, 28), seededAircraft: scale(30, 18),
      liveAircraft: scale(24, 12), hubs: 12, hubLabels: 8,
    };
  }
  if (zoom < 2.8) {
    return {
      routes: scale(180, 96), routeRunners: scale(96, 48), seededAircraft: scale(64, 32),
      liveAircraft: scale(48, 24), hubs: 24, hubLabels: 12,
    };
  }
  if (zoom < 4) {
    return {
      routes: scale(360, 160), routeRunners: scale(180, 84), seededAircraft: scale(120, 56),
      liveAircraft: scale(100, 48), hubs: 30, hubLabels: 18,
    };
  }
  return {
    routes: scale(520, 220), routeRunners: scale(260, 120), seededAircraft: scale(220, 96),
    liveAircraft: scale(160, 72), hubs: 48, hubLabels: 28,
  };
}

function paddedViewport(viewport?: AviationViewport): AviationViewport | null {
  if (!viewport) return null;
  const [west, south, east, north] = viewport;
  if (![west, south, east, north].every(Number.isFinite) || east <= west || east - west >= 300) return null;
  // A buffer avoids flicker when a route/aircraft sits on the camera edge.
  const horizontalPad = (east - west) * 0.12;
  const verticalPad = (north - south) * 0.12;
  return [west - horizontalPad, south - verticalPad, east + horizontalPad, north + verticalPad];
}

function pointIsVisible(event: GeoEvent, viewport: AviationViewport | null) {
  if (!viewport || event.geometry?.type !== 'Point') return true;
  const [lon, lat] = event.geometry.coordinates;
  return lon >= viewport[0] && lon <= viewport[2] && lat >= viewport[1] && lat <= viewport[3];
}

function pathIntersectsViewport(event: GeoEvent, viewport: AviationViewport | null) {
  if (!viewport || event.geometry?.type !== 'LineString') return true;
  let west = Infinity;
  let south = Infinity;
  let east = -Infinity;
  let north = -Infinity;
  for (const [lon, lat] of event.geometry.coordinates) {
    west = Math.min(west, lon);
    east = Math.max(east, lon);
    south = Math.min(south, lat);
    north = Math.max(north, lat);
  }
  return west <= viewport[2] && east >= viewport[0] && south <= viewport[3] && north >= viewport[1];
}

function groupIntersectsViewport(group: AviationMotionGroup, viewport: AviationViewport | null) {
  return group.segments.some((segment) => pathIntersectsViewport(segment, viewport));
}

function flattenGroups(groups: readonly AviationMotionGroup[]) {
  return groups.flatMap((group) => group.segments);
}

function visibleRouteGroups(
  routes: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>,
  viewport: AviationViewport | null,
  budget: AviationBudget,
) {
  return groupSegments(routes, 'routeId')
    .filter((group) => matchesLens(group.event, state.aviationLens, state.aviationRiskSource))
    .filter((group) => groupIntersectsViewport(group, viewport))
    .sort((left, right) => routePriority(right.event) - routePriority(left.event))
    .slice(0, budget.routes);
}

function visibleFlightGroups(
  flights: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>,
  viewport: AviationViewport | null,
  budget: AviationBudget,
) {
  return groupSegments(flights, 'flightId')
    .filter((group) => matchesLens(group.event, state.aviationLens, state.aviationRiskSource))
    .filter((group) => groupIntersectsViewport(group, viewport))
    .sort((left, right) => aircraftPriority(right.event) - aircraftPriority(left.event))
    .slice(0, budget.seededAircraft);
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

function motionPointForGroup(
  group: AviationMotionGroup,
  progress: number,
  color: [number, number, number, number],
  size: number,
): AviationMotionPoint | null {
  const segmentProgress = Math.max(0, Math.min(0.999999, progress)) * group.segments.length;
  const segment = group.segments[Math.min(group.segments.length - 1, Math.floor(segmentProgress))]!;
  if (segment.geometry?.type !== 'LineString') return null;
  const localProgress = segmentProgress - Math.floor(segmentProgress);
  return {
    id: group.id,
    event: segment,
    position: pointAlongPath(segment.geometry.coordinates, localProgress),
    color,
    angle: angleAlongPath(segment.geometry.coordinates, localProgress),
    size,
  };
}

function routeMotionPointsForGroups(groups: readonly AviationMotionGroup[], animationTime: number) {
  const points: AviationMotionPoint[] = [];
  for (const group of groups) {
    const speed = Math.max(0.012, Math.min(0.08, numberProperty(group.event, 'speed', 0.028)));
    const progress = (hashUnit(group.id) + animationTime * speed) % 1;
    const point = motionPointForGroup(group, progress, aviationRouteTone(group.event, 230), 11);
    if (point) points.push(point);
  }
  return points;
}

function seededFlightPointsForGroups(groups: readonly AviationMotionGroup[], animationTime: number) {
  const points: AviationMotionPoint[] = [];
  for (const group of groups) {
    const phase = numberProperty(group.event, 'phase', hashUnit(group.id));
    const speed = Math.max(0.012, Math.min(0.16, numberProperty(group.event, 'speed', 0.06)));
    const progress = (phase + animationTime * speed) % 1;
    const color = isWatch(group.event)
      ? [255, 214, 84, 245] as [number, number, number, number]
      : [92, 241, 255, 235] as [number, number, number, number];
    const point = motionPointForGroup(group, progress, color, 14);
    if (point) points.push(point);
  }
  return points;
}

/** Compatibility helper for the SVG fallback and pure unit tests. */
export function aviationRouteMotionPoints(routes: GeoEvent[], animationTime: number) {
  return routeMotionPointsForGroups(groupSegments(routes, 'routeId'), animationTime);
}

/** Compatibility helper for the SVG fallback and pure unit tests. */
export function aviationSeededFlightPoints(flights: GeoEvent[], animationTime: number) {
  return seededFlightPointsForGroups(groupSegments(flights, 'flightId'), animationTime);
}

export function aviationLayerStats(events: GeoEvent[], visibleRoutes = events): AviationLayerStats {
  const routes = events.filter((event) => entity(event) === 'air-route');
  const routeRepresentatives = groupSegments(routes, 'routeId').map((group) => group.event);
  const visibleRouteCount = groupSegments(
    visibleRoutes.filter((event) => entity(event) === 'air-route'),
    'routeId',
  ).length;
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
    visibleHubs: events.filter((event) => entity(event) === 'air-hub').length,
    flights: groupSegments(events.filter((event) => entity(event) === 'air-flight'), 'flightId').length,
    visibleFlights: groupSegments(events.filter((event) => entity(event) === 'air-flight'), 'flightId').length,
    liveAircraft: events.filter((event) => entity(event) === 'live-aircraft').length,
    visibleLiveAircraft: events.filter((event) => entity(event) === 'live-aircraft').length,
    watchRoutes: routeRepresentatives.filter(isWatch).length,
    riskSources: risks,
  };
}

export function aviationLayerStatsForState(
  events: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>,
) {
  const visible = selectAviationRenderData(events, state);
  const stats = aviationLayerStats(events, visible.routes);
  return {
    ...stats,
    visibleHubs: visible.hubs.length,
    visibleFlights: visible.flightMotionGroups.length,
    visibleLiveAircraft: visible.liveAircraft.length,
  };
}

/**
 * Select and precompute one static aviation generation. This is deliberately
 * called on data/lens/zoom/viewport changes only, never from an animation tick.
 */
export function selectAviationRenderData(
  events: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>,
  viewport?: AviationViewport,
): AviationRenderData {
  const budget = aviationBudget(state.zoom, state.aviationLens);
  const visibleViewport = paddedViewport(viewport);
  const routeGroups = visibleRouteGroups(
    events.filter((event) => entity(event) === 'air-route'), state, visibleViewport, budget,
  );
  const flightGroups = visibleFlightGroups(
    events.filter((event) => entity(event) === 'air-flight'), state, visibleViewport, budget,
  );
  const hubs = events
    .filter((event) => entity(event) === 'air-hub')
    .filter((event) => matchesLens(event, state.aviationLens, state.aviationRiskSource))
    .filter((event) => pointIsVisible(event, visibleViewport))
    .sort((left, right) => numberProperty(right, 'routeCount') - numberProperty(left, 'routeCount'))
    .slice(0, budget.hubs);
  const liveAircraft = events
    .filter((event) => entity(event) === 'live-aircraft')
    .filter((event) => matchesLens(event, state.aviationLens, state.aviationRiskSource))
    .filter((event) => pointIsVisible(event, visibleViewport))
    .sort((left, right) => aircraftPriority(right) - aircraftPriority(left))
    .slice(0, budget.liveAircraft);
  return {
    routes: flattenGroups(routeGroups),
    hubs,
    flights: flattenGroups(flightGroups),
    liveAircraft,
    routeMotionGroups: routeGroups.slice(0, budget.routeRunners),
    flightMotionGroups: flightGroups,
  };
}

function createAviationRouteLayers(data: AviationRenderData, state: Pick<WorldEventMapState, 'selectedEventId'>): LayersList {
  if (!data.routes.length) return [];
  return [
    new PathLayer<GeoEvent>({
      id: 'aviation-route-underlay',
      data: data.routes,
      getPath: (event) => event.geometry?.type === 'LineString' ? event.geometry.coordinates : [],
      getColor: (event) => aviationRouteTone(event, event.id === state.selectedEventId ? 118 : 34),
      getWidth: (event) => routeWidth(event, state.selectedEventId) + 1.1,
      widthMinPixels: 1,
      widthMaxPixels: 5,
      jointRounded: true,
      capRounded: true,
      pickable: false,
    }),
    new PathLayer<GeoEvent>({
      id: 'aviation-route-core',
      data: data.routes,
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
    }),
  ];
}

function createAviationMarkerLayers(
  data: AviationRenderData,
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens'>,
): LayersList {
  const budget = aviationBudget(state.zoom, state.aviationLens);
  const layers: Layer[] = [];
  if (data.liveAircraft.length) {
    layers.push(new IconLayer<GeoEvent>({
      id: 'aviation-live-aircraft',
      data: data.liveAircraft,
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
  if (data.hubs.length) {
    layers.push(new ScatterplotLayer<GeoEvent>({
      id: 'aviation-hubs',
      data: data.hubs,
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
      data: data.hubs.slice(0, budget.hubLabels),
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

/** Builds immutable route/marker layers plus their precomputed animation data. */
export function createAviationStaticLayerSections(
  events: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource' | 'selectedEventId'>,
  viewport?: AviationViewport,
): AviationStaticLayerSections {
  const data = selectAviationRenderData(events, state, viewport);
  return {
    routeLayers: createAviationRouteLayers(data, state),
    markerLayers: createAviationMarkerLayers(data, state),
    data,
  };
}

/**
 * The only layers recreated during aviation animation. Their source groups are
 * stable, and their count is bounded by the current zoom-level budget.
 */
export function createAviationDynamicLayers(
  data: AviationRenderData,
  animationTime = 0,
): LayersList {
  const routeRunners = routeMotionPointsForGroups(data.routeMotionGroups, animationTime);
  const flightPoints = seededFlightPointsForGroups(data.flightMotionGroups, animationTime);
  const layers: Layer[] = [];
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
  return layers;
}

/** Compatibility composition for the SVG renderer and factory callers. */
export function createAviationLayers(
  events: GeoEvent[],
  state: WorldEventMapState,
  animationTime = 0,
  viewport?: AviationViewport,
): LayersList {
  const sections = createAviationStaticLayerSections(events, state, viewport);
  return [
    ...sections.routeLayers,
    ...createAviationDynamicLayers(sections.data, animationTime),
    ...sections.markerLayers,
  ];
}
