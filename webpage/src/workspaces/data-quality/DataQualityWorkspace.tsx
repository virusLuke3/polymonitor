import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { MobileWorkspaceNav } from '@/components/MobileWorkspaceNav';
import {
  formatAge,
  MetricCard,
  StatusBadge,
  type OperationalTone,
} from '@/components/design-system/StatusPrimitives';
import {
  formatCompact,
  formatDate,
  formatRelative,
  shortHash,
} from '@/panels/shared/formatters';
import { fetchMarketDataQuality } from '@/services/api';
import { useI18n } from '@/services/i18n';
import type {
  MarketDataQualityDimension,
  MarketDataQualityGap,
  MarketDataQualityLifecycleStage,
  MarketDataQualityPayload,
  MarketDataQualityWatermark,
  OracleEvent,
} from '@/types';

const REFRESH_INTERVAL_MS = 60_000;
const MAX_VISIBLE_ORACLE_EVENTS = 16;

function statusTone(status?: string | null): OperationalTone {
  const normalized = String(status || '').trim().toLowerCase();
  if (['critical', 'error', 'missing', 'stale'].includes(normalized)) return 'critical';
  if (['warning', 'degraded', 'aging', 'partial'].includes(normalized)) return 'warning';
  if (['ok', 'fresh', 'ready', 'observed'].includes(normalized)) return 'positive';
  return 'neutral';
}

