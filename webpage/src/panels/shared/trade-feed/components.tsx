import { Component, type ComponentChildren } from 'preact';
import { Panel, PanelLoading } from '@/components/Panel';
import type { usePanelResource } from '@/panels/usePanelResource';
import { useI18n } from '@/services/i18n';
import { shortIdentity, type TradeFeed, type TradeObservation } from './model';
import './styles.css';

type FeedState = ReturnType<typeof usePanelResource<TradeFeed>>;
export function TradeFeedFrame({ title, feed, children }: { title: string; feed: FeedState; children: ComponentChildren }) {
  const i18n = useI18n(), cn = i18n.locale.startsWith('zh'), data = feed.data;
  const copy = (en: string, zh: string) => cn ? zh : en;
  const clock = (stamp: string) => new Intl.DateTimeFormat(i18n.locale, { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date(stamp));
  const checked = feed.status.checkedAt ? new Date(feed.status.checkedAt).toISOString() : null;
  return <Panel title={title} badge="CHAIN" count={data ? data.items.length : feed.loading ? '…' : '—'} className="wm-trade-watch-panel">
    <div className="wm-trade-watch-toolbar"><span>{copy('Global on-chain fills', '全市场链上成交')}</span><button type="button" disabled={feed.status.fetching} onClick={() => void feed.refresh()}>{feed.status.fetching ? copy('Refreshing…', '刷新中…') : copy('Refresh', '刷新')}</button></div>
    <p className="wm-trade-watch-clock">{feed.suspended ? copy('Auto refresh paused while hidden.', '不可见时暂停自动刷新。') : copy(`Auto 30s · seed ${data?.refreshIntervalSeconds ?? 120}s`, `自动检查30秒 · 后台更新${data?.refreshIntervalSeconds ?? 120}秒`)}
      <span className="wm-trade-watch-stamps">{checked && <span>{copy('Checked', '检查')} <time data-trade-checked-at dateTime={checked} title={i18n.formatDateTime(checked)}>{clock(checked)}</time></span>}
      {data && <span>{copy('Snapshot', '快照')} <time data-trade-updated-at dateTime={data.generatedAt} title={i18n.formatDateTime(data.generatedAt)}>{clock(data.generatedAt)}</time></span>}</span></p>
    {feed.loading && <PanelLoading />}
    {feed.fromCache && <p role="status">{copy('Showing a saved snapshot while checking updates.', '显示已保存快照，正在检查更新。')}</p>}
    {(feed.error || data?.status === 'degraded') && <p className="wm-trade-watch-warning" role="status">{copy('Trade refresh unavailable. Automatic retries continue.', '成交刷新暂不可用，将继续自动重试。')} {data?.error || feed.error}</p>}
    {(data?.status === 'stale' || feed.status.phase === 'stale') && <p className="wm-trade-watch-warning" role="status">{copy('Previous snapshot · source refresh is overdue or failed.', '显示历史快照 · 来源刷新已过期或失败。')} {data?.error}</p>}
    {data?.status === 'partial' && <p className="wm-trade-watch-warning" role="status">{copy('Partial coverage.', '覆盖不完整。')} {data.error}</p>}
    {children}
  </Panel>;
}
export function TradeCard({ item, onSelect, showType = false }: { item: TradeObservation; onSelect?: (id: number) => void; showType?: boolean }) {
  const i18n = useI18n(), cn = i18n.locale.startsWith('zh');
  const copy = (en: string, zh: string) => cn ? zh : en;
  const money = (value: number | null) => value == null ? copy('Unknown', '未知') : new Intl.NumberFormat(i18n.locale, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(value);
  return <article className={`wm-trade-watch-card is-${item.side.toLowerCase()}`} data-trade-id={item.id}>
    <div className="wm-trade-watch-card-head"><b>{item.side === 'UNKNOWN' ? copy('Direction unknown', '方向未知') : item.side} {item.outcome || copy('token · labels pending', 'token · 标签待核验')}</b><strong>{money(item.notional)}</strong></div>
    {showType && <p className="wm-trade-watch-type">{item.observationType === 'oracle-linked' ? copy('Oracle-linked observation', 'Oracle 关联观测') : copy('Large-trade observation', '大额成交观测')}</p>}
    <button type="button" className="wm-trade-watch-market" disabled={!onSelect} onClick={() => onSelect?.(item.marketId)}>{item.marketTitle}</button>
    <dl className="wm-trade-watch-metrics"><div><dt>{copy('Token fill price', 'Token 成交价')}</dt><dd>{item.price == null ? '—' : `${(item.price*100).toFixed(1)}¢`}</dd></div><div><dt>{copy('Size tier', '成交额分级')}</dt><dd>{item.severity.toUpperCase()}</dd></div></dl>
    <p className="wm-trade-watch-time">{copy('Trade', '成交')} <time dateTime={item.timestamp || undefined}>{item.timestamp ? i18n.formatDateTime(item.timestamp) : copy('Time unknown', '时间未知')}</time></p>
    {item.eventTime && <p className="wm-trade-watch-time">Oracle <time dateTime={item.eventTime}>{i18n.formatDateTime(item.eventTime)}</time></p>}
    <div className="wm-trade-watch-identities">{(['maker', 'taker'] as const).map(role => <span key={role}>{role === 'maker' ? copy('Maker', 'Maker') : copy('Taker', 'Taker')} {item[role] ? <a href={`https://polygonscan.com/address/${item[role]}`} target="_blank" rel="noopener noreferrer" title={item[role]!}>{shortIdentity(item[role]!)}</a> : copy('Unknown', '未知')}</span>)}<span>Tx <a href={`https://polygonscan.com/tx/0x${item.txHash}`} target="_blank" rel="noopener noreferrer" title={`0x${item.txHash}`}>{shortIdentity(item.txHash)}</a></span><span title={item.tokenId}>Token {shortIdentity(item.tokenId)}</span></div>
  </article>;
}
export class TradeFeedBoundary extends Component<{ title: string; children: ComponentChildren }, { failed: boolean }> {
  state = { failed: false };
  componentDidCatch() { this.setState({ failed: true }); }
  render() { return this.state.failed ? <Panel title={this.props.title}><p role="alert">Trade display failed / 成交显示失败</p><button type="button" onClick={() => this.setState({ failed: false })}>Retry / 重试</button></Panel> : this.props.children; }
}
