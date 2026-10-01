import { installLocalAssets } from './browser';
import type { Page, Route } from '@playwright/test';

export const GENERATED_AT = '2026-08-26T03:00:00Z';
export const ALL_LAYERS = [
  'weather-alerts',
  'earthquakes-volcanoes',
  'wildfires',
  'extreme-temperature',
  'climate-anomalies',
  'air-routes',
].join(',');

type Json = Record<string, unknown>;

function source(provider: string, nativeId: string) {
  return [{ provider, nativeId, observedAt: GENERATED_AT, freshness: 'live', status: 'ok' }];
}

export function hazard(overrides: Json): Json {
  const id = String(overrides.id);
  return {
    id,
    category: 'natural-hazard',
    title: id,
    summary: 'Deterministic World Event Map browser fixture.',
    severity: 'warning',
    occurredAt: GENERATED_AT,
    updatedAt: GENERATED_AT,
    geometry: { type: 'Point', coordinates: [0, 0] },
    locationPrecision: 'exact',
    locationLabel: 'Browser fixture',
    sources: source('Fixture authority', id),
    limitations: ['Deterministic browser fixture; not production data.'],
    relatedMarketIds: [],
    properties: { mapEntity: 'hazard-event', detailAvailable: true, geometryMode: 'simplified' },
    hazardKind: 'earthquake',
    lifecycle: 'active',
    coverage: { scope: 'provider-area', label: 'Deterministic browser coverage', isComplete: false, gaps: ['Fixture only.'] },
    severityEvidence: { provider: 'Fixture authority', rawLevel: 'fixture', mappingVersion: 'fixture.v1', reason: 'Deterministic browser contract.' },
    revision: { nativeEventId: id, revisionAt: GENERATED_AT, replaces: [], cancelled: false },
    metrics: { kind: 'earthquake', magnitude: 6.4, depthKm: 12 },
    ...overrides,
  };
}

const quake = hazard({
  id: 'earthquake:usgs:fixture',
  title: 'M6.4 Test Ridge Earthquake',
  severity: 'critical',
  geometry: { type: 'Point', coordinates: [-122.1, 37.4] },
  sources: source('USGS', 'fixture'),
});
const quakeCluster = Array.from({ length: 6 }, (_, index) => hazard({
  id: `earthquake:usgs:cluster-${index}`,
  title: `M5.${index} Cluster Ridge Earthquake`,
  severity: index >= 4 ? 'warning' : 'watch',
  geometry: { type: 'Point', coordinates: [-122.1, 37.4] },
  sources: source('USGS', `cluster-${index}`),
  metrics: { kind: 'earthquake', magnitude: 5 + index / 10, depthKm: 8 + index },
}));
const volcano = hazard({
  id: 'volcano:usgs:fixture',
  title: 'Fixture Volcano · WATCH / ORANGE',
  hazardKind: 'volcano',
  geometry: { type: 'Point', coordinates: [-155.3, 19.4] },
  sources: source('USGS Volcano Hazards Program', 'fixture-volcano'),
  metrics: { kind: 'volcano-or-other', statusLabel: 'WATCH / ORANGE' },
});
const cyclone = hazard({
  id: 'tropical-cyclone:nhc:al012026',
  title: 'HU ADA · NHC Advisory 12',
  hazardKind: 'tropical-cyclone',
  geometry: { type: 'Point', coordinates: [-70, 20] },
  sources: source('NOAA National Hurricane Center', 'AL012026'),
  properties: {
    mapEntity: 'hazard-event', detailAvailable: true, geometryMode: 'simplified',
    movementDirectionDegrees: 315, movementSpeedKnots: 12,
    geometries: {
      observedPosition: { type: 'Point', coordinates: [-70, 20] },
      observedTrack: { type: 'LineString', coordinates: [[-76, 16], [-73, 18], [-70, 20]] },
      forecastTrack: { type: 'LineString', coordinates: [[-70, 20], [-67, 23], [-64, 27]] },
      forecastCone: { type: 'Polygon', coordinates: [[[-72, 18], [-66, 19], [-62, 28], [-67, 29], [-72, 18]]] },
    },
  },
  revision: { nativeEventId: 'AL012026', advisoryId: '12', revisionAt: GENERATED_AT, replaces: [], cancelled: false },
  metrics: { kind: 'tropical-cyclone', maximumWind: { value: 100, unit: 'kt' }, pressureHpa: 960, advisoryNumber: '12', categoryLabel: 'HU' },
});
const wildfire = hazard({
  id: 'wildfire:eonet:fixture',
  title: 'Sierra Major Wildfire',
  hazardKind: 'wildfire',
  severity: 'warning',
  geometry: { type: 'Point', coordinates: [-118.2, 34.1] },
  sources: source('NASA EONET', 'fixture-fire'),
  metrics: { kind: 'wildfire', detectionCount: 84, fireRadiativePowerMw: 420, sensor: 'VIIRS', confidenceLabel: 'high' },
});
const detection = hazard({
  id: 'fire-detection:firms:fixture',
  title: 'VIIRS Detection · FRP 125 MW',
  hazardKind: 'fire-detection',
  severity: 'watch',
  geometry: { type: 'Point', coordinates: [-118.35, 34.18] },
  sources: source('NASA FIRMS', 'fixture-detection'),
  properties: { mapEntity: 'hazard-observation', detailAvailable: true, rawDetection: true, geometryMode: 'source-native' },
  coverage: { scope: 'viewport', label: 'Requested viewport', isComplete: false, gaps: ['Cloud and satellite overpass limitations apply.'] },
  metrics: { kind: 'wildfire', detectionCount: 1, fireRadiativePowerMw: 125, sensor: 'VIIRS', satellite: 'N20', confidenceLabel: 'high' },
});
const anomaly = hazard({
  id: 'temperature-anomaly:ncei:202607:42.5N,12.5E',
  title: 'Observed Temperature Anomaly +3.3 °C',
  hazardKind: 'temperature-anomaly',
  severity: 'critical',
  geometry: { type: 'Polygon', coordinates: [[[10, 40], [15, 40], [15, 45], [10, 45], [10, 40]]] },
  sources: source('NOAA NCEI Climate at a Glance', '202607:42.5N,12.5E'),
  metrics: {
    kind: 'climate-anomaly', variable: 'temperature', value: 3.3, anomaly: 3.3, unit: '°C',
    baselinePeriod: '1991-2020', calculationVersion: 'ncei-cag-global-mapping.v1',
    timeWindow: '202607', spatialResolution: '5-degree-grid', provider: 'NOAA NCEI',
  },
});

