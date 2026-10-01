import type { GeoEvent } from '../../domain/types';
import type { AviationLensMode, AviationRiskSource, WorldEventMapState } from '../../state/mapState';
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
  count: number;
};

export type AviationAircraftMarker = {
  id: string;
  event: GeoEvent;
  position: [number, number];
  count: number;
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

export function numberProperty(event: GeoEvent, key: string, fallback = 0) {
  const value = Number(event.properties[key]);
  return Number.isFinite(value) ? value : fallback;
}

export function stringProperty(event: GeoEvent, key: string) {
  return String(event.properties[key] || '').trim();
}

function riskSources(event: GeoEvent) {
  return Array.isArray(event.properties.riskSources)
    ? event.properties.riskSources.map(String).filter(Boolean)
    : [];
}

export function groupId(event: GeoEvent, key: 'routeId' | 'flightId') {
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

export function isWatch(event: GeoEvent) {
  return event.severity !== 'info'
    || numberProperty(event, 'riskScore') >= 35
    || riskSources(event).length > 0
    || stringProperty(event, 'status').toLowerCase() === 'watch';
}

function matchesRiskSource(event: GeoEvent, source: AviationRiskSource) {
  return source === 'all' || riskSources(event).includes(source);
}

function matchesLens(event: GeoEvent, lens: AviationLensMode, source: AviationRiskSource) {
  if (lens === 'watch') return isWatch(event) && matchesRiskSource(event, source);
  return true;
}

function lensPriority(event: GeoEvent, lens: AviationLensMode) {
  return lens === 'trunk' && stringProperty(event, 'layer') === 'trunk' ? 1 : 0;
}

function trunkEndpointCodes(events: readonly GeoEvent[]) {
  const codes = new Set<string>();
  for (const event of events) {
    if (entity(event) !== 'air-route' || stringProperty(event, 'layer') !== 'trunk') continue;
    for (const key of ['fromCode', 'toCode']) {
      const code = stringProperty(event, key);
      if (code) codes.add(code);
    }
  }
  return codes;
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

const ALTITUDE_COLOR_STOPS = [
  { alt: 0, color: [0, 217, 255] },
  { alt: 5_000, color: [50, 250, 160] },
  { alt: 10_000, color: [200, 230, 60] },
  { alt: 20_000, color: [255, 165, 30] },
  { alt: 30_000, color: [255, 100, 35] },
  { alt: 40_000, color: [235, 50, 55] },
  { alt: 45_000, color: [210, 40, 70] },
] as const;

/** WorldMonitor altitude ramp: cyan at sea level through red at cruise altitude. */
export function aviationAltitudeColor(altitudeMeters: number): [number, number, number] {
  const altitudeFeet = Number.isFinite(altitudeMeters) ? altitudeMeters * 3.28084 : 0;
  const first = ALTITUDE_COLOR_STOPS[0];
  const last = ALTITUDE_COLOR_STOPS[ALTITUDE_COLOR_STOPS.length - 1]!;
  if (altitudeFeet <= first.alt) return [first.color[0], first.color[1], first.color[2]];
  if (altitudeFeet >= last.alt) return [last.color[0], last.color[1], last.color[2]];
  for (let index = 1; index < ALTITUDE_COLOR_STOPS.length; index += 1) {
    const high = ALTITUDE_COLOR_STOPS[index]!;
    const low = ALTITUDE_COLOR_STOPS[index - 1]!;
    if (altitudeFeet > high.alt) continue;
    const ratio = (altitudeFeet - low.alt) / (high.alt - low.alt);
    return [
      Math.round(low.color[0] + (high.color[0] - low.color[0]) * ratio),
      Math.round(low.color[1] + (high.color[1] - low.color[1]) * ratio),
      Math.round(low.color[2] + (high.color[2] - low.color[2]) * ratio),
    ];
  }
  return [last.color[0], last.color[1], last.color[2]];
}

/**
 * World-view traffic needs context, not a full flight board. Detail expands
 * predictably with zoom; route topology remains visible at every level while
 * individual aircraft only become dense once the user has zoomed in.
 */
export function aviationBudget(zoom: number, lens: AviationLensMode): AviationBudget {
  const lensScale = lens === 'watch' ? 0.8 : lens === 'trunk' ? 0.72 : 1;
  const scale = (value: number, minimum: number) => Math.max(minimum, Math.round(value * lensScale));
  if (zoom < 1.6) {
    return {
      routes: scale(32, 24), routeRunners: scale(24, 18), seededAircraft: scale(24, 18),
      hubs: 10, hubLabels: 6,
    };
  }
  if (zoom < 2.8) {
    return {
      routes: scale(48, 32), routeRunners: scale(28, 20), seededAircraft: scale(36, 24),
      hubs: 14, hubLabels: 8,
    };
  }
  if (zoom < 4) {
    return {
      routes: scale(72, 48), routeRunners: scale(36, 24), seededAircraft: scale(48, 32),
      hubs: 18, hubLabels: 10,
    };
  }
  return {
    routes: scale(140, 96), routeRunners: scale(72, 48), seededAircraft: scale(96, 64),
    hubs: 28, hubLabels: 16,
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
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>
    & Partial<Pick<WorldEventMapState, 'selectedEventId'>>,
  viewport: AviationViewport | null,
  budget: AviationBudget,
) {
  return groupSegments(routes, 'routeId')
    .filter((group) => group.segments.some((segment) => segment.id === state.selectedEventId)
      || matchesLens(group.event, state.aviationLens, state.aviationRiskSource))
    .filter((group) => group.segments.some((segment) => segment.id === state.selectedEventId)
      || groupIntersectsViewport(group, viewport))
    .sort((left, right) => (
      Number(right.segments.some((segment) => segment.id === state.selectedEventId))
        - Number(left.segments.some((segment) => segment.id === state.selectedEventId))
      || lensPriority(right.event, state.aviationLens) - lensPriority(left.event, state.aviationLens)
      || routePriority(right.event) - routePriority(left.event)
    ))
    .slice(0, budget.routes);
}

function visibleFlightGroups(
  flights: GeoEvent[],
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>
    & Partial<Pick<WorldEventMapState, 'selectedEventId'>>,
  viewport: AviationViewport | null,
  budget: AviationBudget,
) {
  return groupSegments(flights, 'flightId')
    .filter((group) => group.segments.some((segment) => segment.id === state.selectedEventId)
      || matchesLens(group.event, state.aviationLens, state.aviationRiskSource))
    .filter((group) => group.segments.some((segment) => segment.id === state.selectedEventId)
      || groupIntersectsViewport(group, viewport))
    .sort((left, right) => (
      Number(right.segments.some((segment) => segment.id === state.selectedEventId))
        - Number(left.segments.some((segment) => segment.id === state.selectedEventId))
      || lensPriority(right.event, state.aviationLens) - lensPriority(left.event, state.aviationLens)
      || aircraftPriority(right.event) - aircraftPriority(left.event)
    ))
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

function hashUnit(value: string) {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) / 0xffffffff;
}

function mercatorPixel([lon, lat]: [number, number], zoom: number): [number, number] {
  const worldSize = 512 * Math.pow(2, Math.max(0, zoom));
  const boundedLat = Math.max(-85.051129, Math.min(85.051129, lat));
  const sine = Math.sin((boundedLat * Math.PI) / 180);
  return [
    ((lon + 180) / 360) * worldSize,
    (0.5 - Math.log((1 + sine) / (1 - sine)) / (4 * Math.PI)) * worldSize,
  ];
}

function aircraftScreenGrid<T extends { event: GeoEvent; position: [number, number] }>(
  items: readonly T[],
  zoom: number,
  selectedEventId: string | null,
  cellPixels = 20,
): Array<T & { count: number }> {
  const cells = new Map<string, T & { count: number }>();
  for (const item of items) {
    const [x, y] = mercatorPixel(item.position, zoom);
    const key = `${Math.floor(x / cellPixels)}:${Math.floor(y / cellPixels)}`;
    const existing = cells.get(key);
    const itemPriority = aircraftPriority(item.event) + Number(item.event.id === selectedEventId) * 100_000;
    const existingPriority = existing
      ? aircraftPriority(existing.event) + Number(existing.event.id === selectedEventId) * 100_000
      : Number.NEGATIVE_INFINITY;
    if (!existing || itemPriority > existingPriority) {
      cells.set(key, { ...item, count: (existing?.count || 0) + 1 });
    } else {
      existing.count += 1;
    }
  }
  return [...cells.values()];
}

function endpointFade(progress: number, fadeFraction = 0.1) {
  const edge = Math.max(0.08, Math.min(0.12, fadeFraction));
  const entering = Math.max(0, Math.min(1, progress / edge));
  const leaving = Math.max(0, Math.min(1, (1 - progress) / edge));
  const smooth = (value: number) => value * value * (3 - 2 * value);
  return Math.min(smooth(entering), smooth(leaving));
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
    // A moving marker keeps the stable group representative for hover/click;
    // changing the picked event id at every segment would lose selection mid-flight.
    event: group.event,
    position: pointAlongPath(segment.geometry.coordinates, localProgress),
    color,
    angle: angleAlongPath(segment.geometry.coordinates, localProgress),
    size,
    count: 1,
  };
}

export function routeMotionPointsForGroups(
  groups: readonly AviationMotionGroup[],
  animationTime: number,
  selectedEventId: string | null = null,
  selectedGroupOverride: string | null = null,
) {
  const points: AviationMotionPoint[] = [];
  const selectedGroupId = selectedGroupOverride || (selectedEventId
    ? groups.find((group) => group.segments.some((segment) => segment.id === selectedEventId))?.id || null
    : null);
  for (const group of groups) {
    const speed = Math.max(0.012, Math.min(0.08, numberProperty(group.event, 'speed', 0.028)));
    const progress = (hashUnit(group.id) + animationTime * speed) % 1;
    const alpha = selectedGroupId ? group.id === selectedGroupId ? 225 : 36 : 172;
    const point = motionPointForGroup(group, progress, aviationRouteTone(group.event, alpha), 4);
    if (point) points.push(point);
  }
  return points;
}

export function seededFlightPointsForGroups(
  groups: readonly AviationMotionGroup[],
  animationTime: number,
  zoom = 1.25,
  selectedEventId: string | null = null,
) {
  const points: AviationMotionPoint[] = [];
  for (const group of groups) {
    const phase = numberProperty(group.event, 'phase', hashUnit(group.id));
    const speed = Math.max(0.012, Math.min(0.16, numberProperty(group.event, 'speed', 0.06)));
    const progress = (phase + animationTime * speed) % 1;
    const selected = group.segments.some((segment) => segment.id === selectedEventId);
    const alpha = Math.round(
      (selected ? 245 : isWatch(group.event) ? 220 : 170) * endpointFade(progress, 0.1),
    );
    const color = isWatch(group.event) || selected
      ? [255, 214, 84, alpha] as [number, number, number, number]
      : [92, 241, 255, alpha] as [number, number, number, number];
    const point = motionPointForGroup(group, progress, color, 14);
    if (point) points.push(point);
  }
  return aircraftScreenGrid(points, zoom, selectedEventId);
}

/** Compatibility helper for the SVG fallback and pure unit tests. */
export function aviationRouteMotionPoints(
  routes: GeoEvent[],
  animationTime: number,
  selectedEventId: string | null = null,
) {
  return routeMotionPointsForGroups(groupSegments(routes, 'routeId'), animationTime, selectedEventId);
}

/** Compatibility helper for the SVG fallback and pure unit tests. */
export function aviationSeededFlightPoints(
  flights: GeoEvent[],
  animationTime: number,
  zoom = 1.25,
  selectedEventId: string | null = null,
) {
  return seededFlightPointsForGroups(groupSegments(flights, 'flightId'), animationTime, zoom, selectedEventId);
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
  state: Pick<WorldEventMapState, 'zoom' | 'aviationLens' | 'aviationRiskSource'>
    & Partial<Pick<WorldEventMapState, 'selectedEventId'>>,
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
  const trunkEndpoints = trunkEndpointCodes(events);
  const hubs = events
    .filter((event) => entity(event) === 'air-hub')
    .filter((event) => event.id === state.selectedEventId
      || matchesLens(event, state.aviationLens, state.aviationRiskSource))
    .filter((event) => event.id === state.selectedEventId || pointIsVisible(event, visibleViewport))
    .sort((left, right) => (
      Number(right.id === state.selectedEventId) - Number(left.id === state.selectedEventId)
      || (state.aviationLens === 'trunk'
        ? Number(trunkEndpoints.has(stringProperty(right, 'code')))
          - Number(trunkEndpoints.has(stringProperty(left, 'code')))
        : 0)
      || numberProperty(right, 'routeCount') - numberProperty(left, 'routeCount')
    ))
    .slice(0, budget.hubs);
  const liveAircraft = events
    .filter((event) => entity(event) === 'live-aircraft')
    .filter((event) => event.id === state.selectedEventId
      || matchesLens(event, state.aviationLens, state.aviationRiskSource))
    .filter((event) => event.id === state.selectedEventId || pointIsVisible(event, visibleViewport))
    .sort((left, right) => (
      Number(right.id === state.selectedEventId) - Number(left.id === state.selectedEventId)
      || aircraftPriority(right) - aircraftPriority(left)
    ));
  return {
    routes: flattenGroups(routeGroups),
    hubs,
    flights: flattenGroups(flightGroups),
    liveAircraft,
    routeMotionGroups: routeGroups.slice(0, budget.routeRunners),
    flightMotionGroups: flightGroups,
  };
}

function liveAircraftMarker(event: GeoEvent): AviationAircraftMarker | null {
  return event.geometry?.type === 'Point'
    ? { id: event.id, event, position: event.geometry.coordinates, count: 1 }
    : null;
}

export function aviationLiveAircraftMarkers(
  events: readonly GeoEvent[],
  zoom: number,
  selectedEventId: string | null = null,
) {
  return aircraftScreenGrid(
    events.flatMap((event) => liveAircraftMarker(event) || []),
    zoom,
    selectedEventId,
  );
}
