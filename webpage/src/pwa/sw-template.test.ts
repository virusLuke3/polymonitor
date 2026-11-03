import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const source = readFileSync(new URL('./sw-template.js', import.meta.url), 'utf8');
function worker() {
  const cache = { match: vi.fn().mockResolvedValue(undefined), put: vi.fn().mockResolvedValue(undefined) };
  const fetch = vi.fn();
  const listeners: Record<string, (event: any) => void> = {};
  const open = vi.fn().mockResolvedValue(cache);
  const handlers = runInNewContext(`${source}\n({ cacheFirst, networkFirst })`, {
    self: { location: { origin: 'https://polymonitor.test' }, addEventListener: (name: string, fn: any) => { listeners[name] = fn; } },
    caches: { open }, fetch, Response, URL, setTimeout,
  }) as Record<'cacheFirst' | 'networkFirst', (request: Request) => Promise<Response>>;
  return { ...handlers, cache, open, fetch, listeners };
}
const asset = () => new Request('https://polymonitor.test/assets/GlobeMapRenderer.js');

describe('service worker homepage freshness', () => {
  const home = () => new Request('https://polymonitor.test/?center=0,37&zoom=1.66');
  it('returns the new homepage even when caching it fails and an old homepage exists', async () => {
    const w = worker();
    w.cache.match.mockResolvedValue(new Response('old release without new panels'));
    w.cache.put.mockRejectedValue(new Error('QuotaExceededError'));
    w.fetch.mockResolvedValue(new Response('current release with new panels'));
    expect(await (await w.networkFirst(home())).text()).toBe('current release with new panels');
    expect(w.cache.match).not.toHaveBeenCalled();
    expect(w.fetch).toHaveBeenCalledWith(expect.any(Request), { cache: 'no-cache' });
  });
  it('loads the homepage when browser cache storage is unavailable', async () => {
    const w = worker();
    w.open.mockRejectedValue(new Error('storage unavailable'));
    w.fetch.mockResolvedValue(new Response('current homepage'));
    expect(await (await w.networkFirst(home())).text()).toBe('current homepage');
  });
  it('uses the cached root when offline with a new map URL', async () => {
    const w = worker();
    w.fetch.mockRejectedValue(new TypeError('offline'));
    w.cache.match.mockImplementation(async key => key === '/' ? new Response('offline homepage') : undefined);
    expect(await (await w.networkFirst(home())).text()).toBe('offline homepage');
  });
  it('returns a network error when offline and cache storage also fails', async () => {
    const w = worker();
    w.fetch.mockRejectedValue(new TypeError('offline'));
    w.open.mockRejectedValue(new Error('storage unavailable'));
    expect((await w.networkFirst(home())).type).toBe('error');
  });
});

describe('service worker static asset recovery', () => {
  it('retries a connection failure once before exposing it to the module loader', async () => {
    const w = worker();
    w.fetch.mockRejectedValueOnce(new TypeError('connection reset')).mockResolvedValueOnce(new Response('export const ready = true;'));
    expect(await (await w.cacheFirst(asset())).text()).toContain('ready = true');
    expect(w.fetch).toHaveBeenCalledTimes(2);
    expect(w.cache.put).toHaveBeenCalledTimes(1);
  });
  it('also retries an interrupted response body after HTTP 200', async () => {
    const w = worker();
    const broken = new ReadableStream({ start(controller) { controller.error(new Error('network changed during body')); } });
    w.fetch.mockResolvedValueOnce(new Response(broken)).mockResolvedValueOnce(new Response('complete module'));
    expect(await (await w.cacheFirst(asset())).text()).toBe('complete module');
    expect(w.fetch).toHaveBeenCalledTimes(2);
  });
  it('keeps a valid download when writing the cache exceeds quota', async () => {
    const w = worker();
    w.cache.put.mockRejectedValue(new Error('QuotaExceededError'));
    w.fetch.mockResolvedValue(new Response('valid texture'));
    expect(await (await w.cacheFirst(asset())).text()).toBe('valid texture');
    expect(w.fetch).toHaveBeenCalledTimes(1);
  });
  it('bounds persistent failures and respects an aborted request', async () => {
    const w = worker();
    w.fetch.mockRejectedValue(new TypeError('offline'));
    await expect(w.cacheFirst(asset())).rejects.toThrow('offline');
    expect(w.fetch).toHaveBeenCalledTimes(2);
    const controller = new AbortController(); controller.abort();
    await expect(w.cacheFirst(new Request(asset(), { signal: controller.signal }))).rejects.toThrow('offline');
    expect(w.fetch).toHaveBeenCalledTimes(3);
  });
  it('leaves API cancellation to its document and does not cache HTTP failures', async () => {
    const w = worker();
    const respondWith = vi.fn();
    w.listeners.fetch!({ request: new Request('https://polymonitor.test/wm-api/runtime/world/natural-hazards'), respondWith });
    expect(respondWith).not.toHaveBeenCalled();
    w.fetch.mockResolvedValue(new Response('missing', { status: 404 }));
    expect((await w.cacheFirst(asset())).status).toBe(404);
    expect(w.cache.put).not.toHaveBeenCalled();
  });
});
