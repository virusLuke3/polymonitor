import type { RuntimeMarketTvWireItem, TvPlaybackSource } from '@/types';

export const START_TIMEOUT_MS = 20_000;
export const STALL_TIMEOUT_MS = 30_000;

// Source teardown may reject a pending play with AbortError. It is neither a
// user pause nor autoplay denial; leave the existing watchdog able to recover.
export async function requestPlayback(
  video: Pick<HTMLMediaElement, 'play'>,
  active: () => boolean,
  blocked: () => void,
  failed: () => void,
): Promise<void> {
  if (!active()) return;
  try { await video.play(); }
  catch (error) {
    if (!active()) return;
    const name = error && typeof error === 'object' && 'name' in error ? error.name : '';
    if (name === 'NotAllowedError') blocked();
    else if (name !== 'AbortError') failed();
  }
}

export function observedPlaybackState(confirmed: boolean, moving: boolean, playing: boolean, paused: boolean): string {
  if (paused) return 'paused';
  if (confirmed && playing && moving) return 'playing';
  return confirmed ? 'waiting' : 'connecting';
}

export function playbackCandidates(item: RuntimeMarketTvWireItem): TvPlaybackSource[] {
  const inputs = item.playbackSources ?? [
    ...(item.hlsUrl ? [{ kind: 'hls' as const, url: item.hlsUrl, proxy: !!item.hlsProxyRequired, proxyFallback: item.playbackTier === 'trusted-hls' }] : []),
    ...(item.fallbackVideoId ? [{ kind: 'youtube' as const, videoId: item.fallbackVideoId }] : []),
  ];
  const output: TvPlaybackSource[] = [];
  const seen = new Set<string>();
  for (const source of inputs.slice(0, 6)) {
    if (!source || typeof source !== 'object') continue;
    const valid = source.kind === 'hls' ? /^https:\/\//.test(source.url || '')
      : source.kind === 'youtube' ? /^[\w-]{11}$/.test(source.videoId || '')
        : source.kind === 'youtube-channel' && /^UC[\w-]{22}$/.test(source.channelId || '');
    if (!valid) continue;
    const key = `${source.kind}:${source.url || source.videoId || source.channelId}`;
    if (seen.has(key)) continue;
    seen.add(key);
    output.push(source);
    if (source.kind === 'hls' && !source.proxy && source.proxyFallback) output.push({ ...source, proxy: true });
  }
  return output;
}

// A live-edge seek or a buffering notification is not evidence of playback.
export function advancing(previous: { time: number; at: number } | null, time: number, at: number, playing: boolean): boolean {
  if (!previous || !playing || !Number.isFinite(time)) return false;
  const delta = time - previous.time;
  return delta > 0 && delta <= (at - previous.at) / 1000 + 0.25;
}

export function youtubeVerdict(data: { state?: number; isLive?: boolean; time?: number }, progressed: boolean): 'live' | 'recording' | 'waiting' {
  if (data.state === 0 || (data.state === 1 && data.isLive === false)) return 'recording';
  return data.state === 1 && data.isLive === true && progressed ? 'live' : 'waiting';
}
