import { useEffect, useRef, useState } from 'preact/hooks';
import type { RuntimeMarketTvWireItem } from '@/types';
import { buildRuntimeHlsProxyUrl, buildRuntimeYoutubeEmbedUrl } from '@/services/api';
import { useSpecialistCopy } from '@/services/specialist-i18n';
import { openExternal } from '../../shared/renderers';
import { advancing, playbackCandidates, START_TIMEOUT_MS, STALL_TIMEOUT_MS, youtubeVerdict } from './playback';

export function MarketTvPreview({ item }: { item: RuntimeMarketTvWireItem }) {
  const { shared } = useSpecialistCopy('market-tv-wire');
  const sources = playbackCandidates(item);
  const identity = JSON.stringify(sources);
  const [attempt, setAttempt] = useState(0);
  const [retry, setRetry] = useState(0);
  const [state, setState] = useState('connecting');
  const videoRef = useRef<HTMLVideoElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  const retryRounds = useRef(0);
  const source = sources[attempt];
  const title = item.displayName || item.name || 'Live TV';
  const url = source?.kind === 'hls' ? (source.proxy ? buildRuntimeHlsProxyUrl(source.url!) : source.url!)
    : source ? buildRuntimeYoutubeEmbedUrl(source.videoId || '', { autoplay: true, mute: true })
      + (source.channelId ? `&channelId=${encodeURIComponent(source.channelId)}` : '') : '';

  // Exhausted sources recover automatically with bounded backoff. Hidden pages
  // do not reopen streams, and healthy playback survives catalog refreshes.
  useEffect(() => {
    if (source || !sources.length) return;
    let timer: number;
    const retryWhenVisible = () => {
      if (document.hidden) { timer = window.setTimeout(retryWhenVisible, 60_000); return; }
      retryRounds.current += 1;
      setAttempt(0);
      setRetry((v) => v + 1);
    };
    timer = window.setTimeout(retryWhenVisible, Math.min(300_000, 60_000 * 2 ** retryRounds.current));
    return () => clearTimeout(timer);
  }, [attempt, identity]);
  useEffect(() => {
    if (state === 'playing') retryRounds.current = 0;
  }, [state]);
  useEffect(() => {
    if (!source && sources.length) setAttempt(0);
  }, [identity]);

  // A refreshed directory must not interrupt an already selected channel.
  useEffect(() => { setAttempt(0); }, [item.id]);
  useEffect(() => {
    if (!source) { setState('blocked'); return; }
    let disposed = false;
    let failed = false;
    let confirmed = false;
    let lastProgress = performance.now();
    let start = lastProgress;
    let paused = false;
    let previous: { time: number; at: number } | null = null;
    let progressSeconds = 0;
    let destroy = () => {};
    setState('connecting');
    const fail = () => {
      if (disposed || failed) return;
      failed = true;
      setAttempt((current) => current + 1);
    };
    const observe = (time: number, playing: boolean, live: boolean | undefined) => {
      const at = performance.now();
      const moves = advancing(previous, time, at, playing);
      if (moves) {
        progressSeconds += time - previous!.time;
        lastProgress = at;
      }
      previous = playing ? { time, at } : null;
      if (playing && live === false) { fail(); return; }
      if (playing && live === true && moves && progressSeconds >= 1) {
        confirmed = true;
        setState('playing');
      } else if (confirmed && !playing) setState(paused ? 'paused' : 'waiting');
    };
    const video = videoRef.current;
    let live: boolean | undefined;
    const onPause = () => { paused = true; setState('paused'); };
    const onPlay = () => { paused = false; lastProgress = performance.now(); };
    if (source.kind === 'hls' && video) {
      video.addEventListener('error', fail);
      video.addEventListener('ended', fail);
      video.addEventListener('pause', onPause);
      video.addEventListener('play', onPlay);
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        video.src = url;
        video.play().catch(() => { paused = true; setState('paused'); });
      } else {
        void import('hls.js').then(({ default: Hls }) => {
          if (disposed) return;
          if (!Hls.isSupported()) { fail(); return; }
          const player = new Hls({ enableWorker: true, lowLatencyMode: true });
          destroy = () => player.destroy();
          player.on(Hls.Events.LEVEL_LOADED, (_, data) => { live = data.details.live; if (!live) fail(); });
          player.on(Hls.Events.ERROR, (_, data) => { if (data.fatal) fail(); });
          player.on(Hls.Events.MANIFEST_PARSED, () => { video.play().catch(() => { paused = true; setState('paused'); }); });
          player.loadSource(url);
          player.attachMedia(video);
        }).catch(fail);
      }
    }
    const onMessage = (event: MessageEvent) => {
      const frame = frameRef.current;
      if (!frame || event.source !== frame.contentWindow || event.origin !== new URL(url, location.href).origin) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      if (data.type === 'yt-error') { fail(); return; }
      if (data.type === 'yt-state') {
        paused = data.state === 2;
        if (data.state === 0) fail();
      }
      if (data.type !== 'yt-progress') return;
      if (youtubeVerdict(data, false) === 'recording') { fail(); return; }
      paused = data.state === 2;
      observe(data.time, data.state === 1, data.isLive);
    };
    let resumeOnVisible = false;
    const visibility = () => {
      const frame = frameRef.current;
      if (document.hidden) {
        resumeOnVisible = !paused;
        video?.pause();
        frame?.contentWindow?.postMessage({ type: 'pause' }, new URL(url, location.href).origin);
      } else if (resumeOnVisible) {
        start = lastProgress = performance.now();
        previous = null;
        paused = false;
        void video?.play().catch(() => { paused = true; setState('paused'); });
        frame?.contentWindow?.postMessage({ type: 'play' }, new URL(url, location.href).origin);
        resumeOnVisible = false;
      }
    };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('message', onMessage);
    const timer = window.setInterval(() => {
      if (disposed || failed) return;
      const now = performance.now();
      if (document.hidden || paused) { start = now; lastProgress = now; previous = null; return; }
      if (source.kind === 'hls' && video) observe(video.currentTime, !video.paused && video.readyState >= 2, live ?? (video.duration === Infinity ? true : undefined));
      if ((!confirmed && now - start >= START_TIMEOUT_MS) || (confirmed && now - lastProgress >= STALL_TIMEOUT_MS)) fail();
    }, 1000);
    return () => {
      disposed = true;
      clearInterval(timer);
      window.removeEventListener('message', onMessage);
      document.removeEventListener('visibilitychange', visibility);
      video?.removeEventListener('error', fail);
      video?.removeEventListener('ended', fail);
      video?.removeEventListener('pause', onPause);
      video?.removeEventListener('play', onPlay);
      destroy();
      if (video) { video.pause(); video.removeAttribute('src'); video.load(); }
    };
  }, [item.id, identity, attempt, retry, url]);

  return <div className="wm-market-tv-preview" data-channel-id={item.id} data-playback-state={state} data-playback-attempt={attempt}>
    <div className="wm-market-tv-preview-head">
      <strong>{title}</strong>
      <em className={`wm-market-tv-playback ${state}`}>{state.toUpperCase()}</em>
      <button type="button" onClick={() => openExternal(item.externalUrl || item.sourceUrl)}>{shared('open', 'OPEN')}</button>
    </div>
    <div className="wm-market-tv-stage">
      {source?.kind === 'hls' ? <video key={`${attempt}:${retry}`} ref={videoRef} className="wm-market-tv-video" controls muted playsInline />
        : source ? <iframe key={`${attempt}:${retry}`} ref={frameRef} className="wm-market-tv-youtube-frame" src={url} title={title}
          allow="autoplay; encrypted-media; picture-in-picture" allowFullScreen referrerPolicy="strict-origin-when-cross-origin" /> : null}
      {!source ? <button type="button" className="wm-market-tv-fallback" onClick={() => { setAttempt(0); setRetry((v) => v + 1); }}>{shared('retry', 'Retry')}</button> : null}
    </div>
  </div>;
}
