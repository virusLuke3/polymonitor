import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs } from '../../shared/sports-expansion/ui';
import { num, signed, validateSports, type SportsPayload } from '../../shared/sports-expansion/model';
import './style.css';
function View({ data }: { data?: SportsPayload }) {
  const [group, setGroup] = useState(''), [team, setTeam] = useState('');
  const groups = data?.groups ?? [], g = groups.find(g => g.name === group) ?? groups[0], t = g?.rows.find(t => t.id === team) ?? g?.rows[0];
  return <Frame id="sports-season-race" title="Season Race" data={data} className="sportsx-season"><Tabs values={groups.map(g => g.name)} selected={g?.name ?? ''} onChange={setGroup}/>
    {g && t && <><div className="sportsx-season-focus"><div><small>NBA {g.season}</small><h3>{t.name}</h3><span className="sportsx-meta">Provider seed #{num(t.rank)} · {t.streak}</span></div><strong>{num(t.wins)}<small>WINS</small></strong></div>
      <table className="sportsx-table"><thead><tr><th>Team</th><th>W–L</th><th>GB</th><th>DIFF</th></tr></thead><tbody>{g.rows.map(row => <tr key={row.id} className={row.id === t.id ? 'is-selected' : ''}><td><button type="button" aria-pressed={row.id === t.id} onClick={() => setTeam(row.id)}><span className="sportsx-blue">{num(row.rank)}</span> {row.short}</button></td><td>{num(row.wins)}–{num(row.losses)}</td><td className="sportsx-gold">{num(row.gamesBehind, 1)}</td><td className="sportsx-cyan">{signed(row.differential)}</td></tr>)}</tbody></table>
      <p className="sportsx-note">GB: games behind. DIFF: points per game differential. Source ranking is preserved; no local tiebreak or final-qualification inference.</p>
    </>}</Frame>;
}
export const panel = externalPanel<SportsPayload>({ id: 'sports-season-race', title: 'Season Race', description: 'NBA current conference standings, record and distance to the leader.', render: data => <View data={data}/>, validate: validateSports, intervalMs: 600000, maxAgeMs: 64800000, retentionMs: 259200000 });
