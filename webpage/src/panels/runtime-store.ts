import type {
  PanelFetchContext,
  PanelModule,
  PanelRuntimeData,
} from './types';
import {
  fetchRuntimePanels,
  type RuntimePanelMetadata,
} from '@/services/api';

export type PanelRuntimeFetchOptions = {
  signal: AbortSignal;
  panelSignals?: Record<string, AbortSignal>;
  reason: PanelFetchContext['reason'];
  maxBatchSize?: number;
  onPanelData?: (panelId: string, value: unknown, metadata?: RuntimePanelMetadata, raw?: unknown) => void;
  onPanelError?: (panelId: string, error: Error) => void;
  onPanelSettled?: (panelId: string) => void;
};

export type PanelRuntimeFetchResult = {
  data: PanelRuntimeData;
  errors: Record<string, Error>;
  metadata: Record<string, RuntimePanelMetadata>;
};

export class RuntimeResponseError extends Error {
  constructor(message: string, public retryable = true) { super(message); }
}

export function runtimeTimestamp(value: unknown): number | null {
  if (!value || typeof value !== 'object') return null;
  const payload = value as Record<string, unknown>;
  const candidate = payload.generatedAt || payload.updatedAt || payload.asOf || payload.timestamp;
  const parsed = typeof candidate === 'number' ? candidate * (candidate > 10_000_000_000 ? 1 : 1000)
    : Date.parse(String(candidate || ''));
  return Number.isFinite(parsed) ? parsed : null;
}

/** Every transport uses the same acceptance path. Domain invalidations may be
 * published deliberately (e.g. revoked Alpha evidence), never cached as READY. */
export function parseRuntimeSnapshot(panel: PanelModule, raw: unknown, metadata?: RuntimePanelMetadata) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new RuntimeResponseError('Invalid runtime snapshot');
  const status = String((raw as { status?: unknown }).status || '').toLowerCase();
  if (['unavailable', 'error', 'failed', 'gateway-error', 'agent-error'].includes(status)) {
    throw new RuntimeResponseError('Source snapshot is unavailable');
  }
  const contract = panel.snapshot;
  const value = contract ? contract.parse(raw) : raw;
  const timestamp = contract ? contract.updatedAt(value) : runtimeTimestamp(value)
    ?? (metadata?.freshness?.observedAt ? Date.parse(metadata.freshness.observedAt) : null);
  if (timestamp == null || !Number.isFinite(timestamp) || timestamp > Date.now() + 60_000) {
    throw new RuntimeResponseError('Resource snapshot time is unknown or invalid');
  }
  if (contract) {
    const age = contract.acceptStale ? Math.max(contract.maxAgeMs, contract.staleAgeMs ?? contract.maxAgeMs) : contract.maxAgeMs;
    if (Date.now() - timestamp >= age) throw new RuntimeResponseError('Resource snapshot is overdue');
  }
  return value;
}

