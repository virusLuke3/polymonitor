import { panelStatus } from '../../shared/formatters';
import { Panel } from '@/components/Panel';
import type { RuntimeGlobalWeatherMapPayload } from '@/types';
import type { PanelRenderMap } from '../../types';
import { panelFromRenderer } from '@/panels/definePanel';
import { selectedWeatherCity, statusBadge } from '@/panels/shared/weather/model';
import { sevenDayPoints } from '../../shared/weather/trend';
import { TrendChart } from '../../shared/weather/TrendChart';
import { useSpecialistCopy } from '@/services/specialist-i18n';

function WeatherTrend7dPanel({
  payload,
  selectedCityId,
}: {
  payload?: RuntimeGlobalWeatherMapPayload | null;
  selectedCityId?: string | null;
}) {
  const { copy } = useSpecialistCopy('weather-trend-7d');
  const city = selectedWeatherCity(payload, selectedCityId);
  return (
    <Panel
      title={copy('title', '7 DAY FORECAST')}
      badge={statusBadge(payload?.status)}
      status={panelStatus(payload?.status)}
      className="wm-market-panel wm-weather-trend-detail-panel wm-weather-trend-single-panel"
      dataPanelId="weather-trend-7d"
    >
      {city ? (
        <TrendChart title={copy('chartTitle', '7 day forecast')} city={city} points={sevenDayPoints(city)} daily />
      ) : (
        <div className="wm-weather-detail-empty">{copy('empty', 'Select a city to inspect 7 day temperature trend.')}</div>
      )}
    </Panel>
  );
}

const renderers: PanelRenderMap<'selectedWeatherCityId'> = {
  'weather-trend-7d': {
    render: (ctx) => (
      <WeatherTrend7dPanel
        payload={ctx.runtimeData['global-temperature-monitor'] as RuntimeGlobalWeatherMapPayload | undefined}
        selectedCityId={ctx.selectedWeatherCityId}
      />
    ),
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['selectedWeatherCityId'],
  id: 'weather-trend-7d',
  title: '7 day forecast',
  eyebrow: 'weather',
  description: 'Selected city 7 day temperature trend chart.',
  defaultEnabled: true,
  dataSourceId: 'global-temperature-monitor',
});
