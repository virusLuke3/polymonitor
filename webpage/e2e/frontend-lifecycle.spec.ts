import { installLocalAssets } from './fixtures/browser';
import { expect, test, type Page } from '@playwright/test';
import { fixtureBundle } from './fixtures/dashboard';
import { GENERATED_AT, installFixtures } from './fixtures/world-event-map';
import type {} from './fixtures/lifecycle';

async function harness(page: Page, kind: Parameters<Window['frontendHarness']['mount']>[0], query = '') {
  await installLocalAssets(page);
  await page.goto(`/e2e/lifecycle.html${query}`);
  await page.waitForFunction(() => Boolean(window.frontendHarness), { timeout: 60_000 });
  await page.clock.install({ time: new Date(GENERATED_AT) });
  await page.evaluate((value) => window.frontendHarness.mount(value), kind);
  await page.clock.runFor(200);
}
const count = (page: Page) => page.evaluate(() => window.frontendHarness.requests.length);

test('unobserved panels wait for visibility while explicit map demand starts immediately', async ({ page }) => {
  await harness(page, 'observed-runtime');
  await page.clock.runFor(2000);
  expect(await count(page)).toBe(0);
  await page.evaluate(() => window.frontendHarness.runtime!.setConsumerPanels('map', ['shared']));
  await page.clock.runFor(100);
  expect(await count(page)).toBe(1);
  await page.evaluate(() => {
    window.frontendHarness.runtime!.setPanelVisible('shared', true);
    window.frontendHarness.runtime!.setConsumerPanels('map', []);
  });
  await page.clock.runFor(100);
  expect(await count(page)).toBe(1);
  expect(await page.evaluate(() => window.frontendHarness.requests[0].signal.aborted)).toBe(false);
  await page.evaluate(() => window.frontendHarness.runtime!.setPanelVisible('shared', false));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.requests[0].signal.aborted)).toBe(true);
});

test('dashboard releases slow bootstrap, publishes summaries independently and rejects late previews', async ({ page }) => {
  let releaseBootstrap: (() => Promise<void>) | undefined;
  let releaseContent: (() => Promise<void>) | undefined;
  let tradesRequests = 0;
  await page.route('**/wm-api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/bootstrap')) {
      releaseBootstrap = () => route.fulfill({ json: { systemHealth: { apiStatus: 'old-preview' }, globalTradesPreview: [{ id: 'old' }] } });
    } else if (path.endsWith('/content/latest')) {
      releaseContent = () => route.fulfill({ json: { items: [{ id: 'late-content' }] } });
    } else if (path.endsWith('/trades/recent')) {
      tradesRequests++;
      return route.fulfill({ json: [{ id: 'fresh-trade' }] });
    } else if (path.endsWith('/system/health')) return route.fulfill({ json: { apiStatus: 'fresh-health' } });
    else return route.fulfill({ json: [] });
  });
  await harness(page, 'dashboard');
  await page.clock.runFor(1500);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.dashboard!.health?.apiStatus)).toBe('fresh-health');
  expect(await page.evaluate(() => window.frontendHarness.dashboard!.loading)).toBe(false);
  expect(await page.evaluate(() => window.frontendHarness.dashboard!.globalTrades)).toEqual([{ id: 'fresh-trade' }]);
  expect(releaseContent).toBeDefined();
  await releaseBootstrap!();
  await releaseContent!();
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.dashboard!.health?.apiStatus)).toBe('fresh-health');
  expect(await page.evaluate(() => window.frontendHarness.dashboard!.globalTrades)).toEqual([{ id: 'fresh-trade' }]);
  expect(tradesRequests).toBe(1);
  await page.evaluate(() => window.frontendHarness.unmount());
  await page.clock.runFor(60_000);
  expect(tradesRequests).toBe(1);
});

test('shared demand joins requests, survives a closed panel and rejects aborted generations', async ({ page }) => {
  await harness(page, 'runtime');
  expect(await count(page)).toBe(1);
  await page.evaluate(() => {
    const h = window.frontendHarness;
    h.runtime!.setConsumerPanels('map', ['shared']);
    h.runtime!.setPanelVisible('shared', false);
    h.setPanels([]);
    void h.runtime!.refreshIds(['shared']);
    void h.runtime!.refreshIds(['shared']);
  });
  await page.clock.runFor(100);
  expect(await count(page)).toBe(1);
  expect(await page.evaluate(() => window.frontendHarness.requests[0].signal.aborted)).toBe(false);
  await page.evaluate((generatedAt) => window.frontendHarness.requests[0].resolve({ generatedAt, items: ['first'] }), GENERATED_AT);
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.runtimeData.shared)).toMatchObject({ items: ['first'] });
  await page.evaluate(() => window.frontendHarness.runtime!.setConsumerPanels('map', []));
  await page.clock.runFor(60_000);
  expect(await count(page)).toBe(1);
  await page.evaluate(() => window.frontendHarness.runtime!.setConsumerPanels('map', ['shared']));
  await page.clock.runFor(100);
  expect(await count(page)).toBe(2);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.requests[1].signal.aborted)).toBe(true);
  await page.evaluate(() => window.frontendHarness.requests[1].resolve({ items: ['obsolete'] }));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.runtimeData.shared)).toMatchObject({ items: ['first'] });
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(100);
  expect(await count(page)).toBe(3);
  await page.evaluate(() => window.frontendHarness.unmount());
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.requests[2].signal.aborted)).toBe(true);
  await page.clock.runFor(60_000);
  expect(await count(page)).toBe(3);
});

