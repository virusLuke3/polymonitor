import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimeGlobalTemperatureMonitor } from '@/services/api';
import type { RuntimeGlobalWeatherCity, RuntimeGlobalWeatherMapPayload } from '@/types';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '../helpers';
import { panelStatus, priceLabel, quoteCoverage, statusBadge } from '../weather-detail-utils';

const FAMILY_LABELS: Record<string, string> = {
  highest_temperature: 'High',
  lowest_temperature: 'Low',
  precipitation: 'Rain',
  hurricane: 'Hurricane',
  tornado: 'Tornado',
  volcano: 'Volcano',
  pandemic: 'Pandemic',
  global_climate: 'Climate',
  weather_binary: 'Weather',
};

function familyLabel(value?: string | null) {
  const key = String(value || '').trim();
  return FAMILY_LABELS[key] || key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase()) || 'Weather';
}

function familyTone(value?: string | null) {
  const key = String(value || '').toLowerCase();
  if (key.includes('temperature')) return 'temperature';
  if (key.includes('precip')) return 'precipitation';
  if (key.includes('hurricane') || key.includes('tornado')) return 'storm';
  if (key.includes('pandemic') || key.includes('volcano')) return 'alert';
  return 'neutral';
}

function cityMarkets(city: RuntimeGlobalWeatherCity) {
  if (city.markets?.length) return city.markets;
  if (city.eventSlug || city.bins?.length) return [city];
  return [];
}

function MarketRow({
  city,
  market,
  selected,
  onSelectCity,
}: {
  city: RuntimeGlobalWeatherCity;
  market: NonNullable<RuntimeGlobalWeatherCity['markets']>[number] | RuntimeGlobalWeatherCity;
  selected: boolean;
  onSelectCity: (cityId: string) => void;
}) {
  const cityId = String(city.cityId || '');
  const family = String(market.marketFamily || city.marketFamily || 'weather_binary');
  const top = market.topBin || city.topBin || null;
  return (
    <button
      type="button"
      className={`wm-weather-market-row ${familyTone(family)} ${selected ? 'selected' : ''}`}
      onClick={() => cityId && onSelectCity(cityId)}
    >
      <span className="wm-weather-market-family">{familyLabel(family)}</span>
      <strong>{city.city || 'Global'}</strong>
      <em>{top?.label || market.eventTitle || 'Weather market'}</em>
      <b>{priceLabel(top?.midPriceYes)}</b>
      <i>{market.quoteCoverage || quoteCoverage(city)}</i>
    </button>
  );
}

function WeatherMarketBrowserPanel({
  payload,
  selectedCityId,
  onSelectCity,
}: {
  payload?: RuntimeGlobalWeatherMapPayload | null;
  selectedCityId?: string | null;
  onSelectCity: (cityId: string | null) => void;
}) {
  const [familyFilter, setFamilyFilter] = useState<string>('all');
  const familyCounts = payload?.summary?.marketFamilyCounts || {};
  const families = Object.entries(familyCounts)
    .filter(([, count]) => Number(count) > 0)
    .sort((a, b) => String(a[0]).localeCompare(String(b[0])));
  const rows = useMemo(() => {
    return (payload?.items || []).flatMap((city) => cityMarkets(city).map((market) => ({ city, market })))
      .filter(({ market, city }) => {
        if (familyFilter === 'all') return true;
        return String(market.marketFamily || city.marketFamily || '') === familyFilter;
      })
      .slice(0, 80);
  }, [payload?.items, familyFilter]);
  return (
    <Panel
      title="WEATHER MARKETS"
      badge={statusBadge(payload?.status)}
      status={panelStatus(payload?.status)}
      count={rows.length}
      className="wm-market-panel wm-weather-market-browser-panel"
      dataPanelId="weather-market-browser"
    >
      <div className="wm-weather-market-tabs">
        <button type="button" className={familyFilter === 'all' ? 'active' : ''} onClick={() => setFamilyFilter('all')}>All</button>
        {families.slice(0, 8).map(([family, count]) => (
          <button type="button" className={familyFilter === family ? 'active' : ''} key={family} onClick={() => setFamilyFilter(family)}>
            {familyLabel(family)} <span>{count}</span>
          </button>
        ))}
      </div>
      <div className="wm-weather-market-list">
        {rows.length ? rows.map(({ city, market }, index) => (
          <MarketRow
            key={`${city.cityId || city.city}-${market.eventSlug || market.eventTitle || index}`}
            city={city}
            market={market}
            selected={String(city.cityId || '') === String(selectedCityId || '')}
            onSelectCity={onSelectCity}
          />
        )) : (
          <div className="wm-weather-detail-empty">Weather markets are warming.</div>
        )}
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'weather-market-browser': {
    render: (ctx) => (
      <WeatherMarketBrowserPanel
        payload={ctx.runtimeData['global-temperature-monitor'] as RuntimeGlobalWeatherMapPayload | undefined}
        selectedCityId={ctx.selectedWeatherCityId}
        onSelectCity={ctx.setSelectedWeatherCityId}
      />
    ),
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'weather-market-browser',
  title: 'Weather Market Browser',
  eyebrow: 'weather',
  description: 'Grouped Polymarket weather markets across temperature, precipitation, storms, climate, and disaster families.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 60000,
  fetchData: () => fetchRuntimeGlobalTemperatureMonitor(60),
});
