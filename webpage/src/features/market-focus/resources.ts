import type { MarketsPayload, WorkspaceBundle, ChartPayload, MarketGroupSort } from '@/types';
import { fetchMarketsPage, fetchMarketFocusTile, fetchMarketChart, MARKET_CATALOG_REQUEST_TIMEOUT_MS } from '@/services/api';
import type { PanelResource } from '@/panels/usePanelResource';
import { publicSnapshot, record, records, strings, textFields } from '@/panels/public-snapshot';
import { RuntimeResponseError, runtimeTimestamp } from '@/panels/runtime-store';
import { bundleMatchesMarket } from './marketBundle';

export const MARKET_CATALOG_AUTO_REFRESH_MS = 5 * 60_000;
const market = (value: unknown) => record(value) && Number.isSafeInteger(value.id) && value.id > 0
  && typeof value.title === 'string' && typeof value.slug === 'string'
  && textFields(value, ['category', 'conditionId', 'yesTokenId', 'noTokenId', 'status'])
  && (value.tags == null || strings(value.tags)) && (value.outcomePrices == null || records(value.outcomePrices));

export function marketCatalogResource(sort: MarketGroupSort): PanelResource<MarketsPayload> {
  return { ...publicSnapshot<MarketsPayload>({
    key: `markets:active:page:1:limit:50:sort:${sort}:v1`, version: 1,
    maxAgeMs: MARKET_CATALOG_AUTO_REFRESH_MS, staleAgeMs: 15 * 60_000, acceptStale: true,
    updatedAt: runtimeTimestamp,
    parse(value) {
      if (!record(value) || !records(value.items) || !value.items.every(market)
        || !record(value.pagination) || value.pagination.page !== 1 || value.pagination.pageSize !== 50
        || (value.sort != null && value.sort !== sort)) throw new RuntimeResponseError('Invalid market catalog identity');
      if (value.items.some(item => ['semantics_query_failed', 'semantics_database_unavailable'].includes(item.outcomeSemanticsStatus))) {
        throw new RuntimeResponseError('Quote verification is temporarily unavailable; keeping the previous page.');
      }
      return value as MarketsPayload;
    },
  }), title: 'Market catalog', refreshPolicy: { tier: 'slow', intervalMs: MARKET_CATALOG_AUTO_REFRESH_MS, requestTimeoutMs: MARKET_CATALOG_REQUEST_TIMEOUT_MS },
  fetch: context => fetchMarketsPage(1, '', 50, context?.signal, sort) };
}

export function marketDetailResource(id: number | null, missing: () => void): PanelResource<WorkspaceBundle> {
  return { ...publicSnapshot<WorkspaceBundle>({
    key: `market-detail:${id}:v1`, version: 1, maxAgeMs: 60_000, staleAgeMs: 300_000, acceptStale: true,
    updatedAt: runtimeTimestamp,
    parse(value) {
      if (!record(value) || id == null || !market(value.market) || !bundleMatchesMarket(value as WorkspaceBundle, id)) throw new RuntimeResponseError('Market detail identity mismatch');
      if (value.focusStatus === 'unavailable' || value.focusStatus === 'warming') throw new RuntimeResponseError('Market metadata is unavailable');
      // This owner is metadata/catalog context only. Live book, flow and Oracle
      // are separate resources and cannot be resurrected by its cached response.
      return { ...(value as WorkspaceBundle), lob: null, oracle: null, trades: [], chart: null } as WorkspaceBundle;
    },
  }), title: 'Market metadata', refreshPolicy: { tier: 'fast', intervalMs: 60_000, requestTimeoutMs: 6000 },
  fetch: async context => {
    try { return await fetchMarketFocusTile(id!, 6000, context?.signal); }
    catch (error) { if (!context?.signal.aborted && (error as {status?: number})?.status === 404) missing(); throw error; }
  } };
}

export function marketChartResource(id: number | null, range: string): PanelResource<ChartPayload> {
  return { ...publicSnapshot<ChartPayload>({
    key: `market-chart:${id}:range:${range}:interval:auto:v1`, version: 1, storage: 'indexeddb', maxChars: 2_000_000,
    maxAgeMs: 90_000, staleAgeMs: 300_000, acceptStale: true, updatedAt: runtimeTimestamp,
    parse(value) {
      if (!record(value) || id == null || value.marketId !== id || (value.localMarketId != null && value.localMarketId !== id)
        || value.range !== range || !records(value.points) || value.points.length > 10_000
        || !value.points.every(point => typeof point.timestamp === 'string' && Number.isFinite(Date.parse(point.timestamp))
          && ['yesPrice', 'noPrice', 'value', 'volume'].every(key => point[key] == null || ['string', 'number'].includes(typeof point[key]) && Number.isFinite(Number(point[key]))))) {
        throw new RuntimeResponseError('Invalid market chart identity/points');
      }
      if (value.historyStatus === 'unavailable') throw new RuntimeResponseError('Market history is unavailable');
      return value as ChartPayload;
    },
  }), title: 'Market history', refreshPolicy: { tier: 'fast', intervalMs: 90_000, requestTimeoutMs: 10_000 },
  fetch: context => fetchMarketChart(id!, range, undefined, 10_000, context?.signal) };
}