test('retry recovers and a failed refresh retains data without inventing freshness', async ({ page }) => {
  await harness(page, 'runtime');
  await page.evaluate(() => window.frontendHarness.requests[0].reject(new Error('source down')));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').phase)).toBe('error');
  await page.clock.runFor(1100);
  expect(await count(page)).toBe(2);
  await page.evaluate(() => window.frontendHarness.requests[1].resolve({ items: ['retained'], status: 'ok' }));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').updatedAt)).toBeNull();
  await page.evaluate(() => { void window.frontendHarness.runtime!.refreshIds(['shared'], { reason: 'manual' }); });
  await page.evaluate(() => window.frontendHarness.requests[2].reject(new Error('refresh down')));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').phase)).toBe('degraded');
  expect(await page.evaluate(() => window.frontendHarness.runtime!.runtimeData.shared)).toEqual({ items: ['retained'], status: 'ok' });
  await page.evaluate(() => window.frontendHarness.setPanels([]));
  await page.clock.runFor(10_000);
  expect(await count(page)).toBe(3);
});

test('market and chart switches reject old responses and cancel on unmount', async ({ page }) => {
  const pending: Array<{ url: string; resolve: () => Promise<void> }> = [];
  await page.route('**/wm-api/**', async (route) => {
    const url = new URL(route.request().url());
    const id = Number(url.pathname.match(/markets\/(\d+)/)?.[1] || 1);
    const bundle = fixtureBundle(id);
    const chart = url.pathname.endsWith('/chart');
    const json = chart ? { ...bundle.chart, range: url.searchParams.get('range') } : bundle;
    if (id === 1 || url.searchParams.get('range') === '1h') pending.push({ url: url.href, resolve: () => route.fulfill({ json }).catch(() => {}) });
    else await route.fulfill({ json });
  });
  await harness(page, 'focus');
  await expect.poll(() => pending.length).toBeGreaterThan(0);
  await page.evaluate(() => window.frontendHarness.focus!.setSelectedMarketId(2));
  await page.clock.runFor(300);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.focus!.bundle?.market?.id)).toBe(2);
  for (const item of pending.splice(0)) await item.resolve();
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.focus!.bundle?.market?.id)).toBe(2);
  await page.evaluate(() => window.frontendHarness.focus!.setSelectedMarketGroupChartRange('1h'));
  await page.clock.runFor(200);
  await expect.poll(() => pending.length).toBeGreaterThan(0);
  await page.evaluate(() => window.frontendHarness.focus!.setSelectedMarketGroupChartRange('1w'));
  await page.clock.runFor(200);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.focus!.bundle?.chart?.range)).toBe('1w');
  for (const item of pending.splice(0)) await item.resolve();
  await page.clock.runFor(21_000);
  expect(await page.evaluate(() => window.frontendHarness.focus!.bundle?.chart?.range)).toBe('1w');
  await page.evaluate(() => window.frontendHarness.unmount());
  const afterUnmount: string[] = [];
  page.on('request', (request) => afterUnmount.push(request.url()));
  await page.clock.runFor(60_000);
  expect(afterUnmount.filter((url) => url.includes('/wm-api/'))).toEqual([]);
});

