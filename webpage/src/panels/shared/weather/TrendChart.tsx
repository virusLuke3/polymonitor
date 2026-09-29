import { useMemo } from 'preact/hooks';
import type { RuntimeGlobalWeatherCity } from '@/types';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { forecastSourceLabel, tempLabel } from './model';
import { numericTime, WeatherLiveChart, type WeatherLiveChartSeries } from './WeatherLiveChart';
import type { TrendPoint } from './trend';

export function TrendChart({
  title,
  city,
  points,
}: {
  title: string;
  city?: RuntimeGlobalWeatherCity | null;
  points: TrendPoint[];
}) {
  const { shared } = useSpecialistCopy('weather-trend-detail');
  const unit = city?.unit || '';
  const chartSeries = useMemo<WeatherLiveChartSeries[]>(() => {
    return [
      {
        id: `${title}-avg`,
        type: 'line',
        color: '#ff9900',
        data: points.map((point, index) => ({ time: numericTime(point.time || index + 1), value: point.avg })),
      },
      {
        id: `${title}-high`,
        type: 'line',
        color: '#7edcff',
        data: points.map((point, index) => ({ time: numericTime(point.time || index + 1), value: point.high })),
      },
    ];
  }, [points, title]);
  if (points.length < 2) {
    return (
      <section className="wm-weather-trend-card">
        <div className="wm-weather-trend-title"><strong>{title}</strong><span>{shared('average', 'Avg')}</span><span>{shared('high', 'High')}</span></div>
        <div className="wm-weather-detail-empty-line">{shared('noTrendData', 'No trend data')}</div>
      </section>
    );
  }
  return (
    <section className="wm-weather-trend-card">
      <div className="wm-weather-trend-title">
        <strong>{title}</strong>
        <span className="source">{forecastSourceLabel(city)}</span>
        <span className="avg">{shared('average', 'Avg')}</span>
        <span className="high">{shared('high', 'High')}</span>
      </div>
      <WeatherLiveChart
        className="wm-weather-trend-chart"
        series={chartSeries}
        valueFormatter={(value) => tempLabel(value, unit)}
      />
    </section>
  );
}
