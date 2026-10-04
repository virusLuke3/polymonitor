import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiTimeoutError, withRuntimeRequestBudget, fetchAllActiveMarkets, fetchMarketGroups, fetchAviationViewport, fetchMarketWideAiSnapshot, fetchNaturalHazardMapSource, fetchRuntimeAlpha, fetchRuntimeGeoSanctionsShock, fetchRuntimeGlobalTemperatureMonitor, fetchSystemHealth, fetchWorkspaceBundle } from './api';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('HTTP lifecycle', () => {
  it.each([[503, 'pending', true], [503, null, false], [500, 'pending', false]] as const)(
    'recognizes explicit verification pending separately from source failures (%s, %s)', async (status, marker, pending) => {
      vi.stubGlobal('window', globalThis);
      const headers = new Headers({ 'Retry-After': '1' });
      if (marker) headers.set('X-Panel-Verification', marker);
      vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status, headers })));
      await expect(fetchRuntimeAlpha()).rejects.toMatchObject({ status, verificationPending: pending, retryAfterMs: 1000 });
    });
  it('revalidates hazard snapshots instead of accepting a browser-fresh but source-expired body', async () => {
    vi.stubGlobal('window', globalThis);
    const payload = { sources: [{ key: 'nhc', staleAfter: '2026-10-01T12:00:00Z' }], events: [] };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => payload })));
    expect(await fetchNaturalHazardMapSource('nhc', 2)).toEqual(payload);
    expect(fetch).toHaveBeenCalledWith(expect.stringContaining('source=nhc'), expect.objectContaining({ cache: 'no-cache' }));
  });
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
    ['aviation', (signal: AbortSignal) => fetchAviationViewport([-10, 30, 10, 50], 3, signal)],
    ['hazards', (signal: AbortSignal) => fetchNaturalHazardMapSource('nhc', 2, undefined, signal)],
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
  it.each([
    ['temperature', () => fetchRuntimeGlobalTemperatureMonitor(), 12_000],
    ['aviation', () => fetchAviationViewport([-10, 30, 10, 50], 3), 15_000],
  ] as const)('times out stalled %s response bodies and releases its timer', async (_name, requestData, deadline) => {
    vi.useFakeTimers(); vi.stubGlobal('window', globalThis);
    vi.stubGlobal('fetch', vi.fn(async (_url, options) => ({ ok: true,
      json: () => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))),
    })));
    const request = requestData();
    const rejected = expect(request).rejects.toBeInstanceOf(ApiTimeoutError);
    await vi.advanceTimersByTimeAsync(deadline); await rejected;
    expect(vi.getTimerCount()).toBe(0);
  });
  it('allows an acquired aviation response to finish transferring after the server budget', async () => {
    vi.useFakeTimers(); vi.stubGlobal('window', globalThis);
    const payload = { status: 'partial', aircraft: [{ icao24: 'abc123' }] };
    vi.stubGlobal('fetch', vi.fn(async (_url, options) => ({ ok: true,
      json: () => new Promise((resolve, reject) => {
        const timer = setTimeout(() => resolve(payload), 14_000);
        options.signal.addEventListener('abort', () => { clearTimeout(timer); reject(new DOMException('Aborted', 'AbortError')); });
      }),
    })));
    const request = fetchAviationViewport([-10, 30, 10, 50], 3);
    const result = expect(request).resolves.toEqual(payload);
    await vi.advanceTimersByTimeAsync(14_000); await result;
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
    // The queued Runtime book request is cancelled before admission.
    expect(signals).toHaveLength(2);
    expect(signals.every((signal) => signal.aborted)).toBe(true);
  });
});


