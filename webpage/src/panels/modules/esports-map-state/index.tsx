import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Spark, Tabs } from '../../shared/sports-expansion/ui';
import { date, num, signed, validateSports, type SportsPayload } from '../../shared/sports-expansion/model';
import './style.css';
function View({ data }: { data?: SportsPayload }) {
  const [tab, setTab] = useState('Gold advantage'), m = data?.match;
  const series = tab === 'Gold advantage' ? m?.goldAdvantage ?? [] : m?.xpAdvantage ?? [];
  return <Frame id="esports-map-state" title="Esports Map State" data={data} className="sportsx-dota-map">{m && <><div className="sportsx-row"><span className="sportsx-badge">DOTA 2 · REPLAY</span><small>{date(m.eventTime)} · {num(m.duration == null ? null : m.duration / 60, 1)} min</small></div><h3>{m.league}</h3>
    <p className="sportsx-meta">Final kills</p><div className="sportsx-dota-score"><div><strong className="sportsx-cyan">{num(m.radiantScore)}</strong><span>{m.radiant}</span><small>Radiant{m.radiantWin ? ' · Winner' : ''}</small></div><span>:</span><div><strong className="sportsx-orange">{num(m.direScore)}</strong><span>{m.dire}</span><small>Dire{m.radiantWin === false ? ' · Winner' : ''}</small></div></div>
    <Tabs values={['Gold advantage', 'XP advantage', 'Players']} selected={tab} onChange={setTab}/>
    {tab !== 'Players' ? <><div className="sportsx-hero"><div><small>Radiant − Dire · last replay sample</small><strong className="sportsx-cyan">{signed(series[series.length - 1])}</strong></div></div><Spark values={series} label={tab}/><p className="sportsx-note">Historical in-game resource difference. It is not a win probability or a current live state.</p></> : <table className="sportsx-table"><thead><tr><th>Player / hero</th><th>K/D/A</th><th>Net worth</th></tr></thead><tbody>{m.players.map((p, i) => <tr key={`${p.id}-${i}`}><td className={p.radiant ? 'sportsx-cyan' : 'sportsx-orange'}>{p.name ?? `Hero ${p.heroId}`}<small><br/>{p.radiant ? 'Radiant' : 'Dire'} · #{p.heroId}</small></td><td>{num(p.kills)}/{num(p.deaths)}/{num(p.assists)}</td><td>{num(p.netWorth)}</td></tr>)}</tbody></table>}
    <p className="sportsx-meta">Match {m.id} · source patch ID {m.patchId ?? 'unknown'}</p><p className="sportsx-warning">CS2 and LoL live map feeds require separately authorized coverage.</p>
  </>}</Frame>;
}
export const panel = externalPanel<SportsPayload>({ id: 'esports-map-state', title: 'Esports Map State', description: 'Real completed Dota 2 professional match: kills, resource trajectory and players.', render: data => <View data={data}/>, validate: validateSports, intervalMs: 600000, maxAgeMs: 2700000, retentionMs: 86400000 });
