import { memo } from 'preact/compat';
import { useMemo, useState } from 'preact/hooks';
import { Panel, PanelLoading } from '@/components/Panel';
import { panelFromRenderer } from '@/panels/definePanel';
import { useI18n } from '@/services/i18n';
import { commoditySparkline, tickerTone, formatCommodityChange, averageChange, topMover } from '@/panels/shared/market-tickers';
import { formatCompact } from '@/panels/shared/formatters';
import { useCommodityFeed } from './useCommodityFeed';
import { commodityClass, formatPrice, quoteState, dailyMovers, type Quote } from './model';
import './styles.css';

const QuoteCard = memo(function QuoteCard({ item, cn, now }: { item: Quote; cn: boolean; now: number }) {
  const i18n = useI18n();
  const state = quoteState(item, now), tone = tickerTone(item);
  const sourceLabels = { open: cn ? '交易时段' : 'OPEN', closed: cn ? '休市报价' : 'CLOSED', stale: cn ? '报价过期' : 'QUOTE STALE', unknown: cn ? '报价时间待确认' : 'TIME UNKNOWN', retained: cn ? '保留报价 · 采集失败' : 'RETAINED · FETCH FAILED' };
  const change = item.changePercent;
  const alert = ['open', 'closed'].includes(state) && change != null && Math.abs(change) >= 1.5;
  return <article className={`commodity-item commodity-card ${tone} is-${state}`} data-commodity-symbol={item.symbol}>
    <div className="commodity-head"><span className="commodity-name">{item.label}</span><b className="commodity-class-tag">{commodityClass(item)}</b></div>
    <div className="commodity-spark">{commoditySparkline(item.points, tone === 'down' ? '#ff6464' : '#39ff73')}</div>
    <div className="commodity-foot"><strong className="commodity-price">{formatPrice(item)}</strong><span className={`commodity-change ${tone}`}>{formatCommodityChange(change)}</span></div>
    <div className="commodity-meta"><span className={`commodity-signal-tag ${alert ? 'alert' : 'watch'}`}>{alert ? cn ? '日变动≥1.5%' : 'DAY MOVE ≥1.5%' : sourceLabels[state]}</span>{item.sessionVolume != null && <em>{cn ? '时段量' : 'SESSION VOL'} {formatCompact(item.sessionVolume)}</em>}</div>
    <p className="wm-commodity-quote-time">{sourceLabels[state]} · {item.quoteAt ? <time dateTime={item.quoteAt} title={i18n.formatDateTime(item.quoteAt)}>{i18n.formatDateTime(item.quoteAt)}</time> : cn ? '来源未提供报价时间' : 'Provider quote time unavailable'}</p>
  </article>;
});

