import { Panel } from '@/components/Panel';
import type { OraclePayload, PanelRenderContext } from '@/types';
import type { PanelRenderMap } from './types';
import { AiMarketWidePanel } from './shared/ai-market-wide';
import { oracleList } from './shared/renderers';
import { shortHash } from './shared/formatters';
import { globalOracle } from './shared/selectors';
import { useI18n } from '@/services/i18n';

type OracleI18n = ReturnType<typeof useI18n>;

function focusedOraclePayload(ctx: PanelRenderContext): OraclePayload | null {
  if (ctx.selectedMarketId && ctx.bundle?.oracle) {
    const oracleMarketId = Number(ctx.bundle.oracle.localMarketId ?? ctx.bundle.oracle.marketId);
    if (Number.isFinite(oracleMarketId) && oracleMarketId === Number(ctx.selectedMarketId)) {
      return ctx.bundle.oracle;
    }
  }
  const selectedGroup = ctx.selectedMarketGroupDetail || ctx.bundle?.group || ctx.selectedMarketGroup;
  const selectedOutcome = (
    ctx.bundle?.selectedOutcome && ctx.selectedMarketId != null && Number(ctx.bundle.selectedOutcome.marketId) === ctx.selectedMarketId
      ? ctx.bundle.selectedOutcome
      : null
  ) || (
    (selectedGroup?.outcomes || []).find((outcome) => ctx.selectedMarketId != null && Number(outcome.marketId) === ctx.selectedMarketId)
    || (selectedGroup?.topOutcomes || []).find((outcome) => ctx.selectedMarketId != null && Number(outcome.marketId) === ctx.selectedMarketId)
    || (selectedGroup?.outcomes || []).find((outcome) => outcome.outcomeKey === ctx.selectedMarketGroupOutcomeKey)
    || (selectedGroup?.topOutcomes || []).find((outcome) => outcome.outcomeKey === ctx.selectedMarketGroupOutcomeKey)
    || null
  );
  if (!selectedOutcome && !ctx.selectedMarketId) return null;
  return {
    marketId: Number(selectedOutcome?.marketId || ctx.selectedMarketId || 0),
    localMarketId: selectedOutcome?.marketId ?? ctx.selectedMarketId ?? null,
    gammaMarketId: selectedOutcome?.gammaMarketId ?? ctx.bundle?.market?.gammaMarketId ?? ctx.selectedMarket?.gammaMarketId ?? null,
    conditionId: selectedOutcome?.conditionId ?? ctx.selectedMarket?.conditionId ?? ctx.bundle?.market?.conditionId ?? null,
    questionId: ctx.selectedMarket?.questionId ?? ctx.bundle?.market?.questionId ?? null,
    oracle: ctx.selectedMarket?.oracle ?? ctx.bundle?.market?.oracle ?? null,
    currentStatus: ctx.selectedMarket?.status ?? 'OPEN',
    completionStatus: 'OPEN',
    isTradingClosed: false,
    isResolved: false,
    isFinal: false,
    settlementOutcome: 'UNKNOWN',
    settlementSource: selectedOutcome?.marketId ? 'market' : 'gamma-event',
    timeline: [],
  };
}