test('token switches retain only matching books and errors keep stale levels', async ({ page }) => {
  let fail = false;
  let obsolete: (() => Promise<void>) | undefined;
  await page.route('**/wm-api/runtime/lob/token/**', async (route) => {
    const id = Number(new URL(route.request().url()).searchParams.get('marketId'));
    if (id === 1) { obsolete = () => route.fulfill({ json: fixtureBundle(1).lob }).catch(() => {}); return; }
    await route.fulfill({ json: fail ? fixtureBundle(1).lob : fixtureBundle(2).lob });
  });
  await harness(page, 'book');
  await expect.poll(() => Boolean(obsolete)).toBe(true);
  await page.evaluate(() => window.frontendHarness.selectBook(2));
  await page.clock.runFor(300);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.book!.tokenLobState.lob?.yes?.tokenId)).toBe('yes-2');
  await obsolete!();
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.book!.tokenLobState.lob?.yes?.tokenId)).toBe('yes-2');
  fail = true;
  await page.clock.runFor(2500);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.book!.tokenLobState.lob?.yes?.bookStatus)).toBe('stale');
  expect(await page.evaluate(() => window.frontendHarness.book!.tokenLobState.updatedAt)).toBe(Date.parse(GENERATED_AT));
  await page.evaluate(() => window.frontendHarness.unmount());
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.url()));
  await page.clock.runFor(60_000);
  expect(requests.filter((url) => url.includes('/wm-api/'))).toEqual([]);
});

test('two panel views use one data owner and one cache', async ({ page }) => {
  await harness(page, 'runtime');
  await page.evaluate(() => window.frontendHarness.setPanels(['shared', 'shared-view']));
  await page.clock.runFor(100);
  expect(await count(page)).toBe(1);
  await page.evaluate(() => {
    const h = window.frontendHarness;
    h.setPanels(['shared-view']);
    h.runtime!.setPanelVisible('shared', false);
    void h.runtime!.refreshIds(['shared-view']);
  });
  await page.clock.runFor(100);
  expect(await count(page)).toBe(1);
  expect(await page.evaluate(() => window.frontendHarness.requests[0].signal.aborted)).toBe(false);
  await page.evaluate(() => window.frontendHarness.requests[0].resolve({ items: ['same'] }));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => {
    const r = window.frontendHarness.runtime!;
    return r.getData('shared') === r.getData('shared-view') && r.getStatus('shared') === r.getStatus('shared-view');
  })).toBe(true);
  expect(await page.evaluate(() => Object.keys(window.frontendHarness.runtime!.runtimeData))).toEqual(['shared']);
  await page.evaluate(() => window.frontendHarness.runtime!.setPanelVisible('shared-view', false));
  await page.clock.runFor(60_000);
  expect(await count(page)).toBe(1);
});

async function workspaceServer(page: Page, options: { conflict?: boolean; remote?: Record<string, unknown> } = {}) {
  const writes: Array<{ body: any; reply: () => Promise<void> }> = [];
  await page.route('**/wm-api/auth/session', route => route.fulfill({ json: {
    enabled: true, authenticated: true, user: { id: 7, username: 'workspace-fixture', role: 'user' }, csrfToken: 'fixture-only',
  } }));
  await page.route('**/wm-api/product/workspace-layout', async route => {
    const base = { exists: true, revision: 4, activePanelIds: ['active-markets', 'price-chart'], panelLayout: {},
      preferences: { showPanelLibrary: true, viewMode: '3d', region: 'europe', mapZoom: 4 },
      updatedAt: GENERATED_AT, clientUpdatedAt: GENERATED_AT, ...options.remote };
    if (route.request().method() === 'GET') return route.fulfill({ json: base });
    const body = route.request().postDataJSON();
    writes.push({ body, reply: () => route.fulfill({ status: options.conflict ? 409 : 200,
      json: options.conflict ? { error: 'revision conflict' } : { ...base, ...body, revision: body.revision + 1 } }).catch(() => {}) });
  });
  return writes;
}

test('workspace serializes changes behind the acknowledged revision and cancels pending writes on exit', async ({ page }) => {
  const writes = await workspaceServer(page);
  await harness(page, 'workspace', '?view=2d&zoom=2.2');
  await expect.poll(() => page.evaluate(() => window.frontendHarness.sync!.workspaceSyncStatus)).toBe('synced');
  expect(await page.evaluate(() => window.frontendHarness.workspace!.viewMode)).toBe('2d');
  expect(await page.evaluate(() => window.frontendHarness.camera!.mapZoom)).toBe(2.2);
  await page.evaluate(() => window.frontendHarness.workspace!.setActivePanelIds(['price-chart']));
  await page.clock.runFor(1100);
  await expect.poll(() => writes.length).toBe(1);
  await page.evaluate(() => window.frontendHarness.workspace!.setActivePanelIds(['lob-depth']));
  await page.clock.runFor(2000);
  expect(writes).toHaveLength(1);
  await writes[0].reply();
  await expect.poll(() => page.evaluate(() => window.frontendHarness.sync!.workspaceSyncStatus)).toBe('saving');
  await page.clock.runFor(1100);
  await expect.poll(() => writes.length).toBe(2);
  expect(writes.map(write => write.body.revision)).toEqual([4, 5]);
  expect(writes[1].body.activePanelIds).toEqual(['lob-depth']);
  await writes[1].reply();
  await expect.poll(() => page.evaluate(() => window.frontendHarness.sync!.workspaceSyncStatus)).toBe('synced');
  await page.evaluate(() => window.frontendHarness.workspace!.setActivePanelIds(['active-markets']));
  await page.clock.runFor(100);
  await page.evaluate(() => window.frontendHarness.unmount());
  await page.clock.runFor(5000);
  expect(writes).toHaveLength(2);
});

