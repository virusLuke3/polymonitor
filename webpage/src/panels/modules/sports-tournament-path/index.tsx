import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs } from '../../shared/sports-expansion/ui';
import { date, num, validateSports, type SportsPayload } from '../../shared/sports-expansion/model';
import './style.css';
function View({ data }: { data?: SportsPayload }) {
  const [event, setEvent] = useState(''), [tab, setTab] = useState('Final rounds');
  const tournaments = data?.tournaments ?? [], t = tournaments.find(t => t.id === event) ?? tournaments[0];
  const rounds = [...new Set((t?.matches ?? []).map(m => m.round).filter((r): r is string => !!r))];
  const chosen = tab === 'Final rounds' ? rounds.slice(-3) : rounds;
  return <Frame id="sports-tournament-path" title="Tournament Path" data={data} className="sportsx-tournament">{t && <>
    <select aria-label="ATP tournament" value={t.id} onChange={e => setEvent(e.currentTarget.value)}>{tournaments.map(e => <option key={e.id} value={e.id}>{e.name}</option>)}</select>
    <p className="sportsx-meta">ATP men's singles · {date(t.date)} – {date(t.endDate)}</p><Tabs values={['Final rounds', 'All rounds']} selected={tab} onChange={setTab}/>
    {chosen.map(round => <section className="sportsx-tennis-round" key={round}><h4>{round}</h4>{t.matches.filter(m => m.round === round).map(m => <div className={`sportsx-tennis-match ${m.state === 'pre' ? 'is-upcoming' : ''}`} key={m.id}>
      <small>{date(m.date)} · {m.state === 'post' ? 'Final' : m.state === 'in' ? 'In progress' : 'Scheduled'}</small>
      {m.players.map(p => <div key={p.id} className={p.winner ? 'is-winner' : ''}><span>{p.name}{p.winner ? ' ✓' : ''}</span><b>{p.sets.length ? p.sets.map(n => num(n)).join('  ') : '—'}</b></div>)}
    </div>)}</section>)}
    <p className="sportsx-note">Round names and match results are source facts. Future bracket edges and champion probabilities are not inferred from seeds.</p>
  </>}{!t && <p className="sportsx-note">No ATP tournament in the current source window.</p>}</Frame>;
}
export const panel = externalPanel<SportsPayload>({ id: 'sports-tournament-path', title: 'Tournament Path', description: 'ATP tournament rounds, confirmed opponents and real set scores.', render: data => <View data={data}/>, validate: validateSports, intervalMs: 600000, maxAgeMs: 2700000, retentionMs: 86400000 });
