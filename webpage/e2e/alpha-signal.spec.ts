import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

test('mobile Alpha reserves space before deferred content and loads when scrolled into view', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installDashboard(page, 'en', ['alpha-signal']);
  let requests = 0;
  await page.route('**/wm-api/runtime/signals/smart-money?*', route => {
    requests++;
    const item = { id: 'mobile-alpha', title: 'Mobile matched trade', eventSlug: 'matched-trade',
      side: 'BUY', outcome: 'Up',
      amountUsdc: '150', averagePrice: '.62', fragments: 2, tradedAt: GENERATED_AT, tags: ['CRYPTO · B1'] };
    return route.fulfill({ json: { source: 'matched-trades-v2', status: 'ok', generatedAt: GENERATED_AT,
      sourceObservedAt: GENERATED_AT, items: [item] } });
  });
  await page.goto('/');
  const slot = page.locator('.wm-panel-slot[data-workspace-panel-id="alpha-signal"]');
  await expect(slot).toBeAttached();
  await expect.poll(() => slot.evaluate(element => element.getBoundingClientRect().height)).toBeGreaterThan(0);
  await slot.scrollIntoViewIfNeeded();
  await expect(slot.getByRole('link', { name: 'Mobile matched trade' })).toBeVisible();
  expect(requests).toBeGreaterThan(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
