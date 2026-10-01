import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  fetchPanelRuntimeData,
  mergeRuntimeData,
} from './runtime-store';
import {
  type PanelFetchContext,
  type PanelModule,
  type PanelRefreshTier,
  type PanelRuntimeData,
  type PanelRuntimeStatus,
} from './types';
import type { RuntimePanelMetadata } from '@/services/api';

const DEFAULT_STALE_AFTER_MS: Record<PanelRefreshTier, number> = {
  bootstrap: 5 * 60_000,
  fast: 60_000,
  slow: 15 * 60_000,
  manual: Number.POSITIVE_INFINITY,
};

const EMPTY_STATUS: PanelRuntimeStatus = {
  phase: 'idle',
  updatedAt: null,
  lastAttemptAt: null,
  checkedAt: null,
  fetching: false,
  failureCount: 0,
  error: null,
};

type RuntimeRefreshOptions = {
  panelIds?: Iterable<string>;
  reason?: PanelFetchContext['reason'];
  force?: boolean;
};

type UsePanelRuntimeOptions = {
  panels: PanelModule[];
  activePanelIds: string[];
  initialData?: PanelRuntimeData | (() => PanelRuntimeData);
  suspended?: boolean;
  waitForVisibility?: boolean;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error || 'Panel refresh failed.');
}

