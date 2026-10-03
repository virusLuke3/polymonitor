import type { RuntimeMarketTicker } from '@/types';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { Panel, PanelLoading } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { emptyState } from '@/panels/shared/renderers';
import { formatCompact } from '@/panels/shared/formatters';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { commoditySparkline, formatCommodityChange, tickerTone, averageChange, topMover } from '../../shared/market-tickers';
import { panelFromRenderer } from '@/panels/definePanel';
import { useCryptoFeed } from './useCryptoFeed';
import { cryptoQuoteState, type CryptoQuote } from './model';
import { useI18n } from '@/services/i18n';
import './styles.css';

type CryptoTickDirection = 'tick-up' | 'tick-down';

function formatCryptoPrice(item: RuntimeMarketTicker) {
  if (item.price == null || !Number.isFinite(Number(item.price))) return '--';
  const numeric = Number(item.price);
  if (Math.abs(numeric) >= 1000) {
    return `$${Math.round(numeric).toLocaleString('en-US')}`;
  }
  const digits = numeric >= 100 ? 2 : numeric >= 1 ? 2 : 4;
  return `$${numeric.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function cryptoBoard(
  items: CryptoQuote[],
  emptyMessage: string,
  tickDirections: Record<string, CryptoTickDirection | undefined>,
  labels: { topMove: string; average24h: string; green: string; volume24h: string; marketCap: string; flow: string },
) {
  if (!items.length) return emptyState(emptyMessage);
  const comparable = items.filter(item => cryptoQuoteState(item) === 'live' && item.changePercent != null);
  const leader = topMover(comparable);
  const avg = averageChange(comparable);
  const upCount = comparable.filter((item) => tickerTone(item) === 'up').length;
  return (
    <div className="wm-crypto-watch-shell">
      <div className="wm-market-radar-strip">
        <span><b>{leader?.label || '--'}</b><em>{labels.topMove}</em></span>
        <span><b>{avg == null ? '--' : formatCommodityChange(avg)}</b><em>{labels.average24h}</em></span>
        <span><b>{upCount}/{comparable.length}</b><em>{labels.green}</em></span>
      </div>
      <div className="wm-crypto-watch-list">
      {items.map((item) => {
        const tone = tickerTone(item);
        const sparkColor = tone === 'down' ? '#ff5d5d' : tone === 'up' ? '#39ff73' : '#8f8f8c';
        const tickDirection = tickDirections[item.symbol];
        return (
          <article className={`wm-crypto-market-row ${tone}${tickDirection ? ` ${tickDirection}` : ''}`} key={item.symbol} data-crypto-symbol={item.symbol}>
            <div className="wm-crypto-market-asset">
              <strong>{item.label}</strong>
              <span>{item.symbol.replace('-USD', '')}</span>
              <span className="wm-crypto-quote-clock">{cryptoQuoteState(item).toUpperCase()} · {item.quoteAt ? <time dateTime={item.quoteAt} title={item.quoteAt}>{new Date(item.quoteAt).toLocaleTimeString()}</time> : 'TIME UNKNOWN'}</span>
            </div>
            <div className="wm-crypto-market-spark">{commoditySparkline(item.points, sparkColor)}</div>
            <div className="wm-crypto-market-value">
              <strong>{formatCryptoPrice(item)}</strong>
              <span className={tone}>{formatCommodityChange(item.changePercent)}</span>
            </div>
            <div className="wm-crypto-market-flow">
              <b>{item.volume24h ? `$${formatCompact(item.volume24h)}` : item.marketCap ? `$${formatCompact(item.marketCap)}` : '--'}</b>
              <em>{item.volume24h ? item.volumeBasis === 'rolling-24h' ? labels.volume24h : 'SOURCE VOL' : item.marketCap ? labels.marketCap : labels.flow}</em>
            </div>
          </article>
        );
      })}
      </div>
    </div>
  );
}

function CryptoWatchPanel() {
  const feed = useCryptoFeed(), crypto = feed.data, i18n = useI18n(), cn = i18n.locale.startsWith('zh');
  const { copy, shared } = useSpecialistCopy('crypto-watch');
  const items = useMemo(() => crypto?.items || [], [crypto]);
  const checked = feed.status.checkedAt ? new Date(feed.status.checkedAt).toISOString() : null;
  const clock = (value: string) => new Intl.DateTimeFormat(i18n.locale, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(value));
  const previousPricesRef = useRef<Record<string, number>>({});
  const clearTickTimerRef = useRef<number | null>(null);
  const [tickDirections, setTickDirections] = useState<Record<string, CryptoTickDirection | undefined>>({});

  useEffect(() => {
    const nextPrices: Record<string, number> = {};
    const nextDirections: Record<string, CryptoTickDirection | undefined> = {};

    items.forEach((item) => {
      const numeric = Number(item.price);
      if (!Number.isFinite(numeric)) return;
      nextPrices[item.symbol] = numeric;
      const previous = previousPricesRef.current[item.symbol];
      if (typeof previous === 'number' && Number.isFinite(previous) && previous !== numeric) {
        nextDirections[item.symbol] = numeric > previous ? 'tick-up' : 'tick-down';
      }
    });

    previousPricesRef.current = nextPrices;

    if (!Object.keys(nextDirections).length) return;
    setTickDirections(nextDirections);

    if (clearTickTimerRef.current !== null) {
      window.clearTimeout(clearTickTimerRef.current);
    }
    clearTickTimerRef.current = window.setTimeout(() => {
      setTickDirections({});
      clearTickTimerRef.current = null;
    }, 1200);

    return undefined;
  }, [items]);

  useEffect(() => () => {
    if (clearTickTimerRef.current !== null) {
      window.clearTimeout(clearTickTimerRef.current);
    }
  }, []);

  return (
    <Panel title={copy('title', 'CRYPTO')} badge="SPOT" status="muted" count={crypto ? items.length : '—'} className="wm-market-panel wm-crypto-market-panel" dataPanelId="crypto-watch">
      <div className="wm-crypto-toolbar"><span>{feed.suspended ? cn ? '不可见时暂停检查' : 'Auto paused while hidden' : cn ? '自动检查5秒' : 'Auto check 5s'}{crypto && ` · ${cn ? '后台更新' : 'Source'} ${crypto.refreshIntervalSeconds}s`}</span><button type="button" disabled={feed.status.fetching} onClick={() => void feed.refresh()}>{feed.status.fetching ? cn ? '刷新中…' : 'Refreshing…' : cn ? '刷新' : 'Refresh'}</button></div>
      <p className="wm-crypto-clock">{checked && <span>{cn ? '检查' : 'Checked'} <time data-crypto-checked-at dateTime={checked}>{clock(checked)}</time></span>}{crypto && <span>{cn ? '快照' : 'Snapshot'} <time data-crypto-snapshot-at dateTime={crypto.generatedAt}>{clock(crypto.generatedAt)}</time></span>}</p>
      {feed.loading && <PanelLoading />}
      {feed.fromCache && <p className="wm-crypto-notice">{cn ? '显示缓存报价，正在检查更新。' : 'Showing saved quotes while checking updates.'}</p>}
      {(feed.error || feed.status.phase === 'stale') && <p className="wm-crypto-notice" role="status">{cn ? '刷新失败或采集超时；保留有效报价并自动重试。' : 'Refresh or collector overdue; retaining usable quotes and retrying automatically.'}</p>}
      {crypto && <p className="wm-crypto-clock">{cn ? '采集成功' : 'Acquired'} {crypto.coverage.succeeded}/{crypto.coverage.expected}{!!crypto.coverage.retained && ` · ${cn ? '保留' : 'Retained'} ${crypto.coverage.retained}`}</p>}
      {cryptoBoard(items, copy('empty', 'No crypto prices loaded yet.'), tickDirections, {
        topMove: shared('topMove', 'top move'),
        average24h: shared('average24h', 'avg 24h'),
        green: shared('green', 'green'),
        volume24h: shared('volume24h', '24h vol'),
        marketCap: shared('marketCap', 'mcap'),
        flow: shared('flow', 'flow'),
      })}
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'crypto-watch': {
    render: () => <CryptoWatchPanel />,
  },
};

export const panel = panelFromRenderer(renderers, {
  id: 'crypto-watch',
  title: 'Crypto Watch',
  eyebrow: 'macro',
  description: 'Crypto spot trends and sparklines.',
  defaultEnabled: true,
});
