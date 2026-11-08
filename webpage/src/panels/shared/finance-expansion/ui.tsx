import type { ComponentChildren } from 'preact';
import { Panel } from '@/components/Panel';
import { DisclosureControls, useCopy } from '../official-disclosures';
import type { BasePayload } from '../external/resource';
import './styles.css';
export { useCopy };
export const money = (n: number | null | undefined) => n == null ? '—' : new Intl.NumberFormat('en-US', { style:'currency',currency:'USD',notation:'compact',maximumFractionDigits:2 }).format(n);
export const date = (v?: string | null) => v?.slice(0,10) ?? '—';
export const finite = (n: unknown): n is number => typeof n === 'number' && Number.isFinite(n);
export const nullableNumber = (n: unknown): n is number | null => n === null || finite(n);
export const safeLink = (u?: string) => !!u && /^https:\/\/[^/@]+\//.test(u);
export function Frame({id,title,data,children}:{id:string;title:string;data?:BasePayload;children:ComponentChildren}) {
 const t=useCopy();
 return <Panel title={title} dataPanelId={id} className="fx-panel" controls={<DisclosureControls><p>{data?.coverage}</p>{data?.sources.map(s=><p key={s.id}>{s.label ?? s.id} · {date(s.lastSuccessAt)}{s.error ? ` · ${s.error}` : ''}{s.stale ? ` · ${t('更新延迟','updates delayed')}`:''}</p>)}</DisclosureControls>}><div className={`fx-body fx-${id}`}>{children}{data?.sources.some(s=>s.error||s.stale) && <p className="fx-note fx-amber">{t('部分来源更新延迟，所示记录保留原始日期。','Some sources are delayed; displayed records retain their original dates.')}</p>}</div></Panel>;
}
export function Tabs({values,value,set}:{values:[string,string][];value:string;set:(v:string)=>void}) {return <div className="fx-tabs">{values.map(([v,l])=><button key={v} aria-pressed={v===value} onClick={()=>set(v)}>{l}</button>)}</div>}
export function Empty({data}:{data?:BasePayload}) {const t=useCopy();return <p className="fx-note">{!data ? t('正在读取已采集数据…','Loading acquired data…') : data.status==='unavailable' ? t('当前来源尚无可用快照。','No usable source snapshot is currently available.') : t('此筛选下没有已取得的记录。','No acquired records match this view.')}</p>}
export function SourceLink({url,children}:{url?:string;children:ComponentChildren}) {return safeLink(url)?<a href={url} target="_blank" rel="noreferrer">{children} ↗</a>:<span>{children}</span>}
