import { describe, expect, it } from 'vitest';
import { advancing, playbackCandidates, youtubeVerdict } from './playback';

describe('TV channel playback', () => {
  it('keeps direct, relay and YouTube attempts within the selected channel', () => {
    const candidates = playbackCandidates({ id: 'dw', playbackSources: [
      { kind: 'hls', url: 'https://dw.example/live.m3u8', proxyFallback: true },
      { kind: 'youtube', videoId: 'abcDEF12345' },
    ] });
    expect(candidates.map((s) => [s.kind, !!s.proxy])).toEqual([['hls', false], ['hls', true], ['youtube', false]]);
  });
  it('does not promote buffering, recordings or live-edge seeks to live', () => {
    expect(youtubeVerdict({ state: 3, isLive: true }, true)).toBe('waiting');
    expect(youtubeVerdict({ state: 1, isLive: false }, true)).toBe('recording');
    expect(youtubeVerdict({ state: 1, isLive: true }, true)).toBe('live');
    expect(advancing({ time: 0, at: 0 }, 4000, 1000, true)).toBe(false);
    expect(advancing({ time: 4000, at: 1000 }, 4001, 2000, true)).toBe(true);
  });
});
