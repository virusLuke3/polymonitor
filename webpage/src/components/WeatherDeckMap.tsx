import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { MapboxOverlay } from '@deck.gl/mapbox';
import { PathLayer, ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import type { Layer, LayersList, PickingInfo } from '@deck.gl/core';
import { getWeatherMapFallbackStyle, getWeatherMapStyle } from '@/config/weatherBasemap';
import type { RuntimeGeoSanctionsShockItem, RuntimeGlobalTransportShippingPayload, RuntimeGlobalWeatherCity } from '@/types';

type WeatherTone = 'hot' | 'cool' | 'neutral';
type MarketTone = 'market' | 'watch' | 'none';
type ConflictTone = 'state' | 'nonstate' | 'onesided' | 'unknown';
type CountryRiskLevel = 'quiet' | 'watch' | 'elevated' | 'critical';

type WeatherMapPoint = {
  id: string;
  city: string;
  country: string;
  lon: number;
  lat: number;
  unit: string;
  currentTemp: number | null;
  forecastHigh: number | null;
  condition: string;
  quoteCoverage: string;
  topBinLabel: string | null;
  topBinPrice: number | null;
  topBinBid: number | null;
  topBinAsk: number | null;
  priceSource: string | null;
  bookStatus: string | null;
  marketUrl: string | null;
  temperatureTone: WeatherTone;
  marketTone: MarketTone;
  label: string;
  sublabel: string;
  labelDx: number;
  labelDy: number;
  weatherImpact: number;
};

type WeatherDeckMapProps = {
  items: RuntimeGlobalWeatherCity[];
  ucdpEvents?: RuntimeGeoSanctionsShockItem[];
  transportPayload?: RuntimeGlobalTransportShippingPayload | null;
  showAirRoutes?: boolean;
  selectedCityId?: string | null;
  onSelectCity?: (cityId: string) => void;
  height?: number;
  interactive?: boolean;
  showLabels?: boolean;
};

const IMPORTANT_CITY_IDS = new Set([
  'new-york',
  'chicago',
  'dallas',
  'miami',
  'seattle',
  'london',
  'paris',
  'madrid',
  'tel-aviv',
  'ankara',
  'beijing',
  'shenzhen',
  'hong-kong',
  'singapore',
  'sydney',
]);

type ConflictMapPoint = {
  id: string;
  lon: number;
  lat: number;
  iso2: string | null;
  country: string;
  location: string;
  actors: string;
  sideA: string;
  sideB: string;
  deaths: number;
  deathsLow: number | null;
  deathsHigh: number | null;
  violenceType: string;
  violenceLabel: string;
  occurredAt: string | null;
  source: string | null;
  sourceUrl: string | null;
  severity: string | null;
  tone: ConflictTone;
  color: string;
  size: number;
  label: string;
};

type CountryRisk = {
  iso2: string;
  name: string;
  eventCount: number;
  deaths: number;
  stateCount: number;
  nonStateCount: number;
  oneSidedCount: number;
  latestAt: string | null;
  score: number;
  level: CountryRiskLevel;
  topActors: string[];
  topLocations: string[];
  points: ConflictMapPoint[];
};

type CountryHoverState = {
  iso2: string;
  name: string;
  screenX: number;
  screenY: number;
  risk: CountryRisk;
};

type ConflictClusterPoint = {
  id: string;
  kind: 'conflict-cluster';
  lon: number;
  lat: number;
  count: number;
  deaths: number;
  maxDeaths: number;
  tone: ConflictTone;
  color: string;
  bounds: [number, number, number, number];
  sample: ConflictMapPoint;
};

type AirRoutePath = {
  id: string;
  routeKey: string;
  fromCode: string;
  toCode: string;
  fromCountry: string;
  toCountry: string;
  corridor: string;
  path: [number, number][];
  trafficScore: number;
  riskScore: number;
  status: string;
  airline: string;
  layer: 'trunk' | 'international' | 'regional';
  riskSources: AirRiskSource[];
  riskReason: string;
  sourceUrl: string;
  trend: number[];
  weatherAnchors: RiskAnchor[];
  conflictAnchors: RiskAnchor[];
  weatherIntensity: number;
  conflictIntensity: number;
};

type AirHubPoint = {
  code: string;
  name: string;
  city: string;
  country: string;
  lon: number;
  lat: number;
  routeCount: number;
  riskScore: number;
  status: string;
};

type AirFlightPoint = {
  id: string;
  fromCode: string;
  toCode: string;
  path: [number, number][];
  progress: number;
  riskScore: number;
  status: string;
};

type LiveAircraftPoint = {
  id: string;
  callsign: string;
  originCountry: string;
  regionLabel: string;
  lon: number;
  lat: number;
  altitude: number | null;
  velocity: number | null;
  heading: number | null;
  verticalRate: number | null;
  onGround: boolean;
  riskScore: number;
  status: string;
};

type AirMotionPoint = {
  id: string;
  lon: number;
  lat: number;
  routeId: string;
  source: Exclude<AirRiskSource, 'all'>;
  pulse: number;
  progress: number;
  emphasis: number;
  intensity: number;
};

type RiskAnchor = {
  progress: number;
  intensity: number;
};

type DeckTooltipState = {
  kind: 'city' | 'conflict' | 'cluster' | 'air-route' | 'air-hub' | 'air-flight' | 'live-aircraft';
  x: number;
  y: number;
  city?: WeatherMapPoint;
  conflict?: ConflictMapPoint;
  cluster?: ConflictClusterPoint;
  airRoute?: AirRoutePath;
  airHub?: AirHubPoint;
  airFlight?: AirFlightPoint;
  liveAircraft?: LiveAircraftPoint;
} | null;

type DeckHoverObject = WeatherMapPoint | ConflictMapPoint | ConflictClusterPoint | AirRoutePath | AirHubPoint | AirFlightPoint | LiveAircraftPoint;

type CountryNameLabel = {
  id: string;
  name: string;
  lon: number;
  lat: number;
  kind: 'major' | 'risk';
  level?: CountryRiskLevel;
  score?: number;
  importance: number;
  minZoom: number;
};

type SignalDensityPoint = {
  id: string;
  lon: number;
  lat: number;
  tone: 'cool' | 'warm' | 'risk' | 'alert';
  weight: number;
};

type AirLensMode = 'all' | 'trunk' | 'watch';
type AirFocusRegion = 'global' | 'atlantic' | 'europe' | 'asia' | 'gulf';
type AirRiskSource = 'all' | 'weather' | 'conflict' | 'corridor';

type AirFocusPreset = {
  id: AirFocusRegion;
  label: string;
  bounds: [number, number, number, number] | null;
  maxZoom?: number;
};

const LOCAL_WORLD_COUNTRIES_GEOJSON_URL = '/map-data/world-countries.geojson';
const WEATHER_COUNTRY_SOURCE_ID = 'wm-weather-country-boundaries';
const WEATHER_COUNTRY_NO_MATCH = '__weather_country_no_match__';
const WEATHER_DECK_POINT_NOTE = 'Perf note: before refactor WeatherDeckMap rendered up to 42 weather label buttons and 520 UCDP event buttons, driven by map.project() screen-state updates. Cities and UCDP markers now render as deck.gl GPU layers; only one tooltip plus selected detail panels remain as DOM.';
void WEATHER_DECK_POINT_NOTE;

const MAJOR_COUNTRY_LABELS: CountryNameLabel[] = [
  { id: 'US', name: 'UNITED STATES', lon: -99, lat: 38, kind: 'major', importance: 10, minZoom: 0 },
  { id: 'CA', name: 'CANADA', lon: -101, lat: 58, kind: 'major', importance: 8, minZoom: 0 },
  { id: 'BR', name: 'BRAZIL', lon: -53, lat: -10, kind: 'major', importance: 9, minZoom: 0 },
  { id: 'MX', name: 'MEXICO', lon: -102, lat: 23, kind: 'major', importance: 6, minZoom: 1.4 },
  { id: 'GB', name: 'UNITED KINGDOM', lon: -2.5, lat: 54.3, kind: 'major', importance: 6, minZoom: 1.2 },
  { id: 'FR', name: 'FRANCE', lon: 2, lat: 46.5, kind: 'major', importance: 6, minZoom: 1.8 },
  { id: 'DE', name: 'GERMANY', lon: 10.5, lat: 51.2, kind: 'major', importance: 6, minZoom: 1.8 },
  { id: 'RU', name: 'RUSSIA', lon: 90, lat: 61, kind: 'major', importance: 10, minZoom: 0 },
  { id: 'CN', name: 'CHINA', lon: 104, lat: 35, kind: 'major', importance: 10, minZoom: 0 },
  { id: 'IN', name: 'INDIA', lon: 78, lat: 22, kind: 'major', importance: 9, minZoom: 0 },
  { id: 'JP', name: 'JAPAN', lon: 138, lat: 38, kind: 'major', importance: 7, minZoom: 1.2 },
  { id: 'ID', name: 'INDONESIA', lon: 117, lat: -2, kind: 'major', importance: 7, minZoom: 1.3 },
  { id: 'AU', name: 'AUSTRALIA', lon: 134, lat: -25, kind: 'major', importance: 8, minZoom: 0 },
  { id: 'ZA', name: 'SOUTH AFRICA', lon: 24, lat: -29, kind: 'major', importance: 6, minZoom: 1.2 },
  { id: 'NG', name: 'NIGERIA', lon: 8, lat: 9.5, kind: 'major', importance: 6, minZoom: 1.8 },
  { id: 'EG', name: 'EGYPT', lon: 30, lat: 27, kind: 'major', importance: 6, minZoom: 1.6 },
  { id: 'TR', name: 'TURKEY', lon: 35, lat: 39, kind: 'major', importance: 6, minZoom: 1.6 },
  { id: 'IR', name: 'IRAN', lon: 53, lat: 32, kind: 'major', importance: 6, minZoom: 1.6 },
  { id: 'SA', name: 'SAUDI ARABIA', lon: 45, lat: 24, kind: 'major', importance: 5, minZoom: 1.8 },
  { id: 'KZ', name: 'KAZAKHSTAN', lon: 67, lat: 48, kind: 'major', importance: 6, minZoom: 1.4 },
  { id: 'AR', name: 'ARGENTINA', lon: -64, lat: -36, kind: 'major', importance: 5, minZoom: 1.6 },
];

const COUNTRY_ISO2_ALIASES: Record<string, string> = {
  afghanistan: 'AF',
  algeria: 'DZ',
  angola: 'AO',
  argentina: 'AR',
  armenia: 'AM',
  australia: 'AU',
  azerbaijan: 'AZ',
  bangladesh: 'BD',
  belarus: 'BY',
  belgium: 'BE',
  benin: 'BJ',
  bolivia: 'BO',
  brazil: 'BR',
  'burkina faso': 'BF',
  burundi: 'BI',
  cambodia: 'KH',
  cameroon: 'CM',
  canada: 'CA',
  'central african republic': 'CF',
  chad: 'TD',
  chile: 'CL',
  china: 'CN',
  colombia: 'CO',
  congo: 'CG',
  cuba: 'CU',
  'democratic republic of congo': 'CD',
  'democratic republic of the congo': 'CD',
  'dr congo': 'CD',
  ecuador: 'EC',
  egypt: 'EG',
  eritrea: 'ER',
  ethiopia: 'ET',
  france: 'FR',
  georgia: 'GE',
  germany: 'DE',
  ghana: 'GH',
  greece: 'GR',
  guatemala: 'GT',
  haiti: 'HT',
  honduras: 'HN',
  india: 'IN',
  indonesia: 'ID',
  iran: 'IR',
  iraq: 'IQ',
  israel: 'IL',
  italy: 'IT',
  japan: 'JP',
  jordan: 'JO',
  kazakhstan: 'KZ',
  kenya: 'KE',
  kosovo: 'XK',
  kyrgyzstan: 'KG',
  lebanon: 'LB',
  libya: 'LY',
  mali: 'ML',
  mexico: 'MX',
  moldova: 'MD',
  morocco: 'MA',
  mozambique: 'MZ',
  myanmar: 'MM',
  burma: 'MM',
  nepal: 'NP',
  nicaragua: 'NI',
  niger: 'NE',
  nigeria: 'NG',
  pakistan: 'PK',
  palestine: 'PS',
  peru: 'PE',
  philippines: 'PH',
  poland: 'PL',
  romania: 'RO',
  russia: 'RU',
  'russian federation': 'RU',
  rwanda: 'RW',
  senegal: 'SN',
  serbia: 'RS',
  somalia: 'SO',
  'south africa': 'ZA',
  'south sudan': 'SS',
  spain: 'ES',
  sri_lanka: 'LK',
  'sri lanka': 'LK',
  sudan: 'SD',
  sweden: 'SE',
  syria: 'SY',
  taiwan: 'TW',
  tajikistan: 'TJ',
  thailand: 'TH',
  tunisia: 'TN',
  turkey: 'TR',
  turkiye: 'TR',
  ukraine: 'UA',
  'united kingdom': 'GB',
  'united states': 'US',
  'united states of america': 'US',
  usa: 'US',
  uzbekistan: 'UZ',
  venezuela: 'VE',
  vietnam: 'VN',
  yemen: 'YE',
  zimbabwe: 'ZW',
};

const AIR_LENS_OPTIONS: Array<{ id: AirLensMode; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'trunk', label: 'Trunk' },
  { id: 'watch', label: 'Watch' },
];

const AIR_RISK_OPTIONS: Array<{ id: AirRiskSource; label: string }> = [
  { id: 'all', label: 'All Risk' },
  { id: 'weather', label: 'Weather' },
  { id: 'conflict', label: 'Conflict' },
  { id: 'corridor', label: 'Corridor' },
];

const AIR_FOCUS_PRESETS: AirFocusPreset[] = [
  { id: 'global', label: 'Global', bounds: null },
  { id: 'atlantic', label: 'Atlantic', bounds: [-105, 22, 25, 66], maxZoom: 3.25 },
  { id: 'europe', label: 'Europe', bounds: [-14, 34, 42, 64], maxZoom: 4.2 },
  { id: 'asia', label: 'Asia', bounds: [68, 1, 146, 55], maxZoom: 4.1 },
  { id: 'gulf', label: 'Gulf', bounds: [32, 15, 62, 34], maxZoom: 4.8 },
];

const AIR_FOCUS_PRESET_MAP = new Map(AIR_FOCUS_PRESETS.map((preset) => [preset.id, preset]));

function numberValue(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function compactText(value: string, max = 28) {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= max) return normalized;
  return `${normalized.slice(0, Math.max(0, max - 1)).trim()}…`;
}

function iso2ForCountry(country?: string | null) {
  const normalized = String(country || '').toLowerCase().replace(/[_-]+/g, ' ').replace(/[().]/g, '').replace(/\s+/g, ' ').trim();
  if (!normalized) return null;
  return COUNTRY_ISO2_ALIASES[normalized] || null;
}

function violenceTone(item: RuntimeGeoSanctionsShockItem | ConflictMapPoint): ConflictTone {
  const type = String(item.violenceType || '').trim();
  if (type === '1') return 'state';
  if (type === '2') return 'nonstate';
  if (type === '3') return 'onesided';
  return 'unknown';
}

function violenceLabel(type?: string | number | null) {
  const normalized = String(type || '').trim();
  if (normalized === '1') return 'STATE';
  if (normalized === '2') return 'NON-STATE';
  if (normalized === '3') return 'ONE-SIDED';
  return 'CONFLICT';
}

function conflictColor(item: RuntimeGeoSanctionsShockItem | ConflictMapPoint) {
  const tone = violenceTone(item);
  if (tone === 'state') return '#ff4d4d';
  if (tone === 'nonstate') return '#ff9f1c';
  if (tone === 'onesided') return '#ffd400';
  const severity = String(item.severity || '').toLowerCase();
  if (severity === 'critical') return '#ff4d4d';
  if (severity === 'warning') return '#ff9f1c';
  return '#ffd400';
}

function conflictSeverityScore(item: RuntimeGeoSanctionsShockItem | ConflictMapPoint) {
  const severity = String(item.severity || '').toLowerCase();
  const severityBase = severity === 'critical'
    ? 0.92
    : severity === 'warning' || severity === 'high'
      ? 0.72
      : severity === 'medium'
        ? 0.56
        : severity === 'low'
          ? 0.34
          : 0.42;
  const deaths = Math.max(0, numberValue((item as RuntimeGeoSanctionsShockItem).deathsBest ?? (item as ConflictMapPoint).deaths) ?? 0);
  const deathBoost = clamp01(Math.log10(deaths + 1) / 2.5);
  const toneBoost = violenceTone(item) === 'state' ? 0.1 : violenceTone(item) === 'onesided' ? 0.05 : 0;
  return clamp01(severityBase * 0.62 + deathBoost * 0.28 + toneBoost);
}

