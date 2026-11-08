import { isBasePayload, record, type BasePayload } from '../external/resource';
export type Claim = {id:string;title:string;summary:string;url:string;claim_source:string;reported_time:string|null;event_time:string|null;geographic_scope:string|null;independent_confirmation_count:number|null;verification_status:string};
export type GeoPayload=BasePayload & {items?:Claim[];historical?:{id:string;headline:string;country:string;occurredAt:string;source:string;sideA:string;sideB:string;deathsBest:number|null;deathsLow:number|null;deathsHigh:number|null}[];treaty?:{title:string;signatories:number;parties:number;statusAt:string|null;participants:{country:string;signature:string|null;deposit:string|null}[];scope:string;url:string}|null};
export function validateGeo(v:unknown):v is GeoPayload {
 if(!record(v)||!isBasePayload(v))return false;
 const r=v as Record<string,unknown>;
 if(r.items!==undefined&&(!Array.isArray(r.items)||!r.items.every(x=>record(x)&&typeof x.id==='string'&&typeof x.title==='string'&&typeof x.summary==='string'&&typeof x.url==='string'&&typeof x.claim_source==='string')))return false;
 if(r.historical!==undefined&&(!Array.isArray(r.historical)||!r.historical.every(x=>record(x)&&typeof x.id==='string'&&typeof x.headline==='string')))return false;
 if(r.treaty!==undefined&&r.treaty!==null){const t=r.treaty;if(!record(t)||typeof t.title!=='string'||!Number.isFinite(t.parties)||!Number.isFinite(t.signatories)||!Array.isArray(t.participants)||!t.participants.every(p=>record(p)&&typeof p.country==='string'))return false;}
 return r.items!==undefined||r.treaty!==undefined;
}
