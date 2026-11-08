import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs } from '../../shared/sports-expansion/ui';
import { date, num, validateSports, type SportsPayload } from '../../shared/sports-expansion/model';
import './style.css';
function View({ data }: { data?: SportsPayload }) {
  const [tab, setTab] = useState('Points'), [selected, setSelected] = useState('');
  const g = data?.game, key = tab === 'Points' ? 'points' : tab === 'Rebounds' ? 'rebounds' : 'assists';
  const sorted = [...g?.players ?? []].sort((a, b) => (b[key] ?? -1) - (a[key] ?? -1)), player = sorted.find(p => p.id === selected) ?? sorted[0];
  const high = Math.max(1, ...sorted.map(p => p[key] ?? 0));
  return <Frame data={data} className="sportsx-props">{g && <><p className="sportsx-meta">{g.name} · {date(g.eventTime)} · {g.statusText}</p><Tabs values={['Points', 'Rebounds', 'Assists']} selected={tab} onChange={setTab}/>
    {player && <div className="sportsx-props-profile"><span>{player.jersey ?? '—'}</span><div><h3>{player.name}</h3><small>{player.team} · {player.didNotPlay ? 'DNP' : `${player.minutes ?? 'Unknown'} minutes`} · {player.starter ? 'Starter' : 'Bench'}</small></div><strong>{num(player[key])}</strong></div>}
    <p className="sportsx-note">Actual game box score · select a player to inspect.</p>
    <div className="sportsx-props-bars">{sorted.slice(0, 12).map(p => <button key={p.id} type="button" aria-pressed={p.id === player?.id} onClick={() => setSelected(p.id)}><span>{p.name}<b>{p.didNotPlay ? 'DNP' : num(p[key])}</b></span><i style={{ width: `${Math.max(0, p[key] ?? 0) / high * 100}%` }}/></button>)}</div>
    <p className="sportsx-warning">Player betting lines and minute-qualified award eligibility are not supplied by this box score.</p>
  </>}</Frame>;
}
export const panel = externalPanel<SportsPayload>({ id: 'sports-player-props', title: 'Player Props', description: 'Real NBA points, rebounds, assists, minutes and starter status; no invented prop odds.', render: data => <View data={data}/>, validate: validateSports, intervalMs: 600000, maxAgeMs: 1800000, retentionMs: 86400000 });