function countryRiskLevel(score: number): CountryRiskLevel {
  if (score >= 72) return 'critical';
  if (score >= 46) return 'elevated';
  if (score >= 16) return 'watch';
  return 'quiet';
}

function countryRiskColor(level: CountryRiskLevel) {
  if (level === 'critical') return '#d73535';
  if (level === 'elevated') return '#b86523';
  if (level === 'watch') return '#a19216';
  return '#2f5f8a';
}

function countryRiskOpacity(level: CountryRiskLevel) {
  if (level === 'critical') return 0.34;
  if (level === 'elevated') return 0.24;
  if (level === 'watch') return 0.16;
  return 0.05;
}

function parseDateMs(value?: string | null) {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function formatDateLabel(value?: string | null) {
  if (!value) return '--';
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return value.slice(0, 10);
  return parsed.toISOString().slice(0, 10);
}

function emptyCountryRisk(iso2: string, name: string): CountryRisk {
  return {
    iso2,
    name,
    eventCount: 0,
    deaths: 0,
    stateCount: 0,
    nonStateCount: 0,
    oneSidedCount: 0,
    latestAt: null,
    score: 0,
    level: 'quiet',
    topActors: [],
    topLocations: [],
    points: [],
  };
}

function temperatureLabel(value: number | null, unit: string) {
  if (value == null) return '--';
  return `${Math.round(value)}°${unit || ''}`;
}

function probabilityLabel(value: number | null) {
  if (value == null) return '--';
  return `${Math.round(value * 100)}%`;
}

function airRouteLayerLabel(layer: string) {
  if (layer === 'trunk') return 'TRUNK';
  if (layer === 'international') return 'INTERNATIONAL';
  return 'REGIONAL';
}

function airFocusLabel(region: AirFocusRegion) {
  return AIR_FOCUS_PRESET_MAP.get(region)?.label || 'Global';
}

function airRiskSourceLabel(source: AirRiskSource) {
  if (source === 'weather') return 'WEATHER';
  if (source === 'conflict') return 'CONFLICT';
  if (source === 'corridor') return 'CORRIDOR';
  return 'ALL RISK';
}

function binTemperatureLabel(bin: RuntimeGlobalWeatherCity['topBin'], fallbackUnit: string) {
  if (!bin) return null;
  const unit = String(bin.unit || fallbackUnit || '').toUpperCase();
  const min = numberValue(bin.minTemp);
  const max = numberValue(bin.maxTemp);
  const minValue = numberValue(bin.minValue);
  const maxValue = numberValue(bin.maxValue);
  if (minValue != null || maxValue != null) {
    const suffix = unit ? unit.toLowerCase() : '';
    if (bin.bucketType === 'below' && maxValue != null) return `${Math.round(maxValue)}${suffix}-`;
    if (bin.bucketType === 'above' && minValue != null) return `${Math.round(minValue)}${suffix}+`;
    if (minValue != null && maxValue != null && minValue !== maxValue) return `${Math.round(minValue)}-${Math.round(maxValue)}${suffix}`;
    if (minValue != null) return `${Math.round(minValue)}${suffix}`;
    if (maxValue != null) return `${Math.round(maxValue)}${suffix}`;
  }
  if (bin.bucketType === 'below' && max != null) return `${Math.round(max)}°${unit}-`;
  if (bin.bucketType === 'above' && min != null) return `${Math.round(min)}°${unit}+`;
  if (min != null && max != null && min !== max) return `${Math.round(min)}-${Math.round(max)}°${unit}`;
  if (min != null) return `${Math.round(min)}°${unit}`;
  if (max != null) return `${Math.round(max)}°${unit}`;
  return null;
}

function temperatureTone(city: RuntimeGlobalWeatherCity): WeatherTone {
  const temp = numberValue(city.forecastHigh ?? city.currentTemp);
  if (temp == null) return 'neutral';
  if (String(city.unit || '').toUpperCase() === 'F') {
    if (temp >= 90) return 'hot';
    if (temp <= 45) return 'cool';
    return 'neutral';
  }
  if (temp >= 32) return 'hot';
  if (temp <= 7) return 'cool';
  return 'neutral';
}

function clamp01(value: number) {
  return Math.max(0, Math.min(1, value));
}

function conditionStormScore(condition?: string | null) {
  const normalized = String(condition || '').toLowerCase().trim();
  if (!normalized) return 0.08;
  if (/(hurricane|typhoon|cyclone|tornado|supercell|blizzard|ice storm)/.test(normalized)) return 1;
  if (/(thunder|lightning|storm|squall|hail)/.test(normalized)) return 0.88;
  if (/(heavy rain|heavy snow|freezing rain|snowstorm)/.test(normalized)) return 0.78;
  if (/(rain|showers|snow|sleet|drizzle)/.test(normalized)) return 0.56;
  if (/(wind|gust|fog|mist|smoke|dust)/.test(normalized)) return 0.42;
  if (/(overcast|cloudy)/.test(normalized)) return 0.16;
  if (/(partly cloudy|mainly clear)/.test(normalized)) return 0.1;
  if (/(clear|sunny)/.test(normalized)) return 0.06;
  return 0.18;
}

function normalizeTemperatureToCelsius(value: number, unit: string) {
  return String(unit || '').toUpperCase() === 'F' ? (value - 32) * (5 / 9) : value;
}

function numericMax(values: Array<number | null | undefined>) {
  const filtered = values.filter((value): value is number => typeof value === 'number' && Number.isFinite(value));
  return filtered.length ? Math.max(...filtered) : null;
}

function hourlySwingScore(city: RuntimeGlobalWeatherCity) {
  const unit = String(city.unit || '').toUpperCase();
  const hourly = (city.hourly || [])
    .map((entry) => numberValue(entry?.temp))
    .filter((value): value is number => value != null);
  if (hourly.length < 2) return 0;
  const min = Math.min(...hourly);
  const max = Math.max(...hourly);
  const swingC = Math.abs(normalizeTemperatureToCelsius(max, unit) - normalizeTemperatureToCelsius(min, unit));
  return clamp01(swingC / 8);
}

function temperatureExtremityScore(city: RuntimeGlobalWeatherCity) {
  const unit = String(city.unit || '').toUpperCase();
  const reference = numberValue(city.forecastHigh ?? city.currentTemp ?? city.todayHigh ?? city.todayLow);
  if (reference == null) return 0;
  const tempC = normalizeTemperatureToCelsius(reference, unit);
  if (tempC >= 40 || tempC <= -8) return 1;
  if (tempC >= 35 || tempC <= -2) return 0.78;
  if (tempC >= 31 || tempC <= 3) return 0.52;
  if (tempC >= 28 || tempC <= 7) return 0.3;
  return 0.08;
}

function windImpactScore(city: RuntimeGlobalWeatherCity) {
  const hourlyWind = (city.hourly || [])
    .map((entry) => numberValue(entry?.windSpeed))
    .filter((value): value is number => value != null);
  const hourlyGust = (city.hourly || [])
    .map((entry) => numberValue(entry?.windGust))
    .filter((value): value is number => value != null);
  const peakWind = numericMax([
    numberValue(city.currentWindSpeed),
    numberValue(city.todayWindSpeed),
    numberValue(city.forecastWindSpeedMax),
    ...hourlyWind,
  ]);
  const peakGust = numericMax([
    numberValue(city.currentWindGust),
    numberValue(city.todayWindGust),
    numberValue(city.forecastWindGustMax),
    ...hourlyGust,
  ]);
  const windScore = peakWind == null ? 0 : clamp01(peakWind / 52);
  const gustScore = peakGust == null ? 0 : clamp01(peakGust / 82);
  return clamp01(Math.max(windScore * 0.8, gustScore));
}

function precipitationImpactScore(city: RuntimeGlobalWeatherCity) {
  const hourlyPrecip = (city.hourly || [])
    .map((entry) => numberValue(entry?.precipitation))
    .filter((value): value is number => value != null);
  const hourlyProbability = (city.hourly || [])
    .map((entry) => numberValue(entry?.precipitationProbability))
    .filter((value): value is number => value != null);
  const peakRate = numericMax([numberValue(city.currentPrecipitation), ...hourlyPrecip]);
  const dailySum = numericMax([
    numberValue(city.todayPrecipitationSum),
    numberValue(city.forecastPrecipitationSum),
    ...(city.daily || []).map((entry) => numberValue(entry?.precipitationSum)),
  ]);
  const peakProbability = numericMax([
    numberValue(city.todayPrecipitationProbability),
    numberValue(city.forecastPrecipitationProbabilityMax),
    ...hourlyProbability,
    ...(city.daily || []).map((entry) => numberValue(entry?.precipitationProbabilityMax)),
  ]);
  const rateScore = peakRate == null ? 0 : clamp01(peakRate / 9);
  const sumScore = dailySum == null ? 0 : clamp01(dailySum / 34);
  const probabilityScore = peakProbability == null ? 0 : clamp01(peakProbability / 100);
  return clamp01(Math.max(rateScore * 0.9, sumScore * 0.82, probabilityScore * 0.72));
}

function weatherImpactScore(city: RuntimeGlobalWeatherCity) {
  const condition = conditionStormScore(city.condition);
  const extremity = temperatureExtremityScore(city);
  const swing = hourlySwingScore(city);
  const wind = windImpactScore(city);
  const precipitation = precipitationImpactScore(city);
  const toneBoost = temperatureTone(city) === 'neutral' ? 0 : 0.08;
  const hasObservedSeverity = wind > 0 || precipitation > 0;
  if (hasObservedSeverity) {
    return clamp01(
      0.02
      + wind * 0.38
      + precipitation * 0.34
      + condition * 0.14
      + extremity * 0.07
      + swing * 0.03
      + toneBoost * 0.5,
    );
  }
  return clamp01(0.04 + condition * 0.64 + extremity * 0.2 + swing * 0.12 + toneBoost);
}

function marketTone(city: RuntimeGlobalWeatherCity): MarketTone {
  if (!city.eventSlug) return 'none';
  const coverageParts = String(city.quoteCoverage || '').split('/').map((part) => Number(part));
  const quotedRaw = coverageParts[0];
  const totalRaw = coverageParts[1];
  const quoted = typeof quotedRaw === 'number' && Number.isFinite(quotedRaw) ? quotedRaw : 0;
  const total = typeof totalRaw === 'number' && Number.isFinite(totalRaw) ? totalRaw : 0;
  if (total > 0 && quoted / total >= 0.7) {
    return 'market';
  }
  return 'watch';
}

function shouldShowLabel(point: WeatherMapPoint, selectedCityId?: string | null) {
  return point.id === selectedCityId
    || point.forecastHigh != null
    || point.currentTemp != null
    || Boolean(point.topBinLabel)
    || point.temperatureTone === 'hot'
    || point.weatherImpact >= 0.52
    || IMPORTANT_CITY_IDS.has(point.id);
}

function normalizePoints(items: RuntimeGlobalWeatherCity[]): WeatherMapPoint[] {
  return items.flatMap((city) => {
    const lat = numberValue(city.lat);
    const lon = numberValue(city.lon);
    const id = String(city.cityId || '').trim();
    if (!id || lat == null || lon == null) return [];
    const unit = String(city.unit || '').toUpperCase();
    const currentTemp = numberValue(city.currentTemp);
    const forecastHigh = numberValue(city.forecastHigh ?? city.todayHigh);
    const topBinPrice = numberValue(city.topBin?.midPriceYes);
    const topBinBid = numberValue(city.topBin?.bestBidYes);
    const topBinAsk = numberValue(city.topBin?.bestAskYes);
    const topBinLabel = city.topBin?.label ? String(city.topBin.label) : null;
    const topBinTemperature = binTemperatureLabel(city.topBin, unit);
    const weatherTemperature = temperatureLabel(forecastHigh ?? currentTemp, unit);
    const priceSuffix = topBinPrice != null ? ` · ${probabilityLabel(topBinPrice)}` : '';
    const sublabel = `${topBinTemperature || weatherTemperature}${priceSuffix}`;
    const impact = weatherImpactScore(city);
    return [{
      id,
      city: String(city.city || id),
      country: String(city.country || ''),
      lon,
      lat,
      unit,
      currentTemp,
      forecastHigh,
      condition: String(city.condition || 'Condition pending'),
      quoteCoverage: String(city.quoteCoverage || '0/0'),
      topBinLabel,
      topBinPrice,
      topBinBid,
      topBinAsk,
      priceSource: city.topBin?.priceSource ? String(city.topBin.priceSource) : null,
      bookStatus: city.topBin?.bookStatus ? String(city.topBin.bookStatus) : null,
      marketUrl: city.marketUrl ? String(city.marketUrl) : null,
      temperatureTone: temperatureTone(city),
      marketTone: marketTone(city),
      label: `${String(city.city || id)}\n${sublabel}`,
      sublabel,
      labelDx: numberValue(city.labelDx) ?? 8,
      labelDy: numberValue(city.labelDy) ?? -16,
      weatherImpact: impact,
    }];
  });
}

function normalizeConflictPoints(items: RuntimeGeoSanctionsShockItem[] = []): ConflictMapPoint[] {
  return items.slice(0, 1200).flatMap((item, index): ConflictMapPoint[] => {
    const lat = numberValue(item.latitude);
    const lon = numberValue(item.longitude);
    if (lat == null || lon == null || lat < -90 || lat > 90 || lon < -180 || lon > 180) return [];
    const deaths = Math.max(0, numberValue(item.deathsBest) ?? 0);
    const country = String(item.country || item.locationLabel || 'UCDP');
    const sideA = String(item.sideA || '').trim();
    const sideB = String(item.sideB || '').trim();
    const actors = [sideA, sideB].filter(Boolean).join(' vs ');
    const tone = violenceTone(item);
    const color = conflictColor(item);
    const size = Math.min(20, 7 + Math.log10(deaths + 1) * 5);
    return [{
      id: String(item.id || `ucdp-${index}`),
      lon,
      lat,
      iso2: iso2ForCountry(country),
      country,
      location: String(item.locationLabel || country),
      actors,
      sideA,
      sideB,
      deaths,
      deathsLow: numberValue(item.deathsLow),
      deathsHigh: numberValue(item.deathsHigh),
      violenceType: String(item.violenceType || ''),
      violenceLabel: violenceLabel(item.violenceType),
      occurredAt: item.occurredAt ? String(item.occurredAt) : null,
      source: item.source ? String(item.source) : null,
      sourceUrl: item.sourceUrl ? String(item.sourceUrl) : null,
      severity: item.severity ? String(item.severity) : null,
      tone,
      color,
      size,
      label: `${country}${deaths ? ` · ${deaths} deaths` : ''}${actors ? ` · ${actors}` : ''}`,
    }];
  });
}

function airCoord(lonValue?: number | string | null, latValue?: number | string | null): [number, number] | null {
  const lon = numberValue(lonValue);
  const lat = numberValue(latValue);
  if (lon == null || lat == null || lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return [lon, lat];
}

function wrapDeltaLon(delta: number) {
  if (delta > 180) return delta - 360;
  if (delta < -180) return delta + 360;
  return delta;
}

function normalizeLon(lon: number) {
  let normalized = ((lon + 180) % 360 + 360) % 360 - 180;
  if (normalized === -180 && lon > 0) normalized = 180;
  return normalized;
}

function airArcPath(from: [number, number], to: [number, number], steps = 36): [number, number][] {
  const [fromLon, fromLat] = from;
  const [toLonRaw, toLat] = to;
  const deltaLon = wrapDeltaLon(toLonRaw - fromLon);
  const distance = Math.sqrt(deltaLon * deltaLon + (toLat - fromLat) * (toLat - fromLat));
  const lift = Math.min(26, Math.max(5, distance * 0.18));
  const direction = deltaLon >= 0 ? 1 : -1;
  const controlLon = fromLon + deltaLon * 0.5;
  const controlLat = (fromLat + toLat) * 0.5 + lift * direction * 0.18 + lift;
  const points: [number, number][] = [];
  for (let index = 0; index <= steps; index += 1) {
    const t = index / steps;
    const one = 1 - t;
    const lon = one * one * fromLon + 2 * one * t * controlLon + t * t * (fromLon + deltaLon);
    const lat = one * one * fromLat + 2 * one * t * controlLat + t * t * toLat;
    points.push([lon, Math.max(-85, Math.min(85, lat))]);
  }
  return points;
}

function splitWrappedAirPath(points: [number, number][]): [number, number][][] {
  if (points.length < 2) return [];
  const segments: [number, number][][] = [];
  let current: [number, number][] = [[normalizeLon(points[0]?.[0] ?? 0), points[0]?.[1] ?? 0]];
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const point = points[index];
    if (!previous || !point) continue;
    const [prevLon, prevLat] = previous;
    const [lon, lat] = point;
    let crossed = false;
    if ((prevLon <= 180 && lon > 180) || (prevLon >= 180 && lon < 180 && Math.abs(lon - prevLon) > 90)) {
      const t = (180 - prevLon) / (lon - prevLon || 1);
      const crossingLat = prevLat + (lat - prevLat) * Math.max(0, Math.min(1, t));
      current.push([180, crossingLat]);
      if (current.length >= 2) segments.push(current);
      current = [[-180, crossingLat], [normalizeLon(lon), lat]];
      crossed = true;
    } else if ((prevLon >= -180 && lon < -180) || (prevLon <= -180 && lon > -180 && Math.abs(lon - prevLon) > 90)) {
      const t = (-180 - prevLon) / (lon - prevLon || 1);
      const crossingLat = prevLat + (lat - prevLat) * Math.max(0, Math.min(1, t));
      current.push([-180, crossingLat]);
      if (current.length >= 2) segments.push(current);
      current = [[180, crossingLat], [normalizeLon(lon), lat]];
      crossed = true;
    }
    if (!crossed) current.push([normalizeLon(lon), lat]);
  }
  if (current.length >= 2) segments.push(current);
  return segments
    .map((segment) => segment.filter(([lon, lat]) => Number.isFinite(lon) && Number.isFinite(lat)))
    .filter((segment) => segment.length >= 2);
}

function pointAlongPath(path: [number, number][], progress: number): [number, number] {
  if (!path.length) return [0, 0];
  if (path.length === 1) return path[0] || [0, 0];
  const scaled = Math.max(0, Math.min(0.999, progress)) * (path.length - 1);
  const index = Math.floor(scaled);
  const next = Math.min(path.length - 1, index + 1);
  const local = scaled - index;
  const currentPoint = path[index] || path[0] || [0, 0];
  const nextPoint = path[next] || currentPoint;
  return [
    currentPoint[0] + (nextPoint[0] - currentPoint[0]) * local,
    currentPoint[1] + (nextPoint[1] - currentPoint[1]) * local,
  ];
}

function endpointRiskAnchors(fromIntensity: number, toIntensity: number): RiskAnchor[] {
  const anchors: RiskAnchor[] = [];
  if (fromIntensity > 0 && toIntensity > 0) {
    anchors.push({ progress: 0.24, intensity: fromIntensity });
    anchors.push({ progress: 0.76, intensity: toIntensity });
    return anchors;
  }
  if (fromIntensity > 0) anchors.push({ progress: 0.22, intensity: fromIntensity });
  if (toIntensity > 0) anchors.push({ progress: 0.78, intensity: toIntensity });
  return anchors;
}

function routeHotspotAnchors(path: [number, number][], hotspots: Array<{ lon: number; lat: number; intensity: number }>, radius: number, limit = 3) {
  if (!hotspots.length || !path.length) return [];
  const matches: RiskAnchor[] = [];
  for (let index = 0; index < path.length; index += 1) {
    const point = path[index];
    if (!point) continue;
    const [lon, lat] = point;
    const latScale = Math.max(0.42, Math.cos((lat * Math.PI) / 180));
    let bestDistance = Infinity;
    let bestIntensity = 0;
    for (const hotspot of hotspots) {
      const dx = (hotspot.lon - lon) * latScale;
      const dy = hotspot.lat - lat;
      const distance = Math.sqrt(dx * dx + dy * dy);
      if (distance <= radius && distance < bestDistance) {
        bestDistance = distance;
        bestIntensity = hotspot.intensity;
      }
    }
    if (bestDistance !== Infinity) {
      matches.push({
        progress: index / Math.max(1, path.length - 1),
        intensity: clamp01(bestIntensity * (1 - bestDistance / Math.max(radius, 0.1))),
      });
    }
  }
  return matches
    .sort((left, right) => right.intensity - left.intensity)
    .reduce<RiskAnchor[]>((anchors, match) => {
      const existing = anchors.find((anchor) => Math.abs(anchor.progress - match.progress) < 0.08);
      if (existing) {
        existing.intensity = Math.max(existing.intensity, match.intensity);
        return anchors;
      }
      anchors.push({ ...match });
      return anchors;
    }, [])
    .slice(0, limit)
    .sort((left, right) => left.progress - right.progress);
}

function mergeRiskAnchors(anchors: RiskAnchor[]) {
  return anchors
    .filter((anchor) => anchor.intensity > 0.04)
    .sort((left, right) => left.progress - right.progress)
    .reduce<RiskAnchor[]>((merged, anchor) => {
      const last = merged[merged.length - 1];
      if (last && Math.abs(last.progress - anchor.progress) < 0.05) {
        last.progress = (last.progress + anchor.progress) * 0.5;
        last.intensity = Math.max(last.intensity, anchor.intensity);
        return merged;
      }
      merged.push({ ...anchor });
      return merged;
    }, []);
}

function routeMotionSource(route: AirRoutePath, lens: AirLensMode, riskSource: AirRiskSource): Exclude<AirRiskSource, 'all'> | null {
  if (lens === 'watch' && riskSource !== 'all') {
    return route.riskSources.includes(riskSource) ? riskSource : null;
  }
  if (route.riskSources.includes('conflict')) return 'conflict';
  if (route.riskSources.includes('weather')) return 'weather';
  if (route.riskSources.includes('corridor')) return 'corridor';
  return null;
}

function buildAirMotionPoints(routes: AirRoutePath[], animationTime: number, lens: AirLensMode, riskSource: AirRiskSource): AirMotionPoint[] {
  const points: AirMotionPoint[] = [];
  routes.forEach((route) => {
    const source = routeMotionSource(route, lens, riskSource);
    if (!source) return;
    const seed = hashUnit(`air-motion:${route.id}`);
    const emphasis = Math.max(0.72, Math.min(1.45, 0.72 + route.trafficScore / 120 + route.riskScore / 220));
    if (source === 'conflict') {
      const anchors = route.conflictAnchors.length
        ? route.conflictAnchors.slice(0, 3)
        : [{ progress: 0.14 + seed * 0.72, intensity: Math.max(0.38, route.conflictIntensity || 0.48) }];
      anchors.forEach((anchor, index) => {
        const pulse = 0.5 + 0.5 * Math.sin(animationTime * (4.6 + anchor.intensity * 2.4) + (seed + index * 0.17) * Math.PI * 4);
        const [lon, lat] = pointAlongPath(route.path, anchor.progress);
        points.push({
          id: `${route.id}:conflict:${index}`,
          lon,
          lat,
          routeId: route.id,
          source,
          pulse,
          progress: anchor.progress,
          emphasis: emphasis + index * 0.08,
          intensity: anchor.intensity,
        });
      });
      return;
    }
    if (source === 'weather') {
      const anchors = route.weatherAnchors.length
        ? route.weatherAnchors.slice(0, 2)
        : [{ progress: 0.32, intensity: Math.max(0.24, route.weatherIntensity || 0.34) }, { progress: 0.68, intensity: Math.max(0.24, route.weatherIntensity || 0.34) }];
      anchors.forEach((anchor, anchorIndex) => {
        const drift = 0.14 + hashUnit(`${route.id}:weather-drift:${anchorIndex}`) * 0.12;
        const stormIntensity = clamp01((anchor.intensity + route.weatherIntensity) * 0.5);
        const forwardSpeed = 0.022 + stormIntensity * 0.064 + seed * 0.018;
        const reverseSpeed = 0.016 + stormIntensity * 0.048 + seed * 0.014;
        [
          { direction: 1, speed: forwardSpeed },
          { direction: -1, speed: reverseSpeed },
        ].forEach((flow, index) => {
          const progress = (anchor.progress + flow.direction * animationTime * flow.speed + (index === 0 ? drift : -drift) + 1) % 1;
          const pulse = 0.58 + 0.42 * Math.sin(animationTime * (1.8 + stormIntensity * 1.8 + index * 0.3) + (seed + anchorIndex + index) * Math.PI * 3);
          const [lon, lat] = pointAlongPath(route.path, progress);
          points.push({
            id: `${route.id}:weather:${anchorIndex}:${index}`,
            lon,
            lat,
            routeId: route.id,
            source,
            pulse,
            progress,
            emphasis: emphasis + anchorIndex * 0.06,
            intensity: stormIntensity,
          });
        });
      });
      return;
    }
    const anchors = route.layer === 'trunk' ? [0.24, 0.68] : [0.46];
    anchors.forEach((anchor, index) => {
      const progress = (anchor + seed * 0.16 + animationTime * (0.018 + seed * 0.007)) % 1;
      const pulse = 0.72 + 0.12 * Math.sin(animationTime * 1.2 + (seed + index * 0.13) * Math.PI * 2);
      const [lon, lat] = pointAlongPath(route.path, progress);
      points.push({
        id: `${route.id}:corridor:${index}`,
        lon,
        lat,
        routeId: route.id,
        source,
        pulse,
        progress,
        emphasis,
        intensity: Math.max(0.26, Math.min(0.72, 0.24 + route.trafficScore / 140)),
      });
    });
  });
  return points;
}

function normalizeAirRoutes(payload?: RuntimeGlobalTransportShippingPayload | null): AirRoutePath[] {
  return (payload?.aviation?.routes || []).flatMap((route, index): AirRoutePath[] => {
    const from = airCoord(route.fromLon, route.fromLat);
    const to = airCoord(route.toLon, route.toLat);
    const fromCode = String(route.fromCode || '').trim();
    const toCode = String(route.toCode || '').trim();
    if (!from || !to || !fromCode || !toCode) return [];
    const id = String(route.id || `${fromCode}-${toCode}-${index}`);
    const routeKey = `${fromCode}-${toCode}`;
    const backendRiskSources = normalizeAirRiskSources(route.riskSources);
    return splitWrappedAirPath(airArcPath(from, to)).map((path, segmentIndex) => ({
      id: `${id}-${segmentIndex}`,
      routeKey,
      fromCode,
      toCode,
      fromCountry: String(route.fromCountry || ''),
      toCountry: String(route.toCountry || ''),
      corridor: String(route.corridor || `${route.fromCountry || ''} / ${route.toCountry || ''}`).trim(),
      path,
      trafficScore: numberValue(route.trafficScore) ?? 30,
      riskScore: numberValue(route.riskScore) ?? 0,
      status: String(route.status || 'normal'),
      airline: String(route.airline || 'OpenFlights'),
      layer: route.layer === 'trunk' || route.layer === 'international' || route.layer === 'regional'
        ? route.layer
        : ((numberValue(route.trafficScore) ?? 0) >= 70 ? 'trunk' : 'regional'),
      riskSources: backendRiskSources,
      riskReason: String(route.riskReason || ''),
      sourceUrl: String(route.sourceUrl || ''),
      trend: normalizeAirTrend(route.trend),
      weatherAnchors: [],
      conflictAnchors: [],
      weatherIntensity: backendRiskSources.includes('weather') ? Math.max(0.18, (numberValue(route.riskScore) ?? 0) / 180) : 0,
      conflictIntensity: backendRiskSources.includes('conflict') ? Math.max(0.2, (numberValue(route.riskScore) ?? 0) / 150) : 0,
    }));
  });
}

function normalizeAirHubs(payload?: RuntimeGlobalTransportShippingPayload | null): AirHubPoint[] {
  return (payload?.aviation?.hubs || []).flatMap((hub): AirHubPoint[] => {
    const coord = airCoord(hub.lon, hub.lat);
    const code = String(hub.code || '').trim();
    if (!coord || !code) return [];
    return [{
      code,
      name: String(hub.name || code),
      city: String(hub.city || ''),
      country: String(hub.country || ''),
      lon: coord[0],
      lat: coord[1],
      routeCount: numberValue(hub.routeCount) ?? 0,
      riskScore: numberValue(hub.riskScore) ?? 0,
      status: String(hub.status || 'normal'),
    }];
  });
}

function normalizeAirFlights(payload: RuntimeGlobalTransportShippingPayload | null | undefined, routes: AirRoutePath[], animationTime: number): AirFlightPoint[] {
  const routeByKey = new Map<string, AirRoutePath>();
  routes.forEach((route) => {
    const existing = routeByKey.get(route.routeKey);
    if (!existing || route.path.length > existing.path.length) routeByKey.set(route.routeKey, route);
  });
  return (payload?.aviation?.flights || []).flatMap((flight, index): AirFlightPoint[] => {
    const fromCode = String(flight.fromCode || '').trim();
    const toCode = String(flight.toCode || '').trim();
    const route = routeByKey.get(`${fromCode}-${toCode}`);
    if (!route) return [];
    const phase = numberValue(flight.phase) ?? index * 0.11;
    const speed = numberValue(flight.speed) ?? 0.06;
    const progress = (phase + animationTime * speed) % 1;
    return [{
      id: String(flight.id || `aircraft-${fromCode}-${toCode}-${index}`),
      fromCode,
      toCode,
      path: route.path,
      progress,
      riskScore: numberValue(flight.riskScore) ?? route.riskScore,
      status: String(flight.status || route.status || 'normal'),
    }];
  });
}

function normalizeLiveAircraft(payload?: RuntimeGlobalTransportShippingPayload | null): LiveAircraftPoint[] {
  return (payload?.aviation?.liveFlights || []).flatMap((row, index): LiveAircraftPoint[] => {
    const coord = airCoord(row.lon, row.lat);
    if (!coord) return [];
    return [{
      id: String(row.id || row.icao24 || `opensky-${index}`),
      callsign: String(row.callsign || row.icao24 || 'OPEN'),
      originCountry: String(row.originCountry || 'Unknown'),
      regionLabel: String(row.regionLabel || row.region || 'OpenSky'),
      lon: coord[0],
      lat: coord[1],
      altitude: numberValue(row.baroAltitude),
      velocity: numberValue(row.velocity),
      heading: numberValue(row.heading),
      verticalRate: numberValue(row.verticalRate),
      onGround: Boolean(row.onGround),
      riskScore: numberValue(row.riskScore) ?? 0,
      status: String(row.status || 'normal'),
    }];
  });
}

function enrichedAirRoutes(routes: AirRoutePath[], cities: WeatherMapPoint[], conflicts: ConflictMapPoint[]) {
  const weatherCountries = new Map<string, number>();
  cities
    .filter((city) => city.weatherImpact >= 0.18)
    .forEach((city) => {
      const iso2 = iso2ForCountry(city.country);
      if (!iso2) return;
      weatherCountries.set(iso2, Math.max(weatherCountries.get(iso2) || 0, city.weatherImpact));
    });
  const weatherHotspots = cities
    .filter((city) => city.weatherImpact >= 0.18)
    .map((city) => ({ lon: city.lon, lat: city.lat, intensity: city.weatherImpact }));
  const conflictCountries = new Map<string, number>();
  conflicts.forEach((point) => {
    if (!point.iso2) return;
    const severity = conflictSeverityScore(point);
    conflictCountries.set(point.iso2, Math.max(conflictCountries.get(point.iso2) || 0, severity));
  });
  const conflictHotspots = conflicts
    .filter((point) => point.deaths > 0 || point.tone !== 'unknown')
    .sort((left, right) => conflictSeverityScore(right) - conflictSeverityScore(left) || right.deaths - left.deaths)
    .slice(0, 320)
    .map((point) => ({ lon: point.lon, lat: point.lat, intensity: conflictSeverityScore(point) }));
  return routes.map((route) => {
    const fromIso = iso2ForCountry(route.fromCountry);
    const toIso = iso2ForCountry(route.toCountry);
    const fromConflictIntensity = fromIso ? (conflictCountries.get(fromIso) || 0) : 0;
    const toConflictIntensity = toIso ? (conflictCountries.get(toIso) || 0) : 0;
    const fromWeatherIntensity = fromIso ? (weatherCountries.get(fromIso) || 0) : 0;
    const toWeatherIntensity = toIso ? (weatherCountries.get(toIso) || 0) : 0;
    const conflictAnchors = mergeRiskAnchors([
      ...endpointRiskAnchors(fromConflictIntensity, toConflictIntensity),
      ...routeHotspotAnchors(route.path, conflictHotspots, 8.8, 3),
    ]);
    const weatherAnchors = mergeRiskAnchors([
      ...endpointRiskAnchors(fromWeatherIntensity, toWeatherIntensity),
      ...routeHotspotAnchors(route.path, weatherHotspots, 5.2, 3),
    ]);
    const conflictIntensity = clamp01(Math.max(
      conflictAnchors.reduce((max, anchor) => Math.max(max, anchor.intensity), 0),
      route.status === 'watch' ? route.riskScore / 180 : route.riskScore / 240,
    ));
    const weatherIntensity = clamp01(Math.max(
      weatherAnchors.reduce((max, anchor) => Math.max(max, anchor.intensity), 0),
      route.status === 'watch' ? route.riskScore / 260 : 0,
    ));
    const riskSources: AirRiskSource[] = [...route.riskSources];
    if (conflictAnchors.length && conflictIntensity >= 0.16) {
      riskSources.push('conflict');
    }
    if (weatherAnchors.length && weatherIntensity >= 0.14) {
      riskSources.push('weather');
    }
    if (
      route.status === 'watch'
      || route.layer === 'trunk'
      || route.trafficScore >= 72
      || (route.fromCountry && route.toCountry && route.fromCountry !== route.toCountry)
    ) {
      riskSources.push('corridor');
    }
    if (!riskSources.length && route.riskScore >= 60) riskSources.push('corridor');
    return { ...route, riskSources: listUnique(riskSources), weatherAnchors, conflictAnchors, conflictIntensity, weatherIntensity };
  });
}

function airRouteMatchesLens(route: AirRoutePath, lens: AirLensMode) {
  if (lens === 'watch') return route.riskSources.length > 0;
  if (lens === 'trunk') return route.layer === 'trunk' || route.trafficScore >= 70;
  return true;
}

function airRouteMatchesRiskSource(route: AirRoutePath, source: AirRiskSource) {
  if (source === 'all') return true;
  return route.riskSources.includes(source);
}

function normalizeAirRiskSources(value?: unknown): AirRiskSource[] {
  if (!Array.isArray(value)) return [];
  const valid = new Set<AirRiskSource>(['weather', 'conflict', 'corridor']);
  return value
    .map((item) => String(item || '').toLowerCase().trim())
    .filter((item): item is AirRiskSource => valid.has(item as AirRiskSource));
}

function normalizeAirTrend(value?: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => numberValue(item)).filter((item): item is number => item !== null).slice(0, 12);
}

