import { WeatherQuoteStatus } from '@/panels/shared/weather/WeatherDataStatus';
import { useMemo } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import type { RuntimeGlobalWeatherMapPayload, RuntimeWeatherQuoteBin } from '@/types';
import type { PanelRenderMap } from '../../types';
import { panelFromRenderer } from '@/panels/definePanel';
import { bookMidPrice, retainedBookMidPrice, selectedWeatherCity } from '@/panels/shared/weather/model';
import { useLiveWeatherQuoteBins } from '@/panels/shared/weather/useLiveWeatherQuoteBins';
import { numericTime, WeatherLiveChart, type WeatherLiveChartSeries } from '@/panels/shared/weather/WeatherLiveChart';
import { useSpecialistCopy } from '@/services/specialist-i18n';

function percentAxisLabel(value: number) {
  return `${Math.round(value * 10) / 10}%`;
}

function QuoteCurve({ bins, cityName }: { bins: RuntimeWeatherQuoteBin[]; cityName?: string | null }) {
  const { copy, shared } = useSpecialistCopy('weather-quote-detail');
  const values = bins.map((bin) => bookMidPrice(bin));
  const retained = bins.map((bin) => retainedBookMidPrice(bin));
  const hasBookQuote = [...values, ...retained].some(value => value !== null);
  const hasRetained = retained.some(value => value !== null);
  const chartSeries = useMemo<WeatherLiveChartSeries[]>(() => [
    { id: 'book-mid', type: 'line', color: '#5b9eff', data: values.map((value, index) =>
      value === null ? { time: numericTime(index + 1) } : { time: numericTime(index + 1), value: value * 100 }) },
    { id: 'retained-mid', type: 'line', color: '#e3ac53', data: retained.map((value, index) =>
      value === null ? { time: numericTime(index + 1) } : { time: numericTime(index + 1), value: value * 100 }) },
  ], [values, retained]);
  return (
    <div className="wm-weather-quote-curve-panel">
      <div className="wm-weather-chart-title">
        <strong>{copy('curveTitle', '{city} Book Price Curve', { city: cityName || shared('selectedCity', 'Selected city') })}</strong>
        <span>{shared('yesBidAskMid', 'YES Bid/Ask Mid %')}</span>
      </div>
      <div className="wm-weather-quote-legend"><span>{shared('snapshot', 'Snapshot')} / {shared('live', 'Live')}</span>{hasRetained ? <span>{shared('retainedBooks', 'Retained')}</span> : null}</div>
      {hasBookQuote ? (
        <WeatherLiveChart
          className="wm-weather-quote-curve-large"
          series={chartSeries}
          showTimeScale={false}
          valueFormatter={percentAxisLabel}
        />
      ) : (
        <div className="wm-weather-detail-empty-line wm-weather-quote-curve-large">{copy('noBookMid', 'No two-sided CLOB book mid for this market.')}</div>
      )}

    </div>
  );
}

function WeatherQuoteDetailPanel({
  payload,
  selectedCityId,
}: {
  payload?: RuntimeGlobalWeatherMapPayload | null;
  selectedCityId?: string | null;
}) {
  const { copy } = useSpecialistCopy('weather-quote-detail');
  const city = selectedWeatherCity(payload, selectedCityId);
  const feed = useLiveWeatherQuoteBins(city);
  const { bins } = feed;
  return (
    <Panel
      title={copy('title', 'WEATHER QUOTE CURVE')}
      className="wm-market-panel wm-weather-quote-detail-panel wm-weather-quote-curve-only-panel"
      dataPanelId="weather-quote-detail"
    >
      {city ? (
        <><WeatherQuoteStatus feed={feed} city={city} /><QuoteCurve bins={bins} cityName={city.city} /></>
      ) : (
        <div className="wm-weather-detail-empty">{copy('empty', 'Select a city to inspect quote bins.')}</div>
      )}
    </Panel>
  );
}

const renderers: PanelRenderMap<'selectedWeatherCityId'> = {
  'weather-quote-detail': {
    render: (ctx) => (
      <WeatherQuoteDetailPanel
        payload={ctx.runtimeData['global-temperature-monitor'] as RuntimeGlobalWeatherMapPayload | undefined}
        selectedCityId={ctx.selectedWeatherCityId}
      />
    ),
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['selectedWeatherCityId'],
  id: 'weather-quote-detail',
  title: 'Weather Quote Curve',
  eyebrow: 'weather',
  description: 'Selected city Polymarket temperature bin mid price curve.',
  defaultEnabled: true,
  dataSourceId: 'global-temperature-monitor',
});
