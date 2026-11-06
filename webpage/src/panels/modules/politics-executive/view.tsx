import { useState } from 'preact/hooks';
import { Empty, Evidence, Link, Note, Scope, Shell, Tabs, useCopy } from '../../shared/politics/ui';
import type { Payload } from './model';
export function View({data}:{data?:Payload}) {
 const t=useCopy(),[selected,set]=useState(''),[tab,setTab]=useState('timeline'),rows=data?.items||[],row=rows.find(r=>r.id===selected)||rows[0];
 return <Shell id="politics-executive" title={t('行政命令','EXECUTIVE ACTIONS')} data={data} explanation={t('复用 Federal Register 采集拥有者，保留总统文件类型和原生编号。签署、公布、生效分开。','Reuses the Federal Register owner. Presidential document types, signing, publication and effective dates remain distinct.')}>
  {row ? <><Scope name={row.executiveOrderNumber?`EO ${row.executiveOrderNumber}`:row.id} tag={row.subtype||t('总统文件','Presidential document')}/><select aria-label={t('选择总统文件','Select presidential document')} value={row.id} onChange={e=>set(e.currentTarget.value)}>{rows.map(r=><option key={r.id} value={r.id}>{r.publishedAt} · {r.title}</option>)}</select><div className="pol-document-title"><span className="pol-orange">{row.subtype}</span><strong>{row.title}</strong></div>
   <Tabs values={[[ 'timeline',t('时间线','Timeline') ],['changes',t('效力记录','Legal effect')]]} value={tab} set={setTab}/>
   {tab==='timeline' ? <div className="pol-doc-dates"><div><span>{t('签署','Signed')}</span><b>{row.signingDate||'—'}</b></div><div><span>{t('公布','Published')}</span><b>{row.publishedAt}</b></div><div className="pol-orange"><span>{t('生效','Effective')}</span><b>{row.effectiveOn||'—'}</b></div></div> : <Note tone="orange">{row.executiveOrderNotes||t('来源没有提供完整的修订、撤销或法院暂停执行记录；不能据此判定当前全部条款效力。','No complete amendment, revocation or judicial-stay record is provided; current effect of all provisions is unverified.')}</Note>}
   <Evidence><p><Link href={row.url}>{t('Federal Register 阅读版','Federal Register reading edition')}</Link></p><p><Link href={row.pdfUrl}>{t('GovInfo 正式 PDF','GovInfo official PDF')}</Link> · <Link href={row.textUrl}>{t('正文','Text')}</Link></p><p>{rows.length}/{data?.availableCount ?? '—'} · {t('最近 90 天总统文件；空生效日不等于立即生效。','Presidential documents from the last 90 days. Missing effective date does not mean immediate effect.')}</p></Evidence>
  </> : <Empty>{t('尚未取得总统文件记录。','Presidential documents unavailable.')}</Empty>}
 </Shell>;
}
