import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs, valid, s, n, num, date, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [size, setSize] = useState('Top 10');
  const rows = (data?.items || []).slice(0, size === 'Top 10' ? 10 : 30);
  const low = Math.floor(Math.min(...rows.map(r => n(r.lower) ?? n(r.score) ?? 0)) / 20) * 20;
  const high = Math.ceil(Math.max(...rows.map(r => n(r.upper) ?? n(r.score) ?? 0)) / 20) * 20;
  const scale = (v: unknown) => Math.max(0, Math.min(100, ((n(v) ?? low) - low) / Math.max(1, high - low) * 100));
  return <Frame id="ai-leaderboard-watch" title="AI LEADERBOARD" tone="purple" data={data}>
    <div className="wm-ct-scope"><b>ARENA · TEXT / OVERALL</b><span>{date(data?.publishedAt)}</span></div>
    <Tabs values={['Top 10', 'Top 30']} value={size} onChange={setSize}/>
    <p className="wm-ct-note">Raw scores · 95% score interval · not style controlled</p>
    {rows.map(r => <div className="wm-ct-rank-row" key={r.id}><span className="wm-ct-rank">{num(r.rank)}</span><div><b>{r.title}</b><div className="wm-ct-rating"><span style={{ left: `${scale(r.lower)}%`, width: `${scale(r.upper)-scale(r.lower)}%` }}/><i style={{ left: `${scale(r.score)}%` }}/></div><small>{s(r.organization)} · {num(r.votes)} votes</small></div><span className="wm-ct-value">{num(r.score)}</span></div>)}
    <div className="wm-ct-meta"><span>{Number.isFinite(low) ? low : '—'}</span><span>Shared rating scale</span><span>{Number.isFinite(high) ? high : '—'}</span></div>
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "ai-leaderboard-watch", title: "AI LEADERBOARD", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 1800000, maxAgeMs: 86400000 });
