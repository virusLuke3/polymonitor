import type { PanelInputs } from '../../types';
import { Panel } from '@/components/Panel';
import type { PanelRenderMap } from '@/panels/types';
import { globalMarkets } from '@/panels/shared/selectors';
import { useI18n } from '@/services/i18n';
import { localizedCompact, MarketI18n, localizedCurrency, localizedPercent, groupDisplayTradeCount, sumFiniteValues, firstFiniteValue, groupDisplayVolume, uniqueGroupOutcomes } from '../../shared/market-values';
import { panelFromRenderer } from '@/panels/definePanel';

type Inputs = PanelInputs<'bootstrap' | 'bundle' | 'marketGroups' | 'markets' | 'selectedMarket' | 'selectedMarketGroupDetail' | 'selectedMarketGroupId' | 'selectedMarketGroupOutcomeKey' | 'selectedMarketId'>;

function complementPrice(value?: string | number | null) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return null;
  return Math.max(0, Math.min(1, 1 - numeric));
}

function statusTone(status?: string | null) {
  const normalized = String(status || '').toLowerCase();
  if (/active|open|live|trading/.test(normalized)) return 'active';
  if (/closed|resolved|settled|final/.test(normalized)) return 'settled';
  if (/paused|halt|pending|standby/.test(normalized)) return 'pending';
  return 'neutral';
}

function marketSummaryOracleHint(ctx: Inputs, endDate: string | null | undefined, i18n: MarketI18n) {
  const timeline = ctx.bundle?.oracle?.timeline || [];
  const latest = timeline[0] || null;
  if (latest?.settledPrice !== null && latest?.settledPrice !== undefined && latest?.settledPrice !== '') {
    return i18n.t('atlasMarket.settledAt', { price: localizedPercent(latest.settledPrice, i18n) });
  }
  if (latest?.proposedPrice !== null && latest?.proposedPrice !== undefined && latest?.proposedPrice !== '') {
    return i18n.t('atlasMarket.oracleProposed', { price: localizedPercent(latest.proposedPrice, i18n) });
  }
  if (ctx.bundle?.oracle?.currentStatus) {
    return i18n.t('atlasMarket.oracleStatus', { status: ctx.bundle.oracle.currentStatus });
  }
  if (endDate) {
    return i18n.t('atlasMarket.awaitingAfter', { date: i18n.formatDateTime(endDate) });
  }
  return i18n.t('atlasMarket.oraclePending');
}

function resolveFocusedMarketContext(ctx: Inputs) {
  const selectedGroup = ctx.selectedMarketGroupDetail
    || ctx.bundle?.group
    || ctx.marketGroups.find((group) => {
      const eventId = group.eventId != null ? String(group.eventId) : null;
      const groupOutcomeMarketIds = [...(group.outcomes || []), ...(group.topOutcomes || [])]
        .map((outcome) => Number(outcome.marketId))
        .filter(Number.isFinite);
      return (eventId && eventId === ctx.selectedMarketGroupId)
        || (ctx.selectedMarketId != null && (Number(group.defaultMarketId) === ctx.selectedMarketId || groupOutcomeMarketIds.includes(ctx.selectedMarketId)));
    })
    || null;
  const bundleOutcomeMatches = ctx.bundle?.selectedOutcome && ctx.selectedMarketId != null
    && Number(ctx.bundle.selectedOutcome.marketId) === ctx.selectedMarketId;
  const selectedOutcome = bundleOutcomeMatches
    ? ctx.bundle?.selectedOutcome || null
    : selectedGroup
      ? ((selectedGroup.outcomes?.length ? selectedGroup.outcomes : selectedGroup.topOutcomes) || []).find((outcome) => (
        ctx.selectedMarketId != null && Number(outcome.marketId) === ctx.selectedMarketId
      )) || ((selectedGroup.outcomes?.length ? selectedGroup.outcomes : selectedGroup.topOutcomes) || []).find((outcome) => (
        ctx.selectedMarketGroupOutcomeKey && outcome.outcomeKey === ctx.selectedMarketGroupOutcomeKey
      )) || null
      : null;
  const bundleMarketMatches = ctx.bundle?.market?.id != null && ctx.selectedMarketId != null && Number(ctx.bundle.market.id) === Number(ctx.selectedMarketId);
  const selected = (bundleMarketMatches ? ctx.bundle?.market : null) || ctx.selectedMarket || ctx.bootstrap?.featuredMarket || null;
  const listMarket = globalMarkets(ctx).find((market) => market.id === ctx.selectedMarketId) || null;
  const price = ctx.bundle?.price || ctx.bootstrap?.pricePreview || null;
  return { selectedGroup, selectedOutcome, selected, listMarket, price };
}

