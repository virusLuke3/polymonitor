import { useEffect, useMemo, useRef } from 'preact/hooks';
import type { ContentItem, MarketListItem, MarketSummary, OracleEvent, RuntimeGeoSanctionsShockItem, TradeRow } from '@/types';

type GlobePoint = {
  layer: GlobeLayerId;
  lat: number;
  lng: number;
  size: number;
  altitude: number;
  color: string;
  label: string;
};

type GlobeArc = {
  layer: GlobeLayerId;
  startLat: number;
  startLng: number;
  endLat: number;
  endLng: number;
  color: string[];
};

type GlobeRing = {
  layer: GlobeLayerId;
  lat: number;
  lng: number;
  color: string;
};

type GlobeHtmlMarker = {
  layer: GlobeLayerId;
  lat: number;
  lng: number;
  color: string;
  size: number;
  tone: 'state' | 'nonstate' | 'onesided' | 'watch';
  deaths: number;
  label: string;
};

type GlobeLayerId = 'markets' | 'oracle' | 'trade' | 'lob' | 'intel' | 'ucdp';

type WorldGlobeProps = {
  markets: MarketListItem[];
  selectedMarket: MarketSummary | null;
  recentTrades: TradeRow[];
  recentOracle: OracleEvent[];
  contentItems: ContentItem[];
  ucdpEvents: RuntimeGeoSanctionsShockItem[];
  region: string;
  zoomLevel: number;
  enabledLayerIds: string[];
};

const GLOBAL_VIEW = { lat: 20, lng: 6, altitude: 1.54 };
const REGION_VIEW: Record<string, { lat: number; lng: number; altitude: number }> = {
  global: { lat: 20, lng: 6, altitude: 1.54 },
  america: { lat: 22, lng: -85, altitude: 1.34 },
  mena: { lat: 27, lng: 38, altitude: 1.06 },
  eu: { lat: 50, lng: 12, altitude: 0.96 },
  asia: { lat: 27, lng: 98, altitude: 1.24 },
  latam: { lat: -12, lng: -68, altitude: 1.35 },
  africa: { lat: 6, lng: 20, altitude: 1.28 },
  oceania: { lat: -26, lng: 140, altitude: 1.36 },
};

function resolveAltitude(baseAltitude: number, zoomLevel: number) {
  if (zoomLevel >= 4) return Math.max(0.36, baseAltitude * 0.28);
  if (zoomLevel >= 3) return Math.max(0.58, baseAltitude * 0.46);
  if (zoomLevel >= 2) return Math.max(0.82, baseAltitude * 0.66);
  return baseAltitude;
}

const GEO_HINTS: Array<{ pattern: RegExp; lat: number; lng: number }> = [
  { pattern: /\b(israel|netanyahu|gaza|jerusalem|tel aviv)\b/i, lat: 31.7683, lng: 35.2137 },
  { pattern: /\b(iran|tehran|hormuz)\b/i, lat: 35.6892, lng: 51.389 },
  { pattern: /\b(ukraine|kyiv|kiev)\b/i, lat: 50.4501, lng: 30.5234 },
  { pattern: /\b(russia|moscow)\b/i, lat: 55.7558, lng: 37.6173 },
  { pattern: /\b(china|beijing)\b/i, lat: 39.9042, lng: 116.4074 },
  { pattern: /\b(taiwan|taipei)\b/i, lat: 25.033, lng: 121.5654 },
  { pattern: /\b(india|delhi)\b/i, lat: 28.6139, lng: 77.209 },
  { pattern: /\b(pakistan|islamabad)\b/i, lat: 33.6844, lng: 73.0479 },
  { pattern: /\b(europe|eu|brussels)\b/i, lat: 50.8503, lng: 4.3517 },
  { pattern: /\b(uk|britain|london)\b/i, lat: 51.5072, lng: -0.1276 },
  { pattern: /\b(france|paris)\b/i, lat: 48.8566, lng: 2.3522 },
  { pattern: /\b(germany|berlin)\b/i, lat: 52.52, lng: 13.405 },
  { pattern: /\b(us|u\\.s\\.|america|trump|kamala|president|washington)\b/i, lat: 38.9072, lng: -77.0369 },
  { pattern: /\b(california|silicon valley|san francisco)\b/i, lat: 37.7749, lng: -122.4194 },
  { pattern: /\b(new york|wall street)\b/i, lat: 40.7128, lng: -74.006 },
  { pattern: /\b(mexico|mexico city)\b/i, lat: 19.4326, lng: -99.1332 },
  { pattern: /\b(canada|ottawa)\b/i, lat: 45.4215, lng: -75.6972 },
  { pattern: /\b(brazil|brasilia)\b/i, lat: -15.7939, lng: -47.8828 },
  { pattern: /\b(japan|tokyo)\b/i, lat: 35.6762, lng: 139.6503 },
  { pattern: /\b(korea|seoul)\b/i, lat: 37.5665, lng: 126.978 },
  { pattern: /\b(australia|sydney)\b/i, lat: -33.8688, lng: 151.2093 },
  { pattern: /\b(africa|sudan|cairo|egypt)\b/i, lat: 30.0444, lng: 31.2357 },
];

