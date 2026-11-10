import { expect, test, type Page } from '@playwright/test';
import { installLocalAssets } from './fixtures/browser';
import { fixtureBundle, fixtureMarkets } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
import type {} from './fixtures/lifecycle';

test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });
async function mount(page: Page, kind: Parameters<Window['frontendHarness']['mount']>[0]) {
  await installLocalAssets(page);
  await page.goto('/e2e/lifecycle.html');
  await page.waitForFunction(() => Boolean(window.frontendHarness));
  await page.clock.install({ time: new Date(GENERATED_AT) });
  await page.evaluate(kind => window.frontendHarness.mount(kind), kind);
  await page.clock.runFor(200);
}
const count = (page: Page) => page.evaluate(() => window.frontendHarness.requests.length);
async function visible(page: Page, value: boolean) {
  await page.evaluate(hidden => {
    Object.defineProperty(document, 'hidden', { configurable: true, value: hidden });
    document.dispatchEvent(new Event('visibilitychange'));
  }, !value);
  await page.clock.runFor(100);
}

test('fifteen-minute resources recover on the WorldMonitor retry sequence and publish immediately', async ({ page }) => {
  await mount(page, 'recovery-runtime');
  for (const [i, base] of [15_000, 30_000, 60_000, 120_000, 180_000, 180_000].entries()) {
    await page.evaluate(() => window.frontendHarness.requests.at(-1)!.reject(new TypeError('offline')));
    await page.clock.runFor(100);
    const delay = await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').nextRetryAt! - Date.now());
    expect(delay).toBeGreaterThan(base - 200);
    expect(delay).toBeLessThanOrEqual(base * 1.1);
    await page.clock.runFor(delay + 200);
    expect(await count(page)).toBe(i + 2);
  }
  await page.evaluate(() => window.frontendHarness.requests.at(-1)!.resolve({ generatedAt: new Date().toISOString(), items: ['recovered'] }));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getData('shared'))).toMatchObject({ items: ['recovered'] });
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared')))
    .toMatchObject({ phase: 'ready', error: null, failureCount: 0, fetching: false });
  await page.clock.runFor(200_000);
  expect(await count(page)).toBe(7); // Old failure timer cannot fire after recovery.
});

test('a failed cold read keeps its error visible while automatic recovery is pending', async ({ page }) => {
  await mount(page, 'recovery-runtime');
  await page.evaluate(() => window.frontendHarness.requests[0].reject(new Error('network failed')));
  await page.clock.runFor(17_000);
  expect(await count(page)).toBe(2);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared')))
    .toMatchObject({ phase: 'error', fetching: true, error: 'network failed' });
});

test('returning to the tab recovers failures without reload or overlapping probes', async ({ page }) => {
  await mount(page, 'recovery-runtime');
  await page.evaluate(() => window.frontendHarness.requests[0].reject(new Error('network failed')));
  await page.clock.runFor(2000);
  await visible(page, false);
  await page.clock.runFor(2000);
  expect(await count(page)).toBe(1);
  await visible(page, true);
  await page.clock.runFor(200);
  expect(await count(page)).toBe(2);
  await page.evaluate(() => { window.dispatchEvent(new Event('online')); window.dispatchEvent(new Event('online')); });
  await visible(page, true);
  expect(await count(page)).toBe(2);
  await page.evaluate(() => window.frontendHarness.requests[1].resolve({ generatedAt: new Date().toISOString(), items: ['visible'] }));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').error)).toBeNull();
});

test('warming after a failed check preserves evidence and cannot create an immediate retry loop', async ({ page }) => {
  await mount(page, 'recovery-runtime');
  await page.evaluate(generatedAt => window.frontendHarness.requests[0].resolve({ generatedAt, items: ['kept'] }), GENERATED_AT);
  await page.clock.runFor(100);
  const checkedAt = await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').checkedAt);
  await page.evaluate(() => { void window.frontendHarness.runtime!.refreshIds(['shared']); });
  await page.evaluate(() => window.frontendHarness.requests[1].reject(new Error('unavailable')));
  await page.clock.runFor(17_000);
  expect(await count(page)).toBe(3);
  await page.evaluate(() => window.frontendHarness.requests[2].resolve({ status: 'warming', generatedAt: new Date().toISOString(), items: [] }));
  await page.clock.runFor(1000);
  expect(await count(page)).toBe(3);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared')))
    .toMatchObject({ checkedAt, error: 'unavailable', failureCount: 1, fetching: false });
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getData('shared'))).toMatchObject({ items: ['kept'] });
  await page.clock.runFor(15_000);
  expect(await count(page)).toBe(4);
});

test('Retry-After survives visible, online and manual retry, while permanent errors stay stopped', async ({ page }) => {
  await mount(page, 'recovery-runtime');
  await page.evaluate(() => window.frontendHarness.rejectHttp(0, 429, '120'));
  await page.clock.runFor(2000);
  await visible(page, false);
  await visible(page, true);
  await page.evaluate(() => {
    window.dispatchEvent(new Event('online'));
    void window.frontendHarness.runtime!.refreshIds(['shared'], { reason: 'manual', force: true });
  });
  const deadline = await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').retryAfterAt!);
  const remaining = await page.evaluate(deadline => deadline - Date.now(), deadline);
  await page.clock.runFor(remaining - 2000);
  expect(await count(page)).toBe(1);
  await page.clock.runFor(2500);
  expect(await count(page)).toBe(2);
  expect(await page.evaluate(() => window.frontendHarness.requests[1].startedAt)).toBeGreaterThanOrEqual(deadline);
  await page.evaluate(() => window.frontendHarness.rejectHttp(1, 400));
  await page.clock.runFor(2000);
  await visible(page, false);
  await visible(page, true);
  await page.evaluate(() => window.dispatchEvent(new Event('online')));
  await page.clock.runFor(900_000);
  expect(await count(page)).toBe(2);
});

