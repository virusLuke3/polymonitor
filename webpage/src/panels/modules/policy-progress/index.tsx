import { useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchOfficialDisclosures } from '@/services/api';
import { runtimePanelFromRenderer } from '../../definePanel';
import { contract, date, DisclosureControls, SourceNotice, useCopy } from '../../shared/official-disclosures';
import { category, nextMilestone, validPolicyPayload, type PolicyPayload } from './model';
import './styles.css';

function PolicyProgress({ data }: { data?: PolicyPayload }) {
  const t = useCopy(), [filter, setFilter] = useState('all');
  const items = data?.items || [], today = new Date().toISOString().slice(0,10);
  const upcoming = nextMilestone(items, today), visible = items.filter(item => filter === 'all' || category(item.type) === filter);
  const typeLabel = (type: string) => type === 'Rule' ? t('规则', 'RULE') : type === 'Proposed Rule' ? t('提案', 'PROPOSAL') : type === 'Presidential Document' ? t('总统文件', 'PRESIDENTIAL') : t('通知', 'NOTICE');
  return <Panel title={t('政策进程', 'POLICY PROGRESS')} dataPanelId="policy-progress" className="wm-policy-progress" controls={<DisclosureControls>
    <p>{t('美国 Federal Register · 最近30天，最多100份已发布文件。此视图不覆盖国会立法进程。', 'US Federal Register · Up to 100 published documents from the last 30 days. This view does not cover congressional legislation.')}</p>
    <p>{t('网页为阅读版；正式文件见每条 GovInfo PDF。截止日和生效日仅使用来源字段。', 'Web pages are the reading edition; use each GovInfo PDF for the official document. Milestone dates come from the source.')}</p>
    <p>{t('最近取得', 'Last acquired')}: {data?.source.lastSuccessAt || '—'}</p>
    <p>{items.length} / {data?.availableCount ?? '—'} {t('窗口内文件', 'documents in source window')}</p>
  </DisclosureControls>}>
    <div className="wm-policy-body">
      <div className="wm-policy-scope"><span>US</span><b>FEDERAL REGISTER</b><small>{t('监管公告', 'REGULATORY RECORD')}</small></div>
      <SourceNotice source={data?.source}/>
      {upcoming && <a className="wm-policy-next" href={upcoming.item.url} target="_blank" rel="noreferrer"><div><span>{upcoming.kind === 'comments' ? t('本批次下个意见截止日', 'NEXT IN THIS BATCH · COMMENTS') : t('本批次下个生效日', 'NEXT IN THIS BATCH · EFFECTIVE')}</span><strong>{upcoming.date.slice(5)}</strong><small>{upcoming.date.slice(0,4)}</small></div><p>{upcoming.item.title}</p></a>}
      <div className="wm-panel-tabs">{[['all',t('全部', 'All')],['rule',t('规则','Rules')],['proposal',t('提案','Proposals')],['notice',t('通知','Notices')]].map(([id,label]) => <button key={id} aria-pressed={filter === id} onClick={() => setFilter(id!)}>{label}</button>)}</div>
      {visible.slice(0,40).map(row => <article className={`wm-policy-document kind-${category(row.type)}`} key={row.id}>
        <div className="wm-policy-meta"><b>{typeLabel(row.type)}</b><time dateTime={row.publishedAt}>{date(row.publishedAt)}</time></div>
        <a href={row.url} target="_blank" rel="noreferrer">{row.title}</a>
        <p>{row.agencies.join(' · ')}</p>
        {(row.commentsCloseOn || row.effectiveOn) && <div className="wm-policy-milestones"><span>● {t('公布', 'Published')}</span>{row.commentsCloseOn && <span>{t('意见截止', 'Comments close')} <b>{row.commentsCloseOn}</b></span>}{row.effectiveOn && <span>{row.effectiveOn <= today ? t('已到生效日', 'Effective date reached') : t('待生效', 'Effective from')} <b>{row.effectiveOn}</b></span>}</div>}
        {row.pdfUrl && <a className="wm-policy-pdf" href={row.pdfUrl} target="_blank" rel="noreferrer">{row.id} · {t('正式 PDF', 'Official PDF')} ↗</a>}
      </article>)}
      {!visible.length && <p>{t('当前筛选下暂无已取得的公告。', 'No acquired documents match this view.')}</p>}
      {visible.length > 40 && <p>{t('显示最近40份；其余文件见来源。', 'Showing the latest 40; further documents are available at the source.')}</p>}
    </div>
  </Panel>;
}
export const panel = runtimePanelFromRenderer({ 'policy-progress': { render: ctx => <PolicyProgress data={ctx.runtimeData['policy-progress'] as PolicyPayload | undefined}/> } }, {
  id: 'policy-progress', dataSourceId: 'policy-progress', title: 'Policy Progress', eyebrow: 'macro', description: 'US regulatory documents, comment deadlines and effective dates.', defaultEnabled: true,
  snapshot: contract('policy-progress', validPolicyPayload),
}, { tier: 'slow', intervalMs: 600000, staleAfterMs: 86400000, requestTimeoutMs: 15000, retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 },
  fetchData: context => fetchOfficialDisclosures('policy-progress', context?.signal) });