describe('shared Runtime admission', () => {
  it('queues bulk market catalogues in the shared budget and cancels before downloading', async () => {
    vi.stubGlobal('window', globalThis);
    const releases: (() => void)[] = [];
    const held = [0, 1, 2].map(() => withRuntimeRequestBudget(() => new Promise<void>(resolve => releases.push(resolve))));
    await new Promise(resolve => setTimeout(resolve, 10));
    vi.stubGlobal('fetch', vi.fn());
    const abort = new AbortController();
    const request = fetchMarketGroups('', 80, 'active', abort.signal);
    const rejection = expect(request).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetch).not.toHaveBeenCalled();
    abort.abort(); await rejection;
    releases.forEach(release => release()); await Promise.all(held);
    expect(fetch).not.toHaveBeenCalled();
  });

  it('admits a visible signal before queued background geography without expanding concurrency', async () => {
    vi.stubGlobal('window', globalThis);
    const releases: (() => void)[] = [], started: string[] = [];
    const active = [0, 1, 2].map(() => withRuntimeRequestBudget(() => new Promise<void>(resolve => releases.push(resolve))));
    await new Promise(resolve => setTimeout(resolve, 10));
    vi.stubGlobal('fetch', vi.fn(async (url: unknown) => {
      started.push(String(url));
      return { ok: true, json: async () => ({ items: [] }) };
    }));
    const geography = fetchRuntimeGeoSanctionsShock();
    const signal = fetchRuntimeAlpha();
    expect(started).toHaveLength(0);
    releases.shift()!();
    try {
      await signal; await geography;
      expect(started[0]).toContain('/runtime/signals/alpha');
      expect(started[1]).toContain('/runtime/world/geo-sanctions-shock');
    } finally {
      releases.forEach(release => release()); await Promise.all(active);
    }
  });
  it('bounds independent sources, prioritizes queued map demand, and cancels before work starts', async () => {
    const started: string[] = [], releases: (() => void)[] = [];
    const held = (id: string) => () => new Promise<void>(resolve => { started.push(id); releases.push(resolve); });
    const active = [0, 1, 2].map(i => withRuntimeRequestBudget(held(String(i))));
    await new Promise(resolve => setTimeout(resolve, 10));
    expect(started).toEqual(['0', '1', '2']);
    const abort = new AbortController();
    const cancelled = withRuntimeRequestBudget(held('cancelled'), abort.signal, 0);
    const rejection = expect(cancelled).rejects.toMatchObject({name:'AbortError'});
    abort.abort(); await rejection;
    const background = withRuntimeRequestBudget(async () => { started.push('background'); }, undefined, 2);
    const map = withRuntimeRequestBudget(async () => { started.push('map'); }, undefined, 0);
    expect(started).toHaveLength(3);
    releases.shift()!();
    await map; await background;
    expect(started).toEqual(['0','1','2','map','background']);
    releases.forEach(release=>release()); await Promise.all(active);
  });
  it('ages queued background work without increasing the shared concurrency limit', async () => {
    let clock = 0;
    const now = vi.spyOn(performance, 'now').mockImplementation(() => clock);
    const started: string[] = [], releases: (() => void)[] = [];
    const active = [0, 1, 2].map(() => withRuntimeRequestBudget(() => new Promise<void>(resolve => releases.push(resolve))));
    await new Promise(resolve => setTimeout(resolve, 10));
    const background = withRuntimeRequestBudget(async () => { started.push('background'); }, undefined, 2);
    clock = 8001;
    const interactive = withRuntimeRequestBudget(async () => { started.push('interactive'); }, undefined, 0);
    expect(started).toHaveLength(0);
    releases.shift()!();
    try {
      await Promise.all([background, interactive]);
      expect(started).toEqual(['background', 'interactive']);
    } finally {
      releases.forEach(release => release()); await Promise.all(active); now.mockRestore();
    }
  });
  it('uses the small-screen budget without coupling source cancellation', async () => {
    vi.stubGlobal('matchMedia', () => ({matches:true}));
    let active=0, peak=0;
    await Promise.all(Array.from({length:5},()=>withRuntimeRequestBudget(async()=>{
      peak=Math.max(peak,++active); await new Promise(resolve=>setTimeout(resolve,5)); active--;
    })));
    expect(peak).toBe(2);
  });
});
