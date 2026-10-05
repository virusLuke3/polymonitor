import { panelStatus } from '../../shared/formatters';
import { Panel } from '@/components/Panel';
import type { RuntimeGlobalWeatherMapPayload } from '@/types';
import type { PanelRenderMap } from '../../types';
import { panelFromRenderer } from '@/panels/definePanel';
import { selectedWeatherCity, statusBadge } from '@/panels/shared/weather/model';
import { oneDayPoints } from '@/panels/shared/weather/trend';
import { TrendChart } from '@/panels/shared/weather/TrendChart';
import { useSpecialistCopy } from '@/services/specialist-i18n';

function WeatherTrendDetailPanel({
  payload,
  selectedCityId,
}: {
  payload?: RuntimeGlobalWeatherMapPayload | null;
  selectedCityId?: string | null;
}) {
  const { copy } = useSpecialistCopy('weather-trend-detail');
  const city = selectedWeatherCity(payload, selectedCityId);
  return (
    <Panel
      title={copy('title', 'HOURLY FORECAST')}
      badge={statusBadge(payload?.status)}
      status={panelStatus(payload?.status)}
      className="wm-market-panel wm-weather-trend-detail-panel wm-weather-trend-single-panel"
      dataPanelId="weather-trend-detail"
    >
      {city ? (
        <TrendChart title={copy('chartTitle', 'Hourly forecast')} city={city} points={oneDayPoints(city)} />
      ) : (
        <div className="wm-weather-detail-empty">{copy('empty', 'Select a city to inspect temperature trend.')}</div>
      )}
    </Panel>
  );
}

const renderers: PanelRenderMap<'selectedWeatherCityId'> = {
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
  contextKeys: ['selectedWeatherCityId'],
  id: 'weather-trend-detail',
  title: 'Hourly forecast',
  eyebrow: 'weather',
  description: 'Selected city 1D temperature trend chart.',
  defaultEnabled: true,
  dataSourceId: 'global-temperature-monitor',
});
