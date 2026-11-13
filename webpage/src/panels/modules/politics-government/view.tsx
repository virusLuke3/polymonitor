import { Evidence, Empty, Note, Row, Scope, Shell, useCopy } from '../../shared/politics/ui';
import { num, partyTone } from '../../shared/politics/model';
import type { House as Payload } from '../../shared/politics/model';
export function View({data}:{data?:Payload}) {
 const t=useCopy(), counts=data?.counts||{}, total=Object.values(counts).reduce((a,b)=>a+b,0), majority=data?.majority, label=majority==='R'?t('共和党','Republican'):majority==='D'?t('民主党','Democratic'):majority||'—';
 return <Shell id="politics-government" title={t('政府控制权','GOVERNMENT CONTROL')} data={data} explanation={t('美国众议院现任多数党：采用 Clerk 官方多数/少数记录。当前仅覆盖美国众院，不能套用议会制联盟组阁规则。','Current US House majority follows the Clerk’s majority/minority record. Coverage is the US House, not worldwide coalition formation.')}>
  <Scope name={t('美国众议院 · 现任控制权','US HOUSE · CURRENT CONTROL')} tag={data?.congress ? `${data.congress} CONGRESS`:undefined}/>
  {total ? <><div className={`pol-hero pol-${partyTone(majority || '')}`}><span>{t('官方名册标记的多数党','Majority identified by official roster')}</span><strong>{label}</strong><span>{majority ? num(counts[majority]):'—'} / {total} {t('名册席位','roster seats')}</span></div>
   <div className="pol-coalition">{Object.entries(counts).map(([p,n])=><div key={p} className={`pol-${partyTone(p)}`} style={{flex:n}} title={`${p}: ${n}`}>{n>15?`${p} ${n}`:n}</div>)}</div>
   <Note tone="purple">{t('当前组成与新一届选举控制权分开。','Current composition is distinct from control after the new election.')}</Note>
   <Row label={t('名册发布日期','Roster publication')} value={data?.publishedAt || '—'}/><Row label={t('联盟 / 信任投票','Coalition / confidence vote')} value={t('不适用此美国众院视图','Not this US House scope')}/>
   <Evidence>{t('议长实际选举票、党团变化事件和新一届组成仍需单独记录。英国等议会制国家的联盟协议、信任投票、任命和就职尚未接入，不能用党派席位推断这些事件。','Speaker ballots, caucus-change events and the next Congress require separate records. Parliamentary coalition agreements, confidence votes and appointments for other countries are not inferred from these seat totals.')}</Evidence>
  </> : <Empty>{t('官方现任控制权记录尚不可用。','Official current control record unavailable.')}</Empty>}
 </Shell>;
}
