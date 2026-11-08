import { externalPanel } from '../../shared/external/resource';
import { Frame } from '../../shared/sports-expansion/ui';
import { date, num, signed, validateSports, type SportsPayload } from '../../shared/sports-expansion/model';
import './style.css';
function View({ data }: { data?: SportsPayload }) {
  const g = data?.game, home = g?.teams.find(t => t.side === 'home'), away = g?.teams.find(t => t.side === 'away'), q = g?.odds[0];
  const total = home?.score != null && away?.score != null ? home.score + away.score : null;
  const n = Math.max(home?.periods.length ?? 0, away?.periods.length ?? 0), max = Math.max(1, ...Array.from({ length: n }, (_, i) => (home?.periods[i] ?? 0) + (away?.periods[i] ?? 0)));
  return <Frame id="sports-total-monitor" title="Total Monitor" data={data} className="sportsx-total">{g && <><h3>{g.name}</h3><p className="sportsx-meta">{date(g.eventTime)} · {g.statusText} · NBA</p>
    <div className="sportsx-hero"><div><small>{g.state === 'post' ? 'Final total' : 'Points scored'}</small><strong>{num(total)}</strong></div><div><small>Recorded total line</small><strong className="sportsx-purple">{num(q?.totalLine, 1)}</strong></div></div>
    <p className="sportsx-meta"><span className="sportsx-cyan">{home?.short} {num(home?.score)}</span> / <span className="sportsx-orange">{away?.short} {num(away?.score)}</span></p>
    <div className="sportsx-total-quarters" aria-label="Points by period">{Array.from({ length: n }, (_, i) => <div key={i}><b>{home?.periods[i] != null && away?.periods[i] != null ? num(home.periods[i]! + away.periods[i]!) : '—'}</b><div className="sportsx-total-stack"><span style={{ height: `${(home?.periods[i] ?? 0) / max * 84}px` }}>{num(home?.periods[i])}</span><span style={{ height: `${(away?.periods[i] ?? 0) / max * 84}px` }}>{num(away?.periods[i])}</span></div><small>{i < 4 ? `Q${i + 1}` : `OT${i - 3}`}</small></div>)}</div>
    {q && <div className="sportsx-row"><span>{q.provider}<small><br/>American odds</small></span><b className="sportsx-cyan">Over {signed(q.overPrice)}</b><b className="sportsx-purple">Under {signed(q.underPrice)}</b></div>}
    <p className="sportsx-warning">Recorded reference line; source quote time is {q?.quoteAt ?? 'not supplied'}.</p><p className="sportsx-note">Unstarted periods stay absent. Actual totals are not a final-score forecast or a matched Polymarket settlement.</p>
  </>}</Frame>;
}
export const panel = externalPanel<SportsPayload>({ id: 'sports-total-monitor', title: 'Total Monitor', description: 'NBA actual totals and period scoring alongside recorded reference totals.', render: data => <View data={data}/>, validate: validateSports, intervalMs: 600000, maxAgeMs: 1800000, retentionMs: 86400000 });