function parseTimestamp(value?: string | null): number | null {
  const parsed = Date.parse(String(value || ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function ageSeconds(value?: string | null): number | null {
  const parsed = parseTimestamp(value);
  return parsed == null ? null : Math.max(0, Math.round((Date.now() - parsed) / 1_000));
}

function cleanLabel(value?: string | null): string {
  return String(value || 'unknown')
    .replace(/[_-]/g, ' ')
    .replace(/\b\w/g, (character: string) => character.toUpperCase());
}

function formatCoverage(value?: number | null): string {
  return value == null || !Number.isFinite(value) ? '--' : `${value.toFixed(value >= 99 ? 1 : 2)}%`;
}

function formatCount(value?: number | null): string {
  return value == null ? 'NOT COLLECTED' : formatCompact(value);
}

function qualityStateLabel(payload: MarketDataQualityPayload | null): string {
  if (!payload) return 'LOADING';
  return String(payload.status || 'unknown').toUpperCase();
}

function DimensionCard({ item }: { item: MarketDataQualityDimension }) {
  const value = Number(item.coveragePct);
  const hasCoverage = Number.isFinite(value);
  return (
    <article className={`quality-dimension is-${statusTone(item.status)}`}>
      <div className="quality-dimension-heading">
        <div>
          <span>{item.source}</span>
          <strong>{item.label}</strong>
        </div>
        <StatusBadge label={String(item.status || 'unknown').toUpperCase()} tone={statusTone(item.status)} compact />
      </div>
      <div className="quality-dimension-value">
        <strong>{formatCoverage(item.coveragePct)}</strong>
        {item.ageSeconds != null ? <span>{formatAge(item.ageSeconds)} old</span> : null}
      </div>
      <progress max={100} value={hasCoverage ? Math.max(0, Math.min(100, value)) : 0}>
        {formatCoverage(item.coveragePct)}
      </progress>
      <p>{item.detail || 'No quality definition published.'}</p>
      <div className="quality-dimension-foot">
        {item.denominator ? (
          <span>{formatCompact(item.numerator || 0)} / {formatCompact(item.denominator)} records</span>
        ) : (
          <span>{item.observedAt ? `Observed ${formatRelative(item.observedAt)}` : 'No observation timestamp'}</span>
        )}
        <time>{item.observedAt ? formatDate(item.observedAt) : '--'}</time>
      </div>
    </article>
  );
}

function GapLedger({ gaps }: { gaps: MarketDataQualityGap[] }) {
  return (
    <section className="quality-card quality-gap-card">
      <div className="quality-section-heading">
        <div>
          <span>Fail-open is forbidden</span>
          <h2>Active gap ledger</h2>
        </div>
        <StatusBadge
          label={`${gaps.length} GAP${gaps.length === 1 ? '' : 'S'}`}
          tone={gaps.some((gap) => gap.severity === 'critical') ? 'critical' : (gaps.length ? 'warning' : 'positive')}
        />
      </div>
      <div className="quality-gap-list">
        {gaps.map((gap, index) => (
          <article className={`quality-gap-row is-${statusTone(gap.severity)}`} key={gap.id}>
            <span className="quality-gap-index">{String(index + 1).padStart(2, '0')}</span>
            <div>
              <strong>{gap.label}</strong>
              <p>{gap.detail}</p>
              <em>{gap.source}{gap.observedAt ? ` · ${formatRelative(gap.observedAt)}` : ''}</em>
            </div>
            <div className="quality-gap-count">
              <StatusBadge label={gap.severity.toUpperCase()} tone={statusTone(gap.severity)} compact />
              <strong>{formatCompact(gap.count)}</strong>
            </div>
          </article>
        ))}
        {!gaps.length ? (
          <div className="quality-empty-state">
            <strong>No active contract gaps</strong>
            <span>All published quality dimensions meet their declared thresholds.</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function LifecycleRail({ stages }: { stages: MarketDataQualityLifecycleStage[] }) {
  return (
    <section className="quality-card quality-lifecycle-card">
      <div className="quality-section-heading">
        <div>
          <span>Market state model</span>
          <h2>Lifecycle coverage</h2>
        </div>
        <p>Counts use different historical universes; this is a state audit, not a conversion funnel.</p>
      </div>
      <div className="quality-lifecycle-rail">
        {stages.map((stage, index) => (
          <article className={stage.status === 'not-collected' ? 'is-missing' : ''} key={stage.id}>
            <span className="quality-lifecycle-index">{String(index + 1).padStart(2, '0')}</span>
            <div>
              <strong>{stage.label}</strong>
              <b>{formatCount(stage.count)}</b>
              <p>{stage.detail}</p>
              <em>{stage.source}</em>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function OracleStageRail({ payload }: { payload: MarketDataQualityPayload }) {
  const stages = payload.oracleLifecycle.stages;
  const maximum = Math.max(...stages.map((stage) => stage.count), 1);
  return (
    <section className="quality-card quality-oracle-card">
      <div className="quality-section-heading">
        <div>
          <span>UMA / Neg-risk observations</span>
          <h2>Oracle lifecycle</h2>
        </div>
        <StatusBadge
          label={payload.dimensions.find((item) => item.id === 'oracle-freshness')?.status.toUpperCase() || 'UNKNOWN'}
          tone={statusTone(payload.dimensions.find((item) => item.id === 'oracle-freshness')?.status)}
        />
      </div>
      <div className="quality-oracle-stage-rail">
        {stages.map((stage, index) => (
          <article key={stage.id}>
            <span>{String(index + 1).padStart(2, '0')}</span>
            <div>
              <strong>{stage.label}</strong>
              <b>{formatCompact(stage.count)}</b>
              <progress max={maximum} value={stage.count}>{stage.count}</progress>
            </div>
          </article>
        ))}
      </div>
      <div className="quality-oracle-contract">
        <span>Durable identity <b>tx_hash + log_index</b></span>
        <span>Canonical order <b>block_number + log_index</b></span>
        <span>Latest block <b>{formatCompact(Number(payload.oracleLifecycle.latestBlock || 0))}</b></span>
        <span>Latest event <b>{formatRelative(payload.oracleLifecycle.latestEventAt)}</b></span>
      </div>
    </section>
  );
}

function WatermarkBoard({ watermarks }: { watermarks: MarketDataQualityWatermark[] }) {
  const stateDetail = (watermark: MarketDataQualityWatermark) => {
    if (!watermark.state || typeof watermark.state !== 'object') return String(watermark.state || 'No structured state');
    const state = watermark.state as Record<string, unknown>;
    return [state.status, state.phase, state.error].filter(Boolean).join(' · ') || 'Structured checkpoint';
  };
  return (
    <section className="quality-card quality-watermark-card">
      <div className="quality-section-heading">
        <div>
          <span>Application checkpoints</span>
          <h2>Sync watermarks</h2>
        </div>
      </div>
      <div className="quality-watermark-list">
        {watermarks.map((watermark) => {
          const freshness = ageSeconds(watermark.updatedAt);
          const stale = freshness == null || freshness > 7 * 86_400;
          return (
            <article key={watermark.id}>
              <div>
                <span>{cleanLabel(watermark.id)}</span>
                <strong>Block {formatCompact(Number(watermark.lastBlock || 0))}</strong>
              </div>
              <StatusBadge
                label={stale ? `STALE · ${formatAge(freshness)}` : `OBSERVED · ${formatAge(freshness)}`}
                tone={stale ? 'critical' : 'positive'}
                compact
              />
              <p>{stateDetail(watermark)}</p>
              <time>{formatDate(watermark.updatedAt)}</time>
            </article>
          );
        })}
        {!watermarks.length ? <div className="quality-empty-state"><strong>No sync checkpoints</strong></div> : null}
      </div>
    </section>
  );
}

function RecentOracleTable({ events }: { events: OracleEvent[] }) {
  const visible = events.slice(0, MAX_VISIBLE_ORACLE_EVENTS);
  return (
    <section className="quality-card quality-events-card">
      <div className="quality-section-heading">
        <div>
          <span>Latest indexed observations</span>
          <h2>Oracle event tape</h2>
        </div>
        <span>{visible.length} / {events.length} visible</span>
      </div>
      <div className="quality-table-wrap">
        <table className="quality-table">
          <thead>
            <tr>
              <th>Observed</th>
              <th>Stage</th>
              <th>Market</th>
              <th>Binding</th>
              <th>Block</th>
              <th>Durable key</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((event, index) => (
              <tr key={`${event.txHash || 'oracle'}-${event.logIndex ?? index}`}>
                <td><time>{formatDate(event.eventTime)}</time><small>{formatRelative(event.eventTime)}</small></td>
                <td><StatusBadge label={String(event.eventStatus || 'unknown').toUpperCase()} tone="info" compact /></td>
                <td>
                  {event.localMarketId ? (
                    <a href={`/markets/${event.localMarketId}`}>{event.marketTitle || `Market #${event.localMarketId}`}</a>
                  ) : (
                    <strong>{event.marketTitle || 'Unbound Oracle event'}</strong>
                  )}
                  <small>{event.marketCategory || event.completionStatus || 'Unknown category'}</small>
                </td>
                <td>
                  <StatusBadge label={event.isBound ? 'BOUND' : 'UNBOUND'} tone={event.isBound ? 'positive' : 'warning'} compact />
                  <small>{cleanLabel(event.matchedBy)}</small>
                </td>
                <td><code>{formatCompact(Number(event.blockNumber || 0))}</code></td>
                <td><code>{shortHash(event.txHash, 8, 5)}</code><small>log {event.logIndex ?? '--'}</small></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!visible.length ? <div className="quality-empty-state"><strong>No Oracle events indexed</strong></div> : null}
      </div>
    </section>
  );
}

function GapMarkets({ payload }: { payload: MarketDataQualityPayload }) {
  return (
    <section className="quality-card quality-gap-markets-card">
      <div className="quality-section-heading">
        <div>
          <span>Representative records</span>
          <h2>Awaiting Oracle</h2>
        </div>
        <span>{payload.gapMarkets.length} sampled</span>
      </div>
      <div className="quality-gap-market-list">
        {payload.gapMarkets.map((market) => (
          <a href={`/markets/${market.marketId}`} key={market.marketId}>
            <div>
              <span>Market / {market.marketId}</span>
              <strong>{market.title}</strong>
            </div>
            <div>
              <StatusBadge label={String(market.completionStatus || 'unknown').replace(/_/g, ' ')} tone="warning" compact />
              <em>{market.category || 'uncategorized'} · {formatRelative(market.observedAt)}</em>
            </div>
          </a>
        ))}
      </div>
    </section>
  );
}

export function DataQualityWorkspace() {
  const { locale, t } = useI18n();
  const [payload, setPayload] = useState<MarketDataQualityPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef(0);

  const refresh = useCallback(async () => {
    const requestId = ++requestRef.current;
    setLoading(true);
    const controller = new AbortController();
    try {
      const next = await fetchMarketDataQuality(controller.signal);
      if (requestId !== requestRef.current) return;
      setPayload(next);
      setError(null);
    } catch (caught) {
      if (requestId !== requestRef.current) return;
      setError(caught instanceof Error ? caught.message : t('quality.loadError'));
    } finally {
      if (requestId === requestRef.current) setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
    const interval = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(interval);
      requestRef.current += 1;
    };
  }, [refresh]);

  useEffect(() => {
    const previousTitle = document.title;
    document.title = t('quality.documentTitle');
    return () => {
      document.title = previousTitle;
    };
  }, [locale, t]);

  const dimensions = payload?.dimensions || [];
  const criticalCount = useMemo(
    () => dimensions.filter((item) => statusTone(item.status) === 'critical').length,
    [dimensions],
  );
  const oracleAge = ageSeconds(payload?.summary.latestOracleAt);
  const tradeAge = ageSeconds(payload?.summary.latestTradeAt);

  return (
    <div className="quality-shell">
      <header className="quality-topbar">
        <div className="quality-brand-cluster">
          <a className="quality-home-link" href="/">◎ {t('mobileNav.atlas')}</a>
          <div className="quality-brand">{t('quality.brand')} <span>{t('quality.brandDetail')}</span></div>
        </div>
        <div className="quality-actions">
          <a href="/docs/documentation/">{t('quality.docs')}</a>
          <button type="button" disabled={loading} onClick={() => void refresh()}>
            {loading ? t('quality.refreshing') : t('quality.refresh')}
          </button>
        </div>
      </header>

      <main className="quality-main">
        <section className="quality-hero">
          <div className="quality-hero-copy">
            <div className="quality-kicker-row">
              <span>{t('quality.kicker')}</span>
              <StatusBadge label={qualityStateLabel(payload)} tone={statusTone(payload?.status || 'loading')} />
            </div>
            <h1>{t('quality.titleLineOne')}<br />{t('quality.titleLineTwo')}</h1>
            <p>{t('quality.description')}</p>
            <div className="quality-hero-contract">
              <span>{t('quality.contract')} <b>{payload?.contractVersion || 'prediction-market-data-quality.v1'}</b></span>
              <span>{t('quality.generated')} <b>{payload ? formatRelative(payload.generatedAt) : t('quality.waiting')}</b></span>
            </div>
          </div>
          <div className="quality-score-lockup">
            <span>{t('quality.weightedReadiness')}</span>
            <strong>{payload ? payload.score.toFixed(1) : '--'}</strong>
            <em>/ 100</em>
            <progress max={100} value={payload?.score || 0}>{payload?.score || 0}</progress>
            <div>
              <span>{t('quality.critical')} <b>{criticalCount}</b></span>
              <span>{t('quality.gaps')} <b>{payload?.summary.activeGapCount ?? '--'}</b></span>
            </div>
          </div>
        </section>

        {error ? (
          <div className="quality-error-banner" role="alert">
            <span>{error}</span>
            <em>{payload ? t('quality.lastGood') : t('quality.retryApi')}</em>
          </div>
        ) : null}

        {payload ? (
          <>
            <section className="quality-metric-grid" aria-label={t('quality.summary')}>
              <MetricCard
                eyebrow={t('quality.canonicalMarkets')}
                value={formatCompact(payload.summary.marketCount)}
                detail={`${formatCompact(payload.summary.servingMarketCount)} in serving universe`}
                tone="info"
              />
              <MetricCard
                eyebrow={t('quality.oracleEvents')}
                value={formatCompact(payload.summary.oracleEventCount)}
                detail={`${formatCompact(payload.summary.oracleBoundMarketCount)} bound markets`}
                tone="info"
              />
              <MetricCard
                eyebrow={t('quality.recentlyTraded')}
                value={formatCompact(payload.summary.recentlyTradedMarketCount)}
                detail={`Latest OrderFilled ${formatAge(tradeAge)} ago`}
                tone={tradeAge != null && tradeAge <= 900 ? 'positive' : 'warning'}
              />
              <MetricCard
                eyebrow={t('quality.oracleWatermark')}
                value={formatAge(oracleAge)}
                detail={`Latest event ${formatDate(payload.summary.latestOracleAt)}`}
                tone={oracleAge != null && oracleAge <= 7 * 86_400 ? 'warning' : 'critical'}
              />
              <MetricCard
                eyebrow={t('quality.publishedGaps')}
                value={String(payload.summary.activeGapCount)}
                detail={`${payload.summary.criticalDimensionCount} critical · ${payload.summary.warningDimensionCount} warning`}
                tone={payload.summary.criticalDimensionCount ? 'critical' : (payload.summary.warningDimensionCount ? 'warning' : 'positive')}
              />
            </section>

            <div className="quality-primary-grid">
              <section className="quality-card quality-dimensions-card">
                <div className="quality-section-heading">
                  <div>
                    <span>{t('quality.coverageContract')}</span>
                    <h2>{t('quality.dimensions')}</h2>
                  </div>
                  <span>{t('quality.declaredChecks', { count: dimensions.length })}</span>
                </div>
                <div className="quality-dimension-grid">
                  {dimensions.map((item) => <DimensionCard item={item} key={item.id} />)}
                </div>
              </section>
              <GapLedger gaps={payload.gaps || []} />
            </div>

            <LifecycleRail stages={payload.lifecycle || []} />

            <div className="quality-secondary-grid">
              <OracleStageRail payload={payload} />
              <WatermarkBoard watermarks={payload.watermarks || []} />
            </div>

            <RecentOracleTable events={payload.oracleLifecycle.recentEvents || []} />
            <GapMarkets payload={payload} />

            <section className="quality-card quality-semantics-card">
              <div className="quality-section-heading">
                <div>
                  <span>{t('quality.interpretationBoundary')}</span>
                  <h2>{t('quality.auditSemantics')}</h2>
                </div>
              </div>
              <div className="quality-semantics-grid">
                <div><span>Event identity</span><code>{payload.semantics?.eventIdentity || 'tx_hash + log_index'}</code></div>
                <div><span>Canonical order</span><code>{payload.semantics?.canonicalOrder || 'block_number + log_index'}</code></div>
                <div><span>Market bridge</span><code>{payload.semantics?.marketBridge || 'market + condition + question + token'}</code></div>
                <p>{payload.semantics?.score}</p>
              </div>
            </section>
          </>
        ) : (
          <section className="quality-loading-grid" aria-label={t('quality.loading')}>
            {Array.from({ length: 10 }, (_, index) => <div className="quality-skeleton" key={index} />)}
          </section>
        )}
      </main>
      <MobileWorkspaceNav />
    </div>
  );
}

export default DataQualityWorkspace;
