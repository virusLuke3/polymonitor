import { useCallback, useEffect, useMemo, useState } from 'preact/hooks';
import './operations.css';

type HealthStatus = 'healthy' | 'warning' | 'degraded' | 'unhealthy' | 'unknown' | 'disabled';

type ServiceState = {
  unit: string;
  status: HealthStatus;
  activeState: string;
  subState: string;
  restartCount: number;
};

type PanelState = {
  panelId: string;
  owner: string;
  healthStrategy: string;
  status: HealthStatus;
  freshness: HealthStatus;
  ageSeconds: number | null;
  evidence: string;
  expectedFreshnessSeconds?: number | null;
  degradationPolicy: string;
};

type OperationsPayload = {
  generatedAt: string;
  status: HealthStatus;
  runtime: {
    generatedAt?: string | null;
    ageSeconds?: number | null;
    status: HealthStatus;
    resources?: Record<string, { status?: HealthStatus; availablePct?: number; freePct?: number; oneMinutePerCpu?: number } | number | null>;
    dependencies?: Record<string, {
      status?: HealthStatus;
      ageSeconds?: number | null;
      recovery?: { decision?: string; restartAttemptsInWindow?: number; backoffUntilEpoch?: number };
    }>;
    services?: ServiceState[];
    systemServices?: ServiceState[];
    summary?: { serviceCount?: number; healthyServices?: number; attentionServices?: number };
  };
  panels: {
    generatedAt?: string | null;
    ageSeconds?: number | null;
    status: HealthStatus;
    summary?: { panelCount?: number; healthyCount?: number; attentionCount?: number; unknownCount?: number };
    panels?: PanelState[];
    watermarks?: Record<string, { updatedAt?: string | null; status?: string }>;
    activeGaps?: Array<{ panelId: string; status: HealthStatus; freshness: HealthStatus; evidence: string }>;
  };
};

type Incident = {
  signature: string;
  component: string;
  status: HealthStatus;
  summary: string;
  openedAt: string;
  lastObservedAt: string;
  resolvedAt?: string | null;
  observations: number;
};

type IncidentPayload = {
  items: Incident[];
};

const RAW_API_BASE = import.meta.env.VITE_POLYDATA_API_BASE_URL || '/wm-api';
const API_BASE = RAW_API_BASE.endsWith('/') ? RAW_API_BASE.slice(0, -1) : RAW_API_BASE;
const REFRESH_INTERVAL_MS = 30_000;

function statusLabel(status?: string) {
  return String(status || 'unknown').replace(/-/g, ' ').toUpperCase();
}

function ageLabel(seconds?: number | null) {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return 'unknown';
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function timeLabel(value?: string | null) {
  if (!value) return 'Not observed';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Not observed';
  return new Intl.DateTimeFormat('en', {
    dateStyle: 'medium',
    timeStyle: 'medium',
  }).format(date);
}

function StatusBadge({ status }: { status?: HealthStatus }) {
  const normalized = status || 'unknown';
  return <span className={`ops-status ops-status-${normalized}`}>{statusLabel(normalized)}</span>;
}

async function getJson<T>(path: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: 'same-origin',
    headers: { Accept: 'application/json' },
    signal,
  });
  if (response.status === 401 || response.status === 403) {
    throw new Error('Operator authorization is required for this read-only workspace.');
  }
  if (!response.ok) throw new Error(`Operations API returned HTTP ${response.status}.`);
  return response.json() as Promise<T>;
}

