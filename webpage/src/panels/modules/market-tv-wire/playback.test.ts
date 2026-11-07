import { describe, expect, it, vi } from 'vitest';
import { advancing, observedPlaybackState, playbackCandidates, requestPlayback, youtubeVerdict } from './playback';

describe('TV channel playback', () => {
  it('keeps direct, relay and YouTube attempts within the selected channel', () => {
    const candidates = playbackCandidates({ id: 'dw', playbackSources: [
      { kind: 'hls', url: 'https://dw.example/live.m3u8', proxyFallback: true },
      { kind: 'hls', url: 'https://backup.example/live.m3u8', proxy: true, proxyFallback: true },
      { kind: 'youtube', videoId: 'abcDEF12345' },
    ] });
    expect(candidates.map((s) => [s.kind, !!s.proxy])).toEqual([['hls', false], ['hls', true], ['hls', true], ['youtube', false]]);
  });
  it('does not promote buffering, recordings or live-edge seeks to live', () => {
    expect(youtubeVerdict({ state: 3, isLive: true }, true)).toBe('waiting');
    expect(youtubeVerdict({ state: 1, isLive: false }, true)).toBe('recording');
    expect(youtubeVerdict({ state: 1, isLive: true }, true)).toBe('live');
    expect(advancing({ time: 0, at: 0 }, 4000, 1000, true)).toBe(false);
    expect(advancing({ time: 4000, at: 1000 }, 4001, 2000, true)).toBe(true);
  });
  it('shows waiting during frozen media time even after live playback was confirmed', () => {
    const moving = advancing({ time: 24, at: 24_000 }, 24, 25_000, true);
    expect(observedPlaybackState(true, moving, true, false)).toBe('waiting');
    expect(observedPlaybackState(true, false, false, false)).toBe('waiting');
    expect(observedPlaybackState(true, true, true, false)).toBe('playing');
    expect(observedPlaybackState(true, false, false, true)).toBe('paused');
    expect(observedPlaybackState(false, false, false, false)).toBe('connecting');
  });
  it.each(['AbortError', 'NotAllowedError', 'NotSupportedError'])('ignores late %s after source teardown', async (name) => {
    let reject!: (error: unknown) => void;
    let disposed = false;
    let state = 'connecting';
    const video = { play: vi.fn(() => new Promise<void>((_, fail) => { reject = fail; })) };
    const failed = vi.fn();
    const oldPlay = requestPlayback(video, () => !disposed, () => { state = 'paused'; }, failed);
    disposed = true;
    state = 'playing'; // The replacement source has already advanced.
    reject({ name });
    await oldPlay;
    expect(state).toBe('playing');
    expect(failed).not.toHaveBeenCalled();
  });
  it('does not mistake an interrupted play for a user pause or disable recovery', async () => {
    const paused = vi.fn();
    const failed = vi.fn();
    await requestPlayback({ play: () => Promise.reject({ name: 'AbortError' }) }, () => true, paused, failed);
    expect(paused).not.toHaveBeenCalled();
    expect(failed).not.toHaveBeenCalled();
    await requestPlayback({ play: () => Promise.reject({ name: 'NotSupportedError' }) }, () => true, paused, failed);
    expect(paused).not.toHaveBeenCalled();
    expect(failed).toHaveBeenCalledOnce();
    await requestPlayback({ play: () => Promise.reject({ name: 'NotAllowedError' }) }, () => true, paused, failed);
    expect(paused).toHaveBeenCalledOnce();
  });
  it('does not reopen hidden, user-paused or already-failed media', async () => {
    const video = { play: vi.fn(async () => {}) };
    let hidden = true;
    let paused = false;
    let failed = false;
    const active = () => !hidden && !paused && !failed;
    const request = () => requestPlayback(video, active, () => { paused = true; }, () => { failed = true; });
    await request();
    expect(video.play).not.toHaveBeenCalled();
    hidden = false;
    paused = true;
    await request();
    expect(video.play).not.toHaveBeenCalled();
    paused = false;
    await request();
    expect(video.play).toHaveBeenCalledOnce();
    failed = true;
    await request();
    expect(video.play).toHaveBeenCalledOnce();
  });
  it('ignores a rejected play after the current source has already failed', async () => {
    let reject!: (error: unknown) => void;
    let failed = false;
    const blocked = vi.fn();
    const fallback = vi.fn();
    const pending = requestPlayback({ play: () => new Promise<void>((_, fail) => { reject = fail; }) },
      () => !failed, blocked, fallback);
    failed = true;
    reject({ name: 'NotAllowedError' });
    await pending;
    expect(blocked).not.toHaveBeenCalled();
    expect(fallback).not.toHaveBeenCalled();
  });
});
