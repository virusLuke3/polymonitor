import { useMemo, useState } from 'preact/hooks';
import { Panel, PanelLoading } from '@/components/Panel';
import { panelFromRenderer } from '@/panels/definePanel';
import type { PanelRenderMap } from '@/panels/types';
import { useI18n } from '@/services/i18n';
import { assetStats, fundingStats, percent, quoteState, type FundingAsset, type FundingQuote } from './model';
import { useFundingFeed } from './useFundingFeed';
import './styles.css';

function Quote({ quote, cn, clock }: { quote: FundingQuote; cn: boolean; clock: (value: string) => string }) {
  const state = quoteState(quote);
  return <div className={`wm-funding-quote ${state}`} data-funding-venue={quote.exchange}>
    <div><a href={quote.sourceUrl} target="_blank" rel="noopener noreferrer">{quote.exchange}</a><strong>{percent(quote.fundingRatePercent, 5)}</strong></div>
    <span>{quote.symbol} · {quote.fundingIntervalHours == null ? cn ? '周期未知' : 'Period unknown' : `${quote.fundingIntervalHours}h`}</span>
    <span>{cn ? '下次结算' : 'Next funding'} {quote.nextFundingTime ? <time dateTime={quote.nextFundingTime} title={quote.nextFundingTime}>{clock(quote.nextFundingTime)}</time> : '—'}</span>
    <span>{quote.quoteObservedAt ? cn ? '来源时间' : 'Source time' : cn ? '接口响应时间' : 'Response time'} <time dateTime={quote.updatedAt} title={quote.updatedAt}>{clock(quote.updatedAt)}</time></span>
    {state !== 'fresh' && <b className="wm-funding-saved">{state === 'retained' ? cn ? '保留报价' : 'Saved quote' : cn ? '报价过期' : 'Quote stale'}</b>}
  </div>;
}

function FundingRow({ asset, cn, clock }: { asset: FundingAsset; cn: boolean; clock: (value: string) => string }) {
  const stats = assetStats(asset);
  const bias = stats.bias === 'longs-pay' ? cn ? '多头付费' : 'LONGS PAY' : stats.bias === 'shorts-pay' ? cn ? '空头付费' : 'SHORTS PAY'
    : stats.bias === 'mixed' ? cn ? '方向不一致' : 'MIXED' : stats.bias === 'flat' ? cn ? '零费率' : 'ZERO RATE' : cn ? '无新鲜可比报价' : 'NO FRESH COMPARISON';
  return <article className={`wm-funding-card ${stats.bias}`} data-funding-asset={asset.asset}>
    <div className="wm-funding-card-head"><div><strong>{asset.asset}</strong><span>{bias}</span></div>
      <div><strong data-funding-strongest>{percent(stats.strongest?.fundingRatePercent8h)}</strong><span>{cn ? '最大绝对费率 /8h' : 'Largest |rate| /8h'}{stats.strongest && ` · ${stats.strongest.exchange}`}</span></div>
    </div>
    <p className="wm-funding-comparison">{cn ? '均值 /8h' : 'Mean /8h'} <b>{percent(stats.mean)}</b> · {cn ? '差值' : 'Spread'} {stats.spread == null ? '—' : `${stats.spread.toFixed(4)} pp`} · {stats.freshVenues} {cn ? '新鲜来源' : 'fresh venues'}</p>
    <div className="wm-funding-venues">{asset.quotes.map(quote => <Quote key={quote.id} quote={quote} cn={cn} clock={clock} />)}</div>
    {!!asset.marketCount && <details className="wm-funding-markets"><summary>{asset.priceMarketCount ? `${asset.priceMarketCount} ${cn ? '关联价格市场' : 'price markets'}` : `${asset.marketCount} ${cn ? '币种背景市场' : 'asset context markets'}`}</summary>
      {asset.relatedMarkets.map(market => <a key={market.id} href={market.url} target="_blank" rel="noopener noreferrer">{market.title}{market.relation === 'asset-context' && ` (${cn ? '背景相关' : 'context'})`}</a>)}
    </details>}
  </article>;
}

