import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, EvidenceLink, valid, s, date, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [city,setCity]=useState('All locations');
  const cities=['All locations',...new Set((data?.items||[]).map(r=>s(r.location)))];
  const rows=(data?.items||[]).filter(r=>city==='All locations'||r.location===city);
  return <Frame id="art-auction-watch" title="ART AUCTION CALENDAR" tone="amber" data={data}>
    <div className="wm-ct-scope"><b>CHRISTIE’S · OFFICIAL SALES</b><span>{rows.length} listed</span></div>
    <select aria-label="Auction location" value={city} onChange={e=>setCity(e.currentTarget.value)}>{cities.map(c=><option key={c}>{c}</option>)}</select>
    {rows.map(r=><article className="wm-ct-date-row" key={r.id}><time><b>{s(r.eventTime).slice(8,10)||'—'}</b>{s(r.eventTime).slice(0,7)}</time><div><h3><EvidenceLink row={r}/></h3><div className="wm-ct-tags"><span>{s(r.location)}</span><span>Announced sale</span></div>{r.endDate!==r.eventTime&&<small>Through {date(r.endDate)}</small>}</div></article>)}
    <p className="wm-ct-note">Lot estimates and hammer results not in this calendar.</p>
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "art-auction-watch", title: "ART AUCTION CALENDAR", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 1800000, maxAgeMs: 86400000 });
