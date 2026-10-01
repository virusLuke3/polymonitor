import { useEffect, useRef, useState } from 'preact/hooks';
import type { ContentPayload } from '@/types';
import { fetchLatestContent, fetchMarketContent } from '@/services/api';

export function validScope(payload: ContentPayload, marketId: number | null, scope: 'market' | 'global') {
  return payload.scope === scope && (scope === 'global' || payload.marketId === marketId);
}
export function fingerprint(payload: ContentPayload) {
  return payload.items.map((item) => `${item.id}:${item.content_version}`).join('|');
}
export function useIntelFeed(marketId: number | null, scope: 'market' | 'global', days: number) {
  const key = `${scope}:${scope === 'market' ? marketId : 'all'}:${days}`;
  const [state, setState] = useState<{ key: string; data: ContentPayload | null; pending: ContentPayload | null; error: string | null }>({ key, data: null, pending: null, error: null });
  const sequence = useRef(0);
  useEffect(() => {
    const generation = ++sequence.current;
    let controller: AbortController | null = null;
    let cancelled = false;
    setState({ key, data: null, pending: null, error: null });
    const refresh = async () => {
      if (controller || document.hidden || (scope === 'market' && marketId == null)) return;
      const request = new AbortController();
      controller = request;
      try {
        const data = scope === 'market'
          ? await fetchMarketContent(marketId!, 20, 8000, request.signal, days)
          : await fetchLatestContent(20, request.signal, days);
        if (cancelled || request.signal.aborted || generation !== sequence.current) return;
        if (!validScope(data, marketId, scope)) throw new Error('Content response scope or market identity mismatch');
        setState((old) => old.key !== key || !old.data
          ? { key, data, pending: null, error: null }
          : fingerprint(old.data) === fingerprint(data)
            ? { ...old, data, pending: null, error: null }
            : { ...old, pending: data, error: null });
      } catch (error) {
        if (!cancelled && !request.signal.aborted && generation === sequence.current) {
          setState((old) => ({ ...old, error: error instanceof Error ? error.message : String(error) }));
        }
      } finally { if (controller === request) controller = null; }
    };
    const onVisibility = () => { if (document.hidden) controller?.abort(); else void refresh(); };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    document.addEventListener('visibilitychange', onVisibility);
    return () => { cancelled = true; controller?.abort(); window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisibility); };
  }, [key, marketId, scope, days]);
  const current = state.key === key ? state : { key, data: null, pending: null, error: null };
  return { ...current, loading: !current.data && !current.error, accept: () => setState((old) => old.pending ? { ...old, data: old.pending, pending: null } : old) };
}