export const sourceEvents: Record<string, Json[]> = {
  usgs: [quake, ...quakeCluster],
  'usgs-volcano-cap': [volcano],
  nhc: [cyclone],
  eonet: [wildfire],
  gdacs: [],
  nws: [],
  firms: [wildfire],
  'climate-anomaly': [anomaly],
};

export const transportPayload = {
  generatedAt: GENERATED_AT,
  status: 'ok',
  source: 'OpenFlights fixture',
  freshness: 'live',
  items: [],
  aviation: {
    generatedAt: GENERATED_AT,
    routes: [{
      id: 'JFK-LHR', fromCode: 'JFK', toCode: 'LHR', fromLon: -73.78, fromLat: 40.64,
      toLon: -0.45, toLat: 51.47, corridor: 'North Atlantic trunk', trafficScore: 92,
      riskScore: 55, status: 'watch', layer: 'trunk', phase: 0.2, speed: 0.00002,
      riskSources: ['weather'], source: 'OpenFlights fixture',
    }],
    hubs: [
      { code: 'JFK', name: 'John F Kennedy', city: 'New York', country: 'US', lon: -73.78, lat: 40.64, routeCount: 92, status: 'watch' },
      { code: 'LHR', name: 'Heathrow', city: 'London', country: 'GB', lon: -0.45, lat: 51.47, routeCount: 88, status: 'ok' },
    ],
    flights: [{
      id: 'fixture-seeded', callsign: 'PX101', fromCode: 'JFK', toCode: 'LHR',
      fromLon: -73.78, fromLat: 40.64, toLon: -0.45, toLat: 51.47,
      phase: 0.37, speed: 0.00002, status: 'watch', layer: 'trunk', riskScore: 55,
    }],
  },
};

const minimalStyle = {
  version: 8,
  sources: { countries: { type: 'geojson', data: '/map-data/world-countries.geojson' } },
  layers: [
    { id: 'background', type: 'background', paint: { 'background-color': '#070a0c' } },
    { id: 'countries', type: 'fill', source: 'countries', paint: { 'fill-color': '#12181c', 'fill-opacity': 1 } },
    { id: 'country-lines', type: 'line', source: 'countries', paint: { 'line-color': '#526068', 'line-opacity': 0.7, 'line-width': 0.7 } },
  ],
};

