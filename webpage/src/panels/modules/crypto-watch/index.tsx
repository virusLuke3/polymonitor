import type { RuntimeMarketGroup, RuntimeMarketTicker } from '@/types';
import { useEffect, useRef, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { emptyState } from '@/panels/shared/renderers';
import { formatCompact } from '@/panels/shared/formatters';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { commoditySparkline, formatCommodityChange, tickerTone, averageChange, topMover, sortTickers } from '../../shared/market-tickers';
import { fetchRuntimeCrypto } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

const CRYPTO_SYMBOL_ORDER = [
  'BTC-USD',
  'ETH-USD',
  'SOL-USD',
  'BNB-USD',
  'XRP-USD',
  'DOGE-USD',
  'ADA-USD',
  'AVAX-USD',
  'LINK-USD',
  'LTC-USD',
  'DOT-USD',
  'TRX-USD',
  'BCH-USD',
] as const;

const CRYPTO_SORT_INDEX = new Map(CRYPTO_SYMBOL_ORDER.map((symbol, index) => [symbol, index]));

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
  items: RuntimeMarketTicker[],
  emptyMessage: string,
  tickDirections: Record<string, CryptoTickDirection | undefined>,
  labels: { topMove: string; average24h: string; green: string; volume24h: string; marketCap: string; flow: string },
) {
  if (!items.length) return emptyState(emptyMessage);
  const leader = topMover(items);
  const avg = averageChange(items);
  const upCount = items.filter((item) => tickerTone(item) === 'up').length;
  return (
    <div className="wm-crypto-watch-shell">
      <div className="wm-market-radar-strip">
        <span><b>{leader?.label || '--'}</b><em>{labels.topMove}</em></span>
        <span><b>{avg == null ? '--' : formatCommodityChange(avg)}</b><em>{labels.average24h}</em></span>
        <span><b>{upCount}/{items.length}</b><em>{labels.green}</em></span>
      </div>
      <div className="wm-crypto-watch-list">
      {items.map((item) => {
        const tone = tickerTone(item);
        const sparkColor = tone === 'down' ? '#ff5d5d' : tone === 'up' ? '#39ff73' : '#8f8f8c';
        const tickDirection = tickDirections[item.symbol];
        return (
          <article className={`wm-crypto-market-row ${tone}${tickDirection ? ` ${tickDirection}` : ''}`} key={item.symbol}>
            <div className="wm-crypto-market-asset">
              <strong>{item.label}</strong>
              <span>{item.symbol.replace('-USD', '')}</span>
            </div>
            <div className="wm-crypto-market-spark">{commoditySparkline(item.points, sparkColor)}</div>
            <div className="wm-crypto-market-value">
              <strong>{formatCryptoPrice(item)}</strong>
              <span className={tone}>{formatCommodityChange(item.changePercent)}</span>
            </div>
            <div className="wm-crypto-market-flow">
              <b>{item.volume24h ? `$${formatCompact(item.volume24h)}` : item.marketCap ? `$${formatCompact(item.marketCap)}` : '--'}</b>
              <em>{item.volume24h ? labels.volume24h : item.marketCap ? labels.marketCap : labels.flow}</em>
            </div>
          </article>
        );
      })}
      </div>
    </div>
  );
}

function CryptoWatchPanel({ crypto }: { crypto?: RuntimeMarketGroup | null }) {
  const { copy, shared } = useSpecialistCopy('crypto-watch');
  const items = sortTickers(crypto?.items || [], CRYPTO_SORT_INDEX);
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
    <Panel title={copy('title', 'CRYPTO')} badge={shared('live', 'LIVE')} status="live" count={items.length} className="wm-market-panel wm-crypto-market-panel">
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
    render: (ctx) => <CryptoWatchPanel crypto={(ctx.runtimeData['crypto-watch'] as RuntimeMarketGroup | undefined)} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'crypto-watch',
  title: 'Crypto Watch',
  eyebrow: 'macro',
  description: 'Crypto spot trends and sparklines.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 5000,
  fetchData: (context) => fetchRuntimeCrypto(context?.signal),
});
