import { useEffect, useState } from 'preact/hooks';

export type RadarFrame = { time: number; tiles: string; coverageTiles: string };
export type WeatherRadar = { frame: RadarFrame | null; status: 'off' | 'loading' | 'ready' | 'stale' | 'error'; error?: string };
import { WEATHER_RADAR_ENABLED } from '../config/layerRegistry';
const MANIFEST = 'https://api.rainviewer.com/public/weather-maps.json';
const REFRESH_MS = 300_000;

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
  return {
    time: latest.time,
    tiles: `${data.host}${latest.path}/256/{z}/{x}/{y}/2/1_1.png`,
    coverageTiles: `${data.host}/v2/coverage/0/256/{z}/{x}/{y}/0/0_0.png`,
  };
}

/** One bounded manifest poll, owned by actual map demand. Tiles stay MapLibre-owned. */
export function useWeatherRadar(enabled: boolean) {
  const [state, setState] = useState<WeatherRadar>({ frame: null, status: 'off' });
  useEffect(() => {
    if (!enabled || !WEATHER_RADAR_ENABLED) {
      setState(current => ({ ...current, status: 'off' }));
      return;
    }
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    const stop = () => { clearTimeout(timer); controller?.abort(); controller = null; };
    const refresh = async () => {
      if (disposed || document.hidden) return;
      const request = new AbortController(); controller = request;
      const deadline = setTimeout(() => request.abort(), 12_000);
      setState(current => current.frame ? current : { frame: null, status: 'loading' });
      try {
        const response = await fetch(MANIFEST, { signal: request.signal, credentials: 'omit' });
        if (!response.ok) throw new Error(`RainViewer HTTP ${response.status}`);
        const frame = latestRadarFrame(await response.json());
        if (!disposed && controller === request && !request.signal.aborted) {
          setState({ frame, status: Date.now() - frame.time * 1000 > 30 * 60_000 ? 'stale' : 'ready' });
        }
      } catch (error) {
        if (!disposed && controller === request && !document.hidden) {
          setState(current => ({ ...current, status: current.frame ? 'stale' : 'error', error: String(error) }));
        }
      } finally {
        clearTimeout(deadline);
        if (!disposed && controller === request && !document.hidden) timer = setTimeout(refresh, REFRESH_MS);
      }
    };
    const visibility = () => { stop(); if (!document.hidden) void refresh(); };
    document.addEventListener('visibilitychange', visibility);
    void refresh();
    return () => { disposed = true; stop(); document.removeEventListener('visibilitychange', visibility); };
  }, [enabled]);
  return state;
}
