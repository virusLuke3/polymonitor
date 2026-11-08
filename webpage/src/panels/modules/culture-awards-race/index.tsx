import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs, EvidenceLink, valid, s, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [view,setView]=useState('All announcements');
  const rows=(data?.items||[]).filter(r=>view==='All announcements'||/nominat|winn|award|rule/i.test(r.title));
  return <Frame id="culture-awards-race" title="CULTURE AWARDS" tone="amber" data={data}>
    <div className="wm-ct-scope"><b>GOLDEN GLOBES · OFFICIAL</b></div>
    <div className="wm-ct-hero"><small>AWARDS EVIDENCE DESK</small><h3>Announcements & ceremony updates</h3><span>Read the original decision before assigning outcome.</span></div>
    <Tabs values={['All announcements','Award topics']} value={view} onChange={setView}/>
    {rows.map(r=><article className="wm-ct-date-row" key={r.id}><time><b>{s(r.publishedAt).slice(8,10)}</b>{s(r.publishedAt).slice(0,7)}</time><div><h3><EvidenceLink row={r}/></h3><div className="wm-ct-tags"><span>Official publication</span></div></div></article>)}
    <p className="wm-ct-note">Structured nominee ballots, precursors and winner probabilities are not provided by this feed.</p>
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "culture-awards-race", title: "CULTURE AWARDS", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 1800000, maxAgeMs: 86400000 });
