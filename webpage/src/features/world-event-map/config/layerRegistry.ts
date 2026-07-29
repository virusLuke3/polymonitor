import type { GeoEventCategory, GeoEventSeverity } from '../domain/types';

export type MapLayerDefinition = {
  id: string;
  label: string;
  messageKey?: string;
  icon: string;
  hint?: string;
  categories: GeoEventCategory[];
  sourceKeys: string[];
  defaultEnabled: boolean;
  selectable: boolean;
  minZoom: number;
  labelMinZoom: number;
  cluster: boolean;
  timeFilter: boolean;
  severities: GeoEventSeverity[];
  legend: Array<{ label: string; color: string }>;
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
    id: 'intel-hotspots',
    label: 'Intel Hotspots',
    icon: '✦',
    hint: 'INTEL',
    categories: ['intel'],
    sourceKeys: ['breaking-event-radar'],
    defaultEnabled: false,
    selectable: false,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    timeFilter: true,
    severities: ['watch', 'warning', 'critical'],
    legend: [],
    explanation: {
      purpose: 'Verified, time-bounded real-world intelligence with reliable spatial evidence.',
      sources: ['Breaking Event Radar', 'GDELT', 'Wikimedia'],
      freshness: 'Source-specific runtime freshness.',
      confidence: 'Provider confidence and evidence diversity.',
      limitations: ['Country-only records remain hidden until polygon rendering is available.'],
    },
  },
  {
    id: 'ucdp',
    label: 'Conflict & Unrest',
    messageKey: 'atlas.layer.ucdp',
    icon: '△',
    hint: 'CONFLICT',
    categories: ['conflict', 'unrest'],
    sourceKeys: ['geo-sanctions-shock'],
    defaultEnabled: true,
    selectable: true,
    minZoom: 0,
    labelMinZoom: 3,
    cluster: true,
    timeFilter: true,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [
      { label: 'State-based', color: '#ff675b' },
      { label: 'Non-state', color: '#f0b43c' },
      { label: 'One-sided', color: '#9ee85f' },
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
    icon: '◇',
    hint: 'RISK',
    categories: ['sanctions', 'country-risk'],
    sourceKeys: ['geo-sanctions-shock'],
    defaultEnabled: false,
    selectable: false,
    minZoom: 0,
    labelMinZoom: 2,
    cluster: false,
    timeFilter: true,
    severities: ['watch', 'warning', 'critical'],
    legend: [],
    explanation: {
      purpose: 'Country-level sanctions and verified risk changes.',
      sources: ['OFAC', 'Federal Register', 'UCDP aggregate'],
      freshness: 'Per-source runtime status.',
      confidence: 'Official action and source-backed country aggregation.',
      limitations: ['Disabled until canonical country polygon rendering is complete.'],
    },
  },
  {
    id: 'air-routes',
    label: 'Air Routes',
    messageKey: 'atlas.layer.airRoutes',
    icon: '✈',
    hint: 'REFERENCE',
    categories: ['infrastructure'],
    sourceKeys: ['global-transport-shipping'],
    defaultEnabled: false,
    selectable: true,
    minZoom: 1,
    labelMinZoom: 4,
    cluster: false,
    timeFilter: false,
    severities: ['info', 'watch', 'warning', 'critical'],
    legend: [],
    explanation: {
      purpose: 'Optional low-priority aviation topology reference.',
      sources: ['OpenFlights', 'OpenSky/ADSB where available'],
      freshness: 'Static topology plus source-specific live snapshots.',
      confidence: 'Provider-native coordinates and identifiers.',
      limitations: ['A route line does not prove a flight is operating.'],
    },
  },
] as const;

export function selectableWorldEventLayers() {
  return WORLD_EVENT_LAYER_REGISTRY.filter((layer) => layer.selectable);
}

export function worldEventLayerById(id: string) {
  return WORLD_EVENT_LAYER_REGISTRY.find((layer) => layer.id === id);
}