function hashString(value: string) {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash);
}

function resolveGeo(text: string, index = 0) {
  for (const hint of GEO_HINTS) {
    if (hint.pattern.test(text)) {
      return { lat: hint.lat, lng: hint.lng };
    }
  }
  const hash = hashString(`${text}:${index}`);
  const lat = ((hash % 1200) / 10) - 60;
  const lng = (((Math.floor(hash / 1200) % 3600) / 10) - 180);
  return { lat, lng };
}

function numberValue(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function ucdpColor(item: RuntimeGeoSanctionsShockItem) {
  const type = String(item.violenceType || '').trim();
  if (type === '1') return '#ff4d4d';
  if (type === '2') return '#ff9f1c';
  if (type === '3') return '#ffd400';
  const severity = String(item.severity || '').toLowerCase();
  if (severity === 'critical') return '#ff4d4d';
  if (severity === 'warning') return '#ff9f1c';
  return '#ffd400';
}

function ucdpTone(item: RuntimeGeoSanctionsShockItem): GlobeHtmlMarker['tone'] {
  const type = String(item.violenceType || '').trim();
  if (type === '1') return 'state';
  if (type === '2') return 'nonstate';
  if (type === '3') return 'onesided';
  return 'watch';
}

function ucdpLabel(item: RuntimeGeoSanctionsShockItem) {
  const country = item.country || item.locationLabel || 'UCDP';
  const deaths = numberValue(item.deathsBest);
  const actors = [item.sideA, item.sideB].filter(Boolean).join(' vs ');
  return `${country}${deaths != null ? ` · ${deaths} deaths` : ''}${actors ? ` · ${actors}` : ''}`;
}

function buildUcdpMarkers(events: RuntimeGeoSanctionsShockItem[]) {
  return events.slice(0, 1200).flatMap((item): GlobeHtmlMarker[] => {
    const lat = numberValue(item.latitude);
    const lng = numberValue(item.longitude);
    if (lat == null || lng == null || lat < -90 || lat > 90 || lng < -180 || lng > 180) return [];
    const deaths = Math.max(0, numberValue(item.deathsBest) ?? 0);
    const size = Math.min(14, 5 + Math.log10(deaths + 1) * 4);
    return [{
      layer: 'ucdp',
      lat,
      lng,
      color: ucdpColor(item),
      size,
      tone: ucdpTone(item),
      deaths,
      label: ucdpLabel(item),
    }];
  });
}

function createUcdpMarkerElement(marker: GlobeHtmlMarker) {
  const el = document.createElement('div');
  el.className = `wm-globe-html-marker wm-globe-html-marker-${marker.tone} ${marker.deaths >= 20 ? 'is-major' : ''}`;
  el.title = marker.label;
  el.style.setProperty('--marker-color', marker.color);
  el.style.setProperty('--marker-size', `${marker.size}px`);

  const hit = document.createElement('div');
  hit.className = 'wm-globe-html-hit';

  const dot = document.createElement('span');
  dot.className = 'wm-globe-html-dot';
  hit.appendChild(dot);

  if (marker.deaths >= 20) {
    const pulse = document.createElement('span');
    pulse.className = 'wm-globe-html-pulse';
    hit.appendChild(pulse);
  }

  el.appendChild(hit);
  return el;
}

function buildPoints(
  markets: MarketListItem[],
  selectedMarket: MarketSummary | null,
  recentTrades: TradeRow[],
  recentOracle: OracleEvent[],
  contentItems: ContentItem[],
  ucdpEvents: RuntimeGeoSanctionsShockItem[],
  enabledLayerIds: string[],
) {
  const enabledLayers = new Set(enabledLayerIds);
  const isEnabled = (layer: GlobeLayerId) => enabledLayers.has(layer);
  const selectedText = `${selectedMarket?.title || ''} ${selectedMarket?.category || ''} ${(selectedMarket?.tags || []).join(' ')}`;
  const selectedGeo = resolveGeo(selectedText || 'selected-market');

  const marketPoints: GlobePoint[] = markets.slice(0, 24).map((market, index) => {
    const geo = resolveGeo(`${market.title} ${market.category || ''} ${(market.tags || []).join(' ')}`, index);
    return {
      layer: 'markets',
      lat: geo.lat,
      lng: geo.lng,
      size: market.id === selectedMarket?.id ? 0.45 : 0.2 + (index % 3) * 0.05,
      altitude: market.id === selectedMarket?.id ? 0.19 : 0.12,
      color: market.id === selectedMarket?.id ? '#ffcf4b' : '#58a6ff',
      label: market.title,
    };
  });

  const oraclePoints: GlobePoint[] = recentOracle.slice(0, 10).map((event, index) => {
    const geo = resolveGeo(`${event.marketTitle || ''} ${event.questionId || ''}`, index + 40);
    return {
      layer: 'oracle',
      lat: geo.lat,
      lng: geo.lng,
      size: 0.26,
      altitude: 0.16,
      color: '#ff5c5c',
      label: event.marketTitle || event.eventStatus || 'Oracle event',
    };
  });

  const contentPoints: GlobePoint[] = contentItems.slice(0, 8).map((item, index) => {
    const geo = resolveGeo(`${item.title || ''} ${item.summary || ''} ${item.source || ''}`, index + 80);
    return {
      layer: 'intel',
      lat: geo.lat,
      lng: geo.lng,
      size: 0.18,
      altitude: 0.09,
      color: '#39ff73',
      label: item.title || item.source || 'Intel',
    };
  });

  const tradePoints: GlobePoint[] = recentTrades.slice(0, 12).map((trade, index) => {
    const geo = resolveGeo(`${trade.marketId || ''} ${trade.outcome || ''} ${trade.side || ''}`, index + 120);
    return {
      layer: 'trade',
      lat: (selectedGeo.lat + geo.lat) / 2,
      lng: (selectedGeo.lng + geo.lng) / 2,
      size: 0.16,
      altitude: 0.08,
      color: String(trade.side).toLowerCase() === 'buy' ? '#ff8f24' : '#ffd166',
      label: trade.txHash || 'Trade',
    };
  });
  const ucdpMarkers = buildUcdpMarkers(ucdpEvents);

  const arcs: GlobeArc[] = marketPoints.slice(0, 10).map((point, index) => ({
    layer: 'lob',
    startLat: selectedGeo.lat,
    startLng: selectedGeo.lng,
    endLat: point.lat,
    endLng: point.lng,
    color: index % 2 === 0
      ? ['rgba(255,140,36,0.05)', 'rgba(255,140,36,0.78)', 'rgba(255,140,36,0.05)']
      : ['rgba(88,166,255,0.05)', 'rgba(88,166,255,0.72)', 'rgba(88,166,255,0.05)'],
  }));

  const rings: GlobeRing[] = [
    { layer: 'lob', ...selectedGeo, color: '#ffcf4b' },
    ...oraclePoints.slice(0, 3).map((point) => ({ layer: 'oracle' as const, lat: point.lat, lng: point.lng, color: '#ff5c5c' })),
    ...contentPoints.slice(0, 2).map((point) => ({ layer: 'intel' as const, lat: point.lat, lng: point.lng, color: '#39ff73' })),
  ];

  return {
    points: [...marketPoints, ...oraclePoints, ...contentPoints, ...tradePoints].filter((point) => isEnabled(point.layer)),
    htmlMarkers: ucdpMarkers.filter((marker) => isEnabled(marker.layer)),
    rings: rings.filter((ring) => isEnabled(ring.layer)),
    arcs: arcs.filter((arc) => isEnabled(arc.layer)),
    selectedGeo,
  };
}

export function WorldGlobe({ markets, selectedMarket, recentTrades, recentOracle, contentItems, ucdpEvents, region, zoomLevel, enabledLayerIds }: WorldGlobeProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const globeRef = useRef<any>(null);
  const resizeObserverRef = useRef<ResizeObserver | null>(null);

  const globeData = useMemo(
    () => buildPoints(markets, selectedMarket, recentTrades, recentOracle, contentItems, ucdpEvents, enabledLayerIds),
    [contentItems, enabledLayerIds, markets, recentOracle, recentTrades, selectedMarket, ucdpEvents],
  );

  useEffect(() => {
    let disposed = false;

    async function mount() {
      if (!containerRef.current || globeRef.current) return;
      const [{ default: Globe }] = await Promise.all([import('globe.gl')]);
      if (disposed || !containerRef.current) return;

      const globe = new Globe(containerRef.current);
      globeRef.current = globe;

      globe
        .globeImageUrl('/textures/earth-topo-bathy.jpg')
        .backgroundImageUrl('')
        .showAtmosphere(true)
        .atmosphereColor('#5a8dff')
        .atmosphereAltitude(0.2)
        .pointAltitude(((point: object) => (point as GlobePoint).altitude) as any)
        .pointRadius(((point: object) => (point as GlobePoint).size) as any)
        .pointColor(((point: object) => (point as GlobePoint).color) as any)
        .pointLabel(((point: object) => (point as GlobePoint).label) as any)
        .pointResolution(18)
        .pointsMerge(false)
        .arcStroke(0.58)
        .arcAltitudeAutoScale(0.36)
        .arcDashLength(0.85)
        .arcDashGap(3.5)
        .arcDashAnimateTime(5000)
        .arcColor(((arc: object) => (arc as GlobeArc).color) as any)
        .ringColor(((ring: object) => {
          const color = (ring as GlobeRing).color || '#ffba21';
          return (t: number) => `${color}${Math.round(Math.max(0, 1 - t) * 255).toString(16).padStart(2, '0')}`;
        }) as any)
        .ringMaxRadius(5.4)
        .ringPropagationSpeed(1.9)
        .ringRepeatPeriod(1280)
        .htmlElementsData([])
        .htmlLat(((marker: object) => (marker as GlobeHtmlMarker).lat) as any)
        .htmlLng(((marker: object) => (marker as GlobeHtmlMarker).lng) as any)
        .htmlAltitude(0.003)
        .htmlElement(((marker: object) => createUcdpMarkerElement(marker as GlobeHtmlMarker)) as any);

      const controls = globe.controls();
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.3;
      controls.enablePan = false;
      controls.enableZoom = true;
      controls.zoomSpeed = 1.4;
      controls.minDistance = 101;
      controls.maxDistance = 600;
      controls.enableDamping = true;

      const glCanvas = containerRef.current.querySelector('canvas');
      if (glCanvas) {
        (glCanvas as HTMLElement).style.cssText =
          'position:absolute;top:0;left:0;width:100% !important;height:100% !important;';
      }

      const resize = () => {
        if (!containerRef.current || !globeRef.current) return;
        globeRef.current.width(containerRef.current.clientWidth);
        globeRef.current.height(containerRef.current.clientHeight);
      };

      resize();
      resizeObserverRef.current = new ResizeObserver(resize);
      resizeObserverRef.current.observe(containerRef.current);
    }

    void mount();

    return () => {
      disposed = true;
      resizeObserverRef.current?.disconnect();
      resizeObserverRef.current = null;
      if (globeRef.current?._destructor) globeRef.current._destructor();
      globeRef.current = null;
    };
  }, []);

  useEffect(() => {
    const globe = globeRef.current;
    if (!globe) return;
    globe.pointsData(globeData.points);
    globe.ringsData(globeData.rings);
    globe.arcsData(globeData.arcs);
    globe.htmlElementsData(globeData.htmlMarkers);
    const regionView = REGION_VIEW[region] || GLOBAL_VIEW;
    const altitude = resolveAltitude(regionView.altitude, zoomLevel);
    globe.pointOfView(
      { lat: regionView.lat, lng: regionView.lng, altitude },
      900,
    );
  }, [globeData, region, zoomLevel]);

  return (
    <div className="wm-globe-runtime-wrap">
      <div ref={containerRef} className="wm-globe-runtime" />
      <div className="wm-globe-shade" />
    </div>
  );
}
