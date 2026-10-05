import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';

test('selected-city books refresh every 15s, clear failed ladders and recover', async ({ page }) => {
  await installDashboard(page, 'en', ['weather-quote-table']);
  await page.clock.install({ time: new Date() });
  let state = 'warming', requests = 0;
  await page.route('**/wm-api/runtime/lob/token/**', async route => {
    requests++;
    if (state === 'error') return route.fulfill({ status: 503, json: { error: 'Fixture outage' } });
    const now = Number(new URL(route.request().url()).searchParams.get('_ts'));
    const live = state === 'live';
    return route.fulfill({ json: { marketId: 1, bookStatus: state, yes: { tokenId: '123', bookStatus: state,
      continuity: live, receivedAt: new Date(now - 1000).toISOString(), heartbeatAt: new Date(now).toISOString(), staleAfter: new Date(now + 20_000).toISOString(),
      bids: live ? [{ price: '.3', size: 100 }] : [], asks: live ? [{ price: '.4', size: 100 }] : [] } } });
  });
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(() => window.panelHarness);
  await page.evaluate(() => window.panelHarness.mount('weather-quote-table', { 'global-temperature-monitor': {
    status: 'ok', items: [{ cityId: 'new-york', city: 'New York', marketDate: '2026-10-06', bins: [{ label: '70°F', yesTokenId: '123', bookStatus: 'not-queried' }] }],
  } }));
  const table = page.locator('.wm-weather-quote-table');
  await expect(table).toContainText('WARMING');
  state = 'live'; await page.clock.runFor(16_000);
  await expect(table).toContainText('CLOB MID');
  await expect(table.locator('td').nth(1)).toHaveText('30%');
  expect(requests).toBeGreaterThanOrEqual(2);
  state = 'error'; await page.clock.runFor(16_000);
  await expect(table).toContainText('ERROR');
  await expect(table.locator('td').nth(1)).toHaveText('--');
  state = 'live'; await page.clock.runFor(16_000);
  await expect(table).toContainText('CLOB MID');
  const before = requests;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => requests).toBeGreaterThan(before);
});