function listUnique<T>(items: T[]): T[] {
  return Array.from(new Set(items));
}

function pointInRect(lon: number, lat: number, bounds: [number, number, number, number]) {
  return lon >= bounds[0] && lon <= bounds[2] && lat >= bounds[1] && lat <= bounds[3];
}

function airRouteMatchesRegion(route: AirRoutePath, region: AirFocusRegion) {
  if (region === 'global') return true;
  const preset = AIR_FOCUS_PRESET_MAP.get(region);
  if (!preset?.bounds) return true;
  return route.path.some(([lon, lat]) => pointInRect(lon, lat, preset.bounds!));
}

function airHubMatchesRegion(hub: AirHubPoint, region: AirFocusRegion) {
  if (region === 'global') return true;
  const preset = AIR_FOCUS_PRESET_MAP.get(region);
  if (!preset?.bounds) return true;
  return pointInRect(hub.lon, hub.lat, preset.bounds);
}

function airRoutePriority(route: AirRoutePath) {
  const watchRank = route.riskSources.length > 0 ? 0 : 1;
  const sourceRank = route.riskSources.includes('conflict') ? 0 : route.riskSources.includes('weather') ? 1 : route.riskSources.includes('corridor') ? 2 : 3;
  const layerRank = route.layer === 'trunk' ? 0 : route.layer === 'international' ? 1 : 2;
  return [watchRank, sourceRank, layerRank, -(route.trafficScore || 0), -(route.riskScore || 0), route.id] as const;
}

