import type { GeoEvent, HazardEvent } from '../domain/types';
import { isHazardGeoEvent } from '../config/layerRegistry';

export type InspectorField = {
  label: string;
  value: string;
};

const HAZARD_LABELS: Record<HazardEvent['hazardKind'], string> = {
  'severe-storm': 'Severe storm',
  tornado: 'Tornado',
  'tropical-cyclone': 'Tropical cyclone',
  flood: 'Flood',
  'extreme-heat': 'Extreme heat',
  'extreme-cold': 'Extreme cold',
  earthquake: 'Earthquake',
  volcano: 'Volcano',
  tsunami: 'Tsunami',
  wildfire: 'Named wildfire',
  'fire-detection': 'Satellite thermal anomaly',
  'temperature-anomaly': 'Temperature anomaly',
  'precipitation-anomaly': 'Precipitation anomaly',
  'other-weather-anomaly': 'Weather anomaly',
};

function present(value: unknown): value is string | number {
  return value !== null && value !== undefined && value !== '';
}

function field(label: string, value: unknown, suffix = ''): InspectorField | null {
  return present(value) ? { label, value: `${String(value)}${suffix}` } : null;
}

function compact(fields: Array<InspectorField | null>): InspectorField[] {
  return fields.filter((item): item is InspectorField => item !== null);
}

export function hazardLabel(event: HazardEvent): string {
  return HAZARD_LABELS[event.hazardKind];
}

export function formatTimestamp(value: string | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return value;
  return parsed.toISOString().replace('T', ' ').replace('.000Z', ' UTC');
}

export function geometryLabel(event: GeoEvent): string {
  if (!event.geometry) return 'No renderable geometry';
  if (event.geometry.type === 'Point') {
    const [lon, lat] = event.geometry.coordinates;
    return `${lat.toFixed(3)}°, ${lon.toFixed(3)}°`;
  }
  if (event.geometry.type === 'LineString') {
    return `Track · ${event.geometry.coordinates.length} observed positions`;
  }
  if (event.geometry.type === 'Polygon') {
    return `Polygon · ${event.geometry.coordinates.length} ring${event.geometry.coordinates.length === 1 ? '' : 's'}`;
  }
  return `MultiPolygon · ${event.geometry.coordinates.length} areas`;
}

export function eventTimeFields(event: GeoEvent): InspectorField[] {
  const hazard = isHazardGeoEvent(event) ? event : null;
  return compact([
    field('Occurred', formatTimestamp(event.occurredAt)),
    field('Effective', formatTimestamp(hazard?.effectiveAt)),
    field('Onset', formatTimestamp(hazard?.onsetAt)),
    field('Updated', formatTimestamp(event.updatedAt)),
    field('Expires', formatTimestamp(event.expiresAt)),
    field('Ended', formatTimestamp(hazard?.endedAt)),
  ]);
}

export function eventContextFields(event: GeoEvent): InspectorField[] {
  if (event.category === 'intel') {
    return compact([
      field('Velocity score', event.properties.velocityScore),
      field('Source diversity', event.properties.sourceDiversity),
      field('Evidence articles', event.properties.evidenceArticleCount),
      field('Evidence gate', event.properties.evidenceGate),
      field('Linked markets', event.relatedMarketIds.length),
    ]);
  }
  if (event.category === 'sanctions' || event.category === 'country-risk') {
    return compact([
      field('Sanctions evidence', event.properties.sanctionsEvidenceCount),
      field('Country-risk evidence', event.properties.countryRiskEvidenceCount),
      field('Latest source', event.properties.latestSource),
      field('OFAC records in snapshot', event.properties.ofacRecordCountTotal),
      field('Global new sanctions', event.properties.globalNewSanctionsCount),
      field('Risk mapping', event.properties.riskMappingVersion),
      field('Source contract', event.properties.sourceContract),
    ]);
  }
  if (event.category === 'conflict' || event.category === 'unrest') {
    return compact([
      field('Best death estimate', event.properties.deathsBest),
      field('Low estimate', event.properties.deathsLow),
      field('High estimate', event.properties.deathsHigh),
      field('Violence type', event.properties.violenceType),
    ]);
  }
  return [];
}

export function hazardMetricFields(event: HazardEvent): InspectorField[] {
  const metrics = event.metrics;
  if (metrics.kind === 'earthquake') {
    return compact([
      field('Magnitude', metrics.magnitude.toFixed(1)),
      field('Depth', metrics.depthKm?.toFixed(1), ' km'),
      field('Significance', metrics.significance),
      field('PAGER alert', metrics.pagerAlert?.toUpperCase()),
      field('Tsunami flag', metrics.tsunami == null ? null : metrics.tsunami ? 'Yes' : 'No'),
    ]);
  }
  if (metrics.kind === 'tropical-cyclone') {
    return compact([
      field('Maximum wind', metrics.maximumWind?.value, metrics.maximumWind ? ` ${metrics.maximumWind.unit}` : ''),
      field('Pressure', metrics.pressureHpa, ' hPa'),
      field('Category', metrics.categoryLabel),
      field('Advisory', metrics.advisoryNumber),
    ]);
  }
  if (metrics.kind === 'weather-alert') {
    return compact([
      field('Provider severity', metrics.providerSeverity),
      field('Urgency', metrics.urgency),
      field('Certainty', metrics.certainty),
    ]);
  }
  if (metrics.kind === 'wildfire') {
    return compact([
      field('Record type', event.hazardKind === 'fire-detection' ? 'Thermal anomaly observation' : 'Named wildfire event'),
      field('Detections', metrics.detectionCount),
      field('Total FRP', metrics.fireRadiativePowerMw, ' MW'),
      field('Sensor', metrics.sensor),
      field('Satellite', metrics.satellite),
      field('Confidence', metrics.confidenceLabel),
    ]);
  }
  if (metrics.kind === 'climate-anomaly') {
    return compact([
      field('Variable', metrics.variable),
      field('Observed / forecast', metrics.value, ` ${metrics.unit}`),
      field('Anomaly', `${metrics.anomaly >= 0 ? '+' : ''}${metrics.anomaly}`, ` ${metrics.unit}`),
      field('Baseline', metrics.baselinePeriod),
      field('Calculation', metrics.calculationVersion),
    ]);
  }
  return compact([field('Provider status', metrics.statusLabel)]);
}
