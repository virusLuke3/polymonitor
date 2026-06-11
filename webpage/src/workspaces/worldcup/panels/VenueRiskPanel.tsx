import { matchCity, WORLD_CUP_HOST_MATCH_COUNTS } from '../data';
import { SourceRequired } from '../components/SourceRequired';
import { WorldCupPanel as Panel } from '../components/WorldCupPanel';
import type { WorldCupDashboardPayload, WorldCupMatch } from '../types';
import { clampNumber } from './panelUtils';

export function VenueRiskPanel({ payload, match, weather }: { payload: WorldCupDashboardPayload; match: WorldCupMatch | null; weather?: WorldCupDashboardPayload['weather'][number] | null }) {
  const city = match ? matchCity(payload.cities, match.cityId) : payload.cities[0];
  const matchCount = city ? Math.max(WORLD_CUP_HOST_MATCH_COUNTS[city.id] || 0, payload.matches.filter((item) => item.cityId === city.id).length) : 0;
  if (!weather) {
    return (
      <Panel title="VENUE RISK" count={0} className="wm-worldcup-panel wm-worldcup-venue-risk-panel">
        <SourceRequired
          detail="Venue risk is calculated only from live weather plus real host-city match count. No default temperature or rain values are used."
          rows={[{ source: 'Open-Meteo runtime weather', status: 'required', detail: 'temperature, wind and precipitation probability by host city' }]}
        />
      </Panel>
    );
  }
  const temp = weather.current.tempC;
  const rain = weather.current.precipitationProbability || 0;
  const wind = weather.current.windKph || 0;
  const risk = clampNumber(Math.round((temp > 27 ? 18 : 6) + rain * 0.35 + wind * 0.7 + matchCount * 1.4), 5, 96);
  const metrics = [
    ['TEMP', temp, 36, 'gold'],
    ['RAIN', rain, 100, 'blue'],
    ['WIND', wind, 40, 'purple'],
    ['LOAD', matchCount * 6, 100, 'green'],
  ] as const;
  return (
    <Panel title="VENUE RISK" count={risk} className="wm-worldcup-panel wm-worldcup-venue-risk-panel">
      <div className="wm-worldcup-risk-score">
        <span><em>{city?.city || 'Host city'}</em><strong>{risk}/100</strong><b>{weather?.current.condition || 'venue watch'}</b></span>
      </div>
      <div className="wm-worldcup-risk-grid">
        {metrics.map(([label, value, max, tone]) => (
          <span className={tone} key={label}>
            <em>{label}</em>
            <strong>{value}{label === 'TEMP' ? 'C' : label === 'WIND' ? 'kph' : '%'}</strong>
            <i style={{ width: `${clampNumber((Number(value) / Number(max)) * 100, 4, 100)}%` }} />
          </span>
        ))}
      </div>
    </Panel>
  );
}
