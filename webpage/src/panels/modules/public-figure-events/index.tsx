import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, EvidenceLink, valid, s, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [speaker,setSpeaker]=useState('All speakers');
  const speakers=['All speakers',...new Set((data?.items||[]).map(r=>s(r.speaker)).filter(Boolean))];
  const rows=(data?.items||[]).filter(r=>speaker==='All speakers'||r.speaker===speaker);
  return <Frame id="public-figure-events" title="PUBLIC FIGURE EVENTS" tone="blue" data={data}>
    <div className="wm-ct-scope"><b>FED OFFICIALS · PUBLISHED REMARKS</b></div>
    <select aria-label="Public speaker" value={speaker} onChange={e=>setSpeaker(e.currentTarget.value)}>{speakers.map(v=><option key={v}>{v}</option>)}</select>
    {rows.map(r=><article className="wm-ct-date-row" key={r.id}><time><b>{s(r.publishedAt).slice(8,10)}</b>{s(r.publishedAt).slice(0,7)}</time><div><small>{s(r.speaker)||'Official speaker'}</small><h3><EvidenceLink row={r}/></h3><div className="wm-ct-tags"><span>Published official text</span></div></div></article>)}
    <p className="wm-ct-note">This source covers Fed officials; other public figures are not yet covered.</p>
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "public-figure-events", title: "PUBLIC FIGURE EVENTS", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 600000, maxAgeMs: 10800000 });
