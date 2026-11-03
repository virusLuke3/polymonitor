import {
  signedClass as pnlTone,
  formatCompact,
  formatCurrencyCompact,
  formatPercent,
  formatRelative,
  shortHash,
} from '../../shared/formatters';
import { useState } from 'preact/hooks';
import { Panel } from '@/components/Panel';
import { fetchRuntimePolySignal } from '@/services/api';
import type { RuntimePolySignalItem, RuntimePolySignalPayload, RuntimePolySignalWallet } from '@/types';
import type { PanelRenderMap } from '../../types';
import { runtimePanelFromRenderer } from '@/panels/definePanel';

function badgeLabel(payload?: RuntimePolySignalPayload | null) {
  const status = String(payload?.status || '').toLowerCase();
  const cacheMode = String(payload?.cacheMode || '').toLowerCase();
  if (status === 'empty') return 'QUIET';
  if (cacheMode.includes('stale')) return 'STALE';
  if (cacheMode.includes('seed')) return 'SEED';
  return 'LIVE';
}

function panelStatus(payload?: RuntimePolySignalPayload | null): 'live' | 'muted' {
  const status = String(payload?.status || '').toLowerCase();
  return status === 'empty' ? 'muted' : 'live';
}

function signalBias(item: RuntimePolySignalItem) {
  const explicit = String(item.bias || '').toLowerCase();
  if (explicit === 'bearish' || explicit === 'bullish') return explicit;
  if (String(item.outcome || '').toUpperCase() === 'NO') return 'bearish';
  return 'bullish';
}

function actionLabel(item: RuntimePolySignalItem) {
  const side = String(item.side || item.action?.label || 'BUY').toUpperCase();
  const outcome = String(item.outcome || item.action?.outcome || 'YES').toUpperCase();
  return `${side} ${outcome}`;
}

function primaryWallet(item: RuntimePolySignalItem): RuntimePolySignalWallet | null {
  const wallets = item.wallets || [];
  if (!wallets.length) return null;
  const first = wallets[0] as RuntimePolySignalWallet;
  return wallets.reduce((best, wallet) => {
    const bestScore = Number(best.smartScore || 0);
    const score = Number(wallet.smartScore || 0);
    return score > bestScore ? wallet : best;
  }, first);
}

function metricValue(item: RuntimePolySignalItem, key: 'totalNotional' | 'currentProbability' | 'avgPrice' | 'accountCount' | 'tradeCount') {
  return item.metrics?.[key] ?? null;
}

function probabilityLabel(value?: string | number | null) {
  if (value === null || value === undefined || value === '') return '--';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return numeric <= 1 ? formatPercent(numeric) : `${numeric.toFixed(1)}%`;
}

function domainClass(value?: string | null) {
  const domain = String(value || 'PMKT').toLowerCase();
  if (domain === 'conflict' || domain === 'government') return 'risk';
  if (domain === 'sports') return 'sports';
  if (domain === 'crypto') return 'crypto';
  if (domain === 'economic') return 'economic';
  return 'pmkt';
}

function WalletStrip({ wallet }: { wallet: RuntimePolySignalWallet | null }) {
  if (!wallet) {
    return (
      <div className="wm-polysignal-wallet muted">
        <span>WALLET</span>
        <strong>TRACKING</strong>
      </div>
    );
  }
  return (
    <div className={`wm-polysignal-wallet ${pnlTone(wallet.netCashPnlProxy)}`}>
      <span>{wallet.shortAddress || shortHash(wallet.address, 6, 4)}</span>
      <strong>{formatCurrencyCompact(wallet.netCashPnlProxy)}</strong>
      <em>{formatCompact(wallet.tradeCount)} trades</em>
    </div>
  );
}

