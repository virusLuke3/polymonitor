import type {
  GeoEvent,
  GeoEventCategory,
  GeoEventSeverity,
  HazardEvent,
  HazardKind,
} from '../domain/types';
import type { MapSymbolKey } from './mapSymbols';

export type MapLayerDefinition = {
  id: string;
  label: string;
  messageKey?: string;
  icon: MapSymbolKey;
  hint?: string;
  categories: GeoEventCategory[];
  sourceKeys: string[];
  defaultEnabled: boolean;
  selectable: boolean;
  minZoom: number;
  labelMinZoom: number;
  cluster: boolean;
  clusterRadius: number;
  timeFilter: boolean;
  severities: GeoEventSeverity[];
  legend: Array<{ label: string; color: string; symbol: MapSymbolKey }>;
  explanation: {
    purpose: string;
    sources: string[];
    freshness: string;
    confidence: string;
    limitations: string[];
  };
};

export const WORLD_EVENT_LAYER_REGISTRY: readonly MapLayerDefinition[] = [
  {
    id: 'weather-alerts',
    label: 'Storms, Cyclones & Floods',
    messageKey: 'atlas.layer.weatherAlerts',
    icon: 'storm',
    hint: 'ALERTS',
    categories: ['weather', 'natural-hazard'],
    sourceKeys: ['nws', 'eonet', 'gdacs'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    clusterRadius: 58,
    timeFilter: true,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [
      { label: 'Storm / tornado', color: '#d9e5e7', symbol: 'storm' },
      { label: 'Cyclone', color: '#d9e5e7', symbol: 'cyclone' },
      { label: 'Flood', color: '#d9e5e7', symbol: 'flood' },
      { label: 'Tsunami', color: '#d9e5e7', symbol: 'tsunami' },
    ],
    explanation: {
      purpose: 'Active severe storms, tornadoes, tropical cyclones, floods and tsunamis.',
      sources: ['NWS active CAP alerts', 'NASA EONET', 'GDACS international alerts'],
      freshness: 'NWS refreshes every 60 seconds; EONET refreshes every five minutes.',
      confidence: 'Provider-native alert geometry, advisory identity and event tracks.',
      limitations: ['NWS coverage is United States focused.', 'EONET is a discovery feed, not an exhaustive global alert service.'],
    },
  },
  {
    id: 'earthquakes-volcanoes',
    label: 'Earthquakes & Volcanoes',
    messageKey: 'atlas.layer.earthquakesVolcanoes',
    icon: 'earthquake',
    hint: 'GEO',
    categories: ['natural-hazard'],
    sourceKeys: ['usgs', 'eonet', 'gdacs'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    clusterRadius: 52,
    timeFilter: true,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [
      { label: 'Earthquake', color: '#d9e5e7', symbol: 'earthquake' },
      { label: 'Volcano', color: '#d9e5e7', symbol: 'volcano' },
    ],
    explanation: {
      purpose: 'Recent earthquakes and reported volcanic events.',
      sources: ['USGS Earthquake Hazards Program', 'NASA EONET', 'GDACS international alerts'],
      freshness: 'USGS refreshes every 60 seconds; EONET refreshes every five minutes.',
      confidence: 'Magnitude, depth, PAGER and provider-native event identity are retained.',
      limitations: ['Volcano coverage follows EONET discovery and is not a complete eruption registry.'],
    },
  },
  {
    id: 'wildfires',
    label: 'Wildfires',
    messageKey: 'atlas.layer.wildfires',
    icon: 'wildfire',
    hint: 'FIRE',
    categories: ['natural-hazard'],
    sourceKeys: ['eonet', 'gdacs', 'firms'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    clusterRadius: 62,
    timeFilter: true,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [
      { label: 'Wildfire event', color: '#d9e5e7', symbol: 'wildfire' },
      { label: 'Satellite detection', color: '#d9e5e7', symbol: 'fire-detection' },
    ],
    explanation: {
      purpose: 'Active wildfire events, with aggregated satellite detections when configured.',
      sources: ['NASA EONET', 'NASA FIRMS'],
      freshness: 'EONET refreshes every five minutes; FIRMS availability is source-configured.',
      confidence: 'Event and detection evidence remains source-native.',
      limitations: ['FIRMS raw detections must be spatially aggregated before rendering.', 'FIRMS is unavailable without a MAP_KEY.'],
    },
  },
  {
    id: 'extreme-temperature',
    label: 'Extreme Temperature Alerts',
    messageKey: 'atlas.layer.extremeTemperature',
    icon: 'heat',
    hint: 'TEMP',
    categories: ['weather', 'natural-hazard'],
    sourceKeys: ['nws', 'eonet'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    clusterRadius: 58,
    timeFilter: true,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [
      { label: 'Extreme heat', color: '#d9e5e7', symbol: 'heat' },
      { label: 'Extreme cold', color: '#d9e5e7', symbol: 'cold' },
    ],
    explanation: {
      purpose: 'Active extreme heat and extreme cold alerts.',
      sources: ['NWS active CAP alerts', 'NASA EONET'],
      freshness: 'NWS refreshes every 60 seconds; EONET refreshes every five minutes.',
      confidence: 'Provider severity, urgency and certainty are retained.',
      limitations: ['Global coverage is incomplete and varies by provider.'],
    },
  },
  {
    id: 'climate-anomalies',
    label: 'Major Weather Anomalies',
    messageKey: 'atlas.layer.climateAnomalies',
    icon: 'anomaly',
    hint: 'ANOMALY',
    categories: ['weather', 'natural-hazard'],
    sourceKeys: ['eonet', 'gdacs', 'climate-anomaly'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    clusterRadius: 54,
    timeFilter: true,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [{ label: 'Major anomaly', color: '#d9e5e7', symbol: 'anomaly' }],
    explanation: {
      purpose: 'Major observed weather anomalies and quantitative climate departures.',
      sources: ['NASA EONET', 'GDACS major drought alerts', 'Versioned anomaly baseline pipeline'],
      freshness: 'Source-specific runtime freshness.',
      confidence: 'Quantitative anomalies require a declared baseline period and calculation version.',
      limitations: ['The quantitative baseline pipeline is not yet configured.', 'Discovery events are not presented as calculated anomalies.'],
    },
  },
  {
    id: 'intel-hotspots',
    label: 'Intel Hotspots',
    messageKey: 'atlas.layer.intelHotspots',
    icon: 'intel',
    hint: 'INTEL',
    categories: ['intel'],
    sourceKeys: ['breaking-event-radar'],
    defaultEnabled: false,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    clusterRadius: 55,
    timeFilter: true,
    severities: ['watch', 'warning', 'critical'],
    legend: [{ label: 'Evidence-qualified intelligence', color: '#d9e5e7', symbol: 'intel' }],
    explanation: {
      purpose: 'Verified, time-bounded real-world intelligence with reliable spatial evidence.',
      sources: ['Breaking Event Radar', 'GDELT', 'Wikimedia'],
      freshness: 'Source-specific runtime freshness.',
      confidence: 'Provider confidence and evidence diversity.',
      limitations: ['Only time-bounded country records with confidence >= 0.60 and at least two articles from two sources are rendered.', 'Country polygons do not imply a precise incident footprint.'],
    },
  },
  {
    id: 'ucdp',
    label: 'Conflict & Unrest',
    messageKey: 'atlas.layer.ucdp',
    icon: 'conflict-state',
    hint: 'CONFLICT',
    categories: ['conflict', 'unrest'],
    sourceKeys: ['geo-sanctions-shock'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    clusterRadius: 52,
    timeFilter: true,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [
      { label: 'State-based', color: '#d9e5e7', symbol: 'conflict-state' },
      { label: 'Non-state', color: '#d9e5e7', symbol: 'conflict-nonstate' },
      { label: 'One-sided', color: '#d9e5e7', symbol: 'conflict-one-sided' },
    ],
    explanation: {
      purpose: 'Verified conflict events and fatality estimates.',
      sources: ['UCDP'],
      freshness: 'Runtime snapshot with source status.',
      confidence: 'Source-native event identity and coordinates.',
      limitations: ['Fatality estimates and classifications may be revised.'],
    },
  },
  {
    id: 'sanctions-country-risk',
    label: 'Sanctions & Country Risk',
    messageKey: 'atlas.layer.countryRisk',
    icon: 'country-risk',
    hint: 'RISK',
    categories: ['sanctions', 'country-risk'],
    sourceKeys: ['geo-sanctions-shock'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 2,
    cluster: false,
    clusterRadius: 0,
    timeFilter: true,
    severities: ['watch', 'warning', 'critical'],
    legend: [
      { label: 'Country risk evidence', color: '#eec747', symbol: 'country-risk' },
      { label: 'Elevated country evidence', color: '#ff9135', symbol: 'country-risk' },
    ],
    explanation: {
      purpose: 'Country-level sanctions and verified risk changes.',
      sources: ['OFAC', 'Federal Register', 'UCDP aggregate'],
      freshness: 'Per-source runtime status.',
      confidence: 'Official action and source-backed country aggregation.',
      limitations: ['Country polygons aggregate configured sources and are not legal advice.', 'Unknown entities and non-country targets are rejected rather than mapped to a capital.'],
    },
  },
  {
    id: 'air-routes',
    label: 'Air Routes',
    messageKey: 'atlas.layer.airRoutes',
    icon: 'air-route',
    hint: 'REFERENCE',
    categories: ['infrastructure'],
    sourceKeys: ['global-transport-shipping'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 1,
    labelMinZoom: 4,
    cluster: false,
    clusterRadius: 0,
    timeFilter: false,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [
      { label: 'Trunk corridor', color: '#5eeeff', symbol: 'air-route' },
      { label: 'Weather exposure', color: '#2dd4bf', symbol: 'weather-exposure' },
      { label: 'Conflict exposure', color: '#ff604c', symbol: 'conflict-exposure' },
      { label: 'Aircraft', color: '#ffd654', symbol: 'aircraft' },
    ],
    explanation: {
      purpose: 'Low-priority aviation topology reference with a bounded default trunk view.',
      sources: ['OpenFlights', 'OpenSky/ADSB where available'],
      freshness: 'Static topology plus source-specific live snapshots.',
      confidence: 'Provider-native coordinates and identifiers.',
      limitations: ['A route line does not prove a flight is operating.'],
    },
  },
] as const;

export function selectableWorldEventLayers() {
  const order = new Map([
    'weather-alerts',
    'earthquakes-volcanoes',
    'wildfires',
    'extreme-temperature',
    'climate-anomalies',
    'air-routes',
    'intel-hotspots',
    'ucdp',
    'sanctions-country-risk',
  ].map((id, index) => [id, index]));
  return WORLD_EVENT_LAYER_REGISTRY
    .filter((layer) => layer.selectable)
    .slice()
    .sort((left, right) => (order.get(left.id) ?? 99) - (order.get(right.id) ?? 99));
}

export function worldEventLayerById(id: string) {
  return WORLD_EVENT_LAYER_REGISTRY.find((layer) => layer.id === id);
}

const HAZARD_LAYER_KINDS: Record<string, readonly HazardKind[]> = {
  'weather-alerts': ['severe-storm', 'tornado', 'tropical-cyclone', 'flood', 'tsunami'],
  'earthquakes-volcanoes': ['earthquake', 'volcano'],
  wildfires: ['wildfire', 'fire-detection'],
  'extreme-temperature': ['extreme-heat', 'extreme-cold'],
  'climate-anomalies': ['temperature-anomaly', 'precipitation-anomaly', 'other-weather-anomaly'],
};

export function isHazardGeoEvent(event: GeoEvent): event is HazardEvent {
  return (event.category === 'natural-hazard' || event.category === 'weather')
    && typeof (event as Partial<HazardEvent>).hazardKind === 'string';
}

export function worldEventLayerIdForEvent(event: GeoEvent): string | null {
  if (isHazardGeoEvent(event)) {
    return Object.entries(HAZARD_LAYER_KINDS)
      .find(([, kinds]) => kinds.includes(event.hazardKind))?.[0] || null;
  }
  if (event.category === 'conflict' || event.category === 'unrest') return 'ucdp';
  if (event.category === 'infrastructure') return 'air-routes';
  if (event.category === 'sanctions' || event.category === 'country-risk') return 'sanctions-country-risk';
  if (event.category === 'intel') return 'intel-hotspots';
  return null;
}

export function eventMatchesWorldEventLayers(event: GeoEvent, activeLayerIds: readonly string[]) {
  const layerId = worldEventLayerIdForEvent(event);
  return layerId != null && activeLayerIds.includes(layerId);
}
