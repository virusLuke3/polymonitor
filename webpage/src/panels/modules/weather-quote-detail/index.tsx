import { Panel } from '@/components/Panel';
import type { RuntimeGlobalWeatherMapPayload, RuntimeWeatherQuoteBin } from '@/types';
import type { PanelRenderMap } from '../../types';
import { panelFromRenderer } from '../helpers';
import { displayQuoteBins, num, panelStatus, priceLabel, selectedWeatherCity, statusBadge } from '../weather-detail-utils';

function QuoteCurve({ bins, cityName }: { bins: RuntimeWeatherQuoteBin[]; cityName?: string | null }) {
  const values = bins.map((bin) => num(bin.midPriceYes));
  const hasQuote = values.some((value) => value !== null);
  const points = values.map((value, index) => {
    const x = 42 + (index / Math.max(1, bins.length - 1)) * 378;
    const y = value === null ? null : 136 - Math.max(0, Math.min(1, value)) * 108;
    return { x, y, value };
  });
  const segments: string[][] = [];
  let current: string[] = [];
  for (const point of points) {
    if (point.y === null) {
      if (current.length) segments.push(current);
      current = [];
      continue;
    }
    current.push(`${point.x.toFixed(1)},${point.y.toFixed(1)}`);
  }
  if (current.length) segments.push(current);
  const labelStep = Math.max(1, Math.ceil(bins.length / 4));
  const labelIndexes = bins
    .map((_, index) => index)
    .filter((index) => index === 0 || index === bins.length - 1 || index % labelStep === 0);
  const compactLabel = (label?: string | null) => {
    const value = String(label || '').replace(/\s+/g, ' ').trim();
    const range = value.match(/between\s+(\d+)[^\d]+(\d+)/i);
    if (range) return `${range[1]}-${range[2]}°`;
    const below = value.match(/(\d+)\s*°?[CF]?\s*or below/i);
    if (below) return `<=${below[1]}°`;
    const above = value.match(/(\d+)\s*°?[CF]?\s*or higher/i);
    if (above) return `>=${above[1]}°`;
    const firstNumber = value.match(/(\d+)\s*°?[CF]?/);
    if (firstNumber) return `${firstNumber[1]}°`;
    if (value.length <= 12) return value;
    return `${value.slice(0, 10)}...`;
  };
  return (
    <div className="wm-weather-quote-curve-panel">
      <div className="wm-weather-chart-title">
        <strong>{cityName || 'Selected city'} Mid Price Curve</strong>
        <span>YES Mid %</span>
      </div>
      <svg className="wm-weather-quote-curve-large" viewBox="0 0 440 188" aria-hidden="true">
        {[0, 0.25, 0.5, 0.75, 1].map((tick) => {
          const y = 136 - tick * 108;
          return (
            <g key={`y-${tick}`}>
              <line x1="42" y1={y} x2="420" y2={y} />
              <text x="36" y={y + 4} textAnchor="end">{Math.round(tick * 100)}%</text>
            </g>
          );
        })}
        <line x1="42" y1="28" x2="42" y2="136" />
        <line x1="42" y1="136" x2="420" y2="136" />
        {segments.map((segment, index) => (
          <polyline key={`quote-segment-${index}`} points={segment.join(' ')} fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
        ))}
        {points.map((point, index) => point.y === null ? null : (
          <g key={`quote-dot-${index}`}>
            <circle cx={point.x} cy={point.y} r={point.value && point.value >= 0.99 ? 4.2 : 3.2} />
            {point.value && point.value >= 0.99 && (index === 0 || index === points.length - 1) ? <text x={point.x + 6} y={point.y + 15}>{priceLabel(point.value)}</text> : null}
          </g>
        ))}
        {labelIndexes.map((index) => {
          const x = 42 + (index / Math.max(1, bins.length - 1)) * 378;
          return (
            <text className="wm-weather-quote-x-label" key={`x-${index}`} x={x} y="166" textAnchor="middle">
              {compactLabel(bins[index]?.label)}
            </text>
          );
        })}
      </svg>
      <div className="wm-weather-quote-history-strip">
        <button type="button">Play History</button>
        <span className="muted">24h ago</span>
        <span className="purple">12h ago</span>
        <span className="green">6h ago</span>
        <span className="cyan">1h ago</span>
        <span className="yellow">30m ago</span>
      </div>
      {!hasQuote ? <p>No matching Polymarket temperature market was found for this city. Expected bins are shown as missing quotes.</p> : null}
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
