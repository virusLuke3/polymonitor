import { type RuntimeMarketTvWireItem } from '@/types';
import { useEffect, useState } from 'preact/hooks';

export function useStaggeredLoad(enabled: boolean, delayMs = 0) {
  const [ready, setReady] = useState(delayMs <= 0);

  useEffect(() => {
    if (!enabled) {
      setReady(false);
      return undefined;
    }
    if (delayMs <= 0) {
      setReady(true);
      return undefined;
    }
    const timer = window.setTimeout(() => setReady(true), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, enabled]);

  return enabled && ready;
}

export function youtubeBridgeMessageMatches(event: MessageEvent, iframe: HTMLIFrameElement | null, videoId: string) {
  if (!iframe || event.source !== iframe.contentWindow) return false;
  const payload = event.data as { type?: string; videoId?: string } | null;
  if (!payload || typeof payload !== 'object') return false;
  if (!String(payload.type || '').startsWith('yt-')) return false;
  return !payload.videoId || payload.videoId === videoId;
}

const YOUTUBE_VIDEO_ID_RE = /^[A-Za-z0-9_-]{11}$/;

export function youtubeVideoId(item?: RuntimeMarketTvWireItem | null) {
  const liveId = String(item?.youtubeLiveVideoId || '').trim();
  if (YOUTUBE_VIDEO_ID_RE.test(liveId)) return liveId;
  const fallbackId = String(item?.fallbackVideoId || '').trim();
  return YOUTUBE_VIDEO_ID_RE.test(fallbackId) ? fallbackId : '';
}

export function panelStatus(payload?: { status?: string | null } | null): 'live' | 'muted' {
  const status = String(payload?.status || '').toLowerCase();
  return status === 'warming' || status === 'empty' ? 'muted' : 'live';
}

export function categoryToneClass(value?: string | null) {
  const category = String(value || 'all').toLowerCase().replace(/[^a-z0-9-]/g, '');
  return `tone-${category || 'all'}`;
}

export function sourceLocation(item: RuntimeMarketTvWireItem) {
  return [item.region, item.country, item.language].filter(Boolean).join(' / ') || 'GLOBAL';
}

export function categoryLabel(value?: string | null) {
  return String(value || 'other').toUpperCase();
}
