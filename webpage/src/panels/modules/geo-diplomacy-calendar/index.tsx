import {useState} from 'preact/hooks';
import {externalPanel} from '../../shared/external/resource';
import {Frame} from '../../shared/external/ui';
import {validateGeo,type GeoPayload} from '../../shared/geo-expansion/model';
import {Evidence} from '../../shared/geo-expansion/ui';
import './style.css';
function View({data}:{data?:GeoPayload}){const[q,setQ]=useState(''),rows=data?.items?.filter(r=>(r.title+' '+r.summary).toLowerCase().includes(q.toLowerCase()));return <Frame id="geo-diplomacy-calendar" title="Diplomacy Calendar" data={data} className="gx-diplomacy"><input aria-label="Filter diplomatic statements" placeholder="Country, leader or meeting" value={q} onInput={e=>setQ(e.currentTarget.value)}/><p className="external-evidence-note">Dates below are publication dates, not confirmed meeting times.</p>{rows?.map(r=><article key={r.id}><aside><b>{r.reported_time?.slice(8,10)??'—'}</b><small>{r.reported_time?.slice(0,7)}</small></aside><section><span className="gx-diplomacy-source">{r.claim_source}</span><h3>{r.title}</h3><p>{r.summary}</p><Evidence row={r}/></section></article>)}{rows?.length===0&&<p>No matching diplomatic publications.</p>}</Frame>;}
export const panel=externalPanel({id:'geo-diplomacy-calendar',title:'Diplomacy Calendar',description:'Official diplomatic publications, plans and readouts with separate event clocks.',render:data=><View data={data}/>,validate:validateGeo});