export async function fetchPanelRuntimeData(
  panels: PanelModule[],
  options: PanelRuntimeFetchOptions,
): Promise<PanelRuntimeFetchResult> {
  const fetchable = panels.filter(panel => typeof panel.fetchData === 'function');
  const data: PanelRuntimeData = {}, errors: Record<string, Error> = {}, metadata: Record<string, RuntimePanelMetadata> = {};
  type Response = { raw: unknown; metadata?: RuntimePanelMetadata };
  // Each resource owns a completion and a deadline. Producer promises are not
  // awaited after expiry: an uncooperative fetch wrapper cannot park the lane.
  const states = new Map(fetchable.map(panel => {
    const external = options.panelSignals?.[panel.id] ?? options.signal;
    const controller = new AbortController();
    let resolve!: (value: Response) => void, reject!: (error: unknown) => void;
    const response = new Promise<Response>((yes, no) => { resolve = yes; reject = no; });
    let finish!: () => void;
    const finished = new Promise<void>(done => { finish = done; });
    const state = { panel, external, controller, resolve, reject, finished, done: false };
    const abort = () => reject(new DOMException('Aborted', 'AbortError'));
    const timeoutMs = Math.max(1, panel.refreshPolicy?.requestTimeoutMs ?? 30_000);
    const timer = setTimeout(() => reject(new RuntimeResponseError(`Panel request exceeded ${timeoutMs}ms`)), timeoutMs);
    external.addEventListener('abort', abort, { once: true });
    options.signal.addEventListener('abort', abort, { once: true });
    if (external.aborted || options.signal.aborted) abort();
    const consumer = response.then(({ raw, metadata: meta }) => {
      if (external.aborted || options.signal.aborted) return;
      const value = parseRuntimeSnapshot(panel, raw, meta);
      data[panel.id] = value;
      if (meta) metadata[panel.id] = meta;
      options.onPanelData?.(panel.id, value, meta, raw);
    }).catch(error => {
      if (external.aborted || options.signal.aborted) return;
      const normalized = error instanceof Error ? error : new Error(String(error));
      errors[panel.id] = normalized;
      options.onPanelError?.(panel.id, normalized);
    }).finally(() => {
      state.done = true;
      clearTimeout(timer);
      external.removeEventListener('abort', abort);
      options.signal.removeEventListener('abort', abort);
      controller.abort();
      options.onPanelSettled?.(panel.id);
      finish();
    });
    return [panel.id, { ...state, consumer, get done() { return state.done; } }] as const;
  }));
  const individually = (entries: PanelModule[]) => {
    entries.forEach(panel => {
      const state = states.get(panel.id)!;
      if (state.done || state.external.aborted || options.signal.aborted) return;
      void Promise.resolve().then(() => panel.fetchData!({ signal: state.controller.signal, reason: options.reason }))
        .then(raw => state.resolve({ raw }), state.reject);
    });
  };
  individually(fetchable.filter(panel => panel.batch === false));
  const batchEntries = fetchable.filter(panel => panel.batch !== false);
  const maxBatchSize = Math.max(1, options.maxBatchSize || 12);
  const dispatchBatches = async () => {
    for (let offset = 0; offset < batchEntries.length; offset += maxBatchSize) {
      const batch = batchEntries.slice(offset, offset + maxBatchSize).filter(panel => !states.get(panel.id)!.done);
      if (options.signal.aborted) break;
      if (batch.length <= 1) {
        individually(batch);
        await Promise.all(batch.map(panel => states.get(panel.id)!.finished));
        continue;
      }
      const controller = new AbortController();
      const batchStates = batch.map(panel => states.get(panel.id)!);
      const abortIfFinished = () => {
        if (batchStates.every(state => state.controller.signal.aborted)) controller.abort();
      };
      batchStates.forEach(state => state.controller.signal.addEventListener('abort', abortIfFinished));
      try {
        const request = fetchRuntimePanels(batch.map(panel => panel.id),
          Object.fromEntries(batch.filter(panel => panel.request).map(panel => [panel.id, panel.request!.limit])), controller.signal);
        const payload = await Promise.race([request, Promise.all(batchStates.map(state => state.finished)).then(() => null)]);
        if (!payload) continue;
        for (const state of batchStates) {
          if (state.done) continue;
          const value = payload.panels?.[state.panel.id];
          if (value === undefined) state.reject(new RuntimeResponseError(payload.errors?.[state.panel.id] || `Batch response omitted panel ${state.panel.id}`));
          else state.resolve({ raw: value, metadata: payload.metadata?.[state.panel.id] });
        }
      } catch {
        // Route/transport failure falls back within the ORIGINAL resource lease.
        individually(batch);
      } finally {
        batchStates.forEach(state => state.controller.signal.removeEventListener('abort', abortIfFinished));
      }
    }
  };
  void dispatchBatches();
  await Promise.all([...states.values()].map(state => state.consumer));
  return { data, errors, metadata };
}

export function mergeRuntimeData(current: PanelRuntimeData, patch: PanelRuntimeData): PanelRuntimeData {
  if (!Object.keys(patch).length) return current;
  const next = { ...current };
  for (const [panelId, value] of Object.entries(patch)) {
    const previous = current[panelId];
    if (hasItems(previous) && isEmptyWarming(value)) {
      continue;
    }
    next[panelId] = value;
  }
  return next;
}

function hasItems(value: unknown): boolean {
  return Boolean(
    value &&
    typeof value === 'object' &&
    Array.isArray((value as { items?: unknown[] }).items) &&
    ((value as { items?: unknown[] }).items?.length || 0) > 0,
  );
}

function isEmptyWarming(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false;
  const payload = value as { items?: unknown[]; status?: unknown };
  return (!Array.isArray(payload.items) || payload.items.length === 0) && String(payload.status || '').toLowerCase() === 'warming';
}
