import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs, EvidenceLink, valid, s, num, date, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [view, setView] = useState('Top 10');
  const rows = (data?.items || []).slice(0, view === 'Top 10' ? 10 : 50), top=rows[0];
  return <Frame id="culture-music-charts" title="MUSIC CHARTS" tone="purple" data={data}>
    <div className="wm-ct-scope"><b>APPLE MUSIC · US</b><span>{date(data?.publishedAt)}</span></div>
    {top && <div className="wm-ct-hero"><small>MOST PLAYED · #1</small><h3><EvidenceLink row={top}/></h3><span>{s(top.artist)}</span></div>}
    <Tabs values={['Top 10','Top 50']} value={view} onChange={setView}/>
    {rows.map(r=><div className="wm-ct-rank-row" key={r.id}><span className="wm-ct-rank">{num(r.rank)}</span><div><b><EvidenceLink row={r}/></b><div><small>{s(r.artist)}</small></div></div><small>{s(r.genre)}</small></div>)}
    <p className="wm-ct-note">Chart position only · no stream or sales counts</p>
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "culture-music-charts", title: "MUSIC CHARTS", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 1800000, maxAgeMs: 86400000 });
