import { Component, type ComponentChildren } from 'preact';
import { Panel, PanelLoading } from '@/components/Panel';
import { panelFromRenderer } from '@/panels/definePanel';
import type { PanelInputs, PanelRenderMap } from '@/panels/types';
import { useI18n } from '@/services/i18n';
import { useAlphaFeed } from './useAlphaFeed';
import { signalDirection, type AlphaSignal, type AlphaCandidate } from './model';
import './styles.css';

function AlphaCard({ item, onSelect }: { item: AlphaSignal | AlphaCandidate; onSelect?: (id: number) => void }) {
  const i18n = useI18n(), cn = i18n.locale.startsWith('zh');
  const verified = 'logicalOutcome' in item;
  const money = (value: number) => new Intl.NumberFormat(i18n.locale, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
  return <article className={`wm-alpha-card is-${verified ? signalDirection(item) : 'pending'}`} data-alpha-id={item.id}>
    <div className="wm-alpha-card-heading"><b>{verified ? `${cn ? '资金流评分' : 'Flow score'} ${item.metrics.score}/100` : cn ? '待核验标签 · 资金流候选' : 'Labels pending · flow candidate'}</b><time dateTime={item.timestamp || undefined}>{item.timestamp ? i18n.formatDateTime(item.timestamp) : cn ? '时间未知' : 'Time unknown'}</time></div>
    <button type="button" className="wm-alpha-market" onClick={() => onSelect?.(item.marketId)}>{item.marketTitle}</button>
    <p>{cn ? '观测方向' : 'Observed flow'}: {item.side === 'BUY' ? cn ? '买入' : 'Buy' : cn ? '卖出' : 'Sell'} {verified ? item.outcome : 'token'}</p>
    {!verified && <p className="wm-alpha-help" title={item.tokenId}>Token {item.tokenId.slice(0, 8)}…{item.tokenId.slice(-6)}</p>}
    <dl className="wm-alpha-metrics">
      <div><dt>{cn ? '净资金流' : 'Net flow'}</dt><dd>{money(item.metrics.netFlowNotional)}</dd></div>
      <div><dt>{cn ? '方向强度' : 'Net strength'}</dt><dd>{(item.metrics.netDirectionStrength * 100).toFixed(1)}%</dd></div>
      <div><dt>{cn ? '成交笔数' : 'Fills'}</dt><dd>{item.metrics.tradeCount}</dd></div>
      <div><dt>{cn ? '独立成交方' : 'Unique takers'}</dt><dd>{item.metrics.uniqueTraderCount}</dd></div>
      <div><dt>{cn ? '主方向成交额' : 'Dominant flow'}</dt><dd>{money(item.metrics.totalNotional)}</dd></div>
      {verified && <div><dt>{cn ? '最后成交价格' : 'Last fill price'}</dt><dd>{(item.price * 100).toFixed(1)}¢</dd></div>}
    </dl>
  </article>;
}

function AlphaView({ ctx }: { ctx: PanelInputs<'setSelectedMarketId'> }) {
  const i18n = useI18n(), cn = i18n.locale.startsWith('zh');
  const copy = (en: string, zh: string) => cn ? zh : en;
  const feed = useAlphaFeed(), data = feed.data;
  const checked = feed.status.checkedAt ? new Date(feed.status.checkedAt).toISOString() : null;
  const clock = (value: string) => new Intl.DateTimeFormat(i18n.locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value));
  return <Panel title="ALPHA SIGNAL" badge="FLOW" count={data ? data.items.length + data.candidates.length : feed.loading ? '…' : '—'} className="wm-alpha-signal-panel">
    <div className="wm-alpha-toolbar"><span>{copy('Global', '全市场')} · {data?.windowMinutes ?? 15}{copy('m flow window', '分钟资金流窗口')}</span><button type="button" disabled={feed.status.fetching} onClick={() => void feed.refresh()}>{feed.status.fetching ? copy('Refreshing…', '刷新中…') : copy('Refresh', '刷新')}</button></div>
    <p className="wm-alpha-clock">{feed.suspended ? copy('Auto refresh paused while hidden.', '不可见时暂停自动刷新。') : copy('Auto 30s · seed 2m', '自动检查30秒 · 后台更新2分钟')}{checked && <span>{copy('Checked', '检查')} <time data-alpha-checked-at dateTime={checked} title={i18n.formatDateTime(checked)}>{clock(checked)}</time></span>}{data && <span>{copy('Snapshot', '快照')} <time data-alpha-updated-at dateTime={data.generatedAt} title={i18n.formatDateTime(data.generatedAt)}>{clock(data.generatedAt)}</time></span>}</p>
    {feed.loading && <PanelLoading />}
    {feed.fromCache && <p role="status">{copy('Showing a saved snapshot while checking updates.', '显示已保存快照，正在检查更新。')}</p>}
    {(feed.error || data?.status === 'degraded') && <p role="status">{copy('Alpha data cannot currently be verified.', '当前无法核验 Alpha 数据。')} {data?.error || feed.error}</p>}
    {data && (data.status === 'stale' || feed.status.phase === 'stale') && <p role="status">{copy('The source or saved snapshot is overdue. Refreshing without clearing verified signals.', '来源或快照已过期，更新期间保留已核验信号。')}</p>}
    {data?.status === 'partial' && <p className="wm-alpha-help" role="status">{copy('Unverified labels · neutral flow only.', '标签未核验 · 仅展示中性资金流。')}</p>}
    {data && !data.items.length && ['empty', 'ok'].includes(data.status) && <p role="status">{copy('No verified global flows meet the current thresholds.', '当前暂无满足门槛的已核验全市场资金流。')}</p>}
    {data && <p className="wm-alpha-help">{copy('Verified signals', '已核验信号')} {data.items.length} · {copy('Flow candidates', '资金流候选')} {data.candidates.length}</p>}
    <div className="wm-alpha-list">{data?.items.map(item => <AlphaCard key={item.id} item={item} onSelect={ctx.setSelectedMarketId} />)}{data?.candidates.map(item => <AlphaCard key={item.id} item={item} onSelect={ctx.setSelectedMarketId} />)}</div>
    {data && <details className="wm-alpha-source"><summary>{copy('Source and coverage', '来源与覆盖')} · {data.coverage.verifiedCount}/{data.coverage.candidateCount}</summary><p>OrderFilled · {copy('canonical token labels', '已核验 token 标签')}</p><p>{copy('Unclassified token flow carries no outcome prediction. Verified token flow is ranked by a heuristic score.', '待分类 token 资金流不表示结果预测；已核验资金流按启发式评分排序。')}</p>{data.error && <p>{data.error}</p>}<p>{copy('Source time', '来源时间')}: {data.sourceObservedAt ? i18n.formatDateTime(data.sourceObservedAt) : copy('Unknown', '未知')}</p><p>{copy('Candidates', '候选')} {data.coverage.candidateCount} · {copy('Verified', '已核验')} {data.coverage.verifiedCount} · {copy('Excluded', '排除')} {data.coverage.rejectedCount}{data.coverage.truncated ? copy(' · limited candidate coverage', ' · 候选覆盖受限') : ''}</p>{Object.entries(data.coverage.rejectionReasons).map(([reason, count]) => <p key={reason}>{reason}: {count}</p>)}<p>{copy('Block-based window; heuristic score has no validated return forecast.', '窗口按来源区块估算；评分尚未形成经验证的收益预测。')}</p></details>}
  </Panel>;
}
class AlphaBoundary extends Component<{ children: ComponentChildren }, { failed: boolean }> {
  state = { failed: false };
  componentDidCatch() { this.setState({ failed: true }); }
  render() { return this.state.failed ? <Panel title="ALPHA SIGNAL"><p role="alert">Unable to display Alpha Signal / Alpha 显示失败</p><button type="button" onClick={() => this.setState({ failed: false })}>Retry / 重试</button></Panel> : this.props.children; }
}
const renderers: PanelRenderMap<'setSelectedMarketId'> = { 'alpha-signal': { render: ctx => <AlphaBoundary><AlphaView ctx={ctx} /></AlphaBoundary> } };
export const panel = panelFromRenderer(renderers, { contextKeys: ['setSelectedMarketId'], id: 'alpha-signal', title: 'Alpha Signal', eyebrow: 'signal', description: 'Global canonical-token flow signals with source freshness and explicit coverage.', defaultEnabled: true });
