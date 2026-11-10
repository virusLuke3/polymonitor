import type { RuntimeGlobalWeatherMapPayload, RuntimeGlobalWeatherCity } from '@/types';
import { publicListSnapshot, record, records, strings, textFields } from '../../public-snapshot';
import { PUBLIC_OVERVIEW_RETENTION_MS, resourceIsCurrent } from '../../resource-cache';

const optional = (value: unknown, validate: (value: any) => boolean) => value == null || validate(value);
const bin = (value: any) => record(value) && textFields(value, ['label', 'unit', 'yesTokenId', 'marketSlug', 'bookStatus', 'quoteUpdatedAt', 'quoteStaleAfter'])
  && ['bestBidYes', 'bestAskYes', 'midPriceYes'].every(key => value[key] == null
    || ['number', 'string'].includes(typeof value[key]) && Number.isFinite(Number(value[key])) && Number(value[key]) >= 0 && Number(value[key]) <= 1);
const market = (value: any) => record(value) && textFields(value, ['marketDate', 'eventSlug', 'eventTitle', 'marketFamily', 'marketUrl'])
  && optional(value.topBin, bin) && optional(value.bins, values => Array.isArray(values) && values.every(bin));
const forecastFields = ['todayHigh', 'todayLow', 'todayWindSpeed', 'todayWindGust',
  'todayPrecipitationSum', 'todayPrecipitationProbability', 'forecastHigh',
  'forecastWindSpeedMax', 'forecastWindGustMax', 'forecastPrecipitationSum',
  'forecastPrecipitationProbabilityMax', 'marketForecastHigh', 'marketForecastLow'] as const;

/** Forecast, catalog and book times are independent, including after a reload. */
export function projectWeatherSnapshot(raw: unknown, now = Date.now()): unknown {
  const payload = raw as RuntimeGlobalWeatherMapPayload;
  let changed = false;
  const items = (payload.items || []).map(city => {
    let date: string;
    try { date = new Intl.DateTimeFormat('en-CA', { timeZone: city.timezone || 'UTC', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now); }
    catch { date = new Date(now).toISOString().slice(0, 10); }
    const catalogValid = resourceIsCurrent(Date.parse(city.marketFetchedAt || ''), 900_000, now);
    const markets = (city.markets || []).filter(m => catalogValid && (!m.marketDate || m.marketDate >= date));
    const clearSelected = !catalogValid || Boolean(city.marketDate && city.marketDate < date);
    const forecastStale = !resourceIsCurrent(Date.parse(city.forecastFetchedAt || ''), 2 * 3_600_000, now);
    // Catalog/METAR publication can advance generatedAt while a forecast source
    // is failing. Its original acquisition time still bounds display recovery.
    const forecastExpired = !resourceIsCurrent(Date.parse(city.forecastFetchedAt || ''), PUBLIC_OVERVIEW_RETENTION_MS, now);
    const clearForecast = forecastExpired && (Boolean(city.hourly?.length || city.daily?.length)
      || forecastFields.some(key => city[key] != null));
    const clear = clearSelected && Boolean(city.marketDate || city.bins?.length || city.topBin || city.eventSlug);
    if (!clear && !clearForecast && markets.length === (city.markets || []).length && (!forecastStale || city.weatherCarryForward)) return city;
    changed = true;
    const next: RuntimeGlobalWeatherCity = { ...city, markets, weatherCarryForward: forecastStale || city.weatherCarryForward };
    if (clear) Object.assign(next, { bins: [], topBin: null, marketDate: null, eventSlug: null, eventTitle: null, marketUrl: null,
      marketForecastHigh: null, marketForecastLow: null, quoteCoverage: '0/0', marketCarryForward: true });
    if (clearForecast) Object.assign(next, { hourly: [], daily: [],
      ...Object.fromEntries(forecastFields.map(key => [key, null])) });
    return next;
  });
  return changed ? { ...payload, items, status: 'degraded' } : raw;
}

export function weatherSnapshot(limit: number) {
  const contract = publicListSnapshot({ id: 'global-temperature-monitor', limit,
    maxAgeMs: 2 * 3_600_000, staleAgeMs: PUBLIC_OVERVIEW_RETENTION_MS, storage: 'indexeddb', maxChars: 4_000_000,
    validate: value => value.items.every((city: Record<string, any>) => typeof city.cityId === 'string'
      && textFields(city, ['city', 'country', 'timezone', 'unit', 'condition', 'forecastFetchedAt', 'marketFetchedAt'])
      && market(city) && optional(city.marketFamilies, strings)
      && optional(city.markets, entries => records(entries) && entries.every(market))
      && ['hourly', 'daily'].every(key => optional(city[key], entries => records(entries)
        && entries.every(row => Object.values(row).every(field => field == null || ['string', 'number'].includes(typeof field)))))),
  });
  return { ...contract, parse: (value: unknown) => projectWeatherSnapshot(contract.parse(value)), revalidate: projectWeatherSnapshot };
}
