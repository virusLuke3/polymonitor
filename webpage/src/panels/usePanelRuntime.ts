import { useCallback, useEffect, useMemo, useRef, useState } from 'preact/hooks';
import {
  fetchPanelRuntimeData,
  mergeRuntimeData,
  runtimeTimestamp,
} from './runtime-store';
import {
  type PanelFetchContext,
  type PanelModule,
  type PanelRefreshTier,
  type PanelRuntimeData,
  type PanelRuntimeStatus,
} from './types';
import type { RuntimePanelMetadata } from '@/services/api';
import { ApiHttpError } from '@/services/api';
import { readResourceCache, writeResourceCache, resourceIsCurrent } from './resource-cache';

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


function payloadIsDegraded(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const payload = value as { status?: unknown; generationMode?: unknown };
  const status = String(payload.status || '').trim().toLowerCase();
  return payload.generationMode === 'rules' || ['degraded', 'partial', 'invalid', 'unknown', 'unavailable', 'error', 'failed', 'warming', 'gateway-error', 'agent-error', 'missing-api-key', 'invalid-agent-output'].includes(status);
}

function metadataTimestamp(metadata?: RuntimePanelMetadata): number | null {
  const parsed = Date.parse(String(metadata?.freshness?.observedAt || ''));
  return Number.isFinite(parsed) ? parsed : null;
}