function payloadTimestamp(value: unknown): number | null {
  if (!value || typeof value !== 'object') return null;
  const payload = value as Record<string, unknown>;
  const candidate = payload.generatedAt || payload.updatedAt || payload.asOf || payload.timestamp;
  if (typeof candidate === 'number' && Number.isFinite(candidate)) {
    return candidate > 10_000_000_000 ? candidate : candidate * 1_000;
  }
  const parsed = Date.parse(String(candidate || ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function payloadIsDegraded(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const payload = value as { status?: unknown; generationMode?: unknown };
  const status = String(payload.status || '').trim().toLowerCase();
  return payload.generationMode === 'rules' || ['degraded', 'error', 'failed', 'warming', 'gateway-error', 'agent-error', 'missing-api-key', 'invalid-agent-output'].includes(status);
}

function metadataTimestamp(metadata?: RuntimePanelMetadata): number | null {
  const parsed = Date.parse(String(metadata?.freshness?.observedAt || ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function metadataPhase(metadata?: RuntimePanelMetadata): PanelRuntimeStatus['phase'] | null {
  const freshness = String(metadata?.freshness?.state || '').trim().toLowerCase();
  if (freshness === 'stale') return 'stale';
  if (freshness === 'degraded' || freshness === 'error' || freshness === 'unavailable') return 'degraded';
  return null;
}

function retryDelay(panel: PanelModule, failureCount: number): number | null {
  const retry = panel.refreshPolicy?.retry;
  const attempts = Math.max(0, retry?.attempts ?? 2);
  if (failureCount > attempts) return null;
  const base = Math.max(250, retry?.baseDelayMs ?? 1_000);
  const ceiling = Math.max(base, retry?.maxDelayMs ?? 30_000);
  return Math.min(ceiling, base * (2 ** Math.max(0, failureCount - 1)));
}

/** Shared resource owner. UI visibility is one consumer, never the whole demand. */
export function usePanelRuntime({ panels, activePanelIds, initialData = {}, suspended = false, waitForVisibility = false }: UsePanelRuntimeOptions) {
  const byId = useMemo(() => new Map(panels.map((panel) => [panel.id, panel])), [panels]);
  const sourceId = useCallback((id: string) => byId.get(id)?.dataSourceId || id, [byId]);
  const [runtimeData, setData] = useState<PanelRuntimeData>(() => typeof initialData === 'function' ? initialData() : initialData);
  const [statuses, setStatuses] = useState<Record<string, PanelRuntimeStatus>>({});
  const [documentHidden, setDocumentHidden] = useState(() => typeof document !== 'undefined' && document.hidden);
  const [, demandChanged] = useState(0);
  const consumers = useRef(new Map<string, Set<string>>());
  const visibility = useRef(new Map<string, boolean>());
  const dataRef = useRef(runtimeData);
  const statusesRef = useRef(statuses);
  const inflight = useRef(new Map<string, Promise<PanelRuntimeData>>());
  const controllers = useRef(new Map<string, AbortController>());
  const retries = useRef(new Map<string, number>());
  const mounted = useRef(true);
  const runtimeSuspended = suspended || documentHidden;
  const suspendedRef = useRef(runtimeSuspended);
  suspendedRef.current = runtimeSuspended;
  const demand = new Set<string>();
  const addDemand = (id: string) => {
    demand.add(sourceId(id));
    byId.get(id)?.dataDependencies?.forEach((dependency) => demand.add(sourceId(dependency)));
  };
  activePanelIds.filter((id) => waitForVisibility
    ? visibility.current.get(id) === true : visibility.current.get(id) !== false).forEach(addDemand);
  consumers.current.forEach((ids) => ids.forEach(addDemand));
  const demandRef = useRef(demand);
  demandRef.current = demand;
  const demandKey = [...demand].sort().join(',');

  const setConsumerPanels = useCallback((consumer: string, ids: readonly string[]) => {
    const previous = consumers.current.get(consumer);
    const next = new Set(ids);
    if (previous?.size === next.size && [...next].every((id) => previous.has(id))) return;
    if (next.size) consumers.current.set(consumer, next);
    else consumers.current.delete(consumer);
    demandChanged((version) => version + 1);
  }, []);
  const setPanelVisible = useCallback((id: string, visible: boolean) => {
    if (visibility.current.get(id) === visible) return;
    visibility.current.set(id, visible);
    demandChanged((version) => version + 1);
  }, []);
  const setRuntimeData = useCallback((value: PanelRuntimeData | ((current: PanelRuntimeData) => PanelRuntimeData)) => {
    if (!mounted.current) return;
    dataRef.current = typeof value === 'function' ? value(dataRef.current) : value;
    setData(dataRef.current);
  }, []);
  const updateStatuses = useCallback((ids: string[], update: (current: PanelRuntimeStatus, id: string) => PanelRuntimeStatus) => {
    if (!mounted.current || !ids.length) return;
    const next = { ...statusesRef.current };
    ids.forEach((id) => { next[id] = update(next[id] || EMPTY_STATUS, id); });
    statusesRef.current = next;
    setStatuses(next);
  }, []);

  const refreshPanels = useCallback(async (requested: PanelModule[], options: RuntimeRefreshOptions = {}): Promise<PanelRuntimeData> => {
    if (!mounted.current || ((suspendedRef.current || document.hidden) && !options.force)) return {};
    const ids = options.panelIds ? new Set([...options.panelIds].flatMap((id) => [sourceId(id), ...(byId.get(id)?.dataDependencies || [])])) : demandRef.current;
    const pending = new Set<Promise<PanelRuntimeData>>();
    const owners = [...new Map(requested.flatMap((panel) => {
      const owner = byId.get(sourceId(panel.id)) || panel;
      return [owner, ...(options.reason === 'manual' ? panel.dataDependencies || [] : []).map((id) => byId.get(id)).filter((entry): entry is PanelModule => Boolean(entry))]
        .map((entry) => [entry.id, entry] as const);
    })).values()];
    const eligible = owners.filter((panel) => {
      if (!panel.fetchData || !ids.has(panel.id)) return false;
      const running = inflight.current.get(panel.id);
      if (running) { pending.add(running); return false; }
      const status = statusesRef.current[panel.id];
      if (!options.force && ['interval', 'refresh'].includes(options.reason || 'refresh')
        && panel.refreshPolicy?.tier === 'slow' && status?.updatedAt
        && Date.now() - status.updatedAt < (panel.refreshPolicy.staleAfterMs ?? DEFAULT_STALE_AFTER_MS.slow)) return false;
      return true;
    });
    if (eligible.length) {
      const controller = new AbortController();
      const panelIds = eligible.map((panel) => panel.id);
      const now = Date.now();
      panelIds.forEach((id) => controllers.current.set(id, controller));
      const isCurrent = (id: string) => mounted.current && !controller.signal.aborted && controllers.current.get(id) === controller;
      updateStatuses(panelIds, (current, id) => ({ ...current,
        phase: dataRef.current[id] === undefined ? 'loading' : current.phase,
        lastAttemptAt: now, fetching: true, error: null,
      }));
      const request = fetchPanelRuntimeData(eligible, {
        signal: controller.signal, reason: options.reason || 'refresh',
        maxBatchSize: Math.min(12, ...eligible.map((panel) => Math.max(1, panel.maxBatchSize || 12))),
        onPanelData: (id, value, metadata) => {
          if (!isCurrent(id)) return;
          const policy = eligible.find((panel) => panel.id === id)?.refreshPolicy;
          const merged = mergeRuntimeData(dataRef.current, { [id]: value });
          const retained = merged[id] !== value;
          const updatedAt = retained ? statusesRef.current[id]?.updatedAt ?? payloadTimestamp(merged[id])
            : metadataTimestamp(metadata) ?? payloadTimestamp(value);
          const staleAfter = policy?.staleAfterMs ?? DEFAULT_STALE_AFTER_MS[policy?.tier || 'manual'];
          const phase = metadataPhase(metadata) ?? (payloadIsDegraded(value) ? 'degraded'
            : updatedAt != null && Date.now() - updatedAt > staleAfter ? 'stale' : 'ready');
          const retry = retries.current.get(id);
          if (retry != null) { window.clearTimeout(retry); retries.current.delete(id); }
          setRuntimeData(merged);
          updateStatuses([id], () => ({ phase, updatedAt, lastAttemptAt: now, checkedAt: Date.now(), fetching: false, failureCount: 0, error: null,
            cacheMode: metadata?.cache?.mode || null, freshness: metadata?.freshness?.state || null,
            ageSeconds: metadata?.freshness?.ageSeconds ?? null,
          }));
        },
        onPanelError: (id, error) => {
          if (!isCurrent(id)) return;
          updateStatuses([id], (current) => ({ ...current,
            phase: dataRef.current[id] === undefined ? 'error' : 'degraded', lastAttemptAt: now,
            fetching: false, failureCount: current.failureCount + 1, error: errorMessage(error),
          }));
        },
      }).then(({ data }) => controller.signal.aborted ? {} : data).finally(() => {
        panelIds.forEach((id) => {
          if (controllers.current.get(id) !== controller) return;
          controllers.current.delete(id); inflight.current.delete(id);
        });
      });
      panelIds.forEach((id) => inflight.current.set(id, request));
      pending.add(request);
    }
    const results = await Promise.all(pending);
    return Object.assign({}, ...results);
  }, [byId, sourceId, setRuntimeData, updateStatuses]);
  const refreshIds = useCallback((panelIds: string[], options: RuntimeRefreshOptions = {}) => (
    refreshPanels(panels, { ...options, panelIds })
  ), [panels, refreshPanels]);

  useEffect(() => {
    const onVisibility = () => setDocumentHidden(document.hidden);
    document.addEventListener('visibilitychange', onVisibility);
    return () => document.removeEventListener('visibilitychange', onVisibility);
  }, []);
  useEffect(() => {
    // A batch is aborted only when all of its consumers have gone away.
    const unused = new Set(controllers.current.values());
    if (!runtimeSuspended) controllers.current.forEach((controller, id) => {
      if (demandRef.current.has(id)) unused.delete(controller);
    });
    unused.forEach((controller) => controller.abort());
    const stopped: string[] = [];
    controllers.current.forEach((controller, id) => {
      if (!controller.signal.aborted) return;
      stopped.push(id); controllers.current.delete(id); inflight.current.delete(id);
    });
    updateStatuses(stopped, (current, id) => ({ ...current,
      phase: dataRef.current[id] === undefined ? (runtimeSuspended ? 'suspended' : 'idle') : current.phase,
      lastAttemptAt: null, fetching: false,
    }));
    retries.current.forEach((timer, id) => {
      if (runtimeSuspended || !demandRef.current.has(id)) { window.clearTimeout(timer); retries.current.delete(id); }
    });
  }, [demandKey, runtimeSuspended, updateStatuses]);
  useEffect(() => {
    if (runtimeSuspended) return;
    const tick = () => {
      const now = Date.now();
      const due = panels.filter((panel) => {
        if (!demandRef.current.has(panel.id) || !panel.fetchData || inflight.current.has(panel.id) || retries.current.has(panel.id)) return false;
        const policy = panel.refreshPolicy;
        if (!policy || policy.tier === 'manual') return false;
        const status = statusesRef.current[panel.id];
        if (status?.lastAttemptAt == null) return true;
        const interval = policy.intervalMs ?? (policy.tier === 'fast' || policy.tier === 'slow' ? 20_000 : 0);
        return interval > 0 && now - status.lastAttemptAt >= interval;
      });
      if (due.length) void refreshPanels(due, { reason: 'interval' });
      const stale = panels.filter((panel) => {
        const status = statusesRef.current[panel.id];
        return status?.phase === 'ready' && status.updatedAt != null && panel.refreshPolicy
          && now - status.updatedAt > (panel.refreshPolicy.staleAfterMs ?? DEFAULT_STALE_AFTER_MS[panel.refreshPolicy.tier]);
      });
      updateStatuses(stale.map((panel) => panel.id), (status) => ({ ...status, phase: 'stale' }));
    };
    tick();
    const timer = window.setInterval(tick, 1_000);
    return () => window.clearInterval(timer);
  }, [demandKey, panels, refreshPanels, runtimeSuspended, updateStatuses]);
  useEffect(() => {
    if (runtimeSuspended) return;
    panels.forEach((panel) => {
      const status = statuses[panel.id];
      if (!status?.error || !demandRef.current.has(panel.id) || retries.current.has(panel.id)) return;
      const delay = retryDelay(panel, status.failureCount);
      if (delay == null) return;
      retries.current.set(panel.id, window.setTimeout(() => {
        retries.current.delete(panel.id);
        if (demandRef.current.has(panel.id)) void refreshPanels([panel], { reason: 'retry' });
      }, delay));
    });
  }, [demandKey, panels, refreshPanels, runtimeSuspended, statuses]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controllers.current.forEach((controller) => controller.abort());
      controllers.current.clear(); inflight.current.clear();
      retries.current.forEach((timer) => window.clearTimeout(timer)); retries.current.clear();
    };
  }, []);
  const getStatus = useCallback((id: string) => statuses[sourceId(id)] || EMPTY_STATUS, [sourceId, statuses]);
  const getData = useCallback((id: string) => runtimeData[sourceId(id)], [runtimeData, sourceId]);
  return { runtimeData, setRuntimeData, statuses, getStatus, refreshPanels, refreshIds,
    getData, setConsumerPanels, setPanelVisible, suspended: runtimeSuspended };
}
