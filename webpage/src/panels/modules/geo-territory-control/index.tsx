import {useState} from 'preact/hooks';
import {externalPanel} from '../../shared/external/resource';
import {Frame} from '../../shared/external/ui';
import {validateGeo,type GeoPayload} from '../../shared/geo-expansion/model';
import {Evidence} from '../../shared/geo-expansion/ui';
import './style.css';
function View({data}:{data?:GeoPayload}){const[query,setQuery]=useState('');const rows=data?.items?.filter(r=>(r.title+' '+r.summary).toLowerCase().includes(query.toLowerCase()));return <Frame data={data} className="gx-territory"><div className="gx-territory-verdict"><b>Territorial claims ledger</b><span>Control is not established by a statement</span></div><input aria-label="Filter territorial statements" placeholder="Filter places or claims" value={query} onInput={e=>setQuery(e.currentTarget.value)}/>{rows?.map(r=><article key={r.id}><h3>{r.title}</h3><div className="gx-territory-matrix"><div><small>Claim / publication</small><b>{r.claim_source}</b></div><div><small>Independent control verification</small><b>Not established</b></div></div><p>{r.summary}</p><Evidence row={r}/></article>)}{rows?.length===0&&<p>No matching claims in the acquired window.</p>}<p className="external-evidence-note">No control polygons or percentage are inferred. Official legal positions, reported occupation and on-the-ground control are distinct.</p></Frame>;}
export const panel=externalPanel({id:'geo-territory-control',title:'Territorial Claims',description:'Public territorial claims and explicit verification boundaries.',render:data=><View data={data}/>,validate:validateGeo});
