import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs, EvidenceLink, valid, s, n, num, date, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [view,setView]=useState('Recent');
  const rows=[...(data?.items||[])]; if(view==='Cited')rows.sort((a,b)=>(n(b.citations)||0)-(n(a.citations)||0));
  return <Frame id="research-evidence-watch" title="RESEARCH EVIDENCE" tone="blue" data={data}>
    <div className="wm-ct-scope"><b>CROSSREF · AI RESEARCH</b><span>Registered DOI metadata</span></div>
    <Tabs values={['Recent','Cited']} value={view} onChange={setView}/>
    {rows.map(r=><article className="wm-ct-paper" key={r.id}><div className="wm-ct-meta"><span>{date(r.publishedAt)}</span><span>{s(r.kind)}</span></div><h3><EvidenceLink row={r}/></h3><small>{s(r.journal)||s(r.publisher)}</small><div className="wm-ct-meta"><span>DOI {r.id}</span><span>{num(r.citations)} indexed citations</span></div></article>)}
    <p className="wm-ct-note">Publication metadata does not verify a breakthrough or clinical result.</p>
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "research-evidence-watch", title: "RESEARCH EVIDENCE", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 1800000, maxAgeMs: 86400000 });
