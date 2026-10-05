import { WeatherDataStatus } from './WeatherDataStatus';
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
  daily = false,
}: {
  title: string;
  city?: RuntimeGlobalWeatherCity | null;
  points: TrendPoint[];
  daily?: boolean;
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
        <div className="wm-weather-trend-title"><strong>{title} · {city?.timezone || 'UTC'}</strong><span>{daily ? shared('highLowMidpoint', 'High/low midpoint') : shared('movingAverage', '3-point mean')}</span><span>{daily ? shared('dailyHigh', 'Daily high') : shared('hourlyTemperature', 'Hourly temperature')}</span></div>
        <div className="wm-weather-detail-empty-line">{shared('noTrendData', 'No trend data')}</div>
      </section>
    );
  }
  return (
    <section className="wm-weather-trend-card">
      <div className="wm-weather-trend-title">
        <strong>{title} · {city?.timezone || 'UTC'}</strong>
        <span className="source">{forecastSourceLabel(city)}</span>
        <span className="avg">{daily ? shared('highLowMidpoint', 'High/low midpoint') : shared('movingAverage', '3-point mean')}</span>
        <span className="high">{daily ? shared('dailyHigh', 'Daily high') : shared('hourlyTemperature', 'Hourly temperature')}</span>
      </div>
      <WeatherDataStatus city={city} />
      <WeatherLiveChart
        className="wm-weather-trend-chart"
        series={chartSeries}
        valueFormatter={(value) => tempLabel(value, unit)}
        timeFormatter={value => typeof value === 'number' ? new Intl.DateTimeFormat(undefined, {
          timeZone: daily ? 'UTC' : city?.timezone || 'UTC', month: 'short', day: 'numeric',
          ...(daily ? {} : { hour: '2-digit', minute: '2-digit' }),
        }).format(new Date(value * 1000)) : String(value)}
      />
    </section>
  );
}