function PolySignalRow({
  item,
  active,
  onSelect,
  onToggle,
}: {
  item: RuntimePolySignalItem;
  active: boolean;
  onSelect: () => void;
  onToggle: () => void;
}) {
  const bias = signalBias(item);
  const wallet = primaryWallet(item);
  const notional = metricValue(item, 'totalNotional') || item.notional;
  const probability = metricValue(item, 'currentProbability') || item.price;
  const accounts = metricValue(item, 'accountCount') || item.wallets?.length || 0;
  const trades = metricValue(item, 'tradeCount') || 0;
  return (
    <article className={`wm-polysignal-row ${bias} ${active ? 'active' : ''}`}>
      <button type="button" className="wm-polysignal-row-main" onClick={onToggle} title={item.marketTitle || item.title || 'PolySignal signal'}>
        <span className={`wm-polysignal-glyph ${bias}`}>PS</span>
        <div className="wm-polysignal-copy">
          <div className="wm-polysignal-meta">
            <span className="wm-polysignal-source">PMKT FLOW</span>
            <span className={`wm-polysignal-domain ${domainClass(item.domain)}`}>{String(item.domain || 'PMKT').toUpperCase()}</span>
            <span className={`wm-polysignal-action ${bias}`}>{actionLabel(item)}</span>
            <span>{formatRelative(item.timestamp)}</span>
          </div>
          <strong className="wm-polysignal-title">{item.marketTitle || item.title || 'Market flow detected'}</strong>
          <p className="wm-polysignal-explanation">{item.explanation || item.summary || 'Wallet flow clustered around this market.'}</p>
          {active ? (
            <div className="wm-polysignal-detail">
              {(item.wallets || []).slice(0, 3).map((walletItem) => (
                <div key={walletItem.address || walletItem.shortAddress} className="wm-polysignal-detail-wallet">
                  <span>{walletItem.shortAddress || shortHash(walletItem.address, 6, 4)}</span>
                  <b>{formatCurrencyCompact(walletItem.netCashPnlProxy)}</b>
                  <em>{formatCompact(walletItem.marketVolumeNotional)} market vol</em>
                </div>
              ))}
              {(item.relatedContent || []).slice(0, 1).map((source) => (
                <span key={source.url || source.title || 'source'} className="wm-polysignal-source-link">
                  {source.source || 'INTEL'} / {source.title || 'related source'}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <div className="wm-polysignal-values">
          <strong>{formatCurrencyCompact(notional)}</strong>
          <span>{probabilityLabel(probability)}</span>
          <em>{accounts}W / {trades}T</em>
        </div>
      </button>
      <div className="wm-polysignal-row-foot">
        <WalletStrip wallet={wallet} />
        <button type="button" className="wm-polysignal-market-button" onClick={onSelect} disabled={!item.marketId}>
          VIEW
        </button>
      </div>
    </article>
  );
}

function PolySignalFeedPanel({
  payload,
  selectedMarketId,
  setSelectedMarketId,
}: {
  payload?: RuntimePolySignalPayload | null;
  selectedMarketId: number | null;
  setSelectedMarketId: (marketId: number) => void;
}) {
  const [showHelp, setShowHelp] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const items = payload?.items || [];
  const top = items[0];

  return (
    <Panel
      title="POLYSIGNAL"
      titleControls={(
        <button
          type="button"
          className="wm-panel-help-button"
          aria-label="Explain PolySignal panel"
          aria-expanded={showHelp}
          onClick={() => setShowHelp((value) => !value)}
        >
          ?
        </button>
      )}
      badge={badgeLabel(payload)}
      status={panelStatus(payload)}
      count={items.length || undefined}
      headerOverlay={showHelp ? (
        <div className="wm-panel-help-popover">
          <strong>PolySignal MVP</strong>
          <p>Clusters recent Polymarket fills, profiles participating wallets, attaches related intel, and generates a short flow explanation.</p>
        </div>
      ) : null}
      className="wm-market-panel wm-polysignal-panel"
      dataPanelId="polysignal-feed"
    >
      <div className="wm-polysignal-layout">
        {top ? (
          <div className={`wm-polysignal-hero ${signalBias(top)}`}>
            <div>
              <span>TOP FLOW</span>
              <strong>{actionLabel(top)}</strong>
            </div>
            <em>{formatCurrencyCompact(metricValue(top, 'totalNotional') || top.notional)} / {probabilityLabel(metricValue(top, 'currentProbability') || top.price)}</em>
          </div>
        ) : null}
        {items.length ? (
          <div className="wm-polysignal-list">
            {items.map((item, index) => {
              const itemId = item.id || `${item.marketId || 'market'}-${item.outcome || 'outcome'}-${index}`;
              const marketId = Number(item.marketId);
              return (
                <PolySignalRow
                  key={itemId}
                  item={item}
                  active={expandedId === itemId || (Number.isFinite(marketId) && selectedMarketId === marketId)}
                  onToggle={() => setExpandedId((current) => current === itemId ? null : itemId)}
                  onSelect={() => Number.isFinite(marketId) && marketId > 0 && setSelectedMarketId(marketId)}
                />
              );
            })}
          </div>
        ) : (
          <div className="wm-empty-state">
            <strong>No PolySignal clusters yet.</strong>
            <em>Recent trade flow, wallet profiles, or snapshot cache may still be warming.</em>
          </div>
        )}
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap<'selectedMarketId' | 'setSelectedMarketId'> = {
  'polysignal-feed': {
    render: (ctx) => {
      const payload = ctx.runtimeData['polysignal-feed'] as RuntimePolySignalPayload | undefined;
      return (
        <PolySignalFeedPanel
          payload={payload}
          selectedMarketId={ctx.selectedMarketId}
          setSelectedMarketId={ctx.setSelectedMarketId}
        />
      );
    },
  },
};

export const panel = runtimePanelFromRenderer(renderers, {
  contextKeys: ['selectedMarketId', 'setSelectedMarketId'],
  id: 'polysignal-feed',
  title: 'PolySignal',
  eyebrow: 'signal',
  description: 'Smart-money flow, wallet history, and explainable market briefs.',
  defaultEnabled: true,
}, {
  tier: 'slow',
  intervalMs: 120000,
  limit: 8,
  fetchData: (context, limit) => fetchRuntimePolySignal(limit, context?.signal),
});