function FundingRatePanel() {
  const feed = useFundingFeed(), data = feed.data, { locale } = useI18n(), cn = locale.startsWith('zh');
  const [showHelp, setShowHelp] = useState(false), [query, setQuery] = useState(''), [linked, setLinked] = useState(false), [page, setPage] = useState(0);
  const formatter = useMemo(() => new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }), [locale]);
  const clock = (value: string) => formatter.format(new Date(value));
  const assets = data?.assets || [], linkedCount = assets.filter(asset => asset.priceMarketCount > 0).length;
  const filtered = useMemo(() => assets.filter(asset => (!linked || asset.priceMarketCount > 0) && (!query.trim() || asset.asset.includes(query.trim().toUpperCase())
    || asset.quotes.some(quote => quote.symbol.includes(query.trim().toUpperCase())))), [assets, linked, query]);
  const stats = fundingStats(filtered), perPage = 30, lastPage = Math.max(0, Math.ceil(filtered.length / perPage) - 1), currentPage = Math.min(page, lastPage);
  const visible = filtered.slice(currentPage * perPage, (currentPage + 1) * perPage);
  const checked = feed.status.checkedAt ? new Date(feed.status.checkedAt).toISOString() : null;
  const stale = feed.status.phase === 'stale' || data?.status === 'stale';
  return <Panel title={cn ? '资金费率' : 'FUNDING RATE'} badge="PERPETUAL" status="muted" count={data ? assets.length : '—'} dataPanelId="crypto-funding-watch" className="wm-market-panel wm-funding-panel"
    titleControls={<button className="wm-panel-help-button" type="button" aria-label={cn ? '资金费率说明' : 'Explain funding rates'} aria-expanded={showHelp} onClick={() => setShowHelp(value => !value)}>?</button>}
    headerOverlay={showHelp ? <div className="wm-panel-help-popover"><strong>{cn ? '永续合约的资金成本' : 'Perpetual funding cost'}</strong><p>{cn ? '正费率为多头向空头付费，负费率反向。各交易所显示真实周期费率；汇总统一换算至8小时，仅比较新鲜报价。均值为等权平均，不能视为未来收益或预测市场概率。' : 'Positive funding: longs pay shorts; negative: shorts pay longs. Venue rates use their actual interval. Summaries normalize fresh quotes to 8h and use a simple mean. They do not predict returns or Polymarket probabilities.'}</p></div> : null}>
    <div className="wm-funding-toolbar"><span>{feed.suspended ? cn ? '不可见时暂停' : 'Paused while hidden' : cn ? '自动检查15秒' : 'Auto check 15s'} · {cn ? '采集' : 'Source'} {data?.refreshIntervalSeconds ?? 30}s</span>
      <button type="button" disabled={feed.status.fetching} onClick={() => void feed.refresh()}>{feed.status.fetching ? cn ? '刷新中…' : 'Refreshing…' : cn ? '刷新' : 'Refresh'}</button></div>
    <p className="wm-funding-clock">{checked && <span>{cn ? '检查' : 'Checked'} <time data-funding-checked-at dateTime={checked}>{clock(checked)}</time></span>}{data && <span>{cn ? '快照' : 'Snapshot'} <time data-funding-snapshot-at dateTime={data.generatedAt}>{clock(data.generatedAt)}</time></span>}</p>
    {feed.loading && <PanelLoading />}
    {(feed.error || stale) && <p className="wm-funding-notice" role="status">{cn ? '刷新失败或快照过期；保留有效报价，自动重试。' : 'Refresh failed or snapshot overdue; keeping usable quotes and retrying automatically.'}</p>}
    {feed.fromCache && <p className="wm-funding-clock">{cn ? '显示缓存，正在检查更新。' : 'Saved snapshot; checking for updates.'}</p>}
    {data && <>
      <p className="wm-funding-clock">{cn ? '新鲜报价' : 'Fresh quotes'} {data.coverage.succeeded}/{data.coverage.expectedQuotes} · {cn ? '保留' : 'Saved'} {data.coverage.retained} · {cn ? '缺失' : 'Missing'} {data.coverage.missing}</p>
      <div className="wm-funding-sources">{Object.entries(data.sources).map(([source, state]) => <span key={source} data-funding-source={source} className={state === 'ok' ? 'ok' : 'partial'}>{source.toUpperCase()} {state.toUpperCase()}</span>)}</div>
      {data.status === 'degraded' && !stale && <p className="wm-funding-notice">{cn ? '部分来源、资格或周期未完成核验；保留报价不参与实时汇总。' : 'Some sources, qualifications or intervals are incomplete. Saved quotes are excluded from live summaries.'}</p>}
      {data.marketUniverse.status !== 'ok' && <p className="wm-funding-notice">{cn ? '市场关联目录暂未更新；交易所费率仍独立刷新。' : 'Market associations are not current; venue funding still refreshes independently.'}</p>}
      <div className="wm-funding-filters"><button type="button" aria-pressed={!linked} onClick={() => { setLinked(false); setPage(0); }}>{cn ? '全部' : 'All'} {assets.length}</button><button type="button" aria-pressed={linked} onClick={() => { setLinked(true); setPage(0); }}>{cn ? '价格市场' : 'Price markets'} {linkedCount}</button>
        <input type="search" aria-label={cn ? '搜索资金费率币种' : 'Search funding assets'} placeholder={cn ? '搜索币种，如 BTC / HYPE' : 'Search BTC / HYPE'} value={query} onInput={event => { setQuery(event.currentTarget.value); setPage(0); }} /></div>
      <div className="wm-market-radar-strip wm-funding-radar-strip"><span><strong>{stats.top || '—'}</strong><em>{cn ? '最高绝对费率' : 'Highest |rate|'}</em></span><span><strong>{stats.averageAbs == null ? '—' : `${stats.averageAbs.toFixed(4)}%`}</strong><em>{cn ? '平均绝对费率 /8h' : 'Mean |rate| /8h'}</em></span><span><strong>{stats.alerts}/{stats.comparableAssets}</strong><em>{cn ? '≥0.015% /8h' : '≥0.015% /8h'}</em></span></div>
      <div className="wm-funding-list">{visible.map(asset => <FundingRow key={asset.id} asset={asset} cn={cn} clock={clock} />)}</div>
      {!filtered.length && <p>{cn ? '当前筛选没有匹配的币种。' : 'No assets match this filter.'}</p>}
      {lastPage > 0 && <nav className="wm-funding-pagination" aria-label={cn ? '资金费率分页' : 'Funding pagination'}><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>{cn ? '上一页' : 'Previous'}</button><span>{currentPage + 1}/{lastPage + 1} · {filtered.length} {cn ? '币种' : 'assets'}</span><button type="button" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>{cn ? '下一页' : 'Next'}</button></nav>}
      <details className="wm-funding-coverage"><summary>{cn ? '市场覆盖与限制' : 'Market coverage and limits'}</summary><p>{cn ? '市场目录' : 'Market catalogue'}: {data.marketUniverse.status.toUpperCase()} · {data.marketUniverse.scannedEvents} {cn ? '已扫描事件' : 'events scanned'}{data.marketUniverse.observedAt && <> · <time dateTime={data.marketUniverse.observedAt}>{clock(data.marketUniverse.observedAt)}</time></>}</p>
        <p>{cn ? '关联来自有限的活跃市场扫描；资金费率是背景信息，不是预测市场结算价格。' : 'Associations come from a bounded active-market scan. Funding is context, not a prediction-market settlement price.'}</p>
        {data.marketUniverse.status !== 'ok' && <p className="wm-funding-notice">{cn ? '市场关联目录暂未更新，币种对应关系可能不完整。' : 'Market catalogue is not current; asset associations may be incomplete.'}</p>}
        {!!data.coverage.unavailableAssets.length && <p>{cn ? '没有可核验的交易中USDT永续合约' : 'No qualified trading USDT perpetual'}: {data.coverage.unavailableAssets.map(item => `${item.asset}${item.reason === 'eligibility-unknown' ? ' (?)' : ''}`).join(', ')}</p>}
      </details>
    </>}
    {!data && !feed.loading && <p>{cn ? '目前没有可核验的报价，正在自动重试。' : 'No qualified quotes available; retrying automatically.'}</p>}
  </Panel>;
}

const renderers: PanelRenderMap = { 'crypto-funding-watch': { render: () => <FundingRatePanel /> } };
export const panel = panelFromRenderer(renderers, {
  id: 'crypto-funding-watch', title: 'Crypto Funding Watch', eyebrow: 'macro',
  description: 'Qualified perpetual funding with venue clocks, actual intervals and active crypto market context.', defaultEnabled: true,
});