export function OperationsWorkspace() {
  const [payload, setPayload] = useState<OperationsPayload | null>(null);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [attentionOnly, setAttentionOnly] = useState(true);
  const [filterQuery, setFilterQuery] = useState('');

  const refresh = useCallback(async (signal?: AbortSignal) => {
    const controller = signal ? null : new AbortController();
    const activeSignal = signal || controller!.signal;
    try {
      const [operations, incidentPayload] = await Promise.all([
        getJson<OperationsPayload>('/system/operations', activeSignal),
        getJson<IncidentPayload>('/system/incidents', activeSignal),
      ]);
      setPayload(operations);
      setIncidents(incidentPayload.items || []);
      setError('');
    } catch (caught) {
      if ((caught as { name?: string })?.name !== 'AbortError') {
        setError(caught instanceof Error ? caught.message : 'Operations data is unavailable.');
      }
    } finally {
      setLoading(false);
    }
    return () => controller?.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refresh();
    }, REFRESH_INTERVAL_MS);
    return () => {
      controller.abort();
      window.clearInterval(interval);
    };
  }, [refresh]);

  const normalizedQuery = filterQuery.trim().toLowerCase();
  const services = [...(payload?.runtime.services || []), ...(payload?.runtime.systemServices || [])];
  const panels = payload?.panels.panels || [];
  const visiblePanels = useMemo(
    () => panels.filter((panel) => {
      if (attentionOnly && ['healthy', 'disabled'].includes(panel.status)) return false;
      if (!normalizedQuery) return true;
      return `${panel.panelId} ${panel.owner} ${panel.healthStrategy} ${panel.evidence}`
        .toLowerCase()
        .includes(normalizedQuery);
    }),
    [attentionOnly, normalizedQuery, panels],
  );
  const visibleServices = services.filter((service) => (
    !normalizedQuery
    || `${service.unit} ${service.activeState} ${service.subState} ${service.status}`
      .toLowerCase()
      .includes(normalizedQuery)
  ));
  const visibleIncidents = incidents.filter((incident) => (
    !normalizedQuery
    || `${incident.component} ${incident.summary} ${incident.status}`.toLowerCase().includes(normalizedQuery)
  ));
  const openIncidents = incidents.filter((incident) => !incident.resolvedAt);
  const dependencies = Object.entries(payload?.runtime.dependencies || {});
  const resources = payload?.runtime.resources || {};
  const memory = typeof resources.memory === 'object' && resources.memory ? resources.memory : {};
  const disk = typeof resources.disk === 'object' && resources.disk ? resources.disk : {};
  const uptimeSeconds = typeof resources.uptimeSeconds === 'number' ? resources.uptimeSeconds : null;
  const watermarks = Object.entries(payload?.panels.watermarks || {});

  return (
    <main className="ops-workspace">
      <header className="ops-topbar">
        <a className="ops-home-link" href="/">← WORLD</a>
        <div>
          <strong>POLYDATA OPERATIONS</strong>
          <span>READ-ONLY CONTROL PLANE</span>
        </div>
        <input
          aria-label="Filter operations data"
          onInput={(event) => setFilterQuery(event.currentTarget.value)}
          placeholder="FILTER SERVICES, PANELS, INCIDENTS"
          type="search"
          value={filterQuery}
        />
        <button type="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? 'REFRESHING' : 'REFRESH NOW'}
        </button>
      </header>

      <section className="ops-hero">
        <div>
          <p>PRODUCTION READINESS / DATA PLANE / PANEL CONTRACTS</p>
          <h1>OPERATIONS<br />WORKSPACE</h1>
          <span>Runtime dependencies, host pressure, tunnel evidence, data freshness and every active Panel contract.</span>
        </div>
        <div className="ops-hero-state">
          <StatusBadge status={payload?.status || 'unknown'} />
          <small>Observed {timeLabel(payload?.generatedAt)}</small>
          <small>Runtime snapshot {ageLabel(payload?.runtime.ageSeconds)} old</small>
        </div>
      </section>

      {error ? (
        <section className="ops-notice" role="alert">
          <strong>OPERATIONS DATA UNAVAILABLE</strong>
          <span>{error}</span>
          <small>No credentials are stored in the browser. Authenticate through the operator access layer, then refresh.</small>
        </section>
      ) : null}

      <section className="ops-summary-grid" aria-label="Operations summary">
        <article>
          <small>RUNTIME</small>
          <strong>{statusLabel(payload?.runtime.status)}</strong>
          <span>{payload?.runtime.summary?.healthyServices || 0}/{payload?.runtime.summary?.serviceCount || 0} services healthy</span>
        </article>
        <article>
          <small>PANEL CONTRACTS</small>
          <strong>{payload?.panels.summary?.healthyCount || 0}/{payload?.panels.summary?.panelCount || 0}</strong>
          <span>{payload?.panels.summary?.attentionCount || 0} attention · {payload?.panels.summary?.unknownCount || 0} unknown</span>
        </article>
        <article>
          <small>OPEN INCIDENTS</small>
          <strong>{openIncidents.length}</strong>
          <span>Transition-deduplicated, seven-day retention</span>
        </article>
        <article>
          <small>MEMORY AVAILABLE</small>
          <strong>{memory.availablePct ?? '--'}%</strong>
          <StatusBadge status={memory.status} />
        </article>
        <article>
          <small>DISK FREE</small>
          <strong>{disk.freePct ?? '--'}%</strong>
          <StatusBadge status={disk.status} />
        </article>
        <article>
          <small>VM UPTIME</small>
          <strong>{ageLabel(uptimeSeconds)}</strong>
          <span>Kernel uptime observed by the GCP collector</span>
        </article>
      </section>

      <section className="ops-grid">
        <article className="ops-card">
          <header><div><small>DEPENDENCIES</small><h2>RUNTIME READINESS</h2></div></header>
          <div className="ops-table">
            {dependencies.length ? dependencies.map(([name, item]) => (
              <div className="ops-row" key={name}>
                <strong>{name}</strong>
                <span>
                  {item.ageSeconds === undefined ? 'live probe' : `${ageLabel(item.ageSeconds)} old`}
                  {item.recovery ? ` · ${item.recovery.restartAttemptsInWindow || 0} recoveries · ${item.recovery.decision || 'none'}` : ''}
                </span>
                <StatusBadge status={item.status} />
              </div>
            )) : <p className="ops-empty">No runtime snapshot is available.</p>}
          </div>
        </article>

        <article className="ops-card">
          <header><div><small>SYSTEMD</small><h2>SERVICE OBSERVATIONS</h2></div><span>{services.length} units</span></header>
          <div className="ops-table ops-scroll">
            {visibleServices.map((service) => (
              <div className="ops-row" key={service.unit}>
                <strong>{service.unit.replace(/^polydata-/, '').replace(/\.service$|\.timer$/, '')}</strong>
                <span>{service.activeState}/{service.subState} · {service.restartCount} restarts</span>
                <StatusBadge status={service.status} />
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="ops-card">
        <header><div><small>DATA PLANE</small><h2>PIPELINE WATERMARKS</h2></div><span>{watermarks.length} observed</span></header>
        <div className="ops-table">
          {watermarks.length ? watermarks.map(([name, watermark]) => (
            <div className="ops-row" key={name}>
              <strong>{name}</strong>
              <span>{timeLabel(watermark.updatedAt)}</span>
              <StatusBadge status={(watermark.status || (watermark.updatedAt ? 'healthy' : 'unknown')) as HealthStatus} />
            </div>
          )) : <p className="ops-empty">No pipeline watermark snapshot is available.</p>}
        </div>
      </section>

      <section className="ops-card ops-panel-health">
        <header>
          <div><small>PRODUCT SURFACE</small><h2>ACTIVE PANEL HEALTH CONTRACTS</h2></div>
          <button type="button" onClick={() => setAttentionOnly((current) => !current)}>
            {attentionOnly ? `ATTENTION · ${visiblePanels.length}` : `ALL PANELS · ${panels.length}`}
          </button>
        </header>
        <div className="ops-panel-grid">
          {visiblePanels.length ? visiblePanels.map((panel) => (
            <article key={panel.panelId}>
              <div><strong>{panel.panelId}</strong><StatusBadge status={panel.status} /></div>
              <p>{panel.owner} · {panel.healthStrategy} · {panel.evidence}</p>
              <small>Evidence age {ageLabel(panel.ageSeconds)} · target {ageLabel(panel.expectedFreshnessSeconds)}</small>
              <span>{panel.degradationPolicy}</span>
            </article>
          )) : <p className="ops-empty">Every observed Panel contract is healthy.</p>}
        </div>
      </section>

      <section className="ops-card ops-incidents">
        <header><div><small>FAULT HISTORY</small><h2>INCIDENT TRANSITIONS</h2></div><span>{incidents.length} retained</span></header>
        <div className="ops-table">
          {visibleIncidents.length ? visibleIncidents.slice(0, 50).map((incident) => (
            <div className="ops-row" key={incident.signature}>
              <strong>{incident.component}</strong>
              <span>{incident.summary} · {incident.observations} observations · {incident.resolvedAt ? 'resolved' : 'open'}</span>
              <StatusBadge status={incident.resolvedAt ? 'healthy' : incident.status} />
            </div>
          )) : <p className="ops-empty">No incident transitions have been recorded.</p>}
        </div>
      </section>
    </main>
  );
}

export default OperationsWorkspace;
