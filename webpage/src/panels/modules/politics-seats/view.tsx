import { useState } from 'preact/hooks';
import { Empty, Evidence, Link, Note, Scope, Shell, Stat, useCopy } from '../../shared/politics/ui';
import { num, partyTone } from '../../shared/politics/model';
import type { House as Payload } from '../../shared/politics/model';
export function View({data}:{data?:Payload}) {
 const t=useCopy(),[selected,set]=useState(''), seats=data?.items||[], seat=seats.find(r=>r.id===selected), counts=data?.counts || {};
 return <Shell id="politics-seats" title={t('议席格局','SEAT BALANCE')} data={data} explanation={t('美国众议院 Clerk 现任名单，排除无表决权代表。每格一个原生席位 ID；不是当届开票预测。','US House Clerk current membership, excluding nonvoting delegates. Each cell is a seat, not a current election call.')}>
  <Scope name={t('美国众议院 · 现任','US HOUSE · CURRENT')} tag={data?.congress ? `${data.congress} CONGRESS`:undefined}/>
  {seats.length ? <><div className="pol-stats"><Stat label={t('民主党','Democratic')} value={num(counts.D)} tone={partyTone('D')}/><Stat label={t('共和党','Republican')} value={num(counts.R)} tone={partyTone('R')}/><Stat label={t('名册席位','Roster seats')} value={num(seats.length)} tone="muted"/></div>
    <div className="pol-seat-grid" aria-label={t('现任众议院席位','Current House seats')}>{seats.map(s=><button type="button" key={s.id} className={`pol-${partyTone(s.party)}`} aria-label={`${s.id} ${s.name||'Vacant'} ${s.party}`} aria-pressed={selected===s.id} onClick={()=>set(s.id)}/>)}</div>
    <label className="pol-seat-picker">{t('选择席位','Select seat')}<select value={selected} onChange={e=>set(e.currentTarget.value)}><option value="">—</option>{seats.map(s=><option key={s.id} value={s.id}>{s.id} · {s.name}</option>)}</select></label>
    {seat && <Note tone={partyTone(seat.party)}><strong>{seat.id} · {seat.name||t('空缺','Vacant')}</strong><span>{seat.party} · {seat.sworn || t('就职时间未提供','No sworn date')}</span><Link href={seat.url}>{t('官方成员页','Official member')}</Link></Note>}
    <div className="pol-small">{data?.publishedAt} · {t('每格一席，非地理地图','One cell per seat, not a map')}</div>
    <Evidence>{t('现任名单可能属于上一轮选举产生的国会，不是 2026 年选举的已判定席位；缺认证、重计票及选区边界版本时不画历史胜率。','Current membership may be from the previous election; it is not a tally of 2026 race calls. Certification, recounts and boundary versions are not inferred.')}</Evidence>
  </> : <Empty>{t('尚未取得现任成员表。','Current membership unavailable.')}</Empty>}
 </Shell>;
}