test('workspace conflict preserves local layout and another account hydrates its own remote preferences', async ({ page }) => {
  const writes = await workspaceServer(page, { conflict: true });
  await page.addInitScript(() => {
    localStorage.setItem('polydata:workspace-sync-meta:v1', JSON.stringify({ userId: 999, updatedAt: '2099-01-01' }));
    localStorage.setItem('polydata:workspace-panels:v4', JSON.stringify(['oracle-feed']));
  });
  await harness(page, 'workspace');
  await expect.poll(() => page.evaluate(() => window.frontendHarness.sync!.workspaceSyncStatus)).toBe('synced');
  expect(await page.evaluate(() => window.frontendHarness.workspace!.activePanelIds)).toEqual(['active-markets', 'price-chart']);
  expect(writes).toHaveLength(0);
  await page.evaluate(() => {
    const w = window.frontendHarness.workspace!;
    w.setActivePanelIds(['lob-depth']);
    w.resizeWorkspacePanel('lob-depth', { rowSpan: 3 });
  });
  await page.clock.runFor(1100);
  await expect.poll(() => writes.length).toBe(1);
  await writes[0].reply();
  await expect.poll(() => page.evaluate(() => window.frontendHarness.sync!.workspaceSyncStatus)).toBe('conflict');
  await page.clock.runFor(10_000);
  expect(writes).toHaveLength(1);
  expect(await page.evaluate(() => window.frontendHarness.workspace!.activePanelIds)).toEqual(['lob-depth']);
  expect(await page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panel-layout:v4')!))).toMatchObject({ 'lob-depth': { rowSpan: 3 } });
});

test('warming responses retain the last useful snapshot and its observation time', async ({ page }) => {
  await harness(page, 'runtime');
  await page.evaluate((generatedAt) => window.frontendHarness.requests[0].resolve({ generatedAt, items: ['kept'] }), GENERATED_AT);
  await page.clock.runFor(100);
  await page.evaluate(() => { void window.frontendHarness.runtime!.refreshIds(['shared']); });
  await page.evaluate(() => window.frontendHarness.requests[1].resolve({ status: 'warming', generatedAt: '2099-01-01T00:00:00Z', items: [] }));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared'))).toMatchObject({ phase: 'degraded', updatedAt: Date.parse(GENERATED_AT) });
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getData('shared'))).toMatchObject({ items: ['kept'] });
});

test('late bootstrap defaults do not re-enable panels disabled by the account layout', async ({ page }) => {
  await workspaceServer(page);
  await harness(page, 'workspace');
  await expect.poll(() => page.evaluate(() => window.frontendHarness.sync!.workspaceSyncStatus)).toBe('synced');
  await page.evaluate(() => window.frontendHarness.workspace!.applyBootstrapPanels({ defaultWorkspace: { panels: ['oracle-feed'] } } as any));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.workspace!.activePanelIds)).toEqual(['active-markets', 'price-chart']);
});

test('focused book pauses and cancels while hidden, then resumes with one request', async ({ page }) => {
  const pending: Array<() => Promise<void>> = [];
  await page.route('**/wm-api/runtime/lob/token/**', route => {
    pending.push(() => route.fulfill({ json: fixtureBundle(1).lob }).catch(() => {}));
  });
  await harness(page, 'book');
  await expect.poll(() => pending.length).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(100);
  await pending[0]();
  await page.clock.runFor(10_000);
  expect(pending).toHaveLength(1);
  expect(await page.evaluate(() => window.frontendHarness.book!.tokenLobState.lob)).toBeNull();
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(100);
  await expect.poll(() => pending.length).toBe(2);
  await pending[1]();
  await expect.poll(() => page.evaluate(() => window.frontendHarness.book!.tokenLobState.lob?.yes?.tokenId)).toBe('yes-1');
  await page.evaluate(() => window.frontendHarness.unmount());
});

async function trackRequests(page: Page, ignoreAbortFor = '') {
  await page.addInitScript((ignoreAbortFor) => {
    const calls: Array<{ url: string; signal?: AbortSignal | null }> = [];
    (window as any).fetchCalls = calls;
    const original = window.fetch;
    window.fetch = (input, init) => {
      calls.push({ url: String(input), signal: init?.signal });
      // A misbehaving transport can resolve after cancellation; identity guards must still win.
      return original(input, ignoreAbortFor && String(input).includes(ignoreAbortFor) ? { ...init, signal: undefined } : init);
    };
  }, ignoreAbortFor);
}

