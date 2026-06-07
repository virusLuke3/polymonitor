import { Panel } from '@/components/Panel';
import type { RuntimeGlobalWeatherCity, RuntimeGlobalWeatherMapPayload } from '@/types';
import type { PanelRenderMap } from '../../types';
import { panelFromRenderer } from '../helpers';
import { num, panelStatus, selectedWeatherCity, statusBadge, tempLabel } from '../weather-detail-utils';

type TrendPoint = {
  label: string;
  avg: number;
  high: number;
};

function movingAverage(values: number[], index: number) {
  const start = Math.max(0, index - 2);
  const slice = values.slice(start, index + 1);
  return slice.reduce((sum, value) => sum + value, 0) / Math.max(1, slice.length);
}

function oneDayPoints(city?: RuntimeGlobalWeatherCity | null): TrendPoint[] {
  const hourly = (city?.hourly || [])
    .filter((point) => num(point.temp) !== null)
    .slice(0, 24);
  const values = hourly.map((point) => num(point.temp) || 0);
  return hourly.map((point, index) => {
    const value = num(point.temp) || 0;
    const date = String(point.time || '');
    return {
      label: date.slice(11, 16) || date.slice(5, 10) || '--',
      avg: movingAverage(values, index),
      high: value,
    };
  });
}

function sevenDayPoints(city?: RuntimeGlobalWeatherCity | null): TrendPoint[] {
  const days = (city?.daily || [])
    .filter((point) => num(point.high) !== null || num(point.low) !== null)
    .slice(0, 7);
  return days.map((day) => {
    const high = num(day.high) ?? num(day.low) ?? 0;
    const low = num(day.low) ?? high;
    const avg = (high + low) / 2;
    const label = String(day.date || '').slice(5) || '--';
    return { label, avg, high };
  });
}

function pathFor(values: number[], min: number, range: number, width = 260) {
  return values.map((value, index) => {
    const x = 38 + (index / Math.max(1, values.length - 1)) * width;
    const y = 152 - ((value - min) / range) * 124;
    return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${Math.max(18, Math.min(152, y)).toFixed(1)}`;
  }).join(' ');
}

function TrendChart({
  title,
  city,
  points,
}: {
  title: string;
  city?: RuntimeGlobalWeatherCity | null;
  points: TrendPoint[];
}) {
  const unit = city?.unit || '';
  if (points.length < 2) {
    return (
      <section className="wm-weather-trend-card">
        <div className="wm-weather-trend-title"><strong>{title}</strong><span>Avg</span><span>High</span></div>
        <div className="wm-weather-detail-empty-line">No trend data</div>
      </section>
    );
  }
  const all = points.flatMap((point) => [point.avg, point.high]);
  const min = Math.floor(Math.min(...all));
  const max = Math.ceil(Math.max(...all));
  const range = Math.max(1, max - min);
  const avgPath = pathFor(points.map((point) => point.avg), min, range);
  const highPath = pathFor(points.map((point) => point.high), min, range);
  const last = points[points.length - 1];
  const labeledPoints = points
    .map((point, index) => ({ ...point, index }))
    .filter((point) => point.label);
  const isOneDay = title.toLowerCase().includes('1 day');
  const maxLabels = isOneDay ? 5 : 7;
  const labelIndexes = new Set(
    labeledPoints
      .filter((_, index) => index === 0 || index === labeledPoints.length - 1 || index % Math.max(1, Math.ceil(labeledPoints.length / maxLabels)) === 0)
      .map((point) => point.index),
  );
  return (
    <section className="wm-weather-trend-card">
      <div className="wm-weather-trend-title">
        <strong>{title}</strong>
        <span className="avg">Avg</span>
        <span className="high">High</span>
      </div>
      <svg className="wm-weather-trend-chart" viewBox="0 0 330 190" aria-hidden="true">
        {[0, 0.33, 0.66, 1].map((tick) => {
          const value = min + range * tick;
          const y = 152 - tick * 124;
          return (
            <g key={`${title}-${tick}`}>
              <line x1="38" y1={y} x2="298" y2={y} />
              <text x="32" y={y + 4} textAnchor="end">{value.toFixed(1)}°{unit}</text>
            </g>
          );
        })}
        <path className="avg" d={avgPath} />
        <path className="high" d={highPath} />
        <line className="last-guide" x1="298" y1="28" x2="298" y2="152" />
        <circle className="high" cx="298" cy={152 - ((last!.high - min) / range) * 124} r="3.6" />
        <text className="last-label" x="305" y="70">Max {tempLabel(max, unit)}</text>
        <text className="last-label" x="305" y="86">Last {tempLabel(last?.high, unit)}</text>
        {points.map((point, index) => {
          if (!point.label) return null;
          if (!labelIndexes.has(index)) return null;
          const x = 38 + (index / Math.max(1, points.length - 1)) * 260;
          return <text key={`${title}-x-${point.label}`} className="x-label" x={x} y="178" textAnchor="middle">{point.label}</text>;
        })}
      </svg>
    </section>
  );
}

function WeatherTrendDetailPanel({
  payload,
  selectedCityId,
}: {
  payload?: RuntimeGlobalWeatherMapPayload | null;
  selectedCityId?: string | null;
}) {
  const city = selectedWeatherCity(payload, selectedCityId);
  return (
    <Panel
      title="WU 1 DAY"
      badge={statusBadge(payload?.status)}
      status={panelStatus(payload?.status)}
      className="wm-market-panel wm-weather-trend-detail-panel wm-weather-trend-single-panel"
      dataPanelId="weather-trend-detail"
    >
      {city ? (
        <TrendChart title="WU 1 Day" city={city} points={oneDayPoints(city)} />
      ) : (
        <div className="wm-weather-detail-empty">Select a city to inspect temperature trend.</div>
      )}
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'weather-trend-detail': {
    render: (ctx) => (
      <WeatherTrendDetailPanel
        payload={ctx.runtimeData['global-temperature-monitor'] as RuntimeGlobalWeatherMapPayload | undefined}
        selectedCityId={ctx.selectedWeatherCityId}
      />
    ),
  },
};

export const panel = panelFromRenderer(renderers, {
  id: 'weather-trend-detail',
  title: 'WU 1 Day',
  eyebrow: 'weather',
  description: 'Selected city 1D temperature trend chart.',
  defaultEnabled: true,
});

export { sevenDayPoints, TrendChart };
