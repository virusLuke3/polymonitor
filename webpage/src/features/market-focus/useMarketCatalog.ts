import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { fetchMarketsPage, fetchMarketSearch } from '@/services/api';
import type { BootstrapPayload, MarketListItem, MarketGroupItem, MarketGroupSort } from '@/types';

/** One owner for the active catalog; manual refresh joins the current request. */
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
  const failures = useRef(0);
  const refreshMarketCatalog = useCallback((manual = true): Promise<void> => {
    if (requestRef.current) return requestRef.current.promise;
    if (document.hidden && !manual) return Promise.resolve();
    if (Date.now() < retryAt.current) return Promise.resolve();
    const controller = new AbortController();
    if (manual) { setRefreshing(true); setError(null); }
    const isCurrent = () => !controller.signal.aborted && mounted.current;
    const errors: string[] = [];
    const promise = Promise.allSettled([
      fetchMarketsPage(1, '', 50, controller.signal, sort).then((catalog) => {
        if (!isCurrent()) return;
        hydrated.current.markets = true;
        setMarkets((catalog.items || []).map((item) => ({ ...item, catalogFetchedAt: catalog.generatedAt }))); setMarketGroups([]); setLoaded(true);
        if (catalog.status === 'stale' && catalog.refreshStatus !== 'refreshing') errors.push('Catalog refresh failed; showing the last stored page.');
      }).catch((error) => {
        if (isCurrent()) errors.push(error instanceof Error ? error.message : 'Market catalog refresh failed.');
      }),
    ]).then(() => {
      if (isCurrent()) {
        setLoaded(true); setError(errors[0] || null);
        failures.current = errors.length ? Math.min(3, failures.current + 1) : 0;
        retryAt.current = Date.now() + (errors.length ? 30_000 * 2 ** failures.current : 0);
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
    retryAt.current = 0; failures.current = 0;
    setMarkets([]); setLoaded(false); setError(null);
    void refreshMarketCatalog(false);
    const timer = window.setInterval(() => void refreshMarketCatalog(false), 45_000);
    const resume = () => {
      if (!document.hidden) void refreshMarketCatalog(false);
      else { requestRef.current?.controller.abort(); requestRef.current = null; }
    };
    document.addEventListener('visibilitychange', resume);
    return () => {
      window.clearInterval(timer); document.removeEventListener('visibilitychange', resume);
      requestRef.current?.controller.abort(); requestRef.current = null;
    };
  }, [enabled, refreshMarketCatalog]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; requestRef.current?.controller.abort(); requestRef.current = null; };
  }, []);
  return { markets, marketGroups, marketCatalogRefreshing, marketCatalogError, refreshMarketCatalog, catalogLoaded };
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