async function hidden(page: Page, value: boolean) {
  await page.evaluate((value) => {
    Object.defineProperty(document, 'hidden', { configurable: true, value });
    document.dispatchEvent(new Event('visibilitychange'));
  }, value);
  await page.clock.runFor(100);
}

const hazardCalls = (page: Page) => page.evaluate(() => (window as any).fetchCalls
  .filter((call: any) => call.url.includes('/natural-hazards/map'))
  .map((call: any) => ({ source: new URL(call.url, location.origin).searchParams.get('source'), aborted: call.signal?.aborted })));

test('hazard layers share source demand and only FIRMS restarts for a viewport change', async ({ page }) => {
  await trackRequests(page);
  await installFixtures(page);
  await harness(page, 'hazards');
  await expect.poll(async () => (await hazardCalls(page)).length).toBe(5);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.hazards!.loading)).toBe(false);
  expect((await hazardCalls(page)).map((call: any) => call.source).sort()).toEqual(['eonet', 'firms', 'gdacs', 'usgs', 'usgs-volcano-cap']);
  await page.evaluate(() => window.frontendHarness.setHazardView({ center: [70, 43] }));
  await page.clock.runFor(100);
  await expect.poll(async () => (await hazardCalls(page)).length).toBe(6);
  expect((await hazardCalls(page))[5].source).toBe('firms');
  await page.evaluate(() => window.frontendHarness.setHazardView({ layers: ['wildfires'] }));
  await page.clock.runFor(65_000);
  expect(await hazardCalls(page)).toHaveLength(6);
  await page.evaluate(() => window.frontendHarness.setHazardView({ layers: ['wildfires', 'weather-alerts'] }));
  await page.clock.runFor(100);
  await expect.poll(async () => (await hazardCalls(page)).length).toBe(8);
  expect((await hazardCalls(page)).slice(6).map((call: any) => call.source).sort()).toEqual(['nhc', 'nws']);
  await page.evaluate(() => window.frontendHarness.setHazardView({ layers: [] }));
  await page.clock.runFor(600_000);
  expect(await hazardCalls(page)).toHaveLength(8);
  await page.evaluate(() => window.frontendHarness.unmount());
});

test('hazards cancel hidden and inactive requests, reject cancelled generations and retain failed-refresh snapshots', async ({ page }) => {
  await trackRequests(page);
  await installFixtures(page);
  await harness(page, 'hazards');
  await expect.poll(() => page.evaluate(() => window.frontendHarness.hazards!.loading)).toBe(false);
  const initialIds = await page.evaluate(() => window.frontendHarness.hazards!.events.map(event => event.id));
  const initialTimes = await page.evaluate(() => window.frontendHarness.hazards!.sources.map(source => source.generatedAt));
  await hidden(page, true);
  await page.clock.runFor(600_000);
  expect(await hazardCalls(page)).toHaveLength(5);
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**', route => route.fulfill({ status: 503, json: { error: 'source offline' } }));
  await hidden(page, false);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.hazards!.sources.filter(source => source.status === 'degraded').length)).toBe(5);
  expect(await page.evaluate(() => window.frontendHarness.hazards!.events.map(event => event.id))).toEqual(initialIds);
  expect(await page.evaluate(() => window.frontendHarness.hazards!.sources.map(source => source.generatedAt))).toEqual(initialTimes);
  await page.evaluate(() => window.frontendHarness.setHazardView({ active: false }));
  await page.clock.runFor(100);
  const stopped = (await hazardCalls(page)).length;
  await page.clock.runFor(600_000);
  expect(await hazardCalls(page)).toHaveLength(stopped);
  const pending: Array<() => Promise<void>> = [];
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**', route => {
    const source = new URL(route.request().url()).searchParams.get('source');
    pending.push(() => route.fulfill({ json: { schemaVersion: 'natural-hazards-map.v1', generatedAt: GENERATED_AT,
      events: [], sources: [{ key: source, status: 'ok' }], errors: [], counts: { events: 0 } } }).catch(() => {}));
  });
  await page.evaluate(() => window.frontendHarness.setHazardView({ active: true }));
  await page.clock.runFor(100);
  await expect.poll(() => pending.length).toBe(3); // Bounded initial fan-out.
  await hidden(page, true);
  expect((await hazardCalls(page)).slice(-3).every((call: any) => call.aborted)).toBe(true);
  for (const reply of pending) await reply();
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.hazards!.events.map(event => event.id))).toEqual(initialIds);
  await page.evaluate(() => window.frontendHarness.unmount());
});

