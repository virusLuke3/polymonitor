import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { ApiHttpError, fetchNaturalHazardMapSource } from '@/services/api';
import type {
  HazardEvent,
  HazardKind,
  HazardMapResponse,
} from '../domain/types';
import type { WorldEventSourceStatus } from './sourceStatus';
import { sourceStatusesFromHazardResponse } from './sourceStatus';
import {
  mergeCanonicalHazardEvents,
  parseNaturalHazardsResponse,
  type ParsedNaturalHazards,
} from './naturalHazards';
import {
  HAZARD_MAP_SOURCE_KEYS,
  hazardMapGeometryZoom,
  hazardSnapshotRetainable,
  hazardSnapshotExpiresAt,
  readHazardMapSnapshot,
  writeHazardMapSnapshot,
  type HazardMapSourceKey,
} from './hazardMapCache';
import { recordMapDataPhase } from './mapDataPerformance';

const RETRY_DELAYS_MS = [5_000, 10_000, 20_000, 60_000] as const;
const INITIAL_SOURCE_PRIORITY: readonly HazardMapSourceKey[] = [
  'usgs',
  'usgs-volcano-cap',
  'nhc',
  'eonet',
  'nws',
  'gdacs',
  'firms',
  'climate-anomaly',
];
const INITIAL_SOURCE_CONCURRENCY = 3;
const REFRESH_INTERVAL_MS: Record<HazardMapSourceKey, number> = {
  usgs: 60_000,
  'usgs-volcano-cap': 300_000,
  nhc: 120_000,
  eonet: 300_000,
  gdacs: 300_000,
  nws: 60_000,
  firms: 900_000,
  'climate-anomaly': 6 * 60 * 60_000,
};

type SourceRecord = {
  parsed: ParsedNaturalHazards;
  signature: string;
  origin: 'cache' | 'network';
  refreshError: string | null;
};

export type NaturalHazardsState = {
  events: HazardEvent[];
  response: HazardMapResponse | null;
  sources: WorldEventSourceStatus[];
  loading: boolean;
  error: string | null;
  rejectedCount: number;
};

function sourceSignature(parsed: ParsedNaturalHazards) {
  const source = parsed.response.sources[0];
  return JSON.stringify([
    parsed.response.meta?.geometryZoom,
    source?.key,
    source?.status,
    source?.dataUpdatedAt,
    source?.fetchedAt,
    source?.lastSuccessAt,
    source?.staleAfter,
    source?.errorCode,
    parsed.events,
  ]);
}

function latestGeneratedAt(records: Map<HazardMapSourceKey, SourceRecord>) {
  const timestamps = [...records.values()]
    .map((record) => record.parsed.response.generatedAt)
    .filter(Boolean)
    .sort();
  return timestamps[timestamps.length - 1] || new Date(0).toISOString();
}

function mergeHazardEvents(records: Map<HazardMapSourceKey, SourceRecord>) {
  return mergeCanonicalHazardEvents(HAZARD_MAP_SOURCE_KEYS.flatMap(
    (source) => records.get(source)?.parsed.events || [],
  ));
}

function countsByKind(events: HazardEvent[]) {
  const result: Partial<Record<HazardKind, number>> = {};
  for (const event of events) result[event.hazardKind] = (result[event.hazardKind] || 0) + 1;
  return result;
}

function sourceStatus(
  source: HazardMapSourceKey,
  record: SourceRecord | undefined,
  attempted: boolean,
  requestError: string | undefined,
): WorldEventSourceStatus {
  const label = source === 'climate-anomaly'
    ? 'ANOMALY'
    : source === 'usgs-volcano-cap'
      ? 'USGS VOLCANO'
      : source.toUpperCase();
  if (!record) {
    return {
      key: source,
      label,
      status: attempted ? 'error' : 'loading',
      eventCount: 0,
      rejectedCount: 0,
      message: requestError || undefined,
    };
  }
  const parsedStatus = sourceStatusesFromHazardResponse(
    record.parsed.response,
    record.parsed.rejected.length,
  )[0] || {
    key: source,
    label,
    status: 'partial' as const,
    eventCount: record.parsed.events.length,
    rejectedCount: record.parsed.rejected.length,
  };
  const retainedMessage = record.origin === 'cache'
    ? 'Showing the persisted last-good map snapshot while the source refreshes.'
    : '';
  const refreshMessage = record.refreshError
    ? `Refresh failed; retaining the last-good source snapshot: ${record.refreshError}`
    : '';
  return {
    ...parsedStatus,
    phase: record.refreshError || record.origin === 'cache' ? 'stale' : parsedStatus.phase,
    status: record.refreshError || record.origin === 'cache'
      ? parsedStatus.status === 'error' ? 'error' : 'degraded'
      : parsedStatus.status,
    message: [parsedStatus.message, retainedMessage, refreshMessage].filter(Boolean).join(' · ') || undefined,
  };
}

