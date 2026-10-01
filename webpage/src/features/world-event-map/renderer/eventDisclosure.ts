import type { GeoEvent } from '../domain/types';
import { boundsIntersect, eventGeometryBounds, eventRepresentativePoint, isHazardEvent } from './layerFactories/shared';

/**
 * Zoom disclosure is a presentation decision, not a clustering decision.
 * Keeping it outside the Supercluster factory lets the WebGL and SVG
 * renderers share the same visibility and context-texture contract.
 */
export function isMajorWorldEvent(event: GeoEvent) {
  if (isHazardEvent(event) && (event.lifecycle === 'ended' || event.revision.cancelled
    || (event.expiresAt && Date.parse(event.expiresAt) <= Date.now()))) return false;
  // Default overview occurrence window; older facts keep severity and record access.
  if (isHazardEvent(event) && event.hazardKind === 'earthquake' && event.occurredAt
    && Date.parse(event.occurredAt) < Date.now() - 7 * 24 * 60 * 60_000) return false;
  if (event.severity === 'critical') return true;
  if (event.severity !== 'warning') return false;
  if (!isHazardEvent(event)) return true;
  if (event.metrics.kind === 'earthquake') {
    const pager = String(event.metrics.pagerAlert || '').toLowerCase();
    return event.metrics.magnitude >= 5.2
      || Number(event.metrics.significance || 0) >= 500
      || event.metrics.tsunami === true
      || pager === 'orange'
      || pager === 'red';
  }
  if ((event.hazardKind === 'wildfire' || event.hazardKind === 'fire-detection')
    && event.metrics.kind === 'wildfire') {
    return event.hazardKind === 'wildfire'
      || Number(event.metrics.detectionCount || 0) >= 20
      || Number(event.metrics.fireRadiativePowerMw || 0) >= 100;
  }
  return true;
}

export function eventDisclosureTier(event: GeoEvent) {
  if (isMajorWorldEvent(event)) return 0;
  if (event.severity === 'watch' || event.severity === 'warning') return 1;
  return 2;
}

export function disclosureTierForZoom(zoom: number) {
  return zoom < 2.5 ? 0 : zoom < 4 ? 1 : 2;
}

export function eventVisibleAtZoom(event: GeoEvent, zoom: number, selectedEventId: string | null) {
  // Canonical events selected by the user's severity filters remain visible.
  // Only raw satellite observations use the separate overview texture.
  if (isHazardEvent(event)) return event.id === selectedEventId || event.hazardKind !== 'fire-detection' || zoom >= 4;
  return event.id === selectedEventId || eventDisclosureTier(event) <= disclosureTierForZoom(zoom);
}

export type MapPresentationCounts = { inView: number; singles: number; clusters: number; observations: number; inViewIds?: string[] };

/** Geometry intersection and presentation counts have different denominators. */
export function mapPresentationCounts(
  events: GeoEvent[], presentation: { singles: GeoEvent[]; clusters: { coordinates: [number, number] }[] },
  viewport: [number, number, number, number], zoom: number,
): MapPresentationCounts {
  const pointInView = (p: [number, number] | null) => p != null && boundsIntersect([p[0], p[1], p[0], p[1]], viewport);
  const inView = events.filter(event => { const bounds = eventGeometryBounds(event); return bounds && boundsIntersect(bounds, viewport); });
  const singles = new Set(presentation.singles.filter(event => pointInView(eventRepresentativePoint(event))).map(event => event.id));
  for (const event of inView) {
    if (isHazardEvent(event) && event.hazardKind === 'tropical-cyclone' && event.geometry?.type === 'LineString'
      && pointInView(eventRepresentativePoint(event))) singles.add(event.id);
  }
  return {
    inViewIds: [...new Set(inView.map(event => event.id))],
    inView: new Set(inView.map(event => event.id)).size, singles: singles.size,
    clusters: presentation.clusters.filter(cluster => pointInView(cluster.coordinates)).length,
    observations: zoom < 4 ? inView.filter(event => isHazardEvent(event) && event.hazardKind === 'fire-detection').length : 0,
  };
}