test('anonymous workspace preserves disabled and empty layouts across remount and late bootstrap', async ({ page }) => {
  await page.route('**/wm-api/auth/session', route => route.fulfill({ json: { enabled: true, authenticated: false, user: null } }));
  await harness(page, 'workspace');
  await expect.poll(() => page.evaluate(() => window.frontendHarness.sync!.workspaceSyncStatus)).toBe('local');
  for (const ids of [['oracle-feed'], []] as string[][]) {
    await page.evaluate(ids => window.frontendHarness.workspace!.setActivePanelIds(ids), ids);
    await page.clock.runFor(100);
    await page.evaluate(() => { window.frontendHarness.unmount(); window.frontendHarness.mount('workspace'); });
    await page.clock.runFor(200);
    await page.evaluate(() => window.frontendHarness.workspace!.applyBootstrapPanels({ defaultWorkspace: { panels: ['price-chart'] } } as any));
    await page.clock.runFor(100);
    expect(await page.evaluate(() => window.frontendHarness.workspace!.activePanelIds)).toEqual(ids);
    expect(await page.evaluate(() => JSON.parse(localStorage.getItem('polydata:workspace-panels:v4')!))).toEqual(ids);
  }
});

test('market dossier joins refreshes and cancels the whole request before follow-up books', async ({ page }) => {
  await trackRequests(page);
  const pending: Array<() => Promise<void>> = [];
  await page.route('**/wm-api/**', route => {
    const url = new URL(route.request().url());
    const id = Number(url.pathname.match(/(?:markets|market)\/(\d+)/)?.[1] || 1);
    if (url.pathname.endsWith('/workspace') && id === 1) {
      pending.push(() => route.fulfill({ json: fixtureBundle(1) }).catch(() => {})); return;
    }
    const isBook = url.pathname.includes('/runtime/lob/');
    return route.fulfill({ json: isBook ? fixtureBundle(2).lob : fixtureBundle(id) });
  });
  await harness(page, 'dossier');
  await expect.poll(() => pending.length).toBe(1);
  await page.evaluate(() => { void window.frontendHarness.dossier!.refresh(); void window.frontendHarness.dossier!.refresh(); });
  expect(pending).toHaveLength(1);
  await page.evaluate(() => window.frontendHarness.selectDossier(2));
  await page.clock.runFor(100);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.dossier!.bundle?.market?.id)).toBe(2);
  expect(await page.evaluate(() => (window as any).fetchCalls.find((call: any) => call.url.includes('/markets/1/workspace')).signal.aborted)).toBe(true);
  await pending[0]();
  await page.clock.runFor(100);
  expect(await page.evaluate(() => (window as any).fetchCalls.some((call: any) => call.url.includes('/token/yes-1')))).toBe(false);
  await page.evaluate(() => window.frontendHarness.selectDossier(1));
  await page.clock.runFor(100);
  await expect.poll(() => pending.length).toBe(2);
  await page.evaluate(() => window.frontendHarness.unmount());
  expect(await page.evaluate(() => (window as any).fetchCalls.filter((call: any) => call.url.includes('/markets/1/workspace')).every((call: any) => call.signal.aborted))).toBe(true);
  await pending[1]();
  await page.clock.runFor(60_000);
  expect(await page.evaluate(() => (window as any).fetchCalls.some((call: any) => call.url.includes('/token/yes-1')))).toBe(false);
});

test('market dossier cancels a hidden book and recovers with the correct identity', async ({ page }) => {
  await trackRequests(page);
  let reply: (() => Promise<void>) | undefined;
  await page.route('**/wm-api/**', route => {
    const path = new URL(route.request().url()).pathname;
    if (path.includes('/token/')) { reply = () => route.fulfill({ json: fixtureBundle(1).lob }).catch(() => {}); return; }
    return route.fulfill({ json: path.includes('/runtime/lob/') ? fixtureBundle(1).lob : fixtureBundle(1) });
  });
  await harness(page, 'dossier');
  await expect.poll(() => Boolean(reply)).toBe(true);
  await hidden(page, true);
  expect(await page.evaluate(() => (window as any).fetchCalls.find((call: any) => call.url.includes('/token/')).signal.aborted)).toBe(true);
  await reply!(); reply = undefined;
  await page.clock.runFor(60_000);
  expect(reply).toBeUndefined();
  await hidden(page, false);
  await expect.poll(() => Boolean(reply)).toBe(true);
  await reply!();
  await expect.poll(() => page.evaluate(() => window.frontendHarness.dossier!.bundle?.lob?.yes?.tokenId)).toBe('yes-1');
  await page.evaluate(() => window.frontendHarness.unmount());
});

