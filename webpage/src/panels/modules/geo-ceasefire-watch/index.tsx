import {useState} from 'preact/hooks';
import {externalPanel} from '../../shared/external/resource';
import {Frame} from '../../shared/external/ui';
import {validateGeo,type GeoPayload} from '../../shared/geo-expansion/model';
import {Evidence} from '../../shared/geo-expansion/ui';
import './style.css';
function View({data}:{data?:GeoPayload}){const[i,setI]=useState(0),row=data?.items?.[i]??data?.items?.[0];return <Frame data={data} className="gx-ceasefire"><h3>Ceasefire & negotiation statements</h3><select aria-label="Ceasefire statement" value={i} onChange={e=>setI(Number(e.currentTarget.value))}>{data?.items?.map((r,n)=><option key={r.id} value={n}>{r.title}</option>)}</select>{row?<><div className="gx-ceasefire-stage"><b>PUBLICATION VERIFIED</b><h3>{row.title}</h3><small>{row.reported_time?.slice(0,10)} · {row.claim_source}</small></div><ol className="gx-ceasefire-rail">{['Proposal','Acceptance','Signed text','Effective','Observed compliance'].map(s=><li key={s}><i/><strong>{s}</strong><span>Not independently established</span></li>)}</ol><p>{row.summary}</p><Evidence row={row}/><p className="external-evidence-note">A statement mentioning a ceasefire is not evidence that all parties signed, that it entered into force, or that fighting stopped.</p></>:<p>No matching statements in the acquired window.</p>}</Frame>;}
export const panel=externalPanel({id:'geo-ceasefire-watch',title:'Ceasefire Watch',description:'Negotiation statements with separate legal and execution evidence.',render:data=><View data={data}/>,validate:validateGeo});
