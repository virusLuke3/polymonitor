import type { RuntimeMarketGroup, RuntimeMarketTicker } from '@/types';
import { useMemo, useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { formatCompact } from '@/panels/shared/formatters';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { commoditySparkline, tickerTone, formatCommodityChange, averageChange, topMover, sortTickers } from '../../shared/market-tickers';
import { fetchRuntimeCommodities } from '@/services/api';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

type CommoditiesTab = 'commodities' | 'fx';

const COMMODITY_SYMBOL_ORDER = [
  '^VIX',
  'GC=F',
  'SI=F',
  'HG=F',
  'PL=F',
  'PA=F',
  'ALI=F',
  'CL=F',
  'BZ=F',
  'NG=F',
  'TTF=F',
  'RB=F',
  'HO=F',
  'URA',
  'LIT',
  'MTF=F',
  'ZW=F',
  'ZC=F',
  'ZS=F',
  'ZR=F',
  'KC=F',
  'SB=F',
  'CC=F',
  'CT=F',
] as const;

const FX_SYMBOL_ORDER = [
  'EURUSD=X',
  'GBPUSD=X',
  'USDJPY=X',
  'USDCNY=X',
  'USDINR=X',
  'AUDUSD=X',
  'USDCHF=X',
  'USDCAD=X',
  'USDTRY=X',
] as const;

const COMMODITY_SORT_INDEX = new Map(COMMODITY_SYMBOL_ORDER.map((symbol, index) => [symbol, index]));

const FX_SORT_INDEX = new Map(FX_SYMBOL_ORDER.map((symbol, index) => [symbol, index]));

function tickerMoveTag(item: RuntimeMarketTicker) {
  const absChange = Math.abs(Number(item.changePercent));
  if (!Number.isFinite(absChange)) return 'QUOTE';
  if (absChange >= 1.5) return 'ALERT';
  if (absChange >= 0.6) return 'MOVE';
  return 'WATCH';
}

function tagKey(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-');
}

function commodityClass(item: RuntimeMarketTicker) {
  const symbol = item.symbol.toUpperCase();
  if (isFxTicker(item)) return 'FX';
  if (['GC=F', 'SI=F', 'HG=F', 'PL=F', 'PA=F', 'ALI=F'].includes(symbol)) return 'METALS';
  if (['CL=F', 'BZ=F', 'NG=F', 'TTF=F', 'RB=F', 'HO=F', 'URA', 'LIT'].includes(symbol)) return 'ENERGY';
  if (symbol === '^VIX') return 'RISK';
  return 'AGRI';
}

function commodityAuxMeta(item: RuntimeMarketTicker) {
  const volume = Number(item.volume24h);
  if (Number.isFinite(volume) && volume > 0) return `VOL ${formatCompact(volume)}`;
  const marketCap = Number(item.marketCap);
  if (Number.isFinite(marketCap) && marketCap > 0) return `MCAP ${formatCompact(marketCap)}`;
  return null;
}

function isFxTicker(item: RuntimeMarketTicker) {
  return item.symbol.endsWith('=X');
}

function formatCommodityPrice(item: RuntimeMarketTicker) {
  if (item.price == null || !Number.isFinite(Number(item.price))) return '--';
  const numeric = Number(item.price);
  if (isFxTicker(item)) {
    return numeric.toFixed(4);
  }
  if (Math.abs(numeric) >= 1000) {
    return `$${formatCompact(numeric)}`;
  }
  return `$${numeric.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function commodityBoard(
  items: RuntimeMarketTicker[],
  emptyMessage: string,
  labels: { topMove: string; averageMove: string; alerts: string },
) {
  if (!items.length) {
    return (
      <div className="wm-commodity-empty">
        <span>{emptyMessage}</span>
      </div>
    );
  }
  const leader = topMover(items);
  const avg = averageChange(items);
  const alertCount = items.filter((item) => tickerMoveTag(item) === 'ALERT').length;
  return (
    <div className="wm-commodity-board">
      <div className="wm-market-radar-strip">
        <span><b>{leader?.label || '--'}</b><em>{labels.topMove}</em></span>
        <span><b>{avg == null ? '--' : formatCommodityChange(avg)}</b><em>{labels.averageMove}</em></span>
        <span><b>{alertCount}</b><em>{labels.alerts}</em></span>
      </div>
      <div className="commodities-grid">
      {items.map((item) => {
        const tone = tickerTone(item);
        const sparkColor = tone === 'down' ? '#ff6464' : '#39ff73';
        const assetClass = commodityClass(item);
        const signalTag = tickerMoveTag(item);
        const auxMeta = commodityAuxMeta(item);
        return (
          <div className={`commodity-item ${tone}`} key={item.symbol}>
            <div className="commodity-head">
              <span className="commodity-name">{item.label}</span>
              <b className={`commodity-class-tag ${tagKey(assetClass)}`}>{assetClass}</b>
            </div>
            <div className="commodity-spark">{commoditySparkline(item.points, sparkColor)}</div>
            <div className="commodity-foot">
              <strong className="commodity-price">{formatCommodityPrice(item)}</strong>
              <span className={`commodity-change ${tone}`}>{formatCommodityChange(item.changePercent)}</span>
            </div>
            <div className="commodity-meta">
              <span className={`commodity-signal-tag ${tagKey(signalTag)}`}>{signalTag}</span>
              {auxMeta ? <em>{auxMeta}</em> : null}
            </div>
          </div>
        );
      })}
      </div>
    </div>
  );
}

function CommoditiesWatchPanel({ commodities }: { commodities?: RuntimeMarketGroup | null }) {
  const { copy, shared, formatNumber } = useSpecialistCopy('commodities-watch');
  const [tab, setTab] = useState<CommoditiesTab>('commodities');

  const tabItems = useMemo(() => {
    const items = commodities?.items || [];
    const commodityItems = sortTickers(items.filter((item) => !isFxTicker(item)), COMMODITY_SORT_INDEX);
    const fxItems = sortTickers(items.filter((item) => isFxTicker(item)), FX_SORT_INDEX);
    return { commodities: commodityItems, fx: fxItems };
  }, [commodities]);

  const hasFx = tabItems.fx.length > 0;
  const safeTab = tab === 'fx' && !hasFx ? 'commodities' : tab;
  const visibleItems = safeTab === 'fx' ? tabItems.fx : tabItems.commodities;

  return (
    <Panel
      title={copy('title', 'COMMODITIES')}
      badge={shared('macro', 'MACRO')}
      status="live"
      count={visibleItems.length}
      className="wm-market-panel wm-commodities-panel"
    >
      <div className="wm-commodity-panel-stack">
        <div className="wm-commodity-tabbar" role="tablist" aria-label={copy('views', 'Commodity market views')}>
          <button
            type="button"
            className={`panel-tab${safeTab === 'commodities' ? ' active' : ''}`}
            onClick={() => setTab('commodities')}
            role="tab"
            aria-selected={safeTab === 'commodities'}
          >
            {copy('commodities', 'Commodities')} <b>{formatNumber(tabItems.commodities.length)}</b>
          </button>
          {hasFx ? (
            <button
              type="button"
              className={`panel-tab${safeTab === 'fx' ? ' active' : ''}`}
              onClick={() => setTab('fx')}
              role="tab"
              aria-selected={safeTab === 'fx'}
            >
              FX <b>{formatNumber(tabItems.fx.length)}</b>
            </button>
          ) : null}
        </div>
        {commodityBoard(
          visibleItems,
          safeTab === 'fx' ? copy('noFx', 'No FX quotes loaded yet.') : copy('empty', 'No commodity quotes loaded yet.'),
          {
            topMove: shared('topMove', 'top move'),
            averageMove: shared('averageMove', 'avg move'),
            alerts: shared('alerts', 'alerts'),
          },
        )}
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap = {
  'commodities-watch': {
    render: (ctx) => <CommoditiesWatchPanel commodities={(ctx.runtimeData['commodities-watch'] as RuntimeMarketGroup | undefined)} />,
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  id: 'commodities-watch',
  title: 'Commodities Watch',
  eyebrow: 'macro',
  description: 'Commodity price boards and sparklines.',
  defaultEnabled: true,
}, {
  tier: 'fast',
  fetchData: (context) => fetchRuntimeCommodities(context?.signal),
});