function sortAirRoutes(routes: AirRoutePath[]) {
  return [...routes].sort((left, right) => {
    const a = airRoutePriority(left);
    const b = airRoutePriority(right);
    if (a[0] !== b[0]) return a[0] - b[0];
    if (a[1] !== b[1]) return a[1] - b[1];
    if (a[2] !== b[2]) return a[2] - b[2];
    if (a[3] !== b[3]) return a[3] - b[3];
    if (a[4] !== b[4]) return a[4] - b[4];
    if (a[5] < b[5]) return -1;
    if (a[5] > b[5]) return 1;
    return 0;
  });
}

function airRouteBudget(zoom: number, lens: AirLensMode, region: AirFocusRegion) {
  if (region !== 'global') return zoom < 2.4 ? 220 : 320;
  if (lens === 'watch') return zoom < 2.3 ? 110 : 165;
  if (lens === 'trunk') return zoom < 2.3 ? 140 : 210;
  return zoom < 2.1 ? 380 : 560;
}

function buildCountryRisks(points: ConflictMapPoint[]): CountryRisk[] {
  const groups = new Map<string, CountryRisk>();
  points.forEach((point) => {
    if (!point.iso2) return;
    const existing = groups.get(point.iso2) || emptyCountryRisk(point.iso2, point.country);
    existing.points.push(point);
    existing.name = existing.name || point.country;
    existing.eventCount += 1;
    existing.deaths += point.deaths;
    if (point.tone === 'state') existing.stateCount += 1;
    if (point.tone === 'nonstate') existing.nonStateCount += 1;
    if (point.tone === 'onesided') existing.oneSidedCount += 1;
    if (!existing.latestAt || parseDateMs(point.occurredAt) > parseDateMs(existing.latestAt)) {
      existing.latestAt = point.occurredAt;
    }
    groups.set(point.iso2, existing);
  });

  return Array.from(groups.values()).map((risk) => {
    const actorCounts = new Map<string, number>();
    const locationCounts = new Map<string, number>();
    risk.points.forEach((point) => {
      const actors = point.actors || point.sideA || point.sideB;
      if (actors) actorCounts.set(actors, (actorCounts.get(actors) || 0) + 1);
      if (point.location) locationCounts.set(point.location, (locationCounts.get(point.location) || 0) + 1);
    });
    const score = Math.min(100, Math.round(
      Math.log10(risk.deaths + 1) * 24
      + Math.min(30, risk.eventCount * 1.65)
      + risk.stateCount * 2.2
      + risk.oneSidedCount * 1.4,
    ));
    return {
      ...risk,
      score,
      level: countryRiskLevel(score),
      points: risk.points.slice().sort((a, b) => parseDateMs(b.occurredAt) - parseDateMs(a.occurredAt)),
      topActors: Array.from(actorCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([actor]) => actor),
      topLocations: Array.from(locationCounts.entries()).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([location]) => location),
    };
  }).sort((a, b) => b.score - a.score || b.deaths - a.deaths || b.eventCount - a.eventCount);
}

function firstSymbolLayerId(map: MapLibreMap) {
  return (map.getStyle().layers || []).find((layer) => layer.type === 'symbol')?.id;
}

function addLayerSafe(map: MapLibreMap, layer: any, beforeId?: string) {
  if (map.getLayer(layer.id)) return;
  try {
    map.addLayer(layer, beforeId);
  } catch {
    if (!map.getLayer(layer.id)) map.addLayer(layer);
  }
}

function addSourceSafe(map: MapLibreMap, id: string, data: string) {
  if (map.getSource(id)) return;
  map.addSource(id, { type: 'geojson', data });
}

function setPaintSafe(map: MapLibreMap, layerId: string, property: string, value: unknown) {
  if (!map.getLayer(layerId)) return;
  try {
    map.setPaintProperty(layerId, property, value as any);
  } catch {
    // Third-party basemap styles can omit or lock individual paint properties.
  }
}

function tuneWeatherBasemap(map: MapLibreMap) {
  if (!map.getStyle()) return;
  ['boundary_country_outline', 'boundary_country_inner', 'boundary_state', 'boundary_county'].forEach((id) => {
    setPaintSafe(map, id, 'line-color', '#7a8286');
    setPaintSafe(map, id, 'line-opacity', id.includes('country') ? 0.62 : 0.34);
  });
  ['place_country_1', 'place_country_2', 'place_state', 'place_continent'].forEach((id) => {
    setPaintSafe(map, id, 'text-color', '#8f9da4');
    setPaintSafe(map, id, 'text-halo-color', '#030405');
    setPaintSafe(map, id, 'text-halo-width', 1.2);
  });
  ['place_city_r6', 'place_city_r5', 'place_city_dot_r6', 'place_city_dot_r5'].forEach((id) => {
    setPaintSafe(map, id, 'text-color', '#77848a');
    setPaintSafe(map, id, 'text-halo-color', '#030405');
    setPaintSafe(map, id, 'text-halo-width', 1);
  });
}

function riskMatchExpression(risks: CountryRisk[], field: 'color' | 'opacity') {
  const pairs = risks.flatMap((risk): any[] => [
    risk.iso2,
    field === 'color' ? countryRiskColor(risk.level) : countryRiskOpacity(risk.level),
  ]);
  return ['match', ['get', 'ISO3166-1-Alpha-2'], ...pairs, field === 'color' ? 'rgba(0,0,0,0)' : 0] as any;
}

function updateCountryRiskPaint(map: MapLibreMap | null, risks: CountryRisk[]) {
  if (!map || !map.getStyle() || !map.getLayer('wm-weather-country-risk-fill')) return;
  try {
    map.setPaintProperty('wm-weather-country-risk-fill', 'fill-color', riskMatchExpression(risks, 'color'));
    map.setPaintProperty('wm-weather-country-risk-fill', 'fill-opacity', riskMatchExpression(risks, 'opacity'));
    map.setPaintProperty('wm-weather-country-risk-border', 'line-color', riskMatchExpression(risks, 'color'));
    map.setPaintProperty('wm-weather-country-risk-border', 'line-opacity', [
      'match',
      ['get', 'ISO3166-1-Alpha-2'],
      ...risks.flatMap((risk): any[] => [risk.iso2, risk.level === 'quiet' ? 0.1 : 0.34]),
      0,
    ]);
  } catch {
    // The style can be temporarily unavailable during a fallback style switch.
  }
}

function ensureCountryLayers(map: MapLibreMap, risks: CountryRisk[]) {
  if (!map.getStyle()) return;
  const beforeId = firstSymbolLayerId(map);
  addSourceSafe(map, WEATHER_COUNTRY_SOURCE_ID, LOCAL_WORLD_COUNTRIES_GEOJSON_URL);
  addLayerSafe(map, {
    id: 'wm-weather-country-risk-fill',
    type: 'fill',
    source: WEATHER_COUNTRY_SOURCE_ID,
    paint: {
      'fill-color': riskMatchExpression(risks, 'color'),
      'fill-opacity': riskMatchExpression(risks, 'opacity'),
    },
  }, beforeId);
  addLayerSafe(map, {
    id: 'wm-weather-country-risk-border',
    type: 'line',
    source: WEATHER_COUNTRY_SOURCE_ID,
    paint: {
      'line-color': riskMatchExpression(risks, 'color'),
      'line-opacity': 0.2,
      'line-width': ['interpolate', ['linear'], ['zoom'], 1.5, 0.55, 4, 0.95, 6, 1.35],
    },
  }, beforeId);
  addLayerSafe(map, {
    id: 'wm-weather-country-interactive',
    type: 'fill',
    source: WEATHER_COUNTRY_SOURCE_ID,
    paint: {
      'fill-color': '#ffffff',
      'fill-opacity': 0,
    },
  }, beforeId);
  addLayerSafe(map, {
    id: 'wm-weather-country-hover-fill',
    type: 'fill',
    source: WEATHER_COUNTRY_SOURCE_ID,
    paint: {
      'fill-color': '#73d8ff',
      'fill-opacity': 0.14,
    },
    filter: ['==', ['get', 'ISO3166-1-Alpha-2'], WEATHER_COUNTRY_NO_MATCH],
  }, beforeId);
  addLayerSafe(map, {
    id: 'wm-weather-country-hover-border',
    type: 'line',
    source: WEATHER_COUNTRY_SOURCE_ID,
    paint: {
      'line-color': '#73d8ff',
      'line-opacity': 0.72,
      'line-width': ['interpolate', ['linear'], ['zoom'], 1.5, 1.2, 4, 2.2, 6, 3],
    },
    filter: ['==', ['get', 'ISO3166-1-Alpha-2'], WEATHER_COUNTRY_NO_MATCH],
  }, beforeId);
  addLayerSafe(map, {
    id: 'wm-weather-country-selected-fill',
    type: 'fill',
    source: WEATHER_COUNTRY_SOURCE_ID,
    paint: {
      'fill-color': '#3b82f6',
      'fill-opacity': 0,
    },
    filter: ['==', ['get', 'ISO3166-1-Alpha-2'], WEATHER_COUNTRY_NO_MATCH],
  }, beforeId);
  addLayerSafe(map, {
    id: 'wm-weather-country-selected-border',
    type: 'line',
    source: WEATHER_COUNTRY_SOURCE_ID,
    paint: {
      'line-color': '#3b82f6',
      'line-opacity': 0,
      'line-width': ['interpolate', ['linear'], ['zoom'], 1.5, 1.45, 4, 2.6, 6, 3.4],
    },
    filter: ['==', ['get', 'ISO3166-1-Alpha-2'], WEATHER_COUNTRY_NO_MATCH],
  }, beforeId);
  updateCountryRiskPaint(map, risks);
}

function conflictPriority(point: ConflictMapPoint, selectedId?: string | null) {
  return (point.id === selectedId ? 1_000_000 : 0)
    + (point.deaths >= 50 ? 120_000 : 0)
    + Math.log10(point.deaths + 1) * 10_000
    + parseDateMs(point.occurredAt) / 1000 / 60 / 60 / 24 / 30;
}

function hexToRgba(hex: string, alpha = 255): [number, number, number, number] {
  const normalized = hex.replace('#', '').trim();
  const full = normalized.length === 3
    ? normalized.split('').map((char) => char + char).join('')
    : normalized;
  const value = Number.parseInt(full, 16);
  if (!Number.isFinite(value)) return [255, 255, 255, alpha];
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255, alpha];
}

function weatherColor(point: WeatherMapPoint, alpha = 220): [number, number, number, number] {
  if (point.temperatureTone === 'hot') return [255, 121, 72, alpha];
  if (point.temperatureTone === 'cool') return [72, 215, 190, alpha];
  if (point.marketTone === 'market') return [255, 166, 32, alpha];
  return [115, 216, 255, alpha];
}

function hashUnit(seed: string) {
  return (hashValue(seed) % 10000) / 10000;
}

function hashValue(seed: string) {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function seededRandom(seed: number) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6D2B79F5) >>> 0;
    let value = state;
    value = Math.imul(value ^ (value >>> 15), value | 1);
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61);
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296;
  };
}

function jitteredDensityPoint(
  id: string,
  lon: number,
  lat: number,
  radiusLon: number,
  radiusLat: number,
  tone: SignalDensityPoint['tone'],
  weight: number,
): SignalDensityPoint {
  const random = seededRandom(hashValue(id));
  const rawX = random() * 2 - 1;
  const rawY = random() * 2 - 1;
  const x = Math.sign(rawX) * Math.pow(Math.abs(rawX), 0.68);
  const y = Math.sign(rawY) * Math.pow(Math.abs(rawY), 0.72);
  const latScale = Math.max(0.34, Math.cos((lat * Math.PI) / 180));
  return {
    id,
    lon: Math.max(-179.8, Math.min(179.8, lon + x * radiusLon / latScale)),
    lat: Math.max(-84, Math.min(84, lat + y * radiusLat)),
    tone,
    weight,
  };
}

function buildSignalDensityPoints(cities: WeatherMapPoint[], conflicts: ConflictMapPoint[]): SignalDensityPoint[] {
  const points: SignalDensityPoint[] = [];

  cities.forEach((city) => {
    const quoted = Number(String(city.quoteCoverage || '0/0').split('/')[0]) || 0;
    const priceWeight = city.topBinPrice == null ? 0 : Math.min(1, Math.max(0, city.topBinPrice));
    const baseCount = IMPORTANT_CITY_IDS.has(city.id) ? 26 : 11;
    const signalCount = Math.min(38, baseCount + Math.round(quoted * 0.28) + Math.round(priceWeight * 7));
    const tone: SignalDensityPoint['tone'] = city.temperatureTone === 'cool'
      ? 'cool'
      : city.temperatureTone === 'hot' && priceWeight > 0.62
        ? 'warm'
        : 'cool';
    for (let index = 0; index < signalCount; index += 1) {
      points.push(jitteredDensityPoint(
        `city-density:${city.id}:${index}`,
        city.lon,
        city.lat,
        IMPORTANT_CITY_IDS.has(city.id) ? 2.9 : 1.55,
        IMPORTANT_CITY_IDS.has(city.id) ? 1.75 : 1.05,
        tone,
        0.55 + hashUnit(`${city.id}:w:${index}`) * 0.8,
      ));
    }
  });

  conflicts
    .slice()
    .sort((a, b) => conflictPriority(b) - conflictPriority(a))
    .slice(0, 760)
    .forEach((conflict) => {
      const severityCount = Math.min(8, 1 + Math.round(Math.log10(conflict.deaths + 2) * 2.2));
      const tone: SignalDensityPoint['tone'] = conflict.tone === 'onesided' ? 'risk' : conflict.tone === 'state' ? 'alert' : 'warm';
      for (let index = 0; index < severityCount; index += 1) {
        points.push(jitteredDensityPoint(
          `conflict-density:${conflict.id}:${index}`,
          conflict.lon,
          conflict.lat,
          1.35 + Math.log10(conflict.deaths + 2) * 0.35,
          0.85 + Math.log10(conflict.deaths + 2) * 0.24,
          tone,
          0.72 + Math.min(1.2, Math.log10(conflict.deaths + 2) * 0.24),
        ));
      }
    });

  return points.slice(0, 7800);
}

