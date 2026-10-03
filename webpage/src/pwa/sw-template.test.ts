import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const source = readFileSync(new URL('./sw-template.js', import.meta.url), 'utf8');
function worker() {
  const cache = { match: vi.fn().mockResolvedValue(undefined), put: vi.fn().mockResolvedValue(undefined) };
  const fetch = vi.fn();
  const listeners: Record<string, (event: any) => void> = {};
  const cacheFirst = runInNewContext(`${source}\ncacheFirst`, {
    self: { location: { origin: 'https://polymonitor.test' }, addEventListener: (name: string, fn: any) => { listeners[name] = fn; } },
    caches: { open: async () => cache }, fetch, Response, URL, setTimeout,
  }) as (request: Request) => Promise<Response>;
  return { cacheFirst, cache, fetch, listeners };
}
const asset = () => new Request('https://polymonitor.test/assets/GlobeMapRenderer.js');

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
