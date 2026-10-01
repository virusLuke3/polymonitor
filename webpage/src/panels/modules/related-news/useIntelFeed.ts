import { useEffect, useMemo, useState } from 'preact/hooks';
import { fetchLatestContent, fetchMarketContent } from '@/services/api';
import { usePanelRuntime } from '@/panels/usePanelRuntime';
import type { PanelModule } from '@/panels/types';
import {
  activePayload, intelSnapshot, INTEL_REFRESH_MS, INTEL_STALE_MS, parseIntelPayload,
  reconcileReader, resourceId, type IntelPayload, type IntelSnapshot,
} from './model';

export { fingerprint, validScope } from './model';

/** Parameterized content uses the existing Runtime with a dedicated endpoint and resource key. */
export function useIntelFeed(marketId: number | null, scope: 'market' | 'global', days: number) {
  const key = resourceId({ marketId, scope, days });
  const panels = useMemo<PanelModule[]>(() => [{
    id: key, title: 'Related Intelligence', eyebrow: 'intel', description: 'Public content resource', batch: false,
    refreshPolicy: { tier: 'fast', intervalMs: INTEL_REFRESH_MS, staleAfterMs: INTEL_STALE_MS },
    fetchData: async (context) => {
      const value = scope === 'market'
        ? await fetchMarketContent(marketId!, 20, 8000, context?.signal, days)
        : await fetchLatestContent(20, context?.signal, days);
      return intelSnapshot(parseIntelPayload(value, { marketId, scope, days }));
    },
  }], [key, marketId, scope, days]);
  const activePanelIds = scope === 'market' && marketId == null ? [] : [key];
  const runtime = usePanelRuntime({ panels, activePanelIds });
  const latest = (runtime.getData(key) as IntelSnapshot | undefined)?.content;
  const status = runtime.getStatus(key);
  const [reader, setReader] = useState<{ key: string; data: IntelPayload | null; pending: IntelPayload | null }>({ key, data: null, pending: null });
  const [, expire] = useState(0);
  useEffect(() => {
    if (latest) setReader(old => reconcileReader(old, key, latest));
  }, [key, latest]);
  const current = reader.key === key ? reader : { key, data: null, pending: null };
  const data = current.data ? activePayload(current.data) : null;
  const pending = current.pending ? activePayload(current.pending) : null;
  useEffect(() => {
    const times = [...(current.data?.items || []), ...(current.pending?.items || [])]
      .map(item => Date.parse(item.expires_at || '')).filter(time => Number.isFinite(time) && time > Date.now());
    if (!times.length) return;
    const timer = window.setTimeout(() => expire(version => version + 1), Math.min(2_147_483_647, Math.max(1, Math.min(...times) - Date.now())));
    return () => window.clearTimeout(timer);
  }, [current.data, current.pending, data?.items.length, pending?.items.length]);
  const hasNew = pending?.items.some(item => !data?.items.some(old => String(old.id) === String(item.id)));
  return {
    key, data, pending: hasNew ? pending : null, status,
    error: status.error, loading: !data && !status.error,
    stale: Boolean(data?.stale || ['stale', 'degraded', 'error'].includes(status.phase)),
    refresh: () => runtime.refreshIds([key], { reason: 'manual', force: true }),
    accept: () => setReader(old => old.key === key && old.pending ? { ...old, data: activePayload(old.pending), pending: null } : old),
  };
}