function paddedBounds(map: MapLibreMap | null, padRatio = 0.18): [number, number, number, number] | null {
  if (!map) return null;
  const bounds = map.getBounds();
  const west = bounds.getWest();
  const south = bounds.getSouth();
  const east = bounds.getEast();
  const north = bounds.getNorth();
  const padLon = Math.max(1, (east - west) * padRatio);
  const padLat = Math.max(1, (north - south) * padRatio);
  return [
    Math.max(-180, west - padLon),
    Math.max(-90, south - padLat),
    Math.min(180, east + padLon),
    Math.min(90, north + padLat),
  ];
}

function pointInBounds(point: { lon: number; lat: number }, bounds: [number, number, number, number] | null) {
  if (!bounds) return true;
  const [west, south, east, north] = bounds;
  return point.lon >= west && point.lon <= east && point.lat >= south && point.lat <= north;
}

function countryRiskLabelPoint(risk: CountryRisk): CountryNameLabel | null {
  if (!risk.points.length) return null;
  let lon = 0;
  let lat = 0;
  let weight = 0;
  risk.points.forEach((point) => {
    const pointWeight = Math.max(1, Math.log10(point.deaths + 2));
    lon += point.lon * pointWeight;
    lat += point.lat * pointWeight;
    weight += pointWeight;
  });
  if (weight <= 0) return null;
  return {
    id: risk.iso2,
    name: compactText(risk.name, 18).toUpperCase(),
    lon: lon / weight,
    lat: lat / weight,
    kind: 'risk',
    level: risk.level,
    score: risk.score,
    importance: Math.max(3, Math.min(8, risk.score / 12)),
    minZoom: risk.level === 'critical' ? 0.8 : risk.level === 'elevated' ? 1.8 : 2.8,
  };
}

function buildCountryNameLabels(risks: CountryRisk[], zoom: number, bounds: [number, number, number, number] | null): CountryNameLabel[] {
  const majorBudget = zoom < 1.4 ? 9 : zoom < 2.4 ? 13 : MAJOR_COUNTRY_LABELS.length;
  const riskBudget = zoom < 1.4 ? 4 : zoom < 2.4 ? 8 : 16;
  const labels = new Map<string, CountryNameLabel>();

  MAJOR_COUNTRY_LABELS
    .filter((label) => zoom >= label.minZoom && pointInBounds(label, bounds))
    .sort((a, b) => b.importance - a.importance)
    .slice(0, majorBudget)
    .forEach((label) => labels.set(label.id, label));

  risks
    .map(countryRiskLabelPoint)
    .filter((label): label is CountryNameLabel => Boolean(label))
    .filter((label) => zoom >= label.minZoom && pointInBounds(label, bounds))
    .sort((a, b) => (b.score || 0) - (a.score || 0))
    .slice(0, riskBudget)
    .forEach((label) => {
      const existing = labels.get(label.id);
      if (!existing || label.importance >= existing.importance) labels.set(label.id, label);
    });

  return Array.from(labels.values())
    .sort((a, b) => a.kind.localeCompare(b.kind) || b.importance - a.importance);
}

function pickCityLabels(points: WeatherMapPoint[], zoom: number, selectedCityId?: string | null) {
  if (zoom < 2.2 && !selectedCityId) {
    return points
      .filter((point) => IMPORTANT_CITY_IDS.has(point.id))
      .slice(0, 8);
  }
  const budget = zoom < 3.2 ? 12 : zoom < 5.2 ? 24 : 48;
  return points
    .filter((point) => shouldShowLabel(point, selectedCityId))
    .sort((a, b) => (
      (b.id === selectedCityId ? 1 : 0) - (a.id === selectedCityId ? 1 : 0)
      || (IMPORTANT_CITY_IDS.has(b.id) ? 1 : 0) - (IMPORTANT_CITY_IDS.has(a.id) ? 1 : 0)
      || (b.topBinPrice ?? -1) - (a.topBinPrice ?? -1)
    ))
    .slice(0, budget);
}

function visibleConflictSingles(points: ConflictMapPoint[], zoom: number, bounds: [number, number, number, number] | null, selectedId?: string | null) {
  if (zoom < 3) {
    return selectedId ? points.filter((point) => point.id === selectedId) : [];
  }
  const budget = zoom < 4.5 ? 180 : zoom < 6.5 ? 420 : 900;
  return points
    .filter((point) => pointInBounds(point, bounds))
    .sort((a, b) => conflictPriority(b, selectedId) - conflictPriority(a, selectedId))
    .slice(0, budget);
}

function clusterConflictPoints(points: ConflictMapPoint[], zoom: number, bounds: [number, number, number, number] | null): ConflictClusterPoint[] {
  if (zoom >= 5 || points.length === 0) return [];
  const visible = points.filter((point) => pointInBounds(point, bounds));
  const cellSize = zoom < 2 ? 10 : zoom < 3 ? 6 : 3.2;
  const buckets = new Map<string, ConflictMapPoint[]>();
  for (const point of visible) {
    const key = `${Math.floor(point.lon / cellSize)}:${Math.floor(point.lat / cellSize)}`;
    const bucket = buckets.get(key);
    if (bucket) bucket.push(point);
    else buckets.set(key, [point]);
  }

  const clusters: ConflictClusterPoint[] = [];
  for (const bucket of buckets.values()) {
    if (bucket.length < 3) continue;
    let lon = 0;
    let lat = 0;
    let deaths = 0;
    let maxDeaths = -1;
    let sample = bucket[0]!;
    let west = 180;
    let south = 90;
    let east = -180;
    let north = -90;
    const toneCounts: Record<ConflictTone, number> = { state: 0, nonstate: 0, onesided: 0, unknown: 0 };
    for (const point of bucket) {
      lon += point.lon;
      lat += point.lat;
      deaths += point.deaths;
      toneCounts[point.tone] += 1;
      if (point.deaths > maxDeaths) {
        maxDeaths = point.deaths;
        sample = point;
      }
      west = Math.min(west, point.lon);
      south = Math.min(south, point.lat);
      east = Math.max(east, point.lon);
      north = Math.max(north, point.lat);
    }
    const dominantTone = (Object.entries(toneCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || 'unknown') as ConflictTone;
    const color = dominantTone === 'state'
      ? '#ff4d4d'
      : dominantTone === 'nonstate'
        ? '#ff9f1c'
        : dominantTone === 'onesided'
          ? '#ffd400'
          : '#ff735d';
    clusters.push({
      id: `ucdp-cluster-${Math.round(lon / bucket.length * 100)}-${Math.round(lat / bucket.length * 100)}-${bucket.length}`,
      kind: 'conflict-cluster',
      lon: lon / bucket.length,
      lat: lat / bucket.length,
      count: bucket.length,
      deaths,
      maxDeaths,
      tone: dominantTone,
      color,
      bounds: [west, south, east, north],
      sample,
    });
  }
  return clusters;
}

function buildWeatherDeckLayers({
  cities,
  conflicts,
  countryRisks,
  densityPoints,
  airContextRoutes,
  airRoutes,
  airHubs,
  airFlights,
  liveAircraft,
  animationTime,
  airLensMode,
  airRiskSource,
  selectedCityId,
  selectedConflictId,
  zoom,
  bounds,
  showLabels,
}: {
  cities: WeatherMapPoint[];
  conflicts: ConflictMapPoint[];
  countryRisks: CountryRisk[];
  densityPoints: SignalDensityPoint[];
  airContextRoutes: AirRoutePath[];
  airRoutes: AirRoutePath[];
  airHubs: AirHubPoint[];
  airFlights: AirFlightPoint[];
  liveAircraft: LiveAircraftPoint[];
  animationTime: number;
  airLensMode: AirLensMode;
  airRiskSource: AirRiskSource;
  selectedCityId?: string | null;
  selectedConflictId?: string | null;
  zoom: number;
  bounds: [number, number, number, number] | null;
  showLabels: boolean;
}): LayersList {
  const layers: (Layer | null)[] = [];
  const visibleDensityPoints = densityPoints.filter((point) => pointInBounds(point, bounds));
  const cityLabels = showLabels ? pickCityLabels(cities, zoom, selectedCityId) : [];
  const conflictClusters = clusterConflictPoints(conflicts, zoom, bounds);
  const countryLabels = buildCountryNameLabels(countryRisks, zoom, bounds);
  const clusterMemberIds = zoom < 5
    ? new Set(conflictClusters.flatMap((cluster) => cluster.count >= 3 ? [cluster.sample.id] : []))
    : new Set<string>();
  const conflictSingles = visibleConflictSingles(conflicts, zoom, bounds, selectedConflictId)
    .filter((point) => !clusterMemberIds.has(point.id) || point.id === selectedConflictId);
  const airMotionPoints = buildAirMotionPoints(airRoutes, animationTime, airLensMode, airRiskSource);
  const conflictMotionPoints = airMotionPoints.filter((point) => point.source === 'conflict');
  const weatherMotionPoints = airMotionPoints.filter((point) => point.source === 'weather');
  const corridorMotionPoints = airMotionPoints.filter((point) => point.source === 'corridor');
  const criticalConflictMotionPoints = conflictMotionPoints.filter((point) => point.intensity >= 0.72);

  const routeColor = (route: AirRoutePath, alpha: number): [number, number, number, number] => {
    if (route.layer === 'trunk') return [94, 238, 255, alpha];
    if (route.layer === 'international') return [68, 176, 255, Math.max(24, Math.round(alpha * 0.92))];
    return [98, 126, 156, Math.max(18, Math.round(alpha * 0.68))];
  };

  const routeWidth = (route: AirRoutePath, base: number) => {
    const layerBoost = route.layer === 'trunk' ? 0.5 : route.layer === 'international' ? 0.18 : -0.08;
    return Math.max(0.35, Math.min(2.8, base + layerBoost + route.trafficScore / 82));
  };

  const routeAlpha = (route: AirRoutePath, alpha: number) => {
    const seed = hashUnit(`air-alpha:${route.id}`);
    const pulse = 0.5 + 0.5 * Math.sin(animationTime * 2.8 + seed * Math.PI * 4);
    const source = routeMotionSource(route, airLensMode, airRiskSource);
    if (source === 'conflict') return Math.round(alpha * (0.9 + pulse * (0.16 + route.conflictIntensity * 0.34)));
    if (source === 'weather') return Math.round(alpha * (0.84 + pulse * (0.12 + route.weatherIntensity * 0.22)));
    if (source === 'corridor') return Math.round(alpha * (0.92 + pulse * 0.1));
    return alpha;
  };

  const routeAnimatedWidth = (route: AirRoutePath, base: number) => {
    const seed = hashUnit(`air-width:${route.id}`);
    const pulse = 0.5 + 0.5 * Math.sin(animationTime * 2.6 + seed * Math.PI * 3);
    const source = routeMotionSource(route, airLensMode, airRiskSource);
    if (source === 'conflict') return routeWidth(route, base + pulse * (0.08 + route.conflictIntensity * 0.14));
    if (source === 'weather') return routeWidth(route, base + pulse * (0.05 + route.weatherIntensity * 0.12));
    if (source === 'corridor') return routeWidth(route, base + pulse * 0.04);
    return routeWidth(route, base);
  };

  if (airContextRoutes.length) {
    layers.push(new PathLayer<AirRoutePath>({
      id: 'air-route-corridors-context',
      data: airContextRoutes,
      getPath: (route) => route.path,
      getColor: (route) => routeColor(route, 20),
      getWidth: (route) => routeWidth(route, 0.12),
      widthMinPixels: 0.3,
      widthMaxPixels: 1.5,
      jointRounded: true,
      capRounded: true,
      pickable: false,
    }));
  }

  if (airRoutes.length) {
    layers.push(new PathLayer<AirRoutePath>({
      id: 'air-route-corridors-underlay',
      data: airRoutes,
      getPath: (route) => route.path,
      getColor: (route) => routeColor(route, routeAlpha(route, 42)),
      getWidth: (route) => routeAnimatedWidth(route, 0.22),
      widthMinPixels: 0.45,
      widthMaxPixels: 2.4,
      jointRounded: true,
      capRounded: true,
      pickable: true,
      autoHighlight: true,
      highlightColor: [117, 247, 255, 112],
    }));
    layers.push(new PathLayer<AirRoutePath>({
      id: 'air-route-corridors-core',
      data: airRoutes,
      getPath: (route) => route.path,
      getColor: (route) => routeColor(route, routeAlpha(route, 128)),
      getWidth: (route) => routeAnimatedWidth(route, 0.26),
      widthMinPixels: 0.55,
      widthMaxPixels: 2.4,
      jointRounded: true,
      capRounded: true,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 245, 166, 140],
    }));
  }

  if (corridorMotionPoints.length) {
    layers.push(new ScatterplotLayer<AirMotionPoint>({
      id: 'air-route-corridor-runners',
      data: corridorMotionPoints,
      getPosition: (point) => [point.lon, point.lat],
      getRadius: (point) => 12000 + point.emphasis * 9000,
      getFillColor: (point) => [186, 233, 255, Math.round(126 + point.pulse * 44)],
      getLineColor: [8, 18, 30, 180],
      getLineWidth: 1,
      radiusMinPixels: 1.9,
      radiusMaxPixels: 4.2,
      lineWidthMinPixels: 1,
      pickable: false,
      stroked: true,
    }));
  }

  if (weatherMotionPoints.length) {
    layers.push(new ScatterplotLayer<AirMotionPoint>({
      id: 'air-route-weather-flow',
      data: weatherMotionPoints,
      getPosition: (point) => [point.lon, point.lat],
      getRadius: (point) => 11000 + point.emphasis * 7000 + point.intensity * 20000 + point.pulse * (2500 + point.intensity * 3500),
      getFillColor: (point) => [72, 244, 211, Math.round(88 + point.intensity * 48 + point.pulse * 58)],
      getLineColor: [7, 24, 30, 180],
      getLineWidth: 1,
      radiusMinPixels: 1.8,
      radiusMaxPixels: 6.2,
      lineWidthMinPixels: 1,
      pickable: false,
      stroked: true,
    }));
  }

  if (criticalConflictMotionPoints.length) {
    layers.push(new ScatterplotLayer<AirMotionPoint>({
      id: 'air-route-conflict-halo',
      data: criticalConflictMotionPoints,
      getPosition: (point) => [point.lon, point.lat],
      getRadius: (point) => 26000 + point.emphasis * 12000 + point.intensity * 52000 + point.pulse * (12000 + point.intensity * 18000),
      getFillColor: (point) => [255, 84, 68, Math.round(16 + point.intensity * 34 + point.pulse * 34)],
      radiusMinPixels: 5,
      radiusMaxPixels: 16,
      pickable: false,
      stroked: false,
    }));
  }

  if (conflictMotionPoints.length) {
    layers.push(new ScatterplotLayer<AirMotionPoint>({
      id: 'air-route-conflict-core',
      data: conflictMotionPoints,
      getPosition: (point) => [point.lon, point.lat],
      getRadius: (point) => point.intensity >= 0.72
        ? 11000 + point.emphasis * 7000 + point.intensity * 18000 + point.pulse * 5000
        : 7000 + point.emphasis * 4200 + point.intensity * 9000 + point.pulse * 2200,
      getFillColor: (point) => point.intensity >= 0.72
        ? [255, 172, 92, Math.round(118 + point.intensity * 42 + point.pulse * 68)]
        : [255, 132, 80, Math.round(90 + point.intensity * 46 + point.pulse * 34)],
      getLineColor: [52, 6, 6, 200],
      getLineWidth: 1,
      radiusMinPixels: 1.8,
      radiusMaxPixels: 8.2,
      lineWidthMinPixels: 1,
      pickable: false,
      stroked: true,
    }));
  }

  if (airFlights.length) {
    layers.push(new ScatterplotLayer<AirFlightPoint>({
      id: 'air-route-moving-aircraft',
      data: airFlights,
      getPosition: (flight) => pointAlongPath(flight.path, flight.progress),
      getRadius: (flight) => flight.status === 'watch' || flight.riskScore >= 55 ? 25000 : 18000,
      getFillColor: (flight) => flight.status === 'watch' || flight.riskScore >= 55
        ? [255, 222, 92, 228]
        : [92, 241, 255, 220],
      getLineColor: [6, 13, 20, 230],
      getLineWidth: 1,
      radiusMinPixels: 2.5,
      radiusMaxPixels: 5.5,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 95],
    }));
  }

  if (liveAircraft.length) {
    layers.push(new ScatterplotLayer<LiveAircraftPoint>({
      id: 'opensky-live-aircraft',
      data: liveAircraft,
      getPosition: (flight) => [flight.lon, flight.lat],
      getRadius: (flight) => {
        const speedBoost = Math.min(18000, Math.max(0, (flight.velocity || 0) * 52));
        return (flight.status === 'watch' || flight.riskScore >= 34 ? 24000 : 17000) + speedBoost;
      },
      getFillColor: (flight) => flight.status === 'watch' || flight.riskScore >= 34
        ? [255, 218, 84, 235]
        : [72, 244, 255, 226],
      getLineColor: (flight) => flight.status === 'watch' || flight.riskScore >= 34
        ? [75, 28, 4, 235]
        : [5, 22, 31, 230],
      getLineWidth: 1,
      radiusMinPixels: 2.4,
      radiusMaxPixels: 6.4,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 255, 115],
      stroked: true,
    }));
  }

  if (airHubs.length) {
    layers.push(new ScatterplotLayer<AirHubPoint>({
      id: 'air-route-hub-points',
      data: airHubs,
      getPosition: (hub) => [hub.lon, hub.lat],
      getRadius: (hub) => Math.max(26000, Math.min(76000, 18000 + hub.routeCount * 34)),
      getFillColor: (hub) => hub.status === 'watch' ? [255, 177, 76, 134] : [24, 211, 238, 126],
      getLineColor: (hub) => hub.status === 'watch' ? [255, 220, 130, 220] : [87, 235, 255, 225],
      getLineWidth: 1.5,
      radiusMinPixels: 4,
      radiusMaxPixels: 15,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 210, 94],
    }));
    layers.push(new TextLayer<AirHubPoint>({
      id: 'air-route-hub-labels',
      data: airHubs.slice(0, zoom < 2.2 ? 8 : 12),
      getPosition: (hub) => [hub.lon, hub.lat],
      getText: (hub) => hub.code,
      getPixelOffset: [9, 10],
      getSize: 9,
      getColor: [174, 233, 241, 186],
      getTextAnchor: 'start',
      getAlignmentBaseline: 'center',
      fontFamily: 'monospace',
      fontWeight: 900,
      outlineWidth: 3,
      outlineColor: [0, 0, 0, 220],
      pickable: false,
    }));
  }

  if (visibleDensityPoints.length) {
    layers.push(new ScatterplotLayer<SignalDensityPoint>({
      id: 'signal-density-speckles',
      data: visibleDensityPoints,
      getPosition: (point) => [point.lon, point.lat],
      getRadius: (point) => 2600 + point.weight * 4200,
      getFillColor: (point) => {
        if (point.tone === 'cool') return [41, 183, 232, 82];
        if (point.tone === 'risk') return [235, 211, 58, 62];
        if (point.tone === 'alert') return [255, 91, 76, 56];
        return [255, 155, 42, 58];
      },
      radiusMinPixels: 0.9,
      radiusMaxPixels: zoom < 3 ? 2.2 : 3.4,
      pickable: false,
      stroked: false,
    }));
  }

  if (countryLabels.length) {
    layers.push(new TextLayer<CountryNameLabel>({
      id: 'country-name-labels',
      data: countryLabels,
      getPosition: (label) => [label.lon, label.lat],
      getText: (label) => label.name,
      getSize: (label) => label.kind === 'major'
        ? Math.min(15.5, 8.8 + label.importance * 0.46)
        : Math.min(11.5, 7.8 + Math.log10((label.score || 1) + 1) * 1.8),
      getColor: (label) => {
        if (label.kind === 'risk') {
          if (label.level === 'critical') return [170, 158, 150, 132];
          if (label.level === 'elevated') return [160, 154, 145, 118];
          return [148, 148, 138, 105];
        }
        return [164, 174, 180, 118];
      },
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
      fontFamily: 'Arial, sans-serif',
      fontWeight: 800,
      characterSet: 'auto',
      outlineWidth: 2,
      outlineColor: [0, 0, 0, 165],
      pickable: false,
    }));
  }

  if (cities.length) {
    layers.push(new ScatterplotLayer<WeatherMapPoint>({
      id: 'weather-city-points',
      data: cities,
      getPosition: (point) => [point.lon, point.lat],
      getRadius: (point) => point.id === selectedCityId ? 42000 : IMPORTANT_CITY_IDS.has(point.id) ? 30000 : 19000,
      getFillColor: (point) => weatherColor(point, point.id === selectedCityId ? 230 : 175),
      getLineColor: [255, 232, 172, 150],
      getLineWidth: (point) => point.id === selectedCityId ? 2 : 1,
      lineWidthMinPixels: 1,
      radiusMinPixels: 3,
      radiusMaxPixels: 11,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 245, 190, 120],
    }));
  }

  if (cityLabels.length) {
    layers.push(new TextLayer<WeatherMapPoint>({
      id: 'weather-city-labels',
      data: cityLabels,
      getPosition: (point) => [point.lon, point.lat],
      getText: (point) => `${point.city}\n${point.sublabel}`,
      getPixelOffset: (point) => [point.labelDx + 8, point.labelDy - 2],
      getSize: (point) => point.id === selectedCityId ? 11.5 : 8.8,
      getColor: (point) => point.temperatureTone === 'hot'
        ? [214, 135, 86, 182]
        : point.temperatureTone === 'cool'
          ? [104, 196, 190, 184]
          : [118, 178, 208, 174],
      getTextAnchor: 'start',
      getAlignmentBaseline: 'center',
      fontFamily: 'monospace',
      fontWeight: 900,
      outlineWidth: 3,
      outlineColor: [0, 0, 0, 210],
      pickable: true,
    }));
  }

  if (conflictClusters.length) {
    layers.push(new ScatterplotLayer<ConflictClusterPoint>({
      id: 'ucdp-conflict-clusters',
      data: conflictClusters,
      getPosition: (cluster) => [cluster.lon, cluster.lat],
      getRadius: (cluster) => Math.max(39000, Math.log2(cluster.count + 1) * 32000),
      getFillColor: (cluster) => hexToRgba(cluster.color, 74),
      getLineColor: (cluster) => hexToRgba(cluster.color, 132),
      getLineWidth: 1,
      radiusMinPixels: 4.5,
      radiusMaxPixels: 18,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 180, 80],
    }));
  }

  if (conflictClusters.length && zoom < 2.75) {
    layers.push(new TextLayer<ConflictClusterPoint>({
      id: 'ucdp-conflict-cluster-counts',
      data: conflictClusters,
      getPosition: (cluster) => [cluster.lon, cluster.lat],
      getText: (cluster) => String(cluster.count),
      getSize: 8.5,
      getColor: [224, 210, 186, 162],
      getTextAnchor: 'middle',
      getAlignmentBaseline: 'center',
      fontFamily: 'monospace',
      fontWeight: 900,
      outlineWidth: 2,
      outlineColor: [0, 0, 0, 210],
      pickable: false,
    }));
  }

  if (conflictSingles.length) {
    layers.push(new ScatterplotLayer<ConflictMapPoint>({
      id: 'ucdp-conflict-events',
      data: conflictSingles,
      getPosition: (point) => [point.lon, point.lat],
      getRadius: (point) => Math.max(9000, Math.sqrt(point.deaths + 1) * 6200),
      getFillColor: (point) => hexToRgba(point.color, point.id === selectedConflictId ? 230 : 150),
      getLineColor: (point) => point.id === selectedConflictId ? [255, 246, 210, 230] : hexToRgba(point.color, 180),
      getLineWidth: (point) => point.id === selectedConflictId ? 2 : 1,
      radiusMinPixels: 3,
      radiusMaxPixels: 12,
      lineWidthMinPixels: 1,
      pickable: true,
      autoHighlight: true,
      highlightColor: [255, 255, 180, 90],
    }));
  }

  return layers.filter(Boolean) as LayersList;
}