function CommoditiesWatchPanel() {
  const i18n = useI18n(), cn = i18n.locale.startsWith('zh');
  const copy = (en: string, zh: string) => cn ? zh : en;
  const [tab, setTab] = useState<'commodities' | 'fx'>('commodities');
  const feed = useCommodityFeed(), data = feed.data;
  const groups = useMemo(() => ({ commodities: data?.items.filter(item => !item.symbol.endsWith('=X')) || [], fx: data?.items.filter(item => item.symbol.endsWith('=X')) || [] }), [data]);
  const items = groups[tab], now = feed.status.checkedAt ?? Date.now();
  const movers = dailyMovers(items, now), leader = topMover(movers), average = averageChange(movers);
  const alerts = movers.filter(item => Math.abs(item.changePercent!) >= 1.5).length;
  const checked = feed.status.checkedAt ? new Date(feed.status.checkedAt).toISOString() : null;
  const clock = (value: string) => new Intl.DateTimeFormat(i18n.locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value));
  return <Panel title={copy('COMMODITIES', '商品行情')} badge="MACRO" status="muted" count={data ? items.length : '—'} className="wm-market-panel wm-commodities-panel" dataPanelId="commodities-watch">
    <div className="wm-commodity-panel-stack">
      <div className="wm-commodity-tabbar" role="tablist" aria-label={copy('Quote groups', '行情分组')}>
        {(['commodities', 'fx'] as const).map(group => <button type="button" role="tab" aria-selected={tab === group} key={group} className={`panel-tab${tab === group ? ' active' : ''}`} onClick={() => setTab(group)}>{group === 'fx' ? 'FX' : copy('Commodities', '商品')} <b>{data ? groups[group].length : '—'}</b></button>)}
      </div>
      <div className="wm-commodity-toolbar"><span>{feed.suspended ? copy('Auto paused while hidden', '不可见时暂停检查') : copy('Auto check 20s', '自动检查20秒')}{data && ` · ${copy('Source', '后台更新')} ${data.refreshIntervalSeconds}s`}</span><button type="button" disabled={feed.status.fetching} onClick={() => void feed.refresh()}>{feed.status.fetching ? copy('Refreshing…', '刷新中…') : copy('Refresh', '刷新')}</button></div>
      <p className="wm-commodity-clock">{checked && <span>{copy('Checked', '检查')} <time data-commodity-checked-at dateTime={checked} title={i18n.formatDateTime(checked)}>{clock(checked)}</time></span>}{data && <span>{copy('Snapshot', '快照')} <time data-commodity-updated-at dateTime={data.generatedAt} title={i18n.formatDateTime(data.generatedAt)}>{clock(data.generatedAt)}</time></span>}</p>
      {feed.loading && <PanelLoading />}
      {feed.fromCache && <p className="wm-commodity-notice" role="status">{copy('Showing saved quotes while checking updates.', '显示已保存报价，正在检查更新。')}</p>}
      {(feed.error || feed.status.phase === 'stale' || data?.status === 'stale') && <p className="wm-commodity-notice" role="status">{copy('Refresh or collector overdue. Last available quotes remain visible; retrying automatically.', '刷新失败或采集已超时；保留最后有效报价并自动重试。')}{!data && ` ${copy('No usable snapshot yet.', '暂无可用快照。')}`}</p>}
      {data && <p className="wm-commodity-coverage">{copy('Acquired', '采集成功')} {data.coverage.succeeded}/{data.coverage.expected}{!!data.coverage.retained && ` · ${copy('Retained', '保留')} ${data.coverage.retained}`}{!!data.coverage.missing && ` · ${copy('Missing', '缺失')} ${data.coverage.missing}`}</p>}
      {data && <>
        <div className="commodities-grid">{items.map(item => <QuoteCard key={item.symbol} item={item} cn={cn} now={now} />)}</div>
        {!items.length && <p role="status">{copy('No quotes available in this group; checking automatically.', '本分组暂无报价，正在自动检查。')}</p>}
        <p className="wm-commodity-help">{copy('Moves vs previous close · closed markets may keep the same price.', '涨跌幅对比前收盘 · 休市期间价格可能不变。')}</p>
        <div className="wm-market-radar-strip"><span><b>{leader?.label || '—'}</b><em>{copy('TOP DAY MOVE', '最大日变动')}</em></span><span><b>{average == null ? '—' : formatCommodityChange(average)}</b><em>{copy('AVG DAY MOVE', '平均日变动')}</em></span><span><b>{alerts}</b><em>{copy('MOVES ≥1.5%', '变动≥1.5%')}</em></span></div>
        <p className="wm-commodity-help">{copy('Comparable daily quotes', '可比较的日行情')} {movers.length}/{items.length}</p>
        <details className="wm-commodity-source"><summary>{copy('Source and coverage', '来源与覆盖')}</summary><p>Yahoo Finance · {copy('30-minute chart points; quotes may be delayed.', '30分钟历史价格点，报价可能延迟。')}</p><p>{copy('Includes futures, an index and ETF proxies. Currency and cents are preserved; contract units differ.', '包含期货、指数与ETF代理。保留币种及美分单位，各合约计价单位不同。')}</p><p>{copy('URA, LIT and COAL track sector equities, not physical commodity prices. COAL replaces the obsolete MTF futures quote.', 'URA、LIT、COAL 是行业股票ETF，不是商品实物价格。COAL 替换了停止更新的 MTF 期货报价。')} <a href="https://www.rangeetfs.com/coal" target="_blank" rel="noopener noreferrer">COAL ETF</a></p><p>{copy('Daily statistics exclude missing, retained or unconfirmed quote clocks. Missing previous close is shown as —.', '日变动统计排除缺失、保留及时间未确认的报价；缺少前收盘时显示 —。')}</p>{!!data.coverage.failedSymbols.length && <p>{copy('Acquisition gaps', '采集缺口')}: {data.coverage.failedSymbols.join(', ')}</p>}</details>
      </>}
    </div>
  </Panel>;
}

export const panel = panelFromRenderer({ 'commodities-watch': { render: () => <CommoditiesWatchPanel /> } }, {
  id: 'commodities-watch', title: 'Commodities Watch', eyebrow: 'macro',
  description: 'Commodity and FX quotes with source clocks, daily changes and autonomous refresh.', defaultEnabled: true,
});
