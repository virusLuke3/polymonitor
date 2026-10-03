import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

test('crypto checks every 5s, publishes changed prices, preserves outages and restores validated cache', async ({ page }) => {
  await installDashboard(page, 'en', ['crypto-watch']);
  await page.clock.install({ time: new Date(GENERATED_AT) });
  let price = 110, requests = 0, fail = false;
  await page.route('**/wm-api/runtime/markets/crypto', async route => {
    requests++;
    if (fail) return route.fulfill({ status: 503, json: { error: 'Fixture outage' } });
    const generatedAt = await page.evaluate(() => new Date().toISOString());
    return route.fulfill({ json: { kind: 'crypto', status: 'ok', generatedAt, items: [
      { id: 'btc', label: 'BITCOIN', symbol: 'BTC-USD', price, changePercent: 10, changeBasis: 'rolling-24h', quoteAt: generatedAt, fetchedAt: generatedAt, points: [] },
    ] } });
  });
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(() => window.panelHarness);
  await page.evaluate(() => window.panelHarness.mount('crypto-watch'));
  const btc = page.locator('[data-crypto-symbol="BTC-USD"]');
  await expect(btc).toContainText('$110.00');
  price = 120;
  await page.clock.runFor(6000);
  await expect(btc).toContainText('$120.00');
  expect(requests).toBeGreaterThanOrEqual(2);
  const checked = await page.locator('[data-crypto-checked-at]').getAttribute('datetime');
  fail = true;
  await page.clock.runFor(6000);
  await expect(btc).toContainText('$120.00');
  await expect(page.locator('.wm-crypto-notice')).toContainText('retrying automatically');
  expect(await page.locator('[data-crypto-checked-at]').getAttribute('datetime')).toBe(checked);
  fail = false; price = 130;
  await page.clock.runFor(6000);
  await expect(btc).toContainText('$130.00');
  const before = requests;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => requests).toBeGreaterThan(before);
  fail = true;
  await page.evaluate(() => window.panelHarness.mount('crypto-watch'));
  await expect(btc).toContainText('$130.00');
  await page.clock.fastForward(16 * 60_000);
  await expect(btc).toHaveCount(0); // no unlimited stale prices
});

for (const width of [1440, 390]) test(`crypto loads autonomously with visible prices at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 844 });
  await installDashboard(page, 'en', ['crypto-watch']);
  await page.route('**/wm-api/runtime/markets/crypto', route => route.fulfill({ json: {
    kind: 'crypto', status: 'ok', generatedAt: GENERATED_AT, items: [{ id: 'btc', label: 'BITCOIN', symbol: 'BTC-USD', price: 84000, quoteAt: GENERATED_AT, fetchedAt: GENERATED_AT, points: [] }],
  } }));
  await page.goto('/');
  const slot = page.locator('.wm-panel-slot[data-workspace-panel-id="crypto-watch"]');
  await slot.scrollIntoViewIfNeeded();
  await expect(slot.locator('[data-crypto-symbol="BTC-USD"]')).toContainText('$84,000');
  await slot.locator('[data-crypto-symbol="BTC-USD"]').scrollIntoViewIfNeeded();
  await expect(slot.locator('.wm-crypto-market-value').first()).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
