import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import { getWeatherMapFallbackStyle, getWeatherMapStyle } from '@/config/weatherBasemap';
import type { RuntimeGeoSanctionsShockItem, RuntimeGlobalWeatherCity } from '@/types';

type WeatherTone = 'hot' | 'cool' | 'neutral';
type MarketTone = 'market' | 'watch' | 'none';

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
  country: string;
  actors: string;
  deaths: number;
  violenceType: string;
  color: string;
  size: number;
  label: string;
};

type ConflictScreenPoint = ConflictMapPoint & {
  x: number;
  y: number;
  visible: boolean;
};

function numberValue(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function conflictColor(item: RuntimeGeoSanctionsShockItem) {
  const type = String(item.violenceType || '').trim();
  if (type === '1') return '#ff4d4d';
  if (type === '2') return '#ff9f1c';
  if (type === '3') return '#ffd400';
  const severity = String(item.severity || '').toLowerCase();
  if (severity === 'critical') return '#ff4d4d';
  if (severity === 'warning') return '#ff9f1c';
  return '#ffd400';
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
    const actors = [item.sideA, item.sideB].filter(Boolean).join(' vs ');
    const color = conflictColor(item);
    const size = Math.min(20, 7 + Math.log10(deaths + 1) * 5);
    return [{
      id: String(item.id || `ucdp-${index}`),
      lon,
      lat,
      country,
      actors,
      deaths,
      violenceType: String(item.violenceType || ''),
      color,
      size,
      label: `${country}${deaths ? ` · ${deaths} deaths` : ''}${actors ? ` · ${actors}` : ''}`,
    }];
  });
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

function WeatherHtmlLabels({
  points,
  selectedCityId,
  onSelectCity,
}: {
  points: WeatherScreenPoint[];
  selectedCityId?: string | null;
  onSelectCity?: (cityId: string) => void;
}) {
  return (
    <div className="wm-weather-html-label-layer">
      {points.filter((point) => point.visible && shouldShowLabel(point, selectedCityId)).map((point) => (
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

function UcdpConflictLayer({ points }: { points: ConflictScreenPoint[] }) {
  const visiblePoints = points.filter((point) => point.visible).slice(0, 850);
  if (!visiblePoints.length) return null;
  return (
    <div className="wm-ucdp-map-layer" aria-label="UCDP conflict event overlay">
      {visiblePoints.map((point) => (
        <span
          key={`ucdp-map-${point.id}`}
          className={`wm-ucdp-map-point type-${point.violenceType || 'unknown'}`}
          title={point.label}
          style={{
            transform: `translate(${Math.round(point.x)}px, ${Math.round(point.y)}px)`,
            '--ucdp-color': point.color,
            '--ucdp-size': `${point.size}px`,
          }}
        />
      ))}
    </div>
  );
}

export function WeatherDeckMap({ items, ucdpEvents = [], selectedCityId = null, onSelectCity, height = 320, interactive = true, showLabels = true }: WeatherDeckMapProps) {
  const rootRef = useRef<HTMLDivElement | null>(null);
  const mapHostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const onSelectRef = useRef(onSelectCity);
  const pointsRef = useRef<WeatherMapPoint[]>([]);
  const conflictPointsRef = useRef<ConflictMapPoint[]>([]);
  const fallbackAppliedRef = useRef(false);
  const [mapReady, setMapReady] = useState(false);
  const [mapDegraded, setMapDegraded] = useState(false);
  const [screenPoints, setScreenPoints] = useState<WeatherScreenPoint[]>([]);
  const [conflictScreenPoints, setConflictScreenPoints] = useState<ConflictScreenPoint[]>([]);
  const points = useMemo(() => normalizePoints(items), [items]);
  const conflictPoints = useMemo(() => normalizeConflictPoints(ucdpEvents), [ucdpEvents]);
  const hasProjectedPoints = screenPoints.some((point) => point.visible);
  const hasProjectedConflicts = conflictScreenPoints.some((point) => point.visible);
  const showHtmlLayer = showLabels && hasProjectedPoints;

  useEffect(() => {
    onSelectRef.current = onSelectCity;
  }, [onSelectCity]);

  useEffect(() => {
    pointsRef.current = points;
  }, [points]);

  useEffect(() => {
    conflictPointsRef.current = conflictPoints;
  }, [conflictPoints]);

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
    };
    const resizeAndSync = () => {
      if (!mapRef.current) return;
      map.resize();
      map.triggerRepaint();
      syncScreenPoints();
    };

    map.on('load', () => {
      setMapReady(true);
      resizeAndSync();
    });

    map.on('idle', () => {
      setMapReady(true);
      resizeAndSync();
    });

    map.on('styledata', resizeAndSync);
    map.on('move', syncScreenPoints);
    map.on('zoom', syncScreenPoints);
    map.on('resize', syncScreenPoints);

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
      window.cancelAnimationFrame(initialFrame);
      window.clearTimeout(settleTimer);
      resizeObserver.disconnect();
      map.off('error', onError);
      map.off('styledata', resizeAndSync);
      map.off('move', syncScreenPoints);
      map.off('zoom', syncScreenPoints);
      map.off('resize', syncScreenPoints);
      map.remove();
      mapRef.current = null;
    };
  }, [interactive]);

  useEffect(() => {
    setScreenPoints(projectScreenPoints(mapRef.current, points));
    setConflictScreenPoints(projectConflictScreenPoints(mapRef.current, conflictPoints));
  }, [conflictPoints, points, selectedCityId]);

  return (
    <div
      ref={rootRef}
      className={`wm-weather-deck-map map-ready ${hasProjectedPoints ? 'has-screen-points' : 'no-screen-points'} ${mapDegraded ? 'map-degraded' : ''}`}
      style={{ height: `${height}px` }}
    >
      <div ref={mapHostRef} className={`wm-weather-deck-basemap ${mapReady || hasProjectedPoints ? 'ready' : ''}`} />
      {hasProjectedConflicts ? <UcdpConflictLayer points={conflictScreenPoints} /> : null}
      {showHtmlLayer ? <WeatherHtmlLabels points={screenPoints} selectedCityId={selectedCityId} onSelectCity={onSelectCity} /> : null}
      <div className="wm-weather-deck-legend" aria-hidden="true">
        <span><i className="hot" />HOT</span>
        <span><i className="cool" />COOL</span>
        {conflictPoints.length ? <span><i className="ucdp" />UCDP</span> : null}
      </div>
      <div className="wm-weather-deck-status">{mapDegraded ? 'Fallback tiles' : 'MapLibre'}</div>
    </div>
  );
}

export default WeatherDeckMap;
