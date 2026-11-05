import { useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchOfficialDisclosures } from '@/services/api';
import { runtimePanelFromRenderer } from '../../definePanel';
import { contract, date, DisclosureControls, SourceNotice, useCopy } from '../../shared/official-disclosures';
import { validCompanyPayload, visibleFilings, type CompanyPayload } from './model';
import './styles.css';

function CompanyEvents({ data }: { data?: CompanyPayload }) {
  const t = useCopy(), [symbol, setSymbol] = useState('AAPL'), [mode, setMode] = useState<'all' | 'reports'>('all');
  const company = data?.companies.find(c => c.symbol === symbol), rows = visibleFilings(company, mode);
  const eps = company?.facts.eps, revenue = company?.facts.revenue;
  return <Panel title={t('公司财报与公告', 'COMPANY EVENTS')} dataPanelId="company-events" className="wm-company-events" controls={<DisclosureControls>
    <p>{t('SEC · 8 家美国上市公司实际披露。不包含分析师预期或下一次财报日。', 'SEC · Actual disclosures for 8 US-listed companies. No consensus estimates or next earnings dates.')}</p>
    <p>{t('披露事实按原始起止报告期展示；修订可能改变历史值。', 'Reported facts retain their exact period; amendments may revise earlier figures.')}</p>
    <p>{t('最近取得', 'Last acquired')}: {company?.sources.filings.lastSuccessAt || '—'}</p>
  </DisclosureControls>}>
    <div className="wm-company-body">
      <div className="wm-panel-tabs" aria-label={t('公司', 'Company')}>{(data?.companies || []).map(c => <button aria-pressed={symbol === c.symbol} onClick={() => setSymbol(c.symbol)} key={c.symbol}>{c.symbol}</button>)}</div>
      {company && <><div className="wm-company-identity"><strong>{company.symbol}</strong><span>{company.filings[0]?.company || company.symbol}</span></div>
        {(eps || revenue) && <div className="wm-company-facts">
          {eps && <div><small>{t('摊薄 EPS · 美元/股', 'DILUTED EPS · USD/SHARE')}</small><strong>{eps.value.toFixed(2)}</strong><span>{eps.start} — {eps.end}</span></div>}
          {revenue && <div><small>{t('营业收入 · 美元', 'REVENUE · USD')}</small><strong>{new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 2 }).format(revenue.value)}</strong><span>{revenue.start} — {revenue.end}</span></div>}
        </div>}
        <SourceNotice source={company.sources.facts}/>
        <div className="wm-panel-tabs"><button aria-pressed={mode === 'all'} onClick={() => setMode('all')}>{t('全部公告', 'All filings')}</button><button aria-pressed={mode === 'reports'} onClick={() => setMode('reports')}>{t('定期报告', 'Reports')}</button></div>
        <SourceNotice source={company.sources.filings}/>
      </>}
      {rows.map(row => <a className={`wm-company-event ${row.form.startsWith('8') ? 'is-current' : 'is-report'}`} key={row.id} href={row.url} target="_blank" rel="noreferrer">
        <time dateTime={row.filed}><b>{row.filed.slice(8,10)}</b><span>{row.filed.slice(0,7)}</span></time>
        <div><strong>{row.form}<em>{row.amendment ? t('修订', 'AMENDED') : row.form.startsWith('8') ? t('临时公告', 'CURRENT REPORT') : t('定期报告', 'PERIODIC REPORT')}</em></strong><p>{t('报告日', 'Report date')} {date(row.period)}</p><small>{row.id} ↗</small></div>
      </a>)}
      {!rows.length && <p>{t('当前筛选下暂无已取得的公告。', 'No acquired filings match this view.')}</p>}
      {(eps || revenue) && <details><summary>{t('财报数值来源', 'Fact evidence')}</summary>{[eps, revenue].filter(Boolean).map(f => <p key={f!.concept}>{f!.concept} · {f!.form} · {t('提交', 'Filed')} {f!.filed} · {f!.accession}</p>)}</details>}
    </div>
  </Panel>;
}
export const panel = runtimePanelFromRenderer({ 'company-events': { render: ctx => <CompanyEvents data={ctx.runtimeData['company-events'] as CompanyPayload | undefined}/> } }, {
  id: 'company-events', title: 'Company Events', eyebrow: 'tech', description: 'Official company reports and disclosures.', defaultEnabled: true,
  snapshot: contract('company-events', validCompanyPayload),
}, { tier: 'slow', intervalMs: 600000, staleAfterMs: 86400000, requestTimeoutMs: 15000, retry: { attempts: 1, baseDelayMs: 5000, maxDelayMs: 5000 },
  fetchData: context => fetchOfficialDisclosures('company-events', context?.signal) });