function MarketSummaryPanel({ ctx }: { ctx: Inputs }) {
  const i18n = useI18n();
  const { t } = i18n;
  const { selectedGroup, selectedOutcome, selected, listMarket, price } = resolveFocusedMarketContext(ctx);
  const yesPrice = selectedOutcome?.yesPrice ?? price?.latestYesPrice ?? selected?.latestYesPrice ?? price?.latestPrice ?? selected?.latestPrice;
  const noPrice = selectedOutcome?.noPrice ?? price?.latestNoPrice ?? selected?.latestNoPrice ?? complementPrice(yesPrice);
  const groupOutcomes = selectedGroup ? uniqueGroupOutcomes([...(selectedGroup.outcomes || []), ...(selectedGroup.topOutcomes || [])]) : [];
  const groupOutcomeVolume24h = sumFiniteValues(groupOutcomes.map((outcome) => outcome.volume24h));
  const groupOutcomeTradeCount24h = sumFiniteValues(groupOutcomes.map((outcome) => outcome.tradeCount24h));
  const volume24h = firstFiniteValue(selectedOutcome?.volume24h, selectedGroup ? groupDisplayVolume(selectedGroup) : null, groupOutcomeVolume24h, listMarket?.volume24h, price?.volume24h);
  const tradeCount24h = firstFiniteValue(selectedOutcome?.tradeCount24h, selectedGroup ? groupDisplayTradeCount(selectedGroup) : null, groupOutcomeTradeCount24h, listMarket?.tradeCount24h, price?.tradeCount24h);
  const status = selected?.status || listMarket?.status || t('atlasOracle.market');
  const endDate = selectedGroup?.endDate || selected?.endDate || listMarket?.endDate || null;
  const oracleHint = marketSummaryOracleHint(ctx, endDate, i18n);
  const statusClass = statusTone(status);
  const marketTitle = selectedGroup?.title || selected?.title || t('atlasMarket.noSelection');
  return (
    <Panel title={t('atlasMarket.summary')} badge={status} status="live" className="wm-market-panel wm-market-summary-panel">
      <div className="wm-market-summary">
        <section className="wm-market-summary-hero">
          <div className="wm-market-summary-kicker">
            <span>{selectedGroup?.category || selected?.category || listMarket?.category || t('atlasOracle.market')}</span>
            <em>{endDate ? i18n.formatRelativeTime(endDate) : t('atlasMarket.rolling')}</em>
          </div>
          <strong title={marketTitle}>{marketTitle}</strong>
        </section>

        <div className="wm-market-summary-prices" aria-label={t('atlasMarket.currentPrices')}>
          <article className="yes">
            <span>YES</span>
            <strong>{localizedPercent(yesPrice, i18n)}</strong>
          </article>
          <article className="no">
            <span>NO</span>
            <strong>{localizedPercent(noPrice, i18n)}</strong>
          </article>
        </div>

        <div className="wm-market-summary-grid">
          <article>
            <span>{t('atlasMarket.volume24h')}</span>
            <strong>{localizedCurrency(volume24h, i18n)}</strong>
          </article>
          <article>
            <span>{t('atlasMarket.trades24h')}</span>
            <strong>{localizedCompact(tradeCount24h, i18n)}</strong>
          </article>
          <article>
            <span>{t('atlasMarket.ends')}</span>
            <strong>{endDate ? i18n.formatDateTime(endDate) : '--'}</strong>
          </article>
          <article>
            <span>{t('atlasMarket.status')}</span>
            <strong className={`wm-market-status-value ${statusClass}`}>{status}</strong>
          </article>
        </div>

        <div className="wm-market-summary-oracle">
          <span>{t('atlasMarket.oracleResolution')}</span>
          <strong title={oracleHint}>{oracleHint}</strong>
        </div>
      </div>
    </Panel>
  );
}

const renderers: PanelRenderMap<'bootstrap' | 'bundle' | 'marketGroups' | 'markets' | 'selectedMarket' | 'selectedMarketGroupDetail' | 'selectedMarketGroupId' | 'selectedMarketGroupOutcomeKey' | 'selectedMarketId'> = {
  'market-summary': {
    render: (ctx) => <MarketSummaryPanel ctx={ctx} />,
  },
};

export const panel = panelFromRenderer(renderers, {
  contextKeys: ['bootstrap', 'bundle', 'marketGroups', 'markets', 'selectedMarket', 'selectedMarketGroupDetail', 'selectedMarketGroupId', 'selectedMarketGroupOutcomeKey', 'selectedMarketId'],
  id: 'market-summary',
  title: 'Market Summary',
  eyebrow: 'market',
  description: 'Identifiers, category, timing, and pricing.',
  defaultEnabled: true,
});