test('catalog survives freshness expiry and failed refresh, then replaces immediately and accepts empty', async ({ page }) => {
  let pending: (() => Promise<void>) | undefined;
  let reads = 0;
  let mode: 'initial' | 'failed' | 'recovered' | 'empty' = 'initial';
  await page.route('**/wm-api/markets?**', async route => {
    reads++;
    if (mode === 'failed') { pending = () => route.fulfill({ status: 502, body: 'unavailable' }); return; }
    const generatedAt = mode === 'initial' ? GENERATED_AT : await page.evaluate(() => new Date().toISOString());
    await route.fulfill({ json: { generatedAt, items: mode === 'empty' ? [] : [{ ...fixtureMarkets[0], title: mode }],
      pagination: { page: 1, pageSize: 50 }, sort: 'volume' } });
  });
  await mount(page, 'catalog');
  await expect(page.locator('output')).toHaveText('initial');
  mode = 'failed';
  await page.clock.runFor(300_500);
  await expect.poll(() => Boolean(pending)).toBe(true);
  await expect(page.locator('output')).toHaveText('initial');
  expect(await page.evaluate(() => window.frontendHarness.catalog!.marketCatalogError)).toBeTruthy();
  await pending!();
  await page.clock.runFor(200);
  expect(await page.evaluate(() => window.frontendHarness.catalog!.markets[0].catalogFetchedAt)).toBe(GENERATED_AT);
  mode = 'recovered';
  await page.clock.runFor(17_000);
  await expect(page.locator('output')).toHaveText('recovered');
  expect(await page.evaluate(() => window.frontendHarness.catalog!.marketCatalogError)).toBeNull();
  mode = 'empty';
  await page.clock.runFor(301_000);
  await expect(page.locator('output')).toHaveText('');
  expect(reads).toBe(4);
});

test('catalog hard expiry cannot resurrect the original bootstrap preview', async ({ page }) => {
  let reads = 0;
  await page.route('**/wm-api/markets?**', async route => {
    if (++reads > 1) { await route.fulfill({ status: 502, body: 'unavailable' }); return; }
    await route.fulfill({ json: { generatedAt: GENERATED_AT, items: [{ ...fixtureMarkets[0], title: 'retained catalog' }],
      pagination: { page: 1, pageSize: 50 }, sort: 'volume' } });
  });
  await mount(page, 'catalog');
  await expect(page.locator('output')).toHaveText('retained catalog');
  await page.clock.runFor(901_000);
  await expect(page.locator('output')).toHaveText('');
  expect(await page.evaluate(() => window.frontendHarness.catalog!.marketCatalogError)).toBeTruthy();
});

test('a slow catalog can finish beyond ten seconds without a duplicate read', async ({ page }) => {
  let release: (() => Promise<void>) | undefined;
  let reads = 0;
  await page.route('**/wm-api/markets?**', route => {
    reads++;
    release = () => route.fulfill({ json: { generatedAt: GENERATED_AT, items: [{ ...fixtureMarkets[0], title: 'slow catalog' }],
      pagination: { page: 1, pageSize: 50 }, sort: 'volume' } });
  });
  await mount(page, 'catalog');
  await expect.poll(() => Boolean(release)).toBe(true);
  await page.clock.runFor(20_000);
  expect(reads).toBe(1);
  expect(await page.evaluate(() => window.frontendHarness.catalog!.marketCatalogRefreshing)).toBe(true);
  await release!();
  await expect(page.locator('output')).toHaveText('slow catalog');
  expect(await page.evaluate(() => window.frontendHarness.catalog!.marketCatalogError)).toBeNull();
});

for (const userOverride of [false, true]) {
  test(`404 during an empty catalog preserves selection and respects user deselection (${userOverride})`, async ({ page }) => {
    let missing: (() => Promise<void>) | undefined;
    await page.route('**/wm-api/**', async route => {
      const url = new URL(route.request().url());
      const id = Number(url.pathname.match(/markets\/(\d+)/)?.[1] || 1);
      if (id === 1 && url.pathname.endsWith('/focus-tile')) {
        missing = () => route.fulfill({ status: 404, json: { error: 'missing' } }); return;
      }
      const bundle = fixtureBundle(id);
      await route.fulfill({ json: url.pathname.endsWith('/chart') ? { ...bundle.chart, range: url.searchParams.get('range') } : bundle });
    });
    await mount(page, 'focus');
    await expect.poll(() => Boolean(missing)).toBe(true);
    await page.evaluate(() => window.frontendHarness.setFocusMarkets([]));
    await page.clock.runFor(100);
    await missing!();
    await page.clock.runFor(200);
    expect(await page.evaluate(() => window.frontendHarness.focus!.selectedMarketId)).toBe(1);
    if (userOverride) await page.evaluate(() => window.frontendHarness.focus!.setSelectedMarketId(null));
    await page.evaluate(markets => window.frontendHarness.setFocusMarkets(markets), [fixtureMarkets[1]]);
    await page.clock.runFor(300);
    expect(await page.evaluate(() => window.frontendHarness.focus!.selectedMarketId)).toBe(userOverride ? null : 2);
    if (!userOverride) await expect.poll(() => page.evaluate(() => window.frontendHarness.focus!.bundle?.market?.id)).toBe(2);
  });
}
