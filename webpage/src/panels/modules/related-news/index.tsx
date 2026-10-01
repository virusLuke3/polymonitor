import { useMemo, useState } from 'preact/hooks';
import type { PanelInputs, PanelRenderMap } from '../../types';
import { Panel, PanelLoading } from '@/components/Panel';
import { panelFromRenderer } from '@/panels/definePanel';
import { useI18n } from '@/services/i18n';
import { useIntelFeed } from './useIntelFeed';
import './styles.css';
import { Component, type ComponentChildren } from 'preact';
import { initialIntelScope, INTEL_SCOPE_STORAGE_KEY, resourceId, type IntelResource } from './model';
import { IntelCard, IntelCardBoundary } from './IntelCard';

type Inputs = PanelInputs<'selectedMarketId' | 'selectedMarket'>;
const kinds = ['all', 'news_report', 'official_release', 'event'] as const;
function RelatedIntelPanel({ ctx }: { ctx: Inputs }) {
  const [global, updateGlobal] = useState(() => {
    try { return initialIntelScope(typeof window === 'undefined' ? null : window.localStorage) === 'global'; }
    catch { return true; }
  });
  const setGlobal = (value: boolean) => {
    updateGlobal(value);
    try { window.localStorage.setItem(INTEL_SCOPE_STORAGE_KEY, value ? 'global' : 'market'); } catch { /* Optional preference. */ }
  };
  const [days, setDays] = useState(7);
  const scope = global || ctx.selectedMarketId == null ? 'global' : 'market';
  const key = resourceId({ marketId: ctx.selectedMarketId, scope, days });
  return <IntelBoundary key={key}><IntelView ctx={ctx} scope={scope} days={days} setDays={setDays} setGlobal={setGlobal} /></IntelBoundary>;
}

