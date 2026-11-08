import { useState } from 'preact/hooks';
import { externalPanel } from '../../shared/external/resource';
import { Frame, Tabs, valid, s, n, type CulturePayload } from '../../shared/culture-tech';

function Body({ data }: { data?: CulturePayload }) {
  const [stage,setStage]=useState('New releases');
  const rows=(data?.items||[]).filter(r=>stage==='New releases'?r.stage==='New release listing':r.stage==='Coming soon listing');
  return <Frame id="product-release-watch" title="PRODUCT & GAME RELEASES" data={data}>
    <div className="wm-ct-scope"><b>STEAM · US STOREFRONT</b><span>Public release listings</span></div>
    <Tabs values={['New releases','Coming soon']} value={stage} onChange={setStage}/>
    {rows.map(r=><article className="wm-ct-paper" key={r.id}><small>APP {r.id}</small><h3>{r.title}</h3><div className="wm-ct-row-title"><span className="wm-ct-value">{n(r.priceMinor)!==null?`${s(r.currency)} ${((n(r.priceMinor)||0)/100).toFixed(2)}`:'Price unpublished'}</span><small>{s(r.stage)}</small></div><div className="wm-ct-tags">{r.windows&&<span>Windows</span>}{r.mac&&<span>macOS</span>}{r.linux&&<span>Linux</span>}</div></article>)}
    <p className="wm-ct-note">Storefront appearance does not establish full-release / 1.0 status.</p>
  </Frame>;
}
export const panel = externalPanel<CulturePayload>({ id: "product-release-watch", title: "PRODUCT & GAME RELEASES", description: "Published external evidence with explicit source coverage.", validate: valid, render: data => <Body data={data}/>, intervalMs: 600000, maxAgeMs: 10800000 });
