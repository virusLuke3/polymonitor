import type { RuntimeGlobalWeatherCity, RuntimeGlobalWeatherMapPayload, RuntimeWeatherQuoteBin } from '@/types';
import { formatRelative } from '../formatters';

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

export function bookMidPrice(bin?: RuntimeWeatherQuoteBin | null) {
  const bid = num(bin?.bestBidYes);
  const ask = num(bin?.bestAskYes);
  if (bid === null || ask === null) return null;
  return (bid + ask) / 2;
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

export function bestBookQuoteBin(city?: RuntimeGlobalWeatherCity | null): RuntimeWeatherQuoteBin | null {
  let best: RuntimeWeatherQuoteBin | null = null;
  for (const bin of city?.bins || []) {
    const value = bookMidPrice(bin);
    if (value !== null && value > (bookMidPrice(best) ?? -1)) best = bin;
  }
  return best;
}

export function bookCoverage(city?: RuntimeGlobalWeatherCity | null) {
  const bins = city?.bins || [];
  if (!bins.length) return '0/0';
  return `${bins.filter((bin) => num(bin.bestBidYes) !== null || num(bin.bestAskYes) !== null).length}/${bins.length}`;
}

export function bookMidCoverage(city?: RuntimeGlobalWeatherCity | null) {
  const bins = city?.bins || [];
  if (!bins.length) return '0/0';
  return `${bins.filter((bin) => bookMidPrice(bin) !== null).length}/${bins.length}`;
}

export function midCoverage(city?: RuntimeGlobalWeatherCity | null) {
  const bins = city?.bins || [];
  if (!bins.length) return '0/0';
  return `${bins.filter((bin) => num(bin.midPriceYes) !== null).length}/${bins.length}`;
}

function expectedQuoteBins(city?: RuntimeGlobalWeatherCity | null): RuntimeWeatherQuoteBin[] {
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
      bestAskYes: null,
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

export function statusBadge(status?: string | null) {
  const text = String(status || '').toLowerCase();
  if (text === 'ok') return 'LIVE';
  if (text === 'degraded') return 'PARTIAL';
  if (text === 'warming') return 'WARMING';
  return text ? text.toUpperCase() : 'SEED';
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

export function marketSourceLabel(city?: RuntimeGlobalWeatherCity | null) {
  const source = String(city?.marketSource || '').toLowerCase();
  if (source === 'psql-db') return 'PSQL DB';
  if (source === 'gamma-api') return 'GAMMA API';
  if (source) return source.toUpperCase();
  return 'NO MARKET';
}

export function weatherSourceLabel(city?: RuntimeGlobalWeatherCity | null, payload?: RuntimeGlobalWeatherMapPayload | null) {
  const states = city?.sourceStates || {};
  const openMeteo = String(states.openMeteo || payload?.sources?.openMeteo || '').toLowerCase();
  const wttr = String(states.wttr || payload?.sources?.wttr || '').toLowerCase();
  const metar = String(states.metar || states.aviationWeather || payload?.sources?.aviationWeather || '').toLowerCase();
  if (wttr === 'ok') return 'WTTR LIVE';
  if ((city?.weatherCarryForward || openMeteo === 'stale') && metar === 'ok') return 'METAR LIVE';
  if (city?.weatherCarryForward || openMeteo === 'stale') return 'WX STALE';
  if (openMeteo === 'ok') return 'OPEN-METEO';
  if (metar === 'ok') return 'METAR OK';
  if (openMeteo === 'error') return 'WX ERROR';
  return 'WX SEED';
}

export function forecastSourceLabel(city?: RuntimeGlobalWeatherCity | null, payload?: RuntimeGlobalWeatherMapPayload | null) {
  const states = city?.sourceStates || {};
  const openMeteo = String(states.openMeteo || payload?.sources?.openMeteo || '').toLowerCase();
  const wttr = String(states.wttr || payload?.sources?.wttr || '').toLowerCase();
  if (wttr === 'ok') return 'WTTR LIVE';
  if (city?.weatherCarryForward || openMeteo === 'stale') return 'WX STALE';
  if (openMeteo === 'ok') return 'OPEN-METEO';
  if (openMeteo === 'error') return 'WX ERROR';
  return 'WX SEED';
}

export function updatedLabel(city?: RuntimeGlobalWeatherCity | null, fallback?: string | null) {
  return formatRelative(city?.updatedAt || city?.hourly?.[0]?.time || fallback || null);
}
