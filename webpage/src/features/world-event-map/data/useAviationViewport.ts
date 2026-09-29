import { useEffect, useMemo, useRef, useState } from 'preact/hooks';
import { fetchAviationViewport } from '@/services/api';
import type { AviationViewportPayload } from '@/types';

const CACHE_TTL_MS = 30_000;
const viewportCache = new Map<string, { storedAt: number; payload: AviationViewportPayload }>();

function viewportForCamera(center: [number, number], zoom: number): [number, number, number, number] | null {
  if (zoom < 2) return null;
  const width = Math.max(4, 360 / (2 ** zoom) * 1.65);
  const height = Math.max(3, width * 0.58);
  const threshold = Math.max(0.5, width * 0.18);
  const lon = Math.round(center[0] / threshold) * threshold;
  const lat = Math.round(center[1] / threshold) * threshold;
  const west = Math.max(-180, lon - width / 2);
  const east = Math.min(180, lon + width / 2);
  const south = Math.max(-85, lat - height / 2);
  const north = Math.min(85, lat + height / 2);
  if (west >= east || south >= north) return null;
  return [west, south, east, north].map((value) => Number(value.toFixed(3))) as [number, number, number, number];
}

export function useAviationViewport(
  enabled: boolean,
  center: [number, number],
  zoom: number,
) {
  const bbox = useMemo(() => viewportForCamera(center, zoom), [center[0], center[1], zoom]);
  const key = bbox ? `${Math.floor(zoom)}:${bbox.join(',')}` : '';
  const [payload, setPayload] = useState<AviationViewportPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const generationRef = useRef(0);

  useEffect(() => {
    const generation = ++generationRef.current;
    if (!enabled || !bbox) {
      setPayload(null);
      setError(null);
      return undefined;
    }
    const cached = viewportCache.get(key);
    setPayload(cached?.payload ?? null);
    setError(null);
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let disposed = false;
    const refresh = async () => {
      if (disposed || document.hidden) return;
      const request = new AbortController();
      controller = request;
      try {
        const next = await fetchAviationViewport(bbox, zoom, request.signal);
        if (disposed || request.signal.aborted || generation !== generationRef.current) return;
        viewportCache.delete(key);
        viewportCache.set(key, { storedAt: Date.now(), payload: next });
        while (viewportCache.size > 16) viewportCache.delete(viewportCache.keys().next().value!);
        setPayload(next);
        setError(null);
      } catch (reason) {
        if (disposed || request.signal.aborted || generation !== generationRef.current) return;
        setError(reason instanceof Error ? reason.message : String(reason));
      } finally {
        if (!disposed && !request.signal.aborted && !document.hidden) timer = setTimeout(refresh, CACHE_TTL_MS);
      }
    };
    const visibilityChanged = () => {
      clearTimeout(timer);
      controller?.abort();
      if (!document.hidden) void refresh();
    };
    document.addEventListener('visibilitychange', visibilityChanged);
    const remaining = cached ? CACHE_TTL_MS - (Date.now() - cached.storedAt) : 0;
    if (!document.hidden && remaining > 0) timer = setTimeout(refresh, remaining);
    else void refresh();
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', visibilityChanged);
    };
  }, [enabled, key]);

  return { payload, error, bbox, loading: enabled && Boolean(bbox) && !payload && !error };
}
