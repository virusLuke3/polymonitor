import { useState } from 'preact/hooks';
import { Bar, Empty, Evidence, Link, Row, Scope, Shell, Stat, Tabs, useCopy } from '../../shared/politics/ui';
import { money } from '../../shared/politics/model';
import type { Payload } from './model';
export function View({data}:{data?:Payload}) {
 const t=useCopy(),[tab,set]=useState('candidate'),[selected,select]=useState(''),rows=data?.items||[],row=rows.find(r=>r.id===selected)||rows[0],max=row?Math.max(row.receipts||0,row.spending||0):0;
 return <Shell id="politics-campaign-finance" title={t('竞选资金','CAMPAIGN FINANCE')} data={data} explanation={t('FEC all-candidates 财务汇总；不同候选人报告截止日可能不同。保留转入、转出，避免将汇总直接当作净筹款。','FEC all-candidates financial summaries. Coverage dates differ across candidates; transfers remain explicit.')}>
  <Scope name="US · FEC" tag={data?.cycle}/><Tabs values={[[ 'candidate',t('候选人','Candidates') ],['independent',t('独立支出','Independent')]]} value={tab} set={set}/>
  {tab==='independent' ? <Empty>{t('尚未接入独立支出逐笔数据；候选人支出不会被当作独立支出。OpenFEC 密钥配置后可扩展该链路。','Independent-expenditure transactions are not connected. Candidate spending is not independent spending; the OpenFEC credential extension remains available.')}</Empty> : row ? <>
   <select aria-label={t('选择候选人','Select candidate')} value={row.id} onChange={e=>select(e.currentTarget.value)}>{rows.map(r=><option key={r.id} value={r.id}>{r.state} · {r.name} · {r.periodEnd||'—'}</option>)}</select>
   <div className="pol-finance-head"><Stat label={t('报告筹款','Reported receipts')} value={money(row.receipts)} tone="orange"/><Stat label={t('报告支出','Reported disbursements')} value={money(row.spending)} tone="cyan"/></div>
   <Bar label={t('筹款 · USD','Receipts · USD')} value={money(row.receipts)} percent={row.receipts!==null&&max?row.receipts/max*100:null} tone="orange"/><Bar label={t('支出 · USD','Disbursements · USD')} value={money(row.spending)} percent={row.spending!==null&&max?row.spending/max*100:null} tone="cyan"/>
   <Row label={t('期末现金 / 债务','Cash / debt')} value={`${money(row.cash)} / ${money(row.debt)}`} tone="orange"/><Row label={t('授权委员会转入 / 转出','Authorized transfers in / out')} value={`${money(row.transfersIn)} / ${money(row.transfersOut)}`}/><Row label={t('报告截至','Coverage through')} value={row.periodEnd||'—'}/>
   <Evidence><Link href={row.url}>{row.id} · {t('原始申报','Original filings')}</Link><p>{t('这里只展示按筹款排序的前 200 名候选人。源文件记录数','Shows the top 200 candidates by reported receipts. Source records')}: {data?.availableCount}</p><p>{t('跨委员会转账可能重复计入总额；不能跨不同截止日直接排名表现。当前归档源文件版本，尚未取得逐笔申报修订链。','Intercommittee transfers may double count activity. Coverage periods must match before comparisons. File versions are archived; filing-level amendment chains remain unavailable.')}</p></Evidence>
  </> : <Empty>{t('尚未取得财务汇总。','Financial summary unavailable.')}</Empty>}
 </Shell>;
}
