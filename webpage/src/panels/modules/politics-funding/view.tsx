import { useState } from 'preact/hooks';
import { Empty, Evidence, Link, Note, Scope, Shell, Tabs, useCopy } from '../../shared/politics/ui';
import { LegislationView } from '../../shared/politics/LegislationView';
import type { Payload } from './model';
const labels=[['农业','Agriculture'],['商贸司法','Commerce/Justice'],['国防','Defense'],['能源水利','Energy/Water'],['金融服务','Financial services'],['国土安全','Homeland security'],['内政环境','Interior'],['劳工教育','Labor/HHS'],['立法部门','Legislative'],['军建退伍军人','Military/VA'],['国务院外交','State'],['交通住房','Transport/HUD']];
export function View({data}:{data?:Payload}) {
 const t=useCopy(),[tab,set]=useState('coverage'),[selected,select]=useState('1'),law=data?.law,clause=law?.coverage.find(r=>r.id===selected);
 return <Shell id="politics-funding" title={t('拨款与停摆','FUNDING DEADLINE')} data={data} explanation={t('跟踪已核实法律 P.L.119-103 的期限条款与 12 类拨款范围。它不是对后续全部立法和实际停摆状态的判定。','Tracks the verified deadline clause and 12 appropriation classes in P.L.119-103. This is not a determination of all subsequent legislation or shutdown status.')}>
  <Scope name={law ? `FY ${law.fiscalYear} · P.L.119-103`:'US · APPROPRIATIONS'} tag={t('所跟踪法律','TRACKED LAW')}/><Tabs values={[[ 'coverage',t('条款范围','Coverage') ],['actions',t('立法行动','Legislation')]]} value={tab} set={set}/>
  {tab==='actions' ? <LegislationView data={data}/> : law?.expirationDate ? <><div className="pol-deadline"><span>{t('第 106 条最晚日期','Section 106 latest date')}</span><strong>{law.expirationDate}</strong><span>{t('更早通过适用拨款时可提前结束；原文仅提供日期','May end earlier when applicable appropriations are enacted; date-only source')}</span></div>
   <div className="pol-appropriations">{law.coverage.map((c,i)=><button key={c.id} type="button" className="pol-amber" aria-pressed={selected===c.id} onClick={()=>select(c.id)}>{t(labels[i]?.[0]||c.id,labels[i]?.[1]||c.id)}<small>{t('第 101 条','Section 101')}</small></button>)}</div>
   <Note>{t('后续修法与逐机构当前覆盖尚待核验；不据此宣布停摆，也不虚构精确时刻。','Subsequent laws and current agency-level coverage remain unverified. No shutdown declaration or exact deadline time is inferred.')}</Note>
   {clause&&<p>{clause.text}</p>}<Evidence><p>{law.expirationClause}</p><Link href={law.url}>{t('官方法律原文','Official law text')}</Link><p>{t('12 类常规拨款不是 12 个部门。OMB 预案不等于停摆执行通知。','The 12 appropriation classes are not 12 departments. OMB plans are not shutdown execution notices.')}</p></Evidence>
  </> : <Empty>{t('尚无已核实的拨款法律条款。','Verified funding provisions unavailable.')}</Empty>}
 </Shell>;
}
