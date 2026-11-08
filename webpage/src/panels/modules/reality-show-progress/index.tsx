import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, EvidenceLink, valid, s, num, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [selected,setSelected]=useState('');
  const rows=data?.items||[], row=rows.find(r=>r.id===selected)||rows[0];
  return <Frame id="reality-show-progress" title="REALITY SHOW PROGRESS" tone="purple" data={data}>
    <div className="wm-ct-scope"><b>TVMAZE · EPISODE SCHEDULE</b><span>CC BY-SA</span></div>
    <div className="wm-ct-hero"><small>LATEST LISTED SEASON</small><h3>{data?.show}</h3><strong>Season {data?.season||'—'}</strong><small>{rows.length} published episodes</small></div>
    <div className="wm-ct-episode-grid">{rows.map(r=><button key={r.id} aria-pressed={r.id===row?.id} onClick={()=>setSelected(r.id)}>E{num(r.episode)}</button>)}</div>
    {row&&<div className="wm-ct-paper"><small>EPISODE {num(row.episode)}</small><h3><EvidenceLink row={row}/></h3><p>{s(row.eventTime).replace('T',' ').slice(0,16)} UTC</p><div className="wm-ct-meta"><span>{num(row.runtime)} minutes</span><span>Elimination unknown</span></div></div>}
    <p className="wm-ct-note">Scheduled episodes are not confirmed eliminations or voting results.</p>
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "reality-show-progress", title: "REALITY SHOW PROGRESS", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 1800000, maxAgeMs: 86400000 });
