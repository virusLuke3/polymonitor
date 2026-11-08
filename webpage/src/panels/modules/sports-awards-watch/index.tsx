import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs } from '../../shared/sports-expansion/ui';
import { num, validateSports, type SportsPayload } from '../../shared/sports-expansion/model';
import './style.css';
function View({ data }: { data?: SportsPayload }) {
  const [tab, setTab] = useState('Performance'), [key, setKey] = useState('pointsPerGame');
  const categories = (data?.categories ?? []).filter(c => ['pointsPerGame', 'reboundsPerGame', 'assistsPerGame', 'blocksPerGame', 'stealsPerGame', 'PER'].includes(c.id));
  const c = categories.find(c => c.id === key) ?? categories[0], leader = c?.rows[0];
  return <Frame data={data} className="sportsx-awards"><h3 className="sportsx-gold">NBA · Award research</h3><p className="sportsx-meta">{data?.season} · performance context</p><Tabs values={['Performance', 'Eligibility & voting']} selected={tab} onChange={setTab}/>
    {tab === 'Performance' && <><select aria-label="Season award research statistic" value={c?.id} onChange={e => setKey(e.currentTarget.value)}>{categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
      {leader && <div className="sportsx-awards-leader"><span>#1 <small>statistical leader</small></span><h3>{leader.name}</h3><strong>{leader.displayValue}<small>{c?.abbreviation}</small></strong></div>}
      <p className="sportsx-warning">Statistical rank is not an official award nomination or MVP ranking.</p>
      {c?.rows.slice(1, 8).map(p => <div className="sportsx-row" key={p.id}><span><small>#{p.rank}</small> {p.name}<small><br/>{p.team}</small></span><b className="sportsx-gold">{num(p.value, 1)}</b></div>)}
    </>}
    {tab !== 'Performance' && <><div className="sportsx-accent-block sportsx-gold"><h4>Official qualification: unknown</h4><p>Complete per-game qualifying minutes, medical exceptions and appeals are not available in this feed. Games played alone cannot certify eligibility.</p></div><div className="sportsx-row"><span>Official candidates</span><b>Not acquired</b></div><div className="sportsx-row"><span>Official ballots / vote totals</span><b>Not acquired</b></div><p className="sportsx-note">Performance totals are sourced; eligibility and voting require separate official evidence. No invented zero votes or award probabilities.</p></>}
  </Frame>;
}
export const panel = externalPanel<SportsPayload>({ id: 'sports-awards-watch', title: 'Awards Watch', description: 'Current NBA performance evidence for award research; qualification and ballot gaps stay explicit.', render: data => <View data={data}/>, validate: validateSports, intervalMs: 1800000, maxAgeMs: 64800000, retentionMs: 259200000 });