/** Identity changes reset the reader and release its old shared-resource subscription. */
function IntelView({ ctx, scope, days, setDays, setGlobal }: {
  ctx: Inputs; scope: IntelResource['scope']; days: number;
  setDays: (days: number) => void; setGlobal: (global: boolean) => void;
}) {
  const i18n = useI18n();
  const copy = (en: string, cn: string) => i18n.locale.startsWith('zh') ? cn : en;
  const [kind, setKind] = useState<typeof kinds[number]>('all');
  const feed = useIntelFeed(scope === 'global' ? null : ctx.selectedMarketId, scope, days);
  const data = feed.data;
  const checkTime = feed.status.checkedAt == null ? null : new Date(feed.status.checkedAt).toISOString();
  const clock = useMemo(() => new Intl.DateTimeFormat(i18n.locale, {
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  }), [i18n.locale]);
  const formatCheck = (value: string) => clock.format(new Date(value));
  const items = data?.items || [];
  const unsupported = scope === 'market' && data?.marketCoverage?.status === 'unsupported';
  const labels = { all: copy('All', '全部'), news_report: copy('Reports', '报道'), official_release: copy('Official', '公告'), event: copy('Events', '事件') };
  const filtered = (filter: typeof kinds[number]) => items.filter((item) => filter === 'all' || (filter === 'event' ? ['alert', 'observation'].includes(item.sourceKind || '') : item.sourceKind === filter));
  return <Panel title={scope === 'global' ? copy('Global Updates', '全局资讯') : copy('Related Intelligence', '关联情报')} count={feed.loading ? '…' : items.length} className="wm-related-intel-panel wm-free-intel-panel">
    <div className="wm-intel-scope">
      <button type="button" aria-pressed={scope === 'market'} disabled={ctx.selectedMarketId == null} onClick={() => setGlobal(false)}>{copy('Market', '市场')}</button>
      <button type="button" aria-pressed={scope === 'global'} onClick={() => setGlobal(true)}>{copy('Global', '全局')}</button>
      <select aria-label={copy('Content time range', '资讯时间范围')} value={days} onChange={(event) => setDays(Number(event.currentTarget.value))}><option value={7}>{copy('Past 7 days', '过去 7 天')}</option><option value={30}>{copy('Past 30 days · history', '过去 30 天 · 历史')}</option></select>
      <button type="button" title={copy('Auto check every 30 seconds.', '每 30 秒自动检查。')} disabled={feed.status.fetching} onClick={() => void feed.refresh()}>{feed.status.fetching ? copy('Refreshing…', '刷新中…') : feed.error ? copy('Retry', '重试') : copy('Refresh', '刷新')}</button>
    </div>
    {scope === 'market' && <p className="wm-free-intel-market-caption">{(ctx.selectedMarket?.id === ctx.selectedMarketId ? ctx.selectedMarket.title : null) || data?.marketTitle || `Market ${ctx.selectedMarketId}`}</p>}
    {!unsupported && items.length > 0 && <div className="wm-intel-filter-tabs" role="group" aria-label={copy('Content types', '内容类型')}>{kinds.map((value) => <button type="button" aria-pressed={kind === value} className={kind === value ? 'active' : ''} onClick={() => setKind(value)} key={value}><span>{labels[value]}</span><b>{filtered(value).length}</b></button>)}</div>}
    {feed.loading && <PanelLoading />}
    {feed.pending && <button type="button" className="wm-intel-new" onClick={feed.accept}>{copy('New content available', '有新内容')} · {feed.pendingCount} · {copy('show', '点击查看')}</button>}
    {(feed.error || data?.status === 'unavailable') && <p role="status">{copy('Content service unavailable.', '资讯服务暂不可用。')} {!!items.length && copy('Showing previously verified content.', '显示此前已核验的内容。')}</p>}
    {!feed.error && !unsupported && data?.status === 'partial' && <p role="status" className="wm-intel-health">{data.stale
      ? copy('Using an overdue snapshot.', '当前使用较旧快照。') : data.coverage?.truncated
      ? copy('Candidate coverage is limited; results may be incomplete.', '候选覆盖有限，结果可能不完整。') : data.rejectedItemCount
      ? copy('Some invalid items were excluded.', '部分格式异常的内容已隔离。')
      : copy('Some sources unavailable or overdue.', '部分来源不可用或超过检查时间。')}</p>}
    {feed.fromCache && <p role="status" className="wm-intel-health">{copy('Showing a saved snapshot · checking updates.', '显示已保存的快照 · 检查更新中。')}</p>}
    <p className="wm-news-meta wm-intel-refresh-status">
      {feed.suspended ? <span>{copy('Auto refresh paused while hidden.', '不可见时暂停自动刷新。')}</span> : <span title={copy('Checks the shared feed every 30 seconds; sources follow their own schedules.', '每 30 秒检查共享资讯；来源按各自周期采集。')}>{copy('Auto 30s', '自动 30秒')}</span>}
      {checkTime && <span>{copy('Checked', '检查')} <time data-intel-checked-at dateTime={checkTime} title={i18n.formatDateTime(checkTime)}>{formatCheck(checkTime)}</time></span>}
      {data?.generatedAt && <span>{copy('Snapshot', '快照')} <time data-intel-updated-at dateTime={data.generatedAt} title={i18n.formatDateTime(data.generatedAt)}>{formatCheck(data.generatedAt)}</time>{data.stale || feed.stale && data.status !== 'partial' ? copy(' · overdue', ' · 超时') : ''}</span>}
    </p>
    {!feed.error && unsupported && <div className="wm-intel-empty" role="status"><p>{copy('No dedicated feed for this market is configured in the reviewed sources.', '当前已核验来源尚未接入此市场对应的专门资讯。')}</p><p>{data.marketCoverage?.topic === 'sports' ? copy('Sports coverage is not connected yet.', '尚未接入体育赛事报道。') : copy('This category is not covered yet.', '此类别尚未覆盖。')}</p><button type="button" className="wm-intel-new" onClick={() => setGlobal(true)}>{copy('View global updates', '查看全局资讯')}</button></div>}
    {!feed.error && !unsupported && data && data.status !== 'unavailable' && !feed.pending && !filtered(kind).length && <div className="wm-intel-empty"><p>{scope === 'market' ? copy('No content meeting this market’s conditions was found in the current free sources.', '当前免费来源中，暂未找到符合本市场条件的内容。') : copy('No public content in this type and time range.', '此类型和时间范围内暂无可公开展示的内容。')}</p>{scope === 'market' && <button type="button" className="wm-intel-new" onClick={() => setGlobal(true)}>{copy('View global updates', '查看全局资讯')}</button>}</div>}
    <div className="wm-intel-list">{filtered(kind).map(item => <IntelCardBoundary key={`${item.id}:${item.content_version}`}><IntelCard item={item} scope={scope} /></IntelCardBoundary>)}</div>
    {data && <details className="wm-intel-sources"><summary>{copy('Source status', '来源状态')} · {data.sources?.length || 0} {copy('feeds', '个订阅入口')} · {items.length} {scope === 'market' ? copy('matches', '条匹配') : copy('items', '条内容')}</summary><p>{copy('Latest successful source check', '最近单源成功检查')}：{data.lastSuccessfulCheckAt ? i18n.formatDateTime(data.lastSuccessfulCheckAt) : copy('Unknown', '未知')}</p>{feed.error && <p>{feed.error}</p>}{data.coverage && <p>{copy('Candidates checked', '已检查候选')}：{data.coverage.candidatesScanned}{data.coverage.truncated ? copy(' · limited coverage', ' · 覆盖受限') : ''}</p>}{data.sources?.map((source) => <p key={source.source_id}><b>{source.source_id}</b> · {source.status}{source.stale ? ' · stale' : ''}<br />{source.error || ''}</p>)}</details>}
  </Panel>;
}

/** Isolate an unexpected panel render failure from neighbouring panels. */
class IntelBoundary extends Component<{ children: ComponentChildren }, { failed: boolean }> {
  state = { failed: false };
  componentDidCatch() { this.setState({ failed: true }); }
  render() {
    return this.state.failed ? <Panel title="Related Intelligence" className="wm-related-intel-panel"><p role="alert">Unable to display content / 资讯显示失败</p><button type="button" onClick={() => this.setState({ failed: false })}>Retry / 重试</button></Panel> : this.props.children;
  }
}
const renderers: PanelRenderMap<'selectedMarketId' | 'selectedMarket'> = { 'related-news': { render: (ctx) => <RelatedIntelPanel ctx={ctx} /> } };
export const panel = panelFromRenderer(renderers, { contextKeys: ['selectedMarketId', 'selectedMarket'], id: 'related-news', title: 'Related Intelligence', eyebrow: 'intel', description: 'Reviewed free sources, explicitly scoped to a market or global updates.', defaultEnabled: true });
