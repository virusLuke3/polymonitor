import { usePanelResource, type PanelResource } from '@/panels/usePanelResource';
import { fetchRuntimeCommodities } from '@/services/api';
import { parseCommodities, commodityStatusLabel, REFRESH_MS, MAX_AGE_MS, RETAIN_MS, type CommodityPayload } from './model';

export const commodityResource: PanelResource<CommodityPayload> = {
  key: 'commodities:global:previous-close:v4', title: 'Commodities',
  maxAgeMs: MAX_AGE_MS, staleAgeMs: RETAIN_MS, acceptStale: true,
  cache: { version: 4, maxChars: 192_000 },
  refreshPolicy: { tier: 'fast', intervalMs: REFRESH_MS, staleAfterMs: MAX_AGE_MS },
  fetch: context => fetchRuntimeCommodities(context?.signal), parse: parseCommodities,
  updatedAt: value => Date.parse(value.generatedAt), statusLabel: commodityStatusLabel,
  shouldPersist: (next, previous) => next.status === 'ok' || previous == null
    || (next.coverage.succeeded >= previous.coverage.succeeded && next.items.length >= previous.items.length),
};
export const useCommodityFeed = () => usePanelResource(commodityResource);
