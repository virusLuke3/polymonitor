import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiTimeoutError, fetchAllActiveMarkets, fetchMarketWideAiSnapshot, fetchRuntimeGlobalTemperatureMonitor, fetchSystemHealth, fetchWorkspaceBundle } from './api';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('HTTP lifecycle', () => {
  it('uses redacted public health for anonymous consumers and preserves degraded status', async () => {
    vi.stubGlobal('window', globalThis);
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({
      status: 'degraded', database: true, redis: false,
    }) })));
    expect(await fetchSystemHealth()).toEqual({ apiStatus: 'degraded', redis: false });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).toMatch(/\/health$/);
    expect(String(vi.mocked(fetch).mock.calls[0]?.[0])).not.toContain('/system/');
  });
  it('publishes the first market page before continuing and starts no next page after cancellation', async () => {
    vi.stubGlobal('window', globalThis);
    const controller = new AbortController();
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({
      items: [{ id: 1 }], pagination: { total: 160, totalPages: 2, hasMore: true },
    }) })));
    const firstPage = vi.fn(() => controller.abort());
    await expect(fetchAllActiveMarkets('', 80, 8, controller.signal, firstPage)).rejects.toMatchObject({ name: 'AbortError' });
    expect(firstPage).toHaveBeenCalledTimes(1);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it.each([
    ['temperature', (signal: AbortSignal) => fetchRuntimeGlobalTemperatureMonitor(60, signal)],
    ['AI snapshot', (signal: AbortSignal) => fetchMarketWideAiSnapshot('overview', 8000, signal)],
  ] as const)('keeps %s cancellation connected while consuming the response body', async (_name, requestData) => {
    vi.stubGlobal('window', globalThis);
    let requestSignal!: AbortSignal;
    let reading!: () => void;
    const bodyStarted = new Promise<void>((resolve) => { reading = resolve; });
    vi.stubGlobal('fetch', vi.fn(async (_url, options) => {
      requestSignal = options.signal;
      return { ok: true, json: () => new Promise((_resolve, reject) => {
        reading(); requestSignal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
      }) };
    }));
    const controller = new AbortController();
    const request = requestData(controller.signal);
    const rejected = expect(request).rejects.toMatchObject({ name: 'AbortError' });
    await bodyStarted; controller.abort(); await rejected;
    expect(requestSignal.aborted).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('times out stalled response bodies and releases its timer', async () => {
    vi.useFakeTimers(); vi.stubGlobal('window', globalThis);
    vi.stubGlobal('fetch', vi.fn(async (_url, options) => ({ ok: true,
      json: () => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))),
    })));
    const request = fetchRuntimeGlobalTemperatureMonitor();
    const rejected = expect(request).rejects.toBeInstanceOf(ApiTimeoutError);
    await vi.advanceTimersByTimeAsync(12_000); await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });
  it('does not start a detail fallback after cancellation and cancels optional content and book requests', async () => {
    vi.stubGlobal('window', globalThis);
    const signals: AbortSignal[] = [];
    vi.stubGlobal('fetch', vi.fn((_url, options) => new Promise((_resolve, reject) => {
      signals.push(options.signal);
      options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
    })));
    const controller = new AbortController();
    const request = fetchWorkspaceBundle(1, { includeContent: true, includeLob: true, signal: controller.signal });
    controller.abort(); await request;
    expect(signals).toHaveLength(3);
    expect(signals.every((signal) => signal.aborted)).toBe(true);
  });
});
