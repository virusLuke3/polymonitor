import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { fetchAllActiveMarkets, fetchMarketGroups, fetchMarketSearch } from '@/services/api';
import type { BootstrapPayload, MarketListItem, MarketGroupItem } from '@/types';

/** One owner for the active catalog; manual refresh joins the current request. */
export function useMarketCatalog(bootstrap: BootstrapPayload | null, enabled: boolean) {
  const [markets, setMarkets] = useState<MarketListItem[]>([]);
  const [marketGroups, setMarketGroups] = useState<MarketGroupItem[]>([]);
  const [marketCatalogRefreshing, setRefreshing] = useState(false);
  const [marketCatalogError, setError] = useState<string | null>(null);
  const [catalogLoaded, setLoaded] = useState(false);
  const requestRef = useRef<{ controller: AbortController; promise: Promise<void> } | null>(null);
  const mounted = useRef(true);
  const hydrated = useRef({ markets: false, groups: false });
  const refreshMarketCatalog = useCallback((manual = true): Promise<void> => {
    if (requestRef.current) return requestRef.current.promise;
    if (document.hidden && !manual) return Promise.resolve();
    const controller = new AbortController();
    if (manual) { setRefreshing(true); setError(null); }
    const isCurrent = () => !controller.signal.aborted && mounted.current;
    const promise = Promise.allSettled([
      fetchMarketGroups('', 80, 'active', controller.signal).then((groups) => {
        if (!isCurrent()) return;
        hydrated.current.groups = true;
        setMarketGroups(groups.items || []); setError(null);
        if (groups.items?.length) setLoaded(true);
      }).catch((error) => {
        if (isCurrent()) setError(error instanceof Error ? error.message : 'Market catalog refresh failed.');
      }),
      fetchAllActiveMarkets('', 80, 8, controller.signal, (firstPage) => {
        if (!isCurrent() || hydrated.current.markets) return;
        // Make the initial page usable while the bounded remainder loads. A
        // refresh keeps the complete previous catalog until its replacement.
        hydrated.current.markets = true;
        setMarkets(firstPage.items || []); setLoaded(true);
      }).then((catalog) => {
        if (!isCurrent()) return;
        hydrated.current.markets = true;
        setMarkets(catalog.items || []); setLoaded(true);
      }).catch((error) => {
        if (isCurrent()) setError(error instanceof Error ? error.message : 'Market catalog refresh failed.');
      }),
    ]).then(() => {
      if (isCurrent()) setLoaded(true);
    }).finally(() => {
      if (requestRef.current?.controller === controller) requestRef.current = null;
      if (mounted.current && !controller.signal.aborted) setRefreshing(false);
    });
    requestRef.current = { controller, promise };
    return promise;
  }, []);
  useEffect(() => {
    if (!bootstrap) return;
    if (!hydrated.current.markets) setMarkets(bootstrap.activeMarketsPreview || []);
    if (!hydrated.current.groups) setMarketGroups(bootstrap.activeMarketGroupsPreview || []);
  }, [bootstrap]);
  useEffect(() => {
    if (!enabled) return;
    void refreshMarketCatalog(false);
    const timer = window.setInterval(() => void refreshMarketCatalog(false), 20_000);
    const resume = () => {
      if (!document.hidden) void refreshMarketCatalog(false);
      else { requestRef.current?.controller.abort(); requestRef.current = null; }
    };
    document.addEventListener('visibilitychange', resume);
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', resume); };
  }, [enabled, refreshMarketCatalog]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; requestRef.current?.controller.abort(); requestRef.current = null; };
  }, []);
  return { markets, marketGroups, marketCatalogRefreshing, marketCatalogError, refreshMarketCatalog, catalogLoaded };
}

/** Command search has a separate query identity and no periodic refresh. */
export function useMarketSearch(query: string, enabled: boolean) {
  const [hits, setHits] = useState<MarketListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setHits([]); setLoading(false); setUnavailable(false);
    if (!enabled || !query.trim()) return;
    const timer = window.setTimeout(() => {
      setLoading(true);
      void fetchMarketSearch(query.trim(), 50, controller.signal).then((payload) => {
        if (!controller.signal.aborted) setHits(payload.items || []);
      }).catch(() => {
        if (!controller.signal.aborted) setUnavailable(true);
      }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 180);
    return () => { controller.abort(); window.clearTimeout(timer); };
  }, [query, enabled]);
  return { hits, loading, unavailable };
}
