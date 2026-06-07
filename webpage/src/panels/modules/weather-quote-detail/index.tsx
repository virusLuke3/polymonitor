import { useMemo } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import type { RuntimeGlobalWeatherMapPayload, RuntimeWeatherQuoteBin } from '@/types';
import type { PanelRenderMap } from '../../types';
import { panelFromRenderer } from '../helpers';
import { bookPrice, displayQuoteBins, panelStatus, selectedWeatherCity, statusBadge } from '../weather-detail-utils';
import { numericTime, WeatherLiveChart, type WeatherLiveChartSeries } from '../weather-live-chart';

function percentAxisLabel(value: number) {
  return `${Math.round(value * 10) / 10}%`;
}

function QuoteCurve({ bins, cityName }: { bins: RuntimeWeatherQuoteBin[]; cityName?: string | null }) {
  const values = bins.map((bin) => bookPrice(bin));
  const hasBookQuote = values.some((value) => value !== null);
  const hasLastOnly = bins.some((bin) => bookPrice(bin) === null && bin.midPriceYes !== null);
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
        <strong>{cityName || 'Selected city'} Book Price Curve</strong>
        <span>YES Book %</span>
      </div>
      {hasBookQuote ? (
        <WeatherLiveChart
          className="wm-weather-quote-curve-large"
          series={chartSeries}
          showTimeScale={false}
          valueFormatter={percentAxisLabel}
        />
      ) : (
        <div className="wm-weather-detail-empty-line wm-weather-quote-curve-large">No live CLOB book quotes for this market.</div>
      )}
      <div className="wm-weather-quote-history-strip">
        <button type="button">Play History</button>
        <span className="muted">24h ago</span>
        <span className="purple">12h ago</span>
        <span className="green">6h ago</span>
        <span className="cyan">1h ago</span>
        <span className="yellow">30m ago</span>
      </div>
      {hasLastOnly ? <p>LAST prices are kept in the table but are not plotted as live book quotes.</p> : null}
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
  const city = selectedWeatherCity(payload, selectedCityId);
  const bins = displayQuoteBins(city);
  return (
    <Panel
      title="WEATHER QUOTE CURVE"
      badge={statusBadge(payload?.status)}
      status={panelStatus(payload?.status)}
      className="wm-market-panel wm-weather-quote-detail-panel wm-weather-quote-curve-only-panel"
      dataPanelId="weather-quote-detail"
    >
      {city ? (
        <QuoteCurve bins={bins} cityName={city.city} />
      ) : (
        <div className="wm-weather-detail-empty">Select a city to inspect quote bins.</div>
      )}
    </Panel>
  );
}

const renderers: PanelRenderMap = {
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
  id: 'weather-quote-detail',
  title: 'Weather Quote Curve',
  eyebrow: 'weather',
  description: 'Selected city Polymarket temperature bin mid price curve.',
  defaultEnabled: true,
});