function countryFeatureMeta(props?: Record<string, unknown>) {
  const iso2 = String(props?.['ISO3166-1-Alpha-2'] || props?.iso2 || '').trim();
  const name = String(props?.name || props?.NAME || iso2 || 'Country').trim();
  return { iso2, name };
}

function setupCountryInteractions(
  map: MapLibreMap,
  riskByIsoRef: { current: Map<string, CountryRisk> },
  onHover: (hover: CountryHoverState | null) => void,
  onSelectRef: { current: (risk: CountryRisk) => void },
) {
  if ((map as any).__weatherCountryInteractionsSetup) return;
  (map as any).__weatherCountryInteractionsSetup = true;
  let hoveredIso2 = '';
  let hoverRaf = 0;
  let pendingHover: CountryHoverState | null = null;

  const emitHover = (hover: CountryHoverState | null) => {
    pendingHover = hover;
    if (hoverRaf) return;
    hoverRaf = window.requestAnimationFrame(() => {
      hoverRaf = 0;
      onHover(pendingHover);
    });
  };

  const clearHover = () => {
    hoveredIso2 = '';
    map.getCanvas().style.cursor = '';
    emitHover(null);
    const noMatch: any = ['==', ['get', 'ISO3166-1-Alpha-2'], WEATHER_COUNTRY_NO_MATCH];
    if (map.getLayer('wm-weather-country-hover-fill')) map.setFilter('wm-weather-country-hover-fill', noMatch);
    if (map.getLayer('wm-weather-country-hover-border')) map.setFilter('wm-weather-country-hover-border', noMatch);
  };

  map.on('mousemove', (event) => {
    if (!map.getLayer('wm-weather-country-interactive')) return;
    const features = map.queryRenderedFeatures(event.point, { layers: ['wm-weather-country-interactive'] });
    const { iso2, name } = countryFeatureMeta(features[0]?.properties as Record<string, unknown> | undefined);
    if (!iso2) {
      if (hoveredIso2) clearHover();
      return;
    }
    if (hoveredIso2 !== iso2) {
      hoveredIso2 = iso2;
      const filter: any = ['==', ['get', 'ISO3166-1-Alpha-2'], iso2];
      if (map.getLayer('wm-weather-country-hover-fill')) map.setFilter('wm-weather-country-hover-fill', filter);
      if (map.getLayer('wm-weather-country-hover-border')) map.setFilter('wm-weather-country-hover-border', filter);
      map.getCanvas().style.cursor = 'pointer';
    }
    const risk = riskByIsoRef.current.get(iso2) || emptyCountryRisk(iso2, name);
    emitHover({
      iso2,
      name,
      screenX: event.point.x,
      screenY: event.point.y,
      risk,
    });
  });

  map.on('mouseout', clearHover);
  map.on('click', (event) => {
    if (!map.getLayer('wm-weather-country-interactive')) return;
    const features = map.queryRenderedFeatures(event.point, { layers: ['wm-weather-country-interactive'] });
    const { iso2, name } = countryFeatureMeta(features[0]?.properties as Record<string, unknown> | undefined);
    if (!iso2) return;
    onSelectRef.current(riskByIsoRef.current.get(iso2) || emptyCountryRisk(iso2, name));
    map.easeTo({
      center: event.lngLat,
      zoom: Math.max(map.getZoom(), 2.25),
      duration: 420,
      essential: true,
    });
  });
}

