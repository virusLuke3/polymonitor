import { useEffect, useRef, useState } from 'preact/hooks';
import { fetchNaturalHazards } from '@/services/api';
import type { HazardEvent, HazardMapResponse } from '../domain/types';
import type { WorldEventSourceStatus } from './sourceStatus';
import {
  sourceStatusesAfterHazardRefreshFailure,
  sourceStatusesFromHazardResponse,
} from './sourceStatus';
import { parseNaturalHazardsResponse } from './naturalHazards';

const REFRESH_INTERVAL_MS = 60_000;
const RETRY_DELAYS_MS = [5_000, 10_000, 20_000] as const;

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
    let timer: number | null = null;
    let consecutiveFailures = 0;

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
        consecutiveFailures = 0;
      } catch (error) {
        if (disposed || requestId !== requestIdRef.current || controller.signal.aborted) return;
        consecutiveFailures += 1;
        const message = error instanceof Error ? error.message : String(error);
        setState((current) => ({
          ...current,
          sources: sourceStatusesAfterHazardRefreshFailure(
            current.sources,
            message,
            Boolean(current.response),
          ),
          loading: false,
          error: message,
        }));
      } finally {
        if (disposed) return;
        const retryDelay = RETRY_DELAYS_MS[Math.min(
          Math.max(0, consecutiveFailures - 1),
          RETRY_DELAYS_MS.length - 1,
        )] ?? 20_000;
        const baseDelay = consecutiveFailures > 0 && consecutiveFailures <= RETRY_DELAYS_MS.length
          ? retryDelay
          : REFRESH_INTERVAL_MS;
        const jitter = consecutiveFailures > 0 ? Math.floor(Math.random() * 1_000) : 0;
        timer = window.setTimeout(() => void load(), baseDelay + jitter);
      }
    };

    void load();
    return () => {
      disposed = true;
      requestIdRef.current += 1;
      controller?.abort();
      if (timer != null) window.clearTimeout(timer);
    };
  }, []);

  return state;
}