function viewportForCamera(center: [number, number], zoom: number): [number, number, number, number] | undefined {
  if (zoom < 5) return undefined;
  const longitudinalSpan = Math.max(1.5, 360 / (2 ** zoom) * 1.5);
  const latitudinalSpan = Math.max(1, longitudinalSpan * 0.56);
  const quantum = Math.max(0.25, longitudinalSpan * 0.2);
  const snappedLon = Math.round(center[0] / quantum) * quantum;
  const snappedLat = Math.round(center[1] / quantum) * quantum;
  return [
    Math.max(-180, snappedLon - longitudinalSpan / 2),
    Math.max(-85, snappedLat - latitudinalSpan / 2),
    Math.min(180, snappedLon + longitudinalSpan / 2),
    Math.min(85, snappedLat + latitudinalSpan / 2),
  ].map((value) => Number(value.toFixed(3))) as [number, number, number, number];
}

type SourceTask = {
  key: string;
  controller: AbortController | null;
  timer: number | null;
  queued: boolean;
  run: () => void;
};

function stopSource(task: SourceTask) {
  task.controller?.abort();
  if (task.timer != null) window.clearTimeout(task.timer);
}

/** One cancellable lane per demanded source; changing FIRMS scope leaves other lanes alone. */
export function useNaturalHazards({ sourceKeys, zoom, center, suspended }: {
  sourceKeys: readonly string[];
  zoom: number;
  center: [number, number];
  suspended: boolean;
}): NaturalHazardsState {
  const geometryZoom = hazardMapGeometryZoom(zoom);
  const firmsViewport = viewportForCamera(center, zoom);
  const firmsViewportKey = firmsViewport?.join(',') || '';
  const desired = INITIAL_SOURCE_PRIORITY.filter((source) => sourceKeys.includes(source));
  const demandKey = desired.join(',');
  const demand = useRef(desired);
  demand.current = desired;
  const scope = useRef({ geometryZoom, firmsViewportKey });
  scope.current = { geometryZoom, firmsViewportKey };
  const paused = useRef(suspended);
  paused.current = suspended;
  const mounted = useRef(true);
  const tasks = useRef(new Map<HazardMapSourceKey, SourceTask>());
  const records = useRef(new Map<HazardMapSourceKey, SourceRecord>());
  const errors = useRef(new Map<HazardMapSourceKey, string>());
  const publishFrame = useRef<number | null>(null);
  const expiryTimer = useRef<number | null>(null);
  const [state, setState] = useState<NaturalHazardsState>({
    events: [], response: null,
    sources: HAZARD_MAP_SOURCE_KEYS.map((key) => sourceStatus(key, undefined, false, undefined)),
    loading: desired.length > 0, error: null, rejectedCount: 0,
  });

  const publish = useCallback(() => {
    if (!mounted.current || publishFrame.current != null) return;
    publishFrame.current = window.requestAnimationFrame(() => {
      publishFrame.current = null;
      if (!mounted.current) return;
      const startedAt = performance.now();
      if(expiryTimer.current!=null)window.clearTimeout(expiryTimer.current);expiryTimer.current=null;
      let nextExpiry=Infinity;
      for(const source of demand.current) {
        const record=records.current.get(source);if(!record)continue;
        const deadline=hazardSnapshotExpiresAt(source,record.parsed.response);
        if(deadline!=null && Date.now()>deadline) {
          records.current.delete(source);errors.current.set(source,'Last source snapshot exceeds its retention budget');
        }else {
          if(deadline!=null)nextExpiry=Math.min(nextExpiry,deadline);
          const freshUntil = Date.parse(record.parsed.response.sources[0]?.staleAfter || '');
          if(Number.isFinite(freshUntil) && freshUntil>Date.now())nextExpiry=Math.min(nextExpiry,freshUntil);
        }
      }
      if(Number.isFinite(nextExpiry))expiryTimer.current=window.setTimeout(()=>{expiryTimer.current=null;publish();},Math.max(1,nextExpiry-Date.now()+1));
      const active = new Map(demand.current.flatMap((source) => {
        const record = records.current.get(source);
        return record ? [[source, record] as const] : [];
      }));
      const events = mergeHazardEvents(active);
      const sources = HAZARD_MAP_SOURCE_KEYS.map((source) => ({...sourceStatus(
        source, records.current.get(source), errors.current.has(source), errors.current.get(source),
      ), ...(!demand.current.includes(source) ? {phase: 'disabled' as const} : {})}));
      const activeStatuses = sources.filter((source) => demand.current.includes(source.key as HazardMapSourceKey));
      const responseErrors = [...active.values()].flatMap((record) => record.parsed.response.errors);
      for (const source of demand.current) {
        const message = errors.current.get(source);
        if (message && !active.has(source)) responseErrors.push({ source, code: message });
      }
      const rejectedCount = [...active.values()].reduce((total, record) => total + record.parsed.rejected.length, 0);
      const loading = activeStatuses.some((source) => source.status === 'loading');
      setState({
        events, sources, loading, rejectedCount,
        error: !events.length && !loading && responseErrors.length
          ? responseErrors.map((error) => error.code).join(' · ') : null,
        response: active.size ? {
          schemaVersion: 'natural-hazards-map.v1', generatedAt: latestGeneratedAt(active), events,
          sources: [...active.values()].flatMap((record) => record.parsed.response.sources),
          isPartial: activeStatuses.some((source) => source.status !== 'ok') || rejectedCount > 0,
          errors: responseErrors, counts: { events: events.length, byHazardKind: countsByKind(events) },
        } : null,
      });
      recordMapDataPhase('publish', 'all', startedAt, events.length);
    });
  }, []);

  const pump = useCallback(() => {
    if (!mounted.current || paused.current || document.hidden || navigator.onLine === false) return;
    let running = [...tasks.current.values()].filter((task) => task.controller).length;
    for (const task of tasks.current.values()) {
      if (running >= INITIAL_SOURCE_CONCURRENCY) break;
      if (!task.queued || task.controller) continue;
      running += 1;
      task.queued = false;
      task.run();
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const connectivity = () => {
      tasks.current.forEach(task => {
        stopSource(task); task.timer = null;
        task.queued = true;
      });
      if (!document.hidden && navigator.onLine !== false) pump();
    };
    document.addEventListener('visibilitychange', connectivity);
    window.addEventListener('online', connectivity);
    window.addEventListener('offline', connectivity);
    return () => {
      document.removeEventListener('visibilitychange', connectivity);
      window.removeEventListener('online', connectivity);
      window.removeEventListener('offline', connectivity);
      mounted.current = false;
      if(expiryTimer.current!=null)window.clearTimeout(expiryTimer.current);expiryTimer.current=null;
      tasks.current.forEach(stopSource);
      tasks.current.clear();
      if (publishFrame.current != null) window.cancelAnimationFrame(publishFrame.current);
      publishFrame.current = null;
    };
  }, [pump]);

  useEffect(() => {
    const keyFor = (source: HazardMapSourceKey) => `${geometryZoom}:${source === 'firms' ? firmsViewportKey : ''}`;
    tasks.current.forEach((task, source) => {
      if (suspended || !demand.current.includes(source) || task.key !== keyFor(source)) {
        tasks.current.delete(source);
        stopSource(task);
      }
    });
    if (!suspended) for (const source of demand.current) {
      if (tasks.current.has(source)) continue;
      const task: SourceTask = { key: keyFor(source), controller: null, timer: null, queued: true, run: () => {} };
      tasks.current.set(source, task);
      let failures = 0;
      let retryAfterMs: number | null = null;
      let blocked = false;
      let networkCommitted = false;
      const isCurrent = () => mounted.current && !paused.current && !document.hidden
        && demand.current.includes(source) && tasks.current.get(source) === task
        && task.key === `${scope.current.geometryZoom}:${source === 'firms' ? scope.current.firmsViewportKey : ''}`;
      const commit = (parsed: ParsedNaturalHazards, origin: SourceRecord['origin']) => {
        if (!isCurrent() || (origin === 'cache' && networkCommitted)) return;
        const existing = records.current.get(source);
        const signature = sourceSignature(parsed);
        records.current.set(source, existing?.signature === signature
          ? { ...existing, origin, refreshError: null }
          : { parsed, signature, origin, refreshError: null });
        if (origin === 'network') networkCommitted = true;
        errors.current.delete(source);
        publish();
      };
      const schedule = (failed: boolean) => {
        if (!isCurrent() || blocked) return;
        const expiresAt = Date.parse(records.current.get(source)?.parsed.response.sources[0]?.staleAfter || '');
        // A retained/deadline response is HTTP-successful but not fresh. Check
        // again with bounded backoff instead of waiting FIRMS' 15 min / climate's
        // 6 h interval. This polls our shared snapshot, not the external provider.
        const sourceState = records.current.get(source)?.parsed.response.sources[0];
        const stale = sourceState?.status === 'degraded' || sourceState?.status === 'error'
          || (Number.isFinite(expiresAt) && expiresAt <= Date.now());
        const refreshDelay = Number.isFinite(expiresAt) && expiresAt > Date.now()
          ? Math.min(REFRESH_INTERVAL_MS[source], Math.max(1000, expiresAt - Date.now()))
          : REFRESH_INTERVAL_MS[source];
        const delay = failed ? RETRY_DELAYS_MS[Math.min(RETRY_DELAYS_MS.length - 1, Math.max(0, failures - 1))]!
          : stale ? Math.min(60_000, 30_000 * Math.max(1, failures)) : refreshDelay;
        const jitter = Math.floor(Math.random() * (failed ? 1000 : 3000));
        task.timer = window.setTimeout(() => {
          task.timer = null; task.queued = true; pump();
        }, Math.max(delay + jitter, retryAfterMs || 0));
      };
      task.run = () => {
        const controller = new AbortController();
        task.controller = controller;
        const startedAt = performance.now();
        void fetchNaturalHazardMapSource(source, geometryZoom, source === 'firms' ? firmsViewport : undefined, controller.signal)
          .then((payload) => {
            if (!isCurrent() || controller.signal.aborted) return;
            recordMapDataPhase('network', source, startedAt, payload.events?.length || 0);
            const parseStartedAt = performance.now();
            const parsed = parseNaturalHazardsResponse(payload);
            const upstream = payload.sources[0] as typeof payload.sources[number] & {condition?: string; retryAfterSeconds?: number};
            blocked = upstream?.condition === 'blocked';
            retryAfterMs = Number.isFinite(upstream?.retryAfterSeconds) ? Math.max(0, Number(upstream.retryAfterSeconds) * 1000) : null;
            if (!parsed.events.length && (parsed.rejected.length || parsed.response.sources.some(item => item.status === 'error'))) {
              throw new Error(parsed.response.errors.map(item=>item.code).join(' · ') || 'Source response was invalid or unavailable');
            }
            recordMapDataPhase('parse', source, parseStartedAt, parsed.events.length);
            commit(parsed, 'network');
            const expiresAt = Date.parse(upstream?.staleAfter || '');
            failures = upstream?.status === 'degraded' || upstream?.status === 'error'
              || (Number.isFinite(expiresAt) && expiresAt <= Date.now()) ? failures + 1 : 0;
            void writeHazardMapSnapshot(source, geometryZoom, parsed.response, source === 'firms' ? firmsViewportKey : '');
            schedule(false);
          }).catch((error) => {
            if (!isCurrent() || controller.signal.aborted) return;
            const message = error instanceof Error ? error.message : String(error);
            failures += 1;
            blocked ||= error instanceof ApiHttpError && [401,403].includes(error.status);
            if (error instanceof ApiHttpError) retryAfterMs = error.retryAfterMs;
            errors.current.set(source, message);
            const existing = records.current.get(source);
            if (existing && hazardSnapshotRetainable(source, existing.parsed.response)) records.current.set(source, { ...existing, refreshError: message });
            else records.current.delete(source);
            publish(); schedule(true);
          }).finally(() => {
            if (task.controller === controller) {
              task.controller = null;
              if (isCurrent()) pump();
            }
          });
      };
      const cacheStartedAt = performance.now();
      void readHazardMapSnapshot(source, geometryZoom, source === 'firms' ? firmsViewportKey : '').then((cached) => {
        if (!cached || !isCurrent() || networkCommitted) return;
        recordMapDataPhase('cache-read', source, cacheStartedAt, cached.payload.events?.length || 0);
        try { commit(parseNaturalHazardsResponse(cached.payload), 'cache'); }
        catch { /* Invalid cached schemas are replaced by the network response. */ }
      });
    }
    publish();
    pump();
  }, [demandKey, geometryZoom, firmsViewportKey, suspended, publish, pump]);

  return state;
}
