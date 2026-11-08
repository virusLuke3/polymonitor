import { expect, test, type Page } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { installLocalAssets } from './fixtures/browser';
import { GENERATED_AT } from './fixtures/world-event-map';
import type {} from './fixtures/lifecycle';

test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });
const start = Date.parse(GENERATED_AT);

async function mountCached(page: Page, time = start) {
  await page.goto('/e2e/lifecycle.html');
  await page.waitForFunction(() => Boolean(window.frontendHarness));
  await page.clock.install({ time: new Date(time) });
  await page.evaluate(() => window.frontendHarness.mount('cached-runtime'));
  await page.clock.runFor(100);
}

test('reload restores source/check time before any request; manual refresh still replaces with authoritative empty', async ({ page }) => {
  await installLocalAssets(page);
  await mountCached(page);
  await page.evaluate(generatedAt => window.frontendHarness.requests[0].resolve({ generatedAt, items: ['saved'] }), GENERATED_AT);
  await page.clock.runFor(100);
  const checked = await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').checkedAt);
  await mountCached(page, start + 1000);
  expect(await page.evaluate(() => window.frontendHarness.requests.length)).toBe(0);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getData('shared'))).toMatchObject({ items: ['saved'], generatedAt: GENERATED_AT });
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared'))).toMatchObject({ phase: 'ready', checkedAt: checked, cacheMode: 'browser' });
  await page.evaluate(() => { void window.frontendHarness.runtime!.refreshIds(['shared'], { reason: 'manual', force: true }); });
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.requests.length)).toBe(1);
  await page.evaluate(() => window.frontendHarness.requests[0].resolve({ generatedAt: new Date().toISOString(), status: 'empty', items: [] }));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getData('shared'))).toMatchObject({ items: [] });
});

test('stale reload keeps content through refresh failure then expires at the original retention limit', async ({ page }) => {
  await installLocalAssets(page);
  await mountCached(page);
  await page.evaluate(generatedAt => window.frontendHarness.requests[0].resolve({ generatedAt, items: ['saved'] }), GENERATED_AT);
  await page.clock.runFor(100);
  await mountCached(page, start + 35_000);
  expect(await page.evaluate(() => window.frontendHarness.requests.length)).toBe(1);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').phase)).toBe('stale');
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getData('shared'))).toMatchObject({ items: ['saved'] });
  await page.evaluate(() => window.frontendHarness.requests[0].reject(new Error('offline')));
  await page.clock.runFor(100);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getData('shared'))).toMatchObject({ generatedAt: GENERATED_AT });
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getStatus('shared').phase)).toBe('degraded');
  await page.clock.runFor(56_000);
  expect(await page.evaluate(() => window.frontendHarness.runtime!.getData('shared'))).toBeUndefined();
});

for (const width of [1440, 390]) test(`cached NBA and DeFi remain visible during slow bootstrap at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  await installDashboard(page, 'en', ['nba-scoreboard', 'defi-token-watch']);
  const values = {
    'nba-scoreboard': { generatedAt: GENERATED_AT, status: 'ok', items: [{ id: 'game', homeTeam: 'Home fixture', awayTeam: 'Away fixture', homeScore: 42, awayScore: 41 }] },
    'defi-token-watch': { generatedAt: GENERATED_AT, status: 'ok', items: [{ id: 'uniswap', name: 'Uniswap', symbol: 'UNI', price: 7.25, change24h: 1, change7d: 2 }] },
  };
  let requests = 0;
  await page.route('**/wm-api/**', route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/v1/runtime/panels') && (url.searchParams.get('ids') || '').split(',').some(id => id in values)) {
      requests++;
      return route.fulfill({ json: { apiVersion: 'v1', status: 'ok', data: { panels: values }, meta: { panels: {} }, errors: [] } });
    }
    const id = url.pathname.endsWith('/sports/nba') ? 'nba-scoreboard' : url.pathname.endsWith('/finance/defi-token-watch') ? 'defi-token-watch' : null;
    if (id) { requests++; return route.fulfill({ json: values[id] }); }
    return route.fallback();
  });
  await page.goto('/');
  for (const id of Object.keys(values)) {
    const slot = page.locator(`[data-workspace-panel-id="${id}"]`);
    await slot.scrollIntoViewIfNeeded();
    await expect(slot).toContainText(id === 'nba-scoreboard' ? 'Home fixture' : 'UNI');
  }
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('polymonitor:panel-resource:public-feed:')).length)).toBe(2);
  const before = requests;
  const layout = await page.evaluate(() => localStorage.getItem('polydata:workspace-panels:v4'));
  let release!: () => void;
  const gate = new Promise<void>(resolve => { release = resolve; });
  await page.route('**/wm-api/bootstrap', async route => { await gate; await route.fallback(); });
  try {
    await page.reload({ waitUntil: 'domcontentloaded' });
    for (const id of Object.keys(values)) {
      const slot = page.locator(`[data-workspace-panel-id="${id}"]`);
      await slot.scrollIntoViewIfNeeded();
      await expect(slot).toContainText(id === 'nba-scoreboard' ? 'Home fixture' : 'UNI');
      await expect(slot.locator('.wm-panel-slot-loading')).toHaveCount(0);
    }
    expect(requests).toBe(before);
    expect(await page.evaluate(() => localStorage.getItem('polydata:workspace-panels:v4'))).toBe(layout);
  } finally { release(); }
});
