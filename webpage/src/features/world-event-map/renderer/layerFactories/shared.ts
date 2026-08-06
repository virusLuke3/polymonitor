import type {
  GeoEvent,
  GeoEventSeverity,
  HazardEvent,
  HazardKind,
} from '../../domain/types';
import { MAP_SEVERITY_STYLES } from '../../config/mapSymbols';

export const SEVERITY_COLORS: Record<GeoEventSeverity, [number, number, number, number]> = {
  info: [...MAP_SEVERITY_STYLES.info.rgba],
  watch: [...MAP_SEVERITY_STYLES.watch.rgba],
  warning: [...MAP_SEVERITY_STYLES.warning.rgba],
  critical: [...MAP_SEVERITY_STYLES.critical.rgba],
};

export const MAP_MONO_FONT_FAMILY = '"JetBrains Mono", "SFMono-Regular", Consolas, monospace';

const HAZARD_COLORS: Record<HazardKind, [number, number, number, number]> = {
  'severe-storm': [167, 139, 250, 210],
  tornado: [192, 132, 252, 220],
  'tropical-cyclone': [56, 189, 248, 220],
  flood: [45, 212, 191, 210],
  'extreme-heat': [255, 77, 79, 220],
  'extreme-cold': [96, 165, 250, 215],
  earthquake: [251, 146, 60, 220],
  volcano: [244, 63, 94, 220],
  tsunami: [34, 211, 238, 220],
  wildfire: [255, 107, 53, 225],
  'fire-detection': [249, 115, 22, 205],
  'temperature-anomaly': [232, 121, 249, 210],
  'precipitation-anomaly': [129, 140, 248, 210],
  'other-weather-anomaly': [217, 70, 239, 210],
};

export function eventColor(event: GeoEvent, alpha?: number): [number, number, number, number] {
  let color: [number, number, number, number];
  if (isHazardEvent(event)) {
    color = [...HAZARD_COLORS[event.hazardKind]];
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

export function isHazardEvent(event: GeoEvent): event is HazardEvent {
  return (event.category === 'natural-hazard' || event.category === 'weather')
    && typeof (event as Partial<HazardEvent>).hazardKind === 'string';
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

export function pointRadiusMeters(event: GeoEvent) {
  return continuousMetricRadiusMeters(event)
    ?? (event.category === 'infrastructure' ? 13_000 : 18_000);
}

export function eventLabel(event: GeoEvent) {
  if (isHazardEvent(event) && event.metrics.kind === 'earthquake') {
    return `M${event.metrics.magnitude.toFixed(1)}`;
  }
  const code = String(event.properties.code || '').trim();
  return code || event.title;
}
