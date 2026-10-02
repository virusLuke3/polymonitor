import { withRuntimeRequestBudget } from '@/services/api';
import { useCallback, useEffect, useRef, useState } from 'preact/hooks';

export type RadarFrame = { time: number; tiles: string; coverageTiles: string };
export type WeatherRadar = { frame: RadarFrame | null; status: 'off' | 'loading' | 'ready' | 'stale' | 'error'; error?: string };
import { WEATHER_RADAR_ENABLED } from '../config/layerRegistry';
const MANIFEST = 'https://api.rainviewer.com/public/weather-maps.json';
const REFRESH_MS = 300_000;

/** Three prompt retries, then the normal poll. Never hammer blocked sources. */
export function radarRetryDelay(failures: number, status = 0, retryAfterMs = 0) {
  const delay = status === 401 || status === 403 ? REFRESH_MS
    : [5_000, 15_000, 45_000][failures - 1] ?? REFRESH_MS;
  return Math.max(delay, retryAfterMs);
}

/** The public product currently supplies past radar only, native zoom <= 7. */
export function latestRadarFrame(payload: unknown, now = Date.now()): RadarFrame {
  const data = payload as { host?: unknown; radar?: { past?: unknown } } | null;
  if (data?.host !== 'https://tilecache.rainviewer.com' || !Array.isArray(data.radar?.past)) {
    throw new Error('Invalid RainViewer manifest or tile host');
  }
  const frames = data.radar.past.filter((frame): frame is { time: number; path: string } => (
    frame != null && typeof frame.time === 'number' && Number.isInteger(frame.time)
    && frame.time > 0 && frame.time * 1000 <= now
    && typeof frame.path === 'string' && /^\/v2\/radar\/[a-zA-Z0-9_-]+$/.test(frame.path)
  )).sort((a, b) => b.time - a.time);
  const latest = frames[0];
  if (!latest) throw new Error('No valid past radar frame');
  if (now - latest.time * 1000 > 30 * 60_000) throw new Error('Radar frame exceeds the 30 minute retention budget');
  return {
    time: latest.time,
    tiles: `${data.host}${latest.path}/256/{z}/{x}/{y}/2/1_1.png`,
    coverageTiles: `${data.host}/v2/coverage/0/256/{z}/{x}/{y}/0/0_0.png`,
  };
}

/** One bounded manifest poll, owned by actual map demand. Tiles stay MapLibre-owned. */
export function useWeatherRadar(enabled: boolean) {
  const [state, setState] = useState<WeatherRadar>({ frame: null, status: 'off' });
  const blockedUntil = useRef(0);
  const [attempt, setAttempt] = useState(0);
  const retry = useCallback(() => setAttempt(value => value + 1), []);
  useEffect(() => {
    if (!enabled || !WEATHER_RADAR_ENABLED) {
      setState({ frame: null, status: 'off' });
      return;
    }
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let expiryTimer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    let lastFrame: RadarFrame | null = state.frame;
    let failures = 0;
    const scheduleExpiry = () => {
      clearTimeout(expiryTimer);
      if (!lastFrame) return;
      const remaining=lastFrame.time * 1000 + 30 * 60_000 - Date.now();
      const expire=()=>{ lastFrame=null; if(!disposed)setState({frame:null,status:'error',error:'Radar observation expired after 30 minutes'}); };
      if(remaining<=0)expire();else expiryTimer=setTimeout(expire,remaining);
    };
    const stop = () => { clearTimeout(timer); clearTimeout(expiryTimer); controller?.abort(); controller = null; };
    const refresh = async () => {
      if (disposed || document.hidden || navigator.onLine === false) return;
      if (blockedUntil.current > Date.now()) { timer = setTimeout(refresh, blockedUntil.current - Date.now()); return; }
      const request = new AbortController(); controller = request;
      let deadline: ReturnType<typeof setTimeout> | undefined;
      let failureDelay: number | undefined;
      setState(current => current.frame && Date.now() - current.frame.time * 1000 <= 30 * 60_000 ? current : { frame: null, status: 'loading' });
      try {
        const frame = await withRuntimeRequestBudget(async () => {
        deadline = setTimeout(() => request.abort(), 12_000);
        const response = await fetch(MANIFEST, { signal: request.signal, credentials: 'omit' });
        if (!response.ok) {
          const header = response.headers.get('Retry-After');
          const seconds = Number(header);
          const retryAfter = header ? (Number.isFinite(seconds) ? seconds * 1000 : Date.parse(header) - Date.now()) : 0;
          failureDelay = radarRetryDelay(failures + 1, response.status, Math.max(0, retryAfter || 0));
          if ([401,403,429].includes(response.status)) blockedUntil.current = Date.now() + failureDelay;
          throw new Error(`RainViewer HTTP ${response.status}`);
        }
        return latestRadarFrame(await response.json());
        }, request.signal, 1);
        if (!disposed && controller === request && !request.signal.aborted) {
          lastFrame=frame;setState({ frame, status: 'ready' });scheduleExpiry();
          failures = 0;
        }
      } catch (error) {
        failures += 1;
        failureDelay ??= radarRetryDelay(failures);
        if (!disposed && controller === request && !document.hidden) {
          setState(current => {
            const retained = current.frame && Date.now() - current.frame.time * 1000 <= 30 * 60_000 ? current.frame : null;
            return {frame: retained, status: retained ? 'stale' : 'error', error: String(error)};
          });
        }
      } finally {
        clearTimeout(deadline);
        if (!disposed && controller === request && !document.hidden) timer = setTimeout(refresh, failureDelay ?? REFRESH_MS);
      }
    };
    const visibility = () => { stop(); if (!document.hidden) { scheduleExpiry(); void refresh(); } };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('online', visibility);window.addEventListener('offline', visibility);
    scheduleExpiry();
    void refresh();
    return () => { disposed = true; stop(); document.removeEventListener('visibilitychange', visibility);window.removeEventListener('online', visibility);window.removeEventListener('offline', visibility); };
  }, [enabled, attempt]);
  return { ...state, retry };
}
