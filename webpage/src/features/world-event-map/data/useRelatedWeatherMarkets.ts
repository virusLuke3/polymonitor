import { useEffect, useRef, useState } from 'preact/hooks';
import { fetchNaturalHazardRelatedMarkets, isAbortLikeError } from '@/services/api';
import type { HazardMarketLinksResponse } from '../domain/types';
import { parseRelatedWeatherMarkets } from './relatedMarkets';

export type RelatedWeatherMarketsState = {
  response: HazardMarketLinksResponse | null;
  loading: boolean;
  error: string | null;
};

export function useRelatedWeatherMarkets(eventId: string | null): RelatedWeatherMarketsState {
  const [state, setState] = useState<RelatedWeatherMarketsState>({
    response: null,
    loading: false,
    error: null,
  });
  const requestIdRef = useRef(0);

  useEffect(() => {
    const requestId = ++requestIdRef.current;
    if (!eventId) {
      setState({ response: null, loading: false, error: null });
      return undefined;
    }
    const controller = new AbortController();
    setState({ response: null, loading: true, error: null });
    void fetchNaturalHazardRelatedMarkets(eventId, controller.signal)
      .then(parseRelatedWeatherMarkets)
      .then((response) => {
        if (requestId !== requestIdRef.current) return;
        setState({ response, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (requestId !== requestIdRef.current || isAbortLikeError(error)) return;
        setState({
          response: null,
          loading: false,
          error: error instanceof Error ? error.message : String(error),
        });
      });
    return () => {
      requestIdRef.current += 1;
      controller.abort();
    };
  }, [eventId]);

  return state;
}