test('registered analysis snapshots refresh independently and pause when hidden', async ({ page }) => {
  const requested: string[] = [];
  await page.route('**/wm-api/runtime/agent/market-wide-insights/**', route => {
    const lens = route.request().url().split('/').pop()!;
    requested.push(lens);
    return route.fulfill({ json: { lens, status: 'live', generationMode: 'ai', model: 'fixture', generatedAt: GENERATED_AT,
      brief: 'Snapshot', focus: [], specialMarkets: [], themes: [], watchlist: [], evidence: [] } });
  });
  await harness(page, 'registered-runtime');
  await expect.poll(() => page.evaluate(() => Object.keys(window.frontendHarness.runtime!.runtimeData).sort()))
    .toEqual(['oracle-timeline', 'price-implications', 'sample-chain-trades']);
  expect(requested.sort()).toEqual(['overview', 'special', 'trend']);
  await page.evaluate(() => window.frontendHarness.setPanels(['oracle-timeline']));
  await page.clock.runFor(60_000);
  await expect.poll(() => requested.length).toBe(4);
  expect(requested[3]).toBe('trend');
  await page.evaluate(() => window.frontendHarness.runtime!.setPanelVisible('oracle-timeline', false));
  await page.clock.runFor(600_000);
  expect(requested).toHaveLength(4);
  await page.evaluate(() => window.frontendHarness.unmount());
});

test('FIRMS rejects the previous viewport response and aborts on unmount', async ({ page }) => {
  await trackRequests(page, 'source=firms');
  await installFixtures(page);
  await harness(page, 'hazards');
  await expect.poll(() => page.evaluate(() => window.frontendHarness.hazards!.loading)).toBe(false);
  const initialIds = await page.evaluate(() => window.frontendHarness.hazards!.events.map(event => event.id));
  const pending: Array<() => Promise<void>> = [];
  await page.route('**/wm-api/runtime/world/natural-hazards/map?**', route => {
    if (new URL(route.request().url()).searchParams.get('source') !== 'firms') return route.fallback();
    pending.push(() => route.fulfill({ json: { schemaVersion: 'natural-hazards-map.v1', generatedAt: GENERATED_AT,
      events: [], sources: [{ key: 'firms', status: 'ok' }], errors: [], counts: { events: 0 } } }).catch(() => {}));
  });
  await page.evaluate(() => window.frontendHarness.setHazardView({ center: [70, 43] }));
  await page.clock.runFor(100);
  await expect.poll(() => pending.length).toBe(1);
  await page.evaluate(() => window.frontendHarness.setHazardView({ center: [90, 43] }));
  await page.clock.runFor(100);
  await expect.poll(() => pending.length).toBe(2);
  expect((await hazardCalls(page))[5].aborted).toBe(true);
  await pending[0]();
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.hazards!.events.map(event => event.id))).toEqual(initialIds);
  await page.evaluate(() => window.frontendHarness.unmount());
  expect((await hazardCalls(page))[6].aborted).toBe(true);
  await pending[1]();
  await page.clock.runFor(600_000);
  expect(await hazardCalls(page)).toHaveLength(7);
});

const geometryCalls = (page: Page) => page.evaluate(() => (window as any).fetchCalls
  .filter((call: any) => call.url.includes('/map-data/world-countries.geojson'))
  .map((call: any) => ({ aborted: call.signal?.aborted })));

test('country geometry cancels demand without poisoning the cache with a late response', async ({ page }) => {
  await trackRequests(page, '/map-data/world-countries.geojson');
  const { readFileSync } = await import('node:fs');
  const collection = JSON.parse(readFileSync(new URL('../public/map-data/world-countries.geojson', import.meta.url), 'utf8'));
  // Use the committed real geometry, not synthetic product coordinates.
  const json = { ...collection, features: collection.features.filter((f: any) => f.properties['ISO3166-1-Alpha-2'] === 'NZ') };
  const pending: Array<() => Promise<void>> = [];
  await harness(page, 'geometry');
  await page.route('**/map-data/world-countries.geojson', route => {
    pending.push(() => route.fulfill({ json }).catch(() => {}));
  });
  expect(await geometryCalls(page)).toEqual([]);
  await page.evaluate(() => window.frontendHarness.setGeometryEnabled(true));
  await page.clock.runFor(100);
  await expect.poll(() => pending.length).toBe(1);
  await page.evaluate(() => window.frontendHarness.setGeometryEnabled(false));
  await page.clock.runFor(100);
  expect(await geometryCalls(page)).toEqual([{ aborted: true }]);
  await pending[0]();
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.geometry)).toMatchObject({ index: null, error: null, loading: false });
  await page.evaluate(() => window.frontendHarness.setGeometryEnabled(true));
  await page.clock.runFor(100);
  await expect.poll(() => pending.length).toBe(2);
  await pending[1]();
  await expect.poll(() => page.evaluate(() => window.frontendHarness.geometry?.index?.countries.length)).toBe(1);
  await page.evaluate(() => window.frontendHarness.setGeometryEnabled(false));
  await page.clock.runFor(100);
  await page.evaluate(() => window.frontendHarness.setGeometryEnabled(true));
  await page.clock.runFor(100);
  expect(await geometryCalls(page)).toHaveLength(2);
  expect(await page.evaluate(() => window.frontendHarness.geometry?.index?.resolve('NZ')?.iso2)).toBe('NZ');
});

