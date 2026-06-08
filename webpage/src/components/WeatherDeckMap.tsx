import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { getWeatherMapFallbackStyle, getWeatherMapStyle } from '@/config/weatherBasemap';
import type { RuntimeGeoSanctionsShockItem, RuntimeGlobalWeatherCity } from '@/types';

type WeatherTone = 'hot' | 'cool' | 'neutral';
type MarketTone = 'market' | 'watch' | 'none';
type ConflictTone = 'state' | 'nonstate' | 'onesided' | 'unknown';
type CountryRiskLevel = 'quiet' | 'watch' | 'elevated' | 'critical';

type WeatherMapPoint = {
  id: string;
  city: string;
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
};

type WeatherDeckMapProps = {
  items: RuntimeGlobalWeatherCity[];
  ucdpEvents?: RuntimeGeoSanctionsShockItem[];
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

type WeatherScreenPoint = WeatherMapPoint & {
  x: number;
  y: number;
  visible: boolean;
};

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

type ConflictScreenPoint = ConflictMapPoint & {
  x: number;
  y: number;
  visible: boolean;
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

const LOCAL_WORLD_COUNTRIES_GEOJSON_URL = '/map-data/world-countries.geojson';
const WEATHER_COUNTRY_SOURCE_ID = 'wm-weather-country-boundaries';
const WEATHER_COUNTRY_NO_MATCH = '__weather_country_no_match__';
const WEATHER_LABEL_BUDGET = 42;
const CONFLICT_POINT_BUDGET_INTERACTING = 0;

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

function countryRiskLevel(score: number): CountryRiskLevel {
  if (score >= 72) return 'critical';
  if (score >= 46) return 'elevated';
  if (score >= 16) return 'watch';
  return 'quiet';
}

function countryRiskColor(level: CountryRiskLevel) {
  if (level === 'critical') return '#ff3535';
  if (level === 'elevated') return '#ff7a1a';
  if (level === 'watch') return '#f4c400';
  return '#3b82f6';
}

function countryRiskOpacity(level: CountryRiskLevel) {
  if (level === 'critical') return 0.42;
  if (level === 'elevated') return 0.3;
  if (level === 'watch') return 0.2;
  return 0.08;
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
    return [{
      id,
      city: String(city.city || id),
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
      ...risks.flatMap((risk): any[] => [risk.iso2, risk.level === 'quiet' ? 0.14 : 0.46]),
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
      'line-opacity': 0.26,
      'line-width': ['interpolate', ['linear'], ['zoom'], 1.5, 0.7, 4, 1.2, 6, 1.65],
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

function projectScreenPoints(map: MapLibreMap | null, points: WeatherMapPoint[]): WeatherScreenPoint[] {
  if (!map) return [];
  const canvas = map.getCanvas();
  const width = canvas.clientWidth || canvas.width;
  const height = canvas.clientHeight || canvas.height;
  return points.map((point) => {
    const projected = map.project([point.lon, point.lat]);
    return {
      ...point,
      x: projected.x,
      y: projected.y,
      visible: projected.x > -90 && projected.x < width + 90 && projected.y > -60 && projected.y < height + 60,
    };
  });
}

function projectConflictScreenPoints(map: MapLibreMap | null, points: ConflictMapPoint[]): ConflictScreenPoint[] {
  if (!map) return [];
  const canvas = map.getCanvas();
  const width = canvas.clientWidth || canvas.width;
  const height = canvas.clientHeight || canvas.height;
  return points.map((point) => {
    const projected = map.project([point.lon, point.lat]);
    return {
      ...point,
      x: projected.x,
      y: projected.y,
      visible: projected.x > -40 && projected.x < width + 40 && projected.y > -40 && projected.y < height + 40,
    };
  });
}

function conflictPriority(point: ConflictScreenPoint, selectedId?: string | null) {
  return (point.id === selectedId ? 1_000_000 : 0)
    + (point.deaths >= 50 ? 120_000 : 0)
    + Math.log10(point.deaths + 1) * 10_000
    + parseDateMs(point.occurredAt) / 1000 / 60 / 60 / 24 / 30;
}

function conflictPointBudget(zoom: number, interacting: boolean) {
  if (interacting) return CONFLICT_POINT_BUDGET_INTERACTING;
  if (zoom < 1.8) return 120;
  if (zoom < 2.6) return 220;
  if (zoom < 3.6) return 340;
  return 520;
}

function WeatherHtmlLabels({
  points,
  selectedCityId,
  onSelectCity,
  disabled = false,
}: {
  points: WeatherScreenPoint[];
  selectedCityId?: string | null;
  onSelectCity?: (cityId: string) => void;
  disabled?: boolean;
}) {
  if (disabled) return null;
  const visiblePoints = points
    .filter((point) => point.visible && shouldShowLabel(point, selectedCityId))
    .sort((a, b) => (
      (b.id === selectedCityId ? 1 : 0) - (a.id === selectedCityId ? 1 : 0)
      || (IMPORTANT_CITY_IDS.has(b.id) ? 1 : 0) - (IMPORTANT_CITY_IDS.has(a.id) ? 1 : 0)
      || (b.topBinPrice ?? -1) - (a.topBinPrice ?? -1)
    ))
    .slice(0, WEATHER_LABEL_BUDGET);
  return (
    <div className="wm-weather-html-label-layer">
      {visiblePoints.map((point) => (
        <button
          type="button"
          key={`weather-label-${point.id}`}
          className={`wm-weather-html-label ${point.temperatureTone} ${point.marketTone} ${point.id === selectedCityId ? 'selected' : ''}`}
          title={`${point.city} ${point.condition} ${point.sublabel}`}
          style={{
            transform: `translate(${Math.round(point.x + point.labelDx)}px, ${Math.round(point.y + point.labelDy)}px)`,
          }}
          onClick={() => onSelectCity?.(point.id)}
        >
          <i aria-hidden="true" />
          <strong>{point.city}</strong>
          <span>{point.sublabel}</span>
        </button>
      ))}
    </div>
  );
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

function UcdpConflictLayer({
  points,
  selectedId,
  onSelect,
  zoom,
  interacting,
}: {
  points: ConflictScreenPoint[];
  selectedId?: string | null;
  onSelect: (point: ConflictScreenPoint) => void;
  zoom: number;
  interacting: boolean;
}) {
  const budget = conflictPointBudget(zoom, interacting);
  const visiblePoints = budget <= 0
    ? []
    : points
      .filter((point) => point.visible)
      .sort((a, b) => conflictPriority(b, selectedId) - conflictPriority(a, selectedId))
      .slice(0, budget);
  if (!visiblePoints.length) return null;
  return (
    <div className="wm-ucdp-map-layer" aria-label="UCDP conflict event overlay">
      {visiblePoints.map((point) => (
        <button
          type="button"
          key={`ucdp-map-${point.id}`}
          className={`wm-ucdp-map-point type-${point.violenceType || 'unknown'} tone-${point.tone} ${point.deaths >= 50 ? 'major' : ''} ${point.id === selectedId ? 'selected' : ''}`}
          aria-label={point.label}
          title={point.label}
          style={{
            transform: `translate(${Math.round(point.x)}px, ${Math.round(point.y)}px)`,
            '--ucdp-color': point.color,
            '--ucdp-size': `${point.size}px`,
          }}
          onClick={(event) => {
            event.stopPropagation();
            onSelect(point);
          }}
        />
      ))}
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

function ConflictInspector({ point, onClose }: { point: ConflictScreenPoint; onClose: () => void }) {
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

export function WeatherDeckMap({ items, ucdpEvents = [], selectedCityId = null, onSelectCity, height = 320, interactive = true, showLabels = true }: WeatherDeckMapProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const mapHostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const onSelectRef = useRef(onSelectCity);
  const countryRiskByIsoRef = useRef<Map<string, CountryRisk>>(new Map());
  const onCountrySelectRef = useRef<(risk: CountryRisk) => void>(() => undefined);
  const countryPulseRafRef = useRef<number | null>(null);
  const projectionRafRef = useRef<number | null>(null);
  const interactionEndTimerRef = useRef<number | null>(null);
  const mapInteractingRef = useRef(false);
  const pointsRef = useRef<WeatherMapPoint[]>([]);
  const conflictPointsRef = useRef<ConflictMapPoint[]>([]);
  const countryRisksRef = useRef<CountryRisk[]>([]);
  const fallbackAppliedRef = useRef(false);
  const [mapReady, setMapReady] = useState(false);
  const [mapDegraded, setMapDegraded] = useState(false);
  const [mapInteracting, setMapInteracting] = useState(false);
  const [mapZoom, setMapZoom] = useState(1.25);
  const [screenPoints, setScreenPoints] = useState<WeatherScreenPoint[]>([]);
  const [conflictScreenPoints, setConflictScreenPoints] = useState<ConflictScreenPoint[]>([]);
  const [countryHover, setCountryHover] = useState<CountryHoverState | null>(null);
  const [selectedCountryRisk, setSelectedCountryRisk] = useState<CountryRisk | null>(null);
  const [selectedConflict, setSelectedConflict] = useState<ConflictScreenPoint | null>(null);
  const points = useMemo(() => normalizePoints(items), [items]);
  const conflictPoints = useMemo(() => normalizeConflictPoints(ucdpEvents), [ucdpEvents]);
  const countryRisks = useMemo(() => buildCountryRisks(conflictPoints), [conflictPoints]);
  const countryRiskByIso = useMemo(() => new Map(countryRisks.map((risk) => [risk.iso2, risk])), [countryRisks]);
  const hasProjectedPoints = screenPoints.some((point) => point.visible);
  const hasProjectedConflicts = conflictScreenPoints.some((point) => point.visible);
  const showHtmlLayer = showLabels && hasProjectedPoints;

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
    onCountrySelectRef.current = (risk: CountryRisk) => {
      setSelectedConflict(null);
      setSelectedCountryRisk(risk);
      highlightCountry(risk.iso2, risk.level);
    };
  });

  useEffect(() => {
    pointsRef.current = points;
  }, [points]);

  useEffect(() => {
    conflictPointsRef.current = conflictPoints;
  }, [conflictPoints]);

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
    const syncScreenPoints = () => {
      setScreenPoints(projectScreenPoints(map, pointsRef.current));
      setConflictScreenPoints(projectConflictScreenPoints(map, conflictPointsRef.current));
      setMapZoom((current) => {
        const next = map.getZoom();
        return Math.abs(next - current) > 0.12 ? next : current;
      });
    };
    const scheduleScreenSync = () => {
      if (projectionRafRef.current) return;
      projectionRafRef.current = window.requestAnimationFrame(() => {
        projectionRafRef.current = null;
        syncScreenPoints();
      });
    };
    const beginMapInteraction = () => {
      if (interactionEndTimerRef.current) {
        window.clearTimeout(interactionEndTimerRef.current);
        interactionEndTimerRef.current = null;
      }
      if (mapInteractingRef.current) return;
      mapInteractingRef.current = true;
      setMapInteracting(true);
    };
    const endMapInteraction = () => {
      if (interactionEndTimerRef.current) window.clearTimeout(interactionEndTimerRef.current);
      interactionEndTimerRef.current = window.setTimeout(() => {
        interactionEndTimerRef.current = null;
        mapInteractingRef.current = false;
        setMapInteracting(false);
        scheduleScreenSync();
      }, 90);
    };
    const resizeAndSync = () => {
      if (!mapRef.current) return;
      map.resize();
      map.triggerRepaint();
      ensureCountryLayers(map, countryRisksRef.current);
      setupCountryInteractions(map, countryRiskByIsoRef, setCountryHover, onCountrySelectRef);
      scheduleScreenSync();
    };

    map.on('load', () => {
      setMapReady(true);
      ensureCountryLayers(map, countryRisksRef.current);
      setupCountryInteractions(map, countryRiskByIsoRef, setCountryHover, onCountrySelectRef);
      resizeAndSync();
    });

    map.on('idle', () => {
      setMapReady(true);
      resizeAndSync();
    });

    map.on('styledata', resizeAndSync);
    map.on('movestart', beginMapInteraction);
    map.on('zoomstart', beginMapInteraction);
    map.on('move', beginMapInteraction);
    map.on('zoom', beginMapInteraction);
    map.on('moveend', endMapInteraction);
    map.on('zoomend', endMapInteraction);
    map.on('resize', scheduleScreenSync);

    let tileErrorCount = 0;
    const initialFrame = window.requestAnimationFrame(resizeAndSync);
    const settleTimer = window.setTimeout(resizeAndSync, 250);
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
      if (projectionRafRef.current) {
        window.cancelAnimationFrame(projectionRafRef.current);
        projectionRafRef.current = null;
      }
      if (interactionEndTimerRef.current) {
        window.clearTimeout(interactionEndTimerRef.current);
        interactionEndTimerRef.current = null;
      }
      mapInteractingRef.current = false;
      window.cancelAnimationFrame(initialFrame);
      window.clearTimeout(settleTimer);
      resizeObserver.disconnect();
      map.off('error', onError);
      map.off('styledata', resizeAndSync);
      map.off('movestart', beginMapInteraction);
      map.off('zoomstart', beginMapInteraction);
      map.off('move', beginMapInteraction);
      map.off('zoom', beginMapInteraction);
      map.off('moveend', endMapInteraction);
      map.off('zoomend', endMapInteraction);
      map.off('resize', scheduleScreenSync);
      map.remove();
      mapRef.current = null;
    };
  }, [interactive]);

  useEffect(() => {
    setScreenPoints(projectScreenPoints(mapRef.current, points));
    setConflictScreenPoints(projectConflictScreenPoints(mapRef.current, conflictPoints));
  }, [conflictPoints, points, selectedCityId]);

  useEffect(() => {
    if (!selectedConflict) return;
    const refreshed = conflictScreenPoints.find((point) => point.id === selectedConflict.id);
    if (refreshed && refreshed !== selectedConflict) setSelectedConflict(refreshed);
  }, [conflictScreenPoints, selectedConflict]);

  return (
    <div
      ref={rootRef}
      className={`wm-weather-deck-map map-ready ${hasProjectedPoints ? 'has-screen-points' : 'no-screen-points'} ${mapDegraded ? 'map-degraded' : ''} ${mapInteracting ? 'map-interacting' : ''}`}
      style={{ height: `${height}px` }}
    >
      <div ref={mapHostRef} className={`wm-weather-deck-basemap ${mapReady || hasProjectedPoints ? 'ready' : ''}`} />
      {hasProjectedConflicts ? (
        <UcdpConflictLayer
          points={conflictScreenPoints}
          selectedId={selectedConflict?.id || null}
          zoom={mapZoom}
          interacting={mapInteracting}
          onSelect={(point) => {
            setSelectedCountryRisk(null);
            setSelectedConflict(point);
            highlightCountry(point.iso2, point.tone === 'state' ? 'critical' : point.tone === 'nonstate' ? 'elevated' : 'watch');
          }}
        />
      ) : null}
      {showHtmlLayer ? <WeatherHtmlLabels points={screenPoints} selectedCityId={selectedCityId} onSelectCity={onSelectCity} disabled={mapInteracting} /> : null}
      <CountryHoverTooltip hover={countryHover} />
      {selectedCountryRisk ? <CountryRiskInspector risk={selectedCountryRisk} onClose={() => { setSelectedCountryRisk(null); highlightCountry(null); }} /> : null}
      {selectedConflict ? <ConflictInspector point={selectedConflict} onClose={() => { setSelectedConflict(null); highlightCountry(null); }} /> : null}
      <div className="wm-weather-deck-legend" aria-hidden="true">
        <span><i className="hot" />HOT</span>
        <span><i className="cool" />COOL</span>
        {conflictPoints.length ? <span><i className="ucdp" />UCDP</span> : null}
        {countryRisks.length ? <span><i className="country" />COUNTRY RISK</span> : null}
      </div>
      <div className="wm-weather-deck-status">{mapDegraded ? 'Fallback tiles' : 'MapLibre'}</div>
    </div>
  );
}

export default WeatherDeckMap;
