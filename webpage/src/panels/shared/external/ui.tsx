import type { ComponentChildren } from 'preact';
import type { BasePayload } from './resource';
import './style.css';
export const fmt = (v: number | null | undefined, digits=1) => v == null ? '—' : v.toLocaleString('en-US', { maximumFractionDigits: digits });
export function Frame({data, children, className=''}:{data?:BasePayload;children?:ComponentChildren;className?:string}) {
 return <div className={`external-evidence ${className}`}>{!data ? <p className="external-evidence-note">Loading source records…</p> : <>{data.status==='unavailable' ? <p className="external-evidence-note">Source records are unavailable. Refresh retains valid previous data within its retention limit.</p> : children}<p className="external-evidence-note">{data.coverage}</p><details><summary>Sources & timestamps</summary>{data.sources.map(s=><p key={s.id}><b>{s.label??s.id}</b><br/>{s.lastSuccessAt??'No successful acquisition'}{s.stale?' · retained':''}{s.error?` · ${s.error}`:''}</p>)}</details></>}</div>;
}
export function Tabs({values,value,onChange}:{values:string[];value:string;onChange:(s:string)=>void}) {return <div className="external-evidence-tabs">{values.map(v=><button key={v} type="button" aria-pressed={v===value} onClick={()=>onChange(v)}>{v}</button>)}</div>;}
