import { Panel } from '@/components/Panel';
import type { OraclePayload, PanelRenderContext } from '@/types';
import type { PanelRenderMap } from './types';
import { AiMarketWidePanel } from './shared/ai-market-wide';
import { oracleList } from './shared/renderers';
import { formatRelative, shortHash } from './shared/formatters';
import { globalOracle } from './shared/selectors';

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

function focusedOracleStatus(ctx: PanelRenderContext, payload: OraclePayload) {
  const marketTitle = ctx.bundle?.market?.title || ctx.selectedMarket?.title || ctx.bundle?.group?.title || ctx.selectedMarketGroupDetail?.title || ctx.selectedMarketGroup?.title || 'Selected market';
  const status = payload.completionStatus || (payload.isFinal ? 'SETTLED' : payload.isTradingClosed ? 'CLOSED' : 'OPEN');
  const outcome = payload.settlementOutcome && payload.settlementOutcome !== 'UNKNOWN' ? payload.settlementOutcome : 'Awaiting oracle';
  const bound = payload.questionId || payload.conditionId || payload.gammaMarketId ? 'Yes' : 'No';
  const updatedAt = ctx.selectedMarket?.endDate || ctx.bundle?.market?.endDate || null;
  const createdAt = ctx.bundle?.market?.createdAt || ctx.selectedMarket?.createdAt || ctx.bundle?.group?.createdAt || ctx.selectedMarketGroupDetail?.createdAt || ctx.selectedMarketGroup?.createdAt || null;
  const closedAt = ctx.bundle?.market?.endDate || ctx.selectedMarket?.endDate || ctx.bundle?.group?.endDate || ctx.selectedMarketGroupDetail?.endDate || ctx.selectedMarketGroup?.endDate || null;
  const proposedEvent = (payload.timeline || []).find((event) => String(event.eventStatus || '').toLowerCase().includes('propose'));
  const finalizedEvent = (payload.timeline || []).find((event) => String(event.eventStatus || '').toLowerCase().includes('settle') || event.isFinal);
  const lifecycle = [
    { label: 'Created', time: createdAt, active: true, done: Boolean(createdAt) },
    { label: 'Trading open', time: createdAt, active: !payload.isTradingClosed && !payload.isResolved, done: !payload.isTradingClosed && !payload.isResolved },
    { label: 'Closed', time: closedAt, active: payload.isTradingClosed && !payload.isResolved, done: payload.isTradingClosed || payload.isResolved },
    { label: 'Awaiting oracle', time: closedAt, active: payload.isTradingClosed && !payload.isResolved, done: Boolean(proposedEvent || payload.isResolved) },
    { label: 'Submitted', time: proposedEvent?.eventTime || null, active: Boolean(proposedEvent && !payload.isFinal), done: Boolean(proposedEvent) },
    { label: 'Finalized', time: finalizedEvent?.eventTime || null, active: Boolean(payload.isFinal), done: Boolean(payload.isFinal) },
  ];
  return (
    <div className="wm-oracle-shell focused">
      <div className="wm-oracle-focused-status-list" aria-label="oracle status summary">
        <div><span>Status</span><strong>{status}</strong></div>
        <div><span>Resolution</span><strong>{payload.isResolved ? outcome : 'Unresolved'}</strong></div>
        <div><span>Bound</span><strong>{bound}</strong></div>
        <div><span>Events</span><strong>{payload.timeline?.length || 0}</strong></div>
      </div>
      <div className="wm-oracle-lifecycle" aria-label="oracle lifecycle">
        {lifecycle.map((step) => (
          <div className={`wm-oracle-lifecycle-step${step.done ? ' done' : ''}${step.active ? ' active' : ''}`} key={step.label}>
            <span aria-hidden="true" />
            <strong>{step.label}</strong>
            <em>{step.time ? formatRelative(step.time) : 'pending'}</em>
          </div>
        ))}
      </div>
      <article className="wm-oracle-focused-card">
        <div className="wm-oracle-focused-heading">
          <span className={`wm-oracle-stage-dot ${payload.isFinal ? 'positive' : payload.isTradingClosed ? 'warning' : 'neutral'}`} aria-hidden="true" />
          <strong>Market</strong>
          <em className="wm-oracle-awaiting-badge">{payload.isResolved ? 'resolved' : 'awaiting oracle'}</em>
        </div>
        <div className="wm-oracle-market-title">{marketTitle}</div>
        <div className="wm-oracle-focused-table" aria-label="oracle details">
          <div><span>Source</span><strong>{payload.settlementSource || 'market'}</strong></div>
          <div><span>QID</span><strong>{shortHash(payload.questionId || payload.conditionId || '', 8, 5) || '--'}</strong></div>
          <div><span>Oracle</span><strong>{shortHash(payload.oracle || '', 8, 5) || '--'}</strong></div>
          <div><span>Updated</span><strong>{formatRelative(updatedAt)}</strong></div>
          <div><span>Market</span><strong>{payload.localMarketId || payload.marketId ? `#${payload.localMarketId || payload.marketId}` : '--'}</strong></div>
        </div>
      </article>
    </div>
  );
}

export const oraclePanelRenderers: PanelRenderMap = {
  'oracle-feed': {
    render: (ctx) => {
      const focused = focusedOraclePayload(ctx);
      const events = focused?.timeline?.length ? focused.timeline : globalOracle(ctx);
      return (
        <Panel title={focused ? 'Oracle Status' : 'Oracle Feed'} badge={focused ? 'Bound' : 'Live'} status="live" count={focused ? (focused.timeline?.length || 0) : globalOracle(ctx).length} className="wm-oracle-feed-panel">
          {focused
            ? (focused.timeline?.length ? oracleList(focused.timeline, 10, 'timeline') : focusedOracleStatus(ctx, focused))
            : oracleList(events, 10)}
        </Panel>
      );
    },
  },
  'oracle-timeline': {
    render: (ctx) => (
      <AiMarketWidePanel ctx={ctx} lens="trend" title="TREND WATCH" badge="TREND" />
    ),
  },
};
