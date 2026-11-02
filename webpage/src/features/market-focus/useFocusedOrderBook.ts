import { useEffect, useRef, useState } from 'preact/hooks';
import { ApiHttpError, fetchMarketLobByToken } from '@/services/api';
import type { LobPayload } from '@/types';
import {
  bookMidValue,
  directionFromValues,
  lobMatchesTokens,
  staleLob,
  timestampMillis,
  hasBookLevels,
  type BookSide,
  type RefreshDirection,
} from './orderBook';
const LOB_REFRESH_INTERVAL_MS = 2_000;
type TokenLobState = {
  key: string;
  lob: LobPayload | null;
  loading: boolean;
  error: string | null;
  updatedAt: number | null;
  pulseId: number;
  direction: RefreshDirection;
};
export function useFocusedOrderBook({ marketId, selectedTokenId, selectedNoTokenId, marketIsClosed, bookSide, bundledLob, outcomeLabel, groupTitle }: {
  marketId: number | null; selectedTokenId: string; selectedNoTokenId: string; marketIsClosed: boolean;
  bookSide: BookSide; bundledLob: LobPayload | null; outcomeLabel?: string | null; groupTitle?: string | null;
}) {
  const selectedTokenKey = selectedTokenId ? String(marketId) + ':' + selectedTokenId + ':' + selectedNoTokenId : '';
  const hasBundledBookLevels = hasBookLevels(bundledLob);
  const [refreshClock, setRefreshClock] = useState(0);
  const tokenLobRequestRef = useRef(0);
  const [tokenLobState, setTokenLobState] = useState<TokenLobState>({
    key: '',
    lob: null,
    loading: false,
    error: null,
    updatedAt: null,
    pulseId: 0,
    direction: 'flat',
  });
  void refreshClock;

  useEffect(() => {
    if (marketIsClosed || !selectedTokenId) {
      setTokenLobState((current) => (
        current.loading || current.lob
          ? { key: '', lob: null, loading: false, error: null, updatedAt: null, pulseId: 0, direction: 'flat' }
          : current
      ));
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    let controller: AbortController | null = null;
    let failures = 0;
    let retryAfterMs = 0;
    const key = selectedTokenKey;
    const title = outcomeLabel || groupTitle || '';
    const matchingSeed = lobMatchesTokens(bundledLob, selectedTokenId, selectedNoTokenId) ? bundledLob : null;

    if (matchingSeed) {
      setTokenLobState((current) => ({
        key,
        lob: matchingSeed,
        loading: false,
        error: null,
        updatedAt: timestampMillis(matchingSeed.yes?.receivedAt),
        pulseId: current.key === key ? current.pulseId : current.pulseId + 1,
        direction: current.key === key ? current.direction : 'flat',
      }));
    }

    const loadBook = () => {
      if (cancelled || document.hidden || controller) return;
      const currentController = new AbortController();
      controller = currentController;
      const requestSeq = ++tokenLobRequestRef.current;
      setTokenLobState((current) => ({
        key,
        lob: current.key === key ? current.lob : null,
        loading: true,
        error: current.key === key ? current.error : null,
        updatedAt: current.key === key ? current.updatedAt : null,
        pulseId: current.key === key ? current.pulseId : 0,
        direction: current.key === key ? current.direction : 'flat',
      }));
      fetchMarketLobByToken(selectedTokenId, title, selectedNoTokenId, 3000, currentController.signal, marketId)
        .then((lobPayload) => {
          if (cancelled || currentController.signal.aborted || requestSeq !== tokenLobRequestRef.current) return;
          if (!lobMatchesTokens(lobPayload, selectedTokenId, selectedNoTokenId)) throw new Error('LOB token mismatch');
          if (lobPayload.bookStatus === 'unavailable') throw new Error('Order book source unavailable. Retrying with backoff.');
          failures = 0;
          retryAfterMs = 0;
          setTokenLobState((current) => {
            const previousMid = current.key === key ? bookMidValue(current.lob, bookSide) : null;
            const nextMid = bookMidValue(lobPayload, bookSide);
            return {
              key,
              lob: lobPayload,
              loading: false,
              error: null,
              updatedAt: timestampMillis(lobPayload.yes?.receivedAt),
              pulseId: (current.key === key ? current.pulseId : 0) + 1,
              direction: directionFromValues(nextMid, previousMid),
            };
          });
        })
        .catch((error: unknown) => {
          if (!cancelled && !currentController.signal.aborted && requestSeq === tokenLobRequestRef.current) {
            failures = Math.min(failures + 1, 5);
            retryAfterMs = error instanceof ApiHttpError ? error.retryAfterMs || 0 : 0;
            setTokenLobState((current) => ({
              key,
              lob: current.key === key ? staleLob(current.lob) : null,
              loading: false,
              error: 'Order book source unavailable. Retrying with backoff.',
              updatedAt: current.key === key ? current.updatedAt : null,
              pulseId: current.key === key ? current.pulseId : 0,
              direction: current.key === key ? current.direction : 'flat',
            }));
          }
        })
        .finally(() => {
          if (controller === currentController) controller = null;
          if (!cancelled && !document.hidden && requestSeq === tokenLobRequestRef.current) {
            timer = window.setTimeout(loadBook, Math.max(retryAfterMs, Math.min(60_000, LOB_REFRESH_INTERVAL_MS * 2 ** failures)) + Math.random() * 500);
          }
        });
    };

    const onVisibility = () => {
      if (timer !== undefined) window.clearTimeout(timer);
      if (document.hidden) {
        tokenLobRequestRef.current += 1;
        controller?.abort(); controller = null;
        setTokenLobState((current) => current.key === key ? { ...current, loading: false } : current);
      } else loadBook();
    };
    document.addEventListener('visibilitychange', onVisibility);
    timer = window.setTimeout(loadBook, 100);
    return () => {
      cancelled = true;
      controller?.abort();
      document.removeEventListener('visibilitychange', onVisibility);
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [marketId, bookSide, groupTitle, hasBundledBookLevels, marketIsClosed, selectedNoTokenId, outcomeLabel, selectedTokenId, selectedTokenKey]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      setRefreshClock((value) => value + 1);
    }, 2000);
    return () => {
      window.clearInterval(interval);
    };
  }, []);


  return { tokenLobState, selectedTokenKey };
}
