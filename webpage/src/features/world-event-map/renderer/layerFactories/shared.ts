import { isHazardGeoEvent as isHazardEvent } from '../../config/layerRegistry';
export { isHazardGeoEvent as isHazardEvent } from '../../config/layerRegistry';
import type {
  GeoEvent,
  GeoPoint,
  GeoEventSeverity,
} from '../../domain/types';
import { MAP_SEVERITY_STYLES, HAZARD_SEVERITY_COLORS } from '../../config/mapSymbols';

export const SEVERITY_COLORS: Record<GeoEventSeverity, [number, number, number, number]> = {
  info: [...MAP_SEVERITY_STYLES.info.rgba],
  watch: [...MAP_SEVERITY_STYLES.watch.rgba],
  warning: [...MAP_SEVERITY_STYLES.warning.rgba],
  critical: [...MAP_SEVERITY_STYLES.critical.rgba],
};

export const MAP_MONO_FONT_FAMILY = '"Polymonitor DejaVu Mono", "DejaVu Sans Mono", monospace';

export function mapLabelFontFamily() {
  return '"Noto Sans SC Variable", sans-serif';
}
export const markerSize = (event: GeoEvent, selected: string | null) =>
  (event.severity === 'critical' ? 17 : event.severity === 'warning' ? 15 : 12) + (event.id === selected ? 3 : 0);
export const clusterMarkerSize = (count: number) => Math.min(30, Math.max(20, 18 + 1.6 * Math.log2(Math.max(1, count) + 1)));

export function eventColor(event: GeoEvent, alpha?: number): [number, number, number, number] {
  let color: [number, number, number, number];
  if (isHazardEvent(event)) {
    color = [...(HAZARD_SEVERITY_COLORS[event.severity] || [150, 156, 162, 245])] as [number, number, number, number];
  } else if (event.category === 'conflict' || event.category === 'unrest') {
    const violenceType = String(event.properties.violenceType || '');
    color = violenceType === '1'
      ? [255, 103, 91, 225]
      : violenceType === '2'
        ? [240, 180, 60, 225]
        : violenceType === '3'
          ? [158, 232, 95, 225]
          : [...SEVERITY_COLORS[event.severity]];
  } else if (event.category === 'intel') {
    color = [238, 199, 71, 225];
  } else {
    color = [...SEVERITY_COLORS[event.severity]];
  }
  if (alpha != null) color[3] = alpha;
  return color;
}

function visitGeometryCoordinates(
  value: unknown,
  visitor: (coordinate: GeoPoint) => void,
) {
  if (!Array.isArray(value)) return;
  if (value.length >= 2 && Number.isFinite(value[0]) && Number.isFinite(value[1])) {
    visitor([Number(value[0]), Number(value[1])]);
    return;
  }
  for (const child of value) visitGeometryCoordinates(child, visitor);
}

/** Smallest circular longitude interval, possibly ending beyond +180. */
export function coordinateBounds(points: GeoPoint[]): [number, number, number, number] | null {
  if (!points.length) return null;
  const lons = [...new Set(points.map(p => ((p[0] % 360) + 360) % 360))].sort((a, b) => a - b);
  let gap = -1, start = 0;
  for (let i = 0; i < lons.length; i++) {
    const next = (lons[(i + 1) % lons.length] ?? 0) + (i === lons.length - 1 ? 360 : 0);
    if (next - lons[i]! > gap) { gap = next - lons[i]!; start = (i + 1) % lons.length; }
  }
  let west = lons[start]!; if (west > 180) west -= 360;
  return [west, Math.min(...points.map(p => p[1])), west + 360 - gap, Math.max(...points.map(p => p[1]))];
}

const boundsCache = new WeakMap<GeoEvent, [number, number, number, number] | null>();
/** Include every geometry actually drawn, including forecast outside the center viewport. */
export function eventGeometryBounds(event: GeoEvent) {
  if (boundsCache.has(event)) return boundsCache.get(event)!;
  const points: GeoPoint[] = [];
  visitGeometryCoordinates(event.geometry?.coordinates, p => points.push(p));
  const named = event.properties.geometries;
  if (named && typeof named === 'object') for (const geometry of Object.values(named)) {
    visitGeometryCoordinates((geometry as { coordinates?: unknown })?.coordinates, p => points.push(p));
  }
  const bounds = coordinateBounds(points); boundsCache.set(event, bounds); return bounds;
}

export function boundsIntersect(a: [number, number, number, number], b: [number, number, number, number]) {
  if (a[1] > b[3] || a[3] < b[1]) return false;
  const east = b[2] < b[0] ? b[2] + 360 : b[2];
  return [-360, 0, 360].some(shift => a[0] + shift <= east && a[2] + shift >= b[0]);
}