export function mapResponse(key: string, events: Json[], status = 'ok') {
  return {
    schemaVersion: 'natural-hazards-map.v1', generatedAt: GENERATED_AT, events,
    sources: [{
      key, status,
      coverage: { scope: 'provider-area', label: `${key} deterministic fixture coverage`, isComplete: false, gaps: ['Fixture only.'] },
      fetchedAt: GENERATED_AT, dataUpdatedAt: GENERATED_AT, staleAfter: null,
      lastSuccessAt: status === 'ok' ? GENERATED_AT : null,
      errorCode: status === 'ok' ? null : 'fixture-unavailable',
    }],
    isPartial: status !== 'ok', errors: status === 'ok' ? [] : [{ source: key, code: 'fixture-unavailable' }],
    counts: { events: events.length, byHazardKind: {} },
    meta: { source: key, geometryMode: 'simplified', geometryZoom: 3, detailEndpoint: '/runtime/world/natural-hazards/events/{eventId}' },
  };
}

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) });
}

export async function installFixtures(page: Page, climateUnavailable = false) {
  await installLocalAssets(page);
  await page.addInitScript(() => {
    if (location.protocol === 'http:' || location.protocol === 'https:') {
      localStorage.setItem('polydata:panel-library-open:v1', JSON.stringify(innerWidth > 720));
    }
  });
  await page.route('https://tiles.openfreemap.org/styles/**', (route) => fulfillJson(route, minimalStyle));
  await page.route('https://basemaps.cartocdn.com/gl/**', (route) => fulfillJson(route, minimalStyle));
  await page.route('**/wm-api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/wm-api/, '');
    if (path === '/bootstrap') {
      await fulfillJson(route, {
        generatedAt: GENERATED_AT,
        defaultWorkspace: { name: 'World Event Map fixture', panels: ['global-transport-shipping'] },
        featuredMarket: null, activeMarketsPreview: [], activeMarketGroupsPreview: [],
        globalTradesPreview: [], globalOraclePreview: [], latestContentPreview: [], recentTradesPreview: [],
        oraclePreview: [], contentPreview: [], pricePreview: null, systemHealth: { apiStatus: 'ok', database: 'fixture' },
      });
      return;
    }
    if (path === '/runtime/world/natural-hazards/map') {
      const key = url.searchParams.get('source') || '';
      const zoom = Number(url.searchParams.get('zoom') || 2);
      if (key === 'climate-anomaly' && climateUnavailable) {
        await fulfillJson(route, mapResponse(key, [], 'error'));
        return;
      }
      const events = key === 'firms' && zoom >= 5 ? [detection] : sourceEvents[key] || [];
      await fulfillJson(route, mapResponse(key, events));
      return;
    }
    if (path.startsWith('/runtime/world/natural-hazards/events/')) {
      const id = decodeURIComponent(path.split('/').pop() || '');
      const event = Object.values(sourceEvents).flat().find((candidate) => candidate.id === id) || detection;
      await fulfillJson(route, { schemaVersion: 'natural-hazard-detail.v1', generatedAt: GENERATED_AT, event });
      return;
    }
    if (path === '/runtime/transport/global-shipping') {
      await fulfillJson(route, transportPayload);
      return;
    }
    if (path === '/runtime/transport/aviation-viewport') {
      await fulfillJson(route, {
        schemaVersion: 'aviation-viewport.v1', generatedAt: GENERATED_AT, status: 'ok',
        bbox: (url.searchParams.get('bbox') || '-90,30,-60,55').split(',').map(Number), zoom: Number(url.searchParams.get('zoom') || 3),
        aircraft: [{ id: 'abc123', icao24: 'abc123', callsign: 'PX202', lon: -70, lat: 43, baroAltitude: 10300, velocity: 240, heading: 72, status: 'watch', riskScore: 64, source: 'OpenSky fixture', updatedAt: GENERATED_AT }],
        aircraftCount: 1, availableAircraftCount: 1, source: 'OpenSky fixture', limitations: ['Deterministic browser fixture.'],
      });
      return;
    }
    if (path === '/markets' || path === '/market-groups') {
      await fulfillJson(route, { items: [], pagination: { page: 1, pageSize: 80, total: 0, totalPages: 0, hasMore: false } });
      return;
    }
    await fulfillJson(route, { generatedAt: GENERATED_AT, status: 'ok', items: [], lineups: [], panels: {} });
  });
}
