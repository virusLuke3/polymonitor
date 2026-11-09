import { usePanelResource } from '@/panels/usePanelResource';
import { marketCatalogResource } from './resources';
import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { fetchMarketSearch } from '@/services/api';
import type { BootstrapPayload, MarketListItem, MarketGroupItem, MarketGroupSort } from '@/types';

export { MARKET_CATALOG_AUTO_REFRESH_MS } from './resources';

/** The catalog is a public resource shared with the existing market workspace. */
export function useMarketCatalog(bootstrap: BootstrapPayload | null, enabled: boolean, sort: MarketGroupSort = 'volume') {
  const feed = usePanelResource(marketCatalogResource(sort), enabled);
  const receivedCatalog = useRef(false);
  if (feed.data) receivedCatalog.current = true;
  const markets = useMemo(() => feed.data
    ? feed.data.items.map(item => ({ ...item, catalogFetchedAt: feed.data!.generatedAt }))
    : receivedCatalog.current ? [] : bootstrap?.activeMarketsPreview || [], [feed.data, bootstrap]);
  return { markets, marketGroups: [] as MarketGroupItem[], marketCatalogRefreshing: Boolean(feed.status.fetching),
    marketCatalogError: feed.error || (feed.status.phase === 'stale' || feed.data?.status === 'stale' ? 'Catalog is stale; showing the last stored page.' : null),
    catalogLoaded: Boolean(feed.data || feed.error) };
}

/** Command search has a separate query identity and no periodic refresh. */
export function useMarketSearch(query: string, enabled: boolean, sort: MarketGroupSort = 'volume') {
  const [hits, setHits] = useState<MarketListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setHits([]); setLoading(false); setUnavailable(false);
    if (!enabled || !query.trim()) return;
    const timer = window.setTimeout(() => {
      setLoading(true);
      void fetchMarketSearch(query.trim(), 50, controller.signal, sort).then((payload) => {
        if (!controller.signal.aborted) setHits(payload.items || []);
      }).catch(() => {
        if (!controller.signal.aborted) setUnavailable(true);
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 180);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [query, enabled, sort]);
  return { hits, loading, unavailable };
}
