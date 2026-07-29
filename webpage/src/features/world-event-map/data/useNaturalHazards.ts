import { useEffect, useRef, useState } from 'preact/hooks';
import { fetchNaturalHazards, isAbortLikeError } from '@/services/api';
import type { HazardEvent, HazardMapResponse } from '../domain/types';
import type { WorldEventSourceStatus } from './sourceStatus';
import { sourceStatusesFromHazardResponse } from './sourceStatus';
import { parseNaturalHazardsResponse } from './naturalHazards';

const REFRESH_INTERVAL_MS = 60_000;

export type NaturalHazardsState = {
  events: HazardEvent[];
  response: HazardMapResponse | null;
  sources: WorldEventSourceStatus[];
  loading: boolean;
  error: string | null;
  rejectedCount: number;
};

export function useNaturalHazards(): NaturalHazardsState {
  const [state, setState] = useState<NaturalHazardsState>({
    events: [],
    response: null,
    sources: sourceStatusesFromHazardResponse(null, 0, true),
    loading: true,
    error: null,
    rejectedCount: 0,
  });
  const requestIdRef = useRef(0);

  useEffect(() => {
    let disposed = false;
    let controller: AbortController | null = null;

    const load = async () => {
      controller?.abort();
      controller = new AbortController();
      const requestId = ++requestIdRef.current;
      try {
        const payload = await fetchNaturalHazards(controller.signal);
        const parsed = parseNaturalHazardsResponse(payload);
        if (disposed || requestId !== requestIdRef.current) return;
        setState({
          events: parsed.events,
          response: parsed.response,
          sources: sourceStatusesFromHazardResponse(parsed.response, parsed.rejected.length),
          loading: false,
          error: null,
          rejectedCount: parsed.rejected.length,
        });
      } catch (error) {
        if (disposed || requestId !== requestIdRef.current || isAbortLikeError(error)) return;
        const message = error instanceof Error ? error.message : String(error);
        setState((current) => ({
          ...current,
          sources: current.response
            ? current.sources.map((source) => ({
                ...source,
                status: source.status === 'error' ? 'error' : 'degraded',
                message: `${source.message ? `${source.message} · ` : ''}Refresh failed; retaining the last successful snapshot`,
              }))
            : [],
          loading: false,
          error: message,
        }));
      }
    };

    void load();
    const timer = window.setInterval(() => void load(), REFRESH_INTERVAL_MS);
    return () => {
      disposed = true;
      requestIdRef.current += 1;
      controller?.abort();
      window.clearInterval(timer);
    };
  }, []);

  return state;
}