const representativeCache = new WeakMap<GeoEvent, GeoPoint | null>();
/** A polygon summary is an interior point, never an asserted observation location. */
export function eventRepresentativePoint(event: GeoEvent): GeoPoint | null {
  if (representativeCache.has(event)) return representativeCache.get(event)!;
  const observed = (event.properties.geometries as Record<string, any> | undefined)?.observedPosition;
  if (observed?.type === 'Point' && Array.isArray(observed.coordinates)) return observed.coordinates as GeoPoint;
  const geometry = event.geometry;
  if (!geometry) return null;
  if (geometry.type === 'Point') return geometry.coordinates;
  // An arbitrary path endpoint is not a current observed center.
  if (geometry.type === 'LineString') return null;
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.coordinates;
  let result: GeoPoint | null = null, widest = -1;
  for (const polygon of polygons) {
    const first = polygon[0]?.[0]?.[0]; if (first == null) continue;
    const rings = polygon.map(ring => ring.map(([lon, lat]) => [first + ((((lon! - first) + 540) % 360) - 180), lat!]));
    const ys = [...new Set(rings.flat().map(p => p[1]!))].sort((a, b) => a - b);
    // Midpoints between vertex latitudes avoid ambiguous vertex intersections.
    for (let k = 1; k < ys.length; k += Math.max(1, Math.floor(ys.length / 64))) {
      const y = (ys[k - 1]! + ys[k]!) / 2;
      const xs: number[] = [];
      for (const ring of rings) for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const a = ring[i]!, b = ring[j]!;
        if ((a[1]! > y) !== (b[1]! > y)) xs.push(a[0]! + (y - a[1]!) * (b[0]! - a[0]!) / (b[1]! - a[1]!));
      }
      xs.sort((a, b) => a - b);
      for (let i = 0; i + 1 < xs.length; i += 2) if (xs[i + 1]! - xs[i]! > widest) {
        widest = xs[i + 1]! - xs[i]!;
        result = [((xs[i]! + xs[i + 1]!) / 2 + 540) % 360 - 180, y];
      }
    }
  }
  representativeCache.set(event, result); return result;
}

const HAZARD_AREA_REGIONAL_MIN_ZOOM = 3;
const HAZARD_AREA_DETAIL_MIN_ZOOM = 4.5;

export type HazardAreaPresentation = {
  mode: 'hidden' | 'global' | 'regional' | 'detail' | 'selected';
  fillAlpha: number;
  lineAlpha: number;
  lineWidth: number;
};

/** Shared WebGL/SVG progressive-disclosure contract for official hazard areas. */
export function hazardAreaPresentation(
  event: GeoEvent,
  zoom: number,
  selectedEventId: string | null,
): HazardAreaPresentation {
  if (event.id === selectedEventId) {
    return { mode: 'selected', fillAlpha: 56, lineAlpha: 245, lineWidth: 1.6 };
  }
  if (zoom < HAZARD_AREA_REGIONAL_MIN_ZOOM) {
    const bounds = eventGeometryBounds(event);
    const scale = 512 * Math.pow(2, zoom) / 360;
    const largeEnough = bounds && (bounds[2] - bounds[0]) * (bounds[3] - bounds[1]) * scale * scale >= 16;
    return largeEnough && (event.severity === 'warning' || event.severity === 'critical')
      ? { mode: 'global', fillAlpha: 28, lineAlpha: 150, lineWidth: 0.8 }
      : { mode: 'hidden', fillAlpha: 0, lineAlpha: 0, lineWidth: 0 };
  }
  if (zoom < HAZARD_AREA_DETAIL_MIN_ZOOM) {
    if (event.severity !== 'warning' && event.severity !== 'critical') {
      return { mode: 'hidden', fillAlpha: 0, lineAlpha: 0, lineWidth: 0 };
    }
    return { mode: 'regional', fillAlpha: 36, lineAlpha: 170, lineWidth: 1 };
  }
  return {
    mode: 'detail',
    fillAlpha: event.severity === 'critical' ? 36 : 28,
    lineAlpha: event.severity === 'critical' ? 142 : 108,
    lineWidth: 0.85,
  };
}

export function eventSeverityColor(
  event: GeoEvent,
  alpha = SEVERITY_COLORS[event.severity][3],
): [number, number, number, number] {
  const [red, green, blue] = isHazardEvent(event) ? HAZARD_SEVERITY_COLORS[event.severity] : SEVERITY_COLORS[event.severity];
  return [red, green, blue, alpha];
}

export function continuousMetricRadiusMeters(event: GeoEvent): number | null {
  if (isHazardEvent(event) && event.metrics.kind === 'earthquake') {
    return Math.max(12_000, Math.pow(Math.max(0.5, event.metrics.magnitude), 2.25) * 4_200);
  }
  if (isHazardEvent(event)
    && (event.hazardKind === 'wildfire' || event.hazardKind === 'fire-detection')
    && event.metrics.kind === 'wildfire') {
    const frp = Number(event.metrics.fireRadiativePowerMw || 0);
    const detections = Number(event.metrics.detectionCount || 0);
    if (frp > 0 || detections > 0) {
      return Math.max(11_000, Math.sqrt(Math.max(frp, detections * 18, 1)) * 5_200);
    }
  }
  const deaths = Number(event.properties.deathsBest || 0);
  if (Number.isFinite(deaths) && deaths > 0) {
    return Math.max(10_000, Math.sqrt(deaths + 1) * 6_200);
  }
  return null;
}

export function eventLabel(event: GeoEvent) {
  if (isHazardEvent(event) && event.metrics.kind === 'earthquake') {
    return `M${event.metrics.magnitude.toFixed(1)}`;
  }
  const code = String(event.properties.code || '').trim();
  return code || event.title;
}