function metadataPhase(metadata?: RuntimePanelMetadata): PanelRuntimeStatus['phase'] | null {
  const freshness = String(metadata?.freshness?.state || '').trim().toLowerCase();
  if (freshness === 'stale') return 'stale';
  if (freshness === 'degraded' || freshness === 'error' || freshness === 'unavailable' || freshness === 'unknown') return 'degraded';
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
  const [runtimeData, setData] = useState<PanelRuntimeData>(() => {
    const restored = { ...(typeof initialData === 'function' ? initialData() : initialData) };
    panels.forEach(panel => {
      if (!panel.snapshot) return;
      try {
        const cached = readResourceCache(panel.snapshot, window.localStorage);
        if (cached != null && (restored[panel.id] == null || (panel.snapshot.updatedAt(cached) ?? 0) > (runtimeTimestamp(restored[panel.id]) ?? 0))) restored[panel.id] = cached;
      } catch { /* Public persistence is optional. */ }
    });
    return restored;
  });
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
      if (!options.force && status?.error && (status.retryable === false || (status.nextRetryAt ?? 0) > Date.now())) return false;
      return true;
    });
    if (eligible.length) {
      const panelIds = eligible.map(panel => panel.id);
      const now = Date.now();
      const lanes = new Map(eligible.map(panel => {
        const controller = new AbortController();
        let complete!: (value: PanelRuntimeData) => void;
        const promise = new Promise<PanelRuntimeData>(resolve => { complete = resolve; });
        controllers.current.set(panel.id, controller);
        inflight.current.set(panel.id, promise);
        pending.add(promise);
        const lane = { controller, complete, result: {} as PanelRuntimeData };
        return [panel.id, lane] as const;
      }));
      const isCurrent = (id: string) => mounted.current && !lanes.get(id)!.controller.signal.aborted && controllers.current.get(id) === lanes.get(id)!.controller;
      updateStatuses(panelIds, (current, id) => ({ ...current,
        phase: dataRef.current[id] === undefined ? 'loading' : current.phase,
        lastAttemptAt: now, fetching: true,
      }));
      void fetchPanelRuntimeData(eligible, {
        signal: new AbortController().signal,
        panelSignals: Object.fromEntries([...lanes].map(([id, lane]) => [id, lane.controller.signal])), reason: options.reason || 'refresh',
        maxBatchSize: Math.min(12, ...eligible.map((panel) => Math.max(1, panel.maxBatchSize || 12))),
        onPanelData: (id, value, metadata, raw) => {
          if (!isCurrent(id)) return;
          const policy = eligible.find((panel) => panel.id === id)?.refreshPolicy;
          const merged = mergeRuntimeData(dataRef.current, { [id]: value });
          const retained = merged[id] !== value;
          const updatedAt = retained ? statusesRef.current[id]?.updatedAt ?? runtimeTimestamp(merged[id])
            : eligible.find(panel => panel.id === id)?.snapshot?.updatedAt(value) ?? runtimeTimestamp(value) ?? metadataTimestamp(metadata);
          const staleAfter = policy?.staleAfterMs ?? DEFAULT_STALE_AFTER_MS[policy?.tier || 'manual'];
          const phase = metadataPhase(metadata) ?? ((value as { status?: string } | null)?.status === 'stale' ? 'stale' : payloadIsDegraded(value) ? 'degraded'
            : updatedAt != null && Date.now() - updatedAt > staleAfter ? 'stale' : 'ready');
          const retry = retries.current.get(id);
          if (retry != null) { window.clearTimeout(retry); retries.current.delete(id); }
          lanes.get(id)!.result = { [id]: value };
          const contract = eligible.find(panel => panel.id === id)?.snapshot;
          if (contract) {
            try {
              const previous = contract.shouldPersist ? readResourceCache(contract, window.localStorage) : null;
              if (!contract.shouldPersist || contract.shouldPersist(value, previous)) writeResourceCache(contract, raw ?? value, window.localStorage);
            } catch { /* A cache failure cannot fail the displayed snapshot. */ }
          }
          setRuntimeData(merged);
          updateStatuses([id], () => ({ phase, updatedAt, lastAttemptAt: now, checkedAt: Date.now(), fetching: false, failureCount: 0, error: null,
            cacheMode: metadata?.cache?.mode || null, freshness: metadata?.freshness?.state || null,
            ageSeconds: metadata?.freshness?.ageSeconds ?? null,
          }));
        },
        onPanelError: (id, error) => {
          if (!isCurrent(id)) return;
          updateStatuses([id], (current) => {
            const owner = eligible.find(panel => panel.id === id)!;
            const advised = error instanceof ApiHttpError && Number.isFinite(error.retryAfterMs) ? error.retryAfterMs ?? 0 : 0;
            const pending = error instanceof ApiHttpError && error.verificationPending;
            const pendingSince = current.pendingSince ?? Date.now();
            if (pending && Date.now() - pendingSince < (owner.refreshPolicy?.requestTimeoutMs ?? 30_000)) {
              return { ...current, phase: dataRef.current[id] === undefined ? 'loading' : current.phase,
                lastAttemptAt: now, fetching: false, retryPending: true, pendingSince, retryable: true,
                nextRetryAt: Date.now() + Math.min(5_000, Math.max(1_000, advised)) };
            }
            const failures = current.failureCount + 1;
            const retryable = !(error && typeof error === 'object' && 'retryable' in error && error.retryable === false)
              && (!(error instanceof ApiHttpError) || [408, 425, 429].includes(error.status) || error.status >= 500);
            const interval = owner.refreshPolicy?.intervalMs ?? 30_000;
            const ceiling = Math.max(interval, owner.refreshPolicy?.retry?.maxDelayMs ?? 60_000);
            const backoff = retryDelay(owner, failures) ?? Math.min(ceiling, interval * 2 ** Math.min(4, Math.max(0, failures - 3)));
            const delay = Math.max(advised, backoff) + Math.floor(Math.random() * backoff * 0.1);
            return { ...current,
            phase: dataRef.current[id] === undefined ? 'error' : 'degraded', lastAttemptAt: now,
            fetching: false, failureCount: failures, error: errorMessage(error), retryable,
            retryPending: false, pendingSince: pending ? pendingSince : undefined,
            nextRetryAt: retryable ? Date.now() + delay : null,
          }; });
        },
        onPanelSettled: id => {
          const lane = lanes.get(id)!;
          if (controllers.current.get(id) === lane.controller) {
            controllers.current.delete(id);
            inflight.current.delete(id);
          }
          lane.complete(lane.result);
        },
      });
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
    // The transport releases a batch only after all resource demand is gone.
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
        if (status?.error && (status.retryable === false || (status.nextRetryAt ?? 0) > now)) return false;
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
      const expired = panels.filter(panel => {
        const contract = panel.snapshot, value = dataRef.current[panel.id];
        return contract && value != null && !resourceIsCurrent(contract.updatedAt(value), Math.max(contract.maxAgeMs, contract.staleAgeMs ?? contract.maxAgeMs));
      });
      if (expired.length) {
        setRuntimeData(current => { const next = { ...current }; expired.forEach(panel => delete next[panel.id]); return next; });
        updateStatuses(expired.map(panel => panel.id), status => ({ ...status, phase: 'stale' }));
      }
    };
    tick();
    const timer = window.setInterval(tick, 1_000);
    return () => window.clearInterval(timer);
  }, [demandKey, panels, refreshPanels, runtimeSuspended, updateStatuses, setRuntimeData]);
  useEffect(() => {
    if (runtimeSuspended) return;
    panels.forEach((panel) => {
      const status = statuses[panel.id];
      if ((!status?.error && !status?.retryPending) || status.fetching || status.retryable === false || !demandRef.current.has(panel.id) || retries.current.has(panel.id)) return;
      const delay = !status.retryPending && retryDelay(panel, status.failureCount) == null ? null : Math.max(0, (status.nextRetryAt ?? Date.now()) - Date.now());
      if (delay == null) return;
      retries.current.set(panel.id, window.setTimeout(() => {
        retries.current.delete(panel.id);
        if (demandRef.current.has(panel.id)) void refreshPanels([panel], { reason: 'retry' });
      }, delay));
    });
  }, [demandKey, panels, refreshPanels, runtimeSuspended, statuses]);
  useEffect(() => {
    const reconnect = () => {
      if (suspendedRef.current || document.hidden || navigator.onLine === false) return;
      const due = panels.filter(panel => demandRef.current.has(panel.id) && panel.fetchData
        && panel.refreshPolicy && panel.refreshPolicy.tier !== 'manual'
        && statusesRef.current[panel.id]?.retryable !== false);
      due.forEach(panel => {
        const timer = retries.current.get(panel.id);
        if (timer != null) window.clearTimeout(timer);
        retries.current.delete(panel.id);
      });
      // Connectivity recovery bypasses an old network backoff. Inflight work is
      // still joined, and only accepted data clears errors or advances clocks.
      if (due.length) void refreshPanels(due, { panelIds: due.map(panel => panel.id), reason: 'retry', force: true });
    };
    window.addEventListener('online', reconnect);
    return () => window.removeEventListener('online', reconnect);
  }, [panels, refreshPanels]);
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
  const forgetIds = useCallback((ids: string[]) => {
    ids.forEach(id => {
      const controller = controllers.current.get(id);
      controllers.current.delete(id); inflight.current.delete(id);
      controller?.abort();
      const retry = retries.current.get(id);
      if (retry != null) window.clearTimeout(retry);
      retries.current.delete(id);
    });
    setRuntimeData(current => { const next = { ...current }; ids.forEach(id => delete next[id]); return next; });
    const next = { ...statusesRef.current }; ids.forEach(id => delete next[id]);
    statusesRef.current = next; if (mounted.current) setStatuses(next);
  }, [setRuntimeData]);
  return { runtimeData, setRuntimeData, statuses, getStatus, refreshPanels, refreshIds,
    getData, forgetIds, setConsumerPanels, setPanelVisible, suspended: runtimeSuspended };
}
