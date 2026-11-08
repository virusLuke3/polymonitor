import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs, valid, n, num, compact, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [metric,setMetric]=useState('Weekend');
  const rows=data?.items || [], top=rows[0], field=metric==='Weekend'?'gross':'totalGross';
  const max=Math.max(1,...rows.map(r=>n(r[field])||0));
  return <Frame id="culture-box-office" title="BOX OFFICE" tone="orange" data={data}>
    <div className="wm-ct-scope"><b>BFI · UK · GBP</b><span>{data?.period}</span></div>
    {top&&<div className="wm-ct-hero"><small>WEEKEND LEADER</small><h3>{top.title}</h3><strong>£{compact(top.gross)}</strong><small>{num(top.cinemas)} cinemas · Week {num(top.weeks)}</small></div>}
    <Tabs values={['Weekend','Cumulative']} value={metric} onChange={setMetric}/>
    {rows.slice(0,15).map(r=><div className="wm-ct-row" key={r.id}><div className="wm-ct-row-title"><b>{num(r.rank)}. {r.title}</b><span className="wm-ct-value">£{compact(r[field])}</span></div><div className="wm-ct-bar"><span style={{width:`${(n(r[field])||0)/max*100}%`}}/></div><div className="wm-ct-meta"><span>{num(r.cinemas)} cinemas</span><span>{n(r.change)===null?'New / no comparator':`${((n(r.change)||0)*100).toFixed(1)}% vs last week`}</span></div></div>)}
    {data?.documentUrl&&<a className="wm-ct-note" href={data.documentUrl} target="_blank" rel="noreferrer">Original BFI spreadsheet ↗</a>}
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "culture-box-office", title: "BOX OFFICE", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 1800000, maxAgeMs: 86400000, retentionMs: 1209600000 });
