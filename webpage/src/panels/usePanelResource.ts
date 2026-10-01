import { useEffect, useMemo, useState } from 'preact/hooks';
import type { PanelFetchContext, PanelModule, PanelRefreshConfig } from './types';
import { usePanelRuntime } from './usePanelRuntime';
import { readResourceCache, resourceIsCurrent, writeResourceCache, type ResourceCacheContract } from './resource-cache';

export interface PanelResource<T> extends ResourceCacheContract<T> {
  title: string;
  fetch: (context?: PanelFetchContext) => Promise<unknown>;
  refreshPolicy: PanelRefreshConfig;
}

/** A parameterized endpoint on the existing scheduler, cancellation and retry owner.
 * Memoize the contract and key the owning component by contract.key.
 */
export function usePanelResource<T>(contract: PanelResource<T>) {
  const seed = useMemo(() => {
    try { return readResourceCache(contract, window.localStorage); } catch { return null; }
  }, [contract]);
  const panels = useMemo<PanelModule[]>(() => [{
    id: contract.key, title: contract.title, eyebrow: 'resource', description: contract.title,
    batch: false, refreshPolicy: contract.refreshPolicy,
    fetchData: async context => {
      const raw = await contract.fetch(context);
      const value = contract.parse(raw);
      const timestamp = contract.updatedAt(value);
      if (timestamp != null && !resourceIsCurrent(timestamp, contract.maxAgeMs)) throw new Error('Resource snapshot is overdue');
      if (context?.signal.aborted) throw new DOMException('Aborted', 'AbortError');
      try { writeResourceCache(contract, raw, window.localStorage); } catch { /* Optional public cache. */ }
      return value;
    },
  }], [contract]);
  const runtime = usePanelRuntime({ panels, activePanelIds: [contract.key],
    initialData: () => seed == null ? {} : { [contract.key]: seed } });
  const status = runtime.getStatus(contract.key);
  const latest = runtime.getData(contract.key) as T | undefined;
  const timestamp = latest == null ? null : contract.updatedAt(latest) ?? status.checkedAt ?? null;
  const [, tick] = useState(0);
  const expired = latest != null && timestamp != null && !resourceIsCurrent(timestamp, contract.maxAgeMs);
  useEffect(() => {
    if (timestamp == null || expired) return;
    const timer = window.setTimeout(() => tick(version => version + 1),
      Math.min(2_147_483_647, Math.max(1, timestamp + contract.maxAgeMs - Date.now())));
    return () => window.clearTimeout(timer);
  }, [timestamp, contract.maxAgeMs, expired]);
  const data = expired ? null : latest ?? null;
  return {
    data, status, expired, suspended: runtime.suspended,
    loading: !data && !status.error && !expired,
    fromCache: data != null && status.checkedAt == null,
    error: status.error || (expired ? 'Resource snapshot is overdue' : null),
    refresh: () => runtime.refreshIds([contract.key], { reason: 'manual', force: true }),
  };
}
