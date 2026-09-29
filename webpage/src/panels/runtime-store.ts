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
  reason: PanelFetchContext['reason'];
  maxBatchSize?: number;
  onPanelData?: (panelId: string, value: unknown, metadata?: RuntimePanelMetadata) => void;
  onPanelError?: (panelId: string, error: Error) => void;
  onPanelSettled?: (panelId: string) => void;
};

export type PanelRuntimeFetchResult = {
  data: PanelRuntimeData;
  errors: Record<string, Error>;
  metadata: Record<string, RuntimePanelMetadata>;
};

export async function fetchPanelRuntimeData(
  panels: PanelModule[],
  options: PanelRuntimeFetchOptions,
): Promise<PanelRuntimeFetchResult> {
  const fetchable = panels.filter((panel) => typeof panel.fetchData === 'function');
  const entries = fetchable.filter((panel) => panel.batch !== false);
  const data: PanelRuntimeData = {};
  const errors: Record<string, Error> = {};
  const metadata: Record<string, RuntimePanelMetadata> = {};
  const maxBatchSize = Math.max(1, options.maxBatchSize || 12);

  const recordData = (panelId: string, value: unknown, panelMetadata?: RuntimePanelMetadata) => {
    if (options.signal.aborted) return;
    data[panelId] = value;
    if (panelMetadata) metadata[panelId] = panelMetadata;
    options.onPanelData?.(panelId, value, panelMetadata);
  };
  const recordError = (panelId: string, error: unknown) => {
    if (options.signal.aborted) return;
    const normalized = error instanceof Error ? error : new Error(String(error || 'Panel refresh failed.'));
    errors[panelId] = normalized;
    options.onPanelError?.(panelId, normalized);
  };
  const fetchIndividually = async (individualEntries: PanelModule[]) => {
    await Promise.all(individualEntries.map(async (panel) => {
      if (options.signal.aborted) return;
      try {
        const value = await panel.fetchData!({ signal: options.signal, reason: options.reason });
        if (value !== undefined) recordData(panel.id, value);
        else recordError(panel.id, new Error(`Panel ${panel.id} returned no data.`));
      } catch (error) {
        recordError(panel.id, error);
      } finally {
        options.onPanelSettled?.(panel.id);
      }
    }));
  };

  const individualRequests = fetchIndividually(fetchable.filter((panel) => panel.batch === false));
  for (let offset = 0; offset < entries.length; offset += maxBatchSize) {
    if (options.signal.aborted) break;
    const batch = entries.slice(offset, offset + maxBatchSize);
    if (batch.length <= 1) {
      await fetchIndividually(batch);
      continue;
    }
    try {
      const ids = batch.map((panel) => panel.id);
      const payload = await fetchRuntimePanels(ids, Object.fromEntries(batch.filter((panel) => panel.request).map((panel) => [panel.id, panel.request!.limit])), options.signal);
      const values = payload.panels || {};
      const batchErrors = payload.errors || {};
      const batchMetadata = payload.metadata || {};
      batch.forEach((panel) => {
        const value = values[panel.id];
        if (value !== undefined) {
          recordData(panel.id, value, batchMetadata[panel.id]);
        } else {
          recordError(panel.id, new Error(batchErrors[panel.id] || `Batch response omitted panel ${panel.id}.`));
        }
        options.onPanelSettled?.(panel.id);
      });
    } catch (error) {
      if (options.signal.aborted) {
        batch.forEach((panel) => {
          recordError(panel.id, error);
          options.onPanelSettled?.(panel.id);
        });
        continue;
      }
      // Fall back to individual panel requests if the batch route is unavailable.
      await fetchIndividually(batch);
    }
  }
  await individualRequests;
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
