import { externalPanel } from '../../shared/external/resource';
import { Frame } from '../../shared/sports-expansion/ui';
import { date, num, signed, validateSports, type SportsPayload } from '../../shared/sports-expansion/model';
import './style.css';

function View({ data }: { data?: SportsPayload }) {
  const game = data?.game, home = game?.teams.find(t => t.side === 'home'), away = game?.teams.find(t => t.side === 'away');
  const quote = game?.odds[0], margin = home?.score != null && away?.score != null ? home.score - away.score : null;
  const periods = Math.max(home?.periods.length ?? 0, away?.periods.length ?? 0);
  return <Frame data={data} className="sportsx-spread">{game && <>
    <h3><span className="sportsx-blue">{home?.name}</span><small> vs </small><span className="sportsx-orange">{away?.name}</span></h3>
    <p className="sportsx-meta">NBA · {date(game.eventTime)} · {game.statusText}</p>
    <div className="sportsx-hero"><div><small>Home reference spread</small><strong className="sportsx-blue">{signed(quote?.homeLine)}</strong></div><div><small>Actual home margin</small><strong>{signed(margin)}</strong></div></div>
    <p className="sportsx-warning">{game.state === 'post' ? 'Completed game · recorded line' : 'Reference only'} · quote publication time {quote?.quoteAt ? 'provided' : 'not supplied'}</p>
    <div className="sportsx-spread-periods" aria-label="Actual scoring margin by quarter">{Array.from({ length: periods }, (_, i) => {
      const h = home?.periods[i], a = away?.periods[i], diff = h != null && a != null ? h - a : null;
      return <div key={i}><span>{i < 4 ? `Q${i + 1}` : `OT${i - 3}`}</span><b className={diff != null && diff < 0 ? 'sportsx-orange' : 'sportsx-blue'}>{signed(diff)}</b><i style={{ height: `${Math.min(50, Math.abs(diff ?? 0) * 3)}px` }}/></div>;
    })}</div>
    <h4>Recorded bookmaker line</h4><table className="sportsx-table"><thead><tr><th>Source</th><th>Home</th><th>Away</th></tr></thead><tbody>{game.odds.map((q, i) => <tr key={i}><td>{q.provider}<small><br/>{q.details}</small></td><td className="sportsx-blue">{signed(q.homeLine)}<small><br/>{signed(q.homePrice)}</small></td><td className="sportsx-orange">{q.homeLine == null ? '—' : signed(-q.homeLine)}<small><br/>{signed(q.awayPrice)}</small></td></tr>)}</tbody></table>
    {!game.odds.length && <p className="sportsx-note">No bookmaker reference line supplied for this game.</p>}
    <p className="sportsx-note">American odds. Quarter margins are actual scores, not historical line movement. No Polymarket contract binding or executable hedge.</p>
    <p className="sportsx-meta">Final score: {num(home?.score)} – {num(away?.score)}</p>
  </>}</Frame>;
}
export const panel = externalPanel<SportsPayload>({ id: 'sports-spread-monitor', title: 'Spread Monitor', description: 'NBA reference handicap and actual quarter margins, with source-time limits.', render: data => <View data={data}/>, validate: validateSports, intervalMs: 600000, maxAgeMs: 1800000, retentionMs: 86400000 });
