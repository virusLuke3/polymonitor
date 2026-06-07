import { useEffect, useRef } from 'preact/hooks';
import type { RuntimeGlobalWeatherCity, RuntimeGlobalWeatherMapPayload, RuntimeWeatherQuoteBin } from '@/types';
import { formatRelative } from '../shared/formatters';

export function num(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function tempLabel(value?: string | number | null, unit?: string | null) {
  const parsed = num(value);
  if (parsed === null) return '--';
  return `${Math.round(parsed)}°${unit || ''}`;
}

export function currentWeatherTemp(city?: RuntimeGlobalWeatherCity | null) {
  return city?.currentTemp ?? city?.metarTemp ?? city?.todayHigh ?? null;
}

export function highWeatherTemp(city?: RuntimeGlobalWeatherCity | null) {
  return city?.forecastHigh ?? city?.todayHigh ?? city?.currentTemp ?? city?.metarTemp ?? null;
}

export function priceLabel(value?: string | number | null) {
  const parsed = num(value);
  if (parsed === null) return '--';
  return `${Math.round(parsed * 1000) / 10}%`;
}

export function selectedWeatherCity(payload?: RuntimeGlobalWeatherMapPayload | null, selectedCityId?: string | null) {
  const items = payload?.items || [];
  if (!items.length) return null;
  return items.find((item) => String(item.cityId || '') === String(selectedCityId || '')) || items[0] || null;
}

export function bestQuoteBin(city?: RuntimeGlobalWeatherCity | null): RuntimeWeatherQuoteBin | null {
  if (!city) return null;
  if (city.topBin) return city.topBin;
  let best: RuntimeWeatherQuoteBin | null = null;
  for (const bin of city.bins || []) {
    if ((num(bin.midPriceYes) ?? -1) > (num(best?.midPriceYes) ?? -1)) best = bin;
  }
  return best;
}

export function expectedQuoteBins(city?: RuntimeGlobalWeatherCity | null): RuntimeWeatherQuoteBin[] {
  if (!city) return [];
  const unit = city.unit || '';
  const anchor = num(city.forecastHigh ?? city.todayHigh ?? city.currentTemp ?? city.metarTemp);
  if (anchor === null) return [];
  const center = Math.round(anchor);
  const start = center - 5;
  return Array.from({ length: 11 }, (_, index) => {
    const value = start + index;
    const label = index === 0
      ? `${value}°${unit} or below`
      : index === 10
        ? `${value}°${unit} or higher`
        : `${value}°${unit}`;
    return {
      label,
      bucketType: index === 0 ? 'lte' : index === 10 ? 'gte' : 'eq',
      minTemp: value,
      maxTemp: value,
      unit,
      bestBidYes: null,
      bestAskYes: 0.001,
      midPriceYes: null,
      marketStatus: 'Missing Quote',
    };
  });
}

export function displayQuoteBins(city?: RuntimeGlobalWeatherCity | null): RuntimeWeatherQuoteBin[] {
  const family = String(city?.marketFamily || city?.metricType || '').toLowerCase();
  if (city?.bins?.length) return city.bins;
  if (family && !family.includes('temperature')) return [];
  return expectedQuoteBins(city);
}

export function quoteCoverage(city?: RuntimeGlobalWeatherCity | null) {
  if (!city) return '0/0';
  if (city.quoteCoverage) return city.quoteCoverage;
  const bins = city.bins || [];
  if (!bins.length) return '0/0';
  return `${bins.filter((bin) => num(bin.midPriceYes) !== null).length}/${bins.length}`;
}

export function statusBadge(status?: string | null) {
  const text = String(status || '').toLowerCase();
  if (text === 'ok') return 'LIVE';
  if (text === 'degraded') return 'PARTIAL';
  if (text === 'warming') return 'WARMING';
  return text ? text.toUpperCase() : 'SEED';
}

export function panelStatus(status?: string | null): 'live' | 'muted' {
  return String(status || '').toLowerCase() === 'ok' ? 'live' : 'muted';
}

export function sourceStatus(city?: RuntimeGlobalWeatherCity | null) {
  const sourceStates = city?.sourceStates || {};
  const bad = Object.entries(sourceStates).find(([, value]) => !['ok', 'empty'].includes(String(value).toLowerCase()));
  if (bad) return `${bad[0]} ${bad[1]}`;
  if (sourceStates.polymarket === 'ok') return 'market linked';
  if (sourceStates.openMeteo === 'ok') return 'weather live';
  if (sourceStates.metar === 'ok') return 'metar live';
  return 'seed';
}

export function updatedLabel(city?: RuntimeGlobalWeatherCity | null, fallback?: string | null) {
  return formatRelative(city?.updatedAt || city?.hourly?.[0]?.time || fallback || null);
}

export function WeatherCanvasSparkline({
  values,
  className = '',
}: {
  values: number[];
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || values.length < 2) return;
    const rect = canvas.getBoundingClientRect();
    const pixelRatio = window.devicePixelRatio || 1;
    const width = Math.max(1, Math.floor(rect.width));
    const height = Math.max(1, Math.floor(rect.height));
    canvas.width = Math.floor(width * pixelRatio);
    canvas.height = Math.floor(height * pixelRatio);
    const context = canvas.getContext('2d');
    if (!context) return;
    context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
    context.clearRect(0, 0, width, height);

    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = Math.max(1, max - min);
    const xFor = (index: number) => (index / Math.max(1, values.length - 1)) * (width - 4) + 2;
    const yFor = (value: number) => height - 3 - ((value - min) / range) * (height - 6);

    context.strokeStyle = 'rgba(255,255,255,0.08)';
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(0, height - 4);
    context.lineTo(width, height - 4);
    context.moveTo(0, Math.round(height * 0.5));
    context.lineTo(width, Math.round(height * 0.5));
    context.stroke();

    context.strokeStyle = getComputedStyle(canvas).color || '#7edcff';
    context.lineWidth = 2;
    context.lineJoin = 'round';
    context.lineCap = 'round';
    context.beginPath();
    values.forEach((value, index) => {
      const x = xFor(index);
      const y = yFor(value);
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();

    context.fillStyle = context.strokeStyle;
    values.forEach((value, index) => {
      const x = xFor(index);
      const y = yFor(value);
      context.beginPath();
      context.arc(x, y, 1.6, 0, Math.PI * 2);
      context.fill();
    });
  }, [values]);

  return <canvas ref={canvasRef} className={className} aria-hidden="true" />;
}

export function WeatherMiniLine({
  city,
  className = '',
  limit = 24,
}: {
  city?: RuntimeGlobalWeatherCity | null;
  className?: string;
  limit?: number;
}) {
  const points = (city?.hourly || []).filter((point) => num(point.temp) !== null).slice(0, limit);
  if (points.length < 2) return <div className={`wm-weather-detail-empty-line ${className}`.trim()}>No hourly curve</div>;
  const values = points.map((point) => num(point.temp) || 0);
  return <WeatherCanvasSparkline values={values} className={`wm-weather-detail-line ${className}`.trim()} />;
}
