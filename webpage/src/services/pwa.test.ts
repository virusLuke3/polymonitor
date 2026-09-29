import { afterEach, expect, it, vi } from 'vitest';

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules(); });

it('does not reload on first claim and reloads once when an existing worker is replaced', async () => {
  vi.useFakeTimers();
  vi.stubEnv('DEV', false);
  const reload = vi.fn();
  const container = Object.assign(new EventTarget(), {
    controller: null as object | null,
    register: vi.fn(async () => Object.assign(new EventTarget(), { waiting: null, update: vi.fn(async () => {}) })),
  });
  vi.stubGlobal('__BUILD_ID__', 'startup-test');
  vi.stubGlobal('navigator', { onLine: true, serviceWorker: container });
  vi.stubGlobal('window', Object.assign(new EventTarget(), {
    matchMedia: () => ({ matches: false }),
    location: { search: '', reload },
    setInterval, clearInterval,
  }));
  const { registerPwa } = await import('./pwa');
  registerPwa();
  await Promise.resolve();
  expect(container.register).toHaveBeenCalledTimes(1);
  container.controller = {};
  container.dispatchEvent(new Event('controllerchange'));
  expect(reload).not.toHaveBeenCalled();
  container.controller = {};
  container.dispatchEvent(new Event('controllerchange'));
  container.dispatchEvent(new Event('controllerchange'));
  expect(reload).toHaveBeenCalledTimes(1);
});
