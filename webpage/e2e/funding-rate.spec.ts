import { test, expect } from '@playwright/test';
import { installDashboard } from './fixtures/dashboard';
import { GENERATED_AT } from './fixtures/world-event-map';
test.use({ baseURL: `http://127.0.0.1:${process.env.POLYMONITOR_E2E_PORT || 4174}` });

function snapshot(generatedAt: string, rate: number) {
  const assets = ['BTC', 'HYPE'].map(asset => ({ id: asset, asset, marketCount: 2, priceMarketCount: 2,
    relatedMarkets: [{ id: asset, title: `${asset} above $100?`, url: `https://polymarket.com/event/${asset.toLowerCase()}-price`, endAt: '2027-01-01T00:00:00Z', relation: 'price-asset' }],
    quotes: ['Binance', 'Bybit'].map(exchange => ({ id: `${exchange.toLowerCase()}:${asset}USDT`, asset, symbol: `${asset}USDT`, exchange,
      fundingRate: rate, fundingRatePercent: rate * 100, fundingIntervalHours: 8,
      eligible: true, contractType: 'perpetual', contractStatus: exchange === 'Binance' ? 'TRADING' : 'Trading', settleCoin: 'USDT',
      updatedAt: generatedAt, fetchedAt: generatedAt, eligibilityCheckedAt: generatedAt,
      quoteObservedAt: exchange === 'Binance' ? generatedAt : null, sourceResponseAt: exchange === 'Bybit' ? generatedAt : null,
      nextFundingTime: new Date(Date.parse(generatedAt) + 3_600_000).toISOString(), acquisitionState: 'ok' })) }));
  return { kind: 'crypto-funding', schemaVersion: 3, generatedAt, status: 'ok', refreshIntervalSeconds: 30,
    sources: { binance: 'ok', bybit: 'ok' }, assets, coverage: { expectedQuotes: 4, succeeded: 4 },
    marketUniverse: { status: 'ok', observedAt: generatedAt, scannedEvents: 2 } };
}

test('funding autonomously publishes new snapshots, retains failures, restores cache and recovers', async ({ page }) => {
  await installDashboard(page, 'en', ['crypto-funding-watch']);
  await page.clock.install({ time: new Date(GENERATED_AT) });
  let rate = -0.0004, requests = 0, fail = false;
  await page.route('**/wm-api/runtime/crypto/funding-watch?*', async route => {
    requests++;
    if (fail) return route.fulfill({ status: 503, json: { error: 'Funding fixture outage' } });
    const generatedAt = await page.evaluate(() => new Date().toISOString());
    return route.fulfill({ json: snapshot(generatedAt, rate) });
  });
  await page.goto('/e2e/panels.html');
  await page.waitForFunction(() => window.panelHarness);
  await page.evaluate(() => window.panelHarness.mount('crypto-funding-watch'));
  const btc = page.locator('[data-funding-asset="BTC"]');
  await expect(btc.locator('[data-funding-strongest]')).toHaveText('-0.0400%');
  await expect(btc).toContainText('SHORTS PAY');
  await expect(btc).toContainText('Response time');
  const firstClock = await page.locator('[data-funding-snapshot-at]').getAttribute('datetime');
  rate = -0.0005;
  await page.clock.runFor(16_000);
  await expect(btc.locator('[data-funding-strongest]')).toHaveText('-0.0500%');
  expect(requests).toBeGreaterThanOrEqual(2);
  expect(await page.locator('[data-funding-snapshot-at]').getAttribute('datetime')).not.toBe(firstClock);
  const checked = await page.locator('[data-funding-checked-at]').getAttribute('datetime');
  fail = true;
  await page.clock.runFor(16_000);
  await expect(btc.locator('[data-funding-strongest]')).toHaveText('-0.0500%');
  await expect(page.locator('.wm-funding-notice').first()).toContainText('retrying automatically');
  expect(await page.locator('[data-funding-checked-at]').getAttribute('datetime')).toBe(checked);
  await page.evaluate(() => window.panelHarness.mount('crypto-funding-watch'));
  await expect(btc).toContainText('BTC');
  fail = false; rate = 0.0001;
  await page.clock.runFor(16_000);
  await expect(btc.locator('[data-funding-strongest]')).toHaveText('+0.0100%');
  await expect(btc).toContainText('LONGS PAY');
  const before = requests;
  await page.getByRole('button', { name: 'Refresh', exact: true }).click();
  await expect.poll(() => requests).toBeGreaterThan(before);
  fail = true;
  await page.clock.fastForward(16 * 60_000);
  await expect(btc).toHaveCount(0);
});

for (const width of [1440, 390]) test(`funding search, asset mapping and venue clocks work at ${width}px`, async ({ page }) => {
  await page.setViewportSize({ width, height: 844 });
  await installDashboard(page, 'en', ['crypto-funding-watch']);
  await page.route('**/wm-api/runtime/crypto/funding-watch?*', route => route.fulfill({ json: snapshot(GENERATED_AT, -0.0004) }));
  await page.goto('/');
  const slot = page.locator('.wm-panel-slot[data-workspace-panel-id="crypto-funding-watch"]');
  await slot.scrollIntoViewIfNeeded();
  const btc = slot.locator('[data-funding-asset="BTC"]');
  await expect(btc).toContainText('Binance');
  await expect(btc).toContainText('Bybit');
  await expect(slot.locator('[data-funding-snapshot-at]')).toHaveAttribute('datetime', GENERATED_AT);
  await slot.getByRole('searchbox', { name: 'Search funding assets' }).fill('HYPE');
  await expect(slot.locator('[data-funding-asset="BTC"]')).toHaveCount(0);
  await expect(slot.locator('[data-funding-asset="HYPE"]')).toBeVisible();
  await slot.locator('.wm-funding-markets summary').click();
  await expect(slot.getByRole('link', { name: 'HYPE above $100?' })).toHaveAttribute('href', 'https://polymarket.com/event/hype-price');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
});
