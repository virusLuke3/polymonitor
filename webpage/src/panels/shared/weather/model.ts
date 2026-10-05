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
  return city?.weatherCarryForward && city?.metarTemp != null ? city.metarTemp : city?.currentTemp ?? city?.metarTemp ?? null;
}

export function highWeatherTemp(city?: RuntimeGlobalWeatherCity | null) {
  return city?.marketDate ? city?.marketForecastHigh ?? null : city?.todayHigh ?? null;
}

export function priceLabel(value?: string | number | null) {
  const parsed = num(value);
  if (parsed === null) return '--';
  return `${Math.round(parsed * 1000) / 10}%`;
}

export function bookMidPrice(bin?: RuntimeWeatherQuoteBin | null) {
  if (bin?.bookStatus && !['ok', 'live'].includes(bin.bookStatus)) return null;
  if (bin?.quoteStaleAfter && Date.parse(bin.quoteStaleAfter) <= Date.now()) return null;
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

export function displayQuoteBins(city?: RuntimeGlobalWeatherCity | null): RuntimeWeatherQuoteBin[] {
  return city?.bins || [];
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
  if (wttr === 'ok') return 'WTTR MODEL';
  if ((city?.weatherCarryForward || openMeteo === 'stale') && city?.metarTemp != null && metar === 'ok') return 'METAR OBSERVATION';
  if (city?.weatherCarryForward || openMeteo === 'stale') return 'WX STALE';
  if (openMeteo === 'ok') return 'OPEN-METEO MODEL';
  if (metar === 'ok') return 'METAR OK';
  if (openMeteo === 'error') return 'WX ERROR';
  return 'WX SEED';
}

export function forecastSourceLabel(city?: RuntimeGlobalWeatherCity | null, payload?: RuntimeGlobalWeatherMapPayload | null) {
  const states = city?.sourceStates || {};
  const openMeteo = String(states.openMeteo || payload?.sources?.openMeteo || '').toLowerCase();
  const wttr = String(states.wttr || payload?.sources?.wttr || '').toLowerCase();
  if (wttr === 'ok') return 'WTTR MODEL';
  if (city?.weatherCarryForward || openMeteo === 'stale') return 'WX STALE';
  if (openMeteo === 'ok') return 'OPEN-METEO MODEL';
  if (openMeteo === 'error') return 'WX ERROR';
  return 'WX SEED';
}

export function updatedLabel(city?: RuntimeGlobalWeatherCity | null, _fallback?: string | null) {
  return formatRelative(city?.weatherCarryForward && city?.metarTemp != null ? city.observationUpdatedAt || null : city?.weatherUpdatedAt || null);
}
