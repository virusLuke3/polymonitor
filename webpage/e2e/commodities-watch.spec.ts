import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

test('commodity resource applies automatic changes, preserves outages and restores cached quotes', async ({ page }) => {
  await installDashboard(page, 'en', ['commodities-watch']);
  await page.clock.install({ time: new Date(GENERATED_AT) });
  let price = 2400, requests = 0, fail = false;
  await page.route('**/wm-api/runtime/markets/commodities', async route => {
    requests++;
    if (fail) return route.fulfill({ status: 503, json: { error: 'Fixture outage' } });
    const generatedAt = await page.evaluate(() => new Date().toISOString());
    return route.fulfill({ json: { kind: 'commodities', status: 'ok', generatedAt, items: [
      { id: 'gold', label: 'GOLD', symbol: 'GC=F', price, currency: 'USD', changePercent: 1.5, changeBasis: 'previous-close', marketState: 'closed', quoteAt: GENERATED_AT, fetchedAt: generatedAt, points: [] },
      { id: 'eurusd', label: 'EUR/USD', symbol: 'EURUSD=X', price: 1.1762, currency: 'USD', changePercent: null, changeBasis: 'unknown', marketState: 'closed', quoteAt: GENERATED_AT, fetchedAt: generatedAt, points: [] },
    ] } });
  });
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(() => window.panelHarness);
  await page.evaluate(() => window.panelHarness.mount('commodities-watch'));
  const gold = page.locator('[data-commodity-symbol="GC=F"]');
  await expect(gold).toContainText('$2,400.00');
  await expect(page.locator('.wm-commodity-coverage')).toContainText('2/33');
  price = 2410;
  await page.clock.runFor(21_000);
  await expect(gold).toContainText('$2,410.00');
  expect(requests).toBeGreaterThanOrEqual(2);
  const checked = await page.locator('[data-commodity-checked-at]').getAttribute('datetime');
  fail = true;
  await page.clock.runFor(21_000);
  await expect(gold).toContainText('$2,410.00');
  await expect(page.locator('.wm-commodity-notice')).toContainText('retrying automatically');
  expect(await page.locator('[data-commodity-checked-at]').getAttribute('datetime')).toBe(checked);
  fail = false; price = 2420;
  await page.clock.runFor(5000);
  await expect(gold).toContainText('$2,420.00'); // no manual refresh needed
  const before = requests;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => requests).toBeGreaterThan(before);
  await page.getByRole('tab', { name: 'FX' }).click();
  await expect(page.locator('[data-commodity-symbol="EURUSD=X"]')).toContainText('1.1762');
  fail = true;
  await page.evaluate(() => window.panelHarness.mount('commodities-watch'));
  await expect(gold).toContainText('$2,420.00');
  expect(await page.evaluate(() => localStorage.getItem('polymonitor:panel-resource:commodities:global:previous-close:v3'))).toContain('2420');
});

test('mobile commodity quotes load autonomously when scrolled into view', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installDashboard(page, 'en', ['commodities-watch']);
  await page.route('**/wm-api/runtime/markets/commodities', route => route.fulfill({ json: {
    kind: 'commodities', status: 'ok', generatedAt: GENERATED_AT, items: [{ id: 'ttf', label: 'TTF GAS', symbol: 'TTF=F', price: 76.5, currency: 'EUR', marketState: 'closed', quoteAt: GENERATED_AT, fetchedAt: GENERATED_AT, points: [] }],
  } }));
  await page.goto('/');
  const slot = page.locator('.wm-panel-slot[data-workspace-panel-id="commodities-watch"]');
  await expect(slot).toBeAttached();
  await slot.scrollIntoViewIfNeeded();
  await expect(slot.locator('[data-commodity-symbol="TTF=F"]')).toContainText('€76.50');
  await expect(slot.locator('[data-commodity-checked-at]')).toBeAttached();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