test('country geometry reports a real timeout, then cancels a fresh attempt on unmount', async ({ page }) => {
  await trackRequests(page);
  await harness(page, 'geometry');
  await page.route('**/map-data/world-countries.geojson', () => {});
  await page.evaluate(() => window.frontendHarness.setGeometryEnabled(true));
  await page.clock.runFor(100);
  await expect.poll(async () => (await geometryCalls(page)).length).toBe(1);
  await page.clock.runFor(6000);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.geometry?.error)).toBe('Country geometry timed out after 6s.');
  expect(await geometryCalls(page)).toEqual([{ aborted: true }]);
  await page.evaluate(() => window.frontendHarness.setGeometryEnabled(false));
  await page.clock.runFor(100);
  await page.evaluate(() => window.frontendHarness.setGeometryEnabled(true));
  await page.clock.runFor(100);
  await expect.poll(async () => (await geometryCalls(page)).length).toBe(2);
  await page.evaluate(() => window.frontendHarness.unmount());
  await page.clock.runFor(20_000);
  expect(await geometryCalls(page)).toEqual([{ aborted: true }, { aborted: true }]);
});

test('shared runtime aborts analysis snapshot requests on unmount', async ({ page }) => {
  await trackRequests(page);
  await page.route('**/wm-api/runtime/agent/market-wide-insights/**', () => {});
  await harness(page, 'registered-runtime');
  const snapshotCalls = () => page.evaluate(() => (window as any).fetchCalls
    .filter((call: any) => call.url.includes('/market-wide-insights/')).map((call: any) => call.signal?.aborted));
  await expect.poll(snapshotCalls).toEqual([false, false, false]);
  await page.evaluate(() => window.frontendHarness.unmount());
  await expect.poll(snapshotCalls).toEqual([true, true, true]);
});


test('aircraft refresh retains last good data, cancels hidden/unmounted requests and ignores an old viewport', async ({ page }) => {
  const response = (generatedAt:string) => ({schemaVersion:'aviation-viewport.v1',status:'empty',source:'Controlled lifecycle fixture',generatedAt,aircraft:[],aircraftCount:0,availableAircraftCount:0,bbox:[40,20,80,60],zoom:3,coverage:{complete:true}});
  const nextStamp='2026-08-26T03:02:00Z';
  let calls = 0;
  const held: Array<import('@playwright/test').Route> = [];
  await page.route('**/runtime/transport/aviation-viewport?**', async route => {
    calls++;
    if (calls === 1) await route.fulfill({ json: response(GENERATED_AT) });
    else if (calls === 2) await route.fulfill({ status: 503, json: { error: 'provider unavailable' } });
    else held.push(route);
  });
  await harness(page, 'aviation');
  await expect.poll(() => page.evaluate(() => window.frontendHarness.aviation?.payload?.generatedAt)).toBe(GENERATED_AT);
  await page.clock.runFor(30_200);
  await expect.poll(() => page.evaluate(() => window.frontendHarness.aviation?.error)).toBeTruthy();
  expect(await page.evaluate(() => window.frontendHarness.aviation?.payload?.generatedAt)).toBe(GENERATED_AT);
  await page.clock.runFor(60_200);
  await expect.poll(() => held.length).toBe(1);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  const hiddenCalls = calls;
  await page.clock.runFor(90_000);
  expect(calls).toBe(hiddenCalls);
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await page.clock.runFor(400);
  await expect.poll(() => held.length).toBe(2);
  await page.evaluate(() => window.frontendHarness.setAviationView({ center: [115, 35] }));
  await page.clock.runFor(400);
  await expect.poll(() => held.length).toBe(3);
  await held[2]!.fulfill({ json: response(nextStamp) });
  await held[1]!.fulfill({ json: response(GENERATED_AT) }).catch(() => {});
  await held[0]!.fulfill({ json: response(GENERATED_AT) }).catch(() => {});
  await expect.poll(() => page.evaluate(() => window.frontendHarness.aviation?.payload?.generatedAt)).toBe(nextStamp);
  await page.evaluate(() => window.frontendHarness.unmount());
  const stoppedCalls = calls;
  await page.clock.runFor(90_000);
  expect(calls).toBe(stoppedCalls);
});
