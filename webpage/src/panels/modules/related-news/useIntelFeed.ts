import { useEffect, useMemo, useState } from 'preact/hooks';
import { fetchLatestContent, fetchMarketContent } from '@/services/api';
import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import {
  activePayload, intelSnapshot, INTEL_REFRESH_MS, INTEL_STALE_MS, INTEL_ITEM_LIMIT, parseIntelPayload,
  resourceId, intelStatusLabel, type IntelPayload, type IntelSnapshot,
} from './model';

export { validScope } from './model';

/** Parameterized content uses the existing Runtime with a dedicated endpoint and resource key. */
export function useIntelResource(marketId: number | null, scope: 'market' | 'global', days: number, active?: boolean) {
  const key = resourceId({ marketId, scope, days });
  const contract = useMemo<PanelResource<IntelSnapshot>>(() => ({
    key, title: 'Related Intelligence', maxAgeMs: 5 * 60_000, staleAgeMs: 30 * 60_000, cache: { version: 4, maxChars: 512_000 },
    refreshPolicy: { tier: 'fast', intervalMs: INTEL_REFRESH_MS, staleAfterMs: INTEL_STALE_MS },
    fetch: async context => scope === 'market'
        ? await fetchMarketContent(marketId!, INTEL_ITEM_LIMIT, 8000, context?.signal, days)
        : await fetchLatestContent(INTEL_ITEM_LIMIT, context?.signal, days),
    parse: value => {
      if (value && typeof value === 'object' && (value as IntelPayload).status === 'unavailable'
        && !(value as IntelPayload).items?.length) throw new Error('Content service unavailable');
      const content = parseIntelPayload(value, { marketId, scope, days });
      // Legacy HTTP 200 failures must enter the same bounded retry path as HTTP 503.
      if (content.status === 'unavailable' && !content.items.length) throw new Error('Content service unavailable');
      return intelSnapshot(content);
    },
    updatedAt: value => value.generatedAt ? Date.parse(value.generatedAt) : null,
    statusLabel: intelStatusLabel,
    shouldPersist: next => !next.content.rejectedItemCount && !next.content.stale
      && next.content.status !== 'unavailable',
  }), [key, marketId, scope, days]);
  return usePanelResource(contract, active);
}

export function useIntelFeed(marketId: number | null, scope: 'market' | 'global', days: number) {
  const resource = useIntelResource(marketId, scope, days);
  const latest = resource.data?.content;
  const status = resource.status;
  const [, expire] = useState(0);
  // A successful scheduled read is also a display update. Do not hold new
  // entries behind a separate reader-acceptance state or a manual button.
  const data = latest ? activePayload(latest) : null;
  useEffect(() => {
    const times = (latest?.items || [])
      .map(item => Date.parse(item.expires_at || '')).filter(time => Number.isFinite(time) && time > Date.now());
    if (!times.length) return;
    const timer = window.setTimeout(() => expire(version => version + 1), Math.min(2_147_483_647, Math.max(1, Math.min(...times) - Date.now())));
    return () => window.clearTimeout(timer);
  }, [latest, data?.items.length]);
  return {
    data, status,
    error: resource.error, loading: resource.loading, fromCache: resource.fromCache, suspended: resource.suspended,
    stale: Boolean(data?.stale || ['stale', 'degraded', 'error'].includes(status.phase)),
    refresh: resource.refresh,
  };
}
