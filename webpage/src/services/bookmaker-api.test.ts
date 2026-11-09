import { afterEach, expect, it, vi } from 'vitest';
import { fetchRuntimeGridEsports, fetchRuntimeSportsOdds } from './api';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it.each([fetchRuntimeGridEsports, fetchRuntimeSportsOdds])('allows the persisted bookmaker matrix to finish transferring through the public relay', async request => {
  vi.useFakeTimers(); vi.stubGlobal('window', globalThis);
  const payload = { bookmakerBoard: { fixtures: [] } };
  vi.stubGlobal('fetch', vi.fn(async (_url, options) => ({ ok: true,
    json: () => new Promise((resolve, reject) => {
      const timer = setTimeout(() => resolve(payload), 14_000);
      options.signal.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
    }),
  })));
  const result = expect(request()).resolves.toEqual(payload);
  await vi.advanceTimersByTimeAsync(14_001); await result;
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it.each([fetchRuntimeGridEsports, fetchRuntimeSportsOdds])('bounds a stalled bookmaker matrix at 30 seconds', async request => {
  vi.useFakeTimers(); vi.stubGlobal('window', globalThis);
  vi.stubGlobal('fetch', vi.fn(async (_url, options) => ({ ok: true,
    json: () => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))),
  })));
  const result = expect(request()).rejects.toMatchObject({ name: 'ApiTimeoutError' });
  await vi.advanceTimersByTimeAsync(30_001); await result;
  expect(vi.getTimerCount()).toBe(0);
});
