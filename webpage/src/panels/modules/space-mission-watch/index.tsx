import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, EvidenceLink, valid, s, date, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [selected,setSelected]=useState('');
  const rows=data?.items||[], row=rows.find(r=>r.id===selected)||rows[0];
  return <Frame id="space-mission-watch" title="SPACE MISSIONS" data={data}>
    <div className="wm-ct-scope"><b>LAUNCH LIBRARY 2</b><span>Source-reported status</span></div>
    <select aria-label="Launch mission" value={row?.id} onChange={e=>setSelected(e.currentTarget.value)}>{rows.map(r=><option key={r.id} value={r.id}>{r.title}</option>)}</select>
    {row&&<><div className="wm-ct-hero"><small>{s(row.operator)}</small><h3>{row.title}</h3><strong>{s(row.status)}</strong><small>{s(row.statusDescription)}</small></div><div className="wm-ct-row"><b>Published launch window · UTC</b><p>{s(row.windowStart).replace('T',' ').slice(0,16)} → {s(row.windowEnd).replace('T',' ').slice(0,16)}</p><small>NET precision: {s(row.precision)||'unknown'}</small></div><div className="wm-ct-tags"><span>{s(row.location)}</span>{s(row.orbit)&&<span>{s(row.orbit)}</span>}</div><p>{s(row.mission)}</p><div className="wm-ct-meta"><span>Updated {date(row.publishedAt)}</span><EvidenceLink row={row}>Source record</EvidenceLink></div></>}
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "space-mission-watch", title: "SPACE MISSIONS", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 600000, maxAgeMs: 10800000 });
