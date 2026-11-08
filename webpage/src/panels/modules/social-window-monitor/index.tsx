import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs, valid, s, n, compact, date, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [view,setView]=useState('Recent');
  const rows=[...(data?.items||[])]; if(view==='Most liked')rows.sort((a,b)=>(n(b.likes)||0)-(n(a.likes)||0));
  return <Frame id="social-window-monitor" title="SOCIAL ACTIVITY" data={data}>
    <div className="wm-ct-scope"><b>BLUESKY · CONFIGURED PROFILE</b><span>Recent eligible sample</span></div>
    <Tabs values={['Recent','Most liked']} value={view} onChange={setView}/>
    <p className="wm-ct-note">{rows.length} acquired posts/replies · incomplete time-window coverage</p>
    {rows.map(r=><article className="wm-ct-row" key={r.id}><div className="wm-ct-meta"><b>@{s(r.author)}</b><span>{date(r.publishedAt)}</span></div><p>{r.title}</p><div className="wm-ct-tags"><span>{s(r.kind)}</span><span>{compact(r.likes)} likes</span><span>{compact(r.reposts)} reposts</span><span>{compact(r.replies)} replies</span></div></article>)}
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "social-window-monitor", title: "SOCIAL ACTIVITY", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 600000, maxAgeMs: 10800000, retentionMs: 86400000 });
