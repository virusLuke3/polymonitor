import { useState } from 'preact/hooks';
import { Bar, Empty, Evidence, Note, Scope, Shell, Stat, Tabs, useCopy } from '../../shared/politics/ui';
import { num, partyTone } from '../../shared/politics/model';
import type { Payload } from './model';
export function View({data}:{data?:Payload}) {
 const t=useCopy(), [tab,set]=useState('primary'), [selected,select]=useState(''), rows=data?.items || [], race=rows.find(r=>r.id===selected)||rows[0], total=race?.choices.reduce((n,c)=>n+c.votes,0)||0;
 return <Shell id="politics-nomination" title={t('提名路径','NOMINATION PATH')} data={data} explanation={t('北卡联邦职位初选票数。初选与总统党代会代表票是不同规则，不能互相替代。','North Carolina federal primaries. Primary vote counts and presidential convention delegates have different rules.')}>
  <Scope name="US · NORTH CAROLINA" tag="2026 PRIMARY"/><Tabs values={[[ 'primary',t('初选票数','Primary votes') ],['delegates',t('代表票','Delegates')]]} value={tab} set={set}/>
  {tab==='delegates' ? <><div className="pol-delegate"><Stat label={t('已分配代表票','Allocated delegates')} value="—" tone="purple"/><Stat label={t('本届党规门槛','Convention threshold')} value="—" tone="amber"/></div><Empty>{t('尚无已核实的党代会规则和代表票来源；不会把候选人备案或初选票数填入代表票。','Verified convention rules and delegate allocations are not connected. Candidate filings and primary votes do not substitute for delegates.')}</Empty></> : race ? <><select aria-label={t('初选场次','Primary contest')} value={race.id} onChange={e=>select(e.currentTarget.value)}>{rows.map(r=><option key={r.id} value={r.id}>{r.title} · {r.choices[0]?.party}</option>)}</select><div className="pol-delegate"><Stat label={race.choices[0]?.name || ''} value={num(race.choices[0]?.votes)} tone={partyTone(race.choices[0]?.party || '')}/><div><b className="pol-amber">{race.electionDate}</b><span>{t('初选日','Primary date')}</span></div></div>{race.choices.map(c=><Bar key={c.name} label={c.name} value={num(c.votes)} percent={total?c.votes/total*100:null} tone={partyTone(c.party)}/>)}<Note tone="purple">{t('已发布票数；不据此宣布正式获得提名。','Published votes; formal nomination is not inferred.')}</Note></> : <Empty>{t('尚无初选统计。','Primary statistics unavailable.')}</Empty>}
  <Evidence>{t('当前覆盖北卡 2026 联邦职位初选。未覆盖背书、退选、代表票分配、党代会日程与正式提名事件。','Covers NC 2026 federal primaries. Endorsements, withdrawals, delegate allocation, convention schedules and formal nomination events remain uncovered.')}</Evidence>
 </Shell>;
}
