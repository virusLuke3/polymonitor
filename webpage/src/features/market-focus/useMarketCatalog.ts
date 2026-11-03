import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { fetchMarketsPage, fetchMarketSearch } from '@/services/api';
import type { BootstrapPayload, MarketListItem, MarketGroupItem, MarketGroupSort } from '@/types';

export const MARKET_CATALOG_AUTO_REFRESH_MS = 5 * 60_000;

/** One owner for the active catalog, refreshed only while the page is visible. */
export function useMarketCatalog(bootstrap: BootstrapPayload | null, enabled: boolean, sort: MarketGroupSort = 'volume') {
  const [markets, setMarkets] = useState<MarketListItem[]>([]);
  const [marketGroups, setMarketGroups] = useState<MarketGroupItem[]>([]);
  const [marketCatalogRefreshing, setRefreshing] = useState(false);
  const [marketCatalogError, setError] = useState<string | null>(null);
  const [catalogLoaded, setLoaded] = useState(false);
  const requestRef = useRef<{ controller: AbortController; promise: Promise<void> } | null>(null);
  const mounted = useRef(true);
  const hydrated = useRef({ markets: false, groups: false });
  const retryAt = useRef(0);
  const refreshCatalog = useCallback((): Promise<void> => {
    if (requestRef.current) return requestRef.current.promise;
    if (document.hidden) return Promise.resolve();
    if (Date.now() < retryAt.current) return Promise.resolve();
    retryAt.current = Date.now() + MARKET_CATALOG_AUTO_REFRESH_MS;
    const controller = new AbortController();
    setRefreshing(true);
    const isCurrent = () => !controller.signal.aborted && mounted.current;
    const errors: string[] = [];
    let retryAfterMs = 0;
    const promise = Promise.allSettled([
      fetchMarketsPage(1, '', 50, controller.signal, sort).then((catalog) => {
        if (!isCurrent()) return;
        if (catalog.items?.some((item) => ['semantics_query_failed', 'semantics_database_unavailable'].includes(item.outcomeSemanticsStatus || ''))) {
          throw new Error('Quote verification is temporarily unavailable; keeping the previous page.');
        }
        hydrated.current.markets = true;
        setMarkets((catalog.items || []).map((item) => ({ ...item, catalogFetchedAt: catalog.generatedAt }))); setMarketGroups([]); setLoaded(true);
        if (catalog.status === 'stale' && catalog.refreshStatus !== 'refreshing') errors.push('Catalog refresh failed; showing the last stored page.');
      }).catch((error) => {
        if (isCurrent()) {
          errors.push(error instanceof Error ? error.message : 'Market catalog refresh failed.');
          retryAfterMs = Number(error?.retryAfterMs) || 0;
        }
      }),
    ]).then(() => {
      if (isCurrent()) {
        setLoaded(true); setError(errors[0] || null);
        retryAt.current = Math.max(retryAt.current, Date.now() + retryAfterMs);
      }
    }).finally(() => {
      if (requestRef.current?.controller === controller) requestRef.current = null;
      if (mounted.current && !controller.signal.aborted) setRefreshing(false);
    });
    requestRef.current = { controller, promise };
    return promise;
  }, [sort]);
  useEffect(() => {
    if (!bootstrap) return;
    if (!hydrated.current.markets) setMarkets(bootstrap.activeMarketsPreview || []);

  }, [bootstrap]);
  useEffect(() => {
    if (!enabled) return;
    retryAt.current = 0;
    setMarkets([]); setLoaded(false); setError(null);
    void refreshCatalog();
    const timer = window.setInterval(() => void refreshCatalog(), MARKET_CATALOG_AUTO_REFRESH_MS);
    const resume = () => {
      if (!document.hidden) void refreshCatalog();
      else if (requestRef.current) {
        requestRef.current.controller.abort(); requestRef.current = null;
        retryAt.current = 0;
      }
    };
    document.addEventListener('visibilitychange', resume);
    return () => {
      window.clearInterval(timer); document.removeEventListener('visibilitychange', resume);
      requestRef.current?.controller.abort(); requestRef.current = null;
    };
  }, [enabled, refreshCatalog]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; requestRef.current?.controller.abort(); requestRef.current = null; };
  }, []);
  return { markets, marketGroups, marketCatalogRefreshing, marketCatalogError, catalogLoaded };
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
