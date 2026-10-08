import type { RuntimeGlobalWeatherCity, RuntimeGlobalWeatherMapPayload } from '@/types';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { forecastSourceLabel } from './model';
import type { useLiveWeatherQuoteBins } from './useLiveWeatherQuoteBins';

export function WeatherDataStatus({ city, payload }: { city?: RuntimeGlobalWeatherCity | null; payload?: RuntimeGlobalWeatherMapPayload | null }) {
  const { shared, formatRelativeTime } = useSpecialistCopy('weather-shared');
  return <div className="wm-weather-source-status">
    {payload ? <span>{shared('snapshot', 'Snapshot')} {formatRelativeTime(payload.generatedAt || null)} · {shared('autoCheck', 'Auto check')} 60s · {shared('source', 'Source')} {payload.refresh?.intervalSeconds === 3600 ? '1h' : `${payload.refresh?.intervalSeconds || 3600}s`}</span> : null}
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
  const { shared, formatRelativeTime } = useSpecialistCopy('weather-shared');
  const live = feed.bins.filter(bin => bin.bookStatus === 'ok').length;
  const missing = feed.bins.length - live;
  return <div className="wm-weather-source-status">
    <div className="wm-weather-refresh-row">
      <span>{shared('autoCheck', 'Auto check')} 15s · {shared('marketDate', 'Market date')} {city?.marketDate || '--'}</span>
      <button type="button" disabled={feed.refreshing || !feed.bins.length} onClick={() => void feed.refresh()}>
        {feed.refreshing ? shared('refreshing', 'Refreshing…') : shared('refresh', 'Refresh')}
      </button>
    </div>
    <span>{shared('checked', 'Checked')} {formatRelativeTime(feed.checkedAt ? new Date(feed.checkedAt).toISOString() : null)} · {shared('book', 'Book')} {live}/{feed.bins.length}</span>
    {feed.suspended ? <span>{shared('refreshPaused', 'Refresh paused while this view is hidden.')}</span> : null}
    {missing ? <strong>{shared('missingBooks', '{count} intervals have no current book; retrying automatically.', { count: missing })}</strong> : null}
    {feed.error ? <strong>{feed.error}</strong> : null}
  </div>;
}