function focusedOracleStatus(ctx: PanelRenderContext, payload: OraclePayload, i18n: OracleI18n) {
  const { t } = i18n;
  const marketTitle = ctx.bundle?.market?.title || ctx.selectedMarket?.title || ctx.bundle?.group?.title || ctx.selectedMarketGroupDetail?.title || ctx.selectedMarketGroup?.title || t('atlasOracle.selectedMarket');
  const status = payload.completionStatus || (payload.isFinal ? 'SETTLED' : payload.isTradingClosed ? 'CLOSED' : 'OPEN');
  const outcome = payload.settlementOutcome && payload.settlementOutcome !== 'UNKNOWN' ? payload.settlementOutcome : t('atlasOracle.awaiting');
  const bound = payload.questionId || payload.conditionId || payload.gammaMarketId ? t('atlasOracle.yes') : t('atlasOracle.no');
  const updatedAt = ctx.selectedMarket?.endDate || ctx.bundle?.market?.endDate || null;
  const createdAt = ctx.bundle?.market?.createdAt || ctx.selectedMarket?.createdAt || ctx.bundle?.group?.createdAt || ctx.selectedMarketGroupDetail?.createdAt || ctx.selectedMarketGroup?.createdAt || null;
  const closedAt = ctx.bundle?.market?.endDate || ctx.selectedMarket?.endDate || ctx.bundle?.group?.endDate || ctx.selectedMarketGroupDetail?.endDate || ctx.selectedMarketGroup?.endDate || null;
  const proposedEvent = (payload.timeline || []).find((event) => String(event.eventStatus || '').toLowerCase().includes('propose'));
  const finalizedEvent = (payload.timeline || []).find((event) => String(event.eventStatus || '').toLowerCase().includes('settle') || event.isFinal);
  const lifecycle = [
    { label: t('atlasOracle.created'), time: createdAt, active: true, done: Boolean(createdAt) },
    { label: t('atlasOracle.tradingOpen'), time: createdAt, active: !payload.isTradingClosed && !payload.isResolved, done: !payload.isTradingClosed && !payload.isResolved },
    { label: t('atlasOracle.closed'), time: closedAt, active: payload.isTradingClosed && !payload.isResolved, done: payload.isTradingClosed || payload.isResolved },
    { label: t('atlasOracle.awaiting'), time: closedAt, active: payload.isTradingClosed && !payload.isResolved, done: Boolean(proposedEvent || payload.isResolved) },
    { label: t('atlasOracle.submitted'), time: proposedEvent?.eventTime || null, active: Boolean(proposedEvent && !payload.isFinal), done: Boolean(proposedEvent) },
    { label: t('atlasOracle.finalized'), time: finalizedEvent?.eventTime || null, active: Boolean(payload.isFinal), done: Boolean(payload.isFinal) },
  ];
  return (
    <div className="wm-oracle-shell focused">
      <div className="wm-oracle-focused-status-list" aria-label={t('atlasOracle.statusTitle')}>
        <div><span>{t('atlasOracle.status')}</span><strong>{status}</strong></div>
        <div><span>{t('atlasOracle.resolution')}</span><strong>{payload.isResolved ? outcome : t('atlasOracle.unresolved')}</strong></div>
        <div><span>{t('atlasOracle.bound')}</span><strong>{bound}</strong></div>
        <div><span>{t('atlasOracle.events')}</span><strong>{i18n.formatNumber(payload.timeline?.length || 0)}</strong></div>
      </div>
      <div className="wm-oracle-lifecycle" aria-label={t('atlasOracle.statusTitle')}>
        {lifecycle.map((step) => (
          <div className={`wm-oracle-lifecycle-step${step.done ? ' done' : ''}${step.active ? ' active' : ''}`} key={step.label}>
            <span aria-hidden="true" />
            <strong>{step.label}</strong>
            <em>{step.time ? i18n.formatRelativeTime(step.time) : t('atlasOracle.pending')}</em>
          </div>
        ))}
      </div>
      <article className="wm-oracle-focused-card">
        <div className="wm-oracle-focused-heading">
          <span className={`wm-oracle-stage-dot ${payload.isFinal ? 'positive' : payload.isTradingClosed ? 'warning' : 'neutral'}`} aria-hidden="true" />
          <strong>{t('atlasOracle.market')}</strong>
          <em className="wm-oracle-awaiting-badge">{payload.isResolved ? t('atlasOracle.resolved') : t('atlasOracle.awaitingLower')}</em>
        </div>
        <div className="wm-oracle-market-title">{marketTitle}</div>
        <div className="wm-oracle-focused-table" aria-label={t('atlasOracle.details')}>
          <div><span>{t('atlasOracle.source')}</span><strong>{payload.settlementSource || 'market'}</strong></div>
          <div><span>QID</span><strong>{shortHash(payload.questionId || payload.conditionId || '', 8, 5) || '--'}</strong></div>
          <div><span>Oracle</span><strong>{shortHash(payload.oracle || '', 8, 5) || '--'}</strong></div>
          <div><span>{t('atlasOracle.updated')}</span><strong>{i18n.formatRelativeTime(updatedAt)}</strong></div>
          <div><span>{t('atlasOracle.market')}</span><strong>{payload.localMarketId || payload.marketId ? `#${payload.localMarketId || payload.marketId}` : '--'}</strong></div>
        </div>
      </article>
    </div>
  );
}

function OracleFeedPanel({ ctx }: { ctx: PanelRenderContext }) {
  const i18n = useI18n();
  const { t } = i18n;
  const focused = focusedOraclePayload(ctx);
  const events = focused?.timeline?.length ? focused.timeline : globalOracle(ctx);
  const copy = {
    noActivity: t('atlasOracle.noActivity'),
    finalCount: (count: number) => t('atlasOracle.finalCount', { count: i18n.formatNumber(count) }),
    proposedCount: (count: number) => t('atlasOracle.proposedCount', { count: i18n.formatNumber(count) }),
    boundCount: (count: number) => t('atlasOracle.boundCount', { count: i18n.formatNumber(count) }),
    finalized: t('atlasOracle.finalized'),
    finalizedOutcome: (outcome: string) => t('atlasOracle.finalizedOutcome', { outcome }),
    disputed: t('atlasOracle.disputed'),
    proposed: t('atlasOracle.proposed'),
    requested: t('atlasOracle.requested'),
    event: t('atlasOracle.event'),
    pending: t('atlasOracle.pendingOutcome'),
    unboundEvent: t('atlasOracle.unboundEvent'),
    unbound: t('atlasOracle.unbound'),
    marketNumber: (id: number | string) => t('atlasOracle.marketNumber', { id }),
    formatRelative: (value?: string | null) => i18n.formatRelativeTime(value),
    formatDate: (value?: string | null) => value ? i18n.formatDateTime(value) : '--',
    empty: {
      label: t('atlasShared.standby'),
      detail: t('atlasShared.emptyDetail'),
    },
  };
  return (
    <Panel
      title={focused ? t('atlasOracle.statusTitle') : t('atlasOracle.feedTitle')}
      badge={focused ? t('atlasOracle.bound') : t('atlasOracle.live')}
      status="live"
      count={focused ? (focused.timeline?.length || 0) : globalOracle(ctx).length}
      className="wm-oracle-feed-panel"
    >
      {focused
        ? (focused.timeline?.length ? oracleList(focused.timeline, 10, 'timeline', copy) : focusedOracleStatus(ctx, focused, i18n))
        : oracleList(events, 10, 'feed', copy)}
    </Panel>
  );
}

export const oraclePanelRenderers: PanelRenderMap = {
  'oracle-feed': {
    render: (ctx) => <OracleFeedPanel ctx={ctx} />,
  },
  'oracle-timeline': {
    render: (ctx) => (
      <AiMarketWidePanel ctx={ctx} lens="trend" title="TREND WATCH" badge="TREND" />
    ),
  },
};
