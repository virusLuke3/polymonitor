import { SourceRequired } from '../components/SourceRequired';
import { WorldCupPanel as Panel } from '../components/WorldCupPanel';
import type { WorldCupDashboardPayload, WorldCupMatch } from '../types';
import { clampNumber } from './panelUtils';

export function TeamPowerPanel({ payload, match }: { payload: WorldCupDashboardPayload; match: WorldCupMatch | null }) {
  const teams = match ? [match.homeTeam, match.awayTeam] : payload.rosters.slice(0, 2).map((roster) => roster.team);
  const rows = teams.map((team) => {
    const roster = payload.rosters.find((item) => item.team === team);
    const confirmed = roster?.players.filter((player) => player.status === 'confirmed').length ?? 0;
    const injured = roster?.players.filter((player) => player.status === 'injured').length ?? 0;
    return { team, rosterCount: roster?.players.length ?? 0, confirmed, injured };
  });
  return (
    <Panel title="TEAM POWER" count={rows.length} className="wm-worldcup-panel wm-worldcup-team-power-panel">
      {payload.rosters.length ? (
        <div className="wm-worldcup-power-grid">
          {rows.map((row) => (
            <section key={row.team}>
              <header><strong>{row.team}</strong><span>{row.rosterCount} players</span></header>
              {[
                ['CONFIRMED', row.confirmed, Math.max(1, row.rosterCount)],
                ['INJURY FLAGS', row.injured, Math.max(1, row.rosterCount)],
                ['ROSTER ROWS', row.rosterCount, 26],
              ].map(([label, value, max]) => (
                <div key={label}>
                  <span>{label}</span>
                  <b>{value}</b>
                  <i style={{ width: `${clampNumber((Number(value) / Number(max)) * 100, 4, 100)}%` }} />
                </div>
              ))}
            </section>
          ))}
        </div>
      ) : (
        <SourceRequired
          detail="Team power cannot be computed without a real squad/rating provider. Elo, form and market value are not estimated in the browser."
          rows={[
            { source: 'FIFA ranking / Elo provider', status: 'required', detail: 'team rating and form inputs' },
            { source: 'Official squads', status: 'required', detail: 'confirmed player pool and availability' },
          ]}
        />
      )}
    </Panel>
  );
}
