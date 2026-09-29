import { useCallback, useEffect, useRef, useState } from 'preact/hooks';
import { fetchMarketLobByToken, fetchWorkspaceBundle } from '@/services/api';
import type { MessageKey } from '@/services/i18n';
import type { WorkspaceBundle } from '@/types';
import { bundleMatchesMarket, selectedWorkspaceOutcome } from './marketBundle';
import { lobMatchesTokens, staleLob } from './orderBook';

type Translator = (key: MessageKey, params?: Record<string, string | number>) => string;
const REFRESH_INTERVAL_MS = 30_000;

/** The independent market page owns its dossier and follow-up book as one request. */
export function useMarketDossier(marketId: number | null, t: Translator) {
  const [bundle, setBundle] = useState<WorkspaceBundle | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<number | null>(null);
  const currentMarket = useRef(marketId);
  currentMarket.current = marketId;
  const mounted = useRef(true);
  const request = useRef<{ controller: AbortController; promise: Promise<void> } | null>(null);
  const cancel = useCallback(() => {
    request.current?.controller.abort();
    request.current = null;
  }, []);

  const refresh = useCallback((): Promise<void> => {
    if (!mounted.current || document.hidden) return Promise.resolve();
    if (!marketId) {
      setError(t('market.invalidUrlDetail')); setLoading(false);
      return Promise.resolve();
    }
    if (request.current) return request.current.promise;
    const controller = new AbortController();
    const isCurrent = () => mounted.current && !controller.signal.aborted
      && request.current?.controller === controller && currentMarket.current === marketId;
    setLoading(true);
    const promise = (async () => {
      const next = await fetchWorkspaceBundle(marketId, { includeContent: true, includeLob: true, signal: controller.signal });
      if (!isCurrent()) return;
      if (!next.market || !bundleMatchesMarket(next, marketId)) throw new Error(t('market.noIdentity', { id: marketId }));
      const outcome = selectedWorkspaceOutcome(next);
      const tokenId = String(outcome?.yesTokenId || next.identity?.yesTokenId || next.market.yesTokenId || '').trim();
      const noTokenId = String(outcome?.noTokenId || next.identity?.noTokenId || next.market.noTokenId || '').trim();
      if (tokenId) {
        try {
          const lob = await fetchMarketLobByToken(tokenId, outcome?.label || next.market.title || '', noTokenId, 3500, controller.signal, marketId);
          if (!isCurrent()) return;
          if (!lobMatchesTokens(lob, tokenId, noTokenId)) throw new Error('LOB token mismatch');
          next.lob = lob;
        } catch {
          if (!isCurrent()) return;
          // A failed refresh cannot promote a retained book to live or retain another token.
          next.lob = lobMatchesTokens(next.lob, tokenId, noTokenId) ? staleLob(next.lob) : null;
        }
      }
      if (!isCurrent()) return;
      setBundle(next); setError(null); setLastRefreshedAt(Date.now());
    })().catch((reason) => {
      if (!isCurrent()) return;
      setError(reason instanceof Error ? reason.message : t('market.loadError'));
      setBundle((current) => current ? { ...current, lob: staleLob(current.lob) } : current);
    }).finally(() => {
      if (request.current?.controller !== controller) return;
      request.current = null;
      if (mounted.current) setLoading(false);
    });
    request.current = { controller, promise };
    return promise;
  }, [marketId, t]);

  useEffect(() => {
    mounted.current = true;
    setBundle(null); setError(null); setLastRefreshedAt(null);
    void refresh();
    const timer = window.setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    const visibility = () => {
      if (document.hidden) { cancel(); setLoading(false); }
      else void refresh();
    };
    document.addEventListener('visibilitychange', visibility);
    return () => {
      mounted.current = false; cancel();
      window.clearInterval(timer);
      document.removeEventListener('visibilitychange', visibility);
    };
  }, [refresh, cancel]);

  return { bundle: marketId != null && bundleMatchesMarket(bundle, marketId) ? bundle : null,
    loading, error, setError, lastRefreshedAt, refresh };
}
