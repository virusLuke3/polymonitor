import type { RuntimeGlobalWeatherCity, RuntimeGlobalWeatherMapPayload } from '@/types';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { forecastSourceLabel, hasCurrentBook } from './model';
import type { useLiveWeatherQuoteBins } from './useLiveWeatherQuoteBins';

export function WeatherDataStatus({ city, payload }: { city?: RuntimeGlobalWeatherCity | null; payload?: RuntimeGlobalWeatherMapPayload | null }) {
  const { shared, formatRelativeTime } = useSpecialistCopy('weather-shared');
  return <div className="wm-weather-source-status">
    {payload ? <span>{shared('snapshot', 'Snapshot')} {formatRelativeTime(payload.generatedAt || null)}</span> : null}
    {city ? <>
      <span>{forecastSourceLabel(city)} · {shared('fetched', 'Fetched')} {formatRelativeTime(city.forecastFetchedAt || null)}</span>
      <span>METAR · {shared('observed', 'Observed')} {formatRelativeTime(city.observationUpdatedAt || null)}</span>
      <span>{shared('marketCatalog', 'Market catalog')} · {shared('fetched', 'Fetched')} {formatRelativeTime(city.marketFetchedAt || null)}</span>
      <span>{shared('forecastDate', 'Forecast date')} {city.forecastDate || '--'} · {shared('marketDate', 'Market date')} {city.marketDate || '--'}</span>
      {city.weatherCarryForward ? <strong>{shared('retainedForecast', 'Previous forecast retained; source retry is automatic.')}</strong> : null}
      {city.marketCarryForward ? <strong>{shared('retainedMarkets', 'Previous market catalog retained; source retry is automatic.')}</strong> : null}
    </> : null}
  </div>;
}

export function WeatherQuoteStatus({ feed, city }: { feed: ReturnType<typeof useLiveWeatherQuoteBins>; city?: RuntimeGlobalWeatherCity | null }) {
  const { shared } = useSpecialistCopy('weather-shared');
  const live = feed.bins.filter(hasCurrentBook).length;
  const retained = feed.bins.filter(bin => bin.bookStatus === 'retained').length;
  const missing = feed.bins.length - live - retained;
  return <div className="wm-weather-source-status">
    <div className="wm-weather-refresh-row">
      <span>{shared('marketDate', 'Market date')} {city?.marketDate || '--'}</span>
      <button type="button" disabled={feed.refreshing || !feed.bins.length} onClick={() => void feed.refresh()}>
        {feed.refreshing ? shared('refreshing', 'Refreshing…') : shared('refresh', 'Refresh')}
      </button>
    </div>
    <span>{shared('currentBooks', 'Current books')} {live}/{feed.bins.length} · {shared('retainedBooks', 'Retained')} {retained}</span>
    {retained ? <strong>{shared('retainedBookNotice', 'Retained quotes · source interrupted')}</strong> : null}
    {feed.suspended ? <span>{shared('refreshPaused', 'Refresh paused while this view is hidden.')}</span> : null}
    {missing ? <strong>{shared('missingBooks', '{count} intervals have no current book; retrying automatically.', { count: missing })}</strong> : null}
    {feed.error ? <strong>{feed.error}</strong> : null}
  </div>;
}
