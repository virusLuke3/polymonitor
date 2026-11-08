import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame } from '../../shared/sports-expansion/ui';
import { date, num, seriesScores, validateSports, type SportsPayload } from '../../shared/sports-expansion/model';
import './style.css';
function View({ data }: { data?: SportsPayload }) {
  const [leagueId, setLeagueId] = useState(''), matches = data?.matches ?? [];
  const leagues = [...new Map(matches.map(m => [m.leagueId, m.league])).entries()], selected = leagues.some(([id]) => id === leagueId) ? leagueId : leagues[0]?.[0];
  const games = matches.filter(m => m.leagueId === selected), teams = new Set(games.flatMap(m => [m.radiant, m.dire]));
  const groups = [...new Set(games.map(m => m.seriesId || `single:${m.id}`))];
  return <Frame data={data} className="sportsx-esports-path"><span className="sportsx-badge">DOTA 2 · RECENT RESULTS</span><select aria-label="Esports tournament" value={selected} onChange={e => setLeagueId(e.currentTarget.value)}>{leagues.map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select>
    <div className="sportsx-esports-context"><strong className="sportsx-purple">{teams.size}</strong><span>observed teams</span><strong className="sportsx-cyan">{games.length}</strong><span>recorded maps</span></div>
    <p className="sportsx-warning">Full bracket, future opponents and advancement rules are not supplied.</p>
    {groups.slice(0, 12).map(id => { const maps = games.filter(m => (m.seriesId || `single:${m.id}`) === id); const first = maps[0]!; return <section key={id} className="sportsx-esports-series"><h4>{first.radiant} <small>vs</small> {first.dire}</h4><small>{date(first.eventTime)} · {maps.length} observed map{maps.length > 1 ? 's' : ''} · kills in heading order</small>{maps.map(m => { const score = seriesScores(m, first.radiant); return <div className="sportsx-row" key={m.id}><span className="sportsx-meta">#{m.id}</span><b className="sportsx-cyan">{num(score[0])}–{num(score[1])}</b><small>{m.radiantWin === null ? 'Winner unknown' : m.radiantWin ? m.radiant : m.dire}</small></div>; })}</section>; })}
    <p className="sportsx-note">Coverage is the latest 100 source records, filtered to named teams. Observed games do not establish a complete series score, elimination or championship path.</p>
  </Frame>;
}
export const panel = externalPanel<SportsPayload>({ id: 'esports-tournament-path', title: 'Esports Tournament Path', description: 'Verified professional tournament results grouped by native series; missing bracket edges remain explicit.', render: data => <View data={data}/>, validate: validateSports, intervalMs: 600000, maxAgeMs: 2700000, retentionMs: 86400000 });
