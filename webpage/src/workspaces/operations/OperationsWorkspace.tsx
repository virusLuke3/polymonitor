import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  FreshnessBadge,
  MetricCard,
  operationalTone,
  StatusBadge,
  type OperationalTone,
} from '@/components/design-system/StatusPrimitives';
import { fetchSeedHealth, fetchSystemHealth, isAbortLikeError } from '@/services/api';
import type { SeedHealthItem, SeedHealthPayload, SyncCheckpoint, SystemHealth } from '@/types';

const REFRESH_INTERVAL_MS = 30_000;
const HIDDEN_OPERATION_PANEL_IDS = new Set(['world-cup-match-ops']);

type WatcherFilter = 'all' | 'attention';

type PipelineRow = {
  id: string;
  label: string;
  checkpoint?: SyncCheckpoint | null;
  expectedSeconds: number;
  status?: string | null;
};

function ageFromIso(value?: string | null): number | null {
  const parsed = Date.parse(String(value || ''));
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.round((Date.now() - parsed) / 1_000));
}

function formatTimestamp(value?: string | null): string {
  const parsed = Date.parse(String(value || ''));
  if (!Number.isFinite(parsed)) return '--';
  return new Date(parsed).toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatAgeLong(ageSeconds?: number | null): string {
  if (ageSeconds == null || !Number.isFinite(ageSeconds) || ageSeconds < 0) return 'No observation';
  if (ageSeconds < 60) return `${Math.round(ageSeconds)} seconds ago`;
  if (ageSeconds < 3_600) return `${Math.round(ageSeconds / 60)} minutes ago`;
  if (ageSeconds < 86_400) return `${Math.round(ageSeconds / 3_600)} hours ago`;
  return `${Math.round(ageSeconds / 86_400)} days ago`;
}

function pipelineFreshness(row: PipelineRow): string {
  const explicit = String(row.status || '').trim().toLowerCase();
  if (explicit === 'warming') return 'warming';
  const age = ageFromIso(row.checkpoint?.updatedAt);
  if (age == null) return 'unknown';
  if (age <= row.expectedSeconds * 2) return 'fresh';
  if (age <= row.expectedSeconds * 6) return 'aging';
  return 'stale';
}

function databaseLabel(database?: string): string {
  const normalized = String(database || '').trim().toLowerCase();
  if (!normalized) return 'Unknown';
  if (normalized.startsWith('postgres')) return 'PostgreSQL';
  if (normalized.startsWith('clickhouse')) return 'ClickHouse';
  if (normalized.startsWith('sqlite')) return 'SQLite';
  return 'Configured';
}

function sourceStateSummary(item: SeedHealthItem): string {
  const entries = Object.entries(item.sourceStates || {});
  if (!entries.length) return 'No source detail';
  return entries
    .slice(0, 4)
    .map(([source, status]) => `${source}:${status}`)
    .join(' · ');
}

function watcherNeedsAttention(item: SeedHealthItem): boolean {
  return item.status !== 'ok' || item.freshness !== 'fresh' || Boolean(item.errorSummary);
}

function toneForSummary(status: string, error: string | null): OperationalTone {
  if (error && status === 'unknown') return 'critical';
  return operationalTone(status);
}

export function OperationsWorkspace() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [seedHealth, setSeedHealth] = useState<SeedHealthPayload | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [watcherFilter, setWatcherFilter] = useState<WatcherFilter>('all');
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    const [healthResult, seedResult] = await Promise.allSettled([
      fetchSystemHealth(controller.signal),
      fetchSeedHealth(controller.signal),
    ]);
    if (controller.signal.aborted) return;

    const failures: string[] = [];
    if (healthResult.status === 'fulfilled') {
      setHealth(healthResult.value);
    } else if (!isAbortLikeError(healthResult.reason)) {
      failures.push('system health');
    }
    if (seedResult.status === 'fulfilled') {
      setSeedHealth(seedResult.value);
    } else if (!isAbortLikeError(seedResult.reason)) {
      failures.push('watcher health');
    }
    setError(failures.length ? `Unable to refresh ${failures.join(' and ')}. Last good observations remain visible.` : null);
    setLastRefreshedAt(Date.now());
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
      controllerRef.current?.abort();
    };
  }, [refresh]);

  const watchers = useMemo(
    () => (seedHealth?.items || [])
      .filter((item) => !HIDDEN_OPERATION_PANEL_IDS.has(item.panelId) && !item.panelId.includes('worldcup'))
      .sort((left, right) => {
        const attentionDelta = Number(watcherNeedsAttention(right)) - Number(watcherNeedsAttention(left));
        return attentionDelta || left.serviceName.localeCompare(right.serviceName) || left.panelId.localeCompare(right.panelId);
      }),
    [seedHealth?.items],
  );
  const attentionWatchers = useMemo(() => watchers.filter(watcherNeedsAttention), [watchers]);
  const visibleWatchers = watcherFilter === 'attention' ? attentionWatchers : watchers;
  const healthyWatchers = watchers.filter((item) => item.status === 'ok' && item.freshness === 'fresh').length;
  const totalRecords = watchers.reduce((total, item) => total + Number(item.recordCount || 0), 0);
  const sourceCount = watchers.reduce((total, item) => total + Object.keys(item.sourceStates || {}).length, 0);

  const pipelineRows = useMemo<PipelineRow[]>(() => [
    { id: 'market', label: 'Market registry', checkpoint: health?.marketSync, expectedSeconds: 300 },
    { id: 'trade', label: 'OrderFilled', checkpoint: health?.tradeSync, expectedSeconds: 120 },
    { id: 'oracle', label: 'Oracle events', checkpoint: health?.oracleSync, expectedSeconds: 300 },
    {
      id: 'price',
      label: 'Derived prices',
      checkpoint: { updatedAt: health?.priceSync?.updatedAt },
      expectedSeconds: 300,
      status: health?.priceSync?.status,
    },
  ], [health]);
  const freshPipelines = pipelineRows.filter((row) => pipelineFreshness(row) === 'fresh').length;
  const apiStatus = String(health?.apiStatus || (loading ? 'warming' : 'unknown')).toLowerCase();
  const seedStatus = String(seedHealth?.status || (loading ? 'warming' : 'unknown')).toLowerCase();
  const overallStatus = error && !health && !seedHealth
    ? 'error'
    : (
      apiStatus === 'ok' && seedStatus === 'ok' && !attentionWatchers.length
        ? 'ok'
        : (apiStatus === 'error' || seedStatus === 'error' ? 'error' : 'degraded')
    );
  const generatedAge = ageFromIso(seedHealth?.generatedAt);

  return (
    <div className="ops-shell">
      <header className="ops-topbar">
        <div className="ops-brand-cluster">
          <a className="ops-home-link" href="/">◎ World</a>
          <div className="ops-brand">POLYDATA OPERATIONS <span>READ-ONLY CONTROL PLANE</span></div>
        </div>
        <div className="ops-actions">
          <button className="ops-action-button" type="button" disabled>Auto · 30s</button>
          <button className="ops-action-button is-primary" type="button" disabled={loading} onClick={() => void refresh()}>
            {loading ? 'Refreshing…' : 'Refresh now'}
          </button>
        </div>
      </header>

      <main className="ops-main">
        <section className="ops-hero">
          <div>
            <span className="ops-kicker">Production Readiness / Data Plane / Watcher Heartbeats</span>
            <h1>Operations Workspace</h1>
            <p className="ops-hero-copy">
              One read-only surface for API dependencies, synchronization watermarks, seed freshness,
              source degradation and active data gaps. Service labels reflect application heartbeats;
              host-level systemd control remains outside the browser.
            </p>
          </div>
          <div className="ops-live-lockup" aria-live="polite">
            <StatusBadge
              label={overallStatus.toUpperCase()}
              tone={toneForSummary(overallStatus, error)}
              detail={error}
            />
            <time dateTime={lastRefreshedAt ? new Date(lastRefreshedAt).toISOString() : undefined}>
              {lastRefreshedAt ? `Observed ${new Date(lastRefreshedAt).toLocaleTimeString()}` : 'Awaiting first observation'}
            </time>
            <span className="ops-refresh-copy">Source snapshot {formatAgeLong(generatedAge)}</span>
          </div>
        </section>

        {error ? (
          <div className="ops-error-banner" role="alert">
            <span>{error}</span>
            <StatusBadge label="PARTIAL" tone="warning" compact />
          </div>
        ) : null}

        <section className="ops-metric-grid" aria-label="Operational summary">
          <MetricCard
            eyebrow="API plane"
            value={apiStatus.toUpperCase()}
            detail={`Database ${databaseLabel(health?.database)} · Redis ${health?.redis ? 'online' : 'not confirmed'}`}
            tone={operationalTone(apiStatus)}
          />
          <MetricCard
            eyebrow="Watcher health"
            value={`${healthyWatchers}/${watchers.length || '--'}`}
            detail={`${attentionWatchers.length} need attention`}
            tone={attentionWatchers.length ? 'warning' : (watchers.length ? 'positive' : 'neutral')}
          />
          <MetricCard
            eyebrow="Pipeline freshness"
            value={`${freshPipelines}/${pipelineRows.length}`}
            detail="Market, trades, oracle and derived prices"
            tone={freshPipelines === pipelineRows.length ? 'positive' : 'warning'}
          />
          <MetricCard
            eyebrow="Seed records"
            value={totalRecords.toLocaleString()}
            detail={`${sourceCount} observed source states`}
            tone={totalRecords > 0 ? 'info' : 'neutral'}
          />
          <MetricCard
            eyebrow="Active gaps"
            value={attentionWatchers.length}
            detail={attentionWatchers.length ? 'Degraded, stale or error summaries' : 'No watcher gaps reported'}
            tone={attentionWatchers.length ? 'warning' : 'positive'}
          />
        </section>

        <div className="ops-content-grid">
          <section className="ops-card">
            <div className="ops-section-heading">
              <div>
                <span className="ops-section-kicker">Synchronization</span>
                <h2>Data pipeline watermarks</h2>
              </div>
              <span className="ops-section-copy">Application-level checkpoints</span>
            </div>
            <div className="ops-table-wrap">
              <table className="ops-table">
                <thead>
                  <tr>
                    <th>Pipeline</th>
                    <th>Freshness</th>
                    <th>Last observation</th>
                    <th>Block / value</th>
                  </tr>
                </thead>
                <tbody>
                  {pipelineRows.map((row) => {
                    const freshness = pipelineFreshness(row);
                    const age = ageFromIso(row.checkpoint?.updatedAt);
                    return (
                      <tr key={row.id}>
                        <td><span className="ops-table-primary">{row.label}</span></td>
                        <td><FreshnessBadge freshness={freshness} ageSeconds={age} compact /></td>
                        <td>
                          <span className="ops-table-mono">{formatTimestamp(row.checkpoint?.updatedAt)}</span>
                        </td>
                        <td>
                          <span className="ops-table-mono">
                            {String(row.checkpoint?.lastBlock ?? row.checkpoint?.value ?? '--')}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="ops-card">
            <div className="ops-section-heading">
              <div>
                <span className="ops-section-kicker">Dependencies</span>
                <h2>Runtime readiness</h2>
              </div>
            </div>
            <div className="ops-health-list">
              {[
                { label: 'API', value: apiStatus, detail: apiStatus },
                { label: 'Redis', value: health?.redis ? 'online' : 'not confirmed', detail: health?.redis ? 'online' : 'unknown' },
                { label: 'Database', value: databaseLabel(health?.database), detail: health?.database ? 'ready' : 'unknown' },
                { label: 'LOB runtime', value: health?.lobRuntime?.mode || '--', detail: health?.lobRuntime?.status || 'unknown' },
                { label: 'Content', value: health?.contentSync?.status || '--', detail: health?.contentSync?.status || 'unknown' },
              ].map((item) => (
                <div className="ops-health-row" key={item.label}>
                  <span className="ops-health-label">{item.label}</span>
                  <span className="ops-health-value">{item.value}</span>
                  <StatusBadge label={item.detail.toUpperCase()} tone={operationalTone(item.detail)} compact />
                </div>
              ))}
            </div>
          </section>

          <section className="ops-card is-full">
            <div className="ops-section-heading">
              <div>
                <span className="ops-section-kicker">Service observations</span>
                <h2>Watcher heartbeat matrix</h2>
              </div>
              <span className="ops-section-copy">{visibleWatchers.length} visible / {watchers.length} total</span>
            </div>
            <div className="ops-filter-bar" role="group" aria-label="Watcher filter">
              <button
                className={`ops-filter-button${watcherFilter === 'all' ? ' is-active' : ''}`}
                type="button"
                onClick={() => setWatcherFilter('all')}
              >
                All watchers
              </button>
              <button
                className={`ops-filter-button${watcherFilter === 'attention' ? ' is-active' : ''}`}
                type="button"
                onClick={() => setWatcherFilter('attention')}
              >
                Attention · {attentionWatchers.length}
              </button>
            </div>
            {visibleWatchers.length ? (
              <div className="ops-table-wrap">
                <table className="ops-table">
                  <thead>
                    <tr>
                      <th>Service / panel</th>
                      <th>Status</th>
                      <th>Freshness</th>
                      <th>Records</th>
                      <th>Sources</th>
                      <th>Last success</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleWatchers.map((item) => (
                      <tr key={`${item.serviceName}:${item.panelId}`}>
                        <td>
                          <span className="ops-table-primary">{item.serviceName.replace(/^polydata-/, '').replace(/\.service$/, '')}</span>
                          <span className="ops-table-secondary">{item.panelId}</span>
                        </td>
                        <td>
                          <div className="ops-table-status">
                            <StatusBadge label={item.status.toUpperCase()} tone={operationalTone(item.status)} compact />
                            {item.payloadStatus && item.payloadStatus !== item.status ? (
                              <StatusBadge label={item.payloadStatus.toUpperCase()} tone={operationalTone(item.payloadStatus)} compact />
                            ) : null}
                          </div>
                        </td>
                        <td>
                          <FreshnessBadge freshness={item.freshness} ageSeconds={item.successAgeSeconds} compact />
                        </td>
                        <td><span className="ops-table-mono">{Number(item.recordCount || 0).toLocaleString()}</span></td>
                        <td>
                          <span className="ops-table-primary">{Object.keys(item.sourceStates || {}).length}</span>
                          <span className="ops-table-secondary" title={sourceStateSummary(item)}>{sourceStateSummary(item)}</span>
                        </td>
                        <td>
                          <span className="ops-table-mono">{formatTimestamp(item.lastSuccessAt)}</span>
                          <span className="ops-table-secondary">{item.cacheMode || 'cache mode unknown'}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="ops-empty">No watcher observations match this filter.</div>
            )}
          </section>

          <section className="ops-card is-full">
            <div className="ops-section-heading">
              <div>
                <span className="ops-section-kicker">Attention queue</span>
                <h2>Active data gaps</h2>
              </div>
              <span className="ops-section-copy">Reported by source and seed metadata</span>
            </div>
            {attentionWatchers.length ? (
              <div className="ops-gap-grid">
                {attentionWatchers.map((item) => (
                  <article
                    className={`ops-gap-card${operationalTone(item.status) === 'critical' ? ' is-critical' : ''}`}
                    key={`gap:${item.serviceName}:${item.panelId}`}
                  >
                    <StatusBadge label={item.status.toUpperCase()} tone={operationalTone(item.status)} compact />
                    <strong>{item.panelId}</strong>
                    <p>{item.errorSummary || `${item.serviceName} reports ${item.freshness} data with payload status ${item.payloadStatus || 'unknown'}.`}</p>
                  </article>
                ))}
              </div>
            ) : (
              <div className="ops-empty">All observed watcher heartbeats are fresh and healthy.</div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