function AirMapControls({
  lens,
  focus,
  riskSource,
  routeCount,
  totalRouteCount,
  hubCount,
  flightCount,
  riskCounts,
  onLensChange,
  onFocusChange,
  onRiskSourceChange,
}: {
  lens: AirLensMode;
  focus: AirFocusRegion;
  riskSource: AirRiskSource;
  routeCount: number;
  totalRouteCount: number;
  hubCount: number;
  flightCount: number;
  riskCounts: Record<AirRiskSource, number>;
  onLensChange: (lens: AirLensMode) => void;
  onFocusChange: (focus: AirFocusRegion) => void;
  onRiskSourceChange: (source: AirRiskSource) => void;
}) {
  return (
    <div className="wm-air-map-controls">
      <div className="wm-air-map-head">
        <div>
          <span>Air Lens</span>
          <strong>{airFocusLabel(focus)} / {lens.toUpperCase()}</strong>
          {lens === 'watch' ? <em>{airRiskSourceLabel(riskSource)}</em> : null}
        </div>
        <div className="wm-air-map-counts" aria-hidden="true">
          <b>{routeCount}</b>
          <small>{totalRouteCount}</small>
        </div>
      </div>
      <div className="wm-air-map-stats" aria-hidden="true">
        <span><i className="routes" />{routeCount} corridors</span>
        <span><i className="hubs" />{hubCount} hubs</span>
        <span><i className="flights" />{flightCount} flights</span>
      </div>
      <div className="wm-air-map-segments" role="tablist" aria-label="Air route layer">
        {AIR_LENS_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={option.id === lens ? 'active' : ''}
            aria-pressed={option.id === lens}
            onClick={() => onLensChange(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="wm-air-map-focus-strip" role="tablist" aria-label="Air route focus region">
        {AIR_FOCUS_PRESETS.map((preset) => (
          <button
            key={preset.id}
            type="button"
            className={preset.id === focus ? 'active' : ''}
            aria-pressed={preset.id === focus}
            onClick={() => onFocusChange(preset.id)}
          >
            {preset.label}
          </button>
        ))}
      </div>
      {lens === 'watch' ? (
        <div className="wm-air-map-risk-strip" role="tablist" aria-label="Watch risk source">
          {AIR_RISK_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              className={option.id === riskSource ? 'active' : ''}
              aria-pressed={option.id === riskSource}
              onClick={() => onRiskSourceChange(option.id)}
            >
              <span>{option.label}</span>
              <b>{riskCounts[option.id] || 0}</b>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function CountryHoverTooltip({ hover }: { hover: CountryHoverState | null }) {
  if (!hover) return null;
  return (
    <div
      className={`wm-map-country-tooltip level-${hover.risk.level}`}
      style={{ transform: `translate(${Math.round(hover.screenX + 14)}px, ${Math.round(hover.screenY + 14)}px)` }}
    >
      <strong>{hover.name}</strong>
      <span>{hover.risk.score}/100 · {hover.risk.eventCount} events · {hover.risk.deaths} deaths</span>
    </div>
  );
}

function DeckMapTooltip({ tooltip }: { tooltip: DeckTooltipState }) {
  if (!tooltip) return null;
  if (tooltip.kind === 'air-route' && tooltip.airRoute) {
    const route = tooltip.airRoute;
    return (
      <div className={`wm-map-country-tooltip wm-map-deck-tooltip air ${route.status}`} style={{ transform: `translate(${Math.round(tooltip.x + 14)}px, ${Math.round(tooltip.y + 14)}px)` }}>
        <strong>{route.fromCode} &gt; {route.toCode}</strong>
        <span>{airRouteLayerLabel(route.layer)} · {route.riskSources.map((source) => airRiskSourceLabel(source)).join(' / ') || 'BASELINE'} · {route.corridor}</span>
        {route.riskReason ? <small>{compactText(route.riskReason, 72)}</small> : null}
      </div>
    );
  }
  if (tooltip.kind === 'air-hub' && tooltip.airHub) {
    const hub = tooltip.airHub;
    return (
      <div className={`wm-map-country-tooltip wm-map-deck-tooltip air ${hub.status}`} style={{ transform: `translate(${Math.round(tooltip.x + 14)}px, ${Math.round(tooltip.y + 14)}px)` }}>
        <strong>{hub.code} · {hub.name}</strong>
        <span>{hub.city || hub.country} · {Math.round(hub.routeCount)} route edges</span>
      </div>
    );
  }
  if (tooltip.kind === 'air-flight' && tooltip.airFlight) {
    const flight = tooltip.airFlight;
    return (
      <div className={`wm-map-country-tooltip wm-map-deck-tooltip air ${flight.status}`} style={{ transform: `translate(${Math.round(tooltip.x + 14)}px, ${Math.round(tooltip.y + 14)}px)` }}>
        <strong>{flight.fromCode} &gt; {flight.toCode}</strong>
        <span>seeded aircraft flow · {Math.round(flight.progress * 100)}% route progress</span>
      </div>
    );
  }
  if (tooltip.kind === 'live-aircraft' && tooltip.liveAircraft) {
    const flight = tooltip.liveAircraft;
    return (
      <div className={`wm-map-country-tooltip wm-map-deck-tooltip air ${flight.status}`} style={{ transform: `translate(${Math.round(tooltip.x + 14)}px, ${Math.round(tooltip.y + 14)}px)` }}>
        <strong>{flight.callsign}</strong>
        <span>OpenSky · {flight.regionLabel} · {flight.originCountry}</span>
        <small>{Math.round(flight.velocity || 0)} m/s · {Math.round(flight.altitude || 0)} m · risk {Math.round(flight.riskScore)}</small>
      </div>
    );
  }
  if (tooltip.kind === 'city' && tooltip.city) {
    const city = tooltip.city;
    return (
      <div className={`wm-map-country-tooltip wm-map-deck-tooltip city ${city.temperatureTone}`} style={{ transform: `translate(${Math.round(tooltip.x + 14)}px, ${Math.round(tooltip.y + 14)}px)` }}>
        <strong>{city.city}</strong>
        <span>{city.condition} · {city.sublabel}</span>
      </div>
    );
  }
  if (tooltip.kind === 'cluster' && tooltip.cluster) {
    const cluster = tooltip.cluster;
    return (
      <div className={`wm-map-country-tooltip wm-map-deck-tooltip cluster tone-${cluster.tone}`} style={{ transform: `translate(${Math.round(tooltip.x + 14)}px, ${Math.round(tooltip.y + 14)}px)` }}>
        <strong>{cluster.count} UCDP events</strong>
        <span>{cluster.deaths} deaths · click to zoom</span>
      </div>
    );
  }
  if (tooltip.kind === 'conflict' && tooltip.conflict) {
    const point = tooltip.conflict;
    return (
      <div className={`wm-map-country-tooltip wm-map-deck-tooltip conflict tone-${point.tone}`} style={{ transform: `translate(${Math.round(tooltip.x + 14)}px, ${Math.round(tooltip.y + 14)}px)` }}>
        <strong>{point.country}</strong>
        <span>{point.violenceLabel} · {point.deaths} deaths</span>
      </div>
    );
  }
  return null;
}

function RiskBar({ label, value, max, tone }: { label: string; value: number; max: number; tone: string }) {
  const width = max > 0 ? Math.max(4, Math.round((value / max) * 100)) : 0;
  return (
    <div className={`wm-map-risk-bar ${tone}`}>
      <span>{label}</span>
      <i><b style={{ width: `${width}%` }} /></i>
      <strong>{value}</strong>
    </div>
  );
}

function CountryRiskInspector({ risk, onClose }: { risk: CountryRisk; onClose: () => void }) {
  const max = Math.max(1, risk.stateCount, risk.nonStateCount, risk.oneSidedCount);
  return (
    <aside className={`wm-map-risk-inspector level-${risk.level}`}>
      <button type="button" className="wm-map-risk-close" onClick={onClose} aria-label="Close country risk detail">×</button>
      <div className="wm-map-risk-head">
        <span>{risk.iso2}</span>
        <strong>{risk.name}</strong>
        <em>Updated {formatDateLabel(risk.latestAt)}</em>
      </div>
      <div className="wm-map-risk-score">
        <strong>{risk.score}/100</strong>
        <span>{risk.level === 'quiet' ? 'stable' : risk.level}</span>
      </div>
      <div className="wm-map-risk-bars">
        <RiskBar label="State" value={risk.stateCount} max={max} tone="state" />
        <RiskBar label="Non-state" value={risk.nonStateCount} max={max} tone="nonstate" />
        <RiskBar label="One-sided" value={risk.oneSidedCount} max={max} tone="onesided" />
      </div>
      <div className="wm-map-risk-stats">
        <span><b>{risk.eventCount}</b><em>events</em></span>
        <span><b>{risk.deaths}</b><em>deaths</em></span>
        <span><b>{risk.points.length}</b><em>rows</em></span>
      </div>
      {risk.topActors.length ? (
        <div className="wm-map-risk-list">
          <span>Actors</span>
          {risk.topActors.map((actor) => <strong key={actor}>{compactText(actor, 42)}</strong>)}
        </div>
      ) : null}
      {risk.topLocations.length ? (
        <div className="wm-map-risk-list">
          <span>Locations</span>
          {risk.topLocations.map((location) => <strong key={location}>{compactText(location, 42)}</strong>)}
        </div>
      ) : null}
    </aside>
  );
}

function ConflictInspector({ point, onClose }: { point: ConflictMapPoint; onClose: () => void }) {
  return (
    <aside className={`wm-map-risk-inspector wm-map-conflict-inspector tone-${point.tone}`}>
      <button type="button" className="wm-map-risk-close" onClick={onClose} aria-label="Close conflict detail">×</button>
      <div className="wm-map-risk-head">
        <span>{point.violenceLabel}</span>
        <strong>{point.country}</strong>
        <em>{formatDateLabel(point.occurredAt)} · {point.source || 'UCDP'}</em>
      </div>
      <div className="wm-map-risk-score">
        <strong>{point.deaths}</strong>
        <span>deaths</span>
      </div>
      <div className="wm-map-conflict-body">
        <span>Location</span>
        <strong>{point.location || point.country}</strong>
        <span>Actors</span>
        <strong>{point.actors || '--'}</strong>
        {point.deathsLow != null || point.deathsHigh != null ? (
          <>
            <span>Range</span>
            <strong>{point.deathsLow ?? '--'} - {point.deathsHigh ?? '--'}</strong>
          </>
        ) : null}
      </div>
      {point.sourceUrl ? <a className="wm-map-risk-link" href={point.sourceUrl} target="_blank" rel="noreferrer">OPEN SOURCE</a> : null}
    </aside>
  );
}

export function WeatherDeckMap({
  items,
  ucdpEvents = [],
  transportPayload = null,
  showAirRoutes = false,
  selectedCityId = null,
  onSelectCity,
  height = 320,
  interactive = true,
  showLabels = true,
}: WeatherDeckMapProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const mapHostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const deckOverlayRef = useRef<MapboxOverlay | null>(null);
  const onSelectRef = useRef(onSelectCity);
  const countryRiskByIsoRef = useRef<Map<string, CountryRisk>>(new Map());
  const onCountrySelectRef = useRef<(risk: CountryRisk) => void>(() => undefined);
  const countryPulseRafRef = useRef<number | null>(null);
  const deckRafRef = useRef<number | null>(null);
  const deckSettleTimerRef = useRef<number | null>(null);
  const interactionEndTimerRef = useRef<number | null>(null);
  const tooltipRafRef = useRef<number | null>(null);
  const pendingTooltipRef = useRef<DeckTooltipState>(null);
  const mapInteractingRef = useRef(false);
  const pointsRef = useRef<WeatherMapPoint[]>([]);
  const conflictPointsRef = useRef<ConflictMapPoint[]>([]);
  const densityPointsRef = useRef<SignalDensityPoint[]>([]);
  const countryRisksRef = useRef<CountryRisk[]>([]);
  const airContextRoutesRef = useRef<AirRoutePath[]>([]);
  const airRoutesRef = useRef<AirRoutePath[]>([]);
  const airHubsRef = useRef<AirHubPoint[]>([]);
  const airFlightsRef = useRef<AirFlightPoint[]>([]);
  const liveAircraftRef = useRef<LiveAircraftPoint[]>([]);
  const animationTimeRef = useRef(0);
  const airAnimationRafRef = useRef<number | null>(null);
  const airAnimationLastRef = useRef<number | null>(null);
  const selectedCityIdRef = useRef<string | null>(selectedCityId);
  const selectedConflictIdRef = useRef<string | null>(null);
  const showLabelsRef = useRef(showLabels);
  const showAirRoutesRef = useRef(showAirRoutes);
  const fallbackAppliedRef = useRef(false);
  const [mapReady, setMapReady] = useState(false);
  const [mapDegraded, setMapDegraded] = useState(false);
  const [mapInteracting, setMapInteracting] = useState(false);
  const [mapZoom, setMapZoom] = useState(1.25);
  const [deckTooltip, setDeckTooltip] = useState<DeckTooltipState>(null);
  const [countryHover, setCountryHover] = useState<CountryHoverState | null>(null);
  const [selectedCountryRisk, setSelectedCountryRisk] = useState<CountryRisk | null>(null);
  const [selectedConflict, setSelectedConflict] = useState<ConflictMapPoint | null>(null);
  const [airLensMode, setAirLensMode] = useState<AirLensMode>('all');
  const [airFocusRegion, setAirFocusRegion] = useState<AirFocusRegion>('global');
  const [airRiskSource, setAirRiskSource] = useState<AirRiskSource>('all');
  const points = useMemo(() => normalizePoints(items), [items]);
  const conflictPoints = useMemo(() => normalizeConflictPoints(ucdpEvents), [ucdpEvents]);
  const densityPoints = useMemo(() => buildSignalDensityPoints(points, conflictPoints), [conflictPoints, points]);
  const countryRisks = useMemo(() => buildCountryRisks(conflictPoints), [conflictPoints]);
  const countryRiskByIso = useMemo(() => new Map(countryRisks.map((risk) => [risk.iso2, risk])), [countryRisks]);
  const baseAirRoutes = useMemo(() => showAirRoutes ? normalizeAirRoutes(transportPayload) : [], [showAirRoutes, transportPayload]);
  const allAirHubs = useMemo(() => showAirRoutes ? normalizeAirHubs(transportPayload) : [], [showAirRoutes, transportPayload]);
  const allAirRoutes = useMemo(
    () => showAirRoutes ? enrichedAirRoutes(baseAirRoutes, points, conflictPoints) : [],
    [baseAirRoutes, conflictPoints, points, showAirRoutes],
  );
  const watchRoutes = useMemo(
    () => allAirRoutes.filter((route) => route.riskSources.length > 0 && airRouteMatchesRegion(route, airFocusRegion)),
    [airFocusRegion, allAirRoutes],
  );
  const riskCounts = useMemo<Record<AirRiskSource, number>>(
    () => ({
      all: watchRoutes.length,
      weather: watchRoutes.filter((route) => route.riskSources.includes('weather')).length,
      conflict: watchRoutes.filter((route) => route.riskSources.includes('conflict')).length,
      corridor: watchRoutes.filter((route) => route.riskSources.includes('corridor')).length,
    }),
    [watchRoutes],
  );
  const lensRoutes = useMemo(
    () => showAirRoutes ? sortAirRoutes(allAirRoutes.filter((route) => airRouteMatchesLens(route, airLensMode)).filter((route) => airLensMode === 'watch' ? airRouteMatchesRiskSource(route, airRiskSource) : true)) : [],
    [airLensMode, airRiskSource, allAirRoutes, showAirRoutes],
  );
  const primaryAirRouteUniverse = useMemo(
    () => lensRoutes.filter((route) => airRouteMatchesRegion(route, airFocusRegion)),
    [airFocusRegion, lensRoutes],
  );
  const airContextRoutes = useMemo(
    () => airFocusRegion === 'global' ? [] : lensRoutes.filter((route) => !airRouteMatchesRegion(route, airFocusRegion)).slice(0, 140),
    [airFocusRegion, lensRoutes],
  );
  const visibleAirRouteBudget = useMemo(
    () => airRouteBudget(mapZoom, airLensMode, airFocusRegion),
    [airFocusRegion, airLensMode, mapZoom],
  );
  const airRoutes = useMemo(
    () => primaryAirRouteUniverse.slice(0, visibleAirRouteBudget),
    [primaryAirRouteUniverse, visibleAirRouteBudget],
  );
  const primaryHubCodes = useMemo(() => new Set(airRoutes.flatMap((route) => [route.fromCode, route.toCode])), [airRoutes]);
  const airHubs = useMemo(
    () => showAirRoutes
      ? allAirHubs.filter((hub) => primaryHubCodes.has(hub.code) || (airFocusRegion !== 'global' && airHubMatchesRegion(hub, airFocusRegion)))
      : [],
    [airFocusRegion, allAirHubs, primaryHubCodes, showAirRoutes],
  );
  const airFlights = useMemo(
    () => showAirRoutes ? normalizeAirFlights(transportPayload, airRoutes, animationTimeRef.current) : [],
    [airRoutes, showAirRoutes, transportPayload],
  );
  const liveAircraft = useMemo(
    () => showAirRoutes ? normalizeLiveAircraft(transportPayload) : [],
    [showAirRoutes, transportPayload],
  );

  const updateDeckLayers = () => {
    const map = mapRef.current;
    const overlay = deckOverlayRef.current;
    if (!map || !overlay) return;
    const zoom = map.getZoom();
    const layers = buildWeatherDeckLayers({
      cities: pointsRef.current,
      conflicts: conflictPointsRef.current,
      countryRisks: countryRisksRef.current,
      densityPoints: densityPointsRef.current,
      airContextRoutes: showAirRoutesRef.current ? airContextRoutesRef.current : [],
      airRoutes: showAirRoutesRef.current ? airRoutesRef.current : [],
      airHubs: showAirRoutesRef.current ? airHubsRef.current : [],
      airFlights: showAirRoutesRef.current ? airFlightsRef.current : [],
      liveAircraft: showAirRoutesRef.current ? liveAircraftRef.current : [],
      animationTime: animationTimeRef.current,
      airLensMode,
      airRiskSource,
      selectedCityId: selectedCityIdRef.current,
      selectedConflictId: selectedConflictIdRef.current,
      zoom,
      bounds: paddedBounds(map),
      showLabels: showLabelsRef.current,
    });
    overlay.setProps({ layers });
    map.triggerRepaint();
  };

  const scheduleDeckUpdate = (delay = 0) => {
    if (deckSettleTimerRef.current) {
      window.clearTimeout(deckSettleTimerRef.current);
      deckSettleTimerRef.current = null;
    }
    if (delay > 0) {
      deckSettleTimerRef.current = window.setTimeout(() => {
        deckSettleTimerRef.current = null;
        scheduleDeckUpdate();
      }, delay);
      return;
    }
    if (deckRafRef.current) return;
    deckRafRef.current = window.requestAnimationFrame(() => {
      deckRafRef.current = null;
      updateDeckLayers();
    });
  };

  const stopAirAnimation = () => {
    if (airAnimationRafRef.current) {
      window.cancelAnimationFrame(airAnimationRafRef.current);
      airAnimationRafRef.current = null;
    }
    airAnimationLastRef.current = null;
  };

  const startAirAnimation = () => {
    stopAirAnimation();
    if (!showAirRoutesRef.current || !airRoutesRef.current.length) {
      scheduleDeckUpdate();
      return;
    }
    const tick = (timestamp: number) => {
      const previous = airAnimationLastRef.current ?? timestamp;
      airAnimationLastRef.current = timestamp;
      animationTimeRef.current += Math.min(0.08, Math.max(0, timestamp - previous) / 1000);
      airFlightsRef.current = normalizeAirFlights(transportPayload, airRoutesRef.current, animationTimeRef.current);
      liveAircraftRef.current = normalizeLiveAircraft(transportPayload);
      scheduleDeckUpdate();
      airAnimationRafRef.current = window.requestAnimationFrame(tick);
    };
    airAnimationRafRef.current = window.requestAnimationFrame(tick);
  };

  const updateDeckTooltip = (next: DeckTooltipState) => {
    pendingTooltipRef.current = next;
    if (tooltipRafRef.current) return;
    tooltipRafRef.current = window.requestAnimationFrame(() => {
      tooltipRafRef.current = null;
      setDeckTooltip(pendingTooltipRef.current);
    });
  };

  const handleDeckHover = (info: PickingInfo<DeckHoverObject>) => {
    const map = mapRef.current;
    if (map) map.getCanvas().style.cursor = info.object ? 'pointer' : '';
    if (!info.object) {
      updateDeckTooltip(null);
      return;
    }
    const object = info.object;
    if ('kind' in object && object.kind === 'conflict-cluster') {
      updateDeckTooltip({ kind: 'cluster', x: info.x, y: info.y, cluster: object });
      return;
    }
    if ('path' in object && 'trafficScore' in object) {
      updateDeckTooltip({ kind: 'air-route', x: info.x, y: info.y, airRoute: object as AirRoutePath });
      return;
    }
    if ('path' in object && 'progress' in object) {
      updateDeckTooltip({ kind: 'air-flight', x: info.x, y: info.y, airFlight: object as AirFlightPoint });
      return;
    }
    if ('callsign' in object && 'originCountry' in object && 'regionLabel' in object) {
      updateDeckTooltip({ kind: 'live-aircraft', x: info.x, y: info.y, liveAircraft: object as LiveAircraftPoint });
      return;
    }
    if ('routeCount' in object && 'code' in object) {
      updateDeckTooltip({ kind: 'air-hub', x: info.x, y: info.y, airHub: object as AirHubPoint });
      return;
    }
    if ('city' in object) {
      updateDeckTooltip({ kind: 'city', x: info.x, y: info.y, city: object as WeatherMapPoint });
      return;
    }
    updateDeckTooltip({ kind: 'conflict', x: info.x, y: info.y, conflict: object as ConflictMapPoint });
  };

  const handleDeckClick = (info: PickingInfo<DeckHoverObject>) => {
    const object = info.object;
    if (!object) return;
    if ('kind' in object && object.kind === 'conflict-cluster') {
      const map = mapRef.current;
      const [west, south, east, north] = object.bounds;
      if (map) {
        map.fitBounds([[west, south], [east, north]], {
          padding: 70,
          maxZoom: 5.8,
          duration: 520,
        });
      }
      return;
    }
    if ('path' in object || ('routeCount' in object && 'code' in object) || ('callsign' in object && 'originCountry' in object)) {
      return;
    }
    if ('city' in object) {
      onSelectRef.current?.((object as WeatherMapPoint).id);
      selectedCityIdRef.current = (object as WeatherMapPoint).id;
      scheduleDeckUpdate();
      return;
    }
    const point = object as ConflictMapPoint;
    selectedConflictIdRef.current = point.id;
    setSelectedCountryRisk(null);
    setSelectedConflict(point);
    highlightCountry(point.iso2, point.tone === 'state' ? 'critical' : point.tone === 'nonstate' ? 'elevated' : 'watch');
    scheduleDeckUpdate();
  };

  const highlightCountry = (iso2: string | null, level: CountryRiskLevel = 'quiet') => {
    const map = mapRef.current;
    if (!map) return;
    if (countryPulseRafRef.current) {
      window.cancelAnimationFrame(countryPulseRafRef.current);
      countryPulseRafRef.current = null;
    }
    const filter: any = ['==', ['get', 'ISO3166-1-Alpha-2'], iso2 || WEATHER_COUNTRY_NO_MATCH];
    try {
      if (map.getLayer('wm-weather-country-selected-fill')) map.setFilter('wm-weather-country-selected-fill', filter);
      if (map.getLayer('wm-weather-country-selected-border')) map.setFilter('wm-weather-country-selected-border', filter);
      if (!iso2 || !map.getLayer('wm-weather-country-selected-fill')) {
        if (map.getLayer('wm-weather-country-selected-fill')) map.setPaintProperty('wm-weather-country-selected-fill', 'fill-opacity', 0);
        if (map.getLayer('wm-weather-country-selected-border')) map.setPaintProperty('wm-weather-country-selected-border', 'line-opacity', 0);
        return;
      }
      const color = countryRiskColor(level);
      map.setPaintProperty('wm-weather-country-selected-fill', 'fill-color', color);
      map.setPaintProperty('wm-weather-country-selected-border', 'line-color', color);
      map.setPaintProperty('wm-weather-country-selected-fill', 'fill-opacity', 0.18);
      map.setPaintProperty('wm-weather-country-selected-border', 'line-opacity', 0.78);
      const startedAt = performance.now();
      const step = (now: number) => {
        if (!map.getLayer('wm-weather-country-selected-fill')) {
          countryPulseRafRef.current = null;
          return;
        }
        const t = (now - startedAt) / 3600;
        if (t >= 1) {
          map.setPaintProperty('wm-weather-country-selected-fill', 'fill-opacity', 0.18);
          map.setPaintProperty('wm-weather-country-selected-border', 'line-opacity', 0.78);
          countryPulseRafRef.current = null;
          return;
        }
        const pulse = Math.sin(t * Math.PI * 4) ** 2;
        const fade = 1 - t * t;
        map.setPaintProperty('wm-weather-country-selected-fill', 'fill-opacity', 0.18 + 0.22 * pulse * fade);
        map.setPaintProperty('wm-weather-country-selected-border', 'line-opacity', 0.78 + 0.2 * pulse * fade);
        countryPulseRafRef.current = window.requestAnimationFrame(step);
      };
      countryPulseRafRef.current = window.requestAnimationFrame(step);
    } catch {
      // MapLibre can be mid-style-switch when fallback tiles are applied.
    }
  };

  useEffect(() => {
    onSelectRef.current = onSelectCity;
  }, [onSelectCity]);

  useEffect(() => {
    selectedCityIdRef.current = selectedCityId;
    scheduleDeckUpdate();
  }, [selectedCityId]);

  useEffect(() => {
    showLabelsRef.current = showLabels;
    scheduleDeckUpdate();
  }, [showLabels]);

  useEffect(() => {
    showAirRoutesRef.current = showAirRoutes;
    airContextRoutesRef.current = airContextRoutes;
    airRoutesRef.current = airRoutes;
    airHubsRef.current = airHubs;
    airFlightsRef.current = airFlights;
    liveAircraftRef.current = liveAircraft;
    startAirAnimation();
    return () => stopAirAnimation();
  }, [airContextRoutes, airFlights, airHubs, airRoutes, liveAircraft, showAirRoutes]);

  useEffect(() => {
    onCountrySelectRef.current = (risk: CountryRisk) => {
      setSelectedConflict(null);
      selectedConflictIdRef.current = null;
      setSelectedCountryRisk(risk);
      highlightCountry(risk.iso2, risk.level);
      scheduleDeckUpdate();
    };
  });

  useEffect(() => {
    pointsRef.current = points;
    scheduleDeckUpdate();
  }, [points]);

  useEffect(() => {
    conflictPointsRef.current = conflictPoints;
    if (selectedConflictIdRef.current && !conflictPoints.some((point) => point.id === selectedConflictIdRef.current)) {
      selectedConflictIdRef.current = null;
      setSelectedConflict(null);
    }
    scheduleDeckUpdate();
  }, [conflictPoints]);

  useEffect(() => {
    densityPointsRef.current = densityPoints;
    scheduleDeckUpdate();
  }, [densityPoints]);

  useEffect(() => {
    if (airLensMode !== 'watch' && airRiskSource !== 'all') {
      setAirRiskSource('all');
      return;
    }
    if (airLensMode === 'watch' && airRiskSource !== 'all' && riskCounts[airRiskSource] === 0) {
      setAirRiskSource('all');
    }
  }, [airLensMode, airRiskSource, riskCounts]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !showAirRoutes) return;
    const preset = AIR_FOCUS_PRESET_MAP.get(airFocusRegion);
    if (!preset) return;
    if (preset.bounds == null) {
      map.easeTo({
        center: [20, 24],
        zoom: 1.25,
        duration: 540,
        essential: true,
      });
      return;
    }
    map.fitBounds(
      [
        [preset.bounds[0], preset.bounds[1]],
        [preset.bounds[2], preset.bounds[3]],
      ],
      {
        padding: { top: 88, right: 24, bottom: 36, left: 24 },
        maxZoom: preset.maxZoom || 4.2,
        duration: 620,
        essential: true,
      },
    );
  }, [airFocusRegion, showAirRoutes]);

  useEffect(() => {
    countryRisksRef.current = countryRisks;
    countryRiskByIsoRef.current = countryRiskByIso;
    updateCountryRiskPaint(mapRef.current, countryRisks);
    if (selectedCountryRisk) {
      const refreshed = countryRiskByIso.get(selectedCountryRisk.iso2);
      if (refreshed && refreshed !== selectedCountryRisk) setSelectedCountryRisk(refreshed);
    }
  }, [countryRiskByIso, countryRisks, selectedCountryRisk]);

  useEffect(() => {
    const host = mapHostRef.current;
    if (!host || mapRef.current) return undefined;
    setMapReady(false);
    setMapDegraded(false);
    fallbackAppliedRef.current = false;
    let styleSettled = false;
    const map = new maplibregl.Map({
      container: host,
      style: getWeatherMapStyle('dark'),
      center: [20, 24],
      zoom: 1.25,
      renderWorldCopies: false,
      attributionControl: false,
      interactive,
      pitchWithRotate: false,
      dragRotate: false,
      touchPitch: false,
      canvasContextAttributes: { powerPreference: 'high-performance' },
    });
    mapRef.current = map;
    const beginMapInteraction = () => {
      if (interactionEndTimerRef.current) {
        window.clearTimeout(interactionEndTimerRef.current);
        interactionEndTimerRef.current = null;
      }
      setMapZoom(map.getZoom());
      if (mapInteractingRef.current) return;
      mapInteractingRef.current = true;
      setMapInteracting(true);
      updateDeckTooltip(null);
    };
    const endMapInteraction = () => {
      if (interactionEndTimerRef.current) window.clearTimeout(interactionEndTimerRef.current);
      interactionEndTimerRef.current = window.setTimeout(() => {
        interactionEndTimerRef.current = null;
        mapInteractingRef.current = false;
        setMapInteracting(false);
        setMapZoom(map.getZoom());
        scheduleDeckUpdate(120);
      }, 110);
    };
    const resizeAndSync = () => {
      if (!mapRef.current || !rootRef.current) return;
      const bounds = rootRef.current.getBoundingClientRect();
      if (bounds.width < 1 || bounds.height < 1) return;
      map.resize();
      setMapZoom(map.getZoom());
      map.triggerRepaint();
      ensureCountryLayers(map, countryRisksRef.current);
      setupCountryInteractions(map, countryRiskByIsoRef, setCountryHover, onCountrySelectRef);
      scheduleDeckUpdate(80);
    };
    const ensureDeckOverlay = () => {
      if (deckOverlayRef.current) {
        scheduleDeckUpdate();
        return;
      }
      const overlay = new MapboxOverlay({
        interleaved: true,
        layers: [],
        onHover: handleDeckHover,
        onClick: handleDeckClick,
        pickingRadius: 8,
        useDevicePixels: window.devicePixelRatio > 2 ? 2 : true,
      });
      deckOverlayRef.current = overlay;
      map.addControl(overlay as unknown as maplibregl.IControl);
      scheduleDeckUpdate();
    };

    const handleStyleReady = () => {
      styleSettled = true;
      setMapReady(true);
      tuneWeatherBasemap(map);
      ensureDeckOverlay();
      ensureCountryLayers(map, countryRisksRef.current);
      setupCountryInteractions(map, countryRiskByIsoRef, setCountryHover, onCountrySelectRef);
      resizeAndSync();
    };

    map.on('load', handleStyleReady);

    map.on('idle', () => {
      styleSettled = true;
      setMapReady(true);
      resizeAndSync();
    });

    map.on('style.load', handleStyleReady);
    map.on('styledata', resizeAndSync);
    map.on('movestart', beginMapInteraction);
    map.on('zoomstart', beginMapInteraction);
    map.on('move', beginMapInteraction);
    map.on('zoom', beginMapInteraction);
    map.on('moveend', endMapInteraction);
    map.on('zoomend', endMapInteraction);

    let tileErrorCount = 0;
    const initialFrame = window.requestAnimationFrame(resizeAndSync);
    const settleTimer = window.setTimeout(resizeAndSync, 250);
    const styleFallbackTimer = window.setTimeout(() => {
      if (styleSettled || fallbackAppliedRef.current) return;
      fallbackAppliedRef.current = true;
      setMapDegraded(true);
      map.setStyle(getWeatherMapFallbackStyle('dark'), { diff: false });
      window.requestAnimationFrame(resizeAndSync);
    }, 2200);
    const onError = (event: { error?: Error; message?: string }) => {
      const message = event.error?.message || event.message || '';
      if (!message || fallbackAppliedRef.current) return;
      if (/Failed to fetch|AJAXError|CORS|NetworkError|403|Forbidden/i.test(message)) {
        tileErrorCount += 1;
        if (tileErrorCount >= 2) {
          fallbackAppliedRef.current = true;
          setMapDegraded(true);
          map.setStyle(getWeatherMapFallbackStyle('dark'), { diff: false });
          window.requestAnimationFrame(resizeAndSync);
        }
      }
    };
    map.on('error', onError);

    const resizeObserver = new ResizeObserver(() => {
      window.requestAnimationFrame(resizeAndSync);
    });
    if (rootRef.current) resizeObserver.observe(rootRef.current);

    return () => {
      if (countryPulseRafRef.current) {
        window.cancelAnimationFrame(countryPulseRafRef.current);
        countryPulseRafRef.current = null;
      }
      stopAirAnimation();
      if (deckRafRef.current) {
        window.cancelAnimationFrame(deckRafRef.current);
        deckRafRef.current = null;
      }
      if (deckSettleTimerRef.current) {
        window.clearTimeout(deckSettleTimerRef.current);
        deckSettleTimerRef.current = null;
      }
      if (tooltipRafRef.current) {
        window.cancelAnimationFrame(tooltipRafRef.current);
        tooltipRafRef.current = null;
      }
      if (interactionEndTimerRef.current) {
        window.clearTimeout(interactionEndTimerRef.current);
        interactionEndTimerRef.current = null;
      }
      mapInteractingRef.current = false;
      window.cancelAnimationFrame(initialFrame);
      window.clearTimeout(settleTimer);
      window.clearTimeout(styleFallbackTimer);
      resizeObserver.disconnect();
      map.off('error', onError);
      map.off('load', handleStyleReady);
      map.off('style.load', handleStyleReady);
      map.off('styledata', resizeAndSync);
      map.off('movestart', beginMapInteraction);
      map.off('zoomstart', beginMapInteraction);
      map.off('move', beginMapInteraction);
      map.off('zoom', beginMapInteraction);
      map.off('moveend', endMapInteraction);
      map.off('zoomend', endMapInteraction);
      if (deckOverlayRef.current) {
        try { map.removeControl(deckOverlayRef.current as unknown as maplibregl.IControl); } catch { /* map can already be tearing down */ }
        deckOverlayRef.current = null;
      }
      map.remove();
      mapRef.current = null;
    };
  }, [interactive]);

  useEffect(() => {
    if (!selectedConflict) return;
    const refreshed = conflictPoints.find((point) => point.id === selectedConflict.id);
    if (refreshed && refreshed !== selectedConflict) setSelectedConflict(refreshed);
  }, [conflictPoints, selectedConflict]);

  return (
    <div
      ref={rootRef}
      className={`wm-weather-deck-map map-ready ${points.length ? 'has-screen-points' : 'no-screen-points'} ${showAirRoutes && airRoutes.length ? 'has-air-routes' : ''} ${mapDegraded ? 'map-degraded' : ''} ${mapInteracting ? 'map-interacting' : ''}`}
      style={{ height: `${height}px` }}
    >
      <div ref={mapHostRef} className={`wm-weather-deck-basemap ${mapReady || points.length ? 'ready' : ''}`} />
      {showAirRoutes && allAirRoutes.length ? (
        <AirMapControls
          lens={airLensMode}
          focus={airFocusRegion}
          riskSource={airRiskSource}
          routeCount={primaryAirRouteUniverse.length}
          totalRouteCount={airLensMode === 'watch' && airRiskSource !== 'all' ? riskCounts.all : lensRoutes.length}
          hubCount={airHubs.length}
          flightCount={airFlights.length + liveAircraft.length}
          riskCounts={riskCounts}
          onLensChange={setAirLensMode}
          onFocusChange={setAirFocusRegion}
          onRiskSourceChange={setAirRiskSource}
        />
      ) : null}
      <CountryHoverTooltip hover={countryHover} />
      <DeckMapTooltip tooltip={deckTooltip} />
      {selectedCountryRisk ? <CountryRiskInspector risk={selectedCountryRisk} onClose={() => { setSelectedCountryRisk(null); highlightCountry(null); }} /> : null}
      {selectedConflict ? <ConflictInspector point={selectedConflict} onClose={() => { setSelectedConflict(null); selectedConflictIdRef.current = null; highlightCountry(null); scheduleDeckUpdate(); }} /> : null}
      <div className="wm-weather-deck-legend" aria-hidden="true">
        <span><i className="hot" />HOT</span>
        <span><i className="cool" />COOL</span>
        {showAirRoutes && airRoutes.length ? <span><i className="air" />AIR ROUTES</span> : null}
        {conflictPoints.length ? <span><i className="ucdp" />UCDP</span> : null}
        {countryRisks.length ? <span><i className="country" />COUNTRY RISK</span> : null}
      </div>
      <div className="wm-weather-deck-status">{mapDegraded ? 'Fallback tiles' : 'DeckGL'}</div>
    </div>
  );
}

export default WeatherDeckMap;
