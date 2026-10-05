import { WeatherQuoteStatus } from '@/panels/shared/weather/WeatherDataStatus';
import { panelStatus } from '../../shared/formatters';
import { useMemo } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import type { RuntimeGlobalWeatherMapPayload, RuntimeWeatherQuoteBin } from '@/types';
import type { PanelRenderMap } from '../../types';
import { panelFromRenderer } from '@/panels/definePanel';
import { bookMidPrice, selectedWeatherCity } from '@/panels/shared/weather/model';
import { useLiveWeatherQuoteBins } from '@/panels/shared/weather/useLiveWeatherQuoteBins';
import { numericTime, WeatherLiveChart, type WeatherLiveChartSeries } from '@/panels/shared/weather/WeatherLiveChart';
import { useSpecialistCopy } from '@/services/specialist-i18n';

function percentAxisLabel(value: number) {
  return `${Math.round(value * 10) / 10}%`;
}

function QuoteCurve({ bins, cityName }: { bins: RuntimeWeatherQuoteBin[]; cityName?: string | null }) {
  const { copy, shared } = useSpecialistCopy('weather-quote-detail');
  const values = bins.map((bin) => bookMidPrice(bin));
  const hasBookQuote = values.some((value) => value !== null);
  const hasLastOnly = bins.some((bin) => bookMidPrice(bin) === null && bin.midPriceYes !== null);
  const chartSeries = useMemo<WeatherLiveChartSeries[]>(() => [{
    id: 'book-mid',
    type: 'area',
    color: '#ff9900',
    topColor: 'rgba(255, 153, 0, 0.36)',
    bottomColor: 'rgba(255, 153, 0, 0.02)',
    data: values
      .map((value, index) => value === null ? null : ({
        time: numericTime(index + 1),
        value: Math.max(0, Math.min(100, value * 100)),
      }))
      .filter((point): point is { time: ReturnType<typeof numericTime>; value: number } => Boolean(point)),
  }], [values]);
  return (
    <div className="wm-weather-quote-curve-panel">
      <div className="wm-weather-chart-title">
        <strong>{copy('curveTitle', '{city} Book Price Curve', { city: cityName || shared('selectedCity', 'Selected city') })}</strong>
        <span>{shared('yesBidAskMid', 'YES Bid/Ask Mid %')}</span>
      </div>
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
      {hasLastOnly ? <p>{copy('lastOnlyNote', 'LAST and one-sided book quotes stay in the table but are not plotted as live bid/ask mid.')}</p> : null}
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
  const { bins, loading } = feed;
  return (
    <Panel
      title={copy('title', 'WEATHER QUOTE CURVE')}
      badge={loading ? 'WARMING' : feed.data?.status === 'ok' ? 'BOOK' : 'PARTIAL'}
      status={panelStatus(feed.data?.status)}
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
