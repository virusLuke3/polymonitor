import type { GeoEvent, GeoEventSeverity, HazardEvent } from '../../domain/types';

export const SEVERITY_COLORS: Record<GeoEventSeverity, [number, number, number, number]> = {
  info: [85, 196, 224, 185],
  watch: [238, 199, 71, 205],
  warning: [255, 145, 53, 220],
  critical: [255, 76, 70, 235],
};

export function eventColor(event: GeoEvent, alpha?: number): [number, number, number, number] {
  const color = [...SEVERITY_COLORS[event.severity]] as [number, number, number, number];
  if (alpha != null) color[3] = alpha;
  return color;
}

export function isHazardEvent(event: GeoEvent): event is HazardEvent {
  return (event.category === 'natural-hazard' || event.category === 'weather')
    && typeof (event as Partial<HazardEvent>).hazardKind === 'string';
}

export function pointRadiusMeters(event: GeoEvent) {
  if (isHazardEvent(event) && event.metrics.kind === 'earthquake') {
    return Math.max(12_000, Math.pow(Math.max(0.5, event.metrics.magnitude), 2.25) * 4_200);
  }
  const deaths = Number(event.properties.deathsBest || 0);
  if (Number.isFinite(deaths) && deaths > 0) {
    return Math.max(10_000, Math.sqrt(deaths + 1) * 6_200);
  }
  return event.category === 'infrastructure' ? 13_000 : 18_000;
}

export function eventLabel(event: GeoEvent) {
  if (isHazardEvent(event) && event.metrics.kind === 'earthquake') {
    return `M${event.metrics.magnitude.toFixed(1)}`;
  }
  const code = String(event.properties.code || '').trim();
  return code || event.title;
}
